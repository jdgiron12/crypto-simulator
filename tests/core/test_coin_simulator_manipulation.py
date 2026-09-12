"""CoinSimulator + market-manipulation participants.

Manipulators are ordinary traders to the simulator; these tests pin what
each scheme does to price, volume and balances in both pricing modes, and
that they never disturb the existing (golden-pinned) paths.
"""

from decimal import Decimal

import pytest

from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from tests.core.test_coin_simulator_traders import _all_five, _coin, _golden_whale, _totals


def _washer(cash=50_000.0, probability=0.9):
    return WashTrader(
        "washer", starting_cash=cash, trade_probability=probability,
        max_trade_size=40_000.0, risk_tolerance=0.8, seed=99,
    )


def _pump(cash=30_000.0):
    return PumpAndDump(
        "pump", starting_cash=cash, trade_probability=1.0, max_trade_size=1e9, risk_tolerance=1.0,
        start_tick=3, accumulate_ticks=5, accumulate_share=0.3, pump_ticks=2, dump_ticks=3, seed=98,
    )


def _rw(traders, **kwargs):
    return CoinSimulator(
        _coin(), seed=3, whales=[_golden_whale()], traders=traders, reserve_cash=500_000.0, **kwargs
    )


def _amm(traders):
    return CoinSimulator(
        _coin(), seed=3, traders=traders, reserve_cash=2_000_000.0,
        pricing_mode="amm", amm_pool_coins=100_000.0,
    )


def _organic_fills(ticks):
    return [[f for f in t.trader_trades if f.trader_id != "washer"] for t in ticks]


# --- wash trading, random-walk mode ------------------------------------------------------


def test_random_walk_wash_trading_inflates_volume_without_moving_price():
    base = _rw(_all_five()).run(60)
    sim = _rw(_all_five() + [_washer()])
    ticks = sim.run(60)

    assert [t.price for t in ticks] == [t.price for t in base]
    assert _organic_fills(ticks) == [list(t.trader_trades) for t in base]
    assert [t.whale_trades for t in ticks] == [t.whale_trades for t in base]
    washed = [t for t in ticks if t.wash_volume]
    assert len(washed) > 40
    for t, b in zip(ticks, base):
        assert t.volume == pytest.approx(b.volume + t.wash_volume)
    assert all(t.wash_volume == 0 for t in base)


def test_random_walk_wash_legs_net_to_zero_and_leave_the_washer_flat():
    sim = _rw(_all_five() + [_washer()])
    coins_before, cash_before = _totals(sim)
    ticks = sim.run(60)
    for t in ticks:
        legs = [f for f in t.trader_trades if f.wash]
        assert [f.side for f in legs] in ([], [TradeAction.BUY, TradeAction.SELL])
        if legs:
            assert legs[0].quantity == legs[1].quantity
            assert legs[0].price == legs[1].price
            assert legs[0].price == pytest.approx(t.price / _impact_after_fills(sim, t), rel=1e-12)
    washer = sim.traders[-1].wallet
    assert washer.coins == pytest.approx(0.0, abs=1e-6)
    assert washer.cash == pytest.approx(50_000.0, rel=1e-12)
    assert _totals(sim) == (pytest.approx(coins_before, rel=1e-12), pytest.approx(cash_before, rel=1e-12))


def _impact_after_fills(sim, tick):
    """Price factor the tick's net organic flow applied after the fills."""
    from crypto_simulator.core.traders.execution import net_flow_price_impact

    net = sum(
        f.quantity if f.side is TradeAction.BUY else -f.quantity
        for f in tick.trader_trades if not f.wash
    )
    return net_flow_price_impact(net, sim.coin.initial_supply, sim.trader_impact_coefficient)


# --- wash trading, AMM mode --------------------------------------------------------------


def test_amm_wash_trading_pays_fees_to_the_pool_and_nudges_price_up():
    sim = _amm([_washer(probability=1.0)])
    exact_before = sim.accounting_totals()
    coins_before, cash_before = sim.pool.coin_reserve, sim.pool.cash_reserve
    ticks = sim.run(30)

    prices = [sim.coin.starting_price, *(t.price for t in ticks)]
    assert all(b > a for a, b in zip(prices, prices[1:]))  # retained fees only ever lift spot
    assert all(t.volume == t.wash_volume > 0 for t in ticks)
    assert sim.pool.swap_count == 60
    washer = sim.traders[0].wallet
    assert washer.coins == 0.0
    assert sim.pool.coin_reserve == coins_before
    loss = EXACT.subtract(Decimal(50_000.0), Decimal(washer.cash))
    assert loss > 0
    assert EXACT.subtract(sim.pool.cash_reserve, cash_before) == loss
    assert sim.accounting_totals() == exact_before


def test_amm_wash_trading_alongside_traders_conserves_exactly():
    sim = _amm(_all_five() + [_washer()])
    before = sim.accounting_totals()
    ticks = sim.run(60)
    assert sim.accounting_totals() == before
    assert sum(t.wash_volume for t in ticks) > 0
    for t in ticks:
        assert t.volume == pytest.approx(sum(f.quantity for f in t.trader_trades))


# --- pump and dump -----------------------------------------------------------------------


def test_amm_pump_and_dump_with_no_one_to_dump_on_loses_money():
    sim = _amm([_pump()])
    before = sim.accounting_totals()
    cash_before = sim.pool.cash_reserve
    ticks = sim.run(20)
    manipulator = sim.traders[0].wallet

    peak = max(ticks, key=lambda t: t.price)
    assert peak.tick == 9  # last pump tick
    assert manipulator.coins == 0.0
    assert manipulator.cash < 30_000.0
    # The pool curve is path independent: every unit the manipulator lost
    # is fees, kept in the pool — and the price ends slightly above start.
    loss = EXACT.subtract(Decimal(30_000.0), Decimal(manipulator.cash))
    assert EXACT.subtract(sim.pool.cash_reserve, cash_before) == loss
    assert ticks[-1].price > sim.coin.starting_price
    assert sim.accounting_totals() == before


def test_amm_pump_and_dump_trades_follow_the_schedule():
    sim = _amm([_pump()])
    ticks = sim.run(20)
    reasons = {t.tick: t.trader_trades[0].reason for t in ticks if t.trader_trades}
    assert reasons == {
        **{tick: "accumulate" for tick in range(3, 8)},
        **{tick: "pump" for tick in range(8, 10)},
        **{tick: "dump" for tick in range(10, 13)},
    }


def test_random_walk_pump_and_dump_round_trips_its_position_and_conserves():
    sim = _rw(_all_five() + [_pump()])
    before = _totals(sim)
    ticks = sim.run(30)
    manipulator = sim.traders[-1]
    fills = [f for t in ticks for f in t.trader_trades if f.trader_id == "pump"]
    bought = sum(f.quantity for f in fills if f.side is TradeAction.BUY)
    sold = sum(f.quantity for f in fills if f.side is TradeAction.SELL)
    assert bought == pytest.approx(sold)
    assert manipulator.wallet.coins == 0.0
    assert _totals(sim) == (pytest.approx(before[0], rel=1e-12), pytest.approx(before[1], rel=1e-12))
