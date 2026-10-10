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
    "BOTTOM_LEGEND",
    "COMPARISON_DISCLOSURE",
    "FULL_RANGE_TRACE",
    "INNER_SPREAD_TRACE",
    "LABEL_SEPARATOR",
    "LEGEND_ALLOWANCE",
    "MEAN_TRACE",
    "MEDIAN_TRACE",
    "OUTER_SPREAD_TRACE",
    "ComparisonRange",
    "comparison_range_chart",
    "stacked_label",
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

#: How a configuration label separates its dimensions
#: (``ComparisonConfiguration.label``: ``RW | Pump & dump | Bull``).
LABEL_SEPARATOR = " | "

#: Height added for ``BOTTOM_LEGEND`` — its five entries, one per row on a
#: phone — so the legend does not take its room from the plot.
LEGEND_ALLOWANCE = 100

#: A horizontal legend along the bottom edge of the figure, anchored left.
#: On a wide page it is one row; on a phone it wraps to one entry per row
#: (Plotly wraps a horizontal legend within the plot's width), and at the
#: bottom it cannot run into the title or the toolbar, as a top legend does.
BOTTOM_LEGEND: dict = {"orientation": "h", "xref": "container", "x": 0, "xanchor": "left",
                       "yref": "container", "y": 0, "yanchor": "bottom"}


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
    ranges: Sequence[ComparisonRange],
    *,
    metric_label: str,
    title: str,
    disclosure_in_title: bool = True,
    compact: bool = False,
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

    ``compact`` (Phase 24, Step 6) lays the figure out for a page as narrow
    as a phone; the default, ``False``, leaves it as before. The legend runs
    along the bottom edge, anchored left so its first entry is never pushed
    off the figure, with height added for it so the plot keeps its own; and
    each configuration's axis label puts one compared dimension per line,
    so the labels no longer take most of a narrow plot's width. The labels
    themselves — the trace data, the hover text and the category order —
    are unchanged; only the drawn tick text breaks.

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
    yaxis = {"categoryorder": "array", "categoryarray": labels, "autorange": "reversed",
             "title": "Configuration"}
    height = max(260, 90 * len(ranges) + 160)
    legend: dict = {}
    if compact:
        yaxis.update(tickmode="array", tickvals=labels, ticktext=[stacked_label(label) for label in labels])
        legend["legend"] = BOTTOM_LEGEND
        height += LEGEND_ALLOWANCE
    fig = go.Figure(data=traces)
    fig.update_layout(
        title=f"{title}<br><sup>{COMPARISON_DISCLOSURE}</sup>" if disclosure_in_title else title,
        xaxis_title=metric_label,
        yaxis=yaxis,
        height=height,
        **legend,
        **CHART_LAYOUT,
    )
    return fig


def stacked_label(label: str) -> str:
    """A configuration label drawn one compared dimension per line:
    ``RW | Pump & dump | Bull`` becomes ``RW<br>Pump & dump<br>Bull``.
    Every word of the label is kept; only the separators become breaks."""
    return "<br>".join(part.strip() for part in label.split(LABEL_SEPARATOR))
