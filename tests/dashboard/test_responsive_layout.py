"""Responsive detail figures and the compact comparison chart (Phase 24, Step 6).

Presentation only. The detail tabs' figures sit in rows that wrap
(``render_metric_row``) rather than in fixed four-column grids that cut a
long label short at medium widths; every figure keeps its label, value,
formatting and order. The scenario comparison draws its chart in the
compact layout, which keeps every configuration and series and changes no
trace. The dashboard reads and writes no database, so nothing here does.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.dashboard.data import (
    SimulationParams,
    comparison_configurations,
    comparison_to_dict,
    run_dashboard_comparison,
)
from crypto_simulator.dashboard.view import PAYLOAD_KEY, STATUS_KEY, RunStatus
from crypto_simulator.visualization.comparison_charts import (
    BOTTOM_LEGEND,
    FULL_RANGE_TRACE,
    INNER_SPREAD_TRACE,
    MEAN_TRACE,
    MEDIAN_TRACE,
    OUTER_SPREAD_TRACE,
    stacked_label,
)

TICKS = 60

#: Every figure each detail tab draws, in order, as Step 5 drew them.
TAB_METRICS = {
    "Market details": [
        "Open price", "High", "Low", "Mean price",
        "Volatility (per tick)", "Realized volatility", "Max drawdown", "Drawdown at close",
        "Market cap (open)", "Market cap (close)", "Turnover", "Participant turnover",
    ],
    "Traders": [
        "Traders active", "Participation", "Trader fills", "Trader volume",
        "Trader notional", "VWAP (all fills)", "Net coin flow", "Net cash flow",
        "Combined P&L", "Combined return", "Start equity", "End equity",
    ],
    "Whales": ["Whales listed", "Whale volume", "Share of market volume", "Share of participant volume"],
    "Events": ["Events observed", "Categories", "Ticks analysed"],
    "Psychology": [],
    "Manipulation": [
        "Manipulation volume", "Manipulation share of total volume",
        "Manipulation share of participant volume", "Manipulation active ticks",
    ],
    "Regimes": ["Regime windows", "Complete windows", "Incomplete windows", "Window size (ticks)"],
    "Tick data": [],
}


def _dashboard():
    """The dashboard with its default runners (AppTest executes this source)."""
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard()


def _amm_details():
    """The market details of one AMM run, whose pool row is drawn."""
    from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
    from crypto_simulator.dashboard.market_section import render_market_details

    payload = payload_to_dict(run_simulation(SimulationParams(ticks=12, pricing_mode="amm", include_whales=False)))
    render_market_details(payload["report"]["market"], symbol="FIC")


@pytest.fixture(scope="module")
def full_run() -> AppTest:
    """One run with every optional recorder on and a manipulation scenario,
    so every detail tab draws its figures."""
    at = AppTest.from_function(_dashboard, default_timeout=300).run()
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)
    for key in ("coin_dashboard_events", "coin_dashboard_psychology", "coin_dashboard_whale_observation"):
        at.checkbox(key=key).check()
    at.selectbox(key="coin_dashboard_scenario").set_value("pump_and_dump")
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    return at


def _tab(at: AppTest, label: str):
    return next(tab for tab in at.tabs if tab.label == label)


# --- detail-tab figures --------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(TAB_METRICS))
def test_every_detail_tab_keeps_its_figures_in_order(full_run, name):
    assert [metric.label for metric in _tab(full_run, name).metric] == TAB_METRICS[name]


@pytest.mark.parametrize("name", list(TAB_METRICS))
def test_no_detail_figure_sits_in_a_fixed_column(full_run, name):
    # A fixed column gives every figure the same share of the width and cuts
    # a long label short; the rows wrap instead.
    assert len(_tab(full_run, name).columns) == 0


def test_long_labels_are_shown_whole(full_run):
    labels = {metric.label for tab in TAB_METRICS for metric in _tab(full_run, tab).metric}
    for label in ("Share of participant volume", "Manipulation share of participant volume",
                  "Manipulation share of total volume", "Participant turnover", "Window size (ticks)"):
        assert label in labels
    assert not any(label.endswith(("…", "...")) for label in labels)


def test_the_figures_keep_their_values_and_formatting(full_run):
    report = full_run.session_state[PAYLOAD_KEY]["report"]
    whales, manipulation = report["whale_activity"], report["manipulation"]
    traders, market = report["traders"], report["market"]
    shown = {tab: {m.label: m.value for m in _tab(full_run, tab).metric} for tab in TAB_METRICS}
    assert shown["Whales"] == {
        "Whales listed": format(len(whales["whales"]), ",d"),
        "Whale volume": format(whales["whale_volume"], ",.0f"),
        "Share of market volume": format(whales["whale_volume_share_of_total"], ".2%"),
        "Share of participant volume": format(whales["whale_volume_share_of_participants"], ".2%"),
    }
    assert shown["Manipulation"] == {
        "Manipulation volume": format(manipulation["manipulation_volume"], ",.0f"),
        "Manipulation share of total volume": format(manipulation["manipulation_share_of_total"], ".2%"),
        "Manipulation share of participant volume":
            format(manipulation["manipulation_share_of_participants"], ".2%"),
        "Manipulation active ticks": format(manipulation["active_ticks"], ",d"),
    }
    assert shown["Traders"]["Net cash flow"] == format(traders["net_cash_flow"], "+,.2f")
    assert shown["Traders"]["Combined return"] == format(traders["equity_return"], "+.2%")
    assert shown["Market details"]["Open price"] == format(market["open_price"], ",.4f")
    assert shown["Market details"]["Max drawdown"] == format(market["max_drawdown"], ".2%")
    # No figure gained a delta.
    assert not any(m.delta for tab in TAB_METRICS for m in _tab(full_run, tab).metric)


def test_the_headline_is_unchanged(full_run):
    market = full_run.session_state[PAYLOAD_KEY]["report"]["market"]
    headline = _tab(full_run, "Single run").metric[:4]
    assert [(m.label, m.value) for m in headline] == [
        ("Close price", format(market["close_price"], ",.4f")),
        ("Return", format(market["cumulative_return"], "+.2%")),
        ("Total volume", format(market["volume_breakdown"]["total_volume"], ",.0f")),
        ("Ticks analysed", str(market["ticks"])),
    ]


def test_the_amm_pool_row_wraps_and_keeps_its_figures():
    at = AppTest.from_function(_amm_details, default_timeout=120).run()
    labels = [metric.label for metric in at.metric]
    assert labels[-4:] == ["Swaps", "Fees (cash)", "Fees (coins)", "Largest price impact"]
    assert len(at.columns) == 0


# --- the comparison chart ------------------------------------------------------------------------------


#: Long labels on every dimension: both pricing modes, a manipulation
#: preset and a market condition.
CONFIGURATIONS = comparison_configurations(["random_walk", "amm"], [None, "pump_and_dump"], ["bull"])


def _comparison_section(comparison):
    """The comparison results on their own (AppTest executes this source)."""
    from crypto_simulator.dashboard.comparison_section import render_comparison

    render_comparison(comparison)


@pytest.fixture(scope="module")
def comparison_chart() -> dict:
    comparison = comparison_to_dict(
        run_dashboard_comparison(SimulationParams(ticks=12, include_whales=False), CONFIGURATIONS, 3, base_seed=4242)
    )
    at = AppTest.from_function(_comparison_section, kwargs={"comparison": comparison}, default_timeout=60).run()
    charts = [json.loads(chart.proto.spec) for chart in at.get("plotly_chart")]
    assert len(charts) == 1
    return charts[0]


def test_the_comparison_chart_keeps_every_configuration_and_series(comparison_chart):
    labels = [c.label for c in CONFIGURATIONS]
    yaxis = comparison_chart["layout"]["yaxis"]
    assert yaxis["categoryarray"] == labels
    assert [trace["name"] for trace in comparison_chart["data"]] == [
        FULL_RANGE_TRACE, OUTER_SPREAD_TRACE, INNER_SPREAD_TRACE, MEDIAN_TRACE, MEAN_TRACE,
    ]
    assert all(trace.get("showlegend", True) for trace in comparison_chart["data"])
    for trace in comparison_chart["data"]:
        assert [y for y in trace["y"] if y is not None] == [
            label for label in labels for _ in range(2 if trace["mode"] == "lines" else 1)
        ], trace["name"]


def test_the_comparison_chart_is_drawn_compact(comparison_chart):
    labels = [c.label for c in CONFIGURATIONS]
    yaxis, legend = comparison_chart["layout"]["yaxis"], comparison_chart["layout"]["legend"]
    # Each tick names its configuration, one compared dimension per line.
    assert yaxis["tickvals"] == labels
    assert yaxis["ticktext"] == [stacked_label(label) for label in labels]
    assert yaxis["ticktext"][-1] == "AMM<br>Pump & dump<br>Bull"
    assert {key: legend[key] for key in BOTTOM_LEGEND} == BOTTOM_LEGEND
