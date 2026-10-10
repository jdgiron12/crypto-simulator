"""The dashboard's scenario-comparison panel (Phase 20, Step 7).

The panel comes last, with its own multiselects, run count, shared base
seed, plan preview and Run comparison button, and its own session-state
keys. It never touches the single run's or the batch panel's state, and they
never touch its.
"""

from __future__ import annotations

import inspect
import json

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.errors import AppTestError

import crypto_simulator.dashboard.view as view_module
from crypto_simulator.dashboard.batch_section import SECTION_HEADING as BATCH_SECTION_HEADING
from crypto_simulator.dashboard.comparison_section import METRIC_KEY, NO_COMPARISON_MESSAGE, SECTION_HEADING
from crypto_simulator.dashboard.data import (
    MAX_COMPARISON_RUNS,
    SimulationParams,
    comparison_configurations,
    comparison_to_dict,
    configured_seed,
    run_dashboard_comparison,
)
from crypto_simulator.dashboard.view import (
    BATCH_RUNS_KEY,
    BATCH_STATUS_KEY,
    BATCH_VIEW_KEY,
    COMPARISON_ERROR_KEY,
    COMPARISON_MARKET_CONDITIONS_KEY,
    COMPARISON_PRICING_MODES_KEY,
    COMPARISON_RUNS_KEY,
    COMPARISON_SCENARIOS_KEY,
    COMPARISON_SEED_KEY,
    COMPARISON_STATUS_KEY,
    COMPARISON_VIEW_KEY,
    PAYLOAD_KEY,
    STATUS_KEY,
    TICK_SERIES_KEY,
    RunStatus,
)

TICKS = 8
RUNS = 2
SEED = 77
RUN_COMPARISON = "coin_dashboard_run_comparison"


def _dashboard(calls):
    """The dashboard with counting runners (AppTest executes this source)."""
    from crypto_simulator.dashboard.data import (
        run_dashboard_batch,
        run_dashboard_comparison,
        run_dashboard_simulation,
    )
    from crypto_simulator.dashboard.view import render_dashboard

    def runner(params):
        calls["single"] += 1
        return run_dashboard_simulation(params)

    def batch_runner(params, runs):
        calls["batch"] += 1
        return run_dashboard_batch(params, runs)

    def comparison_runner(params, configurations, runs, *, base_seed):
        calls["comparison"] += 1
        if calls.get("comparison_fails"):
            raise ValueError("comparison refused")
        return run_dashboard_comparison(params, configurations, runs, base_seed=base_seed)

    render_dashboard(runner=runner, batch_runner=batch_runner, comparison_runner=comparison_runner)


def _calls():
    return {"single": 0, "batch": 0, "comparison": 0}


def _app(calls=None) -> AppTest:
    return AppTest.from_function(_dashboard, kwargs={"calls": calls or _calls()}, default_timeout=90).run()


def _configure(at, conditions=("none", "bull"), runs=RUNS):
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)
    at.multiselect(key=COMPARISON_MARKET_CONDITIONS_KEY).set_value(list(conditions))
    at.number_input(key=COMPARISON_RUNS_KEY).set_value(runs)
    at.number_input(key=COMPARISON_SEED_KEY).set_value(SEED)
    return at


def _run_comparison(at, **kwargs):
    _configure(at, **kwargs)
    return at.button(key=RUN_COMPARISON).click().run()


def _expected(conditions=(None, "bull"), runs=RUNS):
    configs = comparison_configurations(["random_walk"], [None], list(conditions))
    return comparison_to_dict(run_dashboard_comparison(SimulationParams(ticks=TICKS), configs, runs, base_seed=SEED))


# --- the panel ------------------------------------------------------------------------------------------


def test_the_default_comparison_runner_is_the_dashboard_comparison():
    default = inspect.signature(view_module.render_dashboard).parameters["comparison_runner"].default
    assert default is run_dashboard_comparison


def test_the_empty_dashboard_shows_the_panel_after_the_batch_panel():
    at = _app()
    labels = [tab.label for tab in at.tabs]
    assert labels.index("Scenario comparison") > labels.index("Batch analysis")
    # Each tab names its panel, so neither panel repeats it as a heading
    # (Phase 24, Step 5).
    headings = [e.value for e in at.markdown]
    assert SECTION_HEADING not in headings and BATCH_SECTION_HEADING not in headings
    comparison = next(tab for tab in at.tabs if tab.label == "Scenario comparison")
    assert NO_COMPARISON_MESSAGE in [e.value for e in comparison.info]
    assert at.session_state[COMPARISON_STATUS_KEY] is RunStatus.EMPTY
    assert at.session_state[COMPARISON_VIEW_KEY] is None
    assert at.get("plotly_chart") == [] and at.metric.len == 0 and at.table.len == 0


def test_the_controls_offer_exactly_the_existing_values():
    at = _app()
    assert list(at.multiselect(key=COMPARISON_PRICING_MODES_KEY).options) == ["RW (random_walk)", "AMM (amm)"]
    assert list(at.multiselect(key=COMPARISON_SCENARIOS_KEY).options) == [
        "No manipulation", "Pump & dump", "Wash trading"]
    assert list(at.multiselect(key=COMPARISON_MARKET_CONDITIONS_KEY).options) == [
        "Neutral (no preset)", "Bear", "Bull", "Meme"]
    assert at.multiselect(key=COMPARISON_PRICING_MODES_KEY).value == ["random_walk"]
    assert at.multiselect(key=COMPARISON_SCENARIOS_KEY).value == ["none"]
    assert at.number_input(key=COMPARISON_SEED_KEY).value == configured_seed()
    assert at.number_input(key=COMPARISON_RUNS_KEY).max == 200


def test_the_plan_shows_the_total_before_running():
    at = _configure(_app(), conditions=("none", "bull", "bear"), runs=30).run()
    assert "Configurations: **3** · Runs per configuration: **30** · Total simulations: 3 × 30 = **90**" in [
        e.value for e in at.markdown]
    assert at.button(key=RUN_COMPARISON).disabled is False
    captions = " ".join(e.value for e in at.caption)
    assert f"Dashboard comparison limit: {MAX_COMPARISON_RUNS} simulations in total" in captions


def test_a_plan_over_the_budget_disables_the_button():
    calls = _calls()
    at = _configure(_app(calls), conditions=("none", "bull", "bear", "meme"), runs=150).run()
    assert "4 configurations x 150 runs is 600 simulations" in at.warning[0].value
    assert at.button(key=RUN_COMPARISON).disabled is True
    with pytest.raises(AppTestError, match="disabled"):
        at.button(key=RUN_COMPARISON).click()
    at.run()
    assert calls["comparison"] == 0
    assert at.session_state[COMPARISON_STATUS_KEY] is RunStatus.EMPTY


def test_amm_with_whales_is_blocked_until_whales_are_off():
    calls = _calls()
    at = _configure(_app(calls))
    at.multiselect(key=COMPARISON_PRICING_MODES_KEY).set_value(["random_walk", "amm"]).run()
    assert "AMM configurations cannot run with whales" in at.warning[0].value
    assert at.button(key=RUN_COMPARISON).disabled is True
    assert at.checkbox(key="coin_dashboard_whales").value is True
    at.checkbox(key="coin_dashboard_whales").uncheck().run()
    assert at.warning.len == 0
    at.button(key=RUN_COMPARISON).click().run()
    assert calls["comparison"] == 1
    stored = at.session_state[COMPARISON_VIEW_KEY]
    assert [g["pricing_mode"] for g in stored["groups"]] == ["random_walk", "random_walk", "amm", "amm"]
    assert stored["held_constant"]["include_whales"] is False


# --- the comparison button ------------------------------------------------------------------------------


def test_the_comparison_button_runs_only_the_comparison():
    calls = _calls()
    at = _run_comparison(_app(calls))
    assert calls == {"single": 0, "batch": 0, "comparison": 1}
    assert at.session_state[COMPARISON_STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[COMPARISON_VIEW_KEY] == _expected()
    assert at.session_state[STATUS_KEY] is RunStatus.EMPTY and at.session_state[PAYLOAD_KEY] is None
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.EMPTY and at.session_state[BATCH_VIEW_KEY] is None
    assert at.session_state[TICK_SERIES_KEY] is None


def test_the_stored_comparison_is_plain_reduced_data():
    at = _run_comparison(_app())
    stored = at.session_state[COMPARISON_VIEW_KEY]
    assert json.loads(json.dumps(stored)) == stored
    for key in ("price_series", "tick_series", "report", "payload"):
        assert f'"{key}"' not in json.dumps(stored), key


def test_the_comparison_is_drawn_after_it_runs():
    at = _run_comparison(_app())
    titles = [json.loads(c.proto.spec)["layout"]["title"]["text"] for c in at.get("plotly_chart")]
    assert len(titles) == 1 and titles[0] == "Close price by configuration"
    assert list(at.table[0].value.index) == ["RW | No manipulation | Neutral (no preset)",
                                            "RW | No manipulation | Bull"]


def test_the_comparison_survives_reruns_without_running_again():
    calls = _calls()
    at = _run_comparison(_app(calls))
    stored = at.session_state[COMPARISON_VIEW_KEY]
    at.selectbox(key=METRIC_KEY).set_value("total_volume").run()
    at.multiselect(key=COMPARISON_MARKET_CONDITIONS_KEY).set_value(["meme"]).run()
    assert calls["comparison"] == 1
    assert at.session_state[COMPARISON_VIEW_KEY] == stored


def test_a_new_comparison_replaces_only_the_comparison():
    calls = _calls()
    at = _run_comparison(_app(calls))
    at.number_input(key=BATCH_RUNS_KEY).set_value(2)
    at.button(key="coin_dashboard_run_batch").click().run()
    batch = at.session_state[BATCH_VIEW_KEY]
    at.multiselect(key=COMPARISON_MARKET_CONDITIONS_KEY).set_value(["bear"])
    at.button(key=RUN_COMPARISON).click().run()
    assert calls == {"single": 0, "batch": 1, "comparison": 2}
    assert [g["market_condition"] for g in at.session_state[COMPARISON_VIEW_KEY]["groups"]] == ["bear"]
    assert at.session_state[BATCH_VIEW_KEY] == batch


def test_a_comparison_that_cannot_run_reports_its_error_and_leaves_the_rest():
    calls = _calls()
    at = _app(calls)
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)
    at.button(key="coin_dashboard_run").click().run()
    payload = at.session_state[PAYLOAD_KEY]
    calls["comparison_fails"] = True
    _run_comparison(at)
    assert at.session_state[COMPARISON_STATUS_KEY] is RunStatus.ERROR
    assert at.session_state[COMPARISON_VIEW_KEY] is None
    assert "ValueError: comparison refused" in at.session_state[COMPARISON_ERROR_KEY]
    assert "Comparison failed. ValueError: comparison refused" in [e.value for e in at.error]
    assert at.session_state[PAYLOAD_KEY] == payload


# --- isolation ------------------------------------------------------------------------------------------


def test_single_runs_and_batches_leave_the_comparison_in_place():
    calls = _calls()
    at = _run_comparison(_app(calls))
    stored = at.session_state[COMPARISON_VIEW_KEY]
    at.button(key="coin_dashboard_run").click().run()
    at.number_input(key=BATCH_RUNS_KEY).set_value(2)
    at.button(key="coin_dashboard_run_batch").click().run()
    assert calls == {"single": 1, "batch": 1, "comparison": 1}
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[COMPARISON_VIEW_KEY] == stored


def test_a_comparison_leaves_the_single_run_and_the_batch_in_place():
    at = _app()
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)
    at.button(key="coin_dashboard_run").click().run()
    at.number_input(key=BATCH_RUNS_KEY).set_value(2)
    at.button(key="coin_dashboard_run_batch").click().run()
    payload, series, batch = (at.session_state[PAYLOAD_KEY], at.session_state[TICK_SERIES_KEY],
                              at.session_state[BATCH_VIEW_KEY])
    _run_comparison(at)
    assert at.session_state[PAYLOAD_KEY] == payload
    assert at.session_state[TICK_SERIES_KEY] == series
    assert at.session_state[BATCH_VIEW_KEY] == batch
