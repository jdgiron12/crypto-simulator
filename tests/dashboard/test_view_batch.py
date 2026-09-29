"""The dashboard's batch panel (Phase 20, Step 6).

The panel comes after every single-run view, with its own run count, its own
Run batch button and its own session-state keys. A batch stores only the
serialized reduced batch; the two buttons never touch each other's state, and
a batch builds no tick series.
"""

from __future__ import annotations

import inspect
import json

from streamlit.testing.v1 import AppTest

import crypto_simulator.dashboard.view as view_module
from crypto_simulator.dashboard.batch_section import METRIC_KEY, NO_BATCH_MESSAGE, SECTION_HEADING
from crypto_simulator.dashboard.data import (
    MAX_BATCH_RUNS,
    MAX_DASHBOARD_BATCH_RUNS,
    SimulationParams,
    batch_to_dict,
    payload_to_dict,
    run_dashboard_batch,
    run_dashboard_simulation,
    tick_series_to_dict,
)
from crypto_simulator.dashboard.tick_section import SECTION_HEADING as TICK_SECTION_HEADING
from crypto_simulator.dashboard.view import (
    BATCH_ERROR_KEY,
    BATCH_RUNS_KEY,
    BATCH_STATUS_KEY,
    BATCH_VIEW_KEY,
    DEFAULT_BATCH_RUNS,
    ERROR_KEY,
    PAYLOAD_KEY,
    STATUS_KEY,
    TICK_SERIES_KEY,
    RunStatus,
)

TICKS = 8
RUNS = 3


def _dashboard(calls):
    """The dashboard with counting runners (AppTest executes this source)."""
    from crypto_simulator.dashboard.data import run_dashboard_batch, run_dashboard_simulation
    from crypto_simulator.dashboard.view import render_dashboard

    def runner(params):
        calls["single"] += 1
        return run_dashboard_simulation(params)

    def batch_runner(params, runs):
        calls["batch"] += 1
        if calls.get("batch_fails"):
            raise ValueError("batch refused")
        return run_dashboard_batch(params, runs)

    render_dashboard(runner=runner, batch_runner=batch_runner)


def _app(calls=None) -> AppTest:
    calls = calls if calls is not None else {"single": 0, "batch": 0}
    return AppTest.from_function(_dashboard, kwargs={"calls": calls}, default_timeout=90).run()


def _set_ticks(at):
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)


def _run_single(at):
    _set_ticks(at)
    return at.button(key="coin_dashboard_run").click().run()


def _run_batch(at, runs=RUNS):
    _set_ticks(at)
    at.number_input(key=BATCH_RUNS_KEY).set_value(runs)
    return at.button(key="coin_dashboard_run_batch").click().run()


def _params():
    return SimulationParams(ticks=TICKS)


# --- the panel ------------------------------------------------------------------------------------------


def test_the_default_batch_runner_is_the_dashboard_batch():
    default = inspect.signature(view_module.render_dashboard).parameters["batch_runner"].default
    assert default is run_dashboard_batch


def test_the_empty_dashboard_shows_the_batch_panel_and_no_batch():
    at = _app()
    assert SECTION_HEADING in [e.value for e in at.markdown]
    assert NO_BATCH_MESSAGE in [e.value for e in at.info]
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.EMPTY
    assert at.session_state[BATCH_VIEW_KEY] is None
    assert at.get("plotly_chart") == []


def test_the_run_count_control_is_held_to_the_dashboard_limit():
    at = _app()
    control = at.number_input(key=BATCH_RUNS_KEY)
    assert control.value == DEFAULT_BATCH_RUNS
    assert control.max == MAX_DASHBOARD_BATCH_RUNS == 200
    assert control.min == 1
    assert "Dashboard batch limit: 200 runs" in control.help
    captions = " ".join(e.value for e in at.caption)
    assert f"Dashboard batch limit: {MAX_DASHBOARD_BATCH_RUNS} runs per batch" in captions
    assert f"the batch service limit, used by the CLI, is {MAX_BATCH_RUNS}" in captions


def test_the_batch_panel_comes_after_every_single_run_view():
    at = _run_batch(_run_single(_app()))
    headings = [e.value for e in at.markdown]
    assert headings.index(SECTION_HEADING) > headings.index(TICK_SECTION_HEADING)
    assert headings.index(SECTION_HEADING) > headings.index("**Market regimes**")


# --- the batch button ------------------------------------------------------------------------------------


def test_the_batch_button_runs_only_the_batch():
    calls = {"single": 0, "batch": 0}
    at = _run_batch(_app(calls))
    assert calls == {"single": 0, "batch": 1}
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[BATCH_VIEW_KEY] == batch_to_dict(run_dashboard_batch(_params(), RUNS))
    assert at.session_state[STATUS_KEY] is RunStatus.EMPTY
    assert at.session_state[PAYLOAD_KEY] is None
    assert at.session_state[TICK_SERIES_KEY] is None


def test_the_batch_runs_the_configuration_the_controls_describe():
    at = _app()
    at.number_input(key="coin_dashboard_ticks").set_value(6)
    at.checkbox(key="coin_dashboard_whales").uncheck()
    at.number_input(key=BATCH_RUNS_KEY).set_value(2)
    at.button(key="coin_dashboard_run_batch").click().run()
    stored = at.session_state[BATCH_VIEW_KEY]
    assert stored["params"]["ticks"] == 6
    assert stored["params"]["include_whales"] is False
    assert stored["requested_runs"] == 2


def test_the_stored_batch_is_plain_reduced_data_with_no_tick_series():
    at = _run_batch(_app())
    stored = at.session_state[BATCH_VIEW_KEY]
    assert isinstance(stored, dict)
    assert json.loads(json.dumps(stored)) == stored
    text = json.dumps(stored)
    for key in ("price_series", "tick_series", "report", "payload"):
        assert f'"{key}"' not in text, key
    assert at.session_state[TICK_SERIES_KEY] is None


def test_the_batch_is_drawn_after_it_runs():
    at = _run_batch(_app())
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Requested runs"] == str(RUNS)
    assert metrics["Successful runs"] == str(RUNS)
    titles = [json.loads(c.proto.spec)["layout"]["title"]["text"] for c in at.get("plotly_chart")]
    assert len(titles) == 6
    assert titles[0].startswith("Selected metric across successful batch runs")
    assert titles[1].startswith("Recorded price across successful runs, per tick")


def test_the_batch_survives_reruns_without_running_again():
    calls = {"single": 0, "batch": 0}
    at = _run_batch(_app(calls))
    stored = at.session_state[BATCH_VIEW_KEY]
    at.selectbox(key=METRIC_KEY).set_value("max_drawdown").run()
    at.checkbox(key="coin_dashboard_events").check().run()
    assert calls["batch"] == 1
    assert at.session_state[BATCH_VIEW_KEY] == stored


def test_a_batch_that_cannot_run_reports_its_error_and_leaves_the_single_run():
    calls = {"single": 0, "batch": 0}
    at = _run_single(_app(calls))
    payload = at.session_state[PAYLOAD_KEY]
    calls["batch_fails"] = True
    at.button(key="coin_dashboard_run_batch").click().run()
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.ERROR
    assert at.session_state[BATCH_VIEW_KEY] is None
    assert "ValueError: batch refused" in at.session_state[BATCH_ERROR_KEY]
    assert "Batch failed. ValueError: batch refused" in [e.value for e in at.error]
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[PAYLOAD_KEY] == payload


# --- isolation from the single run ----------------------------------------------------------------------


def test_a_batch_leaves_the_single_run_result_in_place():
    calls = {"single": 0, "batch": 0}
    at = _run_single(_app(calls))
    payload, series = at.session_state[PAYLOAD_KEY], at.session_state[TICK_SERIES_KEY]
    _run_batch(at)
    assert calls == {"single": 1, "batch": 1}
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[PAYLOAD_KEY] == payload == payload_to_dict(run_dashboard_simulation(_params()).payload)
    assert at.session_state[TICK_SERIES_KEY] == series == tick_series_to_dict(
        run_dashboard_simulation(_params()).tick_series)
    assert "Simulation complete" in at.success[0].value


def test_a_single_run_leaves_the_batch_in_place():
    calls = {"single": 0, "batch": 0}
    at = _run_batch(_app(calls))
    stored = at.session_state[BATCH_VIEW_KEY]
    at.button(key="coin_dashboard_run").click().run()
    assert calls == {"single": 1, "batch": 1}
    assert at.session_state[BATCH_STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[BATCH_VIEW_KEY] == stored
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS


def test_a_failed_single_run_leaves_the_batch_in_place():
    at = _run_batch(_app())
    stored = at.session_state[BATCH_VIEW_KEY]
    at.selectbox(key="coin_dashboard_pricing_mode").set_value("amm")
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.ERROR
    assert "Whales are not supported" in at.session_state[ERROR_KEY]
    assert at.session_state[BATCH_VIEW_KEY] == stored


def test_the_single_run_flow_is_unchanged_with_the_panel_present():
    at = _run_single(_app())
    assert at.session_state[PAYLOAD_KEY] == payload_to_dict(run_dashboard_simulation(_params()).payload)
    first = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert first["data"][0]["y"] == [p.price for p in run_dashboard_simulation(_params()).payload.price_series]
    assert at.session_state[BATCH_VIEW_KEY] is None


# --- price-path bands (Phase 20, Step 8) ----------------------------------------------------------------


def test_the_stored_batch_carries_its_price_path_bands_and_no_run_path():
    at = _run_batch(_app())
    bands = at.session_state[BATCH_VIEW_KEY]["price_paths"]
    assert bands["runs"] == RUNS
    assert bands["ticks"] == list(range(1, TICKS + 1))
    assert '"price_series"' not in json.dumps(at.session_state[BATCH_VIEW_KEY])


def test_price_paths_survive_reruns_and_the_extremes_toggle_without_running_again():
    from crypto_simulator.dashboard.batch_section import PRICE_PATH_EXTREMES_KEY

    calls = {"single": 0, "batch": 0}
    at = _run_batch(_app(calls))
    stored = at.session_state[BATCH_VIEW_KEY]
    at.checkbox(key=PRICE_PATH_EXTREMES_KEY).check().run()
    at.selectbox(key=METRIC_KEY).set_value("total_volume").run()
    at.checkbox(key=PRICE_PATH_EXTREMES_KEY).uncheck().run()
    assert calls == {"single": 0, "batch": 1}
    assert at.session_state[BATCH_VIEW_KEY] == stored
    titles = [json.loads(c.proto.spec)["layout"]["title"]["text"] for c in at.get("plotly_chart")]
    assert any(t.startswith("Recorded price across successful runs, per tick") for t in titles)


def test_a_single_run_leaves_the_batch_price_paths_in_place():
    at = _run_batch(_app())
    bands = at.session_state[BATCH_VIEW_KEY]["price_paths"]
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[BATCH_VIEW_KEY]["price_paths"] == bands


def test_a_new_batch_replaces_the_price_paths():
    at = _run_batch(_app(), runs=2)
    assert at.session_state[BATCH_VIEW_KEY]["price_paths"]["runs"] == 2
    _run_batch(at, runs=4)
    assert at.session_state[BATCH_VIEW_KEY]["price_paths"]["runs"] == 4
    assert at.session_state[BATCH_VIEW_KEY] == batch_to_dict(run_dashboard_batch(_params(), 4))


def test_a_scenario_comparison_gets_no_price_paths_and_leaves_the_batchs():
    from crypto_simulator.dashboard.view import (
        COMPARISON_MARKET_CONDITIONS_KEY,
        COMPARISON_RUNS_KEY,
        COMPARISON_VIEW_KEY,
    )

    at = _run_batch(_app())
    bands = at.session_state[BATCH_VIEW_KEY]["price_paths"]
    at.multiselect(key=COMPARISON_MARKET_CONDITIONS_KEY).set_value(["none", "bull"])
    at.number_input(key=COMPARISON_RUNS_KEY).set_value(2)
    at.button(key="coin_dashboard_run_comparison").click().run()
    groups = at.session_state[COMPARISON_VIEW_KEY]["groups"]
    assert len(groups) == 2
    assert all(group["batch"]["price_paths"] is None for group in groups)
    assert at.session_state[BATCH_VIEW_KEY]["price_paths"] == bands
