"""Whale cohorts, unit level (Phase 8, Step 8).

A ``WhaleCohort`` is a named, immutable ``WhaleCycle`` plus member ids.
Where it stands on a tick is pure arithmetic on the simulator tick number;
binding it to whales (``WhaleCohortSchedule``) checks every membership
rule; and applying it changes a member's behavior and nothing else.
"""

import ast
import dataclasses
import random
from pathlib import Path

import pytest

import crypto_simulator.core.whale_cohort as cohort_module
from crypto_simulator.core.whale import (
    Whale,
    WhaleAttempt,
    WhaleBehavior,
    WhaleCycle,
    WhalePhase,
)
from crypto_simulator.core.whale_cohort import (
    WhaleCohort,
    WhaleCohortPosition,
    WhaleCohortSchedule,
    with_cohort,
)
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0
CYCLE = [{"behavior": "accumulate", "duration": 10}, {"behavior": "neutral", "duration": 5},
         {"behavior": "distribute", "duration": 10}, {"behavior": "neutral", "duration": 5}]
A, N, D = WhaleBehavior.ACCUMULATE, WhaleBehavior.NEUTRAL, WhaleBehavior.DISTRIBUTE


def _funded(whale_id="w", cash=1e6, coins=1e5, behavior="accumulate", seed=1, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.001)
    return Whale(whale_id, coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _expanded(cycle):
    out = []
    for phase in cycle:
        out += [WhaleBehavior(phase["behavior"])] * phase["duration"]
    return out


# --- 1. cohort validation --------------------------------------------------------------------------


def test_a_cohort_holds_an_immutable_id_cycle_and_members():
    cohort = WhaleCohort("c", CYCLE, ["a", "b"])
    assert cohort.cohort_id == "c"
    assert isinstance(cohort.cycle, WhaleCycle)
    assert cohort.cycle.phases[0] == WhalePhase(A, 10) and cohort.cycle.total_ticks == 30
    assert cohort.member_ids == ("a", "b")
    for name, value in [("cohort_id", "x"), ("cycle", None), ("member_ids", ())]:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cohort, name, value)


def test_inputs_are_copied_so_later_edits_cannot_change_a_cohort():
    phases = [dict(p) for p in CYCLE]
    members = ["a", "b"]
    cohort = WhaleCohort("c", phases, members)
    phases.append({"behavior": "neutral", "duration": 99})
    phases[0]["duration"] = 1
    members.append("z")
    assert cohort.cycle.total_ticks == 30 and cohort.member_ids == ("a", "b")


def test_a_cohort_accepts_every_shape_a_personal_cycle_accepts():
    as_dicts = WhaleCohort("c", CYCLE, ("a",))
    as_phases = WhaleCohort("c", [WhalePhase(A, 10), WhalePhase(N, 5), WhalePhase(D, 10), WhalePhase(N, 5)], ("a",))
    as_cycle = WhaleCohort("c", as_dicts.cycle, ("a",))
    as_strings = WhaleCohort("c", tuple(CYCLE), ["a"])
    assert as_dicts == as_phases == as_cycle == as_strings


@pytest.mark.parametrize("cohort_id", ["", None, 5, b"c", ("c",)])
def test_cohort_id_must_be_a_non_empty_string(cohort_id):
    with pytest.raises(ValueError, match="cohort_id must be a non-empty string"):
        WhaleCohort(cohort_id, CYCLE, ("a",))


@pytest.mark.parametrize("members, message", [
    ([], "at least one member"),
    ((), "at least one member"),
    ("a", "must be a list or tuple"),
    ({"a"}, "must be a list or tuple"),
    (None, "must be a list or tuple"),
    ([""], "non-empty strings"),
    ([5], "non-empty strings"),
    (["a", None], "non-empty strings"),
    (["a", "b", "a"], "lists whale 'a' more than once"),
])
def test_member_ids_are_validated(members, message):
    with pytest.raises(ValueError, match=message):
        WhaleCohort("c", CYCLE, members)


# --- 2-4. empty / invalid cycles, behaviors and durations -------------------------------------------


@pytest.mark.parametrize("cycle, message", [
    (None, "needs a cycle"),
    ([], "at least one phase"),
    ((), "at least one phase"),
    ("accumulate", "cycle must be a list of phases"),
    ({"behavior": "accumulate", "duration": 3}, "cycle must be a list of phases"),
    ([("accumulate", 3)], "cycle phase 0 must be a dict"),
    ([{"behavior": "accumulate"}], "cycle phase 0 needs both"),
    ([{"duration": 3}], "cycle phase 0 needs both"),
    ([{"behavior": "accumulate", "duration": 3, "extra": 1}], "unknown key"),
])
def test_empty_and_malformed_cycles_are_rejected(cycle, message):
    with pytest.raises(ValueError, match=message) as error:
        WhaleCohort("c", cycle, ("a",))
    assert "cohort 'c'" in str(error.value)


@pytest.mark.parametrize("behavior", ["buy", "ACCUMULATE", "", None, 1, "hold"])
def test_an_invalid_behavior_is_rejected_naming_the_phase(behavior):
    cycle = [{"behavior": "neutral", "duration": 2}, {"behavior": behavior, "duration": 2}]
    with pytest.raises(ValueError, match=r"cycle phase 1: Unknown whale behavior"):
        WhaleCohort("c", cycle, ("a",))


@pytest.mark.parametrize("duration", [0, -1, 1.5, 2.0, True, False, "3", None])
def test_an_invalid_duration_is_rejected_naming_the_phase(duration):
    cycle = [{"behavior": "accumulate", "duration": 3}, {"behavior": "neutral", "duration": duration}]
    with pytest.raises(ValueError, match=r"cycle phase 1 duration must be an integer >= 1"):
        WhaleCohort("c", cycle, ("a",))


# --- 8-9. exact phase boundaries and repetition -----------------------------------------------------


@pytest.mark.parametrize("tick, index, elapsed, behavior", [
    (1, 0, 0, A), (2, 0, 1, A), (10, 0, 9, A),
    (11, 1, 0, N), (15, 1, 4, N),
    (16, 2, 0, D), (25, 2, 9, D),
    (26, 3, 0, N), (30, 3, 4, N),
    (31, 0, 0, A), (40, 0, 9, A), (41, 1, 0, N),
    (30 * 1_000_000 + 16, 2, 0, D),
])
def test_phase_boundaries_are_exact(tick, index, elapsed, behavior):
    position = WhaleCohort("c", CYCLE, ("a",)).position_at(tick)
    assert position == WhaleCohortPosition("c", tick, index, elapsed, behavior)


def test_the_cycle_repeats_indefinitely_and_matches_the_expanded_timetable():
    cycles = [CYCLE, [{"behavior": "distribute", "duration": 1}],
              [{"behavior": "accumulate", "duration": 3}, {"behavior": "distribute", "duration": 1}],
              [{"behavior": "neutral", "duration": 7}, {"behavior": "accumulate", "duration": 2},
               {"behavior": "neutral", "duration": 1}]]
    for cycle in cycles:
        cohort = WhaleCohort("c", cycle, ("a",))
        table = _expanded(cycle)
        for tick in range(1, 5 * len(table) + 3):
            assert cohort.behavior_at(tick) is table[(tick - 1) % len(table)]


def test_a_cohort_keeps_the_same_time_as_a_personal_cycle():
    """A personal cycle's phase on its k-th tick is the cohort's phase on
    simulator tick k — the property that lets a one-member cohort replace
    a personal cycle exactly."""
    cohort = WhaleCohort("c", CYCLE, ("w",))
    whale = _funded(cycle=CYCLE)
    reserve = Wallet(cash=1e15, coins=1e15)
    for tick in range(1, 200):
        state = whale.cycle_state()
        position = cohort.position_at(tick)
        assert (state.phase_index, state.phase_elapsed, state.behavior) == (
            position.phase_index, position.phase_elapsed, position.behavior)
        whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)


@pytest.mark.parametrize("tick", [0, -1, -30, True, False, 1.0, "1", None])
def test_ticks_start_at_one_and_must_be_integers(tick):
    with pytest.raises(ValueError, match="tick must be an integer >= 1"):
        WhaleCohort("c", CYCLE, ("a",)).position_at(tick)


def test_position_is_a_pure_function_of_the_tick():
    cohort = WhaleCohort("c", CYCLE, ("a",))
    ticks = list(range(1, 400))
    forward = [cohort.position_at(t) for t in ticks]
    random.Random(5).shuffle(ticks)
    shuffled = {t: cohort.position_at(t) for t in ticks}
    assert forward == [shuffled[t] for t in range(1, 400)]
    assert cohort == WhaleCohort("c", CYCLE, ("a",))  # nothing about it changed


# --- 5-7. membership: duplicates, personal-cycle conflict, unfunded -----------------------------------


def test_duplicate_membership_across_cohorts_is_rejected():
    whales = [_funded("a"), _funded("b")]
    cohorts = [WhaleCohort("x", CYCLE, ("a",)), WhaleCohort("y", CYCLE, ("b", "a"))]
    with pytest.raises(ValueError, match="whale 'a' is in cohorts 'x' and 'y'; a whale may belong to at most one"):
        WhaleCohortSchedule(cohorts, whales)


def test_duplicate_membership_within_a_cohort_is_rejected():
    with pytest.raises(ValueError, match="lists whale 'a' more than once"):
        WhaleCohort("x", CYCLE, ("a", "a"))


def test_duplicate_cohort_ids_are_rejected():
    whales = [_funded("a"), _funded("b")]
    with pytest.raises(ValueError, match="cohort id 'x' is used more than once"):
        WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a",)), WhaleCohort("x", CYCLE, ("b",))], whales)


def test_a_personal_cycle_and_a_cohort_together_are_rejected():
    whales = [_funded("a", cycle=CYCLE)]
    with pytest.raises(ValueError, match="whale 'a' has its own cycle and is also in cohort 'x'"):
        WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a",))], whales)
    # No precedence is created: the whale is left exactly as configured.
    assert whales[0].cycle is not None and whales[0].behavior is A


@pytest.mark.parametrize("cycle", [CYCLE, [{"behavior": "neutral", "duration": 4}]])
def test_an_unfunded_whale_cannot_join_a_cohort(cycle):
    legacy = Whale("legacy", 50_000.0, seed=1)
    with pytest.raises(ValueError, match="applies only to funded whales.*never creates a wallet"):
        WhaleCohortSchedule([WhaleCohort("x", cycle, ("legacy",))], [legacy])
    assert legacy.wallet is None and not legacy.funded and legacy.behavior is N


def test_unknown_and_ambiguous_member_ids_are_rejected():
    with pytest.raises(ValueError, match="names whale 'ghost', but the simulation has no whale with that id"):
        WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("ghost",))], [_funded("a")])
    with pytest.raises(ValueError, match="2 whales share that id"):
        WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a",))], [_funded("a"), _funded("a", seed=2)])


def test_duplicate_ids_outside_every_cohort_are_left_alone():
    """Whale ids were never required to be unique; only cohort members
    need to be addressable."""
    schedule = WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a",))],
                                   [_funded("a"), Whale("dup", 1.0), Whale("dup", 1.0)])
    assert schedule.cohorts[0].cohort_id == "x"


def test_a_target_needs_a_directional_phase_in_the_cohort():
    targeted = _funded("a", target_coin_fraction=0.5)
    with pytest.raises(ValueError, match="needs at least one accumulate or distribute phase in cohort 'x'"):
        WhaleCohortSchedule([WhaleCohort("x", [{"behavior": "neutral", "duration": 3}], ("a",))], [targeted])
    WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a",))], [targeted])  # fine with a directional phase


@pytest.mark.parametrize("cohorts, message", [
    (WhaleCohort("x", CYCLE, ("a",)), "must be a list or tuple of WhaleCohort"),
    ("x", "must be a list or tuple of WhaleCohort"),
    ([{"cohort_id": "x", "cycle": CYCLE, "member_ids": ["a"]}], "entries must be WhaleCohort"),
    ([None], "entries must be WhaleCohort"),
])
def test_the_schedule_takes_only_a_list_of_cohorts(cohorts, message):
    with pytest.raises(ValueError, match=message):
        WhaleCohortSchedule(cohorts, [_funded("a")])


# --- applying a cohort changes behavior and nothing else ---------------------------------------------


def _pacing_state(whale):
    return (whale.wallet.cash, whale.wallet.coins, whale.wallet.average_cost, whale.target_coin_fraction,
            whale.intent_strength, whale.cooldown_ticks, whale.min_trade_interval_ticks,
            whale.state().cooldown_remaining, whale.interval_remaining, whale.min_trade_fraction,
            whale.max_trade_fraction, whale.activity_probability, whale._rng.getstate(), whale._last_attempt)


def test_apply_moves_members_to_the_phase_behavior():
    members = [_funded("a", behavior="distribute"), _funded("b", behavior="neutral")]
    outsider = _funded("c", behavior="distribute")
    schedule = WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a", "b"))], members + [outsider])
    for tick in range(1, 70):
        positions = schedule.apply(tick)
        expected = _expanded(CYCLE)[(tick - 1) % 30]
        assert [m.behavior for m in members] == [expected, expected]
        assert set(positions) == set(members)
        assert all(p.behavior is expected and p.tick == tick for p in positions.values())
        assert outsider.behavior is D


def test_apply_leaves_target_intent_pacing_balances_and_rng_untouched():
    """13-16: target allocation, intent strength, cooldown and minimum
    trade interval all carry straight through a cohort transition — as do
    the balances and the RNG state."""
    whale = _funded("a", target_coin_fraction=0.4, intent_strength=1.7, cooldown_ticks=4,
                    min_trade_interval_ticks=6)
    whale.maybe_trade(SUPPLY, price=PRICE, reserve=Wallet(cash=1e12, coins=1e12))  # starts both counters
    before = _pacing_state(whale)
    assert before[7] == 4 and before[8] == 6
    schedule = WhaleCohortSchedule([WhaleCohort("x", CYCLE, ("a",))], [whale])
    for tick in range(1, 100):
        schedule.apply(tick)
        assert _pacing_state(whale) == before


def test_a_transition_places_no_trade_and_touches_no_reserve():
    whale = _funded("a", behavior="neutral")
    reserve = Wallet(cash=1e9, coins=1e9)
    reserve_before = (reserve.cash, reserve.coins)
    schedule = WhaleCohortSchedule([WhaleCohort("x", [{"behavior": "accumulate", "duration": 1},
                                                      {"behavior": "distribute", "duration": 1}], ("a",))],
                                   [whale])
    for tick in range(1, 50):
        assert schedule.apply(tick) is not None
    assert (reserve.cash, reserve.coins) == reserve_before
    assert whale._last_attempt is WhaleAttempt.INACTIVE  # never reached the execution path


def test_with_cohort_labels_a_copy_and_reports_the_cohort_phase():
    whale = _funded("a")
    observation = whale.complete_observation(whale.observe(PRICE), None)
    assert observation.cohort_id is None and observation.cycle_phase_index is None
    position = WhaleCohort("x", CYCLE, ("a",)).position_at(17)
    labelled = with_cohort(observation, position)
    assert (labelled.cohort_id, labelled.cycle_phase_index, labelled.cycle_phase_elapsed) == ("x", 2, 1)
    assert dataclasses.replace(labelled, cohort_id=None, cycle_phase_index=None,
                               cycle_phase_elapsed=None) == observation
    assert observation.cohort_id is None  # the original is untouched


# --- performance: O(cohorts + members) per tick ------------------------------------------------------


def test_apply_places_each_cohort_once_and_touches_each_member_once(monkeypatch):
    whales = [_funded(f"w{i}", seed=i) for i in range(40)] + [Whale(f"u{i}", 1.0) for i in range(20)]
    cohorts = [WhaleCohort(f"c{j}", CYCLE, tuple(f"w{i}" for i in range(j, 40, 4))) for j in range(4)]
    schedule = WhaleCohortSchedule(cohorts, whales)
    positions, transitions = [], []
    original_position, original_set = WhaleCohort.position_at, Whale.set_behavior
    monkeypatch.setattr(WhaleCohort, "position_at",
                        lambda self, tick: positions.append(self.cohort_id) or original_position(self, tick))
    monkeypatch.setattr(Whale, "set_behavior",
                        lambda self, b: transitions.append(self.whale_id) or original_set(self, b))
    for tick in range(1, 11):
        schedule.apply(tick)
    assert len(positions) == 4 * 10 and len(transitions) == 40 * 10
    assert sorted(set(transitions)) == sorted(f"w{i}" for i in range(40))


# --- isolation --------------------------------------------------------------------------------------


def _function(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def _touched(node):
    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
    names |= {n.arg for n in ast.walk(node) if isinstance(n, ast.arg)}
    return names


def test_the_cohort_module_reads_no_market_psychology_event_trader_or_whale_state():
    tree = ast.parse(Path(cohort_module.__file__).read_text())
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= {"__future__", "bisect", "dataclasses", "typing", "crypto_simulator.core.whale"}
    from_whale = {alias.name for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom) and node.module == "crypto_simulator.core.whale"
                  for alias in node.names}
    assert from_whale <= {"Whale", "WhaleBehavior", "WhaleCycle", "WhaleObservation", "_coerce_cycle"}
    forbidden = ("marketview", "market", "psychology", "fear", "fomo", "conviction", "uncertainty",
                 "sentiment", "event", "news", "volatility", "momentum", "returns", "price", "volume",
                 "trader", "manipul", "social", "herd", "cascade", "random", "rng", "wallet", "cash",
                 "coins", "holdings", "allocation", "reserve", "observe", "state", "trade")
    touched = _touched(tree)
    assert not [name for name in touched if any(word in name.lower() for word in forbidden)]


def test_the_per_tick_path_takes_only_the_tick_and_reads_no_whale():
    """``position_at`` and ``apply`` — everything a cohort does on a tick —
    take the tick and nothing else, and ``apply`` touches its members only
    to call ``set_behavior``: it never reads a whale's behavior, balances,
    counters or trades, let alone another whale's."""
    tree = ast.parse(Path(cohort_module.__file__).read_text())
    for name in ("position_at", "behavior_at", "apply"):
        function = _function(tree, name)
        assert [a.arg for a in function.args.args] == ["self", "tick"]
        assert not function.args.kwonlyargs and function.args.vararg is None and function.args.kwarg is None
    apply = _function(tree, "apply")
    whale_uses = [n for n in ast.walk(apply) if isinstance(n, ast.Attribute)
                  and isinstance(n.value, ast.Name) and n.value.id == "whale"]
    assert [n.attr for n in whale_uses] == ["set_behavior"]
    assert _touched(apply) <= {"self", "tick", "int", "positions", "cohort", "members", "position", "whale",
                               "_bindings", "position_at", "set_behavior", "behavior", "dict", "Whale",
                               "WhaleCohortPosition"}
    position_at = _function(tree, "position_at")
    assert _touched(position_at) <= {"self", "tick", "isinstance", "bool", "int", "ValueError", "offset",
                                     "_phase_ends", "index", "bisect", "bisect_right", "start",
                                     "WhaleCohortPosition", "cohort_id", "cycle", "phases", "behavior"}
