"""Descriptive market paths around news events (Phase 9, Step 4).

Post-processing only: reads ``SimulationTick``s and the ``MarketEvent``
timeline and returns frozen results. Nothing here feeds back into the
simulation, draws random numbers, or mutates its inputs. This module adds
nothing that ``analytics/events.py`` (event observations) and
``analytics/market.py`` (Step 1's price/return/volume/drawdown
definitions) do not already define — it only *partitions* a run's ticks
into four windows per event and hands each partition to ``analyze_market``
unchanged, so every figure is Step 1's exact formula, never a copy of it.

**Windows**, derived only from the event's own ground-truth lifecycle
(``MarketEvent.start_tick``/``last_active_tick``/``expires_at``,
``EventPhase`` — never guessed from price behavior), and non-overlapping
by construction (every tick belongs to exactly one):

    pre_event   ``start_tick - baseline_window`` .. ``start_tick - 1``
    active      ``start_tick`` .. ``last_active_tick``        (EventPhase.ACTIVE)
    decay       ``last_active_tick + 1`` .. ``expires_at - 1`` (EventPhase.DECAYING)
    post_event  ``expires_at`` .. ``expires_at + post_window - 1``
    effect      ``start_tick`` .. ``expires_at - 1`` (active + decay combined —
                "while the event had any effect at all"; convenience window
                for peak/trough/expiration-price questions that span both)

``baseline_window``/``post_window`` are the exact ``analytics/events.py``
concepts (same names, same defaults, same parameters) reused for the
pre/post window *lengths*; they are not recomputed. Note this module's
``post_event`` window starts at ``expires_at`` (the first tick with zero
effect), which deliberately differs from ``analytics/events.py``'s own
"post window" (``post_window`` ticks after ``last_active_tick``, which can
overlap the decaying phase) — that coarser two-window view is Step 1's;
this module's four-way split is what Step 4 adds, and no tick is counted
in more than one of pre/active/decay/post.

A window with nothing to request by construction (``decay_ticks == 0``
has no decay window; an event within ``baseline_window`` ticks of the
run's start has no full pre-event window) is ``None`` — never an empty
``MarketSummary`` standing in for "not applicable". A window that *could*
exist but has fewer recorded ticks than requested (data starts later,
gaps, the run ended early) still gets a real ``EventWindow`` whose
``complete`` property is ``False`` — the observed subset is analysed
honestly, per ``analyze_market``'s own conventions, never padded or
bridged across a gap.

**Named prices** (section 7 of the spec this implements) are not
duplicated as separate fields; they are exactly these nested reads:

    pre-event price   pre_event.market.close_price   (None with no pre_event window)
    activation price  active.market.open_price
    peak price        effect.market.high_price
    trough price       effect.market.low_price
    expiration price  effect.market.close_price       (price at expires_at - 1)
    post-event price  post_event.market.close_price

**Volume** is exactly ``analyze_market``'s ``VolumeBreakdown`` per window:
background/whale/organic/manipulator/wash in random-walk mode, trader
swap volume only in AMM mode (Phase 8 rejects whales there, so
``whale_volume`` is naturally ``0.0``, never inferred). Whale volume here
reads ``SimulationTick.whale_trades`` directly (via ``analyze_market``),
which the simulator records whenever a whale trades whether or not
``whale_observation`` was turned on — it is not the richer per-whale
detail ``analytics/whale_activity.py`` (Step 3) adds, which does need
that flag; this module does not attempt Step 3's per-whale breakdown.

**Comparisons** across pre/active/decay/post (mean price, mean return,
volatility, volume, volume per tick, participant volume) are made by
reading the corresponding field off each window's embedded
``MarketSummary`` directly — there is no separate "comparison" object
duplicating those fields under new names. These are observations only:
"observed during", "observed before", "observed after", never a claimed
effect or a trading cue — other events, participants and simulated noise
act in the same windows.

**Category aggregation** (``CategoryActivity``) groups events by their
ground-truth ``category``: event count, observed ticks, mean severity and
sentiment, the mean active/post-window return and active-window
volatility (over whichever events have one), and total active-window
volume. Categories are listed, never ranked; there is no "best" or
"worst" category.

**Overlap** reuses ``analyze_events``'s own overlap detection
(``overlapping_event_ids``) verbatim. Overlapping events keep separate
identities and separate windows; this module never merges them into one
synthetic event or attributes a window's numbers to one event over
another live at the same time.

Conventions shared with ``analytics/events.py`` and ``analytics/market.py``:

- Ticks are ordered by tick number (duplicates rejected) before anything
  reads them.
- Event ids must be unique across the supplied ``events``; a repeat is
  rejected rather than silently merged (the same contract
  ``core/events/engine.py``'s ``EventEngine`` already enforces at
  construction — this module enforces it too, since it is not guaranteed
  for a hand-built ``events`` sequence bypassing ``EventEngine``).
- An event whose ``start_tick`` lies outside the supplied ticks is
  skipped, exactly as ``analyze_events`` already skips it (it may still
  appear in another event's ``overlapping_event_ids`` if its live span
  reaches into the data).
- Returns are fractions (0.05 = +5%), like every threshold in the project.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from crypto_simulator.analytics._series import ordered_ticks
from crypto_simulator.analytics.events import (
    DEFAULT_BASELINE_WINDOW,
    DEFAULT_POST_WINDOW,
    EventGroundTruth,
    analyze_events,
)
from crypto_simulator.analytics.market import MarketSummary, analyze_market
from crypto_simulator.core.coin_simulator import SimulationTick
from crypto_simulator.core.events.event import MarketEvent


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values)


@dataclass(frozen=True)
class EventWindow:
    """One phase-window of one event's price/volume path.

    ``requested_start``/``requested_end`` are the tick numbers the window
    covers by the event's own lifecycle; ``ticks_requested`` is the length
    of that span. ``market`` is ``analyze_market``'s own summary over
    whichever of those ticks were actually supplied, so every return,
    drawdown and volume figure is Step 1's exact definition — nothing here
    recomputes one. ``complete`` says whether every requested tick was
    present; a window can be real and analysable while still incomplete
    (data starting later, a gap, or the run ending early), and this is how
    that is preserved rather than silently assumed away.
    """

    requested_start: int
    requested_end: int
    ticks_requested: int
    market: MarketSummary

    @property
    def ticks_observed(self) -> int:
        return self.market.ticks

    @property
    def complete(self) -> bool:
        return self.ticks_observed == self.ticks_requested

    @property
    def volume_per_tick(self) -> float | None:
        """Total window volume divided by ticks actually observed, or
        ``None`` with none. Mirrors ``analytics/events.py``'s
        ``volume_per_tick`` naming."""
        if self.ticks_observed == 0:
            return None
        return self.market.volume_breakdown.total_volume / self.ticks_observed


@dataclass(frozen=True)
class EventPathSummary:
    """One event's ground truth plus its four descriptive windows.

    ``pre_event``/``decay`` are ``None`` when that window has nothing to
    request by construction (see the module docstring); ``active``,
    ``post_event`` and ``effect`` always exist, since an event's own
    ``duration``/``post_window``/``decay_ticks`` bounds can never make
    those spans empty.
    """

    ground_truth: EventGroundTruth
    overlapping_event_ids: tuple[str, ...]
    pre_event: EventWindow | None
    active: EventWindow
    decay: EventWindow | None
    post_event: EventWindow
    effect: EventWindow

    @property
    def event_id(self) -> str:
        return self.ground_truth.event_id

    @property
    def overlapping(self) -> bool:
        return bool(self.overlapping_event_ids)

    @property
    def overlap_count(self) -> int:
        return len(self.overlapping_event_ids)


@dataclass(frozen=True)
class CategoryActivity:
    """Descriptive aggregation over every reported event sharing one
    ``category``. Listed, never ranked — there is no "best"/"worst"
    category and no causal claim about what a category's events did to
    price. ``active_return``/``post_event_return``/``volatility`` are
    means over whichever member events have one (``None`` with none);
    ``volume`` is the sum of active-window volume across members, and
    ``observed_ticks`` the sum of active-window ticks actually observed.
    """

    category: str
    event_count: int
    observed_ticks: int
    mean_severity: float
    mean_sentiment: float
    active_return: float | None
    post_event_return: float | None
    volume: float
    volatility: float | None


@dataclass(frozen=True)
class EventWindowReport:
    """Descriptive event-window analytics for one finished run.

    ``events`` is ordered by ``(start_tick, event_id)``, exactly
    ``analyze_events``'s own order; ``categories`` is ordered by category
    name.
    """

    ticks: int
    events: tuple[EventPathSummary, ...]
    categories: tuple[CategoryActivity, ...]

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(path.event_id for path in self.events)

    def event(self, event_id: str) -> EventPathSummary:
        for path in self.events:
            if path.event_id == event_id:
                return path
        raise KeyError(f"no event {event_id!r} in this report; got {list(self.event_ids)}")

    @property
    def category_names(self) -> tuple[str, ...]:
        return tuple(activity.category for activity in self.categories)

    def category(self, name: str) -> CategoryActivity:
        for activity in self.categories:
            if activity.category == name:
                return activity
        raise KeyError(f"no category {name!r} in this report; got {list(self.category_names)}")


def _validate_unique_event_ids(events: Sequence[MarketEvent]) -> None:
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            raise ValueError(f"duplicate event_id {event.event_id!r}; events must have unique ids")
        seen.add(event.event_id)


def _window(by_tick: dict[int, SimulationTick], lo: int, hi: int,
           initial_price: float | None, total_supply: float | None) -> EventWindow | None:
    lo = max(lo, 1)
    if lo > hi:
        return None
    window_ticks = [by_tick[t] for t in range(lo, hi + 1) if t in by_tick]
    market = analyze_market(window_ticks, initial_price=initial_price, total_supply=total_supply)
    return EventWindow(requested_start=lo, requested_end=hi, ticks_requested=hi - lo + 1, market=market)


def _event_path(
    event: MarketEvent, by_tick: dict[int, SimulationTick], ground_truth: EventGroundTruth,
    overlapping_event_ids: tuple[str, ...], initial_price: float | None, total_supply: float | None,
    post_window: int, baseline_window: int,
) -> EventPathSummary:
    active = _window(by_tick, event.start_tick, event.last_active_tick, initial_price, total_supply)
    post_event = _window(by_tick, event.expires_at, event.expires_at + post_window - 1,
                         initial_price, total_supply)
    effect = _window(by_tick, event.start_tick, event.expires_at - 1, initial_price, total_supply)
    return EventPathSummary(
        ground_truth=ground_truth,
        overlapping_event_ids=overlapping_event_ids,
        pre_event=_window(by_tick, event.start_tick - baseline_window, event.start_tick - 1,
                          initial_price, total_supply),
        active=active,
        decay=(_window(by_tick, event.last_active_tick + 1, event.expires_at - 1, initial_price, total_supply)
              if event.decay_ticks > 0 else None),
        post_event=post_event,
        effect=effect,
    )


def _category_activity(category: str, members: Sequence[EventPathSummary]) -> CategoryActivity:
    active_returns = [m.active.market.cumulative_return for m in members
                      if m.active.market.cumulative_return is not None]
    post_returns = [m.post_event.market.cumulative_return for m in members
                    if m.post_event.market.cumulative_return is not None]
    volatilities = [m.active.market.volatility for m in members if m.active.market.volatility is not None]
    return CategoryActivity(
        category=category,
        event_count=len(members),
        observed_ticks=sum(m.active.ticks_observed for m in members),
        mean_severity=_mean([m.ground_truth.severity for m in members]),
        mean_sentiment=_mean([m.ground_truth.sentiment for m in members]),
        active_return=_mean(active_returns) if active_returns else None,
        post_event_return=_mean(post_returns) if post_returns else None,
        volume=math.fsum(m.active.market.volume_breakdown.total_volume for m in members),
        volatility=_mean(volatilities) if volatilities else None,
    )


def analyze_event_windows(
    ticks: Sequence[SimulationTick],
    events: Iterable[MarketEvent],
    *,
    initial_price: float | None = None,
    total_supply: float | None = None,
    post_window: int = DEFAULT_POST_WINDOW,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    trader_count: int | None = None,
    random_event_ids: Iterable[str] | None = None,
) -> EventWindowReport:
    """Describe the market paths recorded around ``events`` on ``ticks``.

    ``initial_price`` and ``total_supply`` feed straight into
    ``analyze_market`` for every window (market cap, turnover, and the
    pre-run price point when a window's first tick is 1). ``post_window``/
    ``baseline_window`` are ``analytics/events.py``'s own window-length
    parameters, reused verbatim for this module's post-event and
    pre-event window lengths. ``trader_count``/``random_event_ids`` pass
    straight through to ``analyze_events`` for participation rate and
    provenance.

    Only events whose ``start_tick`` falls within the supplied ticks are
    reported — exactly ``analyze_events``'s own inclusion rule, reused
    rather than reimplemented; an out-of-range event may still appear in
    another event's ``overlapping_event_ids``.

    Pure: the inputs are not mutated, no randomness is drawn, and the same
    ticks and events always produce the same report whatever order they
    arrive in. Raises ``ValueError`` on non-``SimulationTick`` values,
    duplicate tick numbers, or a duplicate event id.
    """
    ordered = ordered_ticks(ticks)
    by_tick = {tick.tick: tick for tick in ordered}
    events = list(events)
    _validate_unique_event_ids(events)
    observations = analyze_events(
        ordered, events, post_window=post_window, baseline_window=baseline_window,
        initial_price=initial_price, trader_count=trader_count, random_event_ids=random_event_ids,
    )
    by_id = {event.event_id: event for event in events}
    paths = tuple(
        _event_path(
            by_id[observation.ground_truth.event_id], by_tick, observation.ground_truth,
            observation.overlapping_event_ids, initial_price, total_supply, post_window, baseline_window,
        )
        for observation in observations
    )
    by_category: dict[str, list[EventPathSummary]] = {}
    for path in paths:
        by_category.setdefault(path.ground_truth.category, []).append(path)
    categories = tuple(
        _category_activity(category, by_category[category]) for category in sorted(by_category)
    )
    return EventWindowReport(ticks=len(ordered), events=paths, categories=categories)
