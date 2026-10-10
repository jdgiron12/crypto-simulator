"""The shared design tokens and chart template (Phase 24, Step 2).

The template styles figures and never changes their data: the existing
chart tests keep asserting every trace value, and these tests check that
every builder carries the one template, that the tokens are readable, and
that the Streamlit theme file repeats the same colors.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import tomllib
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import pytest

from crypto_simulator.visualization import batch_charts, charts, comparison_charts, style, tick_charts
from crypto_simulator.visualization.style import (
    ACCENT,
    BACKGROUND,
    BORDER,
    CHART_LAYOUT,
    CHART_TEMPLATE,
    COLORWAY,
    DOWN,
    FONT_FAMILY,
    GRID,
    SURFACE,
    SURFACE_RAISED,
    TEXT,
    TEXT_MUTED,
    TEXT_SECONDARY,
    TOP_LEGEND,
    UP,
    WARNING,
    with_alpha,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_TOML = REPO_ROOT / ".streamlit" / "config.toml"

#: The theme options Streamlit 1.38 (the declared minimum) defines; any
#: other key would log "not a valid config option" on that version.
THEME_OPTIONS_SINCE_1_38 = {
    "base", "primaryColor", "backgroundColor", "secondaryBackgroundColor", "textColor", "font",
}

TOKENS = {
    "BACKGROUND": BACKGROUND, "SURFACE": SURFACE, "SURFACE_RAISED": SURFACE_RAISED,
    "BORDER": BORDER, "GRID": GRID, "TEXT": TEXT, "TEXT_SECONDARY": TEXT_SECONDARY,
    "TEXT_MUTED": TEXT_MUTED, "ACCENT": ACCENT, "UP": UP, "DOWN": DOWN, "WARNING": WARNING,
}


def _luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# --- tokens --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(TOKENS))
def test_every_token_is_a_hex_color(name):
    value = TOKENS[name]
    assert len(value) == 7 and value.startswith("#")
    int(value[1:], 16)


@pytest.mark.parametrize("text", [TEXT, TEXT_SECONDARY, TEXT_MUTED])
@pytest.mark.parametrize("surface", [BACKGROUND, SURFACE])
def test_text_tokens_meet_wcag_aa_on_the_page_and_panels(text, surface):
    assert _contrast(text, surface) >= 4.5


@pytest.mark.parametrize("color", [*COLORWAY, UP, DOWN])
def test_data_colors_are_distinguishable_from_the_background(color):
    """WCAG's 3:1 for graphical objects, on the page and on panels."""
    assert _contrast(color, BACKGROUND) >= 3.0
    assert _contrast(color, SURFACE) >= 3.0


def test_colorway_never_uses_the_price_direction_colors():
    assert UP not in COLORWAY and DOWN not in COLORWAY
    assert len(set(COLORWAY)) == len(COLORWAY)
    assert COLORWAY[0] == ACCENT


def test_with_alpha_converts_a_token():
    assert with_alpha("#5B8DEF", 0.35) == "rgba(91, 141, 239, 0.35)"
    assert with_alpha(BACKGROUND, 1.0) == "rgba(11, 15, 23, 1.0)"


@pytest.mark.parametrize("color, alpha", [("5B8DEF", 0.5), ("#5B8", 0.5), (None, 0.5), (ACCENT, 1.5), (ACCENT, -0.1)])
def test_with_alpha_rejects_bad_input(color, alpha):
    with pytest.raises(ValueError):
        with_alpha(color, alpha)


# --- template ------------------------------------------------------------------------------------------


def test_template_is_transparent_and_uses_the_tokens():
    layout = CHART_TEMPLATE.layout
    assert layout.paper_bgcolor == "rgba(0, 0, 0, 0)"
    assert layout.plot_bgcolor == "rgba(0, 0, 0, 0)"
    assert layout.font.family == FONT_FAMILY
    assert layout.font.color == TEXT_SECONDARY
    assert layout.title.font.color == TEXT
    assert tuple(layout.colorway) == COLORWAY
    for axis in (layout.xaxis, layout.yaxis):
        assert axis.gridcolor == GRID
        assert axis.linecolor == BORDER
        assert axis.tickfont.color == TEXT_MUTED
    assert layout.hoverlabel.bgcolor == SURFACE_RAISED


def test_template_colors_candles_by_price_direction():
    candle = CHART_TEMPLATE.data.candlestick[0]
    assert candle.increasing.line.color == UP and candle.increasing.fillcolor == UP
    assert candle.decreasing.line.color == DOWN and candle.decreasing.fillcolor == DOWN


def test_importing_the_style_changes_no_global_plotly_state():
    before_names, before_default = set(pio.templates), pio.templates.default
    importlib.reload(style)
    assert set(pio.templates) == before_names
    assert pio.templates.default == before_default


# --- every builder carries the template ----------------------------------------------------------------

BANDS = {name: [1.0, 2.0] for name in batch_charts.PATH_COLUMNS} | {"runs": 2}
RANGE = dict(minimum=1.0, p5=1.1, p25=1.2, median=1.5, p75=1.8, p95=1.9, maximum=2.0, mean=1.5)

BUILDERS = {
    "candlestick_chart": lambda: charts.candlestick_chart(pd.DataFrame(
        {"timestamp": [1, 2], "open": [1, 2], "high": [2, 3], "low": [0.5, 1], "close": [2, 1]})),
    "equity_curve_chart": lambda: charts.equity_curve_chart(pd.DataFrame({"timestamp": [1, 2], "equity": [1, 2]})),
    "price_path_chart": lambda: charts.price_path_chart(
        pd.DataFrame({"tick": [1, 2], "price": [1.0, 2.0]}), markers=[("High", 2, 2.0)]),
    "component_lines_chart": lambda: charts.component_lines_chart(
        pd.DataFrame({"tick": [1, 2], "a": [0.1, 0.2]}), series=["a"]),
    "allocation_chart": lambda: charts.allocation_chart({"A": 1.0, "B": 2.0}),
    "synthetic_ohlc_chart": lambda: tick_charts.synthetic_ohlc_chart(
        tick_charts.synthetic_ohlc([1, 2, 3], [1.0, 2.0, 1.5], 2), title="OHLC"),
    "volume_composition_chart": lambda: tick_charts.volume_composition_chart(
        [1, 2], [("Organic", [1.0, 2.0]), ("Whale", [0.5, 0.0])], title="Volume", unit="FIC"),
    "aggregate_range_chart": lambda: batch_charts.aggregate_range_chart(
        label="Close price", count=3, title="Range", **RANGE),
    "run_histogram_chart": lambda: batch_charts.run_histogram_chart(
        [1.0, 2.0, 2.5], label="Close price", mean=1.8, median=2.0, title="Histogram"),
    "price_path_band_chart": lambda: batch_charts.price_path_band_chart(
        [1, 2], BANDS, title="Bands", show_extremes=True),
    "comparison_range_chart": lambda: comparison_charts.comparison_range_chart(
        [comparison_charts.ComparisonRange(label="RW", count=3, **RANGE),
         comparison_charts.ComparisonRange(label="AMM", count=3, **RANGE)],
        metric_label="Close price", title="Compare"),
}


def test_every_chart_builder_is_covered():
    """A new ``*_chart`` builder must join ``BUILDERS`` (and so carry the template)."""
    found = {
        name
        for module in (charts, tick_charts, batch_charts, comparison_charts)
        for name, member in inspect.getmembers(module, inspect.isfunction)
        if name.endswith("_chart") and member.__module__ == module.__name__
    }
    assert found == set(BUILDERS)


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_builder_applies_the_shared_template(name):
    figure = BUILDERS[name]()
    assert isinstance(figure, go.Figure)
    assert figure.layout.template == CHART_TEMPLATE


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_builder_sets_font_and_backgrounds_on_the_figure_itself(name):
    """Streamlit's front end fills these from the page theme when the
    figure's own layout leaves them unset, whatever its template says."""
    layout = BUILDERS[name]().layout
    assert layout.paper_bgcolor == "rgba(0, 0, 0, 0)"
    assert layout.plot_bgcolor == "rgba(0, 0, 0, 0)"
    assert layout.font.family == FONT_FAMILY
    assert layout.font.color == TEXT_SECONDARY


def test_chart_layout_repeats_the_template_values():
    assert CHART_LAYOUT["template"] is CHART_TEMPLATE
    assert CHART_LAYOUT["paper_bgcolor"] == CHART_TEMPLATE.layout.paper_bgcolor
    assert CHART_LAYOUT["plot_bgcolor"] == CHART_TEMPLATE.layout.plot_bgcolor
    assert CHART_LAYOUT["font"]["family"] == CHART_TEMPLATE.layout.font.family
    assert CHART_LAYOUT["font"]["color"] == CHART_TEMPLATE.layout.font.color


def test_band_and_range_charts_draw_their_bands_in_the_accent():
    bands = batch_charts.price_path_band_chart([1, 2], BANDS, title="Bands", show_extremes=True)
    fills = {trace.name: trace.fillcolor for trace in bands.data if trace.fill == "tonexty"}
    assert fills == {batch_charts.OUTER_SPREAD_TRACE: with_alpha(ACCENT, 0.15),
                     batch_charts.INNER_SPREAD_TRACE: with_alpha(ACCENT, 0.35)}
    median = next(trace for trace in bands.data if trace.name == batch_charts.MEDIAN_TRACE)
    assert median.line.color == ACCENT
    for figure in (BUILDERS["aggregate_range_chart"](), BUILDERS["comparison_range_chart"]()):
        colors = {trace.name: (trace.line.color, trace.marker.color) for trace in figure.data}
        assert colors[batch_charts.OUTER_SPREAD_TRACE][0] == with_alpha(ACCENT, 0.35)
        assert colors[batch_charts.INNER_SPREAD_TRACE][0] == with_alpha(ACCENT, 0.75)
        assert colors[batch_charts.MEAN_TRACE][1] == WARNING


# --- the dashboard renders the figures as styled -------------------------------------------------------


def _plotly_chart_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text())
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "plotly_chart"]


def test_every_dashboard_chart_turns_off_streamlits_own_chart_theme():
    """Streamlit's default ``theme="streamlit"`` repaints a figure; ``None``
    renders the shared template as built."""
    package = REPO_ROOT / "crypto_simulator"
    paths = [*sorted((package / "dashboard").glob("*.py")), package / "app.py"]
    calls = {path.name: _plotly_chart_calls(path) for path in paths}
    assert sum(len(found) for found in calls.values()) >= 15
    for name, found in calls.items():
        for call in found:
            theme = [keyword.value for keyword in call.keywords if keyword.arg == "theme"]
            assert len(theme) == 1 and isinstance(theme[0], ast.Constant) and theme[0].value is None, (
                f"{name}:{call.lineno}"
            )


# --- the Streamlit theme file --------------------------------------------------------------------------


def test_streamlit_theme_repeats_the_tokens():
    config = tomllib.loads(CONFIG_TOML.read_text())
    theme = config["theme"]
    assert theme == {
        "base": "dark",
        "primaryColor": ACCENT,
        "backgroundColor": BACKGROUND,
        "secondaryBackgroundColor": SURFACE,
        "textColor": TEXT,
    }


def test_streamlit_theme_uses_only_options_the_minimum_version_knows():
    config = tomllib.loads(CONFIG_TOML.read_text())
    assert set(config["theme"]) <= THEME_OPTIONS_SINCE_1_38
    assert set(config) == {"theme", "client"}
    assert config["client"] == {"toolbarMode": "minimal"}


#: The builders whose one-line titles leave room for a legend above the plot.
TOP_LEGEND_BUILDERS = {"price_path_chart", "component_lines_chart", "volume_composition_chart"}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_only_one_line_titles_get_the_top_legend(name):
    """Phase 24, Step 4: a legend above the plot leaves a narrow screen its
    width, but would overlap a title's subtitle line."""
    layout = BUILDERS[name]().layout
    top = layout.legend.orientation == "h" and layout.legend.y == TOP_LEGEND["y"]
    assert top == (name in TOP_LEGEND_BUILDERS)
    if top:
        assert "<sup>" not in (layout.title.text or "")
