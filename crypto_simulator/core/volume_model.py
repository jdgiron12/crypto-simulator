"""``VolumeModel``: synthetic per-tick trading volume.

Phase 1 has no orders, traders, or whales generating real trade volume, so
this produces a plausible-looking, always-positive activity series as a
placeholder — enough to build market-cap/volume dashboards and the
simulation loop against. A later phase that adds real market participants
should replace calls into this with actual summed trade volume, not extend
this model to fake participant behavior.
"""

from __future__ import annotations

import random


class VolumeModel:
    """Generates synthetic trading volume, in units of the coin, per tick."""

    def __init__(self, supply: float, *, base_volume_pct: float = 0.01, seed: int | None = None):
        if supply <= 0:
            raise ValueError("supply must be positive")
        if base_volume_pct < 0:
            raise ValueError("base_volume_pct must not be negative")
        self.supply = supply
        self.base_volume_pct = base_volume_pct
        self._rng = random.Random(seed)

    def next_volume(self) -> float:
        """Return the next tick's simulated volume.

        Centered on ``supply * base_volume_pct`` with multiplicative noise;
        ``abs(...)`` keeps volume non-negative without a hard floor that
        would distort the average.
        """
        baseline = self.supply * self.base_volume_pct
        noise = abs(self._rng.gauss(1.0, 0.5))
        return baseline * noise
