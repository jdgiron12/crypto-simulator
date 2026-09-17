"""The dashboard's Streamlit view (Phase 10, Step 1).

Driven through ``streamlit.testing.v1.AppTest``, the framework the app
already uses, so these are the real widgets and the real render path.

The states are the point: nothing before a run, a visible message during
one, real report values after a successful one, a clear error after a
failed one (with the previous run's figures gone). Every figure the view
shows must be one the payload holds — the checks compare what is
displayed against an independently run simulation rather than against a
literal written into the test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.config import clear_settings_cache
from crypto_simulator.dashboard import view as view_module
from crypto_simulator.dashboard.data import SimulationParams, run_simulation
from crypto_simulator.dashboard.view import (
    EMPTY_MESSAGE,
    ERROR_KEY,
    PAYLOAD_KEY,
    RUNNING_MESSAGE,
    STATUS_KEY,
    RunStatus,
)

APP = Path(__file__).resolve().parents[2] / "crypto_simulator" / "app.py"


def _dashboard(runner=None):
    """The dashboard on its own, as AppTest runs it (the source of this
    function is executed as the script, so it imports what it needs)."""
    from crypto_simulator.dashboard.data import run_simulation
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard(runner=runner or run_simulation)


def _app(runner=None, timeout: float = 60) -> AppTest:
    at = AppTest.from_function(_dashboard, kwargs={"runner": runner}, default_timeout=timeout)
    return at.run()


def _values(elements) -> list[str]:
    return [element.value for element in elements]


def _run_button(at: AppTest):
    return at.button(key="coin_dashboard_run")


# --- empty state -----------------------------------------------------------------------------------------


def test_dashboard_renders_before_anything_has_run():
    at = _app()
    assert not at.exception
    assert EMPTY_MESSAGE in _values(at.info)
    assert at.session_state[STATUS_KEY] is RunStatus.EMPTY


def test_empty_state_shows_no_figures():
    at = _app()
    assert at.metric.len == 0
    assert at.session_state[PAYLOAD_KEY] is None


def test_controls_are_available_before_a_run():
    at = _app()
    assert at.number_input(key="coin_dashboard_ticks").value == 20
    assert at.selectbox(key="coin_dashboard_pricing_mode").value == "random_walk"
    assert _run_button(at) is not None


# --- loading state ---------------------------------------------------------------------------------------


def test_running_message_is_on_screen_while_the_simulation_runs():
    """The runner stops the script mid-run, freezing what the browser has
    at that moment: the loading message, and no results."""

    def stopping_runner(params):
        import streamlit as st

        st.stop()

    at = _app(runner=stopping_runner)
    _run_button(at).click().run()
    assert RUNNING_MESSAGE in _values(at.info)
    assert at.metric.len == 0
    assert at.session_state[STATUS_KEY] is RunStatus.RUNNING


def test_requesting_a_run_clears_the_previous_result_first():
    """While the second run is in flight, the first run's figures are
    already gone — the dashboard never shows one run's numbers under
    another run's request."""
    runs = {"count": 0}

    def runner_then_stop(params):
        import streamlit as st

        from crypto_simulator.dashboard.data import run_simulation

        runs["count"] += 1
        if runs["count"] > 1:
            st.stop()
        return run_simulation(params)

    at = _app(runner=runner_then_stop)
    at.number_input(key="coin_dashboard_ticks").set_value(5)
    _run_button(at).click().run()
    assert at.metric.len > 0

    _run_button(at).click().run()
    assert RUNNING_MESSAGE in _values(at.info)
    assert at.metric.len == 0
    assert at.session_state[PAYLOAD_KEY] is None


def test_the_loading_message_is_not_left_on_screen_after_a_run():
    at = _app()
    _run_button(at).click().run()
    assert RUNNING_MESSAGE not in _values(at.info)


# --- success state ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def default_run():
    """The run the dashboard's default controls describe."""
    return run_simulation(SimulationParams())


def test_a_successful_run_reports_completion(default_run):
    at = _app()
    _run_button(at).click().run()
    assert not at.exception
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    assert at.error.len == 0
    assert f"{default_run.simulation.completed_ticks} of" in at.success[0].value


def test_displayed_market_values_are_the_report_values(default_run):
    at = _app()
    _run_button(at).click().run()
    market = default_run.report.market
    shown = {metric.label: metric.value for metric in at.metric}
    assert shown["Close price"] == format(market.close_price, ",.4f")
    assert shown["Return"] == format(market.cumulative_return, "+.2%")
    assert shown["Total volume"] == format(market.volume_breakdown.total_volume, ",.0f")
    assert shown["Ticks analysed"] == str(market.ticks)


def test_displayed_values_are_not_placeholders(default_run):
    at = _app()
    _run_button(at).click().run()
    shown = {metric.label: metric.value for metric in at.metric}
    assert shown["Close price"] not in {"0.0000", "n/a"}
    assert float(shown["Ticks analysed"]) == default_run.report.ticks > 0


def test_the_tick_range_and_run_identity_come_from_the_payload(default_run):
    at = _app()
    _run_button(at).click().run()
    captions = " ".join(_values(at.caption))
    market = default_run.report.market
    assert f"tick range {market.first_tick}-{market.last_tick}" in captions
    assert default_run.simulation.simulation_id in captions


def test_the_chart_is_drawn_from_the_recorded_price_path(default_run):
    at = _app()
    _run_button(at).click().run()
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert spec["data"][0]["x"] == [point.tick for point in default_run.price_series]
    assert spec["data"][0]["y"] == [point.price for point in default_run.price_series]


def test_later_sections_are_named_but_empty():
    at = _app()
    _run_button(at).click().run()
    captions = " ".join(_values(at.caption))
    for label, key in view_module.PLACEHOLDER_SECTIONS:
        assert f"{label} — report.{key}" in captions


def test_controls_are_passed_through_to_the_run():
    at = _app()
    at.number_input(key="coin_dashboard_ticks").set_value(5)
    at.selectbox(key="coin_dashboard_pricing_mode").set_value("amm")
    at.checkbox(key="coin_dashboard_whales").set_value(False)
    _run_button(at).click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    simulation = at.session_state[PAYLOAD_KEY]["simulation"]
    assert simulation["pricing_mode"] == "amm"
    assert simulation["completed_ticks"] == 5
    assert simulation["params"]["include_whales"] is False


# --- error state -----------------------------------------------------------------------------------------


def test_a_failed_run_shows_the_error_and_no_results():
    def failing_runner(params):
        raise ValueError("pool is empty")

    at = _app(runner=failing_runner)
    _run_button(at).click().run()
    assert not at.exception
    assert at.session_state[STATUS_KEY] is RunStatus.ERROR
    assert "ValueError: pool is empty" in at.error[0].value
    assert at.metric.len == 0
    assert at.session_state[PAYLOAD_KEY] is None


def test_an_unsupported_combination_surfaces_as_the_error_state():
    """A real rejection from the simulator, not a stubbed one: AMM mode
    does not support whales."""
    at = _app()
    at.number_input(key="coin_dashboard_ticks").set_value(3)
    at.selectbox(key="coin_dashboard_pricing_mode").set_value("amm")
    _run_button(at).click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.ERROR
    assert "Whales are not supported" in at.error[0].value
    assert at.metric.len == 0


def test_a_failed_run_does_not_leave_the_previous_run_on_screen():
    failure = {"on": False}

    def sometimes_failing_runner(params):
        if failure["on"]:
            raise RuntimeError("second run failed")
        return run_simulation(params)

    at = _app(runner=sometimes_failing_runner)
    at.number_input(key="coin_dashboard_ticks").set_value(5)
    _run_button(at).click().run()
    assert at.metric.len > 0

    failure["on"] = True
    _run_button(at).click().run()
    assert at.metric.len == 0
    assert at.table.len == 0
    assert at.success.len == 0
    assert at.session_state[PAYLOAD_KEY] is None
    assert "second run failed" in at.error[0].value


def test_an_invalid_parameter_never_reaches_the_simulator():
    """The controls are bounded, so this is the backstop: an out-of-range
    value is rejected by ``SimulationParams`` and becomes the error state
    without the runner ever being called."""
    calls = []
    state = {"coin_dashboard_ticks": 0}

    view_module._execute(state, calls.append)

    assert calls == []
    assert state[STATUS_KEY] is RunStatus.ERROR
    assert "ticks must be" in state[ERROR_KEY]
    assert state[PAYLOAD_KEY] is None


def test_the_no_scenario_choice_means_no_scenario():
    params = view_module._params_from_widgets({"coin_dashboard_scenario": "none"})
    assert params.scenario is None


def test_the_controls_map_onto_the_cli_options():
    params = view_module._params_from_widgets(
        {
            "coin_dashboard_ticks": 7,
            "coin_dashboard_pricing_mode": "amm",
            "coin_dashboard_scenario": "wash_trading",
            "coin_dashboard_traders": False,
            "coin_dashboard_whales": False,
            "coin_dashboard_events": True,
            "coin_dashboard_random_events": True,
            "coin_dashboard_psychology": True,
            "coin_dashboard_whale_observation": True,
        }
    )
    assert params == SimulationParams(
        ticks=7, pricing_mode="amm", include_traders=False, include_whales=False,
        scenario="wash_trading", events=True, random_events=True, psychology=True,
        whale_observation=True,
    )


# --- the view computes nothing ---------------------------------------------------------------------------


def test_the_view_calls_no_analytics():
    source = Path(view_module.__file__).read_text()
    for banned in ("analyze_", "build_report", "fsum", "statistics", "numpy"):
        assert banned not in source


def test_the_view_holds_no_figures_of_its_own():
    """Its only literals are labels, keys and format specs."""
    source = Path(view_module.__file__).read_text()
    for banned in ("* 100", "/ 100", "sum(", "round("):
        assert banned not in source


# --- inside the application ------------------------------------------------------------------------------


def test_the_app_shows_the_dashboard_tab(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTOSIM_DB_PATH", str(tmp_path / "app.sqlite3"))
    clear_settings_cache()
    try:
        at = AppTest.from_file(str(APP), default_timeout=60).run()
        assert not at.exception
        assert EMPTY_MESSAGE in _values(at.info)
        assert at.button(key="coin_dashboard_run") is not None
    finally:
        clear_settings_cache()
