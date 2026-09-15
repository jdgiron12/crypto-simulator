"""Core market analytics on hand-built ticks (Phase 9, Step 1).

Every expected value here is worked out by hand from the definitions in
``analytics/market.py``: the price path (with the pre-run point only when
tick 1 is analysed), consecutive-only returns, events.py's volatility,
realized volatility, drawdown and recovery, and the volume decomposition
that classifies every recorded quantity exactly once.
"""

import dataclasses
import math
import statistics
from decimal import Decimal

import pytest

from crypto_simulator.analytics import PRE_RUN_TICK, MarketSummary, PoolActivity, VolumeBreakdown, analyze_market
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.liquidity.pool import PoolState, SwapResult
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade
from crypto_simulator.core.whale import WhaleTrade

SUPPLY = 1_000.0


def _tick(number, price, volume=0.0, whales=(), trades=(), pool=None):
    return SimulationTick(tick=number, timestamp="t", price=price, market_cap=0.0, volume=volume,
                          whale_trades=tuple(whales), trader_trades=tuple(trades), pool_state=pool)


def _path(*prices, start=1):
    return [_tick(start + i, p) for i, p in enumerate(prices)]


def _fill(strategy, quantity, price=2.0, side=TradeAction.BUY, wash=False, swap=None, notional=None):
    return TraderTrade(trader_id=strategy, strategy=strategy, side=side, requested_quantity=quantity,
                       quantity=quantity, price=price, notional=quantity * price if notional is None else notional,
                       swap=swap, wash=wash)


def _pool():
    """A pool snapshot; only its presence matters to the market analytics."""
    return PoolState(**{f.name: (0 if f.name == "swap_count" else Decimal(1)) for f in dataclasses.fields(PoolState)})


def _swap(side, fee, impact):
    one = Decimal(1)
    return SwapResult(side, one, Decimal(fee), one, one, one, one, one, Decimal(impact), Decimal(0),
                      Decimal("0.003"), one, one)


# --- price path, open and close -------------------------------------------------------------------


def test_the_pre_run_price_opens_the_path_when_tick_one_is_analysed():
    ticks = _path(110.0, 99.0, 121.0)
    with_p0 = analyze_market(ticks, initial_price=100.0)
    assert (with_p0.open_price, with_p0.close_price, with_p0.return_count) == (100.0, 121.0, 3)
    assert with_p0.cumulative_return == 121.0 / 100.0 - 1.0
    assert with_p0.log_return == math.log(121.0 / 100.0)
    without = analyze_market(ticks)
    assert (without.open_price, without.return_count) == (110.0, 2)
    assert without.cumulative_return == 121.0 / 110.0 - 1.0


def test_the_pre_run_price_is_not_prepended_to_a_window_that_skips_tick_one():
    ticks = _path(110.0, 99.0, 121.0)
    window = analyze_market(ticks, initial_price=100.0, start_tick=2)
    assert (window.open_price, window.first_tick, window.return_count) == (99.0, 2, 1)
    later_start = analyze_market(_path(99.0, 121.0, start=2), initial_price=100.0)
    assert later_start.open_price == 99.0 and later_start.return_count == 1


def test_one_tick():
    summary = analyze_market([_tick(1, 5.0)])
    assert (summary.ticks, summary.first_tick, summary.last_tick, summary.missing_tick_count) == (1, 1, 1, 0)
    assert summary.open_price == summary.close_price == summary.high_price == summary.low_price == 5.0
    assert summary.cumulative_return == 0.0 and summary.log_return == 0.0
    assert summary.return_count == 0 and summary.mean_return is None
    assert summary.volatility is None and summary.realized_volatility is None
    assert summary.max_drawdown == 0.0 and summary.end_drawdown == 0.0
    one_with_p0 = analyze_market([_tick(1, 5.0)], initial_price=4.0)
    assert one_with_p0.return_count == 1 and one_with_p0.realized_volatility == abs(math.log(5.0 / 4.0))


def test_an_empty_input_fabricates_nothing():
    summary = analyze_market([], initial_price=1.0, total_supply=SUPPLY)
    assert summary.ticks == 0 and summary.return_count == 0 and summary.missing_tick_count == 0
    derived = [f.name for f in dataclasses.fields(MarketSummary)
               if f.name not in ("ticks", "return_count", "missing_tick_count", "volume_breakdown")]
    assert all(getattr(summary, name) is None for name in derived)
    volume = summary.volume_breakdown
    assert volume.total_volume == 0.0 and volume.background_volume is None and volume.fills == 0


# --- returns and volatility ----------------------------------------------------------------------


def test_returns_volatility_and_realized_volatility_follow_their_definitions():
    ticks = _path(110.0, 99.0, 121.0, 118.0)
    summary = analyze_market(ticks, initial_price=100.0)
    prices = [100.0, 110.0, 99.0, 121.0, 118.0]
    simple = [b / a - 1.0 for a, b in zip(prices, prices[1:])]
    logs = [math.log(b / a) for a, b in zip(prices, prices[1:])]
    assert summary.return_count == 4
    assert summary.mean_return == math.fsum(simple) / 4
    assert summary.volatility == statistics.stdev(logs)  # sample, not population
    assert summary.volatility != statistics.pstdev(logs)
    assert summary.realized_volatility == math.sqrt(math.fsum(r * r for r in logs))  # not annualized


def test_volatility_needs_two_returns():
    assert analyze_market(_path(1.0, 2.0)).volatility is None
    assert analyze_market(_path(1.0, 2.0, 1.5)).volatility is not None


def test_a_missing_tick_is_never_bridged():
    ticks = [_tick(1, 10.0), _tick(2, 11.0), _tick(4, 20.0), _tick(5, 22.0)]
    summary = analyze_market(ticks, initial_price=9.0)
    assert summary.missing_tick_count == 1 and summary.ticks == 4
    kept = [(9.0, 10.0), (10.0, 11.0), (20.0, 22.0)]  # 11 -> 20 spans the gap
    assert summary.return_count == 3
    assert summary.mean_return == math.fsum(b / a - 1.0 for a, b in kept) / 3
    assert summary.realized_volatility == math.sqrt(math.fsum(math.log(b / a) ** 2 for a, b in kept))
    assert summary.cumulative_return == 22.0 / 9.0 - 1.0  # open-to-close still spans the whole window


def test_constant_prices():
    summary = analyze_market(_path(3.0, 3.0, 3.0, 3.0), initial_price=3.0)
    assert summary.volatility == 0.0 and summary.realized_volatility == 0.0 and summary.mean_return == 0.0
    assert summary.max_drawdown == 0.0 and summary.drawdown_peak_tick is None
    assert summary.drawdown_trough_tick is None and summary.recovery_tick is None and summary.end_drawdown == 0.0
    assert (summary.high_tick, summary.low_tick) == (PRE_RUN_TICK, PRE_RUN_TICK)


# --- high, low, mean -----------------------------------------------------------------------------


def test_high_and_low_ties_go_to_the_earliest_point():
    summary = analyze_market(_path(2.0, 5.0, 5.0, 1.0, 1.0))
    assert (summary.high_price, summary.high_tick) == (5.0, 2)
    assert (summary.low_price, summary.low_tick) == (1.0, 4)
    at_p0 = analyze_market(_path(5.0, 3.0, 5.0), initial_price=5.0)
    assert at_p0.high_tick == PRE_RUN_TICK == 0


def test_mean_price_is_over_the_ticks_closes_only():
    summary = analyze_market(_path(2.0, 4.0), initial_price=100.0)
    assert summary.mean_price == 3.0


# --- drawdown -------------------------------------------------------------------------------------


def test_a_drawdown_that_recovers():
    summary = analyze_market(_path(10.0, 12.0, 9.0, 11.0, 12.0, 13.0))
    assert summary.max_drawdown == 1.0 - 9.0 / 12.0
    assert (summary.drawdown_peak_tick, summary.drawdown_trough_tick, summary.recovery_tick) == (2, 3, 5)
    assert summary.end_drawdown == 0.0


def test_a_drawdown_that_never_recovers():
    summary = analyze_market(_path(10.0, 12.0, 9.0, 11.0))
    assert (summary.drawdown_peak_tick, summary.drawdown_trough_tick, summary.recovery_tick) == (2, 3, None)
    assert summary.end_drawdown == 1.0 - 11.0 / 12.0


def test_the_deepest_drawdown_wins_and_ties_keep_the_earliest_trough():
    deeper_later = analyze_market(_path(10.0, 8.0, 10.0, 20.0, 12.0))
    assert deeper_later.max_drawdown == 1.0 - 12.0 / 20.0 and deeper_later.drawdown_trough_tick == 5
    tie = analyze_market(_path(10.0, 5.0, 10.0, 5.0))
    assert tie.max_drawdown == 0.5 and tie.drawdown_trough_tick == 2 and tie.recovery_tick == 3


def test_the_pre_run_point_can_be_the_drawdown_peak():
    summary = analyze_market(_path(10.0, 15.0), initial_price=20.0)
    assert summary.max_drawdown == 0.5
    assert (summary.drawdown_peak_tick, summary.drawdown_trough_tick, summary.recovery_tick) == (0, 1, None)


# --- market cap -----------------------------------------------------------------------------------


def test_market_caps_need_total_supply():
    ticks = _path(2.0, 3.0)
    assert analyze_market(ticks, initial_price=1.0, total_supply=500.0).market_cap_start == 1.0 * 500.0
    assert analyze_market(ticks, initial_price=1.0, total_supply=500.0).market_cap_end == 3.0 * 500.0
    no_supply = analyze_market(ticks, initial_price=1.0)
    assert no_supply.market_cap_start is None and no_supply.market_cap_end is None


# --- volume decomposition -------------------------------------------------------------------------


def _busy_tick():
    """Synthetic volume 100 plus one of everything; every value is exact in binary."""
    whales = [WhaleTrade("w", "buy", 8.0, 1.1), WhaleTrade("u", "sell", 0.0, 1.0)]
    trades = [_fill("retail", 2.0), _fill("momentum", 4.0, side=TradeAction.SELL, price=3.0),
              _fill("pump_and_dump", 16.0), _fill("wash_trader", 1.0, wash=True),
              _fill("wash_trader", 1.0, side=TradeAction.SELL, wash=True),
              _fill("retail", 0.5, wash=True)]  # a wash leg is wash whoever makes it
    volume = 100.0 + 8.0 + 0.0 + 2.0 + 4.0 + 16.0 + 1.0 + 1.0 + 0.5
    return _tick(1, 2.0, volume=volume, whales=whales, trades=trades)


def test_every_recorded_quantity_lands_in_exactly_one_category():
    summary = analyze_market([_busy_tick()], total_supply=SUPPLY)
    v = summary.volume_breakdown
    assert (v.total_volume, v.background_volume, v.whale_volume) == (132.5, 100.0, 8.0)
    assert (v.organic_volume, v.manipulator_volume, v.wash_volume) == (6.0, 16.0, 2.5)
    assert v.total_volume == v.background_volume + v.whale_volume + v.organic_volume + v.manipulator_volume + v.wash_volume
    assert (v.whale_fills, v.zero_quantity_whale_trades, v.organic_fills, v.manipulator_fills, v.wash_legs) == (1, 1, 2, 1, 3)
    assert v.fills == 7 and v.trader_fills == 3 and v.participant_volume == 30.0


def test_trade_size_turnover_and_vwap():
    summary = analyze_market([_busy_tick()], total_supply=SUPPLY)
    assert summary.average_trade_size == 30.0 / 4  # whale + organic + manipulator fills, no wash, no zero trade
    assert summary.turnover == 132.5 / SUPPLY
    assert summary.participant_turnover == 30.0 / SUPPLY
    # Non-wash trader fills only: 2@2, 4@3, 16@2.
    assert summary.trader_vwap == (2.0 * 2.0 + 4.0 * 3.0 + 16.0 * 2.0) / 22.0
    no_supply = analyze_market([_busy_tick()])
    assert no_supply.turnover is None and no_supply.participant_turnover is None


def test_wash_only_activity():
    trades = [_fill("wash_trader", 5.0, wash=True), _fill("wash_trader", 5.0, side=TradeAction.SELL, wash=True)]
    summary = analyze_market([_tick(1, 2.0, volume=50.0 + 10.0, trades=trades)], total_supply=SUPPLY)
    v = summary.volume_breakdown
    assert (v.wash_volume, v.organic_volume, v.manipulator_volume, v.background_volume) == (10.0, 0.0, 0.0, 50.0)
    assert summary.trader_vwap is None and summary.average_trade_size is None
    assert summary.participant_turnover == 0.0 and summary.turnover == 60.0 / SUPPLY


def test_no_trades_is_all_background():
    summary = analyze_market([_tick(1, 2.0, volume=7.0), _tick(2, 2.0, volume=3.0)])
    v = summary.volume_breakdown
    assert v.background_volume == v.total_volume == 10.0 and v.fills == 0
    assert summary.trader_vwap is None and summary.average_trade_size is None


def test_zero_quantity_whale_trades_are_not_fills():
    summary = analyze_market([_tick(1, 2.0, volume=5.0, whales=[WhaleTrade("u", "sell", 0.0, 1.0)])])
    v = summary.volume_breakdown
    assert v.zero_quantity_whale_trades == 1 and v.whale_fills == 0 and v.fills == 0
    assert summary.average_trade_size is None


def test_amm_ticks_have_no_background_and_report_pool_activity():
    swaps = [_swap("buy", "0.5", "0.01"), _swap("sell", "0.25", "-0.03"), _swap("buy", "0.125", "0.02")]
    trades = [_fill("retail", 3.0, swap=swaps[0]), _fill("panic", 2.0, side=TradeAction.SELL, swap=swaps[1]),
              _fill("wash_trader", 1.0, wash=True, swap=swaps[2])]
    summary = analyze_market([_tick(1, 2.0, volume=6.0, trades=trades, pool=_pool())])
    assert summary.pricing_mode == "amm" and summary.volume_breakdown.background_volume is None
    assert summary.volume_breakdown.wash_volume == 1.0 and summary.volume_breakdown.organic_volume == 5.0
    assert summary.pool_activity == PoolActivity(swap_count=3, fees_cash=Decimal("0.625"), fees_coins=Decimal("0.25"),
                                                 max_abs_price_impact=Decimal("0.03"))


def test_random_walk_ticks_have_no_pool_activity():
    summary = analyze_market([_busy_tick()])
    assert summary.pricing_mode == "random_walk" and summary.pool_activity is None


def test_an_amm_run_with_no_swaps_reports_empty_pool_activity():
    summary = analyze_market([_tick(1, 2.0, pool=_pool())])
    assert summary.pool_activity == PoolActivity(0, Decimal(0), Decimal(0), None)


def test_mixing_amm_and_random_walk_ticks_is_rejected():
    with pytest.raises(ValueError, match="mix AMM and random-walk"):
        analyze_market([_tick(1, 2.0, pool=_pool()), _tick(2, 2.0)])


# --- windows ---------------------------------------------------------------------------------------


def test_a_window_is_the_same_as_analysing_only_its_ticks():
    ticks = [_tick(n, 10.0 + (n * 7) % 5, volume=float(n)) for n in range(1, 21)]
    for start, end in [(1, 20), (3, 9), (5, 5), (1, 1), (18, 20)]:
        window = analyze_market(ticks, initial_price=9.0, total_supply=SUPPLY, start_tick=start, end_tick=end)
        sliced = analyze_market([t for t in ticks if start <= t.tick <= end], initial_price=9.0, total_supply=SUPPLY)
        assert window == sliced
    only_start = analyze_market(ticks, start_tick=15)
    assert only_start.first_tick == 15 and only_start.last_tick == 20
    only_end = analyze_market(ticks, end_tick=4)
    assert only_end.first_tick == 1 and only_end.last_tick == 4


def test_a_window_with_no_ticks_is_empty():
    assert analyze_market(_path(1.0, 2.0), start_tick=10, end_tick=12).ticks == 0


# --- ordering and validation ------------------------------------------------------------------------


def test_input_order_does_not_matter():
    ticks = [_busy_tick()] + _path(3.0, 2.5, 4.0, start=2)
    assert analyze_market(list(reversed(ticks)), initial_price=1.5) == analyze_market(ticks, initial_price=1.5)


def test_duplicate_ticks_raise_the_established_message():
    with pytest.raises(ValueError) as error:
        analyze_market([_tick(1, 1.0), _tick(2, 1.0), _tick(2, 1.5)])
    assert str(error.value) == "duplicate tick 2"


@pytest.mark.parametrize("bad", [None, "tick", 1, (1, 2.0)])
def test_non_ticks_are_rejected(bad):
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_market([_tick(1, 1.0), bad])


@pytest.mark.parametrize("price", [0.0, -1.0, math.nan, math.inf, True, "2.0", None])
def test_invalid_prices_are_rejected(price):
    with pytest.raises(ValueError, match="invalid price"):
        analyze_market([_tick(1, 1.0), _tick(2, price)])


@pytest.mark.parametrize("name", ["initial_price", "total_supply"])
@pytest.mark.parametrize("value", [0.0, -5.0, math.nan, math.inf, True, "1"])
def test_invalid_initial_price_and_supply_are_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        analyze_market(_path(1.0), **{name: value})


@pytest.mark.parametrize("kwargs, message", [
    ({"start_tick": 0}, "start_tick"), ({"end_tick": -1}, "end_tick"), ({"start_tick": 1.5}, "start_tick"),
    ({"end_tick": True}, "end_tick"), ({"start_tick": 5, "end_tick": 4}, "must not exceed"),
])
def test_invalid_windows_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        analyze_market(_path(1.0, 2.0), **kwargs)


def test_the_results_are_frozen():
    summary = analyze_market([_busy_tick()])
    for value in (summary, summary.volume_breakdown):
        with pytest.raises(dataclasses.FrozenInstanceError):
            value.ticks = 0 if isinstance(value, MarketSummary) else None
    assert isinstance(summary.volume_breakdown, VolumeBreakdown)
