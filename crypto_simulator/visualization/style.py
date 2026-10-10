"""The dashboard's design tokens and shared Plotly chart template (Phase 24).

Styling only: nothing here reads, scales or reorders data. Every chart
builder in ``visualization/`` applies ``CHART_LAYOUT`` (``CHART_TEMPLATE``
plus the figure-level settings below) to its figure, so all charts share
one look; the trace values a builder draws are exactly
the values it was given.

The colors are the single source of the dark theme. The Streamlit theme
in ``.streamlit/config.toml`` repeats the page colors (a TOML file cannot
import them), and ``tests/visualization/test_style.py`` keeps the two in
step.

Plotly only, like the rest of this package: no Streamlit, no simulation,
no data access. The template is a plain object, not registered with
``plotly.io``, so importing this module changes no global Plotly state.
Streamlit's own chart theme would repaint these figures, so the dashboard
renders them with ``st.plotly_chart(..., theme=None)``. Even then, the
Streamlit front end fills in the page font and background colors for any
of ``font``, ``paper_bgcolor`` and ``plot_bgcolor`` a figure's own layout
leaves unset — a template's values do not count — so builders apply
``CHART_LAYOUT``, which sets those explicitly beside the template.
"""

from __future__ import annotations

import plotly.graph_objects as go

__all__ = [
    "ACCENT",
    "BACKGROUND",
    "BORDER",
    "CHART_LAYOUT",
    "CHART_TEMPLATE",
    "COLORWAY",
    "DOWN",
    "FONT_FAMILY",
    "GRID",
    "SURFACE",
    "SURFACE_RAISED",
    "TEXT",
    "TOP_LEGEND",
    "TEXT_MUTED",
    "TEXT_SECONDARY",
    "UP",
    "WARNING",
    "with_alpha",
]

# --- surfaces ------------------------------------------------------------------------------------------
#: The page.
BACKGROUND = "#0B0F17"
#: Panels, inputs, tables (Streamlit's ``secondaryBackgroundColor``).
SURFACE = "#121826"
#: Raised elements: hover labels, menus.
SURFACE_RAISED = "#182030"
BORDER = "#222B3A"
#: Chart gridlines, quieter than any border.
GRID = "#1A2230"

# --- text (each meets WCAG AA, 4.5:1, on BACKGROUND and SURFACE) ------------------------------------
TEXT = "#E6E9EF"
TEXT_SECONDARY = "#9AA4B2"
TEXT_MUTED = "#7A8494"

# --- meaning ---------------------------------------------------------------------------------------------
#: Interactive elements and the first data series.
ACCENT = "#5B8DEF"
#: Price direction only (candles); never a categorical series color.
UP = "#2EBD85"
DOWN = "#E5484D"
WARNING = "#E2A336"

#: Categorical series, in trace order. Up and down are deliberately
#: absent so a series never reads as a price direction. The first four
#: hues are far apart because the four-series charts (psychology
#: components, event state) need them told apart at a glance; cyan, too
#: close to the accent, comes last. The fifth entry is a neutral slate,
#: which the volume chart's fifth component (synthetic background volume)
#: receives.
COLORWAY: tuple[str, ...] = (
    ACCENT,
    WARNING,
    "#9B7BEA",
    "#D9668A",
    "#8A94A6",
    "#4FB3D9",
)

#: Streamlit's bundled sans-serif face (named "Source Sans" in current
#: releases, "Source Sans Pro" in older ones), with system fallbacks.
FONT_FAMILY = '"Source Sans", "Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'


def with_alpha(color: str, alpha: float) -> str:
    """A ``#RRGGBB`` token as an ``rgba(...)`` string at ``alpha`` opacity."""
    if not (isinstance(color, str) and len(color) == 7 and color.startswith("#")):
        raise ValueError(f"color must be '#RRGGBB' (got {color!r})")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha must be between 0 and 1 (got {alpha!r})")
    red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _axis() -> dict:
    return {
        "gridcolor": GRID,
        "linecolor": BORDER,
        "zerolinecolor": BORDER,
        "tickcolor": BORDER,
        "showline": True,
        "automargin": True,
        "tickfont": {"color": TEXT_MUTED, "size": 11},
        "title": {"font": {"color": TEXT_SECONDARY, "size": 12}, "standoff": 8},
    }


#: The shared template. Transparent backgrounds let the page color show
#: through; data colors come from ``COLORWAY`` unless a builder names a
#: token explicitly.
CHART_TEMPLATE = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor="rgba(0, 0, 0, 0)",
        plot_bgcolor="rgba(0, 0, 0, 0)",
        font={"family": FONT_FAMILY, "color": TEXT_SECONDARY, "size": 13},
        title={"font": {"color": TEXT, "size": 15}, "x": 0, "xanchor": "left", "xref": "container",
               "pad": {"l": 12}},
        colorway=list(COLORWAY),
        xaxis=_axis(),
        yaxis=_axis(),
        legend={"bgcolor": "rgba(0, 0, 0, 0)", "font": {"color": TEXT_SECONDARY, "size": 12}},
        hoverlabel={"bgcolor": SURFACE_RAISED, "bordercolor": BORDER,
                    "font": {"family": FONT_FAMILY, "color": TEXT, "size": 12}},
        modebar={"bgcolor": "rgba(0, 0, 0, 0)", "color": TEXT_MUTED, "activecolor": TEXT},
        margin={"l": 56, "r": 24, "t": 72, "b": 48},
    ),
    data=go.layout.template.Data(
        candlestick=[go.Candlestick(
            increasing={"line": {"color": UP, "width": 1}, "fillcolor": UP},
            decreasing={"line": {"color": DOWN, "width": 1}, "fillcolor": DOWN},
        )],
        scatter=[go.Scatter(line={"width": 2})],
        bar=[go.Bar(marker={"line": {"width": 0}})],
        histogram=[go.Histogram(marker={"color": ACCENT, "line": {"width": 0}}, opacity=0.85)],
        pie=[go.Pie(marker={"line": {"color": BACKGROUND, "width": 1}})],
    ),
)

#: A horizontal legend along the top edge of the plot, for charts with a
#: one-line title (Phase 24, Step 4): beside the plot, a legend takes a
#: large share of a narrow screen's width. Charts whose title carries a
#: subtitle line keep the template's legend, which would otherwise overlap it.
TOP_LEGEND: dict = {"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1}

#: What every builder passes to ``update_layout``: the template, plus the
#: font and transparent backgrounds set on the figure itself so that
#: Streamlit's front end does not replace them with its own defaults.
CHART_LAYOUT: dict = {
    "template": CHART_TEMPLATE,
    "paper_bgcolor": CHART_TEMPLATE.layout.paper_bgcolor,
    "plot_bgcolor": CHART_TEMPLATE.layout.plot_bgcolor,
    "font": {"family": FONT_FAMILY, "color": TEXT_SECONDARY, "size": 13},
}
