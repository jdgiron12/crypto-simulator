"""Describing a batch's runs as distributions (Phase 15).

Phase 14 executes batches; this analyses them. It runs no simulation,
opens no database, and knows nothing about how scenarios or runs are
stored — it is handed a finished batch result and reads the reports
already inside it.

**Why it lives in ``analytics``.** It is descriptive statistics over
finished runs, which is what this package is, and it needs this package's
own percentile and volatility conventions. It cannot live in ``services``
because nothing in the simulator's own layers may import ``analytics`` —
analytics observes the simulator, never the other way round. The batch
result is therefore read by attribute rather than imported, the same way
the batch runner keeps its payloads opaque, so this package gains no
dependency on ``services`` either.

**The reports' own numbers, never recomputed.** Every metric aggregated
here is a field ``analytics`` already defines on ``MarketSummary``: the
return is that module's ``cumulative_return`` (``close/open - 1``), the
volatility its sample standard deviation of log returns, the drawdown its
own. Nothing is re-derived from prices, so a figure can never drift from
the one the run's own report gives. Metrics the report deliberately does
not define are deliberately absent here too — there is no absolute price
change, because the report defines none and inventing one would put a
second definition of the same idea in the project.

**Conventions**, chosen to match what the simulator already does rather
than what a statistics library defaults to:

- *mean* is ``fsum(values) / n``, compensated as
  ``analytics/psychology.py`` computes its own means.
- *median* is ``statistics.median`` of the sorted values.
- *percentiles* are the project's single definition, shared from
  ``analytics/_series.percentile``: linear interpolation at rank
  ``p/100 x (n - 1)``. P50 is therefore the median, exactly.
- *standard deviation* is the **sample** one (n - 1), and is ``None``
  below ``MIN_VOLATILITY_RETURNS`` observations — the same rule, and the
  same function, the simulator's own volatility uses. An undefined
  dispersion is reported as undefined and never as zero.

**Missing is missing.** A per-run metric is ``float | None``, where
``None`` means the run could not compute it (no ticks, too few returns,
no total supply). Those runs contribute no observation: a metric's
``count`` is how many runs actually produced it, which may be fewer than
the batch's successful runs. A failed run contributes nothing to any
metric. Nothing missing is ever read as a zero.

**Descriptive only.** These are summaries of what the runs did. There is
no confidence interval, no significance, no forecast and no claim that
one configuration is better than another.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

from crypto_simulator.analytics._series import percentile
from crypto_simulator.analytics.events import MIN_VOLATILITY_RETURNS

__all__ = [
    "AGGREGATED_METRICS",
    "PERCENTILES",
    "AggregateStatistics",
    "MetricStatistics",
    "Percentile",
    "aggregate_batch",
    "aggregate_values",
]

#: The percentiles reported for every metric, in order. P50 is the median
#: by construction, not by coincidence.
PERCENTILES: tuple[int, ...] = (5, 25, 50, 75, 95)

#: The ``MarketSummary`` fields aggregated, in report order. Every one is
#: a number the analytics already define; this list adds no metric of its
#: own. ``total_volume`` is the one that is not a plain attribute — it is
#: ``volume_breakdown``'s own property, read rather than re-added here.
AGGREGATED_METRICS: tuple[str, ...] = (
    "open_price",
    "close_price",
    "cumulative_return",
    "log_return",
    "high_price",
    "low_price",
    "mean_price",
    "mean_return",
    "volatility",
    "realized_volatility",
    "max_drawdown",
    "end_drawdown",
    "market_cap_start",
    "market_cap_end",
    "total_volume",
    "turnover",
    "participant_turnover",
    "average_trade_size",
    "trader_vwap",
)


@dataclass(frozen=True)
class Percentile:
    """One percentile of a metric. ``value`` is ``None`` when there is
    nothing to take a percentile of."""

    percent: int
    value: float | None


@dataclass(frozen=True)
class MetricStatistics:
    """How one metric was distributed across a batch's runs.

    ``count`` is the number of runs that produced this metric, which is
    not always the number of runs that finished. With none, every figure
    is ``None``; with one, everything but the standard deviation is that
    single value.
    """

    metric: str
    count: int
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None
    standard_deviation: float | None
    percentiles: tuple[Percentile, ...]

    def percentile(self, percent: int) -> float | None:
        """The stored value of one percentile, by its number."""
        for entry in self.percentiles:
            if entry.percent == percent:
                return entry.value
        raise ValueError(f"no percentile {percent} in {[p.percent for p in self.percentiles]}")


@dataclass(frozen=True)
class AggregateStatistics:
    """A batch, described.

    The run counts come from the batch itself and are kept apart from any
    metric's ``count``: runs can finish and still not produce a given
    figure.
    """

    requested_runs: int
    successful_runs: int
    failed_runs: int
    metrics: tuple[MetricStatistics, ...]

    def metric(self, name: str) -> MetricStatistics:
        """One metric's statistics, by name."""
        for entry in self.metrics:
            if entry.metric == name:
                return entry
        raise ValueError(f"no metric {name!r}; expected one of {list(AGGREGATED_METRICS)}")


def aggregate_values(metric: str, values: Iterable[float | None]) -> MetricStatistics:
    """Describe one metric's observations.

    ``None`` values are absences and are dropped before anything is
    computed; a non-finite number is an error rather than something to
    average, because the analytics never produce one.
    """
    observations = []
    for index, value in enumerate(values):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{metric}[{index}] must be a number or None (got {value!r})")
        if not math.isfinite(value):
            raise ValueError(f"{metric}[{index}] must be finite (got {value!r})")
        observations.append(float(value))

    count = len(observations)
    if count == 0:
        return MetricStatistics(
            metric=metric,
            count=0,
            mean=None,
            median=None,
            minimum=None,
            maximum=None,
            standard_deviation=None,
            percentiles=tuple(Percentile(percent, None) for percent in PERCENTILES),
        )

    ordered = sorted(observations)
    return MetricStatistics(
        metric=metric,
        count=count,
        mean=math.fsum(observations) / count,
        median=statistics.median(ordered),
        minimum=ordered[0],
        maximum=ordered[-1],
        # Sample standard deviation, undefined below two observations —
        # the simulator's own volatility rule, not a zero.
        standard_deviation=(
            statistics.stdev(ordered) if count >= MIN_VOLATILITY_RETURNS else None
        ),
        percentiles=tuple(
            Percentile(percent, percentile(ordered, percent)) for percent in PERCENTILES
        ),
    )


def aggregate_batch(result: Any) -> AggregateStatistics:
    """Describe every metric across a finished batch's runs.

    Only the runs that finished are read; a failed run contributes no
    observation to anything, and is counted as failed rather than as a
    zero. The metrics come back in ``AGGREGATED_METRICS`` order, so two
    aggregations of the same batch are identical objects.

    ``result`` is a Phase 14 ``BatchResult``, taken by shape rather than
    by type so that this package needs no import from ``services``.
    """
    for attribute in ("requested_runs", "completed", "failed"):
        if not hasattr(result, attribute):
            raise ValueError(
                f"result must be a batch result with .{attribute} "
                f"(got {type(result).__name__})"
            )
    summaries = [_market_summary(run.payload) for run in result.completed]
    return AggregateStatistics(
        requested_runs=result.requested_runs,
        successful_runs=len(result.completed),
        failed_runs=len(result.failed),
        metrics=tuple(
            aggregate_values(metric, [_metric_value(summary, metric) for summary in summaries])
            for metric in AGGREGATED_METRICS
        ),
    )


def _market_summary(payload: Any) -> Any:
    """The market analytics of one finished run.

    Read by attribute rather than by importing a payload type, so this
    module stays independent of which front end produced the run — the
    same reason the batch runner keeps payloads opaque.
    """
    try:
        return payload.report.market
    except AttributeError as exc:  # pragma: no cover - guards a misuse
        raise ValueError(
            "a completed run's payload must expose report.market to be aggregated"
        ) from exc


def _metric_value(summary: Any, metric: str) -> float | None:
    """One metric off one run's summary, as the report holds it."""
    if metric == "total_volume":
        # The analytics' own property; the volume components are never
        # re-added here.
        return summary.volume_breakdown.total_volume
    return getattr(summary, metric)
