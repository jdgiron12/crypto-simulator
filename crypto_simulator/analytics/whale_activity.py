"""Descriptive whale *activity* analytics over a finished run (Phase 9, Step 3).

Post-processing only, exactly like ``analytics/whales.py`` (Step 7) and
``analytics/market.py`` (Step 1), on which this module builds rather than
competing with. It reads ``WhaleObservation`` records off ``SimulationTick``
and returns frozen results; nothing here feeds back into the simulation,
draws random numbers, or mutates its inputs.

**Why a second whale module.** ``analytics/whales.py`` already gives a
thorough per-whale summary (fills, volumes, net flows, allocation path,
behavior/outcome occupancy). This module does not repeat any of that — a
``WhaleActivity`` *embeds* the existing ``WhaleSummary`` — and adds only
what Step 7 does not: volume-share against the wider market, first/last
fill ticks, allocation-gap statistics, target-reaching, behavior-level
volume aggregation, cohort volume aggregation, and a cohort co-fill
(simultaneity) measure. There is exactly one accounting engine for whale
balances and volumes: ``core/whale.py``'s settlement and ``WhaleSummary``'s
aggregation. This module never re-derives cash or coin movement itself.

**Market volume.** ``total_market_volume`` and ``participant_volume`` are
``analytics/market.py``'s own ``VolumeBreakdown.total_volume`` and
``.participant_volume`` for the same ticks — the exact Step 1 definitions
(background/whale/organic/manipulator/wash decomposition, wash counted
once). ``whale_volume`` is this module's own aggregate — the sum of every
reported whale's ``WhaleSummary.total_volume`` — which is *observation*
based rather than read off ``SimulationTick.whale_trades`` directly. The
two agree whenever every analysed tick carries whale observations; when
coverage is only partial (see below), ``whale_volume`` can undercount the
true market total, since the observation layer is the only source this
module reads for whale-level detail. Check ``coverage`` before treating
the share figures as a full accounting.

**Observation coverage.** A tick with an empty ``whale_observations``
tuple is indistinguishable from "no whale acted" and "observation was
off" (the same convention ``analytics/whales.py`` already accepts). This
module reports which situation the *whole* input is likely in, without
building a heavier model than that:

- ``COVERAGE_NONE`` — no analysed tick carried an observation. All
  whale-level figures (``whale_volume``, the two shares, ``whales`` and
  ``cohorts``) are unavailable — ``None`` or empty — never fabricated
  zeroes, because whales may still have traded (in ``whale_trades``)
  without being observed.
- ``COVERAGE_COMPLETE`` — every analysed tick carried at least the
  (possibly empty) observation record, i.e. observed ticks equal total
  ticks.
- ``COVERAGE_PARTIAL`` — some but not all ticks carried observations.
  The observed subset is analysed and reported as real numbers (not
  ``None``); only the coverage label says the input was incomplete.

**AMM.** Phase 8 whales are rejected in AMM mode, so an AMM run's ticks
carry no whale trades and (when observation is on) empty observation
tuples. Nothing here special-cases AMM: the ordinary "no observations"
path already yields ``COVERAGE_NONE`` and an empty whale report, and
``analytics/market.py`` already raises if ``ticks`` mixes AMM and
random-walk records — reused for free by calling it.

**Behavior aggregation** (``BehaviorActivity``) groups observations by the
behavior *in force that tick* (``WhaleObservation.behavior``, which is
already the cohort- or cycle-resolved value — see ``core/whale.py``). It
is strictly descriptive: which behavior category produced how much fill
volume, never a claim about effectiveness or market impact.

**Allocation gap** (``AllocationGapStats``) describes how far a whale's
portfolio has sat from its target across every observation that carries
one, whatever the whale's current behavior — a dormant (neutral) tick
still has a well-defined ``allocation_gap`` on its ``WhaleAllocation``, it
is just not being pursued. **Target reaching** (``TargetReaching``) is the
opposite: it counts only observations where the whale was actively
directional (``ACCUMULATE``/``DISTRIBUTE``) with a target in force, so a
target left dormant by a neutral transition, cycle phase or cohort phase
is never mistaken for an unreached (or reached) pursuit. Both return
``None`` rather than a fabricated zero-sample result when no applicable
observation exists.

**Cohort co-fill** (``CoFillStats``) is a plain simultaneity count: the
share of a cohort's member-observation-ticks that belong to a tick on
which two or more members filled. It says nothing about coordination,
herding, influence or causation — cohorts are already a fixed,
non-reactive schedule (``core/whale_cohort.py``) and this module adds no
new behavior. A cohort with fewer than two members cannot have a
multi-member fill event, so its ``CoFillStats`` is ``None``, not a
degenerate ratio.

Conventions, shared with ``analytics/whales.py``:

- Ticks are ordered by tick number (duplicates rejected) before anything
  reads them, so input order never matters.
- Duplicate whale ids within one tick's observations are rejected with
  ``analyze_whales``'s own error (reused, not re-implemented).
- Collections are sorted deterministically by whale id, then cohort id;
  nothing relies on dict insertion order for a returned result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from crypto_simulator.analytics._series import ordered_ticks
from crypto_simulator.analytics.market import analyze_market
from crypto_simulator.analytics.whales import WhaleReport, WhaleSummary, analyze_whales
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.whale import WhaleBehavior, WhaleObservation

COVERAGE_NONE = "none"
COVERAGE_PARTIAL = "partial"
COVERAGE_COMPLETE = "complete"
OBSERVATION_COVERAGE_LEVELS = (COVERAGE_NONE, COVERAGE_PARTIAL, COVERAGE_COMPLETE)

DIRECTIONAL_BEHAVIORS = (WhaleBehavior.ACCUMULATE, WhaleBehavior.DISTRIBUTE)
"""Behaviors a target actually steers. A target on a ``NEUTRAL`` whale (a
transition, a neutral cycle phase, or a neutral cohort phase) is dormant —
see ``core/whale.py`` — so target-reaching only ever counts these two."""


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


@dataclass(frozen=True)
class AllocationGapStats:
    """How far a funded, targeted whale's portfolio sat from its target,
    over every observation that carries an allocation gap — whatever the
    whale's behavior was on that tick (see the module docstring).

    ``sample_count`` is how many observations were applicable; the three
    figures are ``None`` only together with a zero ``sample_count``.
    """

    sample_count: int
    mean_absolute_gap: float | None
    max_absolute_gap: float | None
    mean_signed_gap: float | None


@dataclass(frozen=True)
class TargetReaching:
    """Whether and when a directional, targeted whale first reached its
    target, counting only observations taken while it was actively
    ``ACCUMULATE`` or ``DISTRIBUTE`` (see ``DIRECTIONAL_BEHAVIORS``).

    ``first_tick_at_target`` is the first such tick whose allocation was
    inside the dead zone (``WhaleAllocation.at_target``), or ``None`` if
    it never was. ``ticks_to_target`` is the tick distance from the first
    directional-target observation to that tick, or ``None`` alongside it.
    """

    target_observation_count: int
    first_tick_at_target: int | None
    ticks_to_target: int | None


@dataclass(frozen=True)
class WhaleActivity:
    """One whale's activity-analytics addition to its existing
    ``WhaleSummary`` (``analytics/whales.py``), reused rather than copied.

    ``volume_share_of_whale_volume`` is this whale's
    ``summary.total_volume`` against the report's aggregate ``whale_volume``
    — ``None`` when that aggregate is ``None`` or zero.
    """

    summary: WhaleSummary
    first_fill_tick: int | None
    last_fill_tick: int | None
    average_fill_size: float | None
    volume_share_of_whale_volume: float | None
    allocation_gap: AllocationGapStats | None
    target_reaching: TargetReaching | None

    @property
    def whale_id(self) -> str:
        return self.summary.whale_id

    @property
    def cohort_id(self) -> str | None:
        return self.summary.cohort_id


@dataclass(frozen=True)
class CoFillStats:
    """A cohort's fill simultaneity — descriptive only (see the module
    docstring). ``eligible_member_ticks`` is every cohort-member
    observation-tick pair; ``co_fill_member_ticks`` is the subset whose
    tick had two or more members fill. ``co_fill_ratio`` is that division,
    or ``None`` with no eligible ticks.

    ``simultaneous_fill_ticks`` counts the distinct ticks with two or more
    member fills; ``same_side_simultaneous_ticks`` and
    ``mixed_side_simultaneous_ticks`` split those by whether the
    simultaneous fillers traded the same side or opposite sides.
    """

    eligible_member_ticks: int
    co_fill_member_ticks: int
    co_fill_ratio: float | None
    simultaneous_fill_ticks: int
    same_side_simultaneous_ticks: int
    mixed_side_simultaneous_ticks: int


@dataclass(frozen=True)
class CohortActivity:
    """Descriptive aggregation over one cohort's reported members
    (``core/whale_cohort.py``). Membership, counts and volumes are read
    from the observations themselves, never from the cohort's own
    configuration (which this module does not receive).

    ``co_fill`` is ``None`` for a one-member cohort — see ``CoFillStats``.
    ``volume_share_of_whale_volume`` is this cohort's ``total_volume``
    against the report's aggregate ``whale_volume``, ``None`` when that is
    ``None`` or zero.
    """

    cohort_id: str
    member_count: int
    active_member_count: int
    observation_ticks: int
    fill_count: int
    buy_volume: float
    sell_volume: float
    total_volume: float
    net_coin_flow: float
    volume_share_of_whale_volume: float | None
    co_fill: CoFillStats | None


@dataclass(frozen=True)
class BehaviorActivity:
    """Descriptive aggregation over every observation recorded with one
    behavior *in force* that tick (see the module docstring). Always
    present for all three behaviors, zero-filled when unobserved — a real
    fact about the run, not a stand-in for missing data."""

    behavior: WhaleBehavior
    observation_ticks: int
    fill_count: int
    buy_volume: float
    sell_volume: float
    total_volume: float
    net_coin_flow: float


@dataclass(frozen=True)
class WhaleActivityReport:
    """Descriptive whale-activity analytics for one finished run.

    ``ticks``/``observed_ticks`` mirror ``WhaleReport``'s (the same
    values). ``coverage`` is one of ``OBSERVATION_COVERAGE_LEVELS``.
    ``whale_volume`` and the two share figures are ``None`` under
    ``COVERAGE_NONE``; ``total_market_volume``/``participant_volume`` are
    always real numbers (``analytics/market.py``'s own convention: a
    market with no recorded volume has zero volume, not an unknown one).

    ``whales`` is ordered by whale id, ``cohorts`` by cohort id,
    ``behaviors`` in ``WhaleBehavior`` declaration order.
    """

    ticks: int
    observed_ticks: int
    coverage: str
    whale_volume: float | None
    total_market_volume: float
    participant_volume: float
    whale_volume_share_of_total: float | None
    whale_volume_share_of_participants: float | None
    whales: tuple[WhaleActivity, ...]
    cohorts: tuple[CohortActivity, ...]
    behaviors: tuple[BehaviorActivity, ...]

    @property
    def whale_ids(self) -> tuple[str, ...]:
        return tuple(activity.whale_id for activity in self.whales)

    def whale(self, whale_id: str) -> WhaleActivity:
        for activity in self.whales:
            if activity.whale_id == whale_id:
                return activity
        raise KeyError(f"no whale {whale_id!r} in this report; got {list(self.whale_ids)}")

    @property
    def cohort_ids(self) -> tuple[str, ...]:
        return tuple(activity.cohort_id for activity in self.cohorts)

    def cohort(self, cohort_id: str) -> CohortActivity:
        for activity in self.cohorts:
            if activity.cohort_id == cohort_id:
                return activity
        raise KeyError(f"no cohort {cohort_id!r} in this report; got {list(self.cohort_ids)}")


def _is_fill(observation: WhaleObservation) -> bool:
    return observation.trade is not None and observation.trade.quantity > 0


def _allocation_gap_stats(records: Sequence[tuple[int, WhaleObservation]]) -> AllocationGapStats | None:
    gaps = [
        observation.allocation_after.allocation_gap
        for _, observation in records
        if observation.allocation_after is not None and observation.allocation_after.allocation_gap is not None
    ]
    if not gaps:
        return None
    return AllocationGapStats(
        sample_count=len(gaps),
        mean_absolute_gap=_mean([abs(gap) for gap in gaps]),
        max_absolute_gap=max(abs(gap) for gap in gaps),
        mean_signed_gap=_mean(gaps),
    )


def _target_reaching(records: Sequence[tuple[int, WhaleObservation]]) -> TargetReaching | None:
    directional = [
        (tick, observation)
        for tick, observation in records
        if observation.behavior in DIRECTIONAL_BEHAVIORS
        and observation.allocation_after is not None
        and observation.allocation_after.target_coin_fraction is not None
    ]
    if not directional:
        return None
    at_target = [tick for tick, observation in directional if observation.allocation_after.at_target]
    first_at_target = at_target[0] if at_target else None
    ticks_to_target = None if first_at_target is None else first_at_target - directional[0][0]
    return TargetReaching(
        target_observation_count=len(directional),
        first_tick_at_target=first_at_target,
        ticks_to_target=ticks_to_target,
    )


def _whale_activity(
    summary: WhaleSummary, records: Sequence[tuple[int, WhaleObservation]], whale_volume: float | None
) -> WhaleActivity:
    fills = [tick for tick, observation in records if _is_fill(observation)]
    average_fill_size = summary.total_volume / summary.trade_count if summary.trade_count else None
    share = (
        None
        if whale_volume is None or whale_volume == 0.0
        else summary.total_volume / whale_volume
    )
    return WhaleActivity(
        summary=summary,
        first_fill_tick=fills[0] if fills else None,
        last_fill_tick=fills[-1] if fills else None,
        average_fill_size=average_fill_size,
        volume_share_of_whale_volume=share,
        allocation_gap=_allocation_gap_stats(records),
        target_reaching=_target_reaching(records),
    )


def _co_fill(records: Sequence[tuple[int, WhaleObservation]], member_count: int) -> CoFillStats | None:
    if member_count < 2:
        return None
    by_tick: dict[int, list[WhaleObservation]] = {}
    for tick, observation in records:
        by_tick.setdefault(tick, []).append(observation)
    eligible = sum(len(observations) for observations in by_tick.values())
    if eligible == 0:
        return None
    co_fill_member_ticks = 0
    simultaneous = 0
    same_side = 0
    mixed_side = 0
    for observations in by_tick.values():
        fillers = [observation for observation in observations if _is_fill(observation)]
        if len(fillers) < 2:
            continue
        co_fill_member_ticks += len(observations)
        simultaneous += 1
        sides = {observation.trade.side for observation in fillers}
        if len(sides) == 1:
            same_side += 1
        else:
            mixed_side += 1
    return CoFillStats(
        eligible_member_ticks=eligible,
        co_fill_member_ticks=co_fill_member_ticks,
        co_fill_ratio=co_fill_member_ticks / eligible,
        simultaneous_fill_ticks=simultaneous,
        same_side_simultaneous_ticks=same_side,
        mixed_side_simultaneous_ticks=mixed_side,
    )


def _cohort_activity(
    cohort_id: str,
    members: Sequence[WhaleSummary],
    records: Sequence[tuple[int, WhaleObservation]],
    whale_volume: float | None,
) -> CohortActivity:
    buy_volume = math.fsum(member.buy_volume for member in members)
    sell_volume = math.fsum(member.sell_volume for member in members)
    total_volume = buy_volume + sell_volume
    share = None if whale_volume is None or whale_volume == 0.0 else total_volume / whale_volume
    observation_ticks = len({tick for tick, _ in records})
    return CohortActivity(
        cohort_id=cohort_id,
        member_count=len(members),
        active_member_count=sum(1 for member in members if member.trade_count > 0),
        observation_ticks=observation_ticks,
        fill_count=sum(member.trade_count for member in members),
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        total_volume=total_volume,
        net_coin_flow=math.fsum(member.net_coin_flow for member in members),
        volume_share_of_whale_volume=share,
        co_fill=_co_fill(records, len(members)),
    )


def _behavior_activity(behavior: WhaleBehavior, observations: Sequence[WhaleObservation]) -> BehaviorActivity:
    fills = [observation for observation in observations if _is_fill(observation)]
    buys = [observation.trade.quantity for observation in fills if observation.trade.side == "buy"]
    sells = [observation.trade.quantity for observation in fills if observation.trade.side == "sell"]
    buy_volume = math.fsum(buys)
    sell_volume = math.fsum(sells)
    return BehaviorActivity(
        behavior=behavior,
        observation_ticks=len(observations),
        fill_count=len(fills),
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        total_volume=buy_volume + sell_volume,
        net_coin_flow=buy_volume - sell_volume,
    )


def analyze_whale_activity(ticks: Sequence[SimulationTick]) -> WhaleActivityReport:
    """Describe the whale activity recorded on ``ticks``, beyond what
    ``analyze_whales`` (Step 7) and ``analyze_market`` (Step 1) already
    give — see the module docstring for the full set of additions and
    their semantics.

    Pure: the inputs are not mutated, no randomness is drawn, and the same
    ticks always produce the same report whatever order they arrive in.
    Raises ``ValueError`` on non-``SimulationTick`` values, duplicate tick
    numbers (``ordered_ticks``), or a duplicate whale id within one tick's
    observations (``analyze_whales``) — every check is reused, not
    re-implemented.
    """
    ordered = ordered_ticks(ticks)
    whale_report = analyze_whales(ordered)
    market = analyze_market(ordered)

    if whale_report.ticks == 0 or whale_report.observed_ticks == 0:
        coverage = COVERAGE_NONE
    elif whale_report.observed_ticks == whale_report.ticks:
        coverage = COVERAGE_COMPLETE
    else:
        coverage = COVERAGE_PARTIAL

    whale_volume = (
        None if coverage == COVERAGE_NONE else math.fsum(summary.total_volume for summary in whale_report.whales)
    )
    total_market_volume = market.volume_breakdown.total_volume
    participant_volume = market.volume_breakdown.participant_volume
    share_of_total = (
        None if whale_volume is None or total_market_volume == 0.0 else whale_volume / total_market_volume
    )
    share_of_participants = (
        None if whale_volume is None or participant_volume == 0.0 else whale_volume / participant_volume
    )

    by_whale_ticks: dict[str, list[tuple[int, WhaleObservation]]] = {}
    by_cohort_ticks: dict[str, list[tuple[int, WhaleObservation]]] = {}
    by_behavior: dict[WhaleBehavior, list[WhaleObservation]] = {behavior: [] for behavior in WhaleBehavior}
    for tick in ordered:
        for observation in tick.whale_observations:
            by_whale_ticks.setdefault(observation.whale_id, []).append((tick.tick, observation))
            if observation.cohort_id is not None:
                by_cohort_ticks.setdefault(observation.cohort_id, []).append((tick.tick, observation))
            by_behavior[observation.behavior].append(observation)

    whales = tuple(
        _whale_activity(summary, by_whale_ticks[summary.whale_id], whale_volume) for summary in whale_report.whales
    )
    cohorts = tuple(
        _cohort_activity(cohort_id, whale_report.cohort(cohort_id), by_cohort_ticks[cohort_id], whale_volume)
        for cohort_id in whale_report.cohort_ids
    )
    behaviors = tuple(_behavior_activity(behavior, by_behavior[behavior]) for behavior in WhaleBehavior)

    return WhaleActivityReport(
        ticks=whale_report.ticks,
        observed_ticks=whale_report.observed_ticks,
        coverage=coverage,
        whale_volume=whale_volume,
        total_market_volume=total_market_volume,
        participant_volume=participant_volume,
        whale_volume_share_of_total=share_of_total,
        whale_volume_share_of_participants=share_of_participants,
        whales=whales,
        cohorts=cohorts,
        behaviors=behaviors,
    )
