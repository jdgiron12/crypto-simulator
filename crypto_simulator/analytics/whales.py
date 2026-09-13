"""Descriptive analytics over the whale activity a finished run recorded.

Post-processing only: reads the ``WhaleObservation`` records on each
``SimulationTick`` (present when the simulation ran with
``whale_observation=True``) and returns frozen results. Nothing here feeds
back into the simulation, draws random numbers, or mutates its inputs.

Every number describes what was recorded; none is a claim about why. A
whale's realised allocation path, for instance, is the path the market and
its own settings happened to produce over those ticks — other participants,
events and noise act on the same ticks — and says nothing about cause.
Observation is a recording, not whale intelligence.

Conventions (the same ones ``analytics/psychology.py`` uses):

- Ticks are ordered by tick number (duplicates are rejected), so the input
  order doesn't matter.
- Ticks that recorded no observations are counted and left out; they are
  never replaced by neutral values. In particular a run made without
  ``whale_observation=True`` yields a report with no whales, not a report
  of zeros.
- Allocation figures use only observations that carry an allocation. An
  unfunded whale has none, so it gets no allocation path rather than a
  fabricated zero.
- Each observed whale-tick is classified into exactly one of
  ``TICK_OUTCOMES`` by ``classify``, under a fixed precedence. What the
  execution actually did is read from the recorded ``attempt``, never
  guessed from the balances.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.whale import (
    TARGET_DEAD_ZONE,
    WhaleAttempt,
    WhaleBehavior,
    WhaleObservation,
)


# What became of one whale on one observed tick. Exactly one applies, in
# the precedence ``classify`` documents. Plain strings, as the rest of this
# package uses (see ``analytics/psychology.py``), so the report stays
# trivially comparable and serialisable.
TRADED = "traded"
BLOCKED_BY_COOLDOWN = "blocked_by_cooldown"
BLOCKED_BY_INTERVAL = "blocked_by_interval"
HELD_AT_TARGET = "held_at_target"
NO_FILL = "no_fill"
INACTIVE = "inactive"

TICK_OUTCOMES = (TRADED, BLOCKED_BY_COOLDOWN, BLOCKED_BY_INTERVAL, HELD_AT_TARGET, NO_FILL, INACTIVE)


def classify(observation: WhaleObservation) -> str:
    """Which ``TickOutcome`` an observed whale-tick was.

    One of ``TICK_OUTCOMES``, in precedence order, so the classification
    is deterministic when more than one condition holds:

    1. ``TRADED`` — a fill that moved coins.
    2. ``BLOCKED_BY_COOLDOWN`` — no trade and a cooldown was running.
       Cooldown wins when both counters were running.
    3. ``BLOCKED_BY_INTERVAL`` — no trade, no cooldown, but a minimum
       trade interval was running.
    4. ``HELD_AT_TARGET`` — nothing was blocking it, it was active, and
       its target left nothing to do (inside the dead zone, or the target
       lay the other way), so the target itself is what stopped it.
    5. ``NO_FILL`` — it was active and reached settlement, which clamped
       to nothing: no cash, no coins, or an exhausted reserve.
    6. ``INACTIVE`` — it was eligible and the activity check said no.

    ``NO_FILL`` and ``INACTIVE`` are kept apart deliberately: one is a
    whale that tried and could not fill, the other a whale that did not
    try. The two are read from ``observation.attempt``, which the
    execution path records as it happens — not reconstructed from the
    balances, which cannot tell an exhausted reserve from an inactive
    tick.
    """
    trade = observation.trade
    if trade is not None and trade.quantity > 0:
        return TRADED
    if observation.cooldown_remaining > 0:
        return BLOCKED_BY_COOLDOWN
    if observation.interval_remaining > 0:
        return BLOCKED_BY_INTERVAL
    if observation.attempt is WhaleAttempt.HELD:
        return HELD_AT_TARGET
    if observation.attempt is WhaleAttempt.NO_FILL:
        return NO_FILL
    return INACTIVE


@dataclass(frozen=True)
class AllocationPath:
    """A funded whale's realised allocation over the observed ticks.

    ``ticks`` is how many observations carried an allocation.
    ``target_coin_fraction`` is the target it held (``None`` if it had
    none, and then the target-relative figures are ``None`` too).
    ``ticks_at_target`` counts observations whose gap was inside
    ``TARGET_DEAD_ZONE``; ``max_abs_gap`` is the widest it ever sat from
    the target; ``crossed_target`` records whether any *fill* finished on
    the far side of the target from where it started — the invariant the
    whale is meant to hold, described rather than assumed.
    """

    ticks: int
    first_coin_fraction: float | None
    last_coin_fraction: float | None
    mean_coin_fraction: float | None
    min_coin_fraction: float | None
    max_coin_fraction: float | None
    target_coin_fraction: float | None
    ticks_at_target: int | None
    max_abs_gap: float | None
    crossed_target: bool | None


@dataclass(frozen=True)
class WhaleSummary:
    """One whale's recorded activity over the observed ticks."""

    whale_id: str
    funded: bool
    observed_ticks: int
    trade_count: int
    buy_count: int
    sell_count: int
    buy_volume: float
    sell_volume: float
    total_volume: float
    buy_notional: float
    sell_notional: float
    notional: float
    vwap: float | None
    net_coin_flow: float
    net_cash_flow: float
    allocation: AllocationPath | None
    behavior_ticks: dict[WhaleBehavior, int]
    phase_ticks: dict[int, int]
    outcome_ticks: dict[str, int]

    @property
    def traded_ticks(self) -> int:
        return self.outcome_ticks[TRADED]

    @property
    def blocked_by_cooldown_ticks(self) -> int:
        return self.outcome_ticks[BLOCKED_BY_COOLDOWN]

    @property
    def blocked_by_interval_ticks(self) -> int:
        return self.outcome_ticks[BLOCKED_BY_INTERVAL]

    @property
    def held_at_target_ticks(self) -> int:
        return self.outcome_ticks[HELD_AT_TARGET]

    @property
    def no_fill_ticks(self) -> int:
        return self.outcome_ticks[NO_FILL]

    @property
    def inactive_ticks(self) -> int:
        return self.outcome_ticks[INACTIVE]


@dataclass(frozen=True)
class WhaleReport:
    """Descriptive whale analytics for one finished run.

    ``whales`` is ordered by whale id. ``ticks`` is how many ticks were
    analysed and ``observed_ticks`` how many of them carried observations
    — equal only when the run had observation on throughout.
    """

    ticks: int
    observed_ticks: int
    whales: tuple[WhaleSummary, ...]

    @property
    def whale_ids(self) -> tuple[str, ...]:
        return tuple(summary.whale_id for summary in self.whales)

    def whale(self, whale_id: str) -> WhaleSummary:
        for summary in self.whales:
            if summary.whale_id == whale_id:
                return summary
        raise KeyError(f"no whale {whale_id!r} in this report; got {list(self.whale_ids)}")


def _ordered(ticks: Sequence[SimulationTick]) -> list[SimulationTick]:
    for tick in ticks:
        if not isinstance(tick, SimulationTick):
            raise ValueError(f"expected SimulationTick values, got {type(tick).__name__}")
    numbers = [tick.tick for tick in ticks]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        raise ValueError(f"ticks must have distinct tick numbers; repeated: {duplicates}")
    return sorted(ticks, key=lambda tick: tick.tick)


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


def _allocation_path(observations: Sequence[WhaleObservation]) -> AllocationPath | None:
    """The allocation path over the observations that carry one."""
    marked = [o for o in observations if o.allocation_after is not None]
    if not marked:
        return None
    fractions = [o.allocation_after.coin_fraction for o in marked]
    targets = {o.allocation_after.target_coin_fraction for o in marked}
    target = targets.pop() if len(targets) == 1 else None
    if target is None:
        return AllocationPath(
            ticks=len(marked), first_coin_fraction=fractions[0], last_coin_fraction=fractions[-1],
            mean_coin_fraction=_mean(fractions), min_coin_fraction=min(fractions),
            max_coin_fraction=max(fractions), target_coin_fraction=None, ticks_at_target=None,
            max_abs_gap=None, crossed_target=None,
        )
    gaps = [o.allocation_after.allocation_gap for o in marked]
    crossed = False
    for observation in marked:
        if observation.trade is None or observation.trade.quantity <= 0:
            continue
        before = observation.allocation_before
        if before is None or before.allocation_gap is None:
            continue
        after_gap = observation.allocation_after.allocation_gap
        # A fill that started short of the target and finished past it (or
        # the reverse) crossed it. Sitting inside the dead zone is not a
        # crossing.
        if abs(after_gap) <= TARGET_DEAD_ZONE or abs(before.allocation_gap) <= TARGET_DEAD_ZONE:
            continue
        if (before.allocation_gap > 0) != (after_gap > 0):
            crossed = True
    return AllocationPath(
        ticks=len(marked), first_coin_fraction=fractions[0], last_coin_fraction=fractions[-1],
        mean_coin_fraction=_mean(fractions), min_coin_fraction=min(fractions),
        max_coin_fraction=max(fractions), target_coin_fraction=target,
        ticks_at_target=sum(1 for gap in gaps if abs(gap) <= TARGET_DEAD_ZONE),
        max_abs_gap=max(abs(gap) for gap in gaps), crossed_target=crossed,
    )


def _summarize(whale_id: str, observations: Sequence[WhaleObservation]) -> WhaleSummary:
    fills = [o for o in observations if o.trade is not None and o.trade.quantity > 0]
    buys = [o for o in fills if o.trade.side == "buy"]
    sells = [o for o in fills if o.trade.side == "sell"]
    buy_volume = math.fsum(o.trade.quantity for o in buys)
    sell_volume = math.fsum(o.trade.quantity for o in sells)
    buy_notional = math.fsum(o.trade.quantity * o.price for o in buys)
    sell_notional = math.fsum(o.trade.quantity * o.price for o in sells)
    total_volume = buy_volume + sell_volume
    notional = buy_notional + sell_notional
    behavior_ticks = {behavior: 0 for behavior in WhaleBehavior}
    outcome_ticks = {outcome: 0 for outcome in TICK_OUTCOMES}
    phase_ticks: dict[int, int] = {}
    for observation in observations:
        behavior_ticks[observation.behavior] += 1
        outcome_ticks[classify(observation)] += 1
        if observation.cycle_phase_index is not None:
            phase_ticks[observation.cycle_phase_index] = phase_ticks.get(observation.cycle_phase_index, 0) + 1
    return WhaleSummary(
        whale_id=whale_id,
        funded=observations[0].funded,
        observed_ticks=len(observations),
        trade_count=len(fills),
        buy_count=len(buys),
        sell_count=len(sells),
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        total_volume=total_volume,
        buy_notional=buy_notional,
        sell_notional=sell_notional,
        notional=notional,
        vwap=(notional / total_volume) if total_volume > 0 else None,
        net_coin_flow=buy_volume - sell_volume,
        net_cash_flow=sell_notional - buy_notional,
        allocation=_allocation_path(observations),
        behavior_ticks=behavior_ticks,
        phase_ticks=dict(sorted(phase_ticks.items())),
        outcome_ticks=outcome_ticks,
    )


def analyze_whales(
    ticks: Sequence[SimulationTick], *, whale_ids: Iterable[str] | None = None
) -> WhaleReport:
    """Describe the whale activity recorded on ``ticks``.

    ``whale_ids``, when given, restricts the report to those whales (and
    rejects ids that were never observed). It selects but does not
    reorder: ``whales`` is always ordered by id. Ticks that recorded no
    observations are counted in ``ticks`` and otherwise ignored, so a run
    made without ``whale_observation=True`` produces an empty report
    rather than a report of zeros.

    Pure: the inputs are not mutated, no randomness is drawn, and the same
    ticks always produce the same report whatever order they arrive in.
    """
    ordered = _ordered(ticks)
    observed_ticks = 0
    by_whale: dict[str, list[WhaleObservation]] = {}
    for tick in ordered:
        if not tick.whale_observations:
            continue
        observed_ticks += 1
        seen_here: set[str] = set()
        for observation in tick.whale_observations:
            if observation.whale_id in seen_here:
                raise ValueError(
                    f"tick {tick.tick} records whale id {observation.whale_id!r} more than once; "
                    "per-whale analytics cannot tell those whales apart"
                )
            seen_here.add(observation.whale_id)
            by_whale.setdefault(observation.whale_id, []).append(observation)
    if whale_ids is not None:
        wanted = list(whale_ids)
        unknown = [whale_id for whale_id in wanted if whale_id not in by_whale]
        if unknown:
            raise ValueError(
                f"no observations for whale id(s) {unknown}; observed: {sorted(by_whale)}"
            )
        by_whale = {whale_id: by_whale[whale_id] for whale_id in wanted}
        # Ordering stays by id below, so the argument order never leaks
        # into the report.
    return WhaleReport(
        ticks=len(ordered),
        observed_ticks=observed_ticks,
        whales=tuple(_summarize(whale_id, by_whale[whale_id]) for whale_id in sorted(by_whale)),
    )
