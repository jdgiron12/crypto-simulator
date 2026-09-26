"""The dashboard's tick-series plumbing (Phase 20, Step 4).

The default runner returns a ``DashboardRun``; the view stores its payload
under ``PAYLOAD_KEY`` exactly as before and its serialized tick series under
``TICK_SERIES_KEY``, and draws the tick-level views after every existing
section. A payload-only runner leaves the key ``None`` and gets the frozen
unavailable message. The OHLC window control never runs a simulation.
"""

from __future__ import annotations

import json

from streamlit.testing.v1 import AppTest

from crypto_simulator.dashboard.data import (
    TICK_SERIES_UNAVAILABLE_MESSAGE,
    SimulationParams,
    payload_to_dict,
    run_dashboard_simulation,
    run_simulation,
    tick_series_to_dict,
)
from crypto_simulator.dashboard.tick_section import OHLC_WINDOW_KEY, SECTION_HEADING
from crypto_simulator.dashboard.view import (
    ERROR_KEY,
    PAYLOAD_KEY,
    REPORT_SECTIONS,
    STATUS_KEY,
    TICK_SERIES_KEY,
    RunStatus,
)

TICKS = 12


def _default_dashboard():
    """The dashboard with its own default runner (AppTest executes this source)."""
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard()


def _dashboard(runner):
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard(runner=runner)


def _run(at: AppTest) -> AppTest:
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)
    return at.button(key="coin_dashboard_run").click().run()


def _default_app() -> AppTest:
    return AppTest.from_function(_default_dashboard, default_timeout=90).run()


def _app(runner) -> AppTest:
    return AppTest.from_function(_dashboard, kwargs={"runner": runner}, default_timeout=90).run()


def _params():
    return SimulationParams(ticks=TICKS)


def test_the_default_runner_stores_the_tick_series_beside_an_identical_payload():
    at = _run(_default_app())
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    run = run_dashboard_simulation(_params())
    assert at.session_state[PAYLOAD_KEY] == payload_to_dict(run_simulation(_params()))
    assert at.session_state[TICK_SERIES_KEY] == tick_series_to_dict(run.tick_series)
    assert "tick_series" not in at.session_state[PAYLOAD_KEY]


def test_a_payload_only_runner_gets_the_unavailable_message():
    at = _run(_app(run_simulation))
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    assert at.session_state[TICK_SERIES_KEY] is None
    assert TICK_SERIES_UNAVAILABLE_MESSAGE in [info.value for info in at.info]
    assert at.session_state[PAYLOAD_KEY] == payload_to_dict(run_simulation(_params()))


def test_the_tick_views_come_after_every_existing_section_and_the_price_chart_stays_first():
    at = _run(_default_app())
    headings = [element.value for element in at.markdown]
    positions = [headings.index(f"**{label}**") for label, _ in REPORT_SECTIONS]
    assert positions == sorted(positions)
    assert headings.index(SECTION_HEADING) > positions[-1]
    first = json.loads(at.get("plotly_chart")[0].proto.spec)
    run = run_simulation(_params())
    assert first["data"][0]["x"] == [point.tick for point in run.price_series]
    assert first["data"][0]["y"] == [point.price for point in run.price_series]
    assert first["data"][0]["type"] == "scatter"


def test_the_existing_charts_are_unchanged_and_the_new_ones_are_appended():
    before = _run(_app(run_simulation)).get("plotly_chart")
    after = _run(_default_app()).get("plotly_chart")
    assert [c.proto.spec for c in after[:len(before)]] == [c.proto.spec for c in before]
    assert len(after) > len(before)


def test_changing_the_ohlc_window_does_not_run_the_simulation():
    calls = {"count": 0}

    def counting_runner(params):
        from crypto_simulator.dashboard.data import run_dashboard_simulation

        calls["count"] += 1
        return run_dashboard_simulation(params)

    at = _run(_app(counting_runner))
    assert calls["count"] == 1
    stored = at.session_state[TICK_SERIES_KEY]
    at.selectbox(key=OHLC_WINDOW_KEY).set_value(5).run()
    at.selectbox(key=OHLC_WINDOW_KEY).set_value(50).run()
    assert calls["count"] == 1
    assert at.session_state[TICK_SERIES_KEY] is stored or at.session_state[TICK_SERIES_KEY] == stored


def test_an_error_clears_the_tick_series():
    state = {"fail": False}

    def sometimes_failing_runner(params):
        from crypto_simulator.dashboard.data import run_dashboard_simulation

        if state["fail"]:
            raise ValueError("boom")
        return run_dashboard_simulation(params)

    at = _run(_app(sometimes_failing_runner))
    assert at.session_state[TICK_SERIES_KEY] is not None
    state["fail"] = True
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.ERROR
    assert at.session_state[TICK_SERIES_KEY] is None
    assert at.session_state[PAYLOAD_KEY] is None
    assert "boom" in at.session_state[ERROR_KEY]
    assert at.get("plotly_chart") == []


def test_a_new_request_clears_the_tick_series_before_the_run():
    runs = {"count": 0}

    def runner_then_stop(params):
        import streamlit as st

        from crypto_simulator.dashboard.data import run_dashboard_simulation

        runs["count"] += 1
        if runs["count"] > 1:
            st.stop()
        return run_dashboard_simulation(params)

    at = _run(_app(runner_then_stop))
    assert at.session_state[TICK_SERIES_KEY] is not None
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.RUNNING
    assert at.session_state[TICK_SERIES_KEY] is None


def test_the_empty_state_has_no_tick_series_and_no_views():
    at = _default_app()
    assert at.session_state[TICK_SERIES_KEY] is None
    assert SECTION_HEADING not in [element.value for element in at.markdown]
    assert at.get("plotly_chart") == []
