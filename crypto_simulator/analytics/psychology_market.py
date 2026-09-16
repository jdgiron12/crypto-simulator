"""Descriptive co-movement between recorded psychology and the market
(Phase 9, Step 5).

Post-processing only: reads ``PsychologyState`` and market data off
``SimulationTick``s and returns frozen results. Nothing here feeds back
into the simulation, draws random numbers, or mutates its inputs, and
nothing here is a second implementation of psychology or market
analytics — it reuses ``analytics/psychology.py`` (validation, component
distributions, threshold occupancy, event-period comparison) and
``analytics/market.py`` (pricing mode, price validation, the volume
decomposition) directly, adding only the tick-aligned pairing and the
descriptive statistics over those pairs that neither module computes.

**This module never claims cause.** Every relationship here is a
same-tick or lagged *co-movement* — values observed alongside each
other, nothing more, and never a claim that one moved the other, a
forecast, or a measure of how well psychology worked. Other participants,
events and simulated noise act on the same ticks. Wording throughout is
"observed alongside", "same-tick relationship", "lagged descriptive
comparison".

**Alignment.** Psychology and market values are paired by actual tick
number, never by list position: ``ordered_ticks`` sorts and validates
first, so shuffled or reordered input never changes the result. A return
at tick *t* requires tick *t − 1* to be present and adjacent (Step 1's own
rule, reused via ``analytics/_series.py``); a missing tick is never
bridged, and a tick whose predecessor is missing simply has no return
rather than a substituted zero.

**Missing psychology.** A tick without a recorded ``PsychologyState`` is
counted (in ``ticks``) and left out of every psychology-dependent figure
— never replaced by the neutral state. ``coverage`` is ``"none"``
(no tick carries psychology), ``"complete"`` (every supplied tick does)
or ``"partial"`` — the same three-level vocabulary
``analytics/whale_activity.py`` (Phase 9, Step 3) established for
observation coverage, restated here rather than imported across an
unrelated domain.

**Volume** is exactly ``analytics/market.py``'s ``VolumeBreakdown`` for
each single tick (background/whale/organic/manipulator/wash in
random-walk mode, trader swap volume only in AMM mode; wash counted
once). ``whale_volume`` reads ``SimulationTick.whale_trades`` directly —
recorded whenever a whale trades, independent of the ``whale_observation``
flag — so it is a real, always-defined figure (``0.0`` in AMM mode, where
Phase 8 rejects whales, and whenever a tick simply had no whale trade),
never inferred from a residual.

**Correlation method.** Pearson's r via the standard library
(``statistics.correlation``, linear method) over whichever ticks have
both paired values. Fewer than two paired observations, or either
variable constant across the pairs (zero variance), reports ``None``
with the reason recorded (never ``NaN``/infinity, never a fabricated
value). Two paired observations *can* produce a value (as the spec for
this step requires), which is a small-sample result and should be read
as such — the ``pairs`` count is always alongside it.

**Volatility proxy.** There is no per-tick "volatility" anywhere in this
codebase — Step 1's ``volatility`` is a standard deviation over a window
of returns, undefined for a single tick. Rather than invent one, the
uncertainty/return-magnitude relationship pairs uncertainty with
``abs_log_return`` (the single tick's own log return, absolute value) —
named for exactly what it is, not relabelled as "volatility".

**Event context** is read straight off each tick's own recorded
``EventState`` (no ground-truth ``MarketEvent`` objects are available to
this function — its signature takes only ``ticks``): ``event_active``,
``event_count``, ``event_sentiment`` and ``event_attention``. All four
are ``None`` when the run had no event engine at all (``event_state is
None``), and real values — including the neutral no-event defaults —
when it did but nothing was live that tick; that is a recorded fact, not
a substitution. Ground-truth event *severity* lives only on
``MarketEvent`` (see ``analytics/events.py``/``analytics/event_windows.py``,
Phase 9 Steps 0 and 4), which this module has no access to, so no
severity figure is reported; correlating psychology against it is left to
those modules, which do receive the event timeline.

**Lag.** Only lag 1 is computed, deliberately (a smaller correct
implementation over a broad, unreliable one): psychology at tick *t*
paired with the log return realised at tick *t + 1*. Every entry's
``direction`` is the descriptive label ``PSYCHOLOGY_LEADS_MARKET`` — a
statement of timing only, not a forecasting claim — and its ``pairs``
count already reflects whatever no-bridging exclusions apply to that
later return.

Conventions shared with ``analytics/psychology.py`` and
``analytics/market.py``:

- Ticks are ordered by tick number (duplicates rejected) before anything
  reads them.
- A tick's ``PsychologyState`` is validated exactly as
  ``analyze_psychology`` already validates it (reused, not re-checked).
- Returns are fractions (0.05 = +5%), like every threshold in the project.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Callable, Sequence

from crypto_simulator.analytics._series import ordered_ticks, price_path
from crypto_simulator.analytics.market import analyze_market
from crypto_simulator.analytics.psychology import (
    COMPONENTS,
    NEUTRAL,
    ComponentSummary,
    EventPeriodComparison,
    analyze_psychology,
)
from crypto_simulator.core.coin_simulator import SimulationTick

COVERAGE_NONE = "none"
COVERAGE_PARTIAL = "partial"
COVERAGE_COMPLETE = "complete"
"""Same three-level vocabulary ``analytics/whale_activity.py`` uses for
observation coverage, restated here (not imported) since the two modules
describe unrelated kinds of coverage."""

SAME_TICK = "same_tick"
PSYCHOLOGY_LEADS_MARKET = "psychology_leads_market"
"""Descriptive labels for a correlation's ``direction`` — a statement of
which tick each value came from, nothing about one making the other
happen."""

INSUFFICIENT_PAIRS = "insufficient_pairs"
ZERO_VARIANCE = "zero_variance"
"""Why a correlation's ``value`` is ``None``."""

GROUP_THRESHOLD = 0.5
"""The one pre-declared split point for low/high grouped comparisons —
``analytics/psychology.py``'s own "at or above threshold" convention
(``value >= threshold`` is "high"), fixed rather than configurable to
keep this module's grouping deterministic and small."""

# (x variable, y variable) same-tick pairs this module reports. A fixed,
# deliberately short list (see the module docstring) rather than every
# combination of every component and every market variable.
_SAME_TICK_PAIRS: tuple[tuple[str, str], ...] = (
    ("fear", "log_return"),
    ("fomo", "log_return"),
    ("conviction", "log_return"),
    ("uncertainty", "abs_log_return"),
    ("fear", "volume"),
    ("fomo", "volume"),
    ("uncertainty", "volume"),
    ("conviction", "participant_volume"),
)

# Lag-1 pairs: psychology at tick t against the log return realised at
# tick t + 1. See the module docstring for why lag is limited to this set.
_LAG1_PAIRS: tuple[str, ...] = COMPONENTS


@dataclass(frozen=True)
class PsychologyMarketObservation:
    """One tick's recorded psychology alongside its recorded market
    values. Only built for ticks that carry a ``PsychologyState``.

    ``simple_return``/``log_return`` are ``None`` unless the previous tick
    number is present with a valid price (Step 1's no-bridging rule).
    ``volume`` is the tick's total recorded volume; ``participant_volume``
    and ``whale_volume`` are ``analytics/market.py``'s own
    ``VolumeBreakdown`` figures for this single tick. ``dominant`` is the
    tick's largest psychology component, ties broken and an all-zero tick
    labelled exactly as ``analytics/psychology.py`` already documents.

    ``event_active``/``event_count``/``event_sentiment``/``event_attention``
    are ``None`` only when the run had no event engine at all; see the
    module docstring for why no severity figure is included.
    """

    tick: int
    price: float
    simple_return: float | None
    log_return: float | None
    volume: float
    participant_volume: float
    whale_volume: float
    fear: float
    fomo: float
    conviction: float
    uncertainty: float
    dominant: str
    event_active: bool | None
    event_count: int | None
    event_sentiment: float | None
    event_attention: float | None


@dataclass(frozen=True)
class PsychologyMarketCorrelation:
    """One descriptive relationship between a psychology component and a
    market variable — same-tick (``lag=0``) or lag-1 (``lag=1``).

    ``pairs`` is how many valid paired observations were available.
    ``value`` is Pearson's r, or ``None`` with ``unavailable_reason`` set
    to ``INSUFFICIENT_PAIRS`` (fewer than two pairs) or ``ZERO_VARIANCE``
    (one side never varied across the pairs). A descriptive co-movement
    figure only — see the module docstring for what it must not be read as.
    """

    x: str
    y: str
    lag: int
    direction: str
    pairs: int
    value: float | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class GroupMarketAverages:
    """Descriptive market averages over one group of ticks. ``None``
    fields mean no tick in the group had that value (never a zero)."""

    ticks: int
    mean_log_return: float | None
    mean_volume: float | None
    mean_participant_volume: float | None


@dataclass(frozen=True)
class ComponentGroupComparison:
    """One component's ticks split at ``threshold`` (``low`` = below,
    ``high`` = at or above), each side's market averages reported side by
    side. Descriptive only: not a ranking and not a recommendation — see
    the module docstring."""

    component: str
    threshold: float
    low: GroupMarketAverages
    high: GroupMarketAverages


@dataclass(frozen=True)
class PsychologyMarketReport:
    """Everything ``analyze_psychology_market`` observed.

    ``components`` is ``analyze_psychology``'s own per-component
    distributions (mean, percentiles, threshold occupancy, persistence),
    embedded rather than recomputed. ``event_periods`` is
    ``analyze_psychology``'s own event-period comparison, likewise
    embedded — ``None`` under the same conditions it already documents.
    ``observations`` is ordered by tick; ``correlations`` lists every
    same-tick pair (``_SAME_TICK_PAIRS``) followed by every lag-1 pair, in
    that fixed order; ``groups`` is ordered ``COMPONENTS``.
    """

    ticks: int
    ticks_with_psychology: int
    coverage: str
    first_psychology_tick: int | None
    last_psychology_tick: int | None
    pricing_mode: str | None
    observations: tuple[PsychologyMarketObservation, ...]
    components: tuple[ComponentSummary, ...]
    event_periods: EventPeriodComparison | None
    correlations: tuple[PsychologyMarketCorrelation, ...]
    groups: tuple[ComponentGroupComparison, ...]

    @property
    def ticks_without_psychology(self) -> int:
        return self.ticks - self.ticks_with_psychology

    def observation(self, tick: int) -> PsychologyMarketObservation:
        for observation in self.observations:
            if observation.tick == tick:
                return observation
        raise KeyError(f"no psychology observation at tick {tick}")

    def correlation(self, x: str, y: str, *, lag: int = 0) -> PsychologyMarketCorrelation:
        for entry in self.correlations:
            if entry.x == x and entry.y == y and entry.lag == lag:
                return entry
        raise KeyError(f"no correlation for ({x!r}, {y!r}) at lag {lag}")

    def group(self, component: str) -> ComponentGroupComparison:
        for entry in self.groups:
            if entry.component == component:
                return entry
        raise KeyError(f"no group comparison for {component!r}")


def _require_volume(tick: SimulationTick) -> None:
    volume = tick.volume
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(volume) or volume < 0:
        raise ValueError(f"tick {tick.tick} has an invalid volume {volume!r}")


def _dominant(fear: float, fomo: float, conviction: float, uncertainty: float) -> str:
    """The tick's largest component; ties go to the first in ``COMPONENTS``
    order, and an all-zero tick is ``NEUTRAL`` — the exact rule
    ``analytics/psychology.py`` documents, restated here since it is not
    exposed per tick by that module's own public API."""
    values = (fear, fomo, conviction, uncertainty)
    top = max(values)
    return NEUTRAL if top == 0.0 else COMPONENTS[values.index(top)]


def _returns_by_tick(path: Sequence[tuple[int, float]]) -> dict[int, tuple[float, float]]:
    """``{tick: (simple_return, log_return)}`` for every tick with a
    present, adjacent predecessor — ``analytics/_series.py``'s own
    ``consecutive_pairs``/``simple_returns``/``log_returns`` condition and
    formulas, kept together here so the tick number survives with them."""
    returns: dict[int, tuple[float, float]] = {}
    for (t0, before), (t1, after) in zip(path, path[1:]):
        if t1 == t0 + 1:
            returns[t1] = (after / before - 1.0, math.log(after / before))
    return returns


def _event_context(tick: SimulationTick) -> tuple[bool | None, int | None, float | None, float | None]:
    state = tick.event_state
    if state is None:
        return None, None, None, None
    return bool(state.events), len(state.events), state.sentiment, state.attention_multiplier


def _observation(tick: SimulationTick, returns: dict[int, tuple[float, float]]) -> PsychologyMarketObservation:
    psychology = tick.psychology
    market = analyze_market([tick]).volume_breakdown
    simple_return, log_return = returns.get(tick.tick, (None, None))
    event_active, event_count, event_sentiment, event_attention = _event_context(tick)
    return PsychologyMarketObservation(
        tick=tick.tick,
        price=tick.price,
        simple_return=simple_return,
        log_return=log_return,
        volume=tick.volume,
        participant_volume=market.participant_volume,
        whale_volume=market.whale_volume,
        fear=psychology.fear,
        fomo=psychology.fomo,
        conviction=psychology.conviction,
        uncertainty=psychology.uncertainty,
        dominant=_dominant(psychology.fear, psychology.fomo, psychology.conviction, psychology.uncertainty),
        event_active=event_active,
        event_count=event_count,
        event_sentiment=event_sentiment,
        event_attention=event_attention,
    )


_VARIABLE_GETTERS: dict[str, Callable[[PsychologyMarketObservation], float | None]] = {
    "fear": lambda o: o.fear,
    "fomo": lambda o: o.fomo,
    "conviction": lambda o: o.conviction,
    "uncertainty": lambda o: o.uncertainty,
    "log_return": lambda o: o.log_return,
    "abs_log_return": lambda o: None if o.log_return is None else abs(o.log_return),
    "volume": lambda o: o.volume,
    "participant_volume": lambda o: o.participant_volume,
}


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> tuple[float | None, str | None]:
    if len(xs) < 2:
        return None, INSUFFICIENT_PAIRS
    try:
        return statistics.correlation(xs, ys), None
    except statistics.StatisticsError:
        return None, ZERO_VARIANCE


def _same_tick_correlation(observations: Sequence[PsychologyMarketObservation], x: str, y: str) -> PsychologyMarketCorrelation:
    x_get, y_get = _VARIABLE_GETTERS[x], _VARIABLE_GETTERS[y]
    xs, ys = [], []
    for observation in observations:
        xv, yv = x_get(observation), y_get(observation)
        if xv is not None and yv is not None:
            xs.append(xv)
            ys.append(yv)
    value, reason = _pearson(xs, ys)
    return PsychologyMarketCorrelation(x=x, y=y, lag=0, direction=SAME_TICK, pairs=len(xs),
                                       value=value, unavailable_reason=reason)


def _lag1_correlation(
    observations: Sequence[PsychologyMarketObservation], returns: dict[int, tuple[float, float]], x: str
) -> PsychologyMarketCorrelation:
    x_get = _VARIABLE_GETTERS[x]
    xs, ys = [], []
    for observation in observations:
        xv = x_get(observation)
        after = returns.get(observation.tick + 1)
        if xv is not None and after is not None:
            xs.append(xv)
            ys.append(after[1])
    value, reason = _pearson(xs, ys)
    return PsychologyMarketCorrelation(x=x, y="log_return", lag=1, direction=PSYCHOLOGY_LEADS_MARKET,
                                       pairs=len(xs), value=value, unavailable_reason=reason)


def _group_averages(observations: Sequence[PsychologyMarketObservation]) -> GroupMarketAverages:
    returns = [o.log_return for o in observations if o.log_return is not None]
    volumes = [o.volume for o in observations]
    participant = [o.participant_volume for o in observations]
    return GroupMarketAverages(
        ticks=len(observations),
        mean_log_return=math.fsum(returns) / len(returns) if returns else None,
        mean_volume=math.fsum(volumes) / len(volumes) if volumes else None,
        mean_participant_volume=math.fsum(participant) / len(participant) if participant else None,
    )


def _component_group(component: str, observations: Sequence[PsychologyMarketObservation]) -> ComponentGroupComparison:
    getter = _VARIABLE_GETTERS[component]
    low = [o for o in observations if getter(o) < GROUP_THRESHOLD]
    high = [o for o in observations if getter(o) >= GROUP_THRESHOLD]
    return ComponentGroupComparison(
        component=component, threshold=GROUP_THRESHOLD,
        low=_group_averages(low), high=_group_averages(high),
    )


def analyze_psychology_market(
    ticks: Sequence[SimulationTick], *, initial_price: float | None = None
) -> PsychologyMarketReport:
    """Describe how recorded psychology and the market varied together on
    ``ticks``.

    Pure: the inputs are not mutated, no randomness is drawn, and the same
    ticks always produce the same report whatever order they arrive in.
    Raises ``ValueError`` on non-``SimulationTick`` values, duplicate tick
    numbers, an invalid price or volume, or a malformed ``PsychologyState``
    — every check reused from ``analyze_psychology``/``analyze_market``
    or, for volume, following their same style.
    """
    ordered = ordered_ticks(ticks)
    for tick in ordered:
        _require_volume(tick)
    psychology_report = analyze_psychology(ordered)
    market_summary = analyze_market(ordered, initial_price=initial_price)
    path = price_path(ordered, initial_price)
    returns = _returns_by_tick(path)

    recorded = [tick for tick in ordered if tick.psychology is not None]
    if not recorded:
        return PsychologyMarketReport(
            ticks=len(ordered), ticks_with_psychology=0, coverage=COVERAGE_NONE,
            first_psychology_tick=None, last_psychology_tick=None, pricing_mode=market_summary.pricing_mode,
            observations=(), components=(), event_periods=None, correlations=(), groups=(),
        )

    observations = tuple(_observation(tick, returns) for tick in recorded)
    coverage = COVERAGE_COMPLETE if len(recorded) == len(ordered) else COVERAGE_PARTIAL

    correlations = tuple(_same_tick_correlation(observations, x, y) for x, y in _SAME_TICK_PAIRS) + tuple(
        _lag1_correlation(observations, returns, x) for x in _LAG1_PAIRS
    )
    groups = tuple(_component_group(component, observations) for component in COMPONENTS)

    return PsychologyMarketReport(
        ticks=len(ordered),
        ticks_with_psychology=len(recorded),
        coverage=coverage,
        first_psychology_tick=recorded[0].tick,
        last_psychology_tick=recorded[-1].tick,
        pricing_mode=market_summary.pricing_mode,
        observations=observations,
        components=psychology_report.components,
        event_periods=psychology_report.event_periods,
        correlations=correlations,
        groups=groups,
    )
