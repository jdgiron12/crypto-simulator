"""Per-tick spread of recorded prices across a batch's runs (Phase 20, Step 8).

A batch runs one configuration under many derived seeds (Phase 14). Every
successful run records its price at ticks 1..N, and every run of one batch
records the same ticks — the configuration is shared and only the seed
differs. This module lines the runs up by tick and describes, tick by tick,
how their recorded prices were spread.

**The Phase 15 statistics, per tick.** Each tick's prices are handed to
``aggregate_values``, so the minimum, P5, P25, median, P75, P95, maximum
and mean use exactly the conventions ``aggregate_batch`` uses — the
project's one percentile (P50 is the median) and its compensated mean.
Nothing here computes a statistic of its own.

**Read by shape.** The batch result is read by attribute, as
``aggregate_batch`` reads it: ``result.completed`` and each run's
``payload.price_series`` of ``(tick, price)`` points. This package gains no
dependency on ``services`` or on a front end.

**Validated, never repaired.** The first successful run's tick sequence
must be consecutive; every other run must record exactly the same ticks,
and every price must be positive and finite. Anything else is a
``ValueError`` naming the run: nothing is truncated, padded or
interpolated. Failed runs contribute nothing, and a batch with no
successful run has no bands (``None``).

**Descriptive only.** The median line and the band edges summarize each
tick on its own; they are not the path of any single run, and they are not
a forecast, a confidence interval or a probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crypto_simulator.analytics._series import is_valid_price
from crypto_simulator.analytics.aggregate import aggregate_values

__all__ = ["PricePathBands", "aggregate_price_paths"]


@dataclass(frozen=True)
class PricePathBands:
    """How the successful runs' recorded prices were spread at each tick.

    Columnar: every tuple has one entry per tick in ``ticks``, and entry
    ``i`` of each describes the ``runs`` prices recorded at ``ticks[i]``.
    ``mean`` is kept alongside the percentiles; it is not the central path.
    """

    runs: int
    ticks: tuple[int, ...]
    minimum: tuple[float, ...]
    p5: tuple[float, ...]
    p25: tuple[float, ...]
    median: tuple[float, ...]
    p75: tuple[float, ...]
    p95: tuple[float, ...]
    maximum: tuple[float, ...]
    mean: tuple[float, ...]


def aggregate_price_paths(result: Any) -> PricePathBands | None:
    """Describe the recorded price at every tick across a batch's
    successful runs, or ``None`` when no run succeeded.

    ``result`` is a Phase 14 ``BatchResult``, taken by shape.

    Raises:
        ValueError: ``result`` has no ``completed`` runs attribute; a
            completed run has no payload, no price series or an empty one;
            its ticks are not consecutive integers or differ from the first
            successful run's; or a price is not positive and finite.
    """
    if not hasattr(result, "completed"):
        raise ValueError(f"result must be a batch result with .completed (got {type(result).__name__})")
    completed = tuple(result.completed)
    if not completed:
        return None

    expected: tuple[int, ...] | None = None
    columns: list[list[float]] = []
    for run in completed:
        name = f"run {getattr(run, 'index', '?')}"
        ticks, prices = _series(run, name)
        if expected is None:
            _require_consecutive(ticks, name)
            expected = ticks
            columns = [[] for _ in ticks]
        elif ticks != expected:
            raise ValueError(f"{name} {_difference(ticks, expected)}; runs of one batch must record the same ticks")
        for column, price in zip(columns, prices):
            column.append(price)

    described = [aggregate_values(f"price at tick {tick}", column) for tick, column in zip(expected, columns)]
    return PricePathBands(
        runs=len(completed),
        ticks=expected,
        minimum=tuple(entry.minimum for entry in described),
        p5=tuple(entry.percentile(5) for entry in described),
        p25=tuple(entry.percentile(25) for entry in described),
        median=tuple(entry.median for entry in described),
        p75=tuple(entry.percentile(75) for entry in described),
        p95=tuple(entry.percentile(95) for entry in described),
        maximum=tuple(entry.maximum for entry in described),
        mean=tuple(entry.mean for entry in described),
    )


def _series(run: Any, name: str) -> tuple[tuple[int, ...], tuple[float, ...]]:
    """One run's recorded ticks and prices, checked."""
    payload = getattr(run, "payload", None)
    if payload is None:
        raise ValueError(f"{name} is marked completed but has no payload")
    series = getattr(payload, "price_series", None)
    if series is None:
        raise ValueError(f"{name} has no recorded price series")
    if not series:
        raise ValueError(f"{name} has an empty price series")
    ticks = []
    prices = []
    for point in series:
        tick, price = point.tick, point.price
        if isinstance(tick, bool) or not isinstance(tick, int):
            raise ValueError(f"{name} has a non-integer tick {tick!r}")
        if not is_valid_price(price):
            raise ValueError(f"{name} has an invalid price {price!r} at tick {tick}")
        ticks.append(tick)
        prices.append(float(price))
    return tuple(ticks), tuple(prices)


def _require_consecutive(ticks: tuple[int, ...], name: str) -> None:
    for previous, current in zip(ticks, ticks[1:]):
        if current != previous + 1:
            raise ValueError(
                f"{name} recorded tick {current} after tick {previous}; a price path needs consecutive ticks"
            )


def _difference(ticks: tuple[int, ...], expected: tuple[int, ...]) -> str:
    """Where a run's ticks first part from the first successful run's."""
    for position, (tick, wanted) in enumerate(zip(ticks, expected)):
        if tick != wanted:
            return (f"recorded tick {tick} at position {position} where the first successful run "
                    f"recorded tick {wanted}")
    return f"recorded {len(ticks)} ticks where the first successful run recorded {len(expected)}"
