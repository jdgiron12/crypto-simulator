"""The Simulate workspace's layout (Phase 24, Step 4).

The run setup sits in the sidebar, grouped; the page has three workflow
tabs (single run, batch, comparison); a run shows its status, the market
overview (headline figures and price chart) and then its detail tabs. The
layout moves nothing the dashboard computes: these tests check that every
control keeps its key and default, that the overview and details together
draw exactly what the market section always drew, and that the batch and
comparison still run from the same setup.
"""

from __future__ import annotations

import json

from streamlit.testing.v1 import AppTest

from crypto_simulator.config import get_settings
from crypto_simulator.dashboard.data import (
    SimulationParams,
    configured_coin,
    payload_to_dict,
    run_simulation,
)
from crypto_simulator.dashboard.view import (
    BATCH_RUNS_KEY,
    BATCH_STATUS_KEY,
    COMPARISON_MARKET_CONDITIONS_KEY,
    COMPARISON_PRICING_MODES_KEY,
    COMPARISON_RUNS_KEY,
    COMPARISON_SCENARIOS_KEY,
    COMPARISON_SEED_KEY,
    COMPARISON_STATUS_KEY,
    EMPTY_GUIDE,
    EMPTY_MESSAGE,
    PAGE_HEADING,
    PAYLOAD_KEY,
    RESULT_TABS,
    RUN_CONTROL_KEYS,
    RUN_ICON,
    RUN_PARAMS_KEY,
    STALE_MESSAGE,
    STATUS_KEY,
    WORKFLOW_TABS,
    RunStatus,
    _control_defaults,
)

TICKS = 8
#: The controls the workflow tabs own; every other run control is the
#: shared run setup in the sidebar.
TAB_CONTROLS = {
    BATCH_RUNS_KEY,
    COMPARISON_PRICING_MODES_KEY,
    COMPARISON_SCENARIOS_KEY,
    COMPARISON_MARKET_CONDITIONS_KEY,
    COMPARISON_RUNS_KEY,
    COMPARISON_SEED_KEY,
}


def _dashboard():
    """The dashboard with its own default runners (AppTest executes this source)."""
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard()


def _market(market_only: str):
    """The market section drawn whole, or as the workspace draws it."""
    from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
    from crypto_simulator.dashboard.market_section import (
        render_market,
        render_market_details,
        render_market_overview,
    )

    payload = payload_to_dict(run_simulation(SimulationParams(ticks=8)))
    market, report = payload["report"]["market"], payload["report"]
    scope = (report["start_tick"], report["end_tick"])
    if market_only == "whole":
        render_market(market, symbol="FIC", price_series=payload["price_series"], scope=scope)
    else:
        render_market_overview(market, symbol="FIC", price_series=payload["price_series"])
        render_market_details(market, symbol="FIC", scope=scope)


def _app() -> AppTest:
    return AppTest.from_function(_dashboard, default_timeout=120).run()


def _run(at: AppTest, ticks: int = TICKS) -> AppTest:
    at.number_input(key="coin_dashboard_ticks").set_value(ticks)
    at.button(key="coin_dashboard_run").click().run()
    return at


def _sidebar_keys(at: AppTest) -> set[str]:
    return {
        widget.key
        for kind in ("number_input", "checkbox", "selectbox", "multiselect")
        for widget in getattr(at.sidebar, kind)
        if widget.key
    }


# --- before any run ------------------------------------------------------------------------------------


def test_the_workspace_names_itself_and_the_coin_it_simulates():
    at = _app()
    assert not at.exception
    assert PAGE_HEADING in [header.value for header in at.subheader]
    name, symbol = configured_coin()
    assert (name, symbol) == (get_settings().coin.name, get_settings().coin.symbol)
    assert any(f"{name} ({symbol})" in caption.value for caption in at.caption)


def test_the_page_offers_three_workflows():
    at = _app()
    assert [tab.label for tab in at.tabs] == list(WORKFLOW_TABS)


def test_the_empty_state_says_how_to_start_and_shows_no_figures():
    at = _app()
    assert EMPTY_MESSAGE in [info.value for info in at.info]
    assert EMPTY_GUIDE in [caption.value for caption in at.caption]
    assert at.metric.len == 0
    assert len(at.get("plotly_chart")) == 0
    assert STALE_MESSAGE not in [caption.value for caption in at.caption]


def test_the_run_action_leads_the_single_run_tab():
    at = _app()
    run = at.button(key="coin_dashboard_run")
    assert at.main.button[0].key == run.key
    assert run.proto.icon == RUN_ICON


def test_the_run_setup_is_in_the_sidebar_and_the_workflow_controls_in_their_tabs():
    at = _app()
    assert _sidebar_keys(at) == set(RUN_CONTROL_KEYS) - TAB_CONTROLS
    for key in TAB_CONTROLS:
        assert key not in _sidebar_keys(at)


def test_every_control_starts_at_its_default():
    at = _app()
    for key, value in _control_defaults().items():
        assert at.session_state[key] == value, key


def test_display_names_leave_the_stored_values_unchanged():
    at = _app()
    pricing = at.selectbox(key="coin_dashboard_pricing_mode")
    assert pricing.value == "random_walk"
    assert pricing.format_func("amm") == "Liquidity pool (AMM)"
    scenario = at.selectbox(key="coin_dashboard_scenario")
    assert scenario.value == "none"
    assert scenario.format_func("pump_and_dump") == "Pump & dump"


# --- a run ---------------------------------------------------------------------------------------------


def test_a_run_shows_the_overview_then_the_detail_tabs():
    at = _run(_app())
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    # AppTest lists tabs depth-first: the run's detail tabs sit inside "Single run".
    single, *others = WORKFLOW_TABS
    assert [tab.label for tab in at.tabs] == [single, *RESULT_TABS, *others]
    payload = at.session_state[PAYLOAD_KEY]
    market = payload["report"]["market"]
    shown = {metric.label: metric.value for metric in at.metric}
    assert shown["Close price"] == format(market["close_price"], ",.4f")
    assert shown["Return"] == format(market["cumulative_return"], "+.2%")
    first = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert first["data"][0]["y"] == [point["price"] for point in payload["price_series"]]


def test_the_run_on_screen_is_the_request_made_directly():
    at = _run(_app())
    expected = payload_to_dict(run_simulation(SimulationParams(ticks=TICKS)))
    assert at.session_state[PAYLOAD_KEY] == expected
    assert at.session_state[RUN_PARAMS_KEY] == SimulationParams(ticks=TICKS)


def test_overview_and_details_draw_exactly_what_the_market_section_draws():
    whole = AppTest.from_function(_market, kwargs={"market_only": "whole"}, default_timeout=60).run()
    split = AppTest.from_function(_market, kwargs={"market_only": "split"}, default_timeout=60).run()

    def metrics(at):
        return sorted((metric.label, metric.value) for metric in at.metric)

    def charts(at):
        return [json.loads(chart.proto.spec)["data"] for chart in at.get("plotly_chart")]

    assert metrics(split) == metrics(whole)
    assert [table.value.to_dict() for table in split.table] == [table.value.to_dict() for table in whole.table]
    assert charts(split) == charts(whole)
    assert sorted(m.value for m in split.markdown) == sorted(m.value for m in whole.markdown)
    assert sorted(c.value for c in split.caption) == sorted(c.value for c in whole.caption)


def test_a_changed_setup_is_flagged_without_rerunning():
    at = _run(_app())
    before = at.session_state[PAYLOAD_KEY]
    assert STALE_MESSAGE not in [caption.value for caption in at.caption]
    at.checkbox(key="coin_dashboard_psychology").check().run()
    assert STALE_MESSAGE in [caption.value for caption in at.caption]
    assert at.session_state[PAYLOAD_KEY] == before
    at.button(key="coin_dashboard_run").click().run()
    assert STALE_MESSAGE not in [caption.value for caption in at.caption]
    assert at.session_state[PAYLOAD_KEY]["simulation"]["params"]["psychology"] is True


def test_setting_the_controls_back_clears_the_flag():
    at = _run(_app())
    at.checkbox(key="coin_dashboard_whales").uncheck().run()
    assert STALE_MESSAGE in [caption.value for caption in at.caption]
    at.checkbox(key="coin_dashboard_whales").check().run()
    assert STALE_MESSAGE not in [caption.value for caption in at.caption]


def test_amm_with_whales_is_flagged_in_the_setup_before_running():
    at = _app()
    assert at.sidebar.warning.len == 0
    at.selectbox(key="coin_dashboard_pricing_mode").set_value("amm").run()
    assert at.sidebar.warning.len == 1
    at.checkbox(key="coin_dashboard_whales").uncheck().run()
    assert at.sidebar.warning.len == 0


def test_a_failed_run_leaves_no_stale_flag_and_no_results():
    at = _app()
    at.selectbox(key="coin_dashboard_pricing_mode").set_value("amm").run()
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.ERROR
    assert at.session_state[RUN_PARAMS_KEY] is None
    assert STALE_MESSAGE not in [caption.value for caption in at.caption]
    assert at.metric.len == 0


# --- the other workflows -------------------------------------------------------------------------------


def test_a_batch_still_runs_from_the_shared_setup():
    at = _app()
    at.number_input(key="coin_dashboard_ticks").set_value(5)
    at.number_input(key=BATCH_RUNS_KEY).set_value(2).run()
    at.button(key="coin_dashboard_run_batch").click().run()
    assert not at.exception
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[STATUS_KEY] is RunStatus.EMPTY


def test_a_comparison_still_runs_from_the_shared_setup():
    at = _app()
    at.number_input(key="coin_dashboard_ticks").set_value(5)
    at.number_input(key=COMPARISON_RUNS_KEY).set_value(1).run()
    at.button(key="coin_dashboard_run_comparison").click().run()
    assert not at.exception
    assert at.session_state[COMPARISON_STATUS_KEY] is RunStatus.SUCCESS
