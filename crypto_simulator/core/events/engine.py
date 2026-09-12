"""``EventEngine``: the event timeline and its combined effect per tick.

The engine holds every event it has been given — scheduled up front or
injected later — and never drops one, so expired events stay in the
timeline. ``state(tick)`` is a pure function of the timeline and the
tick; nothing is advanced or consumed, so querying is repeatable.

Overlapping events combine as:
    sentiment             clamp(sum(sentiment_i * intensity_i), -1, 1)
    volatility_multiplier 1 + sum(volatility_boost_i * intensity_i)
    attention_multiplier  1 + sum(attention_i * intensity_i)

Events are kept sorted by ``(start_tick, event_id)`` and summed in that
order, so the result doesn't depend on the order events were supplied.
How each pricing mode translates these effects is up to the simulator,
not this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from crypto_simulator.core.events.event import EventPhase, MarketEvent

_LIVE_PHASES = (EventPhase.ACTIVE, EventPhase.DECAYING)


@dataclass(frozen=True)
class EventStatus:
    """One live (active or decaying) event at a tick."""

    event_id: str
    category: str
    phase: EventPhase
    intensity: float


@dataclass(frozen=True)
class EventState:
    """Combined effect of every live event at ``tick``.

    This is simulator ground truth: it names the events and their
    strengths. Code modelling market participants may consume the effects;
    analysis of observable market data should not see it. The defaults are
    the neutral state (no live events).
    """

    tick: int
    sentiment: float = 0.0
    volatility_multiplier: float = 1.0
    attention_multiplier: float = 1.0
    events: tuple[EventStatus, ...] = ()


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class EventEngine:
    """Timeline of ``MarketEvent``s: scheduled up front or injected later."""

    def __init__(self, events: Iterable[MarketEvent] = ()) -> None:
        self._events: list[MarketEvent] = []
        for event in events:
            self._add(event)

    @property
    def events(self) -> tuple[MarketEvent, ...]:
        """Every event, in any phase, ordered by ``(start_tick, event_id)``."""
        return tuple(self._events)

    def inject(self, event: MarketEvent, *, current_tick: int) -> None:
        """Add ``event`` during a run.

        ``current_tick`` is the last tick already simulated; the event must
        start after it, so states already produced never change.
        """
        if isinstance(current_tick, bool) or not isinstance(current_tick, int) or current_tick < 0:
            raise ValueError(f"current_tick must be an integer >= 0 (got {current_tick!r})")
        if not isinstance(event, MarketEvent):
            raise TypeError(f"expected a MarketEvent, got {type(event).__name__}")
        if event.start_tick <= current_tick:
            raise ValueError(
                f"Event {event.event_id!r} starts at tick {event.start_tick}, but tick "
                f"{current_tick} has already been simulated; events can't be backdated"
            )
        self._add(event)

    def state(self, tick: int) -> EventState:
        statuses: list[EventStatus] = []
        sentiment = volatility = attention = 0.0
        for event in self._events:
            phase = event.phase_at(tick)
            if phase not in _LIVE_PHASES:
                continue
            intensity = event.intensity_at(tick)
            statuses.append(EventStatus(event.event_id, event.category, phase, intensity))
            sentiment += event.sentiment * intensity
            volatility += event.volatility_boost * intensity
            attention += event.attention * intensity
        return EventState(
            tick=tick,
            sentiment=_clamp(sentiment),
            volatility_multiplier=1.0 + volatility,
            attention_multiplier=1.0 + attention,
            events=tuple(statuses),
        )

    def _add(self, event: MarketEvent) -> None:
        if not isinstance(event, MarketEvent):
            raise TypeError(f"expected a MarketEvent, got {type(event).__name__}")
        if any(existing.event_id == event.event_id for existing in self._events):
            raise ValueError(f"Duplicate event_id {event.event_id!r}")
        self._events.append(event)
        self._events.sort(key=lambda e: (e.start_tick, e.event_id))
