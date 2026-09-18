"""Private price-series helpers for the Phase 9 analytics (Step 1 onward).

Small, pure functions over a finished run's ticks. They follow the
conventions ``analytics/events.py`` already uses, so the new analytics
never disagree with it:

- Ticks are ordered by tick number; a repeated tick number raises
  ``ValueError("duplicate tick N")``, the message ``events.py`` and
  ``psychology.py`` raise.
- The price before tick 1 (``initial_price``) is addressed as tick
  ``PRE_RUN_TICK`` = 0, as ``events.py`` looks it up. It is the pre-run
  point, not a simulated tick, and it is part of a price path only when
  tick 1 itself is.
- A return exists only between consecutive tick numbers, so a missing
  tick is never bridged. (The pre-run point and tick 1 are consecutive.)
- Volatility is the sample standard deviation of log returns, with at
  least ``MIN_VOLATILITY_RETURNS`` of them — ``events.py``'s definition.

Nothing here reads anything but the values passed in, draws randomness,
or mutates its inputs.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Sequence

from crypto_simulator.analytics.events import MIN_VOLATILITY_RETURNS
from crypto_simulator.core.coin_simulator import SimulationTick

PRE_RUN_TICK = 0
"""Tick number of the pre-run price (``initial_price``) in a price path —
the point ``events.py`` reads as ``price(0)``. Not a simulated tick."""


def is_valid_price(value: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def require_price(name: str, value: object) -> None:
    if not is_valid_price(value):
        raise ValueError(f"{name} must be a positive finite number (got {value!r})")


def ordered_ticks(ticks: Iterable[SimulationTick]) -> list[SimulationTick]:
    """``ticks`` sorted by tick number, after rejecting non-ticks and
    repeated tick numbers."""
    by_tick: dict[int, SimulationTick] = {}
    for tick in ticks:
        if not isinstance(tick, SimulationTick):
            raise ValueError(f"expected SimulationTick values, got {type(tick).__name__}")
        if tick.tick in by_tick:
            raise ValueError(f"duplicate tick {tick.tick}")
        by_tick[tick.tick] = tick
    return [by_tick[number] for number in sorted(by_tick)]


def price_path(ordered: Sequence[SimulationTick], initial_price: float | None) -> list[tuple[int, float]]:
    """``(tick, price)`` points in order: the pre-run point first when
    ``initial_price`` is given and tick 1 is among ``ordered``, then every
    tick's recorded price. Prices must be positive and finite."""
    for tick in ordered:
        if not is_valid_price(tick.price):
            raise ValueError(f"tick {tick.tick} has an invalid price {tick.price!r}")
    path = [(tick.tick, float(tick.price)) for tick in ordered]
    if initial_price is not None and ordered and ordered[0].tick == 1:
        path.insert(0, (PRE_RUN_TICK, float(initial_price)))
    return path


def consecutive_pairs(path: Sequence[tuple[int, float]]) -> list[tuple[float, float]]:
    """``(previous price, price)`` for every pair of consecutive tick numbers."""
    return [(before, after) for (t0, before), (t1, after) in zip(path, path[1:]) if t1 == t0 + 1]


def simple_returns(path: Sequence[tuple[int, float]]) -> list[float]:
    return [after / before - 1.0 for before, after in consecutive_pairs(path)]


def log_returns(path: Sequence[tuple[int, float]]) -> list[float]:
    # Written exactly as events.py writes it, so the two agree bit for bit.
    return [math.log(after / before) for before, after in consecutive_pairs(path)]


def sample_volatility(returns: Sequence[float]) -> float | None:
    """Sample standard deviation of log returns (events.py's definition)."""
    return statistics.stdev(returns) if len(returns) >= MIN_VOLATILITY_RETURNS else None


def percentile(ordered: Sequence[float], percent: int) -> float:
    """The ``percent``-th percentile of already-sorted ``ordered``.

    The project's one percentile definition, documented in
    ``analytics/psychology.py`` and referred to by ``analytics/
    regimes.py``: linear interpolation between closest ranks, the p-th
    percentile of n sorted values sitting at rank ``p/100 x (n - 1)`` (the
    common "inclusive" definition, so p50 is the median). The rank is
    split in integer arithmetic so the index and the weight are exact.

    Lived in ``psychology.py`` until Phase 15 needed it for cross-run
    statistics too; moved here rather than copied, so the simulator has
    one percentile and not two that could drift apart.
    """
    scaled = percent * (len(ordered) - 1)
    low, remainder = divmod(scaled, 100)
    if remainder == 0:
        return ordered[low]
    return ordered[low] + (ordered[low + 1] - ordered[low]) * (remainder / 100)


def realized_volatility(returns: Sequence[float]) -> float | None:
    """sqrt(sum of squared log returns); not annualized or scaled."""
    return math.sqrt(math.fsum(r * r for r in returns)) if returns else None


@dataclass(frozen=True)
class Drawdown:
    """The deepest fall from a running peak along a price path.

    ``maximum`` is ``1 - trough / peak`` (0.0 for a path that never falls
    below its running peak, and then the ticks are ``None``); ties go to
    the earliest trough. ``recovery_tick`` is the first later point at or
    above that peak, or ``None``. ``end`` is the drawdown at the last point.
    """

    maximum: float
    peak_tick: int | None
    trough_tick: int | None
    recovery_tick: int | None
    end: float


def drawdown(path: Sequence[tuple[int, float]]) -> Drawdown | None:
    if not path:
        return None
    peak_tick, peak = path[0]
    best, best_peak_tick, best_trough_index, best_peak = 0.0, None, None, None
    for index, (tick, price) in enumerate(path):
        if price > peak:
            peak_tick, peak = tick, price
        depth = 1.0 - price / peak
        if depth > best:
            best, best_peak_tick, best_trough_index, best_peak = depth, peak_tick, index, peak
    recovery = None
    if best_trough_index is not None:
        recovery = next((tick for tick, price in path[best_trough_index + 1:] if price >= best_peak), None)
    return Drawdown(
        maximum=best,
        peak_tick=best_peak_tick,
        trough_tick=None if best_trough_index is None else path[best_trough_index][0],
        recovery_tick=recovery,
        end=1.0 - path[-1][1] / peak,
    )
