"""The coin-economy dashboard's Streamlit view (Phase 10).

Presentation only, in the spirit of ``app.py``: this module receives the
serialized payload from ``dashboard.data`` and formats it for display. It
runs no simulation math and computes no analytical figure — no return,
volatility, volume, P&L or label is calculated here. Every number shown is
read straight out of the payload (which holds the ``SimulationReport``'s
own values) and only ever passed through a format spec.

**States.** The dashboard is a small state machine kept in
``st.session_state``:

    empty    nothing has been run yet         EMPTY_MESSAGE
    running  a run was requested this rerun   RUNNING_MESSAGE, then the work
    success  a payload is available           status, then the sections
    error    the run raised                   the error, and no results

An error clears the previous payload, so a failed run never leaves the
last run's figures on screen presented as the new one, and requesting a
run clears the previous result before the work begins.

**Sections.** This module owns the run controls, the states and the run
status; each section renders itself from the same payload
(``market_section.render_market``, Step 2). The trader, whale, event,
psychology, manipulation and regime sections are still labelled
placeholders for later Phase 10 steps; they show no numbers rather than
invented ones.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, MutableMapping

import streamlit as st

from crypto_simulator.dashboard.data import (
    MAX_TICKS,
    PRICING_MODES,
    SCENARIOS,
    DashboardPayload,
    SimulationParams,
    payload_to_dict,
    run_simulation,
)
from crypto_simulator.dashboard.formatting import text
from crypto_simulator.dashboard.market_section import render_market

__all__ = [
    "EMPTY_MESSAGE",
    "RUNNING_MESSAGE",
    "ERROR_KEY",
    "PAYLOAD_KEY",
    "STATUS_KEY",
    "RunStatus",
    "render_dashboard",
]

EMPTY_MESSAGE = "No simulation results yet. Run a simulation to view analytics."
RUNNING_MESSAGE = "Running simulation..."

STATUS_KEY = "coin_dashboard_status"
PAYLOAD_KEY = "coin_dashboard_payload"
ERROR_KEY = "coin_dashboard_error"

_NO_SCENARIO = "none"

#: Sections later Phase 10 steps will fill, with the payload key each one
#: will read. Nothing is rendered from them yet.
PLACEHOLDER_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Traders", "traders"),
    ("Whales", "whale_activity"),
    ("Events", "event_windows"),
    ("Psychology", "psychology_market"),
    ("Manipulation", "manipulation"),
    ("Regimes", "regimes"),
)


class RunStatus(str, Enum):
    """Where the dashboard is in the run cycle."""

    EMPTY = "empty"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


def render_dashboard(*, runner: Callable[..., DashboardPayload] = run_simulation) -> None:
    """Render the whole dashboard into the current Streamlit container.

    ``runner`` is the simulation entry point, injected so tests can drive
    the failure path; it defaults to ``dashboard.data.run_simulation``.
    """
    state = st.session_state
    _init_state(state)

    st.subheader("Coin economy simulation")
    st.caption(
        "A finished synthetic run, described by the simulator's own analytics report. "
        "Read-only: the dashboard observes a completed simulation and changes nothing in it."
    )

    _render_controls()

    if state[STATUS_KEY] is RunStatus.RUNNING:
        placeholder = st.empty()
        placeholder.info(RUNNING_MESSAGE)
        _execute(state, runner)
        placeholder.empty()

    status = state[STATUS_KEY]
    if status is RunStatus.ERROR:
        _render_error(state[ERROR_KEY])
    elif status is RunStatus.SUCCESS:
        _render_results(state[PAYLOAD_KEY])
    else:
        _render_empty()


# --- state ---------------------------------------------------------------------------------------------


def _init_state(state: MutableMapping[str, Any]) -> None:
    state.setdefault(STATUS_KEY, RunStatus.EMPTY)
    state.setdefault(PAYLOAD_KEY, None)
    state.setdefault(ERROR_KEY, None)


def _request_run() -> None:
    """Button callback: mark a run as requested and drop the old result.

    Runs before the rerun that does the work, so the dashboard shows
    ``RUNNING_MESSAGE`` instead of the previous run's figures while the
    simulation is in progress.
    """
    st.session_state[STATUS_KEY] = RunStatus.RUNNING
    st.session_state[PAYLOAD_KEY] = None
    st.session_state[ERROR_KEY] = None


def _execute(state: MutableMapping[str, Any], runner: Callable[..., DashboardPayload]) -> None:
    """Run one simulation and store its serialized payload, or the error.

    A failure is reported, never fabricated around: the payload stays
    ``None`` so no stale or invented figures are shown.
    """
    try:
        payload = runner(_params_from_widgets(state))
        state[PAYLOAD_KEY] = payload_to_dict(payload)
        state[ERROR_KEY] = None
        state[STATUS_KEY] = RunStatus.SUCCESS
    except Exception as exc:  # noqa: BLE001 - the UI reports any failure rather than crashing
        state[PAYLOAD_KEY] = None
        state[ERROR_KEY] = f"{type(exc).__name__}: {exc}"
        state[STATUS_KEY] = RunStatus.ERROR


def _params_from_widgets(state: MutableMapping[str, Any]) -> SimulationParams:
    """Read the controls into validated parameters.

    ``SimulationParams`` rejects anything outside the known set, so a bad
    combination surfaces as the error state rather than reaching the
    simulator.
    """
    scenario = state.get("coin_dashboard_scenario", _NO_SCENARIO)
    return SimulationParams(
        ticks=int(state.get("coin_dashboard_ticks", 20)),
        pricing_mode=state.get("coin_dashboard_pricing_mode", PRICING_MODES[0]),
        include_traders=bool(state.get("coin_dashboard_traders", True)),
        include_whales=bool(state.get("coin_dashboard_whales", True)),
        scenario=None if scenario == _NO_SCENARIO else scenario,
        events=bool(state.get("coin_dashboard_events", False)),
        random_events=bool(state.get("coin_dashboard_random_events", False)),
        psychology=bool(state.get("coin_dashboard_psychology", False)),
        whale_observation=bool(state.get("coin_dashboard_whale_observation", False)),
    )


# --- controls ------------------------------------------------------------------------------------------


def _render_controls() -> None:
    """The run controls — the same options ``scripts/simulate_coin.py``
    exposes, so a dashboard run is a CLI run."""
    left, middle, right = st.columns(3)
    left.number_input("Ticks", min_value=1, max_value=MAX_TICKS, value=20, step=1,
                      key="coin_dashboard_ticks")
    middle.selectbox("Pricing mode", PRICING_MODES, key="coin_dashboard_pricing_mode")
    right.selectbox("Manipulation scenario", (_NO_SCENARIO, *SCENARIOS), key="coin_dashboard_scenario")

    toggles = st.columns(3)
    toggles[0].checkbox("Traders", value=True, key="coin_dashboard_traders")
    toggles[0].checkbox("Whales", value=True, key="coin_dashboard_whales")
    toggles[1].checkbox("News events", key="coin_dashboard_events")
    toggles[1].checkbox("Random news events", key="coin_dashboard_random_events")
    toggles[2].checkbox("Psychology", key="coin_dashboard_psychology")
    toggles[2].checkbox("Whale observation", key="coin_dashboard_whale_observation")

    st.button("Run simulation", key="coin_dashboard_run", on_click=_request_run)


# --- states --------------------------------------------------------------------------------------------


def _render_empty() -> None:
    st.info(EMPTY_MESSAGE)


def _render_error(message: str | None) -> None:
    st.error(f"Simulation failed. {message or 'No details were reported.'}")
    st.caption("No results are shown for a failed run.")


def _render_results(payload: dict[str, Any] | None) -> None:
    """Every section, from one payload."""
    if payload is None:  # defensive: success is only set with a payload
        _render_empty()
        return
    simulation = payload["simulation"]
    report = payload["report"]
    _render_status_section(simulation, report)
    render_market(
        report["market"],
        symbol=simulation["coin_symbol"],
        price_series=payload["price_series"],
        scope=(report["start_tick"], report["end_tick"]),
    )
    _render_placeholders()


def _render_status_section(simulation: dict[str, Any], report: dict[str, Any]) -> None:
    st.success(
        f"Simulation complete — {simulation['completed_ticks']} of "
        f"{simulation['requested_ticks']} requested ticks, "
        f"{report['ticks']} analysed."
    )
    st.caption(
        f"{simulation['coin_name']} ({simulation['coin_symbol']}) · "
        f"pricing mode {simulation['pricing_mode']} · seed {text(simulation['random_seed'])} · "
        f"run {simulation['simulation_id']}"
    )


def _render_placeholders() -> None:
    st.markdown("**Further sections**")
    for label, key in PLACEHOLDER_SECTIONS:
        st.caption(f"{label} — report.{key} is in the payload; rendered in a later Phase 10 step.")
