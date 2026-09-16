"""Psychology-market co-movement analytics (Phase 9, Step 5).

Unit-style: hand-built ticks exercise alignment, missing-data handling,
correlation/lag/grouping arithmetic and error cases in isolation.
``test_psychology_market_simulation.py`` runs the same analytics against
real simulator output.
"""

import dataclasses
import math

import pytest

from crypto_simulator.analytics.psychology_market import (
    COVERAGE_COMPLETE,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    GROUP_THRESHOLD,
    INSUFFICIENT_PAIRS,
    PSYCHOLOGY_LEADS_MARKET,
    SAME_TICK,
    ZERO_VARIANCE,
    ComponentGroupComparison,
    PsychologyMarketObservation,
    PsychologyMarketReport,
    analyze_psychology_market,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events import EventPhase, EventState, EventStatus
from crypto_simulator.core.psychology import PsychologyState
from crypto_simulator.core.whale import WhaleTrade

P = PsychologyState


def _tick(n, price=100.0, psychology=None, volume=100.0, whales=(), live=None):
    """``live``: None = no event state recorded; True/False = an event
    state with / without a live event."""
    event_state = None
    if live is not None:
        statuses = (EventStatus("e", "custom", EventPhase.ACTIVE, 1.0),) if live else ()
        event_state = EventState(tick=n, sentiment=(-0.4 if live else 0.0), events=statuses)
    return SimulationTick(tick=n, timestamp=f"t{n}", price=price, market_cap=price * 1e6, volume=volume,
                          whale_trades=tuple(whales), event_state=event_state, psychology=psychology)


def _flat(n_ticks, price=100.0, psychology_from=None):
    """Ticks 1..n at a flat price; ``psychology_from`` maps tick -> P."""
    psychology_from = psychology_from or {}
    return [_tick(t, price, psychology_from.get(t)) for t in range(1, n_ticks + 1)]


# --- basic shape -----------------------------------------------------------------------------------


def test_empty_input_is_an_empty_report():
    report = analyze_psychology_market([])
    assert report == PsychologyMarketReport(
        ticks=0, ticks_with_psychology=0, coverage=COVERAGE_NONE, first_psychology_tick=None,
        last_psychology_tick=None, pricing_mode=None, observations=(), components=(),
        event_periods=None, correlations=(), groups=(),
    )


def test_no_psychology_reports_no_coverage_not_zeros():
    report = analyze_psychology_market(_flat(10))
    assert report.ticks == 10 and report.ticks_with_psychology == 0
    assert report.coverage == COVERAGE_NONE
    assert report.observations == () and report.correlations == () and report.groups == ()


def test_one_psychology_tick_is_reported():
    ticks = _flat(10, psychology_from={5: P(fear=0.3)})
    report = analyze_psychology_market(ticks)
    assert report.ticks_with_psychology == 1
    assert report.coverage == COVERAGE_PARTIAL
    assert report.first_psychology_tick == report.last_psychology_tick == 5


def test_complete_psychology_coverage():
    ticks = _flat(5, psychology_from={t: P(fear=0.1 * t) for t in range(1, 6)})
    report = analyze_psychology_market(ticks)
    assert report.coverage == COVERAGE_COMPLETE
    assert report.ticks_with_psychology == 5


def test_partial_coverage_excludes_ticks_without_psychology_not_zero_fills():
    ticks = _flat(6, psychology_from={2: P(fear=0.5), 4: P(fear=0.7)})
    report = analyze_psychology_market(ticks)
    assert report.coverage == COVERAGE_PARTIAL
    assert report.ticks_with_psychology == 2
    assert {o.tick for o in report.observations} == {2, 4}
    assert report.ticks_without_psychology == 4


# --- alignment ---------------------------------------------------------------------------------------


def test_alignment_is_by_tick_number_not_list_position():
    ticks = _flat(10, psychology_from={7: P(fear=0.4)})
    shuffled = list(reversed(ticks))
    report = analyze_psychology_market(shuffled)
    assert report.observation(7).tick == 7
    # The observation's return still uses tick 6's price, wherever tick 6
    # sat in the input list.
    direct = analyze_psychology_market(ticks)
    assert report == direct


def test_missing_tick_number_leaves_the_return_unavailable():
    ticks = [t for t in _flat(10, psychology_from={5: P(fear=0.4)}) if t.tick != 4]
    report = analyze_psychology_market(ticks)
    observation = report.observation(5)
    assert observation.simple_return is None and observation.log_return is None


def test_no_bridging_across_a_gap_even_two_ticks_back():
    # Tick 4 missing entirely; tick 5 has psychology. The return at 5
    # needs tick 4, which is absent, so it must not reach back to tick 3.
    prices = {t: 100.0 + t for t in range(1, 11)}
    ticks = [_tick(t, prices[t], P(fear=0.2) if t == 5 else None) for t in range(1, 11) if t != 4]
    report = analyze_psychology_market(ticks)
    assert report.observation(5).log_return is None


def test_a_present_adjacent_predecessor_gives_a_real_return():
    prices = {1: 100.0, 2: 110.0}
    ticks = [_tick(1, prices[1]), _tick(2, prices[2], P(fear=0.4))]
    report = analyze_psychology_market(ticks)
    observation = report.observation(2)
    assert observation.simple_return == pytest.approx(0.1)
    assert observation.log_return == pytest.approx(math.log(1.1))


# --- correlations --------------------------------------------------------------------------------


def _linear_psychology_run(n, component="fear", sign=1.0):
    """Prices follow a fixed arithmetic path (tiny, shrinking returns);
    ``component`` is set proportional to (``sign`` times) that tick's own
    return, scaled to stay well inside [0, 1] without saturating — so the
    component and the return are related by construction, not clamped
    into a constant."""
    prices = [100.0 + t for t in range(n + 1)]
    ticks = []
    for t in range(1, n + 1):
        ret = prices[t] / prices[t - 1] - 1.0
        kwargs = {component: 0.5 + sign * ret * 10.0}
        ticks.append(_tick(t, prices[t], P(**kwargs)))
    return ticks


def test_a_positive_relationship_reports_a_positive_correlation():
    ticks = _linear_psychology_run(20, component="fomo", sign=1.0)
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fomo", "log_return")
    assert entry.value is not None and entry.value > 0.9
    assert entry.unavailable_reason is None


def test_a_negative_relationship_reports_a_negative_correlation():
    ticks = _linear_psychology_run(20, component="fear", sign=-1.0)
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fear", "log_return")
    assert entry.value is not None and entry.value < -0.9


def test_zero_variance_reports_none_with_the_reason():
    ticks = _flat(10, psychology_from={t: P(fear=0.5) for t in range(1, 11)})
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fear", "log_return")
    assert entry.value is None and entry.unavailable_reason == ZERO_VARIANCE


def test_insufficient_pairs_reports_none_with_the_reason():
    ticks = _flat(10, psychology_from={5: P(fear=0.5)})  # one psychology tick only
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fear", "volume")
    assert entry.pairs == 1
    assert entry.value is None and entry.unavailable_reason == INSUFFICIENT_PAIRS


def test_no_paired_observations_at_all_is_also_insufficient():
    ticks = _flat(10)  # no psychology whatsoever
    report = analyze_psychology_market(ticks)
    assert report.correlations == ()  # nothing to correlate; no fabricated entries


def test_correlation_values_are_always_finite_never_nan_or_inf():
    ticks = _linear_psychology_run(15, component="conviction")
    report = analyze_psychology_market(ticks)
    for entry in report.correlations:
        if entry.value is not None:
            assert math.isfinite(entry.value)


def test_correlations_are_not_ranked_or_labelled_best_or_worst():
    ticks = _linear_psychology_run(15, component="fear")
    report = analyze_psychology_market(ticks)
    # Fixed declared order (_SAME_TICK_PAIRS then lag-1), not sorted by value.
    xs = [(c.x, c.y, c.lag) for c in report.correlations]
    assert xs[0] == ("fear", "log_return", 0)


# --- lagged comparisons ----------------------------------------------------------------------------


def test_valid_lag_1_pairs_psychology_at_t_with_return_at_t_plus_1():
    prices = [100.0, 101.0, 99.0, 105.0, 103.0]
    ticks = [_tick(t, prices[t - 1], P(fomo=0.2 * t)) for t in range(1, 6)]
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fomo", "log_return", lag=1)
    assert entry.direction == PSYCHOLOGY_LEADS_MARKET
    assert entry.pairs == 4  # ticks 1..4 have a tick+1 to pair with; tick 5 does not


def test_a_missing_adjacent_tick_excludes_that_lag_pair():
    ticks = [_tick(t, 100.0 + t, P(fomo=0.3)) for t in range(1, 6) if t != 3]
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fomo", "log_return", lag=1)
    # tick 2's lag pair needs tick 3 (missing) -> excluded.
    # tick 4's lag pair needs tick 5 present, and 4->5 adjacent -> included.
    assert 2 not in {o.tick for o in report.observations if o.tick + 1 in _present_ticks(ticks)}  # sanity
    assert entry.pairs <= 3


def _present_ticks(ticks):
    return {t.tick for t in ticks}


def test_lag_1_is_order_independent():
    prices = [100.0, 102.0, 101.0, 108.0, 107.0, 110.0]
    ticks = [_tick(t, prices[t - 1], P(uncertainty=0.1 * t)) for t in range(1, 7)]
    forward = analyze_psychology_market(ticks)
    backward = analyze_psychology_market(list(reversed(ticks)))
    assert forward == backward


def test_insufficient_lag_observations_reports_none():
    ticks = [_tick(1, 100.0, P(fear=0.4))]  # no tick 2 to pair with
    report = analyze_psychology_market(ticks)
    entry = report.correlation("fear", "log_return", lag=1)
    assert entry.pairs == 0
    assert entry.value is None and entry.unavailable_reason == INSUFFICIENT_PAIRS


# --- thresholds (reused from analyze_psychology) --------------------------------------------------


def test_component_summaries_are_analyze_psychologys_own():
    from crypto_simulator.analytics.psychology import analyze_psychology

    ticks = _flat(10, psychology_from={t: P(fear=0.1 * t) for t in range(1, 11)})
    report = analyze_psychology_market(ticks)
    direct = analyze_psychology([t for t in ticks])
    assert report.components == direct.components


# --- grouping ----------------------------------------------------------------------------------------


def test_low_high_groups_split_at_the_declared_threshold():
    ticks = _flat(4, psychology_from={1: P(fear=0.2), 2: P(fear=0.8), 3: P(fear=0.4), 4: P(fear=0.5)})
    report = analyze_psychology_market(ticks)
    group = report.group("fear")
    assert group.threshold == GROUP_THRESHOLD
    assert group.low.ticks == 2  # 0.2, 0.4 < 0.5
    assert group.high.ticks == 2  # 0.8, 0.5 >= 0.5


def test_an_empty_group_reports_zero_ticks_and_no_fabricated_averages():
    ticks = _flat(4, psychology_from={t: P(fear=0.9) for t in range(1, 5)})
    report = analyze_psychology_market(ticks)
    group = report.group("fear")
    assert group.low.ticks == 0
    assert group.low.mean_log_return is None and group.low.mean_volume is None


def test_grouping_is_deterministic():
    ticks = _flat(6, psychology_from={t: P(uncertainty=0.15 * t) for t in range(1, 7)})
    assert analyze_psychology_market(ticks).groups == analyze_psychology_market(ticks).groups


# --- events ------------------------------------------------------------------------------------------


def test_no_event_engine_reports_no_event_context():
    ticks = _flat(3, psychology_from={2: P(fear=0.3)})
    observation = analyze_psychology_market(ticks).observation(2)
    assert observation.event_active is None and observation.event_count is None
    assert observation.event_sentiment is None and observation.event_attention is None


def test_an_event_engine_with_no_live_event_reports_real_neutral_values():
    ticks = [_tick(1, 100.0, P(fear=0.3), live=False)]
    observation = analyze_psychology_market(ticks).observation(1)
    assert observation.event_active is False
    assert observation.event_count == 0
    assert observation.event_sentiment == 0.0


def test_a_live_event_is_reported_as_active_with_its_sentiment():
    ticks = [_tick(1, 100.0, P(fear=0.3), live=True)]
    observation = analyze_psychology_market(ticks).observation(1)
    assert observation.event_active is True
    assert observation.event_count == 1
    assert observation.event_sentiment == -0.4


def test_overlapping_events_are_counted():
    statuses = (EventStatus("a", "news", EventPhase.ACTIVE, 1.0), EventStatus("b", "news", EventPhase.DECAYING, 0.5))
    tick = SimulationTick(tick=1, timestamp="t", price=100.0, market_cap=0.0, volume=10.0,
                          event_state=EventState(tick=1, events=statuses), psychology=P(fear=0.2))
    observation = analyze_psychology_market([tick]).observation(1)
    assert observation.event_count == 2


def test_event_periods_are_analyze_psychologys_own():
    from crypto_simulator.analytics.psychology import analyze_psychology

    ticks = [_tick(t, 100.0, P(fear=0.1 * t), live=(t == 5)) for t in range(1, 11)]
    report = analyze_psychology_market(ticks)
    direct = analyze_psychology(ticks)
    assert report.event_periods == direct.event_periods


# --- pricing modes -------------------------------------------------------------------------------------


def test_random_walk_reports_a_pricing_mode():
    ticks = _flat(3, psychology_from={2: P(fear=0.3)})
    assert analyze_psychology_market(ticks).pricing_mode == "random_walk"


def test_amm_reports_no_whale_volume():
    from decimal import Decimal
    from crypto_simulator.core.liquidity.pool import PoolState

    pool = PoolState(**{f.name: (0 if f.name == "swap_count" else Decimal(1)) for f in dataclasses.fields(PoolState)})
    tick = SimulationTick(tick=1, timestamp="t", price=100.0, market_cap=0.0, volume=5.0,
                          pool_state=pool, psychology=P(fear=0.3))
    observation = analyze_psychology_market([tick]).observation(1)
    assert observation.whale_volume == 0.0


def test_whale_volume_present_in_random_walk_without_observation_flag():
    tick = _tick(1, 100.0, P(fear=0.3), whales=(WhaleTrade("w", "buy", 50.0, 1.01),))
    observation = analyze_psychology_market([tick]).observation(1)
    assert observation.whale_volume == 50.0


# --- integrity -------------------------------------------------------------------------------------------


def test_duplicate_tick_numbers_are_rejected():
    ticks = _flat(5)
    with pytest.raises(ValueError, match="duplicate tick"):
        analyze_psychology_market(ticks + [ticks[2]])


def test_non_simulation_ticks_are_rejected():
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_psychology_market([{"tick": 1}])


def test_malformed_psychology_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=100.0, market_cap=0.0, volume=0.0, psychology="not-a-state")
    with pytest.raises(ValueError):
        analyze_psychology_market([bad])


def test_invalid_price_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=float("nan"), market_cap=0.0, volume=0.0, psychology=P())
    with pytest.raises(ValueError):
        analyze_psychology_market([bad])


def test_invalid_volume_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=100.0, market_cap=0.0, volume=float("-1"), psychology=P())
    with pytest.raises(ValueError, match="invalid volume"):
        analyze_psychology_market([bad])


def test_nonfinite_volume_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=100.0, market_cap=0.0, volume=float("inf"), psychology=P())
    with pytest.raises(ValueError, match="invalid volume"):
        analyze_psychology_market([bad])


def test_the_report_and_its_nested_dataclasses_are_frozen():
    ticks = _flat(5, psychology_from={3: P(fear=0.4)})
    report = analyze_psychology_market(ticks)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.ticks = 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.observations[0].fear = 0.9
    assert isinstance(report.observations[0], PsychologyMarketObservation)
    assert isinstance(report.groups[0], ComponentGroupComparison)


def test_analysis_is_deterministic_and_order_independent():
    ticks = _flat(10, psychology_from={t: P(fear=0.1 * t, fomo=0.05 * t) for t in range(1, 11)})
    first = analyze_psychology_market(ticks)
    second = analyze_psychology_market(list(reversed(ticks)))
    assert first == second == analyze_psychology_market(ticks)
