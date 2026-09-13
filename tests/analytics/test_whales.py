"""Descriptive whale analytics (Phase 8, Step 7).

``analyze_whales`` reads the ``WhaleObservation`` records a run left on
its ticks and returns frozen summaries. It is post-processing: it mutates
nothing, draws nothing, and describes only what was recorded.
"""

import dataclasses
import math

import pytest

from crypto_simulator.analytics.whales import (
    BLOCKED_BY_COOLDOWN,
    BLOCKED_BY_INTERVAL,
    HELD_AT_TARGET,
    INACTIVE,
    NO_FILL,
    TICK_OUTCOMES,
    TRADED,
    AllocationPath,
    WhaleReport,
    WhaleSummary,
    analyze_whales,
    classify,
)
from crypto_simulator.core.coin_simulator import CoinSimulator, SimulationTick
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.whale import (
    TARGET_DEAD_ZONE,
    Whale,
    WhaleAllocation,
    WhaleAttempt,
    WhaleBehavior,
    WhaleObservation,
    WhaleTrade,
)
from crypto_simulator.services.coin_simulation import build_coin_simulator
from crypto_simulator.config import get_settings
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _acc(whale_id="acc", cash=400_000.0, coins=0.0, seed=21, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale(whale_id, coins, starting_cash=cash, behavior="accumulate", seed=seed, **kwargs)


def _dist(whale_id="dist", cash=0.0, coins=120_000.0, seed=22, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale(whale_id, coins, starting_cash=cash, behavior="distribute", seed=seed, **kwargs)


def _legacy(whale_id="legacy", holdings=50_000.0, seed=23):
    return Whale(whale_id, holdings, activity_probability=0.5, max_trade_fraction=0.01, seed=seed)


def _sim(whales, traders=None, observe=True, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0,
                         whale_observation=observe, **kwargs)


def _observation(whale_id="w", *, funded=True, behavior=WhaleBehavior.ACCUMULATE, intent=1.0,
                 phase=None, elapsed=None, price=2.0, before=None, after=None, cooldown=0,
                 interval=0, trade=None, attempt=WhaleAttempt.INACTIVE, cash=100.0, coins=100.0):
    return WhaleObservation(whale_id=whale_id, funded=funded, behavior=behavior,
                            intent_strength=intent, cycle_phase_index=phase,
                            cycle_phase_elapsed=elapsed, price=price, allocation_before=before,
                            allocation_after=after, cooldown_remaining=cooldown,
                            interval_remaining=interval, trade=trade, attempt=attempt,
                            cash=cash, coins=coins)


def _allocation(coin_fraction, target=None, price=2.0, portfolio=1000.0):
    gap = None if target is None else target - coin_fraction
    target_coins = None if target is None else target * portfolio / price
    return WhaleAllocation(price, portfolio, coin_fraction * portfolio, coin_fraction, target, gap,
                           target_coins)


def _tick(number, observations=()):
    return SimulationTick(tick=number, timestamp="t", price=2.0, market_cap=0.0, volume=0.0,
                          whale_observations=tuple(observations))


# --- classification -------------------------------------------------------------------------------


def test_a_fill_is_traded_whatever_else_was_true():
    trade = WhaleTrade("w", "buy", 10.0, 1.1)
    assert classify(_observation(trade=trade, attempt=WhaleAttempt.FILLED)) == TRADED
    assert classify(_observation(trade=trade, attempt=WhaleAttempt.FILLED,
                                 cooldown=5, interval=5)) == TRADED


def test_cooldown_takes_precedence_over_the_interval():
    blocked = WhaleAttempt.BLOCKED
    assert classify(_observation(cooldown=3, interval=5, attempt=blocked)) == BLOCKED_BY_COOLDOWN
    assert classify(_observation(cooldown=3, interval=0, attempt=blocked)) == BLOCKED_BY_COOLDOWN
    assert classify(_observation(cooldown=0, interval=5, attempt=blocked)) == BLOCKED_BY_INTERVAL


def test_a_recorded_hold_is_held_at_target():
    at_target = _allocation(0.5, target=0.5)
    assert classify(_observation(before=at_target, after=at_target,
                                 attempt=WhaleAttempt.HELD)) == HELD_AT_TARGET
    # An accumulator already past its target is stopped by the target too,
    # and the execution path records that the same way.
    past = _allocation(0.8, target=0.5)
    assert classify(_observation(before=past, after=past, attempt=WhaleAttempt.HELD)) == HELD_AT_TARGET
    below = _allocation(0.2, target=0.5)
    assert classify(_observation(behavior=WhaleBehavior.DISTRIBUTE, before=below, after=below,
                                 attempt=WhaleAttempt.HELD)) == HELD_AT_TARGET


def test_a_recorded_no_fill_is_a_no_fill_whatever_the_balances_look_like():
    """The balances cannot tell an exhausted reserve from an idle tick;
    the recorded attempt can, so it is what decides."""
    plenty = _allocation(0.1, target=0.9)
    assert classify(_observation(before=plenty, after=plenty, cash=1e9, coins=1e9,
                                 attempt=WhaleAttempt.NO_FILL)) == NO_FILL
    assert classify(_observation(before=plenty, after=plenty, cash=0.0, coins=0.0,
                                 attempt=WhaleAttempt.NO_FILL)) == NO_FILL


def test_a_zero_quantity_trade_record_is_a_no_fill_not_a_trade():
    empty = WhaleTrade("w", "sell", 0.0, 1.0)
    assert classify(_observation(funded=False, trade=empty, before=None, after=None,
                                 cash=None, coins=0.0, attempt=WhaleAttempt.NO_FILL)) == NO_FILL


def test_a_recorded_inactive_tick_is_inactive_even_with_money_to_spend():
    room = _allocation(0.1, target=0.9)
    assert classify(_observation(before=room, after=room, cash=1e9, coins=1e9,
                                 attempt=WhaleAttempt.INACTIVE)) == INACTIVE
    assert classify(_observation(funded=False, before=None, after=None, cash=None,
                                 coins=1_000.0, attempt=WhaleAttempt.INACTIVE)) == INACTIVE


def test_the_balances_alone_never_decide_between_no_fill_and_inactive():
    """Identical balances, opposite outcomes: only the recorded attempt
    separates them. This is the case the old balance-based inference got
    wrong for an exhausted reserve."""
    same = dict(before=_allocation(0.1, target=0.9), after=_allocation(0.1, target=0.9),
                cash=250_000.0, coins=1_000.0)
    assert classify(_observation(**same, attempt=WhaleAttempt.NO_FILL)) == NO_FILL
    assert classify(_observation(**same, attempt=WhaleAttempt.INACTIVE)) == INACTIVE


def test_no_fill_and_inactive_are_never_merged():
    assert NO_FILL != INACTIVE
    assert {NO_FILL, INACTIVE} <= set(TICK_OUTCOMES)


def test_every_observation_gets_exactly_one_outcome():
    sim = _sim([_acc(target_coin_fraction=0.6, cooldown_ticks=2, min_trade_interval_ticks=2),
                _dist(target_coin_fraction=0.3), _legacy()], traders=_all_five())
    report = analyze_whales(sim.run(300))
    for whale in report.whales:
        assert set(whale.outcome_ticks) == set(TICK_OUTCOMES)
        assert sum(whale.outcome_ticks.values()) == whale.observed_ticks == 300


# --- trade arithmetic ------------------------------------------------------------------------------


def test_counts_volumes_notional_and_vwap_are_the_recorded_fills():
    sim = _sim([_acc()], traders=_all_five())
    ticks = sim.run(200)
    whale = analyze_whales(ticks).whale("acc")
    fills = [o for t in ticks for o in t.whale_observations if o.trade is not None]
    assert whale.trade_count == len(fills) > 0
    assert whale.buy_count == len(fills) and whale.sell_count == 0
    assert whale.buy_volume == pytest.approx(math.fsum(o.trade.quantity for o in fills))
    assert whale.total_volume == pytest.approx(whale.buy_volume + whale.sell_volume)
    assert whale.notional == pytest.approx(math.fsum(o.trade.quantity * o.price for o in fills))
    assert whale.vwap == pytest.approx(whale.notional / whale.total_volume)


def test_vwap_lies_between_the_cheapest_and_dearest_fill():
    sim = _sim([_acc()], traders=_all_five())
    ticks = sim.run(200)
    prices = [o.price for t in ticks for o in t.whale_observations if o.trade is not None]
    whale = analyze_whales(ticks).whale("acc")
    assert min(prices) <= whale.vwap <= max(prices)


def test_net_flows_match_the_whales_actual_balance_change():
    whale_obj = _acc(cash=400_000.0, coins=50_000.0)
    sim = _sim([whale_obj])
    cash_before, coins_before = whale_obj.wallet.cash, whale_obj.wallet.coins
    summary = analyze_whales(sim.run(200)).whale("acc")
    assert whale_obj.wallet.coins - coins_before == pytest.approx(summary.net_coin_flow, abs=1e-6)
    assert whale_obj.wallet.cash - cash_before == pytest.approx(summary.net_cash_flow, abs=1e-6)


def test_a_distributor_reports_sells_and_a_positive_cash_flow():
    sim = _sim([_dist()])
    summary = analyze_whales(sim.run(200)).whale("dist")
    assert summary.sell_count == summary.trade_count > 0 and summary.buy_count == 0
    assert summary.net_coin_flow < 0 and summary.net_cash_flow > 0


def test_a_whale_that_never_traded_reports_no_vwap():
    sim = _sim([_acc(cash=0.0, coins=0.0)])
    summary = analyze_whales(sim.run(50)).whale("acc")
    assert summary.trade_count == 0 and summary.total_volume == 0.0
    assert summary.vwap is None and summary.net_coin_flow == 0.0 and summary.net_cash_flow == 0.0


# --- allocation path --------------------------------------------------------------------------------


def test_the_allocation_path_describes_the_recorded_allocations():
    sim = _sim([_acc(target_coin_fraction=0.6)])
    ticks = sim.run(200)
    path = analyze_whales(ticks).whale("acc").allocation
    fractions = [o.allocation_after.coin_fraction for t in ticks for o in t.whale_observations]
    assert path.ticks == len(fractions)
    assert path.first_coin_fraction == fractions[0] and path.last_coin_fraction == fractions[-1]
    assert path.min_coin_fraction == min(fractions) and path.max_coin_fraction == max(fractions)
    assert path.mean_coin_fraction == pytest.approx(math.fsum(fractions) / len(fractions))
    assert path.target_coin_fraction == 0.6


def test_ticks_at_target_and_max_gap_are_measured_against_the_target():
    sim = _sim([_acc(target_coin_fraction=0.5, activity_probability=1.0)])
    ticks = sim.run(200)
    path = analyze_whales(ticks).whale("acc").allocation
    gaps = [o.allocation_after.allocation_gap for t in ticks for o in t.whale_observations]
    assert path.ticks_at_target == sum(1 for g in gaps if abs(g) <= TARGET_DEAD_ZONE) > 0
    assert path.max_abs_gap == pytest.approx(max(abs(g) for g in gaps))


def test_a_well_behaved_whale_never_crossed_its_target():
    for whale in (_acc(target_coin_fraction=0.5), _dist(target_coin_fraction=0.4)):
        sim = _sim([whale], traders=_all_five())
        path = analyze_whales(sim.run(300)).whale(whale.whale_id).allocation
        assert path.crossed_target is False


def test_a_whale_without_a_target_reports_no_target_figures():
    sim = _sim([_acc()])
    path = analyze_whales(sim.run(100)).whale("acc").allocation
    assert path.target_coin_fraction is None
    assert path.ticks_at_target is None and path.max_abs_gap is None and path.crossed_target is None
    assert path.mean_coin_fraction is not None  # the composition itself is still described


def test_an_unfunded_whale_gets_no_allocation_path_rather_than_zeros():
    sim = _sim([_legacy()])
    summary = analyze_whales(sim.run(100)).whale("legacy")
    assert summary.funded is False and summary.allocation is None


# --- behaviour and cycle occupancy ---------------------------------------------------------------------


def test_behaviour_occupancy_counts_the_ticks_each_behaviour_was_in_force():
    cycle = [{"behavior": "accumulate", "duration": 5}, {"behavior": "neutral", "duration": 3},
             {"behavior": "distribute", "duration": 2}]
    whale = Whale("cyc", 100_000.0, starting_cash=500_000.0, activity_probability=0.5,
                  max_trade_fraction=0.005, seed=31, cycle=cycle)
    summary = analyze_whales(_sim([whale]).run(100)).whale("cyc")
    assert summary.behavior_ticks[WhaleBehavior.ACCUMULATE] == 50
    assert summary.behavior_ticks[WhaleBehavior.NEUTRAL] == 30
    assert summary.behavior_ticks[WhaleBehavior.DISTRIBUTE] == 20
    assert sum(summary.behavior_ticks.values()) == 100


def test_cycle_phase_occupancy_follows_the_configured_durations():
    cycle = [{"behavior": "accumulate", "duration": 5}, {"behavior": "neutral", "duration": 3},
             {"behavior": "distribute", "duration": 2}]
    whale = Whale("cyc", 100_000.0, starting_cash=500_000.0, activity_probability=0.5,
                  max_trade_fraction=0.005, seed=31, cycle=cycle)
    summary = analyze_whales(_sim([whale]).run(100)).whale("cyc")
    assert summary.phase_ticks == {0: 50, 1: 30, 2: 20}


def test_a_whale_without_a_cycle_reports_no_phase_occupancy():
    summary = analyze_whales(_sim([_acc()]).run(60)).whale("acc")
    assert summary.phase_ticks == {}
    assert summary.behavior_ticks[WhaleBehavior.ACCUMULATE] == 60


# --- tick outcomes in a real run ------------------------------------------------------------------------


def test_pacing_shows_up_as_blocked_ticks():
    whale = _acc(cash=1e9, activity_probability=1.0, cooldown_ticks=2, min_trade_interval_ticks=4)
    summary = analyze_whales(_sim([whale]).run(50)).whale("acc")
    assert summary.traded_ticks == 10  # one trade every five ticks
    assert summary.blocked_by_cooldown_ticks == 20 and summary.blocked_by_interval_ticks == 20
    assert summary.inactive_ticks == 0 and summary.held_at_target_ticks == 0


def test_a_whale_at_its_target_shows_up_as_held_at_target():
    whale = _acc(cash=50_000.0, coins=25_000.0, target_coin_fraction=0.5, activity_probability=1.0)
    summary = analyze_whales(_sim([whale]).run(40)).whale("acc")
    assert summary.held_at_target_ticks > 0
    assert summary.held_at_target_ticks + summary.traded_ticks == 40


def test_a_whale_with_no_cash_shows_up_as_no_fill():
    whale = _acc(cash=0.0, coins=0.0, activity_probability=1.0)
    summary = analyze_whales(_sim([whale]).run(30)).whale("acc")
    assert summary.no_fill_ticks == 30 and summary.traded_ticks == 0 and summary.inactive_ticks == 0


def test_a_whale_that_rarely_acts_shows_up_as_inactive():
    whale = _acc(cash=1e9, activity_probability=0.0)
    summary = analyze_whales(_sim([whale]).run(30)).whale("acc")
    assert summary.inactive_ticks == 30 and summary.traded_ticks == 0


# --- report shape, validation and purity -------------------------------------------------------------------


def test_the_report_covers_every_observed_whale_ordered_by_id():
    sim = _sim([_dist("zulu"), _acc("alpha"), _legacy("mike")])
    report = analyze_whales(sim.run(50))
    assert isinstance(report, WhaleReport)
    assert report.whale_ids == ("alpha", "mike", "zulu")
    assert all(isinstance(w, WhaleSummary) for w in report.whales)
    assert report.ticks == report.observed_ticks == 50


def test_whale_ids_restricts_the_report_without_reordering_it():
    sim = _sim([_acc("a"), _dist("b"), _legacy("c")])
    ticks = sim.run(40)
    # It selects; the report stays ordered by id whatever order it is asked in.
    assert analyze_whales(ticks, whale_ids=["b", "a"]).whale_ids == ("a", "b")
    assert analyze_whales(ticks, whale_ids=["c"]).whale_ids == ("c",)
    assert analyze_whales(ticks, whale_ids=[]).whales == ()


def test_an_unknown_whale_id_is_rejected():
    ticks = _sim([_acc("a")]).run(10)
    with pytest.raises(ValueError, match="no observations for whale id"):
        analyze_whales(ticks, whale_ids=["a", "ghost"])


def test_looking_up_a_missing_whale_is_rejected():
    report = analyze_whales(_sim([_acc("a")]).run(10))
    with pytest.raises(KeyError, match="no whale 'ghost'"):
        report.whale("ghost")


def test_duplicate_tick_numbers_are_rejected():
    ticks = list(_sim([_acc()]).run(5))
    with pytest.raises(ValueError, match="distinct tick numbers"):
        analyze_whales(ticks + [ticks[2]])


def test_non_simulation_ticks_are_rejected():
    with pytest.raises(ValueError, match="expected SimulationTick"):
        analyze_whales([{"tick": 1}])


def test_duplicate_whale_ids_on_one_tick_are_rejected_not_merged():
    both = (_observation("same"), _observation("same"))
    with pytest.raises(ValueError, match="more than once"):
        analyze_whales([_tick(1, both)])


def test_a_run_without_observation_reports_no_whales_rather_than_zeros():
    sim = _sim([_acc(), _dist()], traders=_all_five(), observe=False)
    report = analyze_whales(sim.run(60))
    assert report.ticks == 60 and report.observed_ticks == 0
    assert report.whales == ()


def test_ticks_missing_observations_are_counted_and_excluded():
    recorded = _sim([_acc("a")]).run(20)
    report = analyze_whales(list(recorded) + [_tick(100), _tick(101)])
    assert report.ticks == 22 and report.observed_ticks == 20
    assert report.whale("a").observed_ticks == 20


def test_an_empty_tick_sequence_is_an_empty_report():
    report = analyze_whales([])
    assert report.ticks == 0 and report.observed_ticks == 0 and report.whales == ()


def test_the_report_is_frozen():
    report = analyze_whales(_sim([_acc()]).run(10))
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.ticks = 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.whales[0].trade_count = 0
    assert isinstance(report.whales[0].allocation, AllocationPath)
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.whales[0].allocation.ticks = 0


def test_analysis_is_pure_and_order_independent():
    ticks = list(_sim([_acc("a"), _dist("b")], traders=_all_five()).run(120))
    before = [(t.tick, t.price, t.whale_observations, t.trader_trades) for t in ticks]
    forwards = analyze_whales(ticks)
    backwards = analyze_whales(list(reversed(ticks)))
    assert forwards == backwards == analyze_whales(ticks)
    assert [(t.tick, t.price, t.whale_observations, t.trader_trades) for t in ticks] == before


def test_the_same_run_always_produces_the_same_report():
    def run():
        sim = _sim([_acc(target_coin_fraction=0.6), _dist(target_coin_fraction=0.2), _legacy()],
                   traders=_all_five(),
                   events=EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8,
                                                   sentiment=-0.7, volatility_boost=1.0, attention=1.0,
                                                   start_tick=5, duration=20)]),
                   psychology=True)
        return analyze_whales(sim.run(200))

    assert run() == run()


def test_analysing_a_run_does_not_change_it():
    sim = _sim([_acc(), _dist()], traders=_all_five())
    ticks = sim.run(120)
    totals, reserve = sim.accounting_totals(), (sim.reserve.cash, sim.reserve.coins)
    analyze_whales(ticks)
    analyze_whales(ticks, whale_ids=["acc"])
    assert sim.accounting_totals() == totals
    assert (sim.reserve.cash, sim.reserve.coins) == reserve


def test_it_works_on_a_builder_driven_simulation():
    sim = build_coin_simulator(get_settings(), whale_observation=True)
    report = analyze_whales(sim.run(200))
    assert report.whale_ids == ("whale-1",)
    summary = report.whale("whale-1")
    assert summary.funded is False and summary.allocation is None
    assert summary.observed_ticks == 200 and summary.trade_count > 0
