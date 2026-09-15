"""Whale cohorts inside the simulation (Phase 8, Step 8).

Cohorts are non-reactive coordination: each tick the simulator tick number
alone places every cohort in its cycle and moves its members to that
phase's behavior. These check that the schedule holds inside the loop —
with traders, news, psychology, manipulators and other whales around it,
none of which it reads — that everything Steps 1-7 established still
holds for members, and that a run without cohorts is exactly 649bdee.
"""

import ast
import dataclasses
import hashlib
from pathlib import Path

import pytest

import crypto_simulator
import crypto_simulator.core.coin_simulator as simulator_module
from crypto_simulator.analytics.whales import analyze_whales
from crypto_simulator.config import WhaleSettings, get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale, WhaleAttempt, WhaleBehavior
from crypto_simulator.core.whale_cohort import WhaleCohort
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin

CYCLE = [{"behavior": "accumulate", "duration": 10}, {"behavior": "neutral", "duration": 5},
         {"behavior": "distribute", "duration": 10}, {"behavior": "neutral", "duration": 5}]
FAST = [{"behavior": "distribute", "duration": 3}, {"behavior": "accumulate", "duration": 4}]
A, N, D = WhaleBehavior.ACCUMULATE, WhaleBehavior.NEUTRAL, WhaleBehavior.DISTRIBUTE
DIRECTION = {A: {"buy"}, D: {"sell"}, N: {"buy", "sell"}}


def _member(whale_id="m", cash=400_000.0, coins=60_000.0, seed=21, behavior="accumulate", **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.002)
    return Whale(whale_id, coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _sim(whales, traders=None, cohorts=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0,
                         whale_cohorts=cohorts, **kwargs)


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


def _balances_ok(sim):
    wallets = [sim.reserve, *(t.wallet for t in sim.traders), *(w.wallet for w in sim.whales if w.funded)]
    return all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)


def _conserved(before, after):
    return all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(after, before))


def _behavior_log(sim, ticks, ids):
    """The behavior in force for each listed whale on each tick, read after
    the tick (a whale keeps its tick's behavior until the next one)."""
    by_id = {w.whale_id: w for w in sim.whales}
    log = []
    for _ in range(ticks):
        tick = sim.step()
        log.append((tick.tick, tuple(by_id[i].behavior for i in ids)))
    return log


def _run_view(sim, ticks, drop_cohort=False):
    """Everything a run produces, bar timestamps (wall-clock stamped)."""
    out = sim.run(ticks)
    observations = [t.whale_observations for t in out]
    if drop_cohort:
        observations = [tuple(dataclasses.replace(o, cohort_id=None) for o in obs) for obs in observations]
    return ([(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.pool_state,
              t.event_state, t.psychology) for t in out], observations,
            [(w.whale_id, w.holdings, w.state(), w.intent_strength, w.interval_remaining, w._rng.getstate())
             for w in sim.whales],
            [(tr.trader_id, tr.wallet.cash, tr.wallet.coins, tr.wallet.average_cost) for tr in sim.traders],
            (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals(),
            sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate())


# --- 28. 649bdee compatibility: no cohorts means the Step 7 checkpoint ------------------------------------
#
# `_pinned_world` and `_fingerprint` were run unchanged against a `git archive` of
# 649bdeea6fcc704fc64a1cbd9ab054b18df18382 to produce these values.
PINNED_649BDEE = {"off": "148248bd15a66fb1", "observed": "c1931f1063efc7ac"}


def _pinned_world(**kwargs):
    whales = [Whale("acc", 0.0, starting_cash=300_000.0, behavior="accumulate", target_coin_fraction=0.6,
                    activity_probability=0.6, max_trade_fraction=0.01, intent_strength=1.5,
                    min_trade_interval_ticks=2, seed=41),
              Whale("dist", 120_000.0, starting_cash=0.0, behavior="distribute", target_coin_fraction=0.2,
                    activity_probability=0.6, max_trade_fraction=0.01, cooldown_ticks=1, seed=42),
              Whale("cyc", 60_000.0, starting_cash=400_000.0, cycle=CYCLE, target_coin_fraction=0.5,
                    activity_probability=0.7, max_trade_fraction=0.004, seed=43),
              Whale("fn", 20_000.0, starting_cash=20_000.0, activity_probability=0.5, seed=44),
              Whale("legacy", 40_000.0, activity_probability=0.5, cooldown_ticks=2, seed=45)]
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=_all_five(), reserve_cash=500_000.0,
                         events=_news(), psychology=True, **kwargs)


def _fields(value):
    """A dataclass as (name, value) pairs, recursively, minus Step 8's
    ``cohort_id`` — so a 649bdee record and a Step 8 record compare on
    every field 649bdee had."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return tuple((f.name, _fields(getattr(value, f.name)))
                     for f in dataclasses.fields(value) if f.name != "cohort_id")
    if isinstance(value, tuple):
        return tuple(_fields(v) for v in value)
    return value


def _fingerprint(sim, ticks):
    out = sim.run(ticks)
    view = ([(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.event_state,
              t.psychology, _fields(t.whale_observations)) for t in out],
            [(w.whale_id, w.state(), w.cycle_state(), w.intent_strength, w.interval_remaining,
              w._rng.getstate()) for w in sim.whales],
            [(tr.trader_id, tr.wallet.cash, tr.wallet.coins, tr.wallet.average_cost) for tr in sim.traders],
            (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals(),
            sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate())
    return hashlib.sha256(repr(view).encode()).hexdigest()[:16]


@pytest.mark.parametrize("cohorts", ["omitted", None, [], ()])
def test_a_run_without_cohorts_is_the_649bdee_run(cohorts):
    kwargs = {} if cohorts == "omitted" else {"whale_cohorts": cohorts}
    assert _fingerprint(_pinned_world(**kwargs), 150) == PINNED_649BDEE["off"]
    assert _fingerprint(_pinned_world(whale_observation=True, **kwargs), 150) == PINNED_649BDEE["observed"]


def test_without_cohorts_every_observation_is_unlabelled_and_nothing_is_scheduled():
    sim = _pinned_world(whale_observation=True)
    assert sim.whale_cohorts == () and sim._whale_cohorts is None
    ticks = sim.run(60)
    assert all(o.cohort_id is None for t in ticks for o in t.whale_observations)
    assert all(s.cohort_id is None for s in analyze_whales(ticks).whales)
    assert analyze_whales(ticks).cohort_ids == ()


# --- the schedule holds inside the loop ---------------------------------------------------------------


def test_members_open_in_the_first_ticks_phase_at_construction():
    member = _member("m", behavior="distribute")
    sim = _sim([member], cohorts=[WhaleCohort("c", CYCLE, ("m",))])
    assert member.behavior is A and sim.whale_cohorts[0].cohort_id == "c"


def test_phase_boundaries_hold_exactly_inside_the_simulation():
    cohort = WhaleCohort("c", CYCLE, ("m",))
    sim = _sim([_member("m")], traders=_all_five(), cohorts=[cohort], whale_observation=True)
    for _ in range(95):
        tick = sim.step()
        (observation,) = tick.whale_observations
        position = cohort.position_at(tick.tick)
        assert observation.behavior is position.behavior is sim.whales[0].behavior
        assert (observation.cycle_phase_index, observation.cycle_phase_elapsed) == (
            position.phase_index, position.phase_elapsed)
        assert {t.side for t in tick.whale_trades} <= DIRECTION[position.behavior]
    boundary = [t.tick for t in sim.history if cohort.position_at(t.tick).phase_elapsed == 0]
    assert boundary == [1, 11, 16, 26, 31, 41, 46, 56, 61, 71, 76, 86, 91]


def test_the_cycle_repeats_for_a_long_run():
    cohort = WhaleCohort("c", FAST, ("m",))
    sim = _sim([_member("m", cash=1e7, coins=1e5)], cohorts=[cohort])
    log = _behavior_log(sim, 700, ["m"])
    assert all(behavior == (cohort.behavior_at(tick),) for tick, behavior in log)
    assert [b for _, (b,) in log[:14]] == [D, D, D, A, A, A, A] * 2


@pytest.mark.parametrize("kwargs", [
    {},
    {"target_coin_fraction": 0.5},
    {"cooldown_ticks": 3, "min_trade_interval_ticks": 5},
    {"intent_strength": 1.8, "min_trade_fraction": 0.001},
    {"activity_probability": 0.4, "target_coin_fraction": 0.3, "intent_strength": 0.5, "cooldown_ticks": 1},
])
def test_a_one_member_cohort_is_exactly_a_personal_cycle(kwargs):
    """Reuse of the Step 6 semantics, end to end: the same whale following
    a cohort or carrying the cycle itself produces the same run — prices,
    fills, balances, RNG — and the same observations bar the label."""
    def world(cohort):
        if cohort:
            whale = _member("m", **kwargs)
            return _sim([whale, Whale("legacy", 30_000.0, activity_probability=0.4, seed=9)],
                        traders=_all_five(), events=_news(), psychology=True, whale_observation=True,
                        cohorts=[WhaleCohort("c", CYCLE, ("m",))])
        whale = _member("m", cycle=CYCLE, **kwargs)
        return _sim([whale, Whale("legacy", 30_000.0, activity_probability=0.4, seed=9)],
                    traders=_all_five(), events=_news(), psychology=True, whale_observation=True)

    with_cohort, with_cycle = world(True), world(False)
    assert _run_view(with_cohort, 150, drop_cohort=True) == _run_view(with_cycle, 150)
    labels = {o.whale_id: o.cohort_id for t in with_cohort.history for o in t.whale_observations}
    assert labels == {"m": "c", "legacy": None}


def test_a_cohort_is_indistinguishable_from_the_same_transitions_made_by_hand():
    cohort = WhaleCohort("c", FAST, ("m",))
    by_cohort = _sim([_member("m", target_coin_fraction=0.4)], traders=_all_five(), cohorts=[cohort])
    by_hand_whale = _member("m", target_coin_fraction=0.4)
    by_hand = _sim([by_hand_whale], traders=_all_five())
    for tick in range(1, 121):
        by_hand_whale.set_behavior(cohort.behavior_at(tick))
        by_hand.step()
        by_cohort.step()
    view = lambda sim: ([(t.tick, t.price, t.volume, t.whale_trades, t.trader_trades) for t in sim.history],
                        [(w.state(), w._rng.getstate()) for w in sim.whales], sim.accounting_totals())
    assert view(by_cohort) == view(by_hand)
    assert sum(len(t.whale_trades) for t in by_cohort.history) > 50


# --- 10-12. many members, many cohorts, non-members ------------------------------------------------------


def _mixed_world(order=None, extra_whales=(), cohort_order=None, traders=True, extra_traders=(), **kwargs):
    whales = [_member("a1", seed=1, target_coin_fraction=0.6), _member("a2", seed=2, coins=20_000.0),
              _member("a3", seed=3, behavior="distribute", cash=50_000.0, coins=150_000.0),
              _member("b1", seed=4, behavior="neutral"), _member("b2", seed=5, cooldown_ticks=2),
              _member("solo", seed=6, cycle=CYCLE), _member("free", seed=7, behavior="distribute"),
              Whale("legacy", 40_000.0, activity_probability=0.5, seed=8), *extra_whales]
    if order is not None:
        whales = [whales[i] for i in order]
    cohorts = [WhaleCohort("alpha", CYCLE, ("a1", "a2", "a3")), WhaleCohort("beta", FAST, ("b2", "b1"))]
    if cohort_order is not None:
        cohorts = [cohorts[i] for i in cohort_order]
    return _sim(whales, traders=(_all_five() if traders else []) + list(extra_traders), cohorts=cohorts, **kwargs)


MIXED_IDS = ["a1", "a2", "a3", "b1", "b2", "solo", "free", "legacy"]


def test_every_member_of_a_cohort_runs_the_same_phase_every_tick():
    sim = _mixed_world()
    alpha, beta = sim.whale_cohorts
    for tick, (a1, a2, a3, b1, b2, *_rest) in _behavior_log(sim, 200, MIXED_IDS):
        assert a1 is a2 is a3 is alpha.behavior_at(tick)
        assert b1 is b2 is beta.behavior_at(tick)


def test_independent_cohorts_do_not_affect_each_others_schedule():
    both = _behavior_log(_mixed_world(), 150, ["a1", "b1"])
    whales = [_member("a1", seed=1, target_coin_fraction=0.6), _member("b1", seed=4, behavior="neutral")]
    alpha_only = _behavior_log(_sim(whales[:1], cohorts=[WhaleCohort("alpha", CYCLE, ("a1",))]), 150, ["a1"])
    beta_only = _behavior_log(_sim(whales[1:], cohorts=[WhaleCohort("beta", FAST, ("b1",))]), 150, ["b1"])
    assert [(t, (a,)) for t, (a, _) in both] == alpha_only
    assert [(t, (b,)) for t, (_, b) in both] == beta_only


def test_non_members_keep_their_own_behavior_and_cycle():
    sim = _mixed_world()
    solo_cycle = WhaleCohort("reference", CYCLE, ("x",))  # the solo whale's personal timetable, as a clock
    for tick, (*_members, solo, free, legacy) in _behavior_log(sim, 120, MIXED_IDS):
        assert solo is solo_cycle.behavior_at(tick)
        assert free is D and legacy is N


def test_an_unfunded_legacy_whale_is_untouched_by_cohorts_elsewhere():
    """27: legacy whales trade against external liquidity, so their draws
    and fills do not depend on price — their trades must be identical with
    or without cohorts in the market."""
    def legacy_trades(cohorts):
        whales = [_member("m"), Whale("legacy", 40_000.0, activity_probability=0.5, cooldown_ticks=1, seed=8)]
        sim = _sim(whales, traders=_all_five(), cohorts=cohorts)
        ticks = sim.run(200)
        return [[t for t in tick.whale_trades if t.whale_id == "legacy"] for tick in ticks], whales[1]._rng.getstate()

    assert legacy_trades([WhaleCohort("c", FAST, ("m",))]) == legacy_trades(None)


def test_an_unfunded_whale_cannot_be_put_in_a_cohort_through_the_simulator():
    legacy = Whale("legacy", 40_000.0, seed=8)
    member = _member("m", behavior="distribute")
    with pytest.raises(ValueError, match="applies only to funded whales"):
        _sim([member, legacy], cohorts=[WhaleCohort("c", CYCLE, ("m", "legacy"))])
    assert legacy.wallet is None and member.behavior is D  # a rejected build changes no whale


def test_the_simulator_rejects_a_personal_cycle_in_a_cohort_and_duplicate_membership():
    with pytest.raises(ValueError, match="has its own cycle and is also in cohort 'c'"):
        _sim([_member("m", cycle=CYCLE)], cohorts=[WhaleCohort("c", FAST, ("m",))])
    with pytest.raises(ValueError, match="at most one cohort"):
        _sim([_member("m")], cohorts=[WhaleCohort("c", FAST, ("m",)), WhaleCohort("d", CYCLE, ("m",))])


# --- 13-16. target, intent, cooldown, interval ----------------------------------------------------------


def test_targets_are_kept_and_never_crossed_by_a_directional_fill():
    """The target is authoritative in directional phases and dormant in
    neutral ones (Step 4), exactly as under a personal cycle — so only
    accumulate/distribute fills are held to the no-crossing invariant."""
    sim = _mixed_world(whale_observation=True)
    ticks = sim.run(400)
    a1 = next(w for w in sim.whales if w.whale_id == "a1")
    assert a1.target_coin_fraction == 0.6
    directional = 0
    for tick in ticks:
        for o in tick.whale_observations:
            if o.whale_id != "a1" or o.trade is None or o.trade.quantity <= 0 or o.behavior is N:
                continue
            directional += 1
            before, after = o.allocation_before.allocation_gap, o.allocation_after.allocation_gap
            assert o.trade.side == ("buy" if o.behavior is A else "sell")
            assert (before > 0) == (o.behavior is A)  # it only ever trades toward the target
            if abs(after) > TARGET_DEAD_ZONE:
                assert (before > 0) == (after > 0)
    assert directional > 50
    assert analyze_whales(ticks).whale("a1").held_at_target_ticks > 0


def test_intent_strength_is_kept_and_still_scales_directional_phases():
    cohort = WhaleCohort("c", CYCLE, ("m",))
    zero = _sim([_member("m", intent_strength=0.0)], cohorts=[cohort], whale_observation=True)
    ticks = zero.run(120)
    assert zero.whales[0].intent_strength == 0.0
    for tick in ticks:
        (o,) = tick.whale_observations
        if o.behavior is not N:
            assert o.trade is None and o.attempt is WhaleAttempt.NO_FILL  # asked for nothing
    assert any(o.trade is not None for t in ticks for o in t.whale_observations if o.behavior is N)


@pytest.mark.parametrize("setting", ["cooldown_ticks", "min_trade_interval_ticks"])
def test_pacing_counters_run_straight_through_phase_boundaries(setting):
    cohort = WhaleCohort("c", [{"behavior": "accumulate", "duration": 2},
                               {"behavior": "distribute", "duration": 2}], ("m",))
    sim = _sim([_member("m", cash=1e7, coins=1e6, **{setting: 5})], cohorts=[cohort], whale_observation=True)
    ticks = sim.run(120)
    fills = [t.tick for t in ticks if t.whale_trades]
    assert len(fills) >= 15
    assert all(b - a == 6 for a, b in zip(fills, fills[1:]))  # T, then T + N + 1 — never reset by a flip
    blocked_on_boundary = [o for t in ticks for o in t.whale_observations
                           if cohort.position_at(t.tick).phase_elapsed == 0 and o.attempt is WhaleAttempt.BLOCKED]
    assert blocked_on_boundary  # a flip onto a blocked tick stays blocked


def test_a_transition_never_triggers_a_trade():
    """An idle member flips phase dozens of times and never trades."""
    cohort = WhaleCohort("c", [{"behavior": "accumulate", "duration": 1},
                               {"behavior": "distribute", "duration": 1}], ("m",))
    sim = _sim([_member("m", activity_probability=0.0)], traders=_all_five(), cohorts=[cohort],
               whale_observation=True)
    ticks = sim.run(100)
    assert not any(t.whale_trades for t in ticks)
    assert {o.attempt for t in ticks for o in t.whale_observations} == {WhaleAttempt.INACTIVE}


# --- 17-18. observation and analytics ---------------------------------------------------------------------


def test_observations_label_members_and_leave_non_members_unlabelled():
    sim = _mixed_world(whale_observation=True)
    alpha, beta = sim.whale_cohorts
    for tick in sim.run(90):
        for o in tick.whale_observations:
            cohort = {"a1": alpha, "a2": alpha, "a3": alpha, "b1": beta, "b2": beta}.get(o.whale_id)
            if cohort is None:
                assert o.cohort_id is None
                continue
            position = cohort.position_at(tick.tick)
            assert (o.cohort_id, o.behavior, o.cycle_phase_index, o.cycle_phase_elapsed) == (
                cohort.cohort_id, position.behavior, position.phase_index, position.phase_elapsed)


def test_observation_on_or_off_gives_the_same_run_with_cohorts():
    on = _run_view(_mixed_world(whale_observation=True, events=_news(), psychology=True), 150)
    off = _run_view(_mixed_world(events=_news(), psychology=True), 150)
    assert on[0] == off[0] and on[2:] == off[2:]


def test_analytics_group_members_by_cohort():
    sim = _mixed_world(whale_observation=True)
    report = analyze_whales(sim.run(120))  # four full passes of CYCLE
    assert report.cohort_ids == ("alpha", "beta")
    assert [s.whale_id for s in report.cohort("alpha")] == ["a1", "a2", "a3"]
    assert [s.whale_id for s in report.cohort("beta")] == ["b1", "b2"]
    assert report.whale("free").cohort_id is None and report.whale("legacy").cohort_id is None
    for summary in report.cohort("alpha"):
        assert summary.phase_ticks == {0: 40, 1: 20, 2: 40, 3: 20}
        assert summary.behavior_ticks == {N: 40, A: 40, D: 40}
    assert report.whale("solo").phase_ticks == {0: 40, 1: 20, 2: 40, 3: 20}  # its own cycle, unlabelled
    with pytest.raises(KeyError, match="no cohort 'gamma'"):
        report.cohort("gamma")


def test_analytics_refuse_one_whale_recorded_under_two_cohort_labels():
    first = _sim([_member("m")], cohorts=[WhaleCohort("c", FAST, ("m",))], whale_observation=True).run(5)
    second = _sim([_member("m")], cohorts=[WhaleCohort("d", FAST, ("m",))], whale_observation=True).run(10)[5:]
    with pytest.raises(ValueError, match="more than one cohort label"):
        analyze_whales(first + second)


# --- 19-20. determinism, RNG, ordering --------------------------------------------------------------------


def test_same_seed_and_configuration_replays_identically():
    kwargs = dict(events=_news(), psychology=True, whale_observation=True)
    assert _run_view(_mixed_world(**kwargs), 250) == _run_view(_mixed_world(**kwargs), 250)


def test_cohorts_add_no_random_draws():
    """With no pacing a whale takes the same draws whatever its behavior,
    so a member's RNG must end exactly where an identical non-member's
    does — and the price and volume streams must not notice cohorts.

    Traders' streams are deliberately not compared: their decisions read
    price, and a member trading in its cohort's direction moves price.
    That is the intended behavior change reaching them, not a new draw."""
    def run(cohorts, traders):
        whales = [_member("m", seed=77, activity_probability=0.6), _member("n", seed=78, behavior="neutral")]
        sim = _sim(whales, traders=_all_five() if traders else None, cohorts=cohorts, events=_news(),
                   psychology=True)
        sim.run(300)
        return ([w._rng.getstate() for w in sim.whales], sim._price_engine._rng.getstate(),
                sim._volume_model._rng.getstate())

    for traders in (False, True):
        assert run([WhaleCohort("c", FAST, ("m", "n"))], traders) == run(None, traders)


def test_cohort_scheduling_is_independent_of_whale_list_and_cohort_order():
    reference = dict(_behavior_log(_mixed_world(), 150, MIXED_IDS))
    for order, cohort_order in [([7, 6, 5, 4, 3, 2, 1, 0], None), ([3, 0, 6, 1, 7, 4, 2, 5], [1, 0])]:
        log = dict(_behavior_log(_mixed_world(order=order, cohort_order=cohort_order), 150, MIXED_IDS))
        assert log == reference


def test_the_schedule_is_the_same_in_any_market():
    """Isolation, behaviourally: the members' behavior sequence is identical
    whether the market is quiet or loud — traders or none, news, random
    events, psychology, manipulators, extra whales, even members' balances."""
    def schedule(**kwargs):
        return _behavior_log(_mixed_world(**kwargs), 160, ["a1", "a2", "a3", "b1", "b2"])

    quiet = schedule(traders=False)
    pump = PumpAndDump("pump", starting_cash=80_000.0, starting_coins=0.0, trade_probability=1.0,
                       max_trade_size=6_000.0, risk_tolerance=0.5, seed=91)
    wash = WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                      max_trade_size=3_000.0, risk_tolerance=0.5, seed=92)
    loud = [
        dict(),
        dict(events=_news(), psychology=True),
        dict(events=_news(), event_generator=RandomEventGenerator(probability=0.3, seed=5), psychology=True),
        dict(extra_whales=[_member("big", cash=5e6, coins=150_000.0, max_trade_fraction=0.05, seed=50),
                           Whale("legacy2", 50_000.0, activity_probability=1.0, max_trade_fraction=0.05, seed=51)]),
        dict(extra_traders=[pump, wash], events=_news(), psychology=True),
    ]
    for kwargs in loud:
        assert schedule(**kwargs) == quiet


# --- 21-22. accounting over long multi-whale runs --------------------------------------------------------


def test_long_multi_whale_cohort_runs_conserve_coins_and_cash():
    whales = [_member(f"w{i}", seed=100 + i, cash=60_000.0 + 5_000.0 * i, coins=15_000.0 + 1_000.0 * i,
                      activity_probability=0.3 + 0.05 * (i % 5), max_trade_fraction=0.004,
                      cooldown_ticks=i % 3, min_trade_interval_ticks=i % 4, intent_strength=0.5 + 0.1 * i,
                      target_coin_fraction=None if i % 2 else 0.25 + 0.05 * i)
              for i in range(12)]
    whales += [Whale("legacy", 30_000.0, activity_probability=0.4, seed=200),
               _member("solo", seed=201, cycle=FAST, cash=100_000.0, coins=20_000.0)]
    cohorts = [WhaleCohort("c0", CYCLE, tuple(f"w{i}" for i in range(0, 12, 3))),
               WhaleCohort("c1", FAST, tuple(f"w{i}" for i in range(1, 12, 3))),
               WhaleCohort("c2", [{"behavior": "neutral", "duration": 6}, {"behavior": "distribute", "duration": 9},
                                  {"behavior": "accumulate", "duration": 11}], tuple(f"w{i}" for i in range(2, 12, 3)))]
    sim = _sim(whales, traders=_all_five(), cohorts=cohorts, events=_news(), psychology=True)
    totals = sim.accounting_totals()
    by_id = {w.whale_id: w for w in sim.whales}
    for _ in range(1_000):
        tick = sim.step()
        assert _balances_ok(sim)
        for cohort in cohorts:
            expected = cohort.behavior_at(tick.tick)
            assert all(by_id[m].behavior is expected for m in cohort.member_ids)
    assert _conserved(totals, sim.accounting_totals())
    member_fills = sum(1 for t in sim.history for tr in t.whale_trades if tr.whale_id.startswith("w"))
    assert member_fills > 500


# --- 23-25. psychology, events, manipulation: coexistence without feedback --------------------------------


def test_psychology_and_events_run_alongside_cohorts_and_never_feed_them():
    sim = _mixed_world(events=_news(), event_generator=RandomEventGenerator(probability=0.2, seed=9),
                       psychology=True, whale_observation=True)
    totals = sim.accounting_totals()
    ticks = sim.run(200)
    assert all(t.psychology is not None and t.event_state is not None for t in ticks)
    assert any(t.event_state.events for t in ticks)
    alpha = sim.whale_cohorts[0]
    assert all(o.behavior is alpha.behavior_at(t.tick) for t in ticks for o in t.whale_observations
               if o.cohort_id == "alpha")
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_cohorts_run_alongside_a_manipulation_scenario(scenario):
    settings = get_settings()
    whales = [WhaleSettings("m1", 20_000.0, activity_probability=0.5, max_trade_fraction=0.005,
                            starting_cash=200_000.0, behavior="accumulate", target_coin_fraction=0.5),
              WhaleSettings("m2", 20_000.0, activity_probability=0.5, max_trade_fraction=0.005,
                            starting_cash=200_000.0)]
    base = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)), scenario=scenario)
    cohort = WhaleCohort("c", [{"behavior": "accumulate", "duration": 20},
                               {"behavior": "distribute", "duration": 20}], ("m1", "m2"))
    sim = CoinSimulator(base.coin, seed=settings.simulation.random_seed, volatility=settings.coin.volatility,
                        whales=base.whales, traders=base.traders, reserve_cash=settings.coin.market_reserve_cash,
                        whale_cohorts=[cohort])
    assert any(isinstance(t, (PumpAndDump, WashTrader)) for t in sim.traders)
    totals = sim.accounting_totals()
    ticks = sim.run(80)
    for tick in ticks:
        assert {t.side for t in tick.whale_trades} <= DIRECTION[cohort.behavior_at(tick.tick)]
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert not any(f.trader_id in {"m1", "m2"} for t in ticks for f in t.trader_trades)


# --- 26. AMM ---------------------------------------------------------------------------------------------


def test_amm_mode_rejects_cohorts_and_still_rejects_whales_with_the_same_message():
    cohort = WhaleCohort("c", CYCLE, ("m",))
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[_member("m")], reserve_cash=2_000_000.0, pricing_mode="amm",
                      whale_cohorts=[cohort])
    with pytest.raises(ValueError, match="Whale cohorts are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, reserve_cash=2_000_000.0, pricing_mode="amm", whale_cohorts=[cohort])


@pytest.mark.parametrize("cohorts", [None, [], ()])
def test_amm_without_cohorts_is_unaffected(cohorts):
    settings = get_settings()
    reference = build_coin_simulator(settings, pricing_mode="amm", include_whales=False, psychology=True)
    sim = CoinSimulator(reference.coin, seed=settings.simulation.random_seed, traders=None,
                        reserve_cash=settings.coin.market_reserve_cash, pricing_mode="amm",
                        whale_cohorts=cohorts)
    plain = CoinSimulator(reference.coin, seed=settings.simulation.random_seed, traders=None,
                          reserve_cash=settings.coin.market_reserve_cash, pricing_mode="amm")
    assert _run_view(sim, 40) == _run_view(plain, 40)


# --- isolation and performance inside the simulator -------------------------------------------------------


def test_the_simulator_feeds_cohorts_the_tick_number_and_nothing_else():
    tree = ast.parse(Path(simulator_module.__file__).read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "apply"]
    assert len(calls) == 2  # construction (the first tick's phase) and each tick
    for call in calls:
        assert ast.unparse(call.func.value) == "self._whale_cohorts" and not call.keywords
        assert [ast.unparse(a) for a in call.args] in (["self.clock.tick"], ["self.clock.tick + 1"])


def test_no_whale_market_view_exists_anywhere():
    root = Path(crypto_simulator.__file__).parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names |= {n.name for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef))}
        assert not any("marketview" in name.lower() for name in names), path


def test_per_tick_cohort_work_scales_with_whales_plus_cohorts(monkeypatch):
    whales = [_member(f"w{i}", seed=i, coins=10_000.0) for i in range(30)]
    whales += [Whale(f"u{i}", 10.0, seed=i) for i in range(10)]
    cohorts = [WhaleCohort(f"c{j}", FAST, tuple(f"w{i}" for i in range(j, 30, 3))) for j in range(3)]
    sim = _sim(whales, cohorts=cohorts)
    placed, moved = [], []
    original_position, original_set = WhaleCohort.position_at, Whale.set_behavior
    monkeypatch.setattr(WhaleCohort, "position_at",
                        lambda self, tick: placed.append(tick) or original_position(self, tick))
    monkeypatch.setattr(Whale, "set_behavior", lambda self, b: moved.append(self.whale_id) or original_set(self, b))
    sim.run(50)
    assert len(placed) == 3 * 50 and len(moved) == 30 * 50
