"""``PsychologyState``: a bounded snapshot of market/trader psychology.

Four dimensions, each in [0, 1], where 0 means "none at all":

    fear         anxiety about losses; the pull toward selling
    fomo         fear of missing out; the pull toward chasing a move
    conviction   confidence in a view; resistance to being swayed
    uncertainty  how unclear the situation feels

Pure data: no randomness, no dependence on the rest of the simulator, and
immutable once created. Out-of-range or non-finite values are rejected
rather than clamped, so a bug upstream surfaces instead of being hidden.
Nothing consumes these states yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _require_unit_interval(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1] (got {value!r})")


@dataclass(frozen=True)
class PsychologyState:
    """Fear, FOMO, conviction and uncertainty, each in [0, 1].

    The defaults are the neutral state (all zeros); ``neutral()`` names it.
    """

    fear: float = 0.0
    fomo: float = 0.0
    conviction: float = 0.0
    uncertainty: float = 0.0

    def __post_init__(self) -> None:
        for name in ("fear", "fomo", "conviction", "uncertainty"):
            _require_unit_interval(name, getattr(self, name))

    @classmethod
    def neutral(cls) -> PsychologyState:
        """The state with no fear, FOMO, conviction or uncertainty."""
        return cls()
