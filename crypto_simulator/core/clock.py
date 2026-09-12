"""``SimulationClock``: tracks simulated time independent of wall-clock time.

Keeping simulation time as an explicit, advanceable counter (rather than
reading ``datetime.now()`` throughout the codebase) is what will let the
simulator later run faster/slower than real time, replay history
deterministically, and be tested without sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class SimulationClock:
    """Advances the simulation forward one tick at a time.

    Attributes:
        tick: Number of ticks elapsed since the clock started.
        started_at: Wall-clock time the simulation began (for reference only).
        tick_interval: Simulated seconds represented by a single tick.
    """

    tick_interval: float = 1.0
    tick: int = 0
    started_at: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now(timezone.utc)

    def advance(self, steps: int = 1) -> int:
        """Advance the clock by ``steps`` ticks and return the new tick count.

        TODO(roadmap): no simulation logic runs from this yet — the market
        engine will subscribe to clock advances once tick-driven price
        generation is implemented.
        """
        if steps <= 0:
            raise ValueError("steps must be positive")
        self.tick += steps
        return self.tick

    @property
    def simulated_time(self) -> datetime:
        """Current simulated timestamp, derived from tick count."""
        return self.started_at + timedelta(seconds=self.tick * self.tick_interval)

    def reset(self) -> None:
        self.tick = 0
        self.started_at = datetime.now(timezone.utc)
