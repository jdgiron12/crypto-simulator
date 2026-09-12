"""analyze_psychology on hand-built ticks with known answers."""

import dataclasses
import math
import random

import pytest

from crypto_simulator.analytics import (
    COMPONENTS,
    DEFAULT_PERSISTENCE_THRESHOLD,
    NEUTRAL,
    OCCUPANCY_THRESHOLDS,
    ComponentPeriodMeans,
    Persistence,
    PsychologyReport,
    ThresholdOccupancy,
    TradingActivity,
    analyze_psychology,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events import EventPhase, EventState, EventStatus
from crypto_simulator.core.psychology import PsychologyState
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade

P = PsychologyState
BUY, SELL = TradeAction.BUY, TradeAction.SELL


def _tick(n, psychology=None, fills=(), live=None):
    """``live``: None = no event state recorded; True/False = an event state
    with / without a live event."""
    event_state = None
    if live is not None:
        statuses = (EventStatus("e", "custom", EventPhase.ACTIVE, 1.0),) if live else ()
        event_state = EventState(tick=n, events=statuses)
    return SimulationTick(tick=n, timestamp=f"t{n}", price=1.0, market_cap=1e6, volume=0.0,
                          trader_trades=tuple(fills), event_state=event_state, psychology=psychology)


def _fill(trader_id, side=BUY, wash=False):
    return TraderTrade(trader_id=trader_id, strategy="retail", side=side, requested_quantity=1.0,
                       quantity=1.0, price=1.0, notional=1.0, reason="x", wash=wash)


def _fear_ticks(values):
    return [_tick(n, None if v is None else P(fear=v)) for n, v in enumerate(values, start=1)]


def _group(report, label):
    return next(g for g in report.dominant if g.dominant == label)


# --- basic statistics --------------------------------------------------------------------------


def test_exact_mean_median_min_max_and_percentiles():
    fear = analyze_psychology(_fear_ticks([0.1, 0.4, 0.2, 0.9, 0.5])).component("fear")
    assert fear.count == 5
    assert fear.mean == math.fsum([0.1, 0.4, 0.2, 0.9, 0.5]) / 5
    assert (fear.median, fear.minimum, fear.maximum) == (0.4, 0.1, 0.9)
    # sorted 0.1 0.2 0.4 0.5 0.9: p90 at rank 3.6, p95 at rank 3.8
    assert fear.p90 == 0.5 + (0.9 - 0.5) * (60 / 100)
    assert fear.p95 == 0.5 + (0.9 - 0.5) * (80 / 100)


def test_median_of_an_even_count_averages_the_middle_pair():
    assert analyze_psychology(_fear_ticks([0.4, 0.1, 0.2, 0.6])).component("fear").median == (0.2 + 0.4) / 2


def test_percentiles_land_exactly_on_a_value_when_the_rank_is_whole():
    values = [i / 10 for i in range(11)]  # rank of p90 = 9, p95 = 9.5
    fear = analyze_psychology(_fear_ticks(values)).component("fear")
    assert fear.p90 == values[9]
    assert fear.p95 == values[9] + (values[10] - values[9]) * (50 / 100)


def test_a_single_tick_is_every_statistic():
    fear = analyze_psychology(_fear_ticks([0.3])).component("fear")
    assert (fear.mean, fear.median, fear.minimum, fear.maximum, fear.p90, fear.p95) == (0.3,) * 6


def test_every_component_is_summarized_in_a_fixed_order():
    report = analyze_psychology([_tick(1, P(0.1, 0.2, 0.3, 0.4)), _tick(2, P(0.5, 0.6, 0.7, 0.8))])
    assert tuple(c.component for c in report.components) == COMPONENTS
    assert [report.component(c).mean for c in COMPONENTS] == [(0.1 + 0.5) / 2, (0.2 + 0.6) / 2, (0.3 + 0.7) / 2,
                                                              (0.4 + 0.8) / 2]
    with pytest.raises(KeyError):
        report.component("greed")


# --- threshold occupancy ---------------------------------------------------------------------------


def test_occupancy_counts_values_at_or_above_each_threshold():
    fear = analyze_psychology(_fear_ticks([0.25, 0.5, 0.74, 0.75, 0.9, 1.0, 0.0, 0.1])).component("fear")
    assert OCCUPANCY_THRESHOLDS == (0.25, 0.50, 0.75, 0.90)
    assert fear.occupancy == (
        ThresholdOccupancy(0.25, 6, 6 / 8), ThresholdOccupancy(0.50, 5, 5 / 8),
        ThresholdOccupancy(0.75, 3, 3 / 8), ThresholdOccupancy(0.90, 2, 2 / 8),
    )


# --- dominant component ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state, expected",
    [
        (P(fear=0.9, fomo=0.1), "fear"),
        (P(fear=0.5, fomo=0.5), "fear"),  # ties go to the first in COMPONENTS order
        (P(fomo=0.4, conviction=0.4), "fomo"),
        (P(conviction=0.3, uncertainty=0.3), "conviction"),
        (P(0.5, 0.5, 0.5, 0.5), "fear"),
        (P(fear=0.1, uncertainty=0.2), "uncertainty"),
        (P(), NEUTRAL),  # all zero: no dominant component, not "fear" by tie-break
    ],
)
def test_dominant_component_with_deterministic_tie_breaking(state, expected):
    report = analyze_psychology([_tick(1, state)])
    assert [g.dominant for g in report.dominant if g.ticks] == [expected]


def test_dominant_counts_and_shares():
    states = [P(fear=0.9), P(fear=0.6, fomo=0.2), P(fomo=0.7), P(uncertainty=0.5), P()]
    report = analyze_psychology([_tick(n, s) for n, s in enumerate(states, start=1)])
    assert [g.dominant for g in report.dominant] == [*COMPONENTS, NEUTRAL]
    assert [(g.dominant, g.ticks, g.share) for g in report.dominant] == [
        ("fear", 2, 2 / 5), ("fomo", 1, 1 / 5), ("conviction", 0, 0.0), ("uncertainty", 1, 1 / 5), (NEUTRAL, 1, 1 / 5),
    ]


# --- persistence ---------------------------------------------------------------------------------


def test_longest_run_its_start_and_the_number_of_runs():
    fear = analyze_psychology(_fear_ticks([0.8, 0.9, 0.1, 0.8, 0.8, 0.8, 0.2, 0.9])).component("fear")
    assert fear.persistence == Persistence(threshold=0.75, longest_run=3, longest_run_start=4, runs=3)


def test_the_earliest_of_equally_long_runs_is_reported():
    fear = analyze_psychology(_fear_ticks([0.8, 0.8, 0.1, 0.9, 0.9])).component("fear")
    assert (fear.persistence.longest_run, fear.persistence.longest_run_start, fear.persistence.runs) == (2, 1, 2)


def test_a_missing_tick_or_missing_psychology_ends_a_run():
    gap = [_tick(1, P(fear=0.8)), _tick(2, P(fear=0.8)), _tick(4, P(fear=0.8))]
    assert analyze_psychology(gap).component("fear").persistence == Persistence(0.75, 2, 1, 2)
    hole = _fear_ticks([0.8, None, 0.8, 0.8])
    assert analyze_psychology(hole).component("fear").persistence == Persistence(0.75, 2, 3, 2)


def test_the_persistence_threshold_is_explicit_and_adjustable():
    ticks = _fear_ticks([0.8, 0.95, 0.95, 0.8])
    assert analyze_psychology(ticks).persistence_threshold == DEFAULT_PERSISTENCE_THRESHOLD == 0.75
    assert analyze_psychology(ticks).component("fear").persistence == Persistence(0.75, 4, 1, 1)
    assert analyze_psychology(ticks, persistence_threshold=0.9).component("fear").persistence == Persistence(0.9, 2, 2, 1)
    assert analyze_psychology(_fear_ticks([0.1, 0.2])).component("fear").persistence == Persistence(0.75, 0, None, 0)


# --- event-period comparison -------------------------------------------------------------------------


def test_event_periods_come_from_the_recorded_event_state():
    ticks = [_tick(1, P(fear=0.2), live=False), _tick(2, P(fear=0.8), live=True), _tick(3, P(fear=0.6), live=True),
             _tick(4, P(fear=0.4), live=False)]
    periods = analyze_psychology(ticks).event_periods
    assert (periods.source, periods.event_period_ticks, periods.other_period_ticks, periods.unclassified_ticks) == (
        "event_state", 2, 2, 0)
    fear = periods.components[0]
    assert fear == ComponentPeriodMeans("fear", (0.8 + 0.6) / 2, (0.2 + 0.4) / 2, (0.8 + 0.6) / 2 - (0.2 + 0.4) / 2)
    assert [m.component for m in periods.components] == list(COMPONENTS)
    assert periods.components[1] == ComponentPeriodMeans("fomo", 0.0, 0.0, 0.0)


def test_ticks_without_an_event_state_are_unclassified_not_guessed():
    ticks = [_tick(1, P(fear=0.2), live=False), _tick(2, P(fear=0.8), live=True), _tick(3, P(fear=0.5))]
    periods = analyze_psychology(ticks).event_periods
    assert (periods.event_period_ticks, periods.other_period_ticks, periods.unclassified_ticks) == (1, 1, 1)
    assert periods.components[0].event_period_mean == 0.8


def test_no_event_information_means_no_comparison():
    assert analyze_psychology(_fear_ticks([0.2, 0.4])).event_periods is None


def test_a_period_without_ticks_has_no_mean_and_no_difference():
    periods = analyze_psychology([_tick(1, P(fear=0.2), live=False), _tick(2, P(fear=0.4), live=False)]).event_periods
    assert periods.event_period_ticks == 0
    assert periods.components[0] == ComponentPeriodMeans("fear", None, (0.2 + 0.4) / 2, None)


def test_explicit_event_ticks_replace_the_recorded_event_state():
    ticks = [_tick(1, P(fear=0.2), live=True), _tick(2, P(fear=0.8), live=False), _tick(3, P(fear=0.6))]
    periods = analyze_psychology(ticks, event_ticks=[2, 3, 3, 99]).event_periods
    assert (periods.source, periods.event_period_ticks, periods.other_period_ticks, periods.unclassified_ticks) == (
        "event_ticks", 2, 1, 0)
    assert periods.components[0].event_period_mean == (0.8 + 0.6) / 2
    assert periods.components[0].other_period_mean == 0.2


# --- trading comparison ----------------------------------------------------------------------------


def test_trading_activity_on_the_same_ticks_grouped_by_dominant_component():
    ticks = [
        _tick(1, P(fear=0.9), [_fill("a", SELL), _fill("a", SELL), _fill("b", BUY)]),
        _tick(2, P(fear=0.7), [_fill("c", SELL)]),
        _tick(3, P(fomo=0.8), [_fill("a", BUY), _fill("x", BUY, wash=True), _fill("x", SELL, wash=True)]),
        _tick(4, P()),
    ]
    report = analyze_psychology(ticks, trader_count=4)
    assert _group(report, "fear").activity == TradingActivity(
        ticks=2, fills=4, buy_fills=1, sell_fills=3, fills_per_tick=2.0, active_traders_per_tick=1.5,
        participation_rate=1.5 / 4)
    assert _group(report, "fomo").activity == TradingActivity(1, 3, 2, 1, 3.0, 2.0, 2 / 4)  # wash legs count
    assert _group(report, NEUTRAL).activity == TradingActivity(1, 0, 0, 0, 0.0, 0.0, 0.0)
    assert _group(report, "conviction").activity == TradingActivity(0, 0, 0, 0, None, None, None)
    assert report.activity == TradingActivity(4, 7, 3, 4, 7 / 4, 5 / 4, 5 / 16)


def test_participation_needs_the_population_size():
    report = analyze_psychology([_tick(1, P(fear=0.5), [_fill("a")])])
    assert report.activity.participation_rate is None
    assert report.activity.active_traders_per_tick == 1.0


def test_ticks_without_psychology_are_left_out_of_the_trading_comparison():
    ticks = [_tick(1, P(fear=0.5), [_fill("a")]), _tick(2, None, [_fill("a"), _fill("b")])]
    assert analyze_psychology(ticks).activity.fills == 1


# --- missing psychology -------------------------------------------------------------------------------


def test_empty_input():
    report = analyze_psychology([])
    assert report == PsychologyReport(ticks=0, ticks_with_psychology=0, persistence_threshold=0.75, components=(),
                                      dominant=(), activity=None, event_periods=None)
    assert report.ticks_without_psychology == 0


def test_no_psychology_recorded_gives_no_statistics_rather_than_neutral_ones():
    report = analyze_psychology([_tick(1, live=True), _tick(2, live=False), _tick(3)])
    assert (report.ticks, report.ticks_with_psychology, report.ticks_without_psychology) == (3, 0, 3)
    assert report.components == () and report.dominant == ()
    assert report.activity is None and report.event_periods is None


def test_mixed_ticks_are_summarized_over_the_recorded_psychology_only():
    report = analyze_psychology(_fear_ticks([0.8, None, 0.6, None]))
    assert (report.ticks, report.ticks_with_psychology, report.ticks_without_psychology) == (4, 2, 2)
    fear = report.component("fear")
    assert fear.count == 2 and fear.mean == (0.8 + 0.6) / 2  # not diluted by invented zeros
    assert sum(g.ticks for g in report.dominant) == 2


# --- invalid input ------------------------------------------------------------------------------------


def test_duplicate_ticks_are_rejected():
    with pytest.raises(ValueError, match="duplicate tick 2"):
        analyze_psychology(_fear_ticks([0.1, 0.2]) + [_tick(2, P())])


def test_a_tick_carrying_something_other_than_a_psychology_state_is_rejected():
    bad = dataclasses.replace(_tick(3), psychology={"fear": 0.5})
    with pytest.raises(ValueError, match="tick 3: psychology must be a PsychologyState"):
        analyze_psychology([_tick(1, P()), bad])


@pytest.mark.parametrize("value", [math.nan, math.inf, -0.1, 1.5])
def test_corrupted_state_values_are_rejected_not_clamped(value):
    state = P(fear=0.5)
    object.__setattr__(state, "fomo", value)  # bypasses PsychologyState's own validation
    with pytest.raises(ValueError, match="tick 1: psychology.fomo"):
        analyze_psychology([_tick(1, state)])


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"persistence_threshold": 0.0}, "persistence_threshold"),
        ({"persistence_threshold": 1.5}, "persistence_threshold"),
        ({"persistence_threshold": math.nan}, "persistence_threshold"),
        ({"persistence_threshold": True}, "persistence_threshold"),
        ({"trader_count": 0}, "trader_count"),
        ({"trader_count": 2.0}, "trader_count"),
        ({"event_ticks": [1, 0]}, "event_ticks"),
        ({"event_ticks": [True]}, "event_ticks"),
        ({"event_ticks": ["3"]}, "event_ticks"),
    ],
)
def test_invalid_arguments_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        analyze_psychology(_fear_ticks([0.5]), **kwargs)


# --- determinism ---------------------------------------------------------------------------------------


def _mixed_run(n=60, seed=3):
    rng = random.Random(seed)
    ticks = []
    for t in range(1, n + 1):
        state = None if rng.random() < 0.1 else P(*(rng.choice([0.0, 0.5, rng.random()]) for _ in range(4)))
        fills = [_fill(f"t{rng.randint(1, 5)}", rng.choice([BUY, SELL])) for _ in range(rng.randint(0, 3))]
        ticks.append(_tick(t, state, fills, live=rng.random() < 0.3))
    return ticks


def test_same_input_same_report_and_inputs_untouched():
    ticks = _mixed_run()
    snapshot = list(ticks)
    first = analyze_psychology(ticks, trader_count=5)
    assert all(analyze_psychology(ticks, trader_count=5) == first for _ in range(5))
    assert ticks == snapshot and all(a is b for a, b in zip(ticks, snapshot))


def test_input_order_does_not_matter():
    ticks = _mixed_run()
    shuffled = list(ticks)
    random.Random(1).shuffle(shuffled)
    report = analyze_psychology(ticks, trader_count=5)
    assert analyze_psychology(list(reversed(ticks)), trader_count=5) == report
    assert analyze_psychology(shuffled, trader_count=5) == report
    assert analyze_psychology(tuple(ticks), trader_count=5) == report


def test_analysis_uses_no_global_randomness():
    ticks = _mixed_run()
    state = random.getstate()
    analyze_psychology(ticks, trader_count=5)
    assert random.getstate() == state


def test_results_are_frozen():
    report = analyze_psychology(_mixed_run())
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.ticks = 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.components[0].mean = 0.0
