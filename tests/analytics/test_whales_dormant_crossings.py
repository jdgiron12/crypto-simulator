"""Target crossings in whale analytics (Phase 9, Step 0).

A target binds a whale only while it is directional (accumulate or
distribute). While it is neutral — after a transition, in a neutral cycle
phase or a neutral cohort phase — the target is dormant, so a neutral fill
that happens to cross it breaks no invariant. ``crossed_target`` therefore
counts directional crossings only; neutral crossings are counted in
``dormant_crossings``. Both use the same dead-zone test as before.

Also pins the duplicate-tick check, which is now a single linear pass with
the same error message.
"""

import dataclasses
import random

import pytest

from crypto_simulator.analytics.whales import AllocationPath, analyze_whales
from crypto_simulator.core.coin_simulator import CoinSimulator, SimulationTick
from crypto_simulator.core.whale import (
    TARGET_DEAD_ZONE,
    Whale,
    WhaleAllocation,
    WhaleAttempt,
    WhaleBehavior,
    WhaleObservation,
    WhaleTrade,
)
from crypto_simulator.core.whale_cohort import WhaleCohort
from tests.core.test_coin_simulator_traders import _all_five, _coin

A, N, D = WhaleBehavior.ACCUMULATE, WhaleBehavior.NEUTRAL, WhaleBehavior.DISTRIBUTE
CYCLE = [{"behavior": "accumulate", "duration": 10}, {"behavior": "neutral", "duration": 10},
         {"behavior": "distribute", "duration": 10}]


def _allocation(coin_fraction, target):
    gap = None if target is None else target - coin_fraction
    target_coins = None if target is None else target * 1000.0 / 2.0
    return WhaleAllocation(2.0, 1000.0, coin_fraction * 1000.0, coin_fraction, target, gap, target_coins)


def _fill(behavior, before, after, target=0.5, side="buy", quantity=10.0):
    """One observed fill moving the coin fraction from ``before`` to ``after``."""
    trade = None if quantity is None else WhaleTrade("w", side, quantity, 1.0)
    return WhaleObservation(
        whale_id="w", funded=True, behavior=behavior, intent_strength=1.0, cycle_phase_index=None,
        cycle_phase_elapsed=None, price=2.0, allocation_before=_allocation(before, target),
        allocation_after=_allocation(after, target), cooldown_remaining=0, interval_remaining=0,
        trade=trade, attempt=WhaleAttempt.FILLED if quantity else WhaleAttempt.INACTIVE,
        cash=100.0, coins=100.0)


def _path(*observations):
    ticks = [SimulationTick(tick=i + 1, timestamp="t", price=2.0, market_cap=0.0, volume=0.0,
                            whale_observations=(o,)) for i, o in enumerate(observations)]
    return analyze_whales(ticks).whale("w").allocation


# --- the semantics, on hand-built observations -----------------------------------------------------


def test_a_neutral_crossing_alone_is_dormant_not_crossed():
    path = _path(_fill(N, 0.4, 0.6))
    assert path.crossed_target is False and path.dormant_crossings == 1


@pytest.mark.parametrize("behavior, before, after, side", [(A, 0.4, 0.6, "buy"), (D, 0.6, 0.4, "sell")])
def test_a_directional_crossing_alone_is_crossed_not_dormant(behavior, before, after, side):
    path = _path(_fill(behavior, before, after, side=side))
    assert path.crossed_target is True and path.dormant_crossings == 0


def test_directional_and_neutral_crossings_together():
    path = _path(_fill(N, 0.4, 0.6), _fill(N, 0.6, 0.45, side="sell"), _fill(A, 0.45, 0.55))
    assert path.crossed_target is True and path.dormant_crossings == 2


@pytest.mark.parametrize("behavior", [A, D, N])
@pytest.mark.parametrize("before, after", [
    (0.4, 0.5),                            # lands exactly on the target
    (0.5, 0.6),                            # starts exactly on the target
    (0.4, 0.5 + TARGET_DEAD_ZONE / 2),     # lands inside the dead zone past the target
    (0.5 - TARGET_DEAD_ZONE / 2, 0.6),     # starts inside the dead zone
])
def test_a_dead_zone_endpoint_counts_as_neither(behavior, before, after):
    path = _path(_fill(behavior, before, after))
    assert path.crossed_target is False and path.dormant_crossings == 0


@pytest.mark.parametrize("behavior", [A, N])
def test_moves_that_do_not_cross_count_as_neither(behavior):
    toward = _fill(behavior, 0.3, 0.45)
    zero_quantity = _fill(behavior, 0.4, 0.6, quantity=0.0)
    no_trade = _fill(behavior, 0.4, 0.6, quantity=None)  # price moved, whale did not fill
    path = _path(toward, zero_quantity, no_trade)
    assert path.crossed_target is False and path.dormant_crossings == 0


def test_no_target_reports_none_for_both():
    path = _path(_fill(N, 0.4, 0.6, target=None), _fill(A, 0.4, 0.6, target=None))
    assert path.target_coin_fraction is None
    assert path.crossed_target is None and path.dormant_crossings is None


def test_multiple_targets_report_none_for_both():
    path = _path(_fill(N, 0.4, 0.6, target=0.5), _fill(A, 0.4, 0.7, target=0.6))
    assert path.target_coin_fraction is None
    assert path.crossed_target is None and path.dormant_crossings is None


def test_an_unfunded_whale_still_has_no_allocation_path():
    sim = CoinSimulator(_coin(), seed=3, whales=[Whale("legacy", 50_000.0, activity_probability=0.5, seed=1)],
                        whale_observation=True)
    assert analyze_whales(sim.run(50)).whale("legacy").allocation is None


def test_the_new_field_is_additive_and_defaulted():
    positional = AllocationPath(1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.5, 0, 0.4, False)
    assert positional.dormant_crossings is None
    assert [f.name for f in dataclasses.fields(AllocationPath)][-1] == "dormant_crossings"


# --- the semantics, on real simulations --------------------------------------------------------------


def _independent_counts(ticks, whale_id):
    """Count crossings straight from the observations, split by behavior."""
    directional = dormant = 0
    for tick in ticks:
        for o in tick.whale_observations:
            if o.whale_id != whale_id or o.trade is None or o.trade.quantity <= 0:
                continue
            gb, ga = o.allocation_before.allocation_gap, o.allocation_after.allocation_gap
            if abs(gb) <= TARGET_DEAD_ZONE or abs(ga) <= TARGET_DEAD_ZONE or (gb > 0) == (ga > 0):
                continue
            if o.behavior is N:
                dormant += 1
            else:
                directional += 1
    return directional, dormant


def test_a_cycling_targeted_whale_crosses_only_while_dormant():
    """The Phase 8 audit case: neutral phases cross the target, directional
    phases never do, and only the former is what the whale actually did."""
    whale = Whale("cyc", 60_000.0, starting_cash=400_000.0, cycle=CYCLE, target_coin_fraction=0.3,
                  activity_probability=1.0, max_trade_fraction=0.004, seed=3)
    sim = CoinSimulator(_coin(), seed=2, whales=[whale], reserve_cash=500_000.0, whale_observation=True)
    ticks = sim.run(300)
    path = analyze_whales(ticks).whale("cyc").allocation
    directional, dormant = _independent_counts(ticks, "cyc")
    assert directional == 0 and dormant > 0
    assert path.crossed_target is False and path.dormant_crossings == dormant


def test_a_targeted_cohort_member_gets_the_same_semantics():
    member = Whale("m", 60_000.0, starting_cash=400_000.0, behavior="accumulate", target_coin_fraction=0.3,
                   activity_probability=1.0, max_trade_fraction=0.004, seed=3)
    sim = CoinSimulator(_coin(), seed=2, whales=[member], reserve_cash=500_000.0, whale_observation=True,
                        whale_cohorts=[WhaleCohort("k", CYCLE, ("m",))])
    ticks = sim.run(300)
    summary = analyze_whales(ticks).whale("m")
    directional, dormant = _independent_counts(ticks, "m")
    assert summary.cohort_id == "k" and directional == 0 and dormant > 0
    assert summary.allocation.crossed_target is False and summary.allocation.dormant_crossings == dormant


def test_a_whale_moved_to_neutral_by_hand_gets_the_same_semantics():
    whale = Whale("t", 60_000.0, starting_cash=400_000.0, behavior="accumulate", target_coin_fraction=0.3,
                  activity_probability=1.0, max_trade_fraction=0.004, seed=3)
    sim = CoinSimulator(_coin(), seed=2, whales=[whale], reserve_cash=500_000.0, whale_observation=True)
    ticks = sim.run(40)
    whale.set_behavior("neutral")
    ticks += sim.run(260)
    path = analyze_whales(ticks).whale("t").allocation
    directional, dormant = _independent_counts(ticks, "t")
    assert directional == 0 and dormant > 0
    assert path.crossed_target is False and path.dormant_crossings == dormant


def _random_world(seed):
    g = random.Random(seed)
    whales, cohort_members = [], []
    for i in range(g.randint(1, 5)):
        kw = dict(activity_probability=round(g.uniform(0.3, 1.0), 2), max_trade_fraction=round(g.uniform(0.001, 0.006), 4),
                  cooldown_ticks=g.choice([0, 0, 2]), min_trade_interval_ticks=g.choice([0, 0, 3]),
                  intent_strength=g.choice([0.5, 1.0, 2.0]), seed=g.randint(0, 9_999),
                  target_coin_fraction=round(g.uniform(0.1, 0.9), 2))
        role = g.choice(["cycle", "cohort", "manual"])
        cycle = [{"behavior": b, "duration": g.randint(2, 12)} for b in ("accumulate", "neutral", "distribute")]
        if role == "cycle":
            kw["cycle"] = cycle
        whale = Whale(f"w{i}", round(g.uniform(10_000.0, 60_000.0), 1), starting_cash=round(g.uniform(50_000.0, 300_000.0), 1),
                      behavior=g.choice(["accumulate", "distribute"]), **kw)
        whales.append(whale)
        if role == "cohort":
            cohort_members.append(whale.whale_id)
    cohorts = [WhaleCohort("k", [{"behavior": "accumulate", "duration": 7}, {"behavior": "neutral", "duration": 9},
                                 {"behavior": "distribute", "duration": 7}], tuple(cohort_members))] if cohort_members else None
    sim = CoinSimulator(_coin(), seed=g.randint(0, 9_999), whales=whales, whale_cohorts=cohorts,
                        traders=_all_five(seed_base=g.randint(0, 999)), reserve_cash=500_000.0, whale_observation=True)
    manual = [w for w in whales if w.cycle is None and w.whale_id not in cohort_members]
    ticks = []
    for tick in range(1, 201):
        if manual and tick % 25 == 0:
            g.choice(manual).set_behavior(g.choice(["neutral", "accumulate", "distribute"]))
        ticks.append(sim.step())
    return sim, ticks


def test_no_simulated_whale_is_marked_crossed_for_a_dormant_crossing():
    total_dormant = 0
    for seed in range(40):
        sim, ticks = _random_world(seed)
        report = analyze_whales(ticks)
        for whale in sim.whales:
            path = report.whale(whale.whale_id).allocation
            directional, dormant = _independent_counts(ticks, whale.whale_id)
            assert directional == 0, (seed, whale.whale_id)
            assert path.crossed_target is False and path.dormant_crossings == dormant, (seed, whale.whale_id)
            total_dormant += dormant
    assert total_dormant > 0  # the fuzz does exercise dormant crossings


# --- duplicate-tick validation --------------------------------------------------------------------------


def _bare_tick(number):
    return SimulationTick(tick=number, timestamp="t", price=2.0, market_cap=0.0, volume=0.0)


@pytest.mark.parametrize("numbers, repeated", [
    ([1, 1], "[1]"),
    ([3, 2, 1, 2], "[2]"),
    ([5, 3, 3, 1, 2, 5, 3], "[3, 5]"),
    ([9, 8, 8, 9, 7, 7], "[7, 8, 9]"),
])
def test_duplicate_ticks_raise_the_exact_existing_message(numbers, repeated):
    with pytest.raises(ValueError) as error:
        analyze_whales([_bare_tick(n) for n in numbers])
    assert str(error.value) == f"ticks must have distinct tick numbers; repeated: {repeated}"


def test_distinct_ticks_in_any_order_are_accepted():
    report = analyze_whales([_bare_tick(n) for n in (4, 1, 3, 2)])
    assert report.ticks == 4 and report.whales == ()


def test_a_long_run_is_checked_in_one_pass():
    """50,000 ticks with one repeat at the very end: the old per-number
    ``list.count`` scan took billions of steps here; one pass is instant.
    No timing is asserted — only the result."""
    ticks = [_bare_tick(n) for n in range(1, 50_001)] + [_bare_tick(50_000)]
    with pytest.raises(ValueError, match=r"repeated: \[50000\]$"):
        analyze_whales(ticks)
    assert analyze_whales(ticks[:-1]).ticks == 50_000
