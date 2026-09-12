import random
from decimal import Decimal, localcontext

import pytest

from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.liquidity.pool import (
    AMMPool,
    InsufficientLiquidityError,
    InsufficientOutputError,
    SlippageExceededError,
)

D = Decimal
TIGHT = D("1e-45")  # tolerance for 60-digit quote rounding, relative


def _close(a, b, tol=TIGHT):
    return abs(D(a) - D(b)) <= tol * max(abs(D(b)), D(1))


def _pool(coins=1_000, cash=1_000, fee="0"):
    return AMMPool(coins, cash, fee_rate=fee, initial_provider="lp1")


# --- creation & validation ------------------------------------------------------


def test_initial_pool_creation():
    pool = AMMPool(1_000, 4_000, fee_rate="0.003", initial_provider="lp1")
    assert pool.coin_reserve == 1_000
    assert pool.cash_reserve == 4_000
    assert pool.invariant == 4_000_000
    assert pool.spot_price() == 4
    assert pool.fee_rate == D("0.003")
    assert pool.total_shares == 2_000  # sqrt(k)
    assert pool.shares_of("lp1") == 2_000
    assert pool.swap_count == 0


@pytest.mark.parametrize("coins,cash", [(0, 1), (1, 0), (-1, 1), (1, -5), (0, 0)])
def test_rejects_zero_or_negative_reserves(coins, cash):
    with pytest.raises(ValueError):
        AMMPool(coins, cash)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_rejects_non_finite_reserves(bad):
    with pytest.raises(ValueError):
        AMMPool(bad, 1)


@pytest.mark.parametrize("fee", ["-0.001", "1", "1.5", 2.0, -1])
def test_rejects_invalid_fee(fee):
    with pytest.raises(ValueError):
        AMMPool(1, 1, fee_rate=fee)


def test_accepts_boundary_fees():
    assert AMMPool(1, 1, fee_rate=0).fee_rate == 0
    assert AMMPool(1, 1, fee_rate="0.999").fee_rate == D("0.999")


def test_state_snapshot():
    pool = _pool(fee="0.01")
    pool.buy(100)
    state = pool.state()
    assert state.coin_reserve == pool.coin_reserve
    assert state.cash_reserve == pool.cash_reserve
    assert state.invariant == pool.invariant
    assert state.spot_price == pool.spot_price()
    assert state.fees_collected_cash == 1
    assert state.swap_count == 1


# --- swap mechanics -------------------------------------------------------------


def test_buy_swap_moves_reserves_along_the_curve():
    pool = _pool()
    result = pool.buy(1_000)
    assert result.side == "buy"
    assert result.amount_in == 1_000
    assert result.amount_out == 500
    assert (pool.coin_reserve, pool.cash_reserve) == (500, 2_000)
    assert result.spot_price_before == 1
    assert result.spot_price_after == 4
    assert result.execution_price == 2
    assert result.price_impact == 3
    assert result.slippage == 1
    assert pool.invariant == 1_000_000


def test_sell_swap_moves_reserves_along_the_curve():
    pool = _pool()
    result = pool.sell(1_000)
    assert result.side == "sell"
    assert result.amount_out == 500
    assert (pool.coin_reserve, pool.cash_reserve) == (2_000, 500)
    assert result.spot_price_after == D("0.25")
    assert result.execution_price == D("0.5")
    assert result.price_impact == D("-0.75")
    assert result.slippage == D("0.5")
    assert pool.invariant == 1_000_000


def test_quotes_do_not_change_the_pool_and_match_execution():
    pool = _pool(fee="0.003")
    before = pool.state()
    buy_quote, sell_quote = pool.quote_buy(123), pool.quote_sell(45)
    assert pool.state() == before
    assert pool.buy(123) == buy_quote


def test_buy_increases_price_and_sell_decreases_price():
    pool = _pool(fee="0.003")
    p0 = pool.spot_price()
    buy = pool.buy(50)
    assert pool.spot_price() > p0
    assert buy.price_impact > 0
    assert pool.cash_reserve > 1_000 and pool.coin_reserve < 1_000
    p1 = pool.spot_price()
    sell = pool.sell(80)
    assert pool.spot_price() < p1
    assert sell.price_impact < 0


def test_spot_price_follows_constant_product_formula():
    pool = _pool(coins=2_000, cash=500)
    with localcontext(prec=80):
        for cash_in in (10, 100, 1_000):
            q = pool.quote_buy(cash_in)
            expected = pool.spot_price() * (1 + D(cash_in) / 500) ** 2
            assert _close(q.spot_price_after, expected)
        for coins_in in (10, 100, 1_000):
            q = pool.quote_sell(coins_in)
            expected = pool.spot_price() / (1 + D(coins_in) / 2_000) ** 2
            assert _close(q.spot_price_after, expected)


def test_execution_price_lies_between_spot_before_and_after_without_fee():
    pool = _pool()
    buy = pool.quote_buy(300)
    assert buy.spot_price_before < buy.execution_price < buy.spot_price_after
    sell = pool.quote_sell(300)
    assert sell.spot_price_after < sell.execution_price < sell.spot_price_before


def test_larger_trades_have_disproportionately_greater_impact_and_slippage():
    pool = _pool(coins=100_000, cash=100_000, fee="0.003")
    quotes = [pool.quote_buy(size) for size in (10, 100, 1_000, 10_000)]
    impacts = [q.price_impact for q in quotes]
    slippages = [q.slippage for q in quotes]
    assert impacts == sorted(impacts) and len(set(impacts)) == 4
    assert slippages == sorted(slippages) and len(set(slippages)) == 4
    assert impacts[3] / impacts[2] > 10  # convex, not linear
    assert pool.quote_sell(10_000).price_impact < pool.quote_sell(1_000).price_impact < 0


def test_slippage_matches_closed_form():
    pool = _pool(coins=4_000, cash=9_000, fee="0.003")
    buy = pool.quote_buy(900)
    sell = pool.quote_sell(1_000)
    with localcontext(prec=80):
        assert _close(buy.slippage, buy.amount_in_after_fee / 9_000)
        net = sell.amount_in_after_fee
        assert _close(sell.slippage, net / (4_000 + net))


def test_multiple_sequential_swaps_compose_exactly_without_fee():
    one_shot = _pool().buy(600).amount_out
    split = _pool()
    total = split.buy(100).amount_out + split.buy(200).amount_out + split.buy(300).amount_out
    assert _close(total, one_shot)


def test_invariant_never_decreases_over_many_swaps():
    pool = _pool(coins=50_000, cash=80_000, fee="0.003")
    rng = random.Random(11)
    for _ in range(1_000):
        k_before = pool.invariant
        if rng.random() < 0.5:
            pool.buy(D(rng.uniform(0.001, 5_000)))
        else:
            pool.sell(D(rng.uniform(0.001, 5_000)))
        assert pool.invariant >= k_before
        assert pool.coin_reserve > 0 and pool.cash_reserve > 0


def test_zero_fee_keeps_invariant_constant_up_to_pool_favoring_rounding():
    pool = _pool(coins=3_000, cash=7_000)
    k = pool.invariant
    for size in ("13.7", "0.25", "999.1"):
        pool.buy(size)
        pool.sell(size)
    assert pool.invariant >= k
    assert (pool.invariant - k) / k < D("1e-50")


# --- fees -----------------------------------------------------------------------


def test_buy_fee_is_charged_in_cash_and_kept_in_reserves():
    pool = _pool(fee="0.003")
    result = pool.buy(100)
    assert result.fee == D("0.3")
    assert result.fee_asset == "cash"
    assert result.amount_in_after_fee == D("99.7")
    assert pool.cash_reserve == 1_100  # full input, fee included
    assert pool.fees_collected_cash == D("0.3")
    fee_free = _pool().quote_buy(D("99.7"))
    assert result.amount_out == fee_free.amount_out


def test_sell_fee_is_charged_in_coins():
    pool = _pool(fee="0.01")
    result = pool.sell(200)
    assert result.fee == 2
    assert result.fee_asset == "coin"
    assert pool.coin_reserve == 1_200
    assert pool.fees_collected_coins == 2


def test_fees_make_output_smaller_and_grow_invariant():
    no_fee, with_fee = _pool(), _pool(fee="0.003")
    assert with_fee.quote_buy(500).amount_out < no_fee.quote_buy(500).amount_out
    k = with_fee.invariant
    with_fee.buy(500)
    with_fee.sell(300)
    assert with_fee.invariant > k


def test_fee_makes_round_trip_lose_money():
    pool = _pool(fee="0.003")
    coins = pool.buy(100).amount_out
    cash_back = pool.sell(coins).amount_out
    assert cash_back < 100


# --- slippage protection and delivery caps ------------------------------------------


def test_min_output_protects_against_slippage_and_leaves_pool_untouched():
    pool = _pool(fee="0.003")
    before = pool.state()
    quote = pool.quote_buy(100)
    with pytest.raises(SlippageExceededError):
        pool.buy(100, min_coins_out=quote.amount_out + D("0.0001"))
    with pytest.raises(SlippageExceededError):
        pool.sell(100, min_cash_out=pool.quote_sell(100).amount_out * 2)
    assert pool.state() == before
    assert pool.buy(100, min_coins_out=quote.amount_out).amount_out == quote.amount_out


def test_delivering_less_than_quote_keeps_remainder_in_pool():
    pool = _pool()
    quote = pool.quote_buy(100)
    taken = quote.amount_out - D("0.5")
    result = pool.buy(100, coins_out=taken)
    assert result.amount_out == taken
    assert pool.coin_reserve == EXACT.subtract(D(1_000), taken)
    assert pool.invariant > 1_000_000


def test_delivering_more_than_quote_or_nothing_is_rejected():
    pool = _pool()
    quote = pool.quote_buy(100)
    with pytest.raises(ValueError):
        pool.buy(100, coins_out=quote.amount_out + D("1e-30"))
    with pytest.raises(ValueError):
        pool.buy(100, coins_out=0)


# --- edge cases -------------------------------------------------------------------


@pytest.mark.parametrize("amount", [0, -1, "-0.5"])
def test_zero_or_negative_trade_rejected(amount):
    pool = _pool()
    with pytest.raises(ValueError):
        pool.quote_buy(amount)
    with pytest.raises(ValueError):
        pool.sell(amount)


def test_extremely_small_trade_still_executes_exactly():
    pool = _pool()
    result = pool.buy("1e-30")
    assert result.amount_out > 0
    assert _close(result.amount_out, D("1e-30"), tol=D("1e-20"))


def test_trade_too_small_to_produce_output_is_rejected():
    pool = _pool()
    before = pool.state()
    with pytest.raises(InsufficientOutputError):
        pool.buy("1e-80")
    with pytest.raises(InsufficientOutputError):
        pool.sell("1e-80")
    assert pool.state() == before


def test_extremely_large_buy_cannot_take_the_whole_coin_reserve():
    pool = _pool()
    result = pool.buy(D("1e15"))
    assert result.amount_out < 1_000
    assert pool.coin_reserve > 0
    assert pool.spot_price() > D("1e20")


def test_buying_almost_all_available_coins():
    pool = _pool()
    result = pool.buy(999_000)  # needs 999× the cash reserve to take 99.9%
    assert result.amount_out / 1_000 > D("0.998")
    assert 0 < pool.coin_reserve < 2
    assert pool.invariant >= 1_000_000


def test_selling_until_cash_reserve_is_nearly_empty():
    pool = _pool()
    result = pool.sell(D("1e12"))
    assert result.amount_out < 1_000
    assert 0 < pool.cash_reserve < D("1e-5")
    assert 0 < pool.spot_price() < D("1e-14")


def test_pool_cannot_pay_out_more_than_its_reserves():
    pool = _pool(coins=10, cash=10)
    for _ in range(50):
        pool.buy(D("1e6"))
        assert pool.coin_reserve > 0
    for _ in range(50):
        pool.sell(D("1e30"))
        assert pool.cash_reserve > 0


# --- liquidity ---------------------------------------------------------------------


def test_proportional_add_mints_proportional_shares_and_keeps_price():
    pool = AMMPool(1_000, 4_000, fee_rate=0, initial_provider="lp1")
    change = pool.add_liquidity("lp2", 500, 2_000)
    assert change.shares == 1_000
    assert (pool.coin_reserve, pool.cash_reserve) == (1_500, 6_000)
    assert pool.spot_price() == 4
    assert pool.shares_of("lp2") == 1_000
    assert pool.total_shares == 3_000


def test_unbalanced_add_mints_on_smaller_side_and_donates_the_excess():
    pool = AMMPool(1_000, 4_000, fee_rate=0, initial_provider="lp1")
    change = pool.add_liquidity("lp2", 500, 5_000)
    assert change.shares == 1_000
    assert pool.cash_reserve == 9_000
    lp1 = pool.remove_liquidity("lp1", 2_000)
    assert lp1.coins == 1_000 and lp1.cash == 6_000  # lp1 gained from the donation


def test_optimal_deposit_matches_pool_ratio():
    pool = AMMPool(1_000, 4_000, initial_provider="lp1")
    assert pool.optimal_deposit(500, 5_000) == (500, 2_000)
    assert pool.optimal_deposit(500, 1_000) == (250, 1_000)


@pytest.mark.parametrize("coins,cash", [(0, 10), (10, 0), (-1, 10)])
def test_add_liquidity_rejects_non_positive_amounts(coins, cash):
    with pytest.raises(ValueError):
        _pool().add_liquidity("lp2", coins, cash)


def test_extremely_small_deposit_mints_proportionally_small_shares():
    pool = _pool()
    change = pool.add_liquidity("lp2", "1e-80", "1e-80")
    assert change.shares == D("1e-80")  # total 1000 shares × (1e-80 / 1000)
    assert pool.coin_reserve == EXACT.add(D(1_000), D("1e-80"))


def test_remove_liquidity_pays_pro_rata_reserves_and_keeps_price():
    pool = AMMPool(1_000, 4_000, fee_rate=0, initial_provider="lp1")
    pool.add_liquidity("lp2", 1_000, 4_000)
    change = pool.remove_liquidity("lp2", 1_000)
    assert (change.coins, change.cash) == (500, 2_000)
    assert pool.spot_price() == 4
    assert pool.shares_of("lp2") == 1_000


def test_liquidity_round_trip_conserves_exactly():
    pool = _pool(coins=1_234, cash=5_678, fee="0.003")
    pool.buy(321)
    pool.sell(55)
    lp2_coins, lp2_cash = pool.optimal_deposit(100, 10_000)
    coins_before = EXACT.add(pool.coin_reserve, lp2_coins)
    cash_before = EXACT.add(pool.cash_reserve, lp2_cash)
    minted = pool.add_liquidity("lp2", lp2_coins, lp2_cash).shares
    out = pool.remove_liquidity("lp2", minted)
    assert EXACT.add(pool.coin_reserve, out.coins) == coins_before
    assert EXACT.add(pool.cash_reserve, out.cash) == cash_before
    assert out.coins <= lp2_coins and out.cash <= lp2_cash


def test_late_lp_cannot_capture_fees_earned_before_joining():
    pool = _pool(coins=10_000, cash=10_000, fee="0.01")
    for _ in range(20):
        pool.sell(pool.buy(1_000).amount_out)  # round trips pay fees
    coins, cash = pool.optimal_deposit(1_000, 1_000_000)
    minted = pool.add_liquidity("late", coins, cash).shares
    out = pool.remove_liquidity("late", minted)
    assert out.coins <= coins and out.cash <= cash


def test_fees_accrue_to_existing_lps():
    pool = _pool(coins=10_000, cash=10_000, fee="0.01")
    value_per_share = EXACT.multiply(pool.invariant, 1).sqrt() / pool.total_shares
    for _ in range(20):
        pool.sell(pool.buy(1_000).amount_out)
    assert pool.invariant.sqrt() / pool.total_shares > value_per_share


def test_removing_more_than_owned_is_rejected():
    pool = _pool()
    pool.add_liquidity("lp2", 100, 100)
    with pytest.raises(InsufficientLiquidityError):
        pool.remove_liquidity("lp2", pool.shares_of("lp2") + 1)
    with pytest.raises(InsufficientLiquidityError):
        pool.remove_liquidity("nobody", 1)
    with pytest.raises(ValueError):
        pool.remove_liquidity("lp2", 0)


def test_removing_the_last_liquidity_is_rejected():
    pool = _pool()
    before = pool.state()
    with pytest.raises(InsufficientLiquidityError):
        pool.remove_liquidity("lp1", pool.total_shares)
    assert pool.state() == before


def test_randomized_operations_never_produce_negative_reserves_and_conserve_exactly():
    rng = random.Random(7)
    pool = _pool(coins=10_000, cash=25_000, fee="0.003")
    outside_coins, outside_cash = D(0), D(0)  # net flows into the pool
    start_coins, start_cash = pool.coin_reserve, pool.cash_reserve
    for _ in range(1_500):
        roll = rng.random()
        try:
            if roll < 0.4:
                r = pool.buy(D(rng.uniform(0, 3_000)))
                outside_cash, outside_coins = EXACT.add(outside_cash, r.amount_in), EXACT.subtract(outside_coins, r.amount_out)
            elif roll < 0.8:
                r = pool.sell(D(rng.uniform(0, 3_000)))
                outside_coins, outside_cash = EXACT.add(outside_coins, r.amount_in), EXACT.subtract(outside_cash, r.amount_out)
            elif roll < 0.9:
                coins, cash = pool.optimal_deposit(D(rng.uniform(1, 500)), D(rng.uniform(1, 500)))
                pool.add_liquidity("lp2", coins, cash)
                outside_coins, outside_cash = EXACT.add(outside_coins, coins), EXACT.add(outside_cash, cash)
            elif pool.shares_of("lp2") > 0:
                r = pool.remove_liquidity("lp2", pool.shares_of("lp2") * D(rng.uniform(0.1, 1)))
                outside_coins, outside_cash = EXACT.subtract(outside_coins, r.coins), EXACT.subtract(outside_cash, r.cash)
        except InsufficientOutputError:
            pass
        assert pool.coin_reserve > 0 and pool.cash_reserve > 0
    assert pool.coin_reserve == EXACT.add(start_coins, outside_coins)
    assert pool.cash_reserve == EXACT.add(start_cash, outside_cash)


def test_identical_operation_sequences_are_deterministic():
    def run():
        pool = _pool(fee="0.003")
        for size in ("12.5", "300", "0.001", "77"):
            pool.buy(size)
            pool.sell(size)
        pool.add_liquidity("lp2", 10, 10)
        return pool.state()

    assert run() == run()
