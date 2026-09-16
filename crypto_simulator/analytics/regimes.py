"""Descriptive market regimes over a finished run (Phase 9, Step 7).

Post-processing only: reads ``SimulationTick`` records and returns frozen
results. Nothing here feeds back into the simulation, draws random
numbers, or mutates its inputs. A regime is a label for what the recorded
market looked like over one historical window — never a statement about
what comes next, and never an input to any participant.

**Windows** are fixed and anchored on tick numbers, not on whichever
ticks happen to be supplied: window ``k`` (0-based) covers ticks
``k·window_size + 1`` .. ``(k + 1)·window_size``, so with the default of 20
they are 1–20, 21–40, 41–60, … Only windows holding at least one supplied
tick are reported (``window_index`` shows any whole window skipped by a
gap). A window with fewer ticks than it spans — a gap, or the run ending
part-way through, as the final window usually does — is reported with
``complete=False`` and analysed on the ticks it has; it is never padded.

**Every price and volume figure is ``analyze_market``'s own**, computed
over the window's ticks and embedded as ``market`` — Step 1's price path,
returns, volatility, realized volatility, drawdown, ``VolumeBreakdown``,
average trade size and turnover, not a second copy of any of them. That
includes Step 1's windowing convention: a return exists only between
consecutive tick numbers *inside* the window, so the return into a
window's first tick belongs to no window, and the pre-run price
(``initial_price``, as ``PRE_RUN_TICK``) joins window 0's path only when
tick 1 is present. ``market.cumulative_return``/``market.log_return`` are
Step 1's open-to-close figures, which span any gap inside the window;
``net_log_return`` is the sum of the window's consecutive log returns
only, and is what the direction label uses, so no label ever rests on a
move across a missing tick.

**Taxonomy** — four independent dimensions, each ``None`` when the data
cannot support it:

- ``direction`` (``RISING``/``FALLING``/``FLAT``): the window's net
  consecutive log return compared with its own realized volatility
  (``sqrt`` of the summed squared log returns, Step 1's definition):
  ``RISING`` when the net move is larger than that, ``FALLING`` when it is
  more negative, ``FLAT`` otherwise. A window's net move can only exceed
  its realized volatility when the returns lean one way, so this is
  scale-free and uses no percentage cut-off. Needs at least
  ``MIN_VOLATILITY_RETURNS`` returns (Step 1's volatility minimum).
- ``volatility`` and ``volume`` (``LOW_``/``NORMAL_``/``HIGH_``): the
  window's ``market.volatility`` (sample standard deviation of log
  returns) and its volume per observed tick, placed against the lower and
  upper quartiles of the same figure over every *earlier complete* window
  — below the lower quartile is low, above the upper quartile is high,
  anything between (inclusive) normal. Quartiles use the inclusive
  linear-interpolation percentile ``analytics/psychology.py`` documents.
  Unavailable until ``MIN_REFERENCE_WINDOWS`` earlier complete windows
  exist, since fewer values cannot populate four quartile bins.
- ``market_state`` (``AT_HIGH``/``DRAWDOWN``/``RECOVERY``): measured
  against the highest price observed anywhere in the analysed history up
  to the window's last point. ``AT_HIGH`` when the window closes at that
  running high; otherwise ``RECOVERY`` when the drawdown at the close is
  smaller than the drawdown at the window's first point (a narrowing that
  has already happened), and ``DRAWDOWN`` when it is not. "Recovery"
  describes the window as observed, not a recovery still to come.

**No look-ahead.** A window's labels read only its own ticks, earlier
windows, and earlier prices: the grid is fixed by tick number, the
quartile reference grows one completed window at a time, and the running
high is a prefix maximum. Adding, removing or changing ticks after a
window's last tick never changes that window's labels. The one
consequence worth knowing is that early windows have a thinner reference
than later ones — a window's class is relative to the history before it,
not to the whole run.

**Context** is recorded alongside the labels and never used to assign
them: events (from each tick's own ``EventState``), psychology means
(ticks with a ``PsychologyState`` only — never neutral fill-ins), ticks
carrying whale observations, and the manipulation/whale volume already in
``market.volume_breakdown``. A high-volatility window with a live event is
two observations side by side; this module links them in no way, and
never labels a window a pump or a dump from its price path. Event
severity is not recorded per tick and so is not reported here.

Conventions shared with the rest of ``analytics/``:

- Ticks are ordered by tick number (duplicates rejected) before anything
  reads them, so input order never matters.
- Prices must be positive and finite and volumes finite and non-negative;
  ticks mixing AMM and random-walk records, or carrying a malformed
  ``PsychologyState``, are rejected by the existing checks, reused.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from crypto_simulator.analytics._series import PRE_RUN_TICK, log_returns, ordered_ticks, price_path
from crypto_simulator.analytics.events import MIN_VOLATILITY_RETURNS
from crypto_simulator.analytics.market import MarketSummary, analyze_market
from crypto_simulator.analytics.psychology import COMPONENTS, analyze_psychology
from crypto_simulator.core.coin_simulator import SimulationTick

DEFAULT_WINDOW_SIZE = 20

RISING = "rising"
FALLING = "falling"
FLAT = "flat"
DIRECTIONS = (RISING, FALLING, FLAT)

LOW_VOLATILITY = "low_volatility"
NORMAL_VOLATILITY = "normal_volatility"
HIGH_VOLATILITY = "high_volatility"
VOLATILITY_CLASSES = (LOW_VOLATILITY, NORMAL_VOLATILITY, HIGH_VOLATILITY)

LOW_VOLUME = "low_volume"
NORMAL_VOLUME = "normal_volume"
HIGH_VOLUME = "high_volume"
VOLUME_CLASSES = (LOW_VOLUME, NORMAL_VOLUME, HIGH_VOLUME)

AT_HIGH = "at_high"
DRAWDOWN = "drawdown"
RECOVERY = "recovery"
MARKET_STATES = (AT_HIGH, DRAWDOWN, RECOVERY)

MIN_REFERENCE_WINDOWS = 4
"""Earlier complete windows needed before a volatility or volume class is
assigned: four values are the fewest that can populate four quartile
bins."""

COVERAGE_NONE = "none"
COVERAGE_PARTIAL = "partial"
COVERAGE_COMPLETE = "complete"
"""Whether every reported window is complete — the same three-level
vocabulary the other Phase 9 modules use, restated rather than imported."""


@dataclass(frozen=True)
class RegimeContext:
    """What else was recorded in a window. Descriptive only: none of it is
    used to assign the window's labels.

    ``event_state_ticks`` counts ticks that recorded an ``EventState``
    (zero for a run with no event engine); ``event_ids``/``event_categories``
    are the distinct live events seen, sorted; ``max_concurrent_events`` is
    the most live at once. The psychology means cover only the
    ``psychology_ticks`` that recorded a state, and are ``None`` without
    one. ``whale_observed_ticks`` counts ticks carrying whale observations.
    """

    event_state_ticks: int
    event_active_ticks: int
    event_ids: tuple[str, ...]
    event_categories: tuple[str, ...]
    max_concurrent_events: int | None
    psychology_ticks: int
    mean_fear: float | None
    mean_fomo: float | None
    mean_conviction: float | None
    mean_uncertainty: float | None
    whale_observed_ticks: int

    @property
    def event_active(self) -> bool | None:
        """Whether any event was live, or ``None`` when no tick recorded an
        event state at all."""
        return None if self.event_state_ticks == 0 else self.event_active_ticks > 0


@dataclass(frozen=True)
class RegimeObservation:
    """One window's labels and the figures that decide them.

    ``market`` is ``analyze_market`` over the window's ticks; every price,
    return, volatility, drawdown and volume figure lives there. The
    remaining numbers are the ones the labels are read from, kept so each
    label can be checked by hand: ``net_log_return`` (consecutive returns
    only) against ``market.realized_volatility`` for ``direction``;
    ``volatility_reference``/``volume_reference`` (the lower and upper
    quartiles of earlier complete windows, or ``None``) for the two
    classes; and ``running_peak`` with ``drawdown_at_start``/
    ``drawdown_at_end`` (from the highest price observed up to each point)
    for ``market_state``.
    """

    window_index: int
    start_tick: int
    end_tick: int
    tick_count: int
    expected_tick_count: int
    market: MarketSummary
    net_log_return: float | None
    volume_per_tick: float | None
    running_peak: float | None
    drawdown_at_start: float | None
    drawdown_at_end: float | None
    volatility_reference: tuple[float, float] | None
    volume_reference: tuple[float, float] | None
    direction: str | None
    volatility: str | None
    volume: str | None
    market_state: str | None
    context: RegimeContext

    @property
    def complete(self) -> bool:
        return self.tick_count == self.expected_tick_count

    @property
    def price_change(self) -> float | None:
        """Last price minus first price, Step 1's open and close."""
        m = self.market
        return None if m.open_price is None else m.close_price - m.open_price

    @property
    def manipulation_volume(self) -> float:
        """Manipulator plus wash volume, two of ``VolumeBreakdown``'s
        disjoint categories — context, not a label."""
        breakdown = self.market.volume_breakdown
        return breakdown.manipulator_volume + breakdown.wash_volume

    @property
    def manipulation_active(self) -> bool:
        breakdown = self.market.volume_breakdown
        return breakdown.manipulator_fills + breakdown.wash_legs > 0

    @property
    def description(self) -> str:
        """The four labels joined, ``unavailable`` for a missing one."""
        return " / ".join(label or "unavailable"
                          for label in (self.direction, self.volatility, self.volume, self.market_state))


@dataclass(frozen=True)
class RegimeReport:
    """Descriptive regimes for one finished run.

    ``observations`` is ordered by window. Each ``*_counts`` field lists
    every label of its dimension in taxonomy order, then ``None`` for
    windows where that dimension was unavailable, so every count is
    present even when zero. ``coverage`` is ``"none"`` with no windows,
    ``"complete"`` when every window is complete, ``"partial"`` otherwise.
    """

    ticks: int
    window_size: int
    pricing_mode: str | None
    coverage: str
    observations: tuple[RegimeObservation, ...]
    direction_counts: tuple[tuple[str | None, int], ...]
    volatility_counts: tuple[tuple[str | None, int], ...]
    volume_counts: tuple[tuple[str | None, int], ...]
    market_state_counts: tuple[tuple[str | None, int], ...]

    @property
    def total_windows(self) -> int:
        return len(self.observations)

    @property
    def complete_windows(self) -> int:
        return sum(1 for observation in self.observations if observation.complete)

    @property
    def incomplete_windows(self) -> int:
        return self.total_windows - self.complete_windows

    def window(self, window_index: int) -> RegimeObservation:
        for observation in self.observations:
            if observation.window_index == window_index:
                return observation
        raise KeyError(f"no window {window_index} in this report")


def _require_window_size(window_size: object) -> None:
    if isinstance(window_size, bool) or not isinstance(window_size, int) or window_size < 1:
        raise ValueError(f"window_size must be an integer >= 1 (got {window_size!r})")


def _require_volume(tick: SimulationTick) -> None:
    volume = tick.volume
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(volume) or volume < 0:
        raise ValueError(f"tick {tick.tick} has an invalid volume {volume!r}")


def _quartiles(ordered: Sequence[float]) -> tuple[float, float]:
    """Lower and upper quartile by linear interpolation at rank
    ``p/100 × (n − 1)`` — ``analytics/psychology.py``'s percentile
    convention."""
    return _percentile(ordered, 25), _percentile(ordered, 75)


def _percentile(ordered: Sequence[float], percent: int) -> float:
    low, remainder = divmod(percent * (len(ordered) - 1), 100)
    if remainder == 0:
        return ordered[low]
    return ordered[low] + (ordered[low + 1] - ordered[low]) * (remainder / 100)


def _insert_sorted(values: list[float], value: float) -> None:
    """Insert keeping ``values`` sorted: a binary search for the position,
    then one insert, instead of re-sorting the whole reference."""
    low, high = 0, len(values)
    while low < high:
        middle = (low + high) // 2
        if value < values[middle]:
            high = middle
        else:
            low = middle + 1
    values.insert(low, value)


def _classify(value: float | None, reference: list[float], labels: tuple[str, str, str]):
    """``(label, (lower, upper))`` against the earlier windows' quartiles,
    or ``(None, None)`` when either side is unavailable."""
    if value is None or len(reference) < MIN_REFERENCE_WINDOWS:
        return None, None
    lower, upper = _quartiles(reference)
    low, normal, high = labels
    if value < lower:
        return low, (lower, upper)
    if value > upper:
        return high, (lower, upper)
    return normal, (lower, upper)


def _direction(net: float | None, realized: float | None, returns: int) -> str | None:
    if net is None or realized is None or returns < MIN_VOLATILITY_RETURNS:
        return None
    if net > realized:
        return RISING
    if net < -realized:
        return FALLING
    return FLAT


def _market_state(start: float | None, end: float | None) -> str | None:
    if end is None:
        return None
    if end == 0.0:
        return AT_HIGH
    return RECOVERY if end < start else DRAWDOWN


def _context(ticks: Sequence[SimulationTick]) -> RegimeContext:
    state_ticks = active_ticks = 0
    max_live: int | None = None
    ids: set[str] = set()
    categories: set[str] = set()
    sums = {name: [] for name in COMPONENTS}
    psychology_ticks = whale_ticks = 0
    for tick in ticks:
        state = tick.event_state
        if state is not None:
            state_ticks += 1
            live = len(state.events)
            max_live = live if max_live is None else max(max_live, live)
            if live:
                active_ticks += 1
            for status in state.events:
                ids.add(status.event_id)
                categories.add(status.category)
        if tick.psychology is not None:
            psychology_ticks += 1
            for name in COMPONENTS:
                sums[name].append(getattr(tick.psychology, name))
        if tick.whale_observations:
            whale_ticks += 1

    def mean(name: str) -> float | None:
        return math.fsum(sums[name]) / psychology_ticks if psychology_ticks else None

    return RegimeContext(
        event_state_ticks=state_ticks,
        event_active_ticks=active_ticks,
        event_ids=tuple(sorted(ids)),
        event_categories=tuple(sorted(categories)),
        max_concurrent_events=max_live,
        psychology_ticks=psychology_ticks,
        mean_fear=mean("fear"),
        mean_fomo=mean("fomo"),
        mean_conviction=mean("conviction"),
        mean_uncertainty=mean("uncertainty"),
        whale_observed_ticks=whale_ticks,
    )


def _counts(observations: Sequence[RegimeObservation], attribute: str,
            labels: tuple[str, ...]) -> tuple[tuple[str | None, int], ...]:
    values = [getattr(observation, attribute) for observation in observations]
    return tuple((label, values.count(label)) for label in (*labels, None))


def analyze_regimes(
    ticks: Sequence[SimulationTick],
    *,
    initial_price: float | None = None,
    window_size: int = DEFAULT_WINDOW_SIZE,
    total_supply: float | None = None,
) -> RegimeReport:
    """Label each fixed tick-number window of ``ticks`` with its observed
    direction, volatility, volume and market state.

    ``initial_price`` is the pre-run price (used only when tick 1 is
    present, as in ``analyze_market``); ``total_supply`` enables each
    window's turnover. See the module docstring for every definition.

    Pure: the inputs are not mutated, no randomness is drawn, and the same
    ticks in any order always give the same report. Raises ``ValueError``
    on an invalid ``window_size``, ``initial_price`` or ``total_supply``, a
    non-``SimulationTick`` value, a duplicate tick number, an invalid price
    or volume, mixed pricing modes, or a malformed ``PsychologyState``.
    """
    _require_window_size(window_size)
    ordered = ordered_ticks(ticks)
    for tick in ordered:
        _require_volume(tick)
    overall = analyze_market(ordered, initial_price=initial_price, total_supply=total_supply)
    analyze_psychology(ordered)  # validation only: rejects malformed psychology states

    buckets: dict[int, list[SimulationTick]] = {}
    for tick in ordered:
        buckets.setdefault((tick.tick - 1) // window_size, []).append(tick)

    # One pass over the whole price path: each point's drawdown from the
    # highest price observed up to and including it, bucketed by window.
    drawdowns: dict[int, list[tuple[float, float]]] = {}
    peak = None
    for tick_number, price in price_path(ordered, initial_price):
        peak = price if peak is None or price > peak else peak
        index = 0 if tick_number == PRE_RUN_TICK else (tick_number - 1) // window_size
        drawdowns.setdefault(index, []).append((peak, 1.0 - price / peak))

    volatility_reference: list[float] = []
    volume_reference: list[float] = []
    observations = []
    for index in sorted(buckets):
        window = buckets[index]
        market = analyze_market(window, initial_price=initial_price, total_supply=total_supply)
        returns = log_returns(price_path(window, initial_price))
        net = math.fsum(returns) if returns else None
        volume_per_tick = market.volume_breakdown.total_volume / len(window)
        points = drawdowns.get(index, [])
        start_drawdown = points[0][1] if points else None
        end_drawdown = points[-1][1] if points else None

        volatility_label, volatility_bounds = _classify(
            market.volatility, volatility_reference, VOLATILITY_CLASSES)
        volume_label, volume_bounds = _classify(volume_per_tick, volume_reference, VOLUME_CLASSES)
        observation = RegimeObservation(
            window_index=index,
            start_tick=index * window_size + 1,
            end_tick=(index + 1) * window_size,
            tick_count=len(window),
            expected_tick_count=window_size,
            market=market,
            net_log_return=net,
            volume_per_tick=volume_per_tick,
            running_peak=points[-1][0] if points else None,
            drawdown_at_start=start_drawdown,
            drawdown_at_end=end_drawdown,
            volatility_reference=volatility_bounds,
            volume_reference=volume_bounds,
            direction=_direction(net, market.realized_volatility, len(returns)),
            volatility=volatility_label,
            volume=volume_label,
            market_state=_market_state(start_drawdown, end_drawdown),
            context=_context(window),
        )
        observations.append(observation)
        # Only a complete window joins the reference, and only after its
        # own label is fixed, so no window is ever compared with itself or
        # with anything later.
        if observation.complete:
            if market.volatility is not None:
                _insert_sorted(volatility_reference, market.volatility)
            _insert_sorted(volume_reference, volume_per_tick)

    observations = tuple(observations)
    if not observations:
        coverage = COVERAGE_NONE
    elif all(observation.complete for observation in observations):
        coverage = COVERAGE_COMPLETE
    else:
        coverage = COVERAGE_PARTIAL
    return RegimeReport(
        ticks=len(ordered),
        window_size=window_size,
        pricing_mode=overall.pricing_mode,
        coverage=coverage,
        observations=observations,
        direction_counts=_counts(observations, "direction", DIRECTIONS),
        volatility_counts=_counts(observations, "volatility", VOLATILITY_CLASSES),
        volume_counts=_counts(observations, "volume", VOLUME_CLASSES),
        market_state_counts=_counts(observations, "market_state", MARKET_STATES),
    )
