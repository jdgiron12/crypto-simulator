"""Consistency of the dashboard's wording and actions (Phase 24, Step 7).

Presentation only. Step 4 renamed the run controls and moved them into the
sidebar's Run setup; every message that tells the reader which control to
change now names a control that exists, by the label it is drawn with, and
the comparison plan lists the held-constant options under the same names.
The three workflows' run buttons look alike. The dashboard reads and writes
no database, so nothing here does.
"""

from __future__ import annotations

import re

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.dashboard.comparison_section import _held_constant
from crypto_simulator.dashboard.data import SimulationParams, comparison_configurations, plan_comparison
from crypto_simulator.dashboard.event_section import NO_TIMELINE_MESSAGE
from crypto_simulator.dashboard.manipulation_section import NO_SCENARIO_MESSAGE
from crypto_simulator.dashboard.psychology_section import PSYCHOLOGY_OFF_MESSAGE
from crypto_simulator.dashboard.tick_section import NO_EVENT_STATE_MESSAGE
from crypto_simulator.dashboard.view import RUN_ICON
from crypto_simulator.dashboard.whale_section import NO_COHORTS_MESSAGE, NOT_OBSERVED_MESSAGE

AMM_WITH_WHALES = plan_comparison(
    SimulationParams(ticks=12), comparison_configurations(["amm"], [None], [None]), 3
).problems[0]

#: Every message that points the reader at a run control.
CONTROL_MESSAGES = {
    "event timeline": NO_TIMELINE_MESSAGE,
    "event state": NO_EVENT_STATE_MESSAGE,
    "psychology": PSYCHOLOGY_OFF_MESSAGE,
    "manipulation": NO_SCENARIO_MESSAGE,
    "whales not observed": NOT_OBSERVED_MESSAGE,
    "whale cohorts": NO_COHORTS_MESSAGE,
    "AMM with whales": AMM_WITH_WHALES,
}

RUN_BUTTONS = ("coin_dashboard_run", "coin_dashboard_run_batch", "coin_dashboard_run_comparison")


def _dashboard():
    """The dashboard with its default runners (AppTest executes this source)."""
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard()


@pytest.fixture(scope="module")
def app() -> AppTest:
    return AppTest.from_function(_dashboard, default_timeout=60).run()


def _sidebar_labels(at: AppTest) -> set[str]:
    sidebar = at.sidebar
    return {w.label for kind in (sidebar.checkbox, sidebar.selectbox, sidebar.number_input) for w in kind}


@pytest.mark.parametrize("name", list(CONTROL_MESSAGES))
def test_a_message_names_controls_by_their_drawn_labels(app, name):
    message = CONTROL_MESSAGES[name]
    # A quoted name opens after a space or bracket; "run's" is not a quote.
    named = re.findall(r"(?:^|[\s(])'([^']+)'(?=[\s,.;)]|$)", message)
    assert named or name == "whale cohorts"
    assert set(named) <= _sidebar_labels(app), named


@pytest.mark.parametrize("name", list(CONTROL_MESSAGES))
def test_a_message_points_at_the_run_setup(name):
    message = CONTROL_MESSAGES[name]
    assert "run options" not in message
    if name != "whales not observed":
        assert "Run setup" in message


def test_the_held_constant_line_uses_the_control_names(app):
    params = {"ticks": 12, "include_traders": True, "include_whales": False, "whale_observation": True,
              "events": False, "random_events": True, "psychology": False}
    assert _held_constant(params) == (
        "12 ticks · traders on · whales off · record whale detail on · scheduled news off · "
        "random news on · trader psychology off"
    )
    labels = {label.lower() for label in _sidebar_labels(app)}
    for part in _held_constant(params).split(" · ")[1:]:
        assert part.rsplit(" ", 1)[0] in labels, part


def test_the_three_run_buttons_look_alike(app):
    buttons = [app.button(key=key) for key in RUN_BUTTONS]
    assert [b.label for b in buttons] == ["Run simulation", "Run batch", "Run comparison"]
    assert {b.proto.icon for b in buttons} == {RUN_ICON}
