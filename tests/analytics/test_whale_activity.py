"""Whale activity analytics (Phase 9, Step 3).

Unit-style: hand-built ticks and observations exercise the report's shape,
edge cases and error handling in isolation from a real simulation.
``test_whale_activity_simulation.py`` runs the same analytics against real
simulator output, including cohorts, psychology, events and manipulation.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

import crypto_simulator.analytics.whale_activity as whale_activity_module
from crypto_simulator.analytics.whale_activity import (
    COVERAGE_COMPLETE,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    BehaviorActivity,
    WhaleActivityReport,
    analyze_whale_activity,
)
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.whale import WhaleAttempt, WhaleBehavior, WhaleTrade
from tests.analytics.test_market import _fill
from tests.analytics.test_whales import _allocation, _observation


def _trade(whale_id="w", side="buy", quantity=10.0, impact=1.0):
    return WhaleTrade(whale_id=whale_id, side=side, quantity=quantity, price_impact=impact)


def _tick(number, observations=(), *, background=100.0, trader_trades=()):
    """A tick whose ``whale_trades`` are derived from ``observations`` the
    way ``CoinSimulator`` actually builds them (one entry per attempted
    whale, in whale-list order, whatever the outcome) and whose ``volume``
    is ``background`` plus every whale and trader quantity — so
    ``analyze_market``'s totals are meaningful without hand-summing them
    in every test."""
    whale_trades = tuple(o.trade for o in observations if o.trade is not None)
    trader_trades = tuple(trader_trades)
    volume = background + sum(t.quantity for t in whale_trades) + sum(t.quantity for t in trader_trades)
    return SimulationTick(tick=number, timestamp="t", price=2.0, market_cap=0.0, volume=volume,
                          whale_trades=whale_trades, trader_trades=trader_trades,
                          whale_observations=tuple(observations))


def _member(whale_id, cohort_id, *, trade=None, behavior=WhaleBehavior.ACCUMULATE, after=None):
    observation = _observation(whale_id, behavior=behavior, trade=trade, after=after,
                               attempt=WhaleAttempt.FILLED if trade is not None else WhaleAttempt.INACTIVE)
    return dataclasses.replace(observation, cohort_id=cohort_id)


# --- basic shape -----------------------------------------------------------------------------------


def test_empty_input_is_an_empty_report_with_no_coverage():
    report = analyze_whale_activity([])
    assert report.ticks == 0 and report.observed_ticks == 0
    assert report.coverage == COVERAGE_NONE
    assert report.whale_volume is None
    assert report.total_market_volume == 0.0 and report.participant_volume == 0.0
    assert report.whales == () and report.cohorts == ()
    assert report.behaviors == tuple(
        BehaviorActivity(behavior, 0, 0, 0.0, 0.0, 0.0, 0.0) for behavior in WhaleBehavior
    )


def test_ticks_with_no_whale_observations_report_no_coverage_not_zeros():
    report = analyze_whale_activity([_tick(1), _tick(2)])
    assert report.ticks == 2 and report.observed_ticks == 0
    assert report.coverage == COVERAGE_NONE
    assert report.whales == () and report.whale_volume is None
    assert report.whale_volume_share_of_total is None
    assert report.whale_volume_share_of_participants is None


def test_one_funded_whale_with_a_single_buy_fill():
    obs = _observation("w1", trade=_trade("w1", "buy", 10.0), attempt=WhaleAttempt.FILLED)
    report = analyze_whale_activity([_tick(1, [obs])])
    assert report.coverage == COVERAGE_COMPLETE
    assert report.whale_ids == ("w1",)
    w = report.whale("w1")
    assert w.summary.total_volume == 10.0
    assert w.first_fill_tick == w.last_fill_tick == 1
    assert w.average_fill_size == 10.0
    assert w.volume_share_of_whale_volume == 1.0


def test_multiple_whales_are_ordered_by_id():
    zulu = _observation("zulu", trade=_trade("zulu", "buy", 5.0))
    alpha = _observation("alpha", trade=_trade("alpha", "sell", 3.0))
    report = analyze_whale_activity([_tick(1, [zulu, alpha])])
    assert report.whale_ids == ("alpha", "zulu")


def test_unfunded_whale_reports_no_allocation_gap_or_target_reaching():
    obs = _observation("w", funded=False, before=None, after=None, cash=None,
                       trade=_trade("w", "sell", 4.0))
    w = analyze_whale_activity([_tick(1, [obs])]).whale("w")
    assert w.summary.funded is False
    assert w.allocation_gap is None and w.target_reaching is None


def test_buy_only_and_sell_only_activity_are_kept_apart():
    buy_obs = _observation("buyer", trade=_trade("buyer", "buy", 6.0))
    sell_obs = _observation("seller", trade=_trade("seller", "sell", 4.0))
    report = analyze_whale_activity([_tick(1, [buy_obs, sell_obs])])
    buyer, seller = report.whale("buyer"), report.whale("seller")
    assert buyer.summary.buy_volume == 6.0 and buyer.summary.sell_volume == 0.0
    assert seller.summary.sell_volume == 4.0 and seller.summary.buy_volume == 0.0


def test_mixed_buy_and_sell_activity_tracks_first_and_last_fill():
    ticks = [_tick(1, [_observation("w", trade=_trade("w", "buy", 10.0))]),
             _tick(2, [_observation("w", trade=None, attempt=WhaleAttempt.INACTIVE)]),
             _tick(3, [_observation("w", trade=_trade("w", "sell", 4.0))])]
    w = analyze_whale_activity(ticks).whale("w")
    assert w.summary.net_coin_flow == 6.0
    assert w.first_fill_tick == 1 and w.last_fill_tick == 3
    assert w.average_fill_size == pytest.approx((10.0 + 4.0) / 2)


# --- volume ------------------------------------------------------------------------------------------


def test_whale_volume_and_market_shares_are_computed_from_the_same_ticks():
    obs = _observation("w", trade=_trade("w", "buy", 20.0))
    report = analyze_whale_activity([_tick(1, [obs], background=80.0)])
    assert report.whale_volume == 20.0
    assert report.total_market_volume == 100.0
    assert report.participant_volume == 20.0
    assert report.whale_volume_share_of_total == pytest.approx(0.2)
    assert report.whale_volume_share_of_participants == 1.0


def test_zero_market_volume_yields_no_share_rather_than_a_manufactured_ratio():
    obs = _observation("w", trade=None, attempt=WhaleAttempt.INACTIVE)
    report = analyze_whale_activity([_tick(1, [obs], background=0.0)])
    assert report.total_market_volume == 0.0 and report.participant_volume == 0.0
    assert report.whale_volume == 0.0
    assert report.whale_volume_share_of_total is None
    assert report.whale_volume_share_of_participants is None


def test_wash_volume_counts_toward_total_market_volume_but_never_participant_or_whale_volume():
    whale_obs = _observation("w", trade=_trade("w", "buy", 10.0))
    wash_buy = _fill("wash_trader", 5.0, wash=True)
    wash_sell = _fill("wash_trader", 5.0, side=TradeAction.SELL, wash=True)
    report = analyze_whale_activity(
        [_tick(1, [whale_obs], background=50.0, trader_trades=[wash_buy, wash_sell])]
    )
    assert report.whale_volume == 10.0
    assert report.participant_volume == 10.0
    assert report.total_market_volume == 50.0 + 10.0 + 5.0 + 5.0


def test_organic_trader_volume_counts_toward_participants_but_not_whale_volume():
    whale_obs = _observation("w", trade=_trade("w", "buy", 10.0))
    organic = _fill("retail", 8.0)
    report = analyze_whale_activity([_tick(1, [whale_obs], background=0.0, trader_trades=[organic])])
    assert report.whale_volume == 10.0
    assert report.participant_volume == 18.0
    assert report.whale_volume_share_of_participants == pytest.approx(10.0 / 18.0)


# --- behavior aggregation ------------------------------------------------------------------------------


def test_behavior_aggregation_groups_by_the_behavior_in_force():
    acc = _observation("a", behavior=WhaleBehavior.ACCUMULATE, trade=_trade("a", "buy", 5.0))
    dist = _observation("d", behavior=WhaleBehavior.DISTRIBUTE, trade=_trade("d", "sell", 3.0))
    neutral = _observation("n", behavior=WhaleBehavior.NEUTRAL, trade=None, attempt=WhaleAttempt.INACTIVE)
    report = analyze_whale_activity([_tick(1, [acc, dist, neutral])])
    by_behavior = {activity.behavior: activity for activity in report.behaviors}
    assert by_behavior[WhaleBehavior.ACCUMULATE].total_volume == 5.0
    assert by_behavior[WhaleBehavior.DISTRIBUTE].total_volume == 3.0
    assert by_behavior[WhaleBehavior.NEUTRAL].fill_count == 0
    assert by_behavior[WhaleBehavior.NEUTRAL].observation_ticks == 1


def test_a_behavior_transition_moves_which_bucket_a_ticks_fill_lands_in():
    accumulating = _observation("w", behavior=WhaleBehavior.ACCUMULATE, trade=_trade("w", "buy", 4.0))
    distributing = _observation("w", behavior=WhaleBehavior.DISTRIBUTE, trade=_trade("w", "sell", 2.0))
    report = analyze_whale_activity([_tick(1, [accumulating]), _tick(2, [distributing])])
    by_behavior = {activity.behavior: activity for activity in report.behaviors}
    assert by_behavior[WhaleBehavior.ACCUMULATE].buy_volume == 4.0
    assert by_behavior[WhaleBehavior.DISTRIBUTE].sell_volume == 2.0
    assert by_behavior[WhaleBehavior.NEUTRAL].observation_ticks == 0


# --- allocation gap -------------------------------------------------------------------------------------


def test_allocation_gap_stats_use_only_observations_that_carry_a_target():
    with_target = _observation("w", after=_allocation(0.4, target=0.6))
    without_target = _observation("w", after=_allocation(0.4, target=None))
    report = analyze_whale_activity([_tick(1, [with_target]), _tick(2, [without_target])])
    stats = report.whale("w").allocation_gap
    assert stats.sample_count == 1
    assert stats.mean_signed_gap == pytest.approx(0.2)
    assert stats.mean_absolute_gap == pytest.approx(0.2)
    assert stats.max_absolute_gap == pytest.approx(0.2)


def test_a_whale_without_any_targeted_observation_reports_no_allocation_gap_stats():
    obs = _observation("w", after=_allocation(0.4, target=None))
    assert analyze_whale_activity([_tick(1, [obs])]).whale("w").allocation_gap is None


def test_allocation_gap_stats_include_dormant_neutral_ticks():
    """A gap is a portfolio fact whatever the current behavior; only
    target-*reaching* excludes dormant ticks (see below)."""
    dormant = _observation("w", behavior=WhaleBehavior.NEUTRAL, after=_allocation(0.3, target=0.6))
    stats = analyze_whale_activity([_tick(1, [dormant])]).whale("w").allocation_gap
    assert stats.sample_count == 1
    assert stats.mean_signed_gap == pytest.approx(0.3)


def test_allocation_gap_stats_over_multiple_ticks():
    ticks = [
        _tick(1, [_observation("w", after=_allocation(0.2, target=0.5))]),
        _tick(2, [_observation("w", after=_allocation(0.6, target=0.5))]),
    ]
    stats = analyze_whale_activity(ticks).whale("w").allocation_gap
    assert stats.sample_count == 2
    assert stats.max_absolute_gap == pytest.approx(0.3)
    assert stats.mean_signed_gap == pytest.approx((0.3 + -0.1) / 2)


# --- target reaching -------------------------------------------------------------------------------------


def test_target_reaching_reports_the_first_tick_at_target():
    approaching = _observation("w", behavior=WhaleBehavior.ACCUMULATE, after=_allocation(0.3, target=0.5))
    reached = _observation("w", behavior=WhaleBehavior.ACCUMULATE, after=_allocation(0.5, target=0.5))
    report = analyze_whale_activity([_tick(1, [approaching]), _tick(2, [reached])])
    tr = report.whale("w").target_reaching
    assert tr.target_observation_count == 2
    assert tr.first_tick_at_target == 2
    assert tr.ticks_to_target == 1


def test_a_whale_that_never_reaches_its_target_reports_none_for_the_tick_fields():
    short = _observation("w", behavior=WhaleBehavior.ACCUMULATE, after=_allocation(0.2, target=0.5))
    tr = analyze_whale_activity([_tick(1, [short])]).whale("w").target_reaching
    assert tr.target_observation_count == 1
    assert tr.first_tick_at_target is None and tr.ticks_to_target is None


def test_a_whale_without_a_target_has_no_target_reaching_result():
    no_target = _observation("w", behavior=WhaleBehavior.ACCUMULATE, after=_allocation(0.4, target=None))
    assert analyze_whale_activity([_tick(1, [no_target])]).whale("w").target_reaching is None


def test_a_dormant_neutral_target_is_never_mistaken_for_an_active_pursuit():
    dormant_at_target = _observation("w", behavior=WhaleBehavior.NEUTRAL, after=_allocation(0.5, target=0.5))
    assert analyze_whale_activity([_tick(1, [dormant_at_target])]).whale("w").target_reaching is None


def test_a_dormant_stretch_between_directional_observations_is_excluded_from_the_count():
    directional_1 = _observation("w", behavior=WhaleBehavior.ACCUMULATE, after=_allocation(0.2, target=0.5))
    dormant = _observation("w", behavior=WhaleBehavior.NEUTRAL, after=_allocation(0.2, target=0.5))
    directional_2 = _observation("w", behavior=WhaleBehavior.ACCUMULATE, after=_allocation(0.5, target=0.5))
    ticks = [_tick(1, [directional_1]), _tick(2, [dormant]), _tick(3, [directional_2])]
    tr = analyze_whale_activity(ticks).whale("w").target_reaching
    assert tr.target_observation_count == 2  # the dormant tick does not count
    assert tr.first_tick_at_target == 3
    assert tr.ticks_to_target == 2  # measured from the first *directional* observation, tick 1


# --- cohorts ---------------------------------------------------------------------------------------------


def test_a_one_member_cohort_reports_no_co_fill():
    solo = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    cohort = analyze_whale_activity([_tick(1, [solo])]).cohort("c1")
    assert cohort.member_count == 1
    assert cohort.co_fill is None


def test_two_members_filling_the_same_side_on_one_tick_is_a_same_side_co_fill():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c1", trade=_trade("b", "buy", 3.0))
    cf = analyze_whale_activity([_tick(1, [a, b])]).cohort("c1").co_fill
    assert (cf.eligible_member_ticks, cf.co_fill_member_ticks) == (2, 2)
    assert cf.co_fill_ratio == 1.0
    assert (cf.simultaneous_fill_ticks, cf.same_side_simultaneous_ticks, cf.mixed_side_simultaneous_ticks) == (1, 1, 0)


def test_two_members_filling_opposite_sides_on_one_tick_is_a_mixed_co_fill():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c1", trade=_trade("b", "sell", 3.0))
    cf = analyze_whale_activity([_tick(1, [a, b])]).cohort("c1").co_fill
    assert cf.mixed_side_simultaneous_ticks == 1 and cf.same_side_simultaneous_ticks == 0


def test_members_filling_on_separate_ticks_are_not_a_co_fill():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c1", trade=_trade("b", "buy", 3.0))
    cf = analyze_whale_activity([_tick(1, [a]), _tick(2, [b])]).cohort("c1").co_fill
    assert cf.eligible_member_ticks == 2
    assert cf.co_fill_member_ticks == 0
    assert cf.co_fill_ratio == 0.0
    assert cf.simultaneous_fill_ticks == 0


def test_no_member_filling_reports_a_real_zero_ratio_not_none():
    a = _member("a", "c1", trade=None, behavior=WhaleBehavior.NEUTRAL)
    b = _member("b", "c1", trade=None, behavior=WhaleBehavior.NEUTRAL)
    cf = analyze_whale_activity([_tick(1, [a, b])]).cohort("c1").co_fill
    assert cf.eligible_member_ticks == 2
    assert cf.co_fill_member_ticks == 0
    assert cf.co_fill_ratio == 0.0


def test_all_members_filling_together_is_a_full_co_fill():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c1", trade=_trade("b", "buy", 3.0))
    c = _member("c", "c1", trade=_trade("c", "sell", 1.0))
    cf = analyze_whale_activity([_tick(1, [a, b, c])]).cohort("c1").co_fill
    assert cf.co_fill_ratio == 1.0
    assert cf.mixed_side_simultaneous_ticks == 1


def test_multiple_cohorts_are_kept_separate():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c2", trade=_trade("b", "buy", 3.0))
    report = analyze_whale_activity([_tick(1, [a, b])])
    assert report.cohort_ids == ("c1", "c2")
    assert report.cohort("c1").total_volume == 5.0
    assert report.cohort("c2").total_volume == 3.0


def test_a_whale_outside_every_cohort_is_excluded_from_cohorts():
    solo = _observation("solo", trade=_trade("solo", "buy", 5.0))
    report = analyze_whale_activity([_tick(1, [solo])])
    assert report.cohorts == ()
    assert report.whale("solo").cohort_id is None


def test_cohort_active_member_count_only_counts_whales_that_actually_filled():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c1", trade=None, behavior=WhaleBehavior.NEUTRAL)
    cohort = analyze_whale_activity([_tick(1, [a, b])]).cohort("c1")
    assert cohort.member_count == 2 and cohort.active_member_count == 1


def test_cohort_volume_share_of_whale_volume():
    member = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    outsider = _observation("solo", trade=_trade("solo", "buy", 5.0))
    cohort = analyze_whale_activity([_tick(1, [member, outsider])]).cohort("c1")
    assert cohort.volume_share_of_whale_volume == pytest.approx(0.5)


def test_partial_observation_coverage_within_a_cohort_still_counts_observation_ticks():
    a = _member("a", "c1", trade=_trade("a", "buy", 5.0))
    b = _member("b", "c1", trade=_trade("b", "buy", 3.0))
    report = analyze_whale_activity([_tick(1, [a]), _tick(2, [b])])
    assert report.cohort("c1").observation_ticks == 2


# --- data integrity -------------------------------------------------------------------------------------


def test_duplicate_whale_ids_on_one_tick_are_rejected_not_merged():
    both = (_observation("dup", trade=_trade("dup", "buy", 1.0)),
            _observation("dup", trade=_trade("dup", "sell", 1.0)))
    with pytest.raises(ValueError, match="more than once"):
        analyze_whale_activity([_tick(1, both)])


def test_duplicate_tick_numbers_are_rejected():
    ticks = [_tick(1, [_observation("w")]), _tick(1, [_observation("w")])]
    with pytest.raises(ValueError, match="duplicate tick"):
        analyze_whale_activity(ticks)


def test_non_simulation_ticks_are_rejected():
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_whale_activity([{"tick": 1}])


def test_partial_observation_coverage_is_reported_and_the_observed_subset_is_analysed():
    observed = _tick(1, [_observation("w", trade=_trade("w", "buy", 4.0))])
    unobserved = _tick(2)
    report = analyze_whale_activity([observed, unobserved])
    assert report.ticks == 2 and report.observed_ticks == 1
    assert report.coverage == COVERAGE_PARTIAL
    assert report.whale_volume == 4.0
    assert report.whale("w").summary.total_volume == 4.0


def test_missing_observations_are_never_treated_as_zero_whale_activity():
    report = analyze_whale_activity([_tick(1), _tick(2)])
    assert report.coverage == COVERAGE_NONE
    assert report.whale_volume is None


def test_a_nonfinite_price_is_rejected():
    bad = SimulationTick(tick=1, timestamp="t", price=float("nan"), market_cap=0.0, volume=0.0)
    with pytest.raises(ValueError):
        analyze_whale_activity([bad])


def test_the_report_and_its_nested_dataclasses_are_frozen():
    report = analyze_whale_activity([_tick(1, [_observation("w", trade=_trade("w", "buy", 1.0))])])
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.ticks = 5
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.whales[0].first_fill_tick = 0
    assert isinstance(report, WhaleActivityReport)


# --- purity and determinism -------------------------------------------------------------------------------


def test_analysis_is_pure_and_order_independent():
    a = _observation("a", trade=_trade("a", "buy", 5.0))
    b = _observation("b", trade=_trade("b", "sell", 2.0))
    ticks = [_tick(1, [a]), _tick(2, [b])]
    snapshot = list(ticks)
    forward = analyze_whale_activity(ticks)
    backward = analyze_whale_activity(list(reversed(ticks)))
    assert forward == backward == analyze_whale_activity(ticks)
    assert ticks == snapshot


def test_repeated_analysis_of_the_same_ticks_is_identical():
    ticks = [_tick(1, [_observation("w", trade=_trade("w", "buy", 3.0))])]
    assert analyze_whale_activity(ticks) == analyze_whale_activity(ticks)


# --- import hygiene and no causal claims (mirrors test_market_simulation.py) --------------------------------


def _names(path):
    tree = ast.parse(Path(path).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    return imported, used


def test_the_module_only_reads_records():
    imported, used = _names(whale_activity_module.__file__)
    assert imported <= {
        "__future__", "math", "dataclasses", "typing",
        "crypto_simulator.analytics._series", "crypto_simulator.analytics.market",
        "crypto_simulator.analytics.whales", "crypto_simulator.core.coin_simulator",
        "crypto_simulator.core.whale",
    }
    # Nothing that could run, steer, trade, reseed or read psychology.
    forbidden = {"random", "_rng", "step", "run", "set_price", "maybe_trade", "decide", "set_behavior",
                "set_intent_strength", "deposit_cash", "withdraw_cash", "deposit_coins", "withdraw_coins",
                "buy", "sell", "observe", "complete_observation", "psychology"}
    assert not used & forbidden, used & forbidden
    assert "random" not in imported


def test_the_module_makes_no_causal_claims():
    text = Path(whale_activity_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "signal", "predict"):
        assert phrase not in text, phrase
