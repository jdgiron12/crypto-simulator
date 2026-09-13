"""Whale accumulation / distribution cycles (Phase 8, Step 6).

An optional ``cycle`` gives a funded whale a repeating behavior
timetable. It is a fixed clock, not a judgement: phases and durations are
set up front and the whale never reads the market to decide where it is.
A phase of N ticks covers exactly N ticks; the next phase opens on the
tick after. Target, intent and both pacing counters carry across phases
untouched, and the clock draws no randomness.
"""

import dataclasses
import math
import random

import pytest

from crypto_simulator.core.whale import (
    TARGET_DEAD_ZONE,
    Whale,
    WhaleBehavior,
    WhaleCycle,
    WhaleCycleState,
    WhalePhase,
)
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0

ACC_CYCLE = [{"behavior": "accumulate", "duration": 50}, {"behavior": "neutral", "duration": 20},
             {"behavior": "distribute", "duration": 50}, {"behavior": "neutral", "duration": 20}]


def _whale(cycle=None, cash=1e9, coins=1e6, behavior="neutral", seed=1, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.001)
    return Whale("w", coins, starting_cash=cash, behavior=behavior, seed=seed, cycle=cycle, **kwargs)


def _reserve(cash=1e15, coins=1e15):
    return Wallet(cash=cash, coins=coins)


def _behaviors(whale, ticks, price=PRICE, reserve=None):
    """The behavior in force on each tick, as the whale itself saw it."""
    reserve = _reserve() if reserve is None else reserve
    seen = []
    for _ in range(ticks):
        whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
        seen.append(whale.behavior)
    return seen


def _sides(whale, ticks, price=PRICE, reserve=None):
    reserve = _reserve() if reserve is None else reserve
    out = []
    for _ in range(ticks):
        trade = whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
        out.append(None if trade is None else trade.side)
    return out


class _RecordingRNG:
    def __init__(self, seed):
        self._inner = random.Random(seed)
        self.calls = []

    def random(self):
        self.calls.append("random")
        return self._inner.random()

    def choice(self, seq):
        self.calls.append("choice")
        return self._inner.choice(seq)

    def uniform(self, a, b):
        self.calls.append("uniform")
        return self._inner.uniform(a, b)

    def getstate(self):
        return self._inner.getstate()


# --- configuration and validation -------------------------------------------------------------


def test_no_cycle_is_the_default_and_leaves_the_whale_exactly_as_it_was():
    plain, explicit = _whale(seed=4), _whale(cycle=None, seed=4)
    a, b = _reserve(), _reserve()
    assert [plain.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(300)] == [
        explicit.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(300)
    ]
    assert plain._rng.getstate() == explicit._rng.getstate()
    assert plain.cycle is None and plain.cycle_state() == WhaleCycleState(False, 0, None, 0, None, None)


def test_a_single_phase_cycle_is_valid():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 1}])
    assert whale.cycle == WhaleCycle((WhalePhase(WhaleBehavior.ACCUMULATE, 1),))
    assert whale.cycle.total_ticks == 1
    assert set(_behaviors(whale, 10)) == {WhaleBehavior.ACCUMULATE}


def test_a_multi_phase_cycle_is_parsed_in_order():
    whale = _whale(cycle=ACC_CYCLE)
    assert whale.cycle.phases == (
        WhalePhase(WhaleBehavior.ACCUMULATE, 50), WhalePhase(WhaleBehavior.NEUTRAL, 20),
        WhalePhase(WhaleBehavior.DISTRIBUTE, 50), WhalePhase(WhaleBehavior.NEUTRAL, 20))
    assert whale.cycle.total_ticks == 140


def test_phases_may_be_given_as_objects_or_dicts():
    by_dict = _whale(cycle=[{"behavior": "accumulate", "duration": 2}], seed=5)
    by_object = _whale(cycle=[WhalePhase(WhaleBehavior.ACCUMULATE, 2)], seed=5)
    by_cycle = _whale(cycle=WhaleCycle((WhalePhase(WhaleBehavior.ACCUMULATE, 2),)), seed=5)
    assert by_dict.cycle == by_object.cycle == by_cycle.cycle
    assert _behaviors(by_dict, 20) == _behaviors(by_object, 20) == _behaviors(by_cycle, 20)


def test_the_enum_or_its_configuration_string_may_name_a_phase():
    whale = _whale(cycle=[{"behavior": WhaleBehavior.DISTRIBUTE, "duration": 3}])
    assert whale.cycle.phases[0].behavior is WhaleBehavior.DISTRIBUTE


@pytest.mark.parametrize(
    "cycle, message",
    [
        ([], "at least one phase"),
        ((), "at least one phase"),
        (WhaleCycle(()), "at least one phase"),
        ("accumulate", "must be a list of phases"),
        ({"behavior": "accumulate", "duration": 2}, "must be a list of phases"),
        (5, "must be a list of phases"),
        ([{"behavior": "hodl", "duration": 2}], "Unknown whale behavior"),
        ([{"behavior": "accumulate", "duration": 0}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": -3}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": 1.5}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": True}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": False}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": "2"}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": None}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate", "duration": math.nan}], "duration must be an integer >= 1"),
        ([{"behavior": "accumulate"}], "needs both a behavior and a duration"),
        ([{"duration": 2}], "needs both a behavior and a duration"),
        ([{}], "needs both a behavior and a duration"),
        ([{"behavior": "accumulate", "duration": 2, "intent": 2.0}], "unknown key"),
        (["accumulate"], "must be a dict with behavior and duration"),
        ([None], "must be a dict with behavior and duration"),
        ([("accumulate", 2)], "must be a dict with behavior and duration"),
    ],
)
def test_a_malformed_cycle_is_rejected_not_repaired(cycle, message):
    with pytest.raises(ValueError, match=message):
        _whale(cycle=cycle)


def test_the_offending_phase_is_named_in_the_error():
    with pytest.raises(ValueError, match="cycle phase 2"):
        _whale(cycle=[{"behavior": "accumulate", "duration": 1},
                      {"behavior": "neutral", "duration": 1},
                      {"behavior": "accumulate", "duration": 0}])


def test_a_cycle_needs_a_funded_whale():
    with pytest.raises(ValueError, match="cycle applies only to funded whales"):
        Whale("w", 1_000.0, cycle=[{"behavior": "accumulate", "duration": 5}])
    # Even an all-neutral cycle: it would be inert, and a cycle never
    # creates a wallet.
    with pytest.raises(ValueError, match="cycle applies only to funded whales"):
        Whale("w", 1_000.0, cycle=[{"behavior": "neutral", "duration": 5}])


def test_the_cycle_definition_is_immutable():
    whale = _whale(cycle=ACC_CYCLE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        whale.cycle.phases = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        whale.cycle.phases[0].duration = 99
    assert isinstance(whale.cycle.phases, tuple)
    # Mutating the list that was passed in does not reach the whale.
    source = [{"behavior": "accumulate", "duration": 5}]
    built = _whale(cycle=source)
    source[0]["duration"] = 500
    source.append({"behavior": "distribute", "duration": 1})
    assert built.cycle == WhaleCycle((WhalePhase(WhaleBehavior.ACCUMULATE, 5),))


# --- phase timing -----------------------------------------------------------------------------


def test_the_first_phase_is_in_force_from_construction():
    whale = _whale(cycle=[{"behavior": "distribute", "duration": 3}], behavior="accumulate")
    assert whale.behavior is WhaleBehavior.DISTRIBUTE  # the cycle is authoritative
    assert whale.cycle_state() == WhaleCycleState(
        True, 0, WhaleBehavior.DISTRIBUTE, 0, 3, whale.cycle)


@pytest.mark.parametrize("duration", [1, 2, 3, 5, 8])
def test_a_phase_of_n_ticks_covers_exactly_n_ticks(duration):
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": duration},
                          {"behavior": "distribute", "duration": duration}])
    seen = _behaviors(whale, 4 * duration)
    expected = ([WhaleBehavior.ACCUMULATE] * duration + [WhaleBehavior.DISTRIBUTE] * duration) * 2
    assert seen == expected


def test_the_documented_boundary_example_holds_exactly():
    # duration 3: the phase applies on ticks 0, 1, 2; the next opens at 3.
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 3},
                          {"behavior": "neutral", "duration": 3}])
    seen = _behaviors(whale, 6)
    assert seen[:3] == [WhaleBehavior.ACCUMULATE] * 3
    assert seen[3:] == [WhaleBehavior.NEUTRAL] * 3


def test_the_elapsed_counter_tracks_the_phase_and_resets_at_the_boundary():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 3},
                          {"behavior": "distribute", "duration": 2}])
    reserve = _reserve()
    observed = []
    for _ in range(10):
        state = whale.cycle_state()
        observed.append((state.phase_index, state.phase_elapsed, state.behavior))
        whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
    assert observed == [
        (0, 0, WhaleBehavior.ACCUMULATE), (0, 1, WhaleBehavior.ACCUMULATE), (0, 2, WhaleBehavior.ACCUMULATE),
        (1, 0, WhaleBehavior.DISTRIBUTE), (1, 1, WhaleBehavior.DISTRIBUTE),
        (0, 0, WhaleBehavior.ACCUMULATE), (0, 1, WhaleBehavior.ACCUMULATE), (0, 2, WhaleBehavior.ACCUMULATE),
        (1, 0, WhaleBehavior.DISTRIBUTE), (1, 1, WhaleBehavior.DISTRIBUTE),
    ]


def test_the_cycle_repeats_indefinitely():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 2},
                          {"behavior": "neutral", "duration": 1},
                          {"behavior": "distribute", "duration": 2}])
    seen = _behaviors(whale, 50)
    one_pass = [WhaleBehavior.ACCUMULATE] * 2 + [WhaleBehavior.NEUTRAL] + [WhaleBehavior.DISTRIBUTE] * 2
    assert seen == (one_pass * 10)
    assert whale.cycle_state().phase_index == 0 and whale.cycle_state().phase_elapsed == 0


def test_the_clock_runs_on_every_tick_even_ones_the_whale_sits_out():
    """A phase is a number of ticks, not a number of trades: blocked and
    inactive ticks still advance it."""
    blocked = _whale(cycle=[{"behavior": "accumulate", "duration": 2},
                            {"behavior": "distribute", "duration": 2}], cooldown_ticks=10)
    assert _behaviors(blocked, 8) == (
        [WhaleBehavior.ACCUMULATE] * 2 + [WhaleBehavior.DISTRIBUTE] * 2) * 2
    idle = _whale(cycle=[{"behavior": "accumulate", "duration": 2},
                         {"behavior": "distribute", "duration": 2}], activity_probability=0.0)
    assert _behaviors(idle, 8) == ([WhaleBehavior.ACCUMULATE] * 2 + [WhaleBehavior.DISTRIBUTE] * 2) * 2


# --- behavior inside a phase --------------------------------------------------------------------


def test_each_phase_trades_the_way_that_behavior_always_has():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 6},
                          {"behavior": "neutral", "duration": 6},
                          {"behavior": "distribute", "duration": 6}], seed=9)
    sides = _sides(whale, 18)
    assert set(sides[:6]) == {"buy"}
    assert set(sides[12:]) == {"sell"}
    assert set(sides[6:12]) <= {"buy", "sell"} and len(set(sides[6:12])) == 2  # neutral draws both


def test_a_phase_beginning_places_no_trade_of_its_own():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 2},
                          {"behavior": "distribute", "duration": 2}],
                   activity_probability=0.0, cash=500_000.0, coins=100_000.0)
    reserve = _reserve()
    before = (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins)
    assert _sides(whale, 20, reserve=reserve) == [None] * 20  # every phase boundary crossed
    assert (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) == before


def test_a_cycling_whale_is_the_same_as_one_told_to_transition_by_hand():
    """The cycle is only an automated caller of the Step 4 transition."""
    cycle = [{"behavior": "accumulate", "duration": 4}, {"behavior": "distribute", "duration": 4}]
    cycled = _whale(cycle=cycle, seed=12, cash=600_000.0, coins=200_000.0)
    manual = _whale(seed=12, cash=600_000.0, coins=200_000.0, behavior="accumulate")
    a, b = _reserve(), _reserve()
    for tick in range(40):
        if tick % 4 == 0:
            manual.set_behavior("accumulate" if (tick // 4) % 2 == 0 else "distribute")
        assert cycled.maybe_trade(SUPPLY, price=PRICE, reserve=a) == manual.maybe_trade(
            SUPPLY, price=PRICE, reserve=b)
    assert (a.cash, a.coins) == (b.cash, b.coins)
    assert cycled._rng.getstate() == manual._rng.getstate()


# --- state preservation across phases --------------------------------------------------------------


def test_the_target_survives_every_phase_and_is_dormant_only_while_neutral():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 3},
                          {"behavior": "neutral", "duration": 3},
                          {"behavior": "distribute", "duration": 3}],
                   cash=500_000.0, coins=100_000.0, target_coin_fraction=0.5, seed=7)
    reserve = _reserve()
    for _ in range(30):
        whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
        assert whale.target_coin_fraction == 0.5
        assert whale.allocation(PRICE).target_coin_fraction == 0.5


def test_the_intent_survives_every_phase():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 2},
                          {"behavior": "neutral", "duration": 2},
                          {"behavior": "distribute", "duration": 2}], intent_strength=1.8)
    reserve = _reserve()
    for _ in range(30):
        whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
        assert whale.intent_strength == 1.8


def test_intent_applies_again_the_moment_a_directional_phase_resumes():
    def first_trade_size(intent):
        whale = _whale(cycle=[{"behavior": "neutral", "duration": 1},
                              {"behavior": "accumulate", "duration": 1}],
                       cash=1e9, coins=0.0, seed=14, intent_strength=intent,
                       min_trade_fraction=0.002, max_trade_fraction=0.002)
        reserve = _reserve()
        whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)  # neutral tick
        return whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve).quantity

    assert first_trade_size(2.0) == pytest.approx(first_trade_size(1.0) * 2.0)


def test_a_phase_change_does_not_reset_cooldown_or_interval():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 1},
                          {"behavior": "distribute", "duration": 1}],
                   cooldown_ticks=3, min_trade_interval_ticks=5)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    assert (whale.state().cooldown_remaining, whale.interval_remaining) == (3, 5)
    for cooldown, interval in ((2, 4), (1, 3), (0, 2), (0, 1), (0, 0)):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None  # still blocked
        assert (whale.state().cooldown_remaining, whale.interval_remaining) == (cooldown, interval)
        assert whale.behavior is not None  # the phase kept changing underneath
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


def test_a_phase_change_does_not_touch_balances():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 1},
                          {"behavior": "neutral", "duration": 1},
                          {"behavior": "distribute", "duration": 1}],
                   activity_probability=0.0, cash=400_000.0, coins=60_000.0)
    reserve = _reserve()
    for _ in range(30):
        whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
    assert (whale.wallet.cash, whale.wallet.coins, whale.holdings) == (400_000.0, 60_000.0, 60_000.0)
    assert (reserve.cash, reserve.coins) == (1e15, 1e15)


# --- existing rules stay authoritative inside a phase -------------------------------------------------


def test_the_target_cap_still_binds_inside_a_phase():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 100}],
                   cash=1_000_000.0, coins=0.0, target_coin_fraction=0.5,
                   min_trade_fraction=1.0, max_trade_fraction=1.0, intent_strength=2.0)
    (side, *_), = [_sides(whale, 1)]
    assert side == "buy"
    assert whale.allocation(PRICE).coin_fraction == pytest.approx(0.5)
    assert whale.allocation(PRICE).at_target
    assert _sides(whale, 5) == [None] * 5  # dead-zone hold for the rest of the phase


def test_a_cycling_whale_never_crosses_its_target_in_either_phase():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 20},
                          {"behavior": "distribute", "duration": 20}],
                   cash=500_000.0, coins=200_000.0, target_coin_fraction=0.5,
                   max_trade_fraction=0.05, activity_probability=0.8, seed=8, intent_strength=1.5)
    reserve = _reserve()
    rng = random.Random(3)
    for _ in range(400):
        price = rng.uniform(0.5, 4.0)
        behavior = whale.cycle_state().behavior  # the phase this tick will run under
        before = whale.allocation(price).coin_fraction
        trade = whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
        assert whale.behavior is behavior  # and that is what it traded as
        after = whale.allocation(price).coin_fraction
        if trade is None:
            continue
        if behavior is WhaleBehavior.ACCUMULATE:
            assert before < after <= 0.5 + TARGET_DEAD_ZONE
        elif behavior is WhaleBehavior.DISTRIBUTE:
            assert before > after >= 0.5 - TARGET_DEAD_ZONE


def test_scheduling_still_paces_a_cycling_whale():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 3},
                          {"behavior": "distribute", "duration": 3}],
                   cooldown_ticks=2, min_trade_interval_ticks=4)
    traded = [i for i, side in enumerate(_sides(whale, 40)) if side is not None]
    assert traded == list(range(0, 40, 5))


def test_cash_coins_and_the_reserve_still_bind():
    buyer = _whale(cycle=[{"behavior": "accumulate", "duration": 10}], cash=1_000.0, coins=0.0,
                   max_trade_fraction=0.05)
    assert buyer.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == 500.0
    seller = _whale(cycle=[{"behavior": "distribute", "duration": 10}], cash=0.0, coins=7.0,
                    max_trade_fraction=0.05)
    assert seller.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == 7.0
    thin = _whale(cycle=[{"behavior": "accumulate", "duration": 10}], cash=1e9, coins=0.0,
                  max_trade_fraction=0.05)
    assert thin.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve(coins=3.0)).quantity == 3.0


# --- randomness ------------------------------------------------------------------------------------


def test_the_cycle_clock_consumes_no_randomness():
    cycled = _whale(cycle=[{"behavior": "accumulate", "duration": 1},
                           {"behavior": "neutral", "duration": 1},
                           {"behavior": "distribute", "duration": 1}], seed=6,
                    activity_probability=0.5)
    cycled._rng = _RecordingRNG(6)
    plain = _whale(seed=6, activity_probability=0.5, behavior="accumulate")
    plain._rng = _RecordingRNG(6)
    a, b = _reserve(), _reserve()
    for _ in range(300):
        cycled.maybe_trade(SUPPLY, price=PRICE, reserve=a)
        plain.maybe_trade(SUPPLY, price=PRICE, reserve=b)
    assert cycled._rng.calls == plain._rng.calls
    assert cycled._rng.getstate() == plain._rng.getstate()


def test_a_blocked_cycling_whale_still_draws_nothing():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 1},
                          {"behavior": "distribute", "duration": 1}], cooldown_ticks=3)
    whale._rng = _RecordingRNG(1)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    after = list(whale._rng.calls)
    for _ in range(3):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert whale._rng.calls == after


# --- determinism ---------------------------------------------------------------------------------------


def test_the_same_cycle_and_seed_replay_identically():
    def run():
        whale = _whale(cycle=ACC_CYCLE, cash=600_000.0, coins=120_000.0, seed=21,
                       activity_probability=0.5, target_coin_fraction=0.6, intent_strength=1.5,
                       cooldown_ticks=2, min_trade_interval_ticks=3, max_trade_fraction=0.01)
        reserve = _reserve(cash=2e6, coins=2e6)
        trades = [whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) for _ in range(400)]
        return (trades, whale.state(), whale.cycle_state(), whale.intent_strength,
                (reserve.cash, reserve.coins), whale._rng.getstate())

    assert run() == run()


def test_two_whales_with_the_same_cycle_and_seed_behave_identically():
    a, b = _whale(cycle=ACC_CYCLE, seed=30), _whale(cycle=ACC_CYCLE, seed=30)
    ra, rb = _reserve(), _reserve()
    assert [a.maybe_trade(SUPPLY, price=PRICE, reserve=ra) for _ in range(300)] == [
        b.maybe_trade(SUPPLY, price=PRICE, reserve=rb) for _ in range(300)
    ]
    assert a.cycle_state() == b.cycle_state()


def test_different_cycles_give_different_runs():
    def run(cycle):
        whale = _whale(cycle=cycle, cash=1e6, coins=1e5, seed=21, activity_probability=0.8,
                       max_trade_fraction=0.01)
        return [None if t is None else (t.side, t.quantity)
                for t in (whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) for _ in range(200))]

    fast = [{"behavior": "accumulate", "duration": 5}, {"behavior": "distribute", "duration": 5}]
    slow = [{"behavior": "accumulate", "duration": 50}, {"behavior": "distribute", "duration": 50}]
    assert run(fast) != run(slow)


# --- accounting ------------------------------------------------------------------------------------------


def test_cycles_never_break_conservation_or_produce_a_negative_balance():
    rng = random.Random(0)
    behaviors = ("neutral", "accumulate", "distribute")
    for case in range(200):
        cycle = [{"behavior": rng.choice(behaviors), "duration": rng.randint(1, 8)}
                 for _ in range(rng.randint(1, 5))]
        directional = any(phase["behavior"] != "neutral" for phase in cycle)
        target = rng.choice([None, rng.random()]) if directional else None
        whale = Whale(
            "w", rng.choice([0.0, rng.uniform(0, 2e5)]), starting_cash=rng.choice([0.0, rng.uniform(0, 5e5)]),
            target_coin_fraction=target, behavior="neutral" if target is None else "accumulate",
            activity_probability=rng.random(), max_trade_fraction=rng.uniform(0.001, 0.2),
            cooldown_ticks=rng.randint(0, 3), min_trade_interval_ticks=rng.randint(0, 4),
            intent_strength=rng.uniform(0.0, 2.0), cycle=cycle, seed=case,
        )
        reserve = Wallet(cash=rng.uniform(0, 3e5), coins=rng.uniform(0, 3e5))
        coins = whale.wallet.coins + reserve.coins
        cash = whale.wallet.cash + reserve.cash
        for _ in range(80):
            whale.maybe_trade(SUPPLY, price=rng.uniform(0.5, 4.0), reserve=reserve)
            assert min(whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) >= 0.0
            state = whale.cycle_state()
            assert state.configured and 0 <= state.phase_elapsed < state.phase_duration
        assert whale.wallet.coins + reserve.coins == pytest.approx(coins, rel=1e-12, abs=1e-6)
        assert whale.wallet.cash + reserve.cash == pytest.approx(cash, rel=1e-12, abs=1e-6)


def test_several_cycling_whales_share_a_reserve_safely():
    whales = [
        _whale(cycle=[{"behavior": "accumulate", "duration": 7}, {"behavior": "neutral", "duration": 3}],
               cash=300_000.0, coins=20_000.0, seed=1, target_coin_fraction=0.7,
               activity_probability=0.6, max_trade_fraction=0.01),
        _whale(cycle=[{"behavior": "distribute", "duration": 5}, {"behavior": "accumulate", "duration": 5}],
               cash=50_000.0, coins=150_000.0, seed=2, target_coin_fraction=0.2,
               activity_probability=0.6, max_trade_fraction=0.01, intent_strength=1.5),
        _whale(cycle=[{"behavior": "neutral", "duration": 4}], cash=100_000.0, coins=100_000.0, seed=3,
               max_trade_fraction=0.01),
    ]
    reserve = Wallet(cash=400_000.0, coins=400_000.0)
    coins = math.fsum([w.wallet.coins for w in whales] + [reserve.coins])
    cash = math.fsum([w.wallet.cash for w in whales] + [reserve.cash])
    rng = random.Random(9)
    for _ in range(500):
        price = rng.uniform(0.8, 3.0)
        for whale in whales:
            whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
            assert whale.wallet.cash >= 0.0 and whale.wallet.coins >= 0.0
        assert reserve.cash >= 0.0 and reserve.coins >= 0.0
    assert math.fsum([w.wallet.coins for w in whales] + [reserve.coins]) == pytest.approx(coins, abs=1e-6)
    assert math.fsum([w.wallet.cash for w in whales] + [reserve.cash]) == pytest.approx(cash, abs=1e-6)


def test_a_long_run_stays_on_the_timetable():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 13},
                          {"behavior": "neutral", "duration": 7},
                          {"behavior": "distribute", "duration": 11}])
    seen = _behaviors(whale, 3100)
    one_pass = ([WhaleBehavior.ACCUMULATE] * 13 + [WhaleBehavior.NEUTRAL] * 7
                + [WhaleBehavior.DISTRIBUTE] * 11)
    assert seen == one_pass * 100
    assert whale.cycle_state().phase_index == 0 and whale.cycle_state().phase_elapsed == 0
