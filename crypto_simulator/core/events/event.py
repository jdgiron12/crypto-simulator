"""``MarketEvent``: one fictional news/external event and its lifecycle.

An event is pure data. It never touches prices, pools, wallets or
traders: consumers ask it (usually through ``EventEngine``) how strongly
it applies at a given tick and translate that into their own mechanisms.

Lifecycle, by tick::

    SCHEDULED  tick < start_tick                          intensity 0
    ACTIVE     start_tick <= tick <= last_active_tick     intensity 1
    DECAYING   the next ``decay_ticks`` ticks             linear, strictly between 1 and 0
    EXPIRED    tick >= expires_at                         intensity 0

During decay step ``j`` (1 .. ``decay_ticks``) the intensity is
``(decay_ticks + 1 - j) / (decay_ticks + 1)`` — e.g. 0.75, 0.5, 0.25 for
three decay ticks — so a decaying event is never back at full strength
and never already zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class EventPhase(str, Enum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    DECAYING = "decaying"
    EXPIRED = "expired"


def _require_text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string (got {value!r})")


def _require_finite(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")


def _require_tick_count(name: str, value: object, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum} (got {value!r})")


@dataclass(frozen=True)
class MarketEvent:
    """A fictional event with fully resolved effects.

    Effects, each applied at the event's current intensity:
        sentiment: directional tone in [-1, 1] (> 0 good news, < 0 bad news).
        volatility_boost: >= 0; at full intensity volatility is scaled by
            ``1 + volatility_boost``.
        attention: >= 0; at full intensity participation is scaled by
            ``1 + attention``.

    ``severity`` in (0, 1] records how big the event is; ``create_event``
    uses it to scale a catalog profile into the effects above, and it is
    kept as ground-truth metadata. ``category`` is a free label (the
    catalog's keys by convention). Ticks are 1-based, like
    ``SimulationClock`` after its first advance.
    """

    event_id: str
    category: str
    severity: float
    sentiment: float
    volatility_boost: float
    attention: float
    start_tick: int
    duration: int
    decay_ticks: int = 0
    headline: str = ""

    def __post_init__(self) -> None:
        _require_text("event_id", self.event_id)
        _require_text("category", self.category)
        # Severity first: create_event derives the effects from it, so a bad
        # severity should be reported as such, not as a bad sentiment.
        _require_finite("severity", self.severity)
        if not 0.0 < self.severity <= 1.0:
            raise ValueError(f"severity must be within (0, 1] (got {self.severity!r})")
        _require_finite("sentiment", self.sentiment)
        if not -1.0 <= self.sentiment <= 1.0:
            raise ValueError(f"sentiment must be within [-1, 1] (got {self.sentiment!r})")
        for name in ("volatility_boost", "attention"):
            value = getattr(self, name)
            _require_finite(name, value)
            if value < 0:
                raise ValueError(f"{name} must not be negative (got {value!r})")
        _require_tick_count("start_tick", self.start_tick, 1)
        _require_tick_count("duration", self.duration, 1)
        _require_tick_count("decay_ticks", self.decay_ticks, 0)
        if not isinstance(self.headline, str):
            raise ValueError(f"headline must be a string (got {self.headline!r})")

    @property
    def last_active_tick(self) -> int:
        """Last tick at full intensity."""
        return self.start_tick + self.duration - 1

    @property
    def expires_at(self) -> int:
        """First tick the event no longer has any effect."""
        return self.start_tick + self.duration + self.decay_ticks

    def phase_at(self, tick: int) -> EventPhase:
        if tick < self.start_tick:
            return EventPhase.SCHEDULED
        if tick <= self.last_active_tick:
            return EventPhase.ACTIVE
        if tick < self.expires_at:
            return EventPhase.DECAYING
        return EventPhase.EXPIRED

    def intensity_at(self, tick: int) -> float:
        """How strongly the event applies at ``tick``, in [0, 1]."""
        phase = self.phase_at(tick)
        if phase is EventPhase.ACTIVE:
            return 1.0
        if phase is EventPhase.DECAYING:
            step = tick - self.last_active_tick
            return (self.decay_ticks + 1 - step) / (self.decay_ticks + 1)
        return 0.0
