"""Descriptive market regimes on hand-built ticks (Phase 9, Step 7).

Every expected label is worked out by hand from the definitions in
``analytics/regimes.py``: the tick-number window grid, direction from the
window's own consecutive returns against its realized volatility, the
volatility and volume classes against the quartiles of earlier complete
windows only, and market state from the running high. The no-look-ahead
tests change or add later ticks and require earlier windows to stay
exactly as they were.
"""

import dataclasses
import math
from decimal import Decimal

import pytest

from crypto_simulator.analytics import analyze_market
from crypto_simulator.analytics.regimes import (
    AT_HIGH,
    COVERAGE_COMPLETE,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    DEFAULT_WINDOW_SIZE,
    DRAWDOWN,
    FALLING,
    FLAT,
    HIGH_VOLATILITY,
    HIGH_VOLUME,
    LOW_VOLATILITY,
    LOW_VOLUME,
    MIN_REFERENCE_WINDOWS,
    NORMAL_VOLATILITY,
    NORMAL_VOLUME,
    RECOVERY,
    RISING,
    RegimeContext,
    RegimeObservation,
    RegimeReport,
    analyze_regimes,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events import EventPhase, EventState, EventStatus
from crypto_simulator.core.liquidity.pool import PoolState
from crypto_simulator.core.psychology import PsychologyState
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade
from tests.analytics.test_whales import _observation as _whale_observation

P = PsychologyState


def _tick(n, price=100.0, volume=10.0, fills=(), event_state=None, psychology=None, whales=(), pool=None):
    return SimulationTick(tick=n, timestamp=f"t{n}", price=price, market_cap=0.0, volume=volume,
                          trader_trades=tuple(fills), event_state=event_state, psychology=psychology,
                          whale_observations=tuple(whales), pool_state=pool)


def _series(prices, volume=10.0, start=1):
    return [_tick(start + i, price, volume) for i, price in enumerate(prices)]


def _zigzag_windows(amplitudes, volumes=None, w=5):
    """One window per amplitude: prices 100, 100+a, 100, 100+a, 100, so the
    window's net move is zero and its volatility grows with ``a``."""
    volumes = volumes or [10.0] * len(amplitudes)
    ticks = []
    for k, (a, v) in enumerate(zip(amplitudes, volumes)):
        for i, price in enumerate((100.0, 100.0 + a, 100.0, 100.0 + a, 100.0)):
            ticks.append(_tick(k * w + i + 1, price, v))
    return ticks


def _flat_windows(volumes, w=5):
    return [_tick(k * w + i + 1, 100.0, v) for k, v in enumerate(volumes) for i in range(w)]


def _labels(report):
    return [(o.window_index, o.direction, o.volatility, o.volume, o.market_state) for o in report.observations]


# --- basic shape -----------------------------------------------------------------------------------


def test_empty_input_is_an_empty_report():
    report = analyze_regimes([])
    assert report == RegimeReport(
        ticks=0, window_size=DEFAULT_WINDOW_SIZE, pricing_mode=None, coverage=COVERAGE_NONE, observations=(),
        direction_counts=((RISING, 0), (FALLING, 0), (FLAT, 0), (None, 0)),
        volatility_counts=((LOW_VOLATILITY, 0), (NORMAL_VOLATILITY, 0), (HIGH_VOLATILITY, 0), (None, 0)),
        volume_counts=((LOW_VOLUME, 0), (NORMAL_VOLUME, 0), (HIGH_VOLUME, 0), (None, 0)),
        market_state_counts=((AT_HIGH, 0), (DRAWDOWN, 0), (RECOVERY, 0), (None, 0)),
    )
    assert report.total_windows == report.complete_windows == report.incomplete_windows == 0


def test_one_tick_is_one_incomplete_window_with_only_what_it_supports():
    report = analyze_regimes([_tick(1)])
    (window,) = report.observations
    assert (window.start_tick, window.end_tick, window.tick_count, window.complete) == (1, 20, 1, False)
    assert window.direction is None and window.volatility is None and window.volume is None
    assert window.market_state == AT_HIGH  # a single price is its own running high
    assert report.coverage == COVERAGE_PARTIAL


def test_windows_are_fixed_by_tick_number():
    report = analyze_regimes(_series([100.0] * 45), window_size=20)
    assert [(o.start_tick, o.end_tick, o.tick_count) for o in report.observations] == [
        (1, 20, 20), (21, 40, 20), (41, 60, 5)]
    assert [o.complete for o in report.observations] == [True, True, False]


def test_the_incomplete_final_window_is_kept_and_never_padded():
    report = analyze_regimes(_series([100.0] * 23), window_size=10)
    last = report.observations[-1]
    assert (last.tick_count, last.expected_tick_count, last.complete) == (3, 10, False)
    assert last.market.ticks == 3
    assert report.incomplete_windows == 1 and report.coverage == COVERAGE_PARTIAL


def test_exactly_divisible_input_is_complete_coverage():
    report = analyze_regimes(_series([100.0] * 30), window_size=10)
    assert report.coverage == COVERAGE_COMPLETE and report.complete_windows == 3


def test_custom_window_size():
    report = analyze_regimes(_series([100.0] * 12), window_size=4)
    assert [(o.start_tick, o.end_tick) for o in report.observations] == [(1, 4), (5, 8), (9, 12)]
    assert report.window_size == 4


@pytest.mark.parametrize("bad", [0, -1, 2.5, True, "20", None])
def test_invalid_window_sizes_are_rejected(bad):
    with pytest.raises(ValueError, match="window_size"):
        analyze_regimes(_series([100.0] * 5), window_size=bad)


def test_each_window_embeds_analyze_markets_own_summary():
    ticks = _series([100.0, 101.0, 99.0, 104.0, 102.0, 107.0, 103.0, 101.0], volume=7.0)
    report = analyze_regimes(ticks, initial_price=100.0, window_size=4, total_supply=1_000.0)
    for window in report.observations:
        assert window.market == analyze_market(ticks, initial_price=100.0, total_supply=1_000.0,
                                               start_tick=window.start_tick, end_tick=window.end_tick)


def test_counts_cover_every_window_once_per_dimension():
    report = analyze_regimes(_zigzag_windows([1, 2, 3, 4, 10, 0.5]), window_size=5)
    for counts in (report.direction_counts, report.volatility_counts, report.volume_counts,
                   report.market_state_counts):
        assert sum(count for _, count in counts) == report.total_windows


# --- direction -----------------------------------------------------------------------------------------


def test_steady_rises_are_rising():
    window = analyze_regimes(_series([100.0, 101.0, 102.0, 103.0, 104.0]), window_size=5).window(0)
    assert window.direction == RISING
    assert window.net_log_return == pytest.approx(math.log(104.0 / 100.0))
    assert window.net_log_return > window.market.realized_volatility


def test_steady_falls_are_falling():
    window = analyze_regimes(_series([104.0, 103.0, 102.0, 101.0, 100.0]), window_size=5).window(0)
    assert window.direction == FALLING


def test_an_unchanged_price_is_flat():
    window = analyze_regimes(_series([100.0] * 5), window_size=5).window(0)
    assert window.direction == FLAT
    assert window.net_log_return == 0.0 and window.market.realized_volatility == 0.0


def test_mixed_moves_that_cancel_out_are_flat_not_rising_or_falling():
    window = analyze_regimes(_series([100.0, 110.0, 100.0, 110.0, 100.0]), window_size=5).window(0)
    assert window.direction == FLAT


def test_a_net_move_no_larger_than_realized_volatility_is_flat():
    # One large rise and three smaller falls: net is positive but smaller
    # than sqrt(sum r^2), so the net move never stood out from the path.
    prices = [100.0, 120.0, 116.0, 112.0, 108.0]
    window = analyze_regimes(_series(prices), window_size=5).window(0)
    assert 0 < window.net_log_return <= window.market.realized_volatility
    assert window.direction == FLAT


def test_direction_needs_at_least_two_returns():
    window = analyze_regimes(_series([100.0, 110.0]), window_size=5).window(0)
    assert window.market.return_count == 1
    assert window.direction is None


# --- volatility ------------------------------------------------------------------------------------------


def test_no_volatility_class_until_enough_earlier_complete_windows():
    report = analyze_regimes(_zigzag_windows([1, 2, 3, 4, 10]), window_size=5)
    assert [o.volatility for o in report.observations[:MIN_REFERENCE_WINDOWS]] == [None] * MIN_REFERENCE_WINDOWS
    assert all(o.volatility_reference is None for o in report.observations[:MIN_REFERENCE_WINDOWS])


@pytest.mark.parametrize("amplitude, expected", [(10.0, HIGH_VOLATILITY), (0.5, LOW_VOLATILITY),
                                                 (2.5, NORMAL_VOLATILITY)])
def test_volatility_class_against_earlier_quartiles(amplitude, expected):
    report = analyze_regimes(_zigzag_windows([1, 2, 3, 4, amplitude]), window_size=5)
    window = report.window(4)
    earlier = sorted(o.market.volatility for o in report.observations[:4])
    lower = earlier[0] + (earlier[1] - earlier[0]) * 0.75
    upper = earlier[2] + (earlier[3] - earlier[2]) * 0.25
    assert window.volatility_reference == pytest.approx((lower, upper))
    assert window.volatility == expected


def test_volatility_needs_returns_to_exist():
    ticks = _zigzag_windows([1, 2, 3, 4]) + [_tick(21, 100.0)]
    window = analyze_regimes(ticks, window_size=5).window(4)
    assert window.market.volatility is None and window.volatility is None


# --- volume ----------------------------------------------------------------------------------------------


def test_volume_reference_uses_the_documented_quartiles():
    window = analyze_regimes(_flat_windows([10.0, 20.0, 30.0, 40.0, 25.0]), window_size=5).window(4)
    assert window.volume_reference == (17.5, 32.5)
    assert window.volume == NORMAL_VOLUME


@pytest.mark.parametrize("per_tick, expected", [(100.0, HIGH_VOLUME), (1.0, LOW_VOLUME), (17.5, NORMAL_VOLUME),
                                               (32.5, NORMAL_VOLUME)])
def test_volume_class_against_earlier_quartiles_with_inclusive_bounds(per_tick, expected):
    window = analyze_regimes(_flat_windows([10.0, 20.0, 30.0, 40.0, per_tick]), window_size=5).window(4)
    assert window.volume == expected


def test_zero_volume_throughout_is_normal_not_missing():
    window = analyze_regimes(_flat_windows([0.0] * 5), window_size=5).window(4)
    assert window.volume_per_tick == 0.0 and window.volume == NORMAL_VOLUME


def test_an_incomplete_window_uses_volume_per_observed_tick():
    ticks = _flat_windows([10.0, 20.0, 30.0, 40.0]) + [_tick(21, 100.0, 100.0), _tick(22, 100.0, 100.0)]
    window = analyze_regimes(ticks, window_size=5).window(4)
    assert window.volume_per_tick == 100.0 and window.volume == HIGH_VOLUME and not window.complete


def test_an_incomplete_window_never_joins_the_reference():
    ticks = _flat_windows([10.0, 20.0, 30.0, 40.0])
    ticks += [_tick(21, 100.0, 1000.0)]  # window 4: one tick, huge volume, incomplete
    ticks += [_tick(26 + i, 100.0, 25.0) for i in range(5)]  # window 5: complete
    window = analyze_regimes(ticks, window_size=5).window(5)
    assert window.volume_reference == (17.5, 32.5)  # windows 0-3 only


def test_invalid_volume_is_rejected():
    for bad in (float("nan"), float("inf"), -1.0):
        with pytest.raises(ValueError, match="invalid volume"):
            analyze_regimes([_tick(1, 100.0, bad)])


# --- market state ------------------------------------------------------------------------------------------


def test_closing_at_a_new_high_is_at_high():
    window = analyze_regimes(_series([100.0, 101.0, 102.0, 103.0, 104.0]), window_size=5).window(0)
    assert window.market_state == AT_HIGH
    assert window.running_peak == 104.0 and window.drawdown_at_end == 0.0


def test_falling_further_below_an_earlier_high_is_drawdown():
    ticks = _series([100.0, 110.0, 120.0, 130.0, 140.0, 135.0, 130.0, 125.0, 120.0, 115.0])
    window = analyze_regimes(ticks, window_size=5).window(1)
    assert window.running_peak == 140.0  # set in the earlier window
    assert window.drawdown_at_start == pytest.approx(1 - 135.0 / 140.0)
    assert window.drawdown_at_end == pytest.approx(1 - 115.0 / 140.0)
    assert window.market_state == DRAWDOWN


def test_a_narrowing_drawdown_is_recovery_while_still_below_the_high():
    ticks = _series([140.0, 130.0, 120.0, 110.0, 100.0, 105.0, 110.0, 115.0, 120.0, 125.0])
    window = analyze_regimes(ticks, window_size=5).window(1)
    assert 0 < window.drawdown_at_end < window.drawdown_at_start
    assert window.market_state == RECOVERY


def test_a_window_that_rallies_back_to_a_new_high_is_at_high_not_recovery():
    ticks = _series([140.0, 130.0, 120.0, 110.0, 100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
    assert analyze_regimes(ticks, window_size=5).window(1).market_state == AT_HIGH


def test_a_window_that_sets_a_high_then_falls_back_is_drawdown():
    ticks = _series([100.0, 110.0, 120.0, 130.0, 125.0])
    window = analyze_regimes(ticks, window_size=5).window(0)
    assert window.drawdown_at_start == 0.0 and window.drawdown_at_end > 0
    assert window.market_state == DRAWDOWN


def test_the_pre_run_price_counts_toward_the_running_high():
    window = analyze_regimes(_series([100.0] * 5), initial_price=200.0, window_size=5).window(0)
    assert window.running_peak == 200.0
    assert window.drawdown_at_start == 0.0  # the pre-run point itself
    assert window.drawdown_at_end == pytest.approx(0.5)
    assert window.market_state == DRAWDOWN


def test_without_initial_price_the_first_window_starts_at_its_first_tick():
    window = analyze_regimes(_series([100.0] * 5), window_size=5).window(0)
    assert window.running_peak == 100.0 and window.market_state == AT_HIGH
    assert window.market.return_count == 4


# --- gaps -----------------------------------------------------------------------------------------------------


def test_a_missing_tick_makes_the_window_incomplete_and_is_never_bridged():
    ticks = [_tick(1, 100.0), _tick(2, 110.0), _tick(4, 200.0), _tick(5, 210.0)]
    window = analyze_regimes(ticks, window_size=5).window(0)
    assert (window.tick_count, window.complete) == (4, False)
    assert window.market.return_count == 2
    assert window.net_log_return == pytest.approx(math.log(1.1) + math.log(210.0 / 200.0))
    assert window.net_log_return != pytest.approx(math.log(210.0 / 100.0))


def test_a_whole_missing_window_is_skipped_not_reported_as_flat():
    ticks = _series([100.0] * 5) + _series([100.0] * 5, start=11)
    report = analyze_regimes(ticks, window_size=5)
    assert [o.window_index for o in report.observations] == [0, 2]


def test_later_ticks_never_change_earlier_windows():
    base = _zigzag_windows([1, 2, 3, 4, 6, 2])  # 30 ticks, six windows
    earlier = analyze_regimes(base, initial_price=100.0, window_size=5).observations
    extended = base + [_tick(31 + i, 1_000.0 * (i + 1), 1e6) for i in range(20)]
    changed = [dataclasses.replace(t, price=t.price * 50, volume=t.volume * 999) if t.tick > 20 else t
               for t in extended]
    for variant in (extended, changed):
        later = analyze_regimes(variant, initial_price=100.0, window_size=5).observations
        prefix = 4 if variant is changed else 6
        assert later[:prefix] == earlier[:prefix]


def test_a_later_new_high_does_not_relabel_an_earlier_at_high_window():
    ticks = _series([100.0, 101.0, 102.0, 103.0, 104.0])
    before = analyze_regimes(ticks, window_size=5).window(0)
    after = analyze_regimes(ticks + _series([500.0] * 5, start=6), window_size=5).window(0)
    assert before == after and after.market_state == AT_HIGH


# --- events (context only) --------------------------------------------------------------------------------


def _live(n, *events):
    return EventState(tick=n, events=tuple(EventStatus(i, c, EventPhase.ACTIVE, 1.0) for i, c in events))


def test_event_context_is_recorded():
    ticks = [_tick(1, event_state=_live(1)), _tick(2, event_state=_live(2, ("b", "regulation"))),
             _tick(3, event_state=_live(3, ("b", "regulation"), ("a", "listing")))]
    context = analyze_regimes(ticks, window_size=5).window(0).context
    assert context.event_state_ticks == 3 and context.event_active_ticks == 2
    assert context.event_ids == ("a", "b") and context.event_categories == ("listing", "regulation")
    assert context.max_concurrent_events == 2 and context.event_active is True


def test_an_event_engine_with_nothing_live_is_inactive_not_unknown():
    context = analyze_regimes([_tick(1, event_state=_live(1))], window_size=5).window(0).context
    assert context.event_active is False and context.max_concurrent_events == 0


def test_no_event_engine_is_unknown():
    context = analyze_regimes([_tick(1)], window_size=5).window(0).context
    assert context.event_active is None and context.max_concurrent_events is None


def test_events_never_change_any_label():
    plain = _zigzag_windows([1, 2, 3, 4, 9])
    with_events = [dataclasses.replace(t, event_state=_live(t.tick, ("e", "custom"))) for t in plain]
    assert _labels(analyze_regimes(plain, window_size=5)) == _labels(analyze_regimes(with_events, window_size=5))


# --- psychology (context only) ----------------------------------------------------------------------------


def test_psychology_means_cover_only_ticks_that_recorded_a_state():
    ticks = [_tick(1, psychology=P(fear=0.2, fomo=0.4)), _tick(2), _tick(3, psychology=P(fear=0.6))]
    context = analyze_regimes(ticks, window_size=5).window(0).context
    assert context.psychology_ticks == 2
    assert context.mean_fear == pytest.approx(0.4) and context.mean_fomo == pytest.approx(0.2)


def test_absent_psychology_is_none_never_a_neutral_zero():
    context = analyze_regimes([_tick(1), _tick(2)], window_size=5).window(0).context
    assert context.psychology_ticks == 0
    assert (context.mean_fear, context.mean_fomo, context.mean_conviction, context.mean_uncertainty) == (None,) * 4


def test_psychology_never_changes_any_label():
    plain = _zigzag_windows([1, 2, 3, 4, 9])
    anxious = [dataclasses.replace(t, psychology=P(fear=1.0, uncertainty=1.0)) for t in plain]
    assert _labels(analyze_regimes(plain, window_size=5)) == _labels(analyze_regimes(anxious, window_size=5))


def test_malformed_psychology_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=1.0, market_cap=0.0, volume=0.0, psychology="calm")
    with pytest.raises(ValueError, match="psychology"):
        analyze_regimes([bad])


# --- manipulation (context only) ------------------------------------------------------------------------


def _fill(trader, quantity, strategy, side=TradeAction.BUY, wash=False, reason=""):
    return TraderTrade(trader_id=trader, strategy=strategy, side=side, requested_quantity=quantity,
                       quantity=quantity, price=100.0, notional=quantity * 100.0, reason=reason, wash=wash)


def test_pump_and_dump_and_wash_volume_are_context():
    fills = [_fill("p", 3.0, "pump_and_dump", reason="pump"),
             _fill("w", 2.0, "wash_trader", wash=True), _fill("w", 2.0, "wash_trader", TradeAction.SELL, wash=True)]
    window = analyze_regimes([_tick(1, volume=100.0, fills=fills)], window_size=5).window(0)
    assert window.manipulation_active is True
    assert window.manipulation_volume == pytest.approx(7.0)
    assert window.market.volume_breakdown.wash_volume == 4.0


def test_no_manipulation_fills_is_inactive():
    window = analyze_regimes([_tick(1, fills=[_fill("r", 1.0, "retail")])], window_size=5).window(0)
    assert window.manipulation_active is False and window.manipulation_volume == 0.0


def test_a_sharp_rally_is_never_labelled_manipulation():
    window = analyze_regimes(_series([100.0, 150.0, 225.0, 340.0, 510.0]), window_size=5).window(0)
    assert window.direction == RISING
    assert window.manipulation_active is False
    assert "pump" not in window.description and "dump" not in window.description


# --- whales (context only) --------------------------------------------------------------------------------


def test_whale_observation_ticks_are_counted():
    ticks = [_tick(1, whales=[_whale_observation("w")]), _tick(2), _tick(3, whales=[_whale_observation("w")])]
    assert analyze_regimes(ticks, window_size=5).window(0).context.whale_observed_ticks == 2


def test_absent_whale_observations_count_zero():
    assert analyze_regimes([_tick(1)], window_size=5).window(0).context.whale_observed_ticks == 0


def test_whale_observations_never_change_any_label():
    plain = _zigzag_windows([1, 2, 3, 4, 9])
    observed = [dataclasses.replace(t, whale_observations=(_whale_observation("w"),)) for t in plain]
    assert _labels(analyze_regimes(plain, window_size=5)) == _labels(analyze_regimes(observed, window_size=5))


# --- modes and validation ---------------------------------------------------------------------------------


def _pool():
    return PoolState(**{f.name: (0 if f.name == "swap_count" else Decimal(1)) for f in dataclasses.fields(PoolState)})


def test_amm_ticks_report_amm_and_classify_the_same_way():
    ticks = [dataclasses.replace(t, pool_state=_pool()) for t in _series([100.0, 101.0, 102.0, 103.0, 104.0])]
    report = analyze_regimes(ticks, window_size=5)
    assert report.pricing_mode == "amm" and report.window(0).direction == RISING


def test_mixed_pricing_modes_are_rejected():
    ticks = [_tick(1), dataclasses.replace(_tick(2), pool_state=_pool())]
    with pytest.raises(ValueError, match="mix AMM and random-walk"):
        analyze_regimes(ticks)


def test_duplicate_ticks_are_rejected():
    with pytest.raises(ValueError, match="duplicate tick 1"):
        analyze_regimes([_tick(1), _tick(1)])


def test_non_ticks_are_rejected():
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_regimes([{"tick": 1}])


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_prices_are_rejected(bad):
    with pytest.raises(ValueError, match="invalid price"):
        analyze_regimes([_tick(1), _tick(2, bad)])


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), True])
def test_invalid_initial_price_is_rejected(bad):
    with pytest.raises(ValueError, match="initial_price"):
        analyze_regimes([_tick(1)], initial_price=bad)


# --- purity -----------------------------------------------------------------------------------------------


def test_the_report_is_frozen():
    report = analyze_regimes(_series([100.0] * 6), window_size=5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.coverage = COVERAGE_NONE
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.observations[0].direction = RISING
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.observations[0].context.psychology_ticks = 9
    assert isinstance(report.observations[0], RegimeObservation)
    assert isinstance(report.observations[0].context, RegimeContext)


def test_analysis_is_deterministic_order_independent_and_leaves_inputs_alone():
    ticks = _zigzag_windows([1, 2, 3, 4, 9, 0.5, 3])
    before = [dataclasses.astuple(t) for t in ticks]
    forward = analyze_regimes(ticks, initial_price=100.0, window_size=5)
    backward = analyze_regimes(list(reversed(ticks)), initial_price=100.0, window_size=5)
    assert forward == backward == analyze_regimes(ticks, initial_price=100.0, window_size=5)
    assert [dataclasses.astuple(t) for t in ticks] == before
