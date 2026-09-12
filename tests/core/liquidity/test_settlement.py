import random
from decimal import Decimal

import pytest

from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.liquidity.pool import AMMPool
from crypto_simulator.core.liquidity.settlement import (
    execute_decision_via_pool,
    execute_wash_via_pool,
    planned_credit,
    planned_debit,
    seed_pool_from_wallet,
)
from crypto_simulator.core.traders.base import TradeAction, TradeDecision
from crypto_simulator.core.traders.strategies import RetailTrader
from crypto_simulator.models.wallet import Wallet

D = Decimal


def _trader(cash=0.0, coins=0.0, trader_id="t"):
    return RetailTrader(trader_id, starting_cash=cash, starting_coins=coins)


def _buy(quantity):
    return TradeDecision(TradeAction.BUY, quantity, "test buy")


def _sell(quantity):
    return TradeDecision(TradeAction.SELL, quantity, "test sell")


def _totals(pool, *wallets):
    coins, cash = pool.coin_reserve, pool.cash_reserve
    for w in wallets:
        coins, cash = EXACT.add(coins, D(w.coins)), EXACT.add(cash, D(w.cash))
    return coins, cash


# --- float/Decimal boundary helpers ---------------------------------------------


def test_planned_debit_reports_exact_amount_removed():
    after, removed = planned_debit(0.3, 0.1)
    assert after == 0.3 - 0.1
    assert EXACT.add(D(after), removed) == D(0.3)
    assert planned_debit(5.0, 5.0) == (0.0, D(5.0))


def test_planned_credit_never_exceeds_limit():
    rng = random.Random(3)
    for _ in range(5_000):
        balance = rng.choice([0.0, rng.uniform(0, 1), rng.uniform(0, 1e7), rng.uniform(1e6, 1e9)])
        limit = D(rng.uniform(0, 1e6)) / D(rng.choice([1, 3, 7, 1_000_003]))
        deposit, increase = planned_credit(balance, limit)
        assert increase <= limit
        assert EXACT.subtract(D(balance + deposit), D(balance)) == increase
        assert deposit >= 0


def test_planned_credit_returns_nothing_for_sub_ulp_amounts():
    assert planned_credit(1e9, D("1e-12")) == (0.0, D(0))
    assert planned_credit(1.0, D(0)) == (0.0, D(0))


def test_seed_pool_from_wallet_moves_exact_amounts():
    wallet = Wallet(cash=1_000.1, coins=500.3)
    before = (D(wallet.coins), D(wallet.cash))
    pool = seed_pool_from_wallet(wallet, coins=200.1, cash=400.7, fee_rate="0.003", provider_id="lp")
    assert pool.shares_of("lp") == pool.total_shares
    assert EXACT.add(pool.coin_reserve, D(wallet.coins)) == before[0]
    assert EXACT.add(pool.cash_reserve, D(wallet.cash)) == before[1]


def test_seed_pool_rejects_amounts_the_wallet_lacks():
    with pytest.raises(ValueError):
        seed_pool_from_wallet(Wallet(cash=10.0, coins=10.0), coins=11.0, cash=5.0, fee_rate=0, provider_id="lp")
    with pytest.raises(ValueError):
        seed_pool_from_wallet(Wallet(cash=10.0, coins=10.0), coins=5.0, cash=11.0, fee_rate=0, provider_id="lp")


# --- trader execution through the pool ------------------------------------------


def test_buy_spends_budget_at_reference_price_and_receives_curve_output():
    pool = AMMPool(10_000, 20_000, fee_rate="0.003")
    trader = _trader(cash=5_000.0)
    quote = pool.quote_buy(D(1_000.0))
    trade = execute_decision_via_pool(trader, _buy(500.0), pool, reference_price=2.0)
    assert trade.side is TradeAction.BUY
    assert trade.notional == 1_000.0
    assert trader.wallet.cash == 4_000.0
    assert trade.quantity == pytest.approx(float(quote.amount_out), rel=1e-15)
    assert trade.quantity < 500.0  # slippage + fee: fewer coins than requested
    assert trade.swap.fee == D("3.000")
    assert trade.price == pytest.approx(float(trade.swap.execution_price))
    assert trader.wallet.average_cost == pytest.approx(1_000.0 / trade.quantity)


def test_sell_swaps_requested_coins_for_curve_output():
    pool = AMMPool(10_000, 20_000, fee_rate="0.003")
    trader = _trader(coins=1_000.0)
    quote = pool.quote_sell(D(400.0))
    trade = execute_decision_via_pool(trader, _sell(400.0), pool)
    assert trade.quantity == 400.0
    assert trader.wallet.coins == 600.0
    assert trader.wallet.cash == pytest.approx(float(quote.amount_out), rel=1e-15)
    assert trade.swap.fee_asset == "coin"


def test_every_fill_conserves_coins_and_cash_exactly():
    pool = AMMPool(10_000.0, 20_000.0, fee_rate="0.003")
    trader = _trader(cash=7_777.77, coins=3_333.33)
    before = _totals(pool, trader.wallet)
    execute_decision_via_pool(trader, _buy(123.456), pool)
    assert _totals(pool, trader.wallet) == before
    execute_decision_via_pool(trader, _sell(2_000.1), pool)
    assert _totals(pool, trader.wallet) == before


def test_insufficient_cash_spends_exactly_all_cash_and_never_goes_negative():
    pool = AMMPool(10_000, 10_000, fee_rate="0.003")
    trader = _trader(cash=250.0)
    trade = execute_decision_via_pool(trader, _buy(1_000_000.0), pool)
    assert trade.notional == 250.0
    assert trader.wallet.cash == 0.0
    assert trade.requested_quantity == 1_000_000.0
    assert trade.quantity < 250.0


def test_buy_with_no_cash_does_nothing():
    pool = AMMPool(10_000, 10_000)
    trader = _trader(cash=0.0)
    before = pool.state()
    assert execute_decision_via_pool(trader, _buy(10.0), pool) is None
    assert pool.state() == before


def test_insufficient_coins_sells_exactly_all_holdings():
    pool = AMMPool(10_000, 10_000, fee_rate="0.003")
    trader = _trader(coins=75.5)
    trader.wallet.average_cost = 1.0
    trade = execute_decision_via_pool(trader, _sell(10_000.0), pool)
    assert trade.quantity == 75.5
    assert trader.wallet.coins == 0.0
    assert trader.wallet.average_cost == 0.0


def test_sell_with_no_coins_does_nothing():
    pool = AMMPool(10_000, 10_000)
    before = pool.state()
    assert execute_decision_via_pool(_trader(cash=100.0), _sell(10.0), pool) is None
    assert pool.state() == before


def test_cannot_buy_more_coins_than_the_pool_holds():
    pool = AMMPool(1_000, 1_000, fee_rate="0.003")
    whale_sized = _trader(cash=1e12)
    trade = execute_decision_via_pool(whale_sized, _buy(5_000.0), pool, reference_price=1e6)
    assert trade.quantity < 1_000
    assert pool.coin_reserve > 0
    assert _totals(pool, whale_sized.wallet) == (EXACT.add(D(1_000), D(0)), EXACT.add(D(1_000), D(1e12)))


def test_selling_into_a_nearly_empty_cash_reserve_still_pays_out_and_leaves_cash():
    pool = AMMPool(1_000, 1_000, fee_rate="0")
    trader = _trader(coins=1e15)
    trade = execute_decision_via_pool(trader, _sell(1e15), pool)
    assert 0 < trade.notional < 1_000
    assert pool.cash_reserve > 0
    assert trader.wallet.coins == 0.0


def test_trade_that_rounds_to_nothing_is_rejected_without_side_effects():
    pool = AMMPool(1_000, 1_000)
    rich = _trader(cash=1.0, coins=1e12)
    before = (pool.state(), rich.wallet.cash, rich.wallet.coins)
    # 1e-15 coins can't be represented as a change to a 1e12 balance.
    assert execute_decision_via_pool(rich, _buy(1e-15), pool) is None
    assert (pool.state(), rich.wallet.cash, rich.wallet.coins) == before


def test_nearly_drained_pool_pays_a_tiny_but_real_amount():
    pool = AMMPool(1_000, D("1e-60"), fee_rate="0")
    trader = _trader(coins=1.0)
    before = _totals(pool, trader.wallet)
    trade = execute_decision_via_pool(trader, _sell(1.0), pool)
    assert 0 < trader.wallet.cash < 1e-60
    assert pool.cash_reserve > 0
    assert _totals(pool, trader.wallet) == before
    assert trade.quantity == 1.0


def test_pool_that_cannot_satisfy_a_sell_rejects_it():
    # Payout (~1e-63) is too small to change a 1.0 cash balance at all.
    drained = AMMPool(1_000, D("1e-60"), fee_rate="0")
    trader = _trader(cash=1.0, coins=1.0)
    before = drained.state()
    assert execute_decision_via_pool(trader, _sell(1.0), drained) is None
    assert drained.state() == before
    assert (trader.wallet.cash, trader.wallet.coins) == (1.0, 1.0)

    # Output rounds to zero inside the pool itself.
    deep = AMMPool(1e6, 1e6, fee_rate="0")
    dust_seller = _trader(coins=1e-90)
    assert execute_decision_via_pool(dust_seller, _sell(1e-90), deep) is None
    assert dust_seller.wallet.coins == 1e-90
    assert deep.swap_count == 0


def test_hold_does_nothing():
    pool = AMMPool(1_000, 1_000)
    assert execute_decision_via_pool(_trader(cash=10.0, coins=10.0), TradeDecision.hold(), pool) is None
    assert pool.swap_count == 0


def test_randomized_trading_conserves_exactly_and_never_goes_negative():
    rng = random.Random(2024)
    pool = AMMPool(50_000.0, 50_000.0, fee_rate="0.003")
    traders = [_trader(cash=rng.uniform(0, 20_000), coins=rng.uniform(0, 20_000), trader_id=f"t{i}") for i in range(6)]
    before = _totals(pool, *(t.wallet for t in traders))
    for _ in range(3_000):
        trader = rng.choice(traders)
        decision = (_buy if rng.random() < 0.5 else _sell)(rng.uniform(0, 8_000))
        execute_decision_via_pool(trader, decision, pool, reference_price=float(pool.spot_price()))
        for t in traders:
            assert t.wallet.cash >= 0.0 and t.wallet.coins >= 0.0
        assert pool.coin_reserve > 0 and pool.cash_reserve > 0
    assert _totals(pool, *(t.wallet for t in traders)) == before
    assert pool.swap_count > 2_000


# --- wash trades ------------------------------------------------------------------------


def _wash(quantity):
    return TradeDecision(TradeAction.WASH, quantity, "wash trade")


def test_wash_through_the_pool_is_two_swaps_that_return_the_coins():
    pool = AMMPool(D(100_000), D(200_000), fee_rate="0.003")
    trader = _trader(cash=10_000.0)
    before = _totals(pool, trader.wallet)
    coins_before, k_before, spot_before = pool.coin_reserve, pool.invariant, pool.spot_price()
    legs = execute_wash_via_pool(trader, _wash(1_000.0), pool, reference_price=2.0)

    assert [leg.side for leg in legs] == [TradeAction.BUY, TradeAction.SELL]
    assert all(leg.wash and leg.swap is not None for leg in legs)
    assert legs[0].notional == 2_000.0
    assert legs[1].quantity == legs[0].quantity
    assert trader.wallet.coins == 0.0
    assert pool.coin_reserve == coins_before
    assert _totals(pool, trader.wallet) == before
    # The trader paid a fee on both legs (the second on coins now worth a bit
    # less than the 2,000 spent); every unit lost stayed in the pool.
    loss = EXACT.subtract(D(10_000.0), D(trader.wallet.cash))
    assert loss == EXACT.subtract(pool.cash_reserve, D(200_000))
    assert 0.003 * 2_000.0 < loss < 2 * 0.003 * 2_000.0
    assert pool.invariant > k_before
    assert pool.spot_price() > spot_before
    assert pool.swap_count == 2


def test_fee_free_wash_through_the_pool_costs_only_rounding():
    pool = AMMPool(D(100_000), D(200_000), fee_rate="0")
    trader = _trader(cash=10_000.0)
    legs = execute_wash_via_pool(trader, _wash(1_000.0), pool, reference_price=2.0)
    assert len(legs) == 2
    assert 0.0 <= 10_000.0 - trader.wallet.cash < 1e-9


def test_wash_through_the_pool_with_no_cash_does_nothing():
    pool = AMMPool(D(100_000), D(200_000), fee_rate="0.003")
    state = pool.state()
    assert execute_wash_via_pool(_trader(coins=50.0), _wash(10.0), pool) == ()
    assert execute_wash_via_pool(_trader(cash=50.0), _wash(0.0), pool) == ()
    assert pool.state() == state


def test_pool_wash_and_plain_pool_execution_reject_each_others_decisions():
    pool = AMMPool(D(100_000), D(200_000))
    with pytest.raises(ValueError, match="execute_wash_via_pool"):
        execute_decision_via_pool(_trader(cash=10.0), _wash(1.0), pool)
    with pytest.raises(ValueError, match="expected a WASH decision"):
        execute_wash_via_pool(_trader(cash=10.0), _buy(1.0), pool)
