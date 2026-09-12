"""Descriptive analytics over the market psychology a finished run recorded.

Post-processing only: reads the ``PsychologyState`` on each
``SimulationTick`` (present when the simulation ran with
``psychology=True``) and returns frozen results. Nothing here feeds back
into the simulation, draws random numbers, or mutates its inputs.

Every number describes what was recorded; none is a claim about why. In
particular, the event-period and trading comparisons put numbers side by
side over the same ticks — other participants, events and noise act on
those ticks too — and say nothing about cause.

Conventions:

- Ticks are ordered by tick number (duplicates are rejected), so the input
  order doesn't matter. "Consecutive" means consecutive tick numbers.
- Ticks without psychology (``None``) are counted and left out; they are
  never replaced by a neutral state. A tick carrying anything but a valid
  ``PsychologyState`` is rejected, as ``PsychologyState`` itself rejects
  out-of-range values rather than clamping them.
- Percentiles use linear interpolation between closest ranks: the p-th
  percentile of n sorted values sits at rank ``p/100 × (n − 1)`` (the
  common "inclusive" definition; p50 is the median).
- "At or above a threshold" is ``value >= threshold``.
- The dominant component of a tick is its largest value; ties go to the
  first in ``COMPONENTS`` order (fear, fomo, conviction, uncertainty). A
  tick with every component at 0 has no dominant component (``NEUTRAL``).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Sequence

from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.psychology.state import PsychologyState
from crypto_simulator.core.traders.base import TradeAction

# Also the dominant-component tie-break order.
COMPONENTS = ("fear", "fomo", "conviction", "uncertainty")
NEUTRAL = "neutral"
OCCUPANCY_THRESHOLDS = (0.25, 0.50, 0.75, 0.90)
DEFAULT_PERSISTENCE_THRESHOLD = 0.75
_PERCENTILES = (90, 95)


@dataclass(frozen=True)
class ThresholdOccupancy:
    """Ticks with the component at or above ``threshold``."""

    threshold: float
    ticks: int
    share: float  # of the ticks with psychology


@dataclass(frozen=True)
class Persistence:
    """Runs of consecutive ticks with the component at or above
    ``threshold``. A missing tick, or a tick without psychology, ends a run.
    ``longest_run_start`` is the first tick of the earliest longest run
    (``None`` when there is no run)."""

    threshold: float
    longest_run: int
    longest_run_start: int | None
    runs: int


@dataclass(frozen=True)
class ComponentSummary:
    """Distribution of one component over the ticks with psychology."""

    component: str
    count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    p90: float
    p95: float
    occupancy: tuple[ThresholdOccupancy, ...]  # one per OCCUPANCY_THRESHOLDS
    persistence: Persistence


@dataclass(frozen=True)
class TradingActivity:
    """Trader fills recorded on a set of ticks (the same ticks' fills; whale
    trades not included). Wash legs count as ordinary fills, as an observer
    would see them. ``active_traders_per_tick`` is the mean number of
    distinct traders with at least one fill per tick;
    ``participation_rate`` divides it by the trader population, when that
    is supplied (it isn't in the tick data). Per-tick figures are ``None``
    for an empty set of ticks."""

    ticks: int
    fills: int
    buy_fills: int
    sell_fills: int
    fills_per_tick: float | None
    active_traders_per_tick: float | None
    participation_rate: float | None


@dataclass(frozen=True)
class DominantGroup:
    """The ticks whose dominant component was ``dominant`` (or ``NEUTRAL``),
    and the trader fills recorded on those same ticks."""

    dominant: str
    ticks: int
    share: float  # of the ticks with psychology
    activity: TradingActivity


@dataclass(frozen=True)
class ComponentPeriodMeans:
    """Mean of one component in the event period and outside it.
    ``difference`` is event-period mean minus other-period mean; means are
    ``None`` for a period without ticks."""

    component: str
    event_period_mean: float | None
    other_period_mean: float | None
    difference: float | None


@dataclass(frozen=True)
class EventPeriodComparison:
    """Psychology during event periods vs. the other ticks — side by side,
    not attributed.

    ``source`` says where the periods came from: ``"event_state"`` (ticks
    with at least one live event, active or decaying, per the ticks' own
    recorded ground truth) or ``"event_ticks"`` (tick numbers the caller
    supplied). With ``"event_state"``, ticks that recorded no event state
    can't be classified and are counted in ``unclassified_ticks``.
    """

    source: str
    event_period_ticks: int
    other_period_ticks: int
    unclassified_ticks: int
    components: tuple[ComponentPeriodMeans, ...]


@dataclass(frozen=True)
class PsychologyReport:
    """Everything ``analyze_psychology`` observed. With no psychology
    recorded, ``components`` and ``dominant`` are empty and ``activity``
    and ``event_periods`` are ``None``."""

    ticks: int
    ticks_with_psychology: int
    persistence_threshold: float
    components: tuple[ComponentSummary, ...]
    dominant: tuple[DominantGroup, ...]  # COMPONENTS order, then NEUTRAL
    activity: TradingActivity | None  # over all ticks with psychology
    event_periods: EventPeriodComparison | None

    @property
    def ticks_without_psychology(self) -> int:
        return self.ticks - self.ticks_with_psychology

    def component(self, name: str) -> ComponentSummary:
        for summary in self.components:
            if summary.component == name:
                return summary
        raise KeyError(name)


def analyze_psychology(
    ticks: Sequence[SimulationTick],
    *,
    event_ticks: Iterable[int] | None = None,
    persistence_threshold: float = DEFAULT_PERSISTENCE_THRESHOLD,
    trader_count: int | None = None,
) -> PsychologyReport:
    """Describe the psychology recorded on ``ticks``.

    ``event_ticks``, when given, is the event period for the comparison
    (tick numbers); otherwise the period comes from each tick's recorded
    ``event_state``, and there is no comparison if no tick recorded one.
    ``persistence_threshold`` (in (0, 1]) is the level runs are measured
    at; ``trader_count`` (the population size) enables participation rates.
    """
    if (isinstance(persistence_threshold, bool) or not isinstance(persistence_threshold, (int, float))
            or not math.isfinite(persistence_threshold) or not 0.0 < persistence_threshold <= 1.0):
        raise ValueError(f"persistence_threshold must be within (0, 1] (got {persistence_threshold!r})")
    if trader_count is not None and (isinstance(trader_count, bool) or not isinstance(trader_count, int)
                                     or trader_count < 1):
        raise ValueError(f"trader_count must be an integer >= 1 (got {trader_count!r})")
    period = None if event_ticks is None else _tick_numbers(event_ticks)

    by_tick: dict[int, SimulationTick] = {}
    for tick in ticks:
        if tick.tick in by_tick:
            raise ValueError(f"duplicate tick {tick.tick}")
        by_tick[tick.tick] = tick
    ordered = [by_tick[n] for n in sorted(by_tick)]
    recorded = [tick for tick in ordered if tick.psychology is not None]
    for tick in recorded:
        _check_state(tick)
    if not recorded:
        return PsychologyReport(
            ticks=len(ordered), ticks_with_psychology=0, persistence_threshold=persistence_threshold,
            components=(), dominant=(), activity=None, event_periods=None,
        )

    dominant = [_dominant(tick.psychology) for tick in recorded]
    return PsychologyReport(
        ticks=len(ordered),
        ticks_with_psychology=len(recorded),
        persistence_threshold=persistence_threshold,
        components=tuple(_summary(name, recorded, persistence_threshold) for name in COMPONENTS),
        dominant=tuple(
            _dominant_group(label, [t for t, d in zip(recorded, dominant) if d == label], len(recorded), trader_count)
            for label in (*COMPONENTS, NEUTRAL)
        ),
        activity=_activity(recorded, trader_count),
        event_periods=_event_periods(recorded, period),
    )


def _tick_numbers(event_ticks: Iterable[int]) -> frozenset[int]:
    numbers = set()
    for n in event_ticks:
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError(f"event_ticks must hold tick numbers >= 1 (got {n!r})")
        numbers.add(n)
    return frozenset(numbers)


def _check_state(tick: SimulationTick) -> None:
    state = tick.psychology
    if not isinstance(state, PsychologyState):
        raise ValueError(f"tick {tick.tick}: psychology must be a PsychologyState (got {type(state).__name__})")
    for name in COMPONENTS:
        value = getattr(state, name)
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or not 0.0 <= value <= 1.0):
            raise ValueError(f"tick {tick.tick}: psychology.{name} must be a finite number in [0, 1] (got {value!r})")


def _percentile(ordered: list[float], percent: int) -> float:
    """Linear interpolation at rank percent/100 × (n − 1), with the rank
    split in integer arithmetic so index and weight are exact."""
    scaled = percent * (len(ordered) - 1)
    low, remainder = divmod(scaled, 100)
    if remainder == 0:
        return ordered[low]
    return ordered[low] + (ordered[low + 1] - ordered[low]) * (remainder / 100)


def _summary(name: str, recorded: list[SimulationTick], threshold: float) -> ComponentSummary:
    values = [getattr(tick.psychology, name) for tick in recorded]
    ordered = sorted(values)
    n = len(values)
    p90, p95 = (_percentile(ordered, p) for p in _PERCENTILES)
    return ComponentSummary(
        component=name,
        count=n,
        mean=math.fsum(values) / n,
        median=statistics.median(ordered),
        minimum=ordered[0],
        maximum=ordered[-1],
        p90=p90,
        p95=p95,
        occupancy=tuple(_occupancy(values, level) for level in OCCUPANCY_THRESHOLDS),
        persistence=_persistence([(tick.tick, v) for tick, v in zip(recorded, values)], threshold),
    )


def _occupancy(values: list[float], threshold: float) -> ThresholdOccupancy:
    count = sum(value >= threshold for value in values)
    return ThresholdOccupancy(threshold, count, count / len(values))


def _persistence(series: list[tuple[int, float]], threshold: float) -> Persistence:
    longest, longest_start, runs = 0, None, 0
    current, start, previous = 0, None, None
    for tick, value in series:
        if value >= threshold:
            if current and tick == previous + 1:
                current += 1
            else:
                current, start = 1, tick
                runs += 1
            if current > longest:
                longest, longest_start = current, start
        else:
            current = 0
        previous = tick
    return Persistence(threshold, longest, longest_start, runs)


def _dominant(state: PsychologyState) -> str:
    values = [getattr(state, name) for name in COMPONENTS]
    top = max(values)
    return NEUTRAL if top == 0.0 else COMPONENTS[values.index(top)]


def _dominant_group(label: str, group: list[SimulationTick], total: int, trader_count: int | None) -> DominantGroup:
    return DominantGroup(label, len(group), len(group) / total, _activity(group, trader_count))


def _activity(ticks: list[SimulationTick], trader_count: int | None) -> TradingActivity:
    fills = buys = sells = active = 0
    for tick in ticks:
        fills += len(tick.trader_trades)
        buys += sum(f.side is TradeAction.BUY for f in tick.trader_trades)
        sells += sum(f.side is TradeAction.SELL for f in tick.trader_trades)
        active += len({f.trader_id for f in tick.trader_trades})
    n = len(ticks)
    active_per_tick = active / n if n else None
    return TradingActivity(
        ticks=n,
        fills=fills,
        buy_fills=buys,
        sell_fills=sells,
        fills_per_tick=fills / n if n else None,
        active_traders_per_tick=active_per_tick,
        participation_rate=active_per_tick / trader_count if trader_count and active_per_tick is not None else None,
    )


def _event_periods(recorded: list[SimulationTick], period: frozenset[int] | None) -> EventPeriodComparison | None:
    if period is not None:
        source, unclassified = "event_ticks", []
        inside = [t for t in recorded if t.tick in period]
        outside = [t for t in recorded if t.tick not in period]
    else:
        if all(t.event_state is None for t in recorded):
            return None
        source = "event_state"
        unclassified = [t for t in recorded if t.event_state is None]
        inside = [t for t in recorded if t.event_state is not None and t.event_state.events]
        outside = [t for t in recorded if t.event_state is not None and not t.event_state.events]
    return EventPeriodComparison(
        source=source,
        event_period_ticks=len(inside),
        other_period_ticks=len(outside),
        unclassified_ticks=len(unclassified),
        components=tuple(_period_means(name, inside, outside) for name in COMPONENTS),
    )


def _period_means(name: str, inside: list[SimulationTick], outside: list[SimulationTick]) -> ComponentPeriodMeans:
    def mean(ticks):
        return math.fsum(getattr(t.psychology, name) for t in ticks) / len(ticks) if ticks else None

    event_mean, other_mean = mean(inside), mean(outside)
    difference = None if event_mean is None or other_mean is None else event_mean - other_mean
    return ComponentPeriodMeans(name, event_mean, other_mean, difference)
