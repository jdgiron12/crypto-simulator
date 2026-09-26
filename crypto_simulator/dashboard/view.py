"""The coin-economy dashboard's Streamlit view (Phase 10, Steps 1-7).

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

**Controls.** The controls are the CLI's flags plus the seed (Step 7).
The seed control is off by default and then requests nothing, so a
defaulted run is the configured-seed run the dashboard always did; turned
on, it runs the same options against a chosen seed. The view still reads
no configuration of its own — the configured seed it shows as the
control's starting value comes from ``data.configured_seed``.

**Sections.** This module owns the run controls, the states and the run
status; each section renders itself from the same payload
(``market_section.render_market``, Step 2;
``trader_section.render_traders``, Step 3; ``whale_section.render_whales``,
Step 4; ``event_section.render_events`` and
``psychology_section.render_psychology``, Step 5;
``manipulation_section.render_manipulation`` and
``regime_section.render_regimes``, Step 6). Every section of the report is
now rendered from the payload, so nothing is left as a placeholder.

**Tick-level views** (Phase 20, Step 4). The default runner is
``run_dashboard_simulation``, which returns the same payload plus the run's
``TickSeries``; the serialized tick series is kept under its own key
(``TICK_SERIES_KEY``), never inside the payload, and
``tick_section.render_tick_views`` draws it after every report section. A
runner that returns only a payload leaves the key ``None``, and the section
then shows ``TICK_SERIES_UNAVAILABLE_MESSAGE`` — the state a saved run will
be in, since tick series are never persisted.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, MutableMapping

import streamlit as st

from crypto_simulator.dashboard.data import (
    MAX_SEED,
    MAX_TICKS,
    MIN_SEED,
    PRICING_MODES,
    SCENARIOS,
    DashboardPayload,
    DashboardRun,
    SimulationParams,
    configured_seed,
    payload_to_dict,
    run_dashboard_simulation,
    tick_series_to_dict,
)
from crypto_simulator.dashboard.formatting import text
from crypto_simulator.dashboard.event_section import render_events
from crypto_simulator.dashboard.manipulation_section import render_manipulation
from crypto_simulator.dashboard.market_section import render_market
from crypto_simulator.dashboard.psychology_section import render_psychology
from crypto_simulator.dashboard.regime_section import render_regimes
from crypto_simulator.dashboard.tick_section import render_tick_views
from crypto_simulator.dashboard.trader_section import render_traders
from crypto_simulator.dashboard.whale_section import render_whales

__all__ = [
    "EMPTY_MESSAGE",
    "RUNNING_MESSAGE",
    "ERROR_KEY",
    "PAYLOAD_KEY",
    "SEED_KEY",
    "SEED_OVERRIDE_KEY",
    "STATUS_KEY",
    "TICK_SERIES_KEY",
    "RunStatus",
    "render_dashboard",
]

EMPTY_MESSAGE = "No simulation results yet. Run a simulation to view analytics."
RUNNING_MESSAGE = "Running simulation..."

STATUS_KEY = "coin_dashboard_status"
PAYLOAD_KEY = "coin_dashboard_payload"
#: The run's serialized ``TickSeries`` (Phase 20, Step 4), kept beside the
#: payload rather than in it; ``None`` when the runner returned only a payload.
TICK_SERIES_KEY = "coin_dashboard_tick_series"
ERROR_KEY = "coin_dashboard_error"

SEED_KEY = "coin_dashboard_seed"
SEED_OVERRIDE_KEY = "coin_dashboard_seed_override"

_NO_SCENARIO = "none"

#: Every section of the report, as the heading it is rendered under and
#: the payload key it reads. The whole report is rendered as of Step 6, so
#: this is a manifest rather than a list of things still to come.
REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Market summary", "market"),
    ("Traders", "traders"),
    ("Whales", "whale_activity"),
    ("Events", "event_windows"),
    ("Psychology", "psychology_market"),
    ("Manipulation", "manipulation"),
    ("Market regimes", "regimes"),
)


class RunStatus(str, Enum):
    """Where the dashboard is in the run cycle."""

    EMPTY = "empty"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


def render_dashboard(
    *, runner: Callable[..., DashboardPayload | DashboardRun] = run_dashboard_simulation
) -> None:
    """Render the whole dashboard into the current Streamlit container.

    ``runner`` is the simulation entry point, injected so tests can drive
    the failure path; it defaults to ``dashboard.data.run_dashboard_simulation``
    (Phase 20, Step 4). A runner may return a ``DashboardRun`` (payload and
    tick series) or only a ``DashboardPayload``, which then has no tick-level
    views.
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
        _render_results(state[PAYLOAD_KEY], state[TICK_SERIES_KEY])
    else:
        _render_empty()


# --- state ---------------------------------------------------------------------------------------------


def _init_state(state: MutableMapping[str, Any]) -> None:
    state.setdefault(STATUS_KEY, RunStatus.EMPTY)
    state.setdefault(PAYLOAD_KEY, None)
    state.setdefault(TICK_SERIES_KEY, None)
    state.setdefault(ERROR_KEY, None)


def _request_run() -> None:
    """Button callback: mark a run as requested and drop the old result.

    Runs before the rerun that does the work, so the dashboard shows
    ``RUNNING_MESSAGE`` instead of the previous run's figures while the
    simulation is in progress.
    """
    st.session_state[STATUS_KEY] = RunStatus.RUNNING
    st.session_state[PAYLOAD_KEY] = None
    st.session_state[TICK_SERIES_KEY] = None
    st.session_state[ERROR_KEY] = None


def _execute(
    state: MutableMapping[str, Any], runner: Callable[..., DashboardPayload | DashboardRun]
) -> None:
    """Run one simulation and store its serialized payload (and tick
    series, when the runner returns one), or the error.

    A failure is reported, never fabricated around: the payload and tick
    series stay ``None`` so no stale or invented figures are shown.
    """
    try:
        result = runner(_params_from_widgets(state))
        if isinstance(result, DashboardRun):
            payload, tick_series = payload_to_dict(result.payload), tick_series_to_dict(result.tick_series)
        else:
            payload, tick_series = payload_to_dict(result), None
        state[PAYLOAD_KEY] = payload
        state[TICK_SERIES_KEY] = tick_series
        state[ERROR_KEY] = None
        state[STATUS_KEY] = RunStatus.SUCCESS
    except Exception as exc:  # noqa: BLE001 - the UI reports any failure rather than crashing
        state[PAYLOAD_KEY] = None
        state[TICK_SERIES_KEY] = None
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
        random_seed=_seed_from_widgets(state),
    )


def _seed_from_widgets(state: MutableMapping[str, Any]) -> int | None:
    """The requested seed, or ``None`` for the configured one (Step 7).

    The number is read only when the override is on, so a seed left in
    the control from an earlier request cannot leak into a run the user
    turned the override back off for.
    """
    if not state.get(SEED_OVERRIDE_KEY, False):
        return None
    return int(state.get(SEED_KEY, configured_seed()))


# --- controls ------------------------------------------------------------------------------------------


def _render_controls() -> None:
    """The run controls — the same options ``scripts/simulate_coin.py``
    exposes, plus the seed it takes from configuration (Step 7), so a
    dashboard run is a CLI run."""
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

    _render_seed_control()

    st.button("Run simulation", key="coin_dashboard_run", on_click=_request_run)


def _render_seed_control() -> None:
    """The seed control (Step 7).

    Off by default, which is the configured seed and so the behavior
    every run had before Step 7. The number starts at the configured seed
    too, so turning the control on and running reproduces the same run
    rather than quietly switching to a different one; the input is
    disabled while the override is off, because its value is then unused.
    """
    left, right = st.columns(2)
    left.checkbox(
        "Set the random seed",
        key=SEED_OVERRIDE_KEY,
        help="Off uses the configured seed. On runs the same options against the seed you choose.",
    )
    right.number_input(
        "Random seed",
        min_value=MIN_SEED,
        max_value=MAX_SEED,
        value=configured_seed(),
        step=1,
        key=SEED_KEY,
        disabled=not st.session_state.get(SEED_OVERRIDE_KEY, False),
        help="The same seed and the same options always give the same run.",
    )


# --- states --------------------------------------------------------------------------------------------


def _render_empty() -> None:
    st.info(EMPTY_MESSAGE)


def _render_error(message: str | None) -> None:
    st.error(f"Simulation failed. {message or 'No details were reported.'}")
    st.caption("No results are shown for a failed run.")


def _render_results(payload: dict[str, Any] | None, tick_series: dict[str, Any] | None = None) -> None:
    """Every section, from one payload, then the tick-level views from the
    run's tick series (Phase 20, Step 4) — last, so no existing section or
    chart moves."""
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
    render_traders(report["traders"], symbol=simulation["coin_symbol"])
    render_whales(
        report["whale_activity"], symbol=simulation["coin_symbol"], simulation=simulation
    )
    render_events(report["event_windows"], symbol=simulation["coin_symbol"], simulation=simulation)
    render_psychology(
        report["psychology_market"], symbol=simulation["coin_symbol"], simulation=simulation
    )
    render_manipulation(
        report["manipulation"], symbol=simulation["coin_symbol"], simulation=simulation
    )
    render_regimes(report["regimes"], symbol=simulation["coin_symbol"], simulation=simulation)
    render_tick_views(tick_series, symbol=simulation["coin_symbol"])


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
