"""CoinSimulator pricing modes: random-walk compatibility and AMM integration.

GOLDEN_FULL_* / *_SHA256 were captured from the code *before* the AMM phase
(whale + all five traders, random walk, 60 ticks), pinning that path bit
for bit.
"""

import hashlib
from decimal import Decimal

import pytest

from crypto_simulator.core.coin_simulator import RESERVE_PROVIDER_ID, CoinSimulator, PricingMode
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.strategies import RetailTrader
from tests.core.test_coin_simulator_traders import (
    GOLDEN_PLAIN_PRICES,
    SUPPLY,
    _all_five,
    _coin,
    _golden_whale,
    _market_view,
    _RecordingTrader,
)

GOLDEN_FULL_PRICES = [2.08548978489927, 2.2261367229779205, 2.194407438594872, 2.291807635537021, 2.319823773159836, 2.536538831615878, 2.648539714817786, 2.661368972291802, 2.6479354252175122, 2.755599021301462, 2.979968220473425, 2.9837223630915135, 3.0187264500522413, 3.0618036142493583, 3.038973415322526, 3.192287946229443, 2.8101809786278404, 2.580386844661915, 2.6120575933121706, 2.4452208333289724, 2.424575847399612, 2.413114610659542, 2.4404600271403663, 2.3328456680741834, 2.6277009061014547, 2.681673859929948, 2.658474663457008, 2.873403501248678, 2.8747133746163223, 2.76060379021809, 2.7263760478266748, 2.504903804249611, 2.320043600596527, 2.1395325395201295, 1.9702455342914091, 1.9948953843139883, 2.161851131187004, 2.330814295003446, 2.3574875656399352, 2.5675431654655005, 2.695289746213292, 2.716049831084732, 2.6981761453680937, 2.6723695114122035, 2.2927198107616604, 2.185379185522829, 2.17283158943332, 2.3377356738068835, 2.311093032320279, 2.153984005718585, 2.1020080419462834, 2.1602267883122406, 2.333290484130505, 2.208341003386721, 2.195425590024125, 2.020630374753937, 1.953909288345756, 2.0620697299192217, 2.2563624413263814, 2.468552830635459]
GOLDEN_FULL_FILLS_SHA256 = "b757e1d8bc5daf1e161aca89f72703024325b5b8a76f2c3539c4d766f9207793"
GOLDEN_FULL_VOLUMES_SHA256 = "c568b0a8e6c4e710a73826684496fd9139fc8c6eb05b8b608860b2363216d076"
GOLDEN_FULL_WHALES_SHA256 = "0be8c50e9152a59f3ca8efc5b1e07934392fe830080b96e458d8896edf6a2372"
GOLDEN_FULL_WALLETS = [("retail", 6121.96179892281, 5834.780583242333, 2.2191551128427074), ("momentum", 25821.078765986385, 11328.323534904339, 2.3578950651661503), ("dip", 0.019073486328125, 14797.460394904558, 2.703165263431791), ("panic", 7813.425211737642, 33464.23479554769, 2.2463328440608765), ("holder", 6328.125, 66071.48549529593, 2.023140148854637)]
GOLDEN_FULL_RESERVE = (563915.3901498667, 768503.7151961047)


def _sha(obj) -> str:
    return hashlib.sha256(repr(obj).encode()).hexdigest()


def _exact_sum(values) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = EXACT.add(total, value)
    return total


def _amm(traders=None, pool_coins=100_000.0, reserve_cash=2_000_000.0, fee="0.003", **kwargs):
    return CoinSimulator(
        _coin(), seed=3, traders=traders, reserve_cash=reserve_cash,
        pricing_mode="amm", amm_pool_coins=pool_coins, amm_fee_rate=fee, **kwargs,
    )


def _buyer(trader_id="buyer", cash=100_000.0, max_size=5_000.0):
    return RetailTrader(
        trader_id, starting_cash=cash, buy_bias=1.0, trade_probability=1.0,
        max_trade_size=max_size, risk_tolerance=1.0, seed=1,
    )


def _seller(coins=100_000.0, max_size=5_000.0):
    return RetailTrader(
        "seller", starting_coins=coins, buy_bias=0.0, trade_probability=1.0,
        max_trade_size=max_size, risk_tolerance=1.0, seed=1,
    )


# --- random-walk mode stays exactly as before ------------------------------------------


def test_default_pricing_mode_is_random_walk_without_a_pool():
    sim = CoinSimulator(_coin(), seed=1)
    assert sim.pricing_mode is PricingMode.RANDOM_WALK
    assert sim.pool is None
    assert [t.price for t in sim.run(10)] == GOLDEN_PLAIN_PRICES


@pytest.mark.parametrize("mode", [None, "random_walk", PricingMode.RANDOM_WALK])
def test_full_random_walk_run_is_bit_identical_to_pre_amm_code(mode):
    kwargs = {} if mode is None else {"pricing_mode": mode}
    sim = CoinSimulator(
        _coin(), seed=3, whales=[_golden_whale()], traders=_all_five(), reserve_cash=500_000.0, **kwargs
    )
    ticks = sim.run(60)
    fills = [
        (t.tick, f.trader_id, f.side.value, f.requested_quantity, f.quantity, f.price, f.notional)
        for t in ticks for f in t.trader_trades
    ]
    whales = [(t.tick, w.side, w.quantity, w.price_impact) for t in ticks for w in t.whale_trades]
    assert [t.price for t in ticks] == GOLDEN_FULL_PRICES
    assert _sha([t.volume for t in ticks]) == GOLDEN_FULL_VOLUMES_SHA256
    assert _sha(fills) == GOLDEN_FULL_FILLS_SHA256
    assert _sha(whales) == GOLDEN_FULL_WHALES_SHA256
    assert [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost) for t in sim.traders] == GOLDEN_FULL_WALLETS
    assert (sim.reserve.cash, sim.reserve.coins) == GOLDEN_FULL_RESERVE
    assert all(t.pool_state is None for t in ticks)
    assert all(f.swap is None for t in ticks for f in t.trader_trades)


# --- AMM construction ------------------------------------------------------------------


def test_amm_pool_is_seeded_by_the_reserve_at_the_starting_price():
    rw = CoinSimulator(_coin(), seed=3, traders=_all_five(), reserve_cash=2_000_000.0)
    sim = _amm(traders=_all_five())
    assert sim.pricing_mode is PricingMode.AMM
    assert sim.pool.coin_reserve == 100_000
    assert sim.pool.cash_reserve == 200_000
    assert sim.pool.spot_price() == 2
    assert sim.current_price == 2.0
    assert sim.pool.shares_of(RESERVE_PROVIDER_ID) == sim.pool.total_shares
    assert sim.reserve.coins == rw.reserve.coins - 100_000
    assert sim.accounting_totals() == rw.accounting_totals()


def test_amm_default_pool_size_pairs_as_much_as_the_reserve_can():
    sim = CoinSimulator(_coin(), seed=1, traders=_all_five(), reserve_cash=300_000.0, pricing_mode="amm")
    assert sim.pool.coin_reserve == 150_000  # limited by 300k cash at price 2
    assert sim.pool.cash_reserve == 300_000
    assert sim.reserve.cash == 0.0


def test_amm_mode_rejects_whales_explicitly():
    with pytest.raises(ValueError, match="Whales are not supported"):
        _amm(whales=[_golden_whale()])


def test_amm_mode_rejects_unknown_mode_and_bad_pool_config():
    with pytest.raises(ValueError, match="Unknown pricing_mode"):
        CoinSimulator(_coin(), pricing_mode="order_book")
    with pytest.raises(ValueError, match="unallocated"):
        _amm(pool_coins=SUPPLY * 2)
    with pytest.raises(ValueError, match="raise the reserve cash"):
        _amm(pool_coins=100_000.0, reserve_cash=1_000.0)
    with pytest.raises(ValueError):
        _amm(fee="1.5")


# --- AMM pricing ------------------------------------------------------------------------


def test_amm_price_does_not_random_walk_without_trades():
    sim = _amm(traders=_all_five(trade_probability=0.0))
    ticks = sim.run(50)
    assert all(t.price == 2.0 for t in ticks)
    assert all(t.volume == 0 for t in ticks)
    assert sim.clock.tick == 50
    assert [t.pool_state.swap_count for t in ticks] == [0] * 50


def test_amm_buyer_pushes_price_up_and_seller_pushes_it_down():
    up = _amm(traders=[_buyer()]).run(10)
    assert [t.price for t in up] == sorted(t.price for t in up)
    assert up[-1].price > 2.0
    down = _amm(traders=[_seller()]).run(10)
    assert [t.price for t in down] == sorted((t.price for t in down), reverse=True)
    assert down[-1].price < 2.0


def test_amm_tick_price_is_pool_spot_price_and_synced_to_engine():
    sim = _amm(traders=[_buyer()])
    tick = sim.step()
    trade = tick.trader_trades[0]
    assert tick.price == float(sim.pool.spot_price())
    assert tick.price == float(trade.swap.spot_price_after)
    assert sim.current_price == tick.price
    assert tick.market_cap == pytest.approx(tick.price * SUPPLY)
    assert tick.pool_state == sim.pool.state()


def test_amm_trades_carry_swap_details_and_fees_are_collected():
    sim = _amm(traders=[_buyer(), _seller()])
    ticks = sim.run(5)
    buys = [f for t in ticks for f in t.trader_trades if f.side is TradeAction.BUY]
    sells = [f for t in ticks for f in t.trader_trades if f.side is TradeAction.SELL]
    assert buys and sells
    for fill in buys + sells:
        assert fill.swap is not None
        assert fill.swap.fee == EXACT.multiply(fill.swap.amount_in, Decimal("0.003"))
        assert fill.swap.slippage > 0
        assert fill.price == float(fill.swap.execution_price)
    assert sim.pool.fees_collected_cash == _exact_sum(f.swap.fee for f in buys)
    assert sim.pool.fees_collected_coins == _exact_sum(f.swap.fee for f in sells)


def test_amm_volume_is_the_coins_actually_swapped():
    ticks = _amm(traders=[_buyer(), _seller()]).run(10)
    for tick in ticks:
        assert tick.volume == pytest.approx(sum(f.quantity for f in tick.trader_trades))
        assert tick.volume == pytest.approx(sum(float(f.swap.coins_traded) for f in tick.trader_trades))


def test_amm_price_impact_scales_with_pool_depth():
    shallow = _amm(traders=[_buyer()], pool_coins=50_000.0).step()
    deep = _amm(traders=[_buyer()], pool_coins=400_000.0).step()
    assert shallow.price > deep.price > 2.0


def test_amm_traders_later_in_the_list_execute_at_worse_prices():
    first, second = _buyer("first"), _buyer("second")
    tick = _amm(traders=[first, second]).step()
    a, b = tick.trader_trades
    assert a.notional == b.notional == 10_000.0
    assert b.quantity < a.quantity
    assert b.price > a.price


def test_amm_strategies_decide_on_pre_trade_spot_and_close_history():
    recorder = _RecordingTrader("rec", trade_probability=1.0, seed=1)
    sim = _amm(traders=[_buyer(), recorder])
    ticks = sim.run(4)
    contexts = recorder.contexts
    assert contexts[0].price == 2.0
    assert contexts[0].price_history == (2.0,)
    for context, previous in zip(contexts[1:], ticks):
        assert context.price == previous.price  # nothing moves the pool between ticks
        assert context.price_history[-1] == previous.price


# --- AMM accounting ---------------------------------------------------------------------


def test_amm_insufficient_cash_and_coins_never_go_negative():
    broke_buyer = _buyer(cash=12_345.0, max_size=1e9)
    small_seller = RetailTrader(
        "seller", starting_coins=777.0, buy_bias=0.0, trade_probability=1.0,
        max_trade_size=1e9, risk_tolerance=1.0, seed=1,
    )
    sim = _amm(traders=[broke_buyer, small_seller])
    sim.run(5)
    assert broke_buyer.wallet.cash == 0.0
    assert small_seller.wallet.coins == 0.0
    assert sum(f.notional for t in sim.history for f in t.trader_trades if f.trader_id == "buyer") == 12_345.0


def test_amm_long_run_conserves_coins_and_cash_exactly():
    sim = _amm(traders=_all_five())
    totals_before = sim.accounting_totals()
    k_previous = sim.pool.invariant
    for _ in range(500):
        sim.step()
        assert sim.pool.invariant >= k_previous
        k_previous = sim.pool.invariant
        assert sim.pool.coin_reserve > 0 and sim.pool.cash_reserve > 0
        for wallet in (sim.reserve, *(t.wallet for t in sim.traders)):
            assert wallet.cash >= 0.0 and wallet.coins >= 0.0
    assert sim.accounting_totals() == totals_before
    strategies = {f.strategy for t in sim.history for f in t.trader_trades}
    assert strategies == {"retail", "momentum", "dip_buyer", "panic_seller", "long_term_holder"}


def test_amm_runs_are_deterministic():
    def run():
        sim = _amm(traders=_all_five())
        ticks = sim.run(200)
        return (
            _market_view(ticks),
            [t.pool_state for t in ticks],
            [t.wallet for t in sim.traders],
            sim.reserve,
        )

    assert run() == run()


def test_amm_and_random_walk_modes_diverge_from_the_same_start():
    rw = CoinSimulator(_coin(), seed=3, traders=_all_five(), reserve_cash=2_000_000.0).run(30)
    amm = _amm(traders=_all_five()).run(30)
    assert [t.price for t in rw] != [t.price for t in amm]
