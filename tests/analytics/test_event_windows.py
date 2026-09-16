"""Event-window market path analytics (Phase 9, Step 4).

Unit-style: hand-built ticks and events exercise the four-window split,
boundary exactness, missing-data handling and error cases in isolation.
``test_event_windows_simulation.py`` runs the same analytics against real
simulator output.
"""

import dataclasses

import pytest

from crypto_simulator.analytics.event_windows import (
    CategoryActivity,
    EventPathSummary,
    EventWindow,
    EventWindowReport,
    analyze_event_windows,
)
from crypto_simulator.core.events import MarketEvent
from crypto_simulator.core.traders.base import TradeAction
from tests.analytics.test_events import _event, _fill, _flat, _tick

BUY, SELL = TradeAction.BUY, TradeAction.SELL


def _report(ticks, events, **kwargs):
    return analyze_event_windows(ticks, events, **kwargs)


def _one(ticks, event, **kwargs):
    report = _report(ticks, [event], **kwargs)
    return report.event(event.event_id)


# --- basic shape -----------------------------------------------------------------------------------


def test_empty_input_is_an_empty_report():
    report = analyze_event_windows([], [])
    assert report == EventWindowReport(ticks=0, events=(), categories=())


def test_ticks_with_no_events_reports_nothing_to_analyse():
    report = _report(_flat(20), [])
    assert report.ticks == 20 and report.events == () and report.categories == ()


def test_one_event_is_reported():
    event = _event(start_tick=5, duration=3, decay_ticks=2)
    report = _report(_flat(30), [event])
    assert report.event_ids == ("e",)


def test_multiple_events_are_ordered_by_start_tick_then_id():
    late = _event("z", start_tick=20, duration=2, decay_ticks=0)
    early = _event("a", start_tick=5, duration=2, decay_ticks=0)
    report = _report(_flat(30), [late, early])
    assert report.event_ids == ("a", "z")


# --- windows: boundaries and no double counting ------------------------------------------------------


def test_active_window_is_exactly_start_to_last_active_tick():
    event = _event(start_tick=10, duration=4, decay_ticks=2)  # last_active_tick = 13
    path = _one(_flat(40), event)
    assert (path.active.requested_start, path.active.requested_end) == (10, 13)
    assert path.active.ticks_requested == 4


def test_decay_window_is_exactly_the_decaying_phase():
    event = _event(start_tick=10, duration=4, decay_ticks=3)  # decaying 14..16
    path = _one(_flat(40), event)
    assert (path.decay.requested_start, path.decay.requested_end) == (14, 16)
    assert path.decay.ticks_requested == 3


def test_zero_decay_ticks_means_no_decay_window_at_all():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    path = _one(_flat(40), event)
    assert path.decay is None


def test_post_event_window_starts_exactly_at_expiration():
    event = _event(start_tick=10, duration=4, decay_ticks=3)  # expires_at = 17
    path = _one(_flat(40), event, post_window=5)
    assert (path.post_event.requested_start, path.post_event.requested_end) == (17, 21)


def test_pre_event_window_is_the_baseline_ticks_before_activation():
    event = _event(start_tick=20, duration=3, decay_ticks=0)
    path = _one(_flat(40), event, baseline_window=6)
    assert (path.pre_event.requested_start, path.pre_event.requested_end) == (14, 19)


def test_pre_event_window_clamps_at_tick_one_rather_than_going_negative():
    event = _event(start_tick=5, duration=3, decay_ticks=0)
    path = _one(_flat(40), event, baseline_window=10)
    assert (path.pre_event.requested_start, path.pre_event.requested_end) == (1, 4)
    assert path.pre_event.ticks_requested == 4  # clamped, not the nominal 10


def test_an_event_starting_on_tick_one_has_no_pre_event_window():
    event = _event(start_tick=1, duration=3, decay_ticks=0)
    path = _one(_flat(40), event)
    assert path.pre_event is None


def test_effect_window_spans_active_plus_decay_and_no_further():
    event = _event(start_tick=10, duration=4, decay_ticks=3)
    path = _one(_flat(40), event)
    assert (path.effect.requested_start, path.effect.requested_end) == (10, 16)


def test_no_tick_is_double_counted_across_pre_active_decay_post():
    event = _event(start_tick=10, duration=4, decay_ticks=3)
    path = _one(_flat(50), event, baseline_window=5, post_window=4)
    spans = [
        range(path.pre_event.requested_start, path.pre_event.requested_end + 1),
        range(path.active.requested_start, path.active.requested_end + 1),
        range(path.decay.requested_start, path.decay.requested_end + 1),
        range(path.post_event.requested_start, path.post_event.requested_end + 1),
    ]
    seen = set()
    for span in spans:
        ticks = set(span)
        assert not (ticks & seen), "a tick appeared in more than one window"
        seen |= ticks
    # Contiguous: pre ends right before active starts, active right before
    # decay, decay right before post.
    assert path.pre_event.requested_end + 1 == path.active.requested_start
    assert path.active.requested_end + 1 == path.decay.requested_start
    assert path.decay.requested_end + 1 == path.post_event.requested_start


def test_no_tick_is_double_counted_when_decay_is_absent():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    path = _one(_flat(50), event, baseline_window=5, post_window=4)
    assert path.decay is None
    assert path.active.requested_end + 1 == path.post_event.requested_start


# --- prices ----------------------------------------------------------------------------------------


def test_first_last_high_low_come_straight_from_the_embedded_market_summary():
    prices = {10: 100.0, 11: 110.0, 12: 90.0, 13: 105.0}
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    path = _one(_flat(20, price=100.0, overrides=prices), event)
    m = path.active.market
    assert m.open_price == 100.0 and m.close_price == 105.0
    assert m.high_price == 110.0 and m.high_tick == 11
    assert m.low_price == 90.0 and m.low_tick == 12


def test_high_low_ties_go_to_the_earliest_tick():
    prices = {10: 100.0, 11: 120.0, 12: 120.0, 13: 100.0}
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    path = _one(_flat(20, price=100.0, overrides=prices), event)
    assert path.active.market.high_tick == 11


def test_a_window_with_no_recorded_ticks_reports_no_prices():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    ticks = [t for t in _flat(30) if not (10 <= t.tick <= 13)]  # active window entirely missing
    path = _one(ticks, event)
    assert path.active.ticks_observed == 0
    assert path.active.market.open_price is None and path.active.market.close_price is None
    assert path.active.complete is False


def test_a_partially_observed_window_is_marked_incomplete_not_padded():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    ticks = [t for t in _flat(30) if t.tick != 12]  # one tick missing from the active window
    path = _one(ticks, event)
    assert path.active.ticks_requested == 4 and path.active.ticks_observed == 3
    assert path.active.complete is False
    assert path.active.market.missing_tick_count == 1  # tick 12 is a gap between 11 and 13


# --- returns -----------------------------------------------------------------------------------------


def test_simple_and_log_returns_match_analyze_markets_own_definitions():
    import math
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    prices = {10: 100.0, 11: 105.0, 12: 110.0, 13: 121.0}
    path = _one(_flat(20, price=100.0, overrides=prices), event)
    m = path.active.market
    assert m.cumulative_return == pytest.approx(121.0 / 100.0 - 1.0)
    assert m.log_return == pytest.approx(math.log(121.0 / 100.0))


def test_a_single_observed_tick_gives_a_zero_return_not_a_missing_one():
    event = _event(start_tick=10, duration=1, decay_ticks=0)
    path = _one(_flat(20), event)
    assert path.active.ticks_observed == 1
    assert path.active.market.cumulative_return == 0.0


def test_zero_observed_ticks_gives_no_return_rather_than_zero():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    ticks = [t for t in _flat(30) if not (10 <= t.tick <= 13)]
    path = _one(ticks, event)
    assert path.active.market.cumulative_return is None


def test_returns_never_bridge_across_a_missing_tick_in_the_window():
    event = _event(start_tick=10, duration=5, decay_ticks=0)
    ticks = [t for t in _flat(30) if t.tick != 12]  # gap inside the active window
    path = _one(ticks, event)
    # 10,11 and 13,14 are each consecutive; 11->13 is not, so only two
    # returns exist rather than three (Step 1's no-bridging rule, reused).
    assert path.active.market.return_count == 2
    assert path.active.market.missing_tick_count == 1


# --- volume ------------------------------------------------------------------------------------------


def test_random_walk_volume_breakdown_is_present_per_window():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    ticks = _flat(30)
    path = _one(ticks, event)
    v = path.active.market.volume_breakdown
    assert v.total_volume == 4 * 100.0  # _flat's default per-tick volume
    assert v.background_volume == pytest.approx(v.total_volume)


def test_wash_volume_is_not_double_counted_in_an_event_window():
    fills = [_fill("wt", BUY, 5.0, wash=True), _fill("wt", SELL, 5.0, wash=True)]
    ticks = [_tick(t, 100.0, fills=fills if t == 11 else ()) for t in range(1, 21)]
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    path = _one(ticks, event)
    v = path.active.market.volume_breakdown
    assert v.wash_volume == 10.0
    assert v.participant_volume == 0.0  # wash is excluded from participant volume


def test_whale_volume_does_not_require_whale_observation_to_be_recorded():
    """VolumeBreakdown.whale_volume reads SimulationTick.whale_trades
    directly, which the simulator always populates when a whale trades —
    independent of the whale_observation flag."""
    from crypto_simulator.core.whale import WhaleTrade

    event = _event(start_tick=10, duration=4, decay_ticks=0)
    ticks = [_tick(t, 100.0, whales=(WhaleTrade("w", "buy", 50.0, 1.01),) if t == 11 else ())
            for t in range(1, 21)]
    path = _one(ticks, event)
    assert path.active.market.volume_breakdown.whale_volume == 50.0


def test_a_zero_volume_window_reports_a_real_zero():
    event = _event(start_tick=10, duration=4, decay_ticks=0)
    ticks = [_tick(t, 100.0, volume=0.0) for t in range(1, 21)]
    path = _one(ticks, event)
    assert path.active.market.volume_breakdown.total_volume == 0.0


# --- overlap -----------------------------------------------------------------------------------------


def test_overlapping_events_are_symmetric_and_keep_separate_windows():
    e1 = _event("a", start_tick=10, duration=5, decay_ticks=0)
    e2 = _event("b", start_tick=12, duration=5, decay_ticks=0)
    report = _report(_flat(40), [e1, e2])
    a, b = report.event("a"), report.event("b")
    assert a.overlapping_event_ids == ("b",) and b.overlapping_event_ids == ("a",)
    assert a.overlapping and b.overlapping
    assert a.overlap_count == 1
    assert a.active.requested_start != b.active.requested_start  # distinct windows


def test_non_overlapping_events_report_no_overlap():
    e1 = _event("a", start_tick=10, duration=3, decay_ticks=0)
    e2 = _event("b", start_tick=30, duration=3, decay_ticks=0)
    report = _report(_flat(40), [e1, e2])
    assert report.event("a").overlapping_event_ids == ()
    assert report.event("b").overlapping is False


def test_adjacent_events_that_only_touch_do_not_overlap():
    # e1 is live through tick 13 (expires_at - 1 == 13); e2 starts at 14.
    e1 = _event("a", start_tick=10, duration=4, decay_ticks=0)
    e2 = _event("b", start_tick=14, duration=3, decay_ticks=0)
    report = _report(_flat(40), [e1, e2])
    assert report.event("a").overlapping_event_ids == ()
    assert report.event("b").overlapping_event_ids == ()


def test_overlapping_events_of_different_categories_are_kept_separate():
    e1 = _event("a", start_tick=10, duration=5, decay_ticks=0)
    e2 = MarketEvent(event_id="b", category="other", severity=0.5, sentiment=0.1, volatility_boost=0.2,
                     attention=0.2, start_tick=12, duration=5)
    report = _report(_flat(40), [e1, e2])
    assert report.category_names == ("exchange_listing", "other")
    assert report.category("exchange_listing").event_count == 1
    assert report.category("other").event_count == 1


# --- provenance ----------------------------------------------------------------------------------------


def test_provenance_is_unknown_without_random_event_ids():
    event = _event(start_tick=10, duration=3, decay_ticks=0)
    path = _one(_flat(30), event)
    assert path.ground_truth.randomly_generated is None


def test_provenance_marks_scheduled_events_false():
    event = _event(start_tick=10, duration=3, decay_ticks=0)
    path = _one(_flat(30), event, random_event_ids=["someone-else"])
    assert path.ground_truth.randomly_generated is False


def test_provenance_marks_random_events_true():
    event = _event(start_tick=10, duration=3, decay_ticks=0)
    path = _one(_flat(30), event, random_event_ids=[event.event_id])
    assert path.ground_truth.randomly_generated is True


# --- categories ----------------------------------------------------------------------------------------


def test_category_aggregation_over_multiple_events():
    e1 = _event("a", start_tick=10, duration=4, decay_ticks=0, severity=0.6, sentiment=0.2)
    e2 = _event("b", start_tick=30, duration=4, decay_ticks=0, severity=0.4, sentiment=-0.2)
    report = _report(_flat(60), [e1, e2])
    category = report.category("exchange_listing")
    assert category.event_count == 2
    assert category.mean_severity == pytest.approx(0.5)
    assert category.mean_sentiment == pytest.approx(0.0)


def test_only_categories_with_at_least_one_event_are_listed():
    event = _event(start_tick=10, duration=3, decay_ticks=0)
    report = _report(_flat(30), [event])
    assert report.category_names == ("exchange_listing",)
    with pytest.raises(KeyError):
        report.category("nonexistent")


def test_multiple_distinct_categories_are_kept_apart():
    e1 = _event("a", start_tick=10, duration=3, decay_ticks=0)
    e2 = MarketEvent(event_id="b", category="regulatory", severity=0.5, sentiment=-0.3, volatility_boost=0.3,
                     attention=0.3, start_tick=20, duration=3)
    report = _report(_flat(40), [e1, e2])
    assert report.category_names == ("exchange_listing", "regulatory")


# --- integrity -------------------------------------------------------------------------------------------


def test_duplicate_event_ids_are_rejected():
    e1 = _event("dup", start_tick=10, duration=3, decay_ticks=0)
    e2 = _event("dup", start_tick=20, duration=3, decay_ticks=0)
    with pytest.raises(ValueError, match="duplicate event_id"):
        analyze_event_windows(_flat(40), [e1, e2])


def test_duplicate_tick_numbers_are_rejected():
    ticks = _flat(10)
    with pytest.raises(ValueError, match="duplicate tick"):
        analyze_event_windows(ticks + [ticks[2]], [])


def test_non_simulation_ticks_are_rejected():
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_event_windows([{"tick": 1}], [])


def test_an_event_starting_outside_the_ticks_is_skipped():
    event = _event(start_tick=100, duration=3, decay_ticks=0)
    report = _report(_flat(30), [event])
    assert report.events == ()


def test_the_report_and_its_nested_dataclasses_are_frozen():
    event = _event(start_tick=10, duration=3, decay_ticks=0)
    report = _report(_flat(30), [event])
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.ticks = 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.events[0].overlapping_event_ids = ()
    assert isinstance(report.events[0], EventPathSummary)
    assert isinstance(report.events[0].active, EventWindow)


def test_analysis_is_deterministic_and_order_independent():
    e1 = _event("a", start_tick=10, duration=4, decay_ticks=2)
    e2 = _event("b", start_tick=13, duration=3, decay_ticks=1)
    ticks = _flat(40)
    first = analyze_event_windows(ticks, [e1, e2])
    second = analyze_event_windows(list(reversed(ticks)), [e2, e1])
    assert first == second == analyze_event_windows(ticks, [e1, e2])
