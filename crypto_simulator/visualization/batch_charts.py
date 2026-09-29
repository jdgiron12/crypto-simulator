"""Batch Plotly chart builders (Phase 20, Step 6).

Pure functions over a batch's already-computed values: numbers in, a
``go.Figure`` out. No Streamlit, no simulation, no data access, and no
statistic of their own — every mean, median, percentile, minimum and
maximum drawn here is handed in from Phase 15's ``AggregateStatistics``.
The histogram's bins are Plotly's, drawn over the successful runs' own
values. Inputs are never mutated, and the same inputs always give the same
figure.

**Descriptive only.** A batch is one configuration run under many derived
seeds. These figures show how those simulated runs were spread; every one
carries a disclosure saying it is not a forecast and not a real-market
probability.
"""

from __future__ import annotations

import math
from typing import Sequence

import plotly.graph_objects as go

__all__ = [
    "FULL_RANGE_TRACE",
    "HISTOGRAM_DISCLOSURE",
    "INNER_SPREAD_TRACE",
    "MEAN_TRACE",
    "MEDIAN_TRACE",
    "OUTER_SPREAD_TRACE",
    "RANGE_DISCLOSURE",
    "RUNS_TRACE",
    "aggregate_range_chart",
    "run_histogram_chart",
]

RANGE_DISCLOSURE = "Descriptive spread of successful simulated runs; not a forecast or real-market probability."
HISTOGRAM_DISCLOSURE = (
    "Distribution of values recorded by successful simulated runs; not a real-market probability distribution."
)

#: Trace names, shared with the tests.
RUNS_TRACE = "Successful simulated runs"
FULL_RANGE_TRACE = "Minimum to maximum"
OUTER_SPREAD_TRACE = "P5 to P95"
INNER_SPREAD_TRACE = "P25 to P75"
MEDIAN_TRACE = "Median (P50)"
MEAN_TRACE = "Mean"


def aggregate_range_chart(
    *,
    label: str,
    minimum: float,
    p5: float,
    p25: float,
    median: float,
    p75: float,
    p95: float,
    maximum: float,
    mean: float,
    count: int,
    title: str,
) -> go.Figure:
    """One metric's aggregate as nested horizontal ranges: minimum to
    maximum, P5 to P95 and P25 to P75, with median and mean markers.

    Every value is drawn as given. With one successful run all of them are
    that run's value, and the ranges collapse to a point.

    Raises:
        ValueError: a value is ``None`` or not finite, or ``count`` is not
            positive — a metric no run computed has no range to draw.
    """
    values = {"minimum": minimum, "p5": p5, "p25": p25, "median": median,
              "p75": p75, "p95": p95, "maximum": maximum, "mean": mean}
    for name, value in values.items():
        _require_finite(name, value)
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError(f"count must be a positive int (got {count!r})")

    y = [label, label]
    fig = go.Figure(
        data=[
            go.Scatter(
                x=[minimum, maximum], y=y, mode="lines+markers", name=FULL_RANGE_TRACE,
                line={"width": 2}, marker={"symbol": "line-ns-open", "size": 14},
                hovertemplate="%{x:,.6g}<extra>" + FULL_RANGE_TRACE + "</extra>",
            ),
            go.Scatter(
                x=[p5, p95], y=y, mode="lines", name=OUTER_SPREAD_TRACE, line={"width": 10},
                hovertemplate="%{x:,.6g}<extra>" + OUTER_SPREAD_TRACE + "</extra>",
            ),
            go.Scatter(
                x=[p25, p75], y=y, mode="lines", name=INNER_SPREAD_TRACE, line={"width": 20},
                hovertemplate="%{x:,.6g}<extra>" + INNER_SPREAD_TRACE + "</extra>",
            ),
            go.Scatter(
                x=[median], y=[label], mode="markers", name=MEDIAN_TRACE,
                marker={"symbol": "line-ns-open", "size": 30, "line": {"width": 3}},
                hovertemplate="%{x:,.6g}<extra>" + MEDIAN_TRACE + "</extra>",
            ),
            go.Scatter(
                x=[mean], y=[label], mode="markers", name=MEAN_TRACE,
                marker={"symbol": "diamond", "size": 12},
                hovertemplate="%{x:,.6g}<extra>" + MEAN_TRACE + "</extra>",
            ),
        ]
    )
    runs = "run" if count == 1 else "runs"
    fig.update_layout(
        title=f"{title}<br><sup>{RANGE_DISCLOSURE} {count} successful {runs}.</sup>",
        xaxis_title=label,
        yaxis={"showticklabels": False},
        height=300,
    )
    return fig


def run_histogram_chart(
    values: Sequence[float | None],
    *,
    label: str,
    mean: float,
    median: float,
    title: str,
) -> go.Figure:
    """A histogram of one metric over the successful runs, one observation
    per run, with the aggregate's mean and median as reference lines.

    ``None`` values are runs that did not compute the metric and are left
    out, as ``aggregate_batch`` leaves them out; nothing stands in for them.

    Raises:
        ValueError: no value is left to draw, or a value, the mean or the
            median is not finite.
    """
    observed = [value for value in values if value is not None]
    if not observed:
        raise ValueError(f"no run recorded a value for {label!r}")
    for index, value in enumerate(observed):
        _require_finite(f"values[{index}]", value)
    _require_finite("mean", mean)
    _require_finite("median", median)

    fig = go.Figure(
        data=[
            go.Histogram(
                x=observed, name=RUNS_TRACE,
                hovertemplate=f"{label} %{{x}}<br>%{{y}} runs<extra></extra>",
            )
        ]
    )
    fig.add_vline(x=median, line_dash="solid", line_width=2, name=MEDIAN_TRACE,
                  annotation_text=MEDIAN_TRACE, annotation_position="top left")
    fig.add_vline(x=mean, line_dash="dash", line_width=2, name=MEAN_TRACE,
                  annotation_text=MEAN_TRACE, annotation_position="top right")
    fig.update_layout(
        title=f"{title}<br><sup>{HISTOGRAM_DISCLOSURE}</sup>",
        xaxis_title=label,
        yaxis_title="Successful simulated runs",
        showlegend=False,
        bargap=0.05,
    )
    return fig


def _require_finite(name: str, value: float | None) -> None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number (got {value!r})")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite (got {value!r})")
