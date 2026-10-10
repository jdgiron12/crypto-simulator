"""Scenario-comparison Plotly chart builders (Phase 20, Step 7).

Pure functions over already-reduced values: one ``ComparisonRange`` per
configuration in, a ``go.Figure`` out. No Streamlit, no simulation, no
analytics and no statistic of their own — every value drawn is one Phase
15's ``aggregate_batch`` already computed for that configuration's batch.
Configurations are drawn in the order given, which is the order they were
selected in; nothing is sorted by value, ranked or scored.

**Descriptive only.** Each row is a separate batch of synthetic runs. The
figure shows how each batch's runs were spread side by side and carries a
disclosure saying it establishes no causal effect, forecast or real-market
probability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import plotly.graph_objects as go

from crypto_simulator.visualization.style import (
    ACCENT,
    CHART_LAYOUT,
    TEXT,
    TEXT_MUTED,
    WARNING,
    with_alpha,
)

__all__ = [
    "COMPARISON_DISCLOSURE",
    "FULL_RANGE_TRACE",
    "INNER_SPREAD_TRACE",
    "MEAN_TRACE",
    "MEDIAN_TRACE",
    "OUTER_SPREAD_TRACE",
    "ComparisonRange",
    "comparison_range_chart",
]

COMPARISON_DISCLOSURE = (
    "These charts compare descriptive statistics from separate batches of synthetic simulations. They do "
    "not establish causal effects, forecasts, or real-market probabilities."
)

FULL_RANGE_TRACE = "Minimum to maximum"
OUTER_SPREAD_TRACE = "P5 to P95"
INNER_SPREAD_TRACE = "P25 to P75"
MEDIAN_TRACE = "Median (P50)"
MEAN_TRACE = "Mean"


@dataclass(frozen=True)
class ComparisonRange:
    """One configuration's aggregate for one metric, as the aggregate holds it."""

    label: str
    count: int
    minimum: float
    p5: float
    p25: float
    median: float
    p75: float
    p95: float
    maximum: float
    mean: float

    def __post_init__(self) -> None:
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count <= 0:
            raise ValueError(f"{self.label}: count must be a positive int (got {self.count!r})")
        for name in ("minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"):
            value = getattr(self, name)
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.label}: {name} must be a number (got {value!r})")
            if not math.isfinite(value):
                raise ValueError(f"{self.label}: {name} must be finite (got {value!r})")


def comparison_range_chart(
    ranges: Sequence[ComparisonRange], *, metric_label: str, title: str, disclosure_in_title: bool = True
) -> go.Figure:
    """One row per configuration: minimum to maximum, P5 to P95 and P25 to
    P75 as nested bands, with median and mean markers.

    Rows run top to bottom in the order given. Each band is one trace
    holding every configuration's segment, separated by gaps, so the legend
    names each band once.

    ``disclosure_in_title`` (Phase 24, Step 5) keeps the disclosure in the
    title's subtitle line, the default; ``False`` leaves the title as given,
    for a page that shows the disclosure as wrapping text beside the chart
    — a chart title is drawn on one line and is cut off on a narrow plot.

    Raises:
        ValueError: ``ranges`` is empty or two ranges share a label.
    """
    if not ranges:
        raise ValueError("no configuration to draw")
    labels = [r.label for r in ranges]
    if len(set(labels)) != len(labels):
        raise ValueError(f"configuration labels must be unique (got {labels})")

    def band(low: str, high: str) -> tuple[list, list]:
        x: list = []
        y: list = []
        for r in ranges:
            x += [getattr(r, low), getattr(r, high), None]
            y += [r.label, r.label, None]
        return x, y

    traces = []
    for name, low, high, width, color in (
        (FULL_RANGE_TRACE, "minimum", "maximum", 2, TEXT_MUTED),
        (OUTER_SPREAD_TRACE, "p5", "p95", 10, with_alpha(ACCENT, 0.35)),
        (INNER_SPREAD_TRACE, "p25", "p75", 20, with_alpha(ACCENT, 0.75)),
    ):
        x, y = band(low, high)
        traces.append(go.Scatter(
            x=x, y=y, mode="lines", name=name, line={"width": width, "color": color}, connectgaps=False,
            hovertemplate="%{y}<br>%{x:,.6g}<extra>" + name + "</extra>",
        ))
    traces.append(go.Scatter(
        x=[r.median for r in ranges], y=labels, mode="markers", name=MEDIAN_TRACE,
        marker={"symbol": "line-ns-open", "size": 30, "color": TEXT,
                "line": {"width": 3, "color": TEXT}},
        hovertemplate="%{y}<br>%{x:,.6g}<extra>" + MEDIAN_TRACE + "</extra>",
    ))
    traces.append(go.Scatter(
        x=[r.mean for r in ranges], y=labels, mode="markers", name=MEAN_TRACE,
        marker={"symbol": "diamond", "size": 12, "color": WARNING},
        hovertemplate="%{y}<br>%{x:,.6g}<extra>" + MEAN_TRACE + "</extra>",
    ))
    fig = go.Figure(data=traces)
    fig.update_layout(
        title=f"{title}<br><sup>{COMPARISON_DISCLOSURE}</sup>" if disclosure_in_title else title,
        xaxis_title=metric_label,
        yaxis={"categoryorder": "array", "categoryarray": labels, "autorange": "reversed",
               "title": "Configuration"},
        height=max(260, 90 * len(ranges) + 160),
        **CHART_LAYOUT,
    )
    return fig
