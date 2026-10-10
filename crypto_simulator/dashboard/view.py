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

**Batch panel** (Phase 20, Step 6). After every single-run view comes a
batch panel with its own run count and its own Run batch button. A batch
runs the configuration the controls describe through
``data.run_dashboard_batch`` (``run_batch`` + ``aggregate_batch``, capped at
``MAX_DASHBOARD_BATCH_RUNS``) and keeps only the serialized reduced batch
under ``BATCH_VIEW_KEY``, with its own status and error keys;
``batch_section.render_batch`` draws it. Each button reads and writes only
its own keys, so a batch leaves the single run's result on screen and a
single run leaves the batch's.

**Scenario comparison** (Phase 20, Step 7). Last comes a comparison panel:
multiselects for pricing modes, manipulation presets and market conditions
(every combination selected is one configuration), runs per configuration
and a shared base seed. The planned configurations, the total number of
simulations and anything that stops the comparison — AMM with whales on,
or more than ``MAX_COMPARISON_RUNS`` simulations — are shown before the Run
comparison button, which stays disabled until the plan is valid. Every
other control is held constant. ``data.run_dashboard_comparison`` keeps one
reduced batch per configuration under ``COMPARISON_VIEW_KEY``, with its own
status and error keys, and ``comparison_section.render_comparison`` draws
it; neither of the other panels' keys is touched.

**Navigation** (Phase 24, Step 3). The app shows this dashboard as one
page of a multipage app. Streamlit drops the state of any widget that is
not drawn on a run, so a visit to another page would otherwise reset the
run controls to their defaults while the last run's results stayed on
screen. ``retain_control_state`` keeps every run-configuration control
(``RUN_CONTROL_KEYS``) across such visits; the app calls it before each
page runs. The controls take their defaults from session state
(``_control_defaults``) rather than from widget arguments, so keeping their
values never collides with a widget default.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, MutableMapping

import streamlit as st

from crypto_simulator.dashboard.batch_section import SECTION_HEADING as BATCH_SECTION_HEADING
from crypto_simulator.dashboard.batch_section import render_batch
from crypto_simulator.dashboard.comparison_section import SECTION_HEADING as COMPARISON_SECTION_HEADING
from crypto_simulator.dashboard.comparison_section import render_comparison, render_comparison_plan
from crypto_simulator.dashboard.data import (
    COMPARISON_MARKET_CONDITIONS,
    COMPARISON_SCENARIOS,
    MARKET_CONDITION_LABELS,
    MAX_BATCH_RUNS,
    MAX_COMPARISON_RUNS,
    MAX_DASHBOARD_BATCH_RUNS,
    MAX_SEED,
    MAX_TICKS,
    MIN_BATCH_RUNS,
    MIN_SEED,
    PRICING_MODES,
    PRICING_MODE_LABELS,
    SCENARIO_LABELS,
    SCENARIOS,
    ComparisonConfiguration,
    DashboardBatch,
    DashboardPayload,
    DashboardRun,
    SimulationParams,
    ScenarioComparison,
    batch_to_dict,
    comparison_configurations,
    comparison_to_dict,
    configured_seed,
    payload_to_dict,
    plan_comparison,
    plan_to_dict,
    run_dashboard_batch,
    run_dashboard_comparison,
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
    "BATCH_ERROR_KEY",
    "BATCH_RUNNING_MESSAGE",
    "BATCH_RUNS_KEY",
    "BATCH_STATUS_KEY",
    "BATCH_VIEW_KEY",
    "COMPARISON_ERROR_KEY",
    "COMPARISON_MARKET_CONDITIONS_KEY",
    "COMPARISON_PRICING_MODES_KEY",
    "COMPARISON_RUNNING_MESSAGE",
    "COMPARISON_RUNS_KEY",
    "COMPARISON_SCENARIOS_KEY",
    "COMPARISON_SEED_KEY",
    "COMPARISON_STATUS_KEY",
    "COMPARISON_VIEW_KEY",
    "DEFAULT_BATCH_RUNS",
    "EMPTY_MESSAGE",
    "RUNNING_MESSAGE",
    "ERROR_KEY",
    "PAYLOAD_KEY",
    "SEED_KEY",
    "SEED_OVERRIDE_KEY",
    "STATUS_KEY",
    "TICK_SERIES_KEY",
    "RUN_CONTROL_KEYS",
    "RunStatus",
    "render_dashboard",
    "retain_control_state",
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

#: The batch panel's own state (Phase 20, Step 6), kept apart from the
#: single run's: the batch's ``RunStatus``, its serialized reduced result
#: (``data.batch_to_dict``) and its error. Neither Run button touches the
#: other's keys.
BATCH_STATUS_KEY = "coin_dashboard_batch_status"
BATCH_VIEW_KEY = "coin_dashboard_batch_view"
BATCH_ERROR_KEY = "coin_dashboard_batch_error"
BATCH_RUNS_KEY = "coin_dashboard_batch_runs"
DEFAULT_BATCH_RUNS = 20
BATCH_RUNNING_MESSAGE = "Running batch..."

#: The scenario-comparison panel's own state (Phase 20, Step 7), apart from
#: both the single run's and the batch panel's, and its own controls.
COMPARISON_STATUS_KEY = "coin_dashboard_comparison_status"
COMPARISON_VIEW_KEY = "coin_dashboard_comparison_view"
COMPARISON_ERROR_KEY = "coin_dashboard_comparison_error"
COMPARISON_PRICING_MODES_KEY = "coin_dashboard_compare_pricing_modes"
COMPARISON_SCENARIOS_KEY = "coin_dashboard_compare_scenarios"
COMPARISON_MARKET_CONDITIONS_KEY = "coin_dashboard_compare_market_conditions"
COMPARISON_RUNS_KEY = "coin_dashboard_compare_runs"
COMPARISON_SEED_KEY = "coin_dashboard_compare_seed"
DEFAULT_COMPARISON_RUNS = 20
COMPARISON_RUNNING_MESSAGE = "Running comparison..."

_NO_SCENARIO = "none"

#: Every widget whose value configures a run, batch or comparison — the
#: single-run controls, the batch size and the comparison controls. Their
#: values must survive a visit to another page (``retain_control_state``).
#: Display choices inside the result sections (a picked trader, a chart
#: window) are not run configuration and are left out.
RUN_CONTROL_KEYS: tuple[str, ...] = (
    "coin_dashboard_ticks",
    "coin_dashboard_pricing_mode",
    "coin_dashboard_scenario",
    "coin_dashboard_traders",
    "coin_dashboard_whales",
    "coin_dashboard_events",
    "coin_dashboard_random_events",
    "coin_dashboard_psychology",
    "coin_dashboard_whale_observation",
    SEED_OVERRIDE_KEY,
    SEED_KEY,
    BATCH_RUNS_KEY,
    COMPARISON_PRICING_MODES_KEY,
    COMPARISON_SCENARIOS_KEY,
    COMPARISON_MARKET_CONDITIONS_KEY,
    COMPARISON_RUNS_KEY,
    COMPARISON_SEED_KEY,
)

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
    *,
    runner: Callable[..., DashboardPayload | DashboardRun] = run_dashboard_simulation,
    batch_runner: Callable[[SimulationParams, int], DashboardBatch] = run_dashboard_batch,
    comparison_runner: Callable[..., ScenarioComparison] = run_dashboard_comparison,
) -> None:
    """Render the whole dashboard into the current Streamlit container.

    ``runner`` is the simulation entry point, injected so tests can drive
    the failure path; it defaults to ``dashboard.data.run_dashboard_simulation``
    (Phase 20, Step 4). A runner may return a ``DashboardRun`` (payload and
    tick series) or only a ``DashboardPayload``, which then has no tick-level
    views. ``batch_runner`` is the batch entry point (Phase 20, Step 6),
    injected the same way; it defaults to ``data.run_dashboard_batch``.
    ``comparison_runner`` is the scenario-comparison entry point (Step 7),
    defaulting to ``data.run_dashboard_comparison``.
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

    _render_batch_panel(state, batch_runner)
    _render_comparison_panel(state, comparison_runner)


# --- state ---------------------------------------------------------------------------------------------


def _control_defaults() -> dict[str, Any]:
    """The run controls' starting values — the same defaults the widgets
    always had, now held in session state so a kept value never collides
    with a widget default."""
    return {
        "coin_dashboard_ticks": 20,
        "coin_dashboard_pricing_mode": PRICING_MODES[0],
        "coin_dashboard_scenario": _NO_SCENARIO,
        "coin_dashboard_traders": True,
        "coin_dashboard_whales": True,
        "coin_dashboard_events": False,
        "coin_dashboard_random_events": False,
        "coin_dashboard_psychology": False,
        "coin_dashboard_whale_observation": False,
        SEED_OVERRIDE_KEY: False,
        SEED_KEY: configured_seed(),
        BATCH_RUNS_KEY: DEFAULT_BATCH_RUNS,
        COMPARISON_PRICING_MODES_KEY: [PRICING_MODES[0]],
        COMPARISON_SCENARIOS_KEY: [_NO_SCENARIO],
        COMPARISON_MARKET_CONDITIONS_KEY: [_NO_SCENARIO, "bull", "bear"],
        COMPARISON_RUNS_KEY: DEFAULT_COMPARISON_RUNS,
        COMPARISON_SEED_KEY: configured_seed(),
    }


def retain_control_state(state: MutableMapping[str, Any] | None = None) -> None:
    """Keep the run controls' values across a visit to another page.

    Streamlit forgets a widget's value once a run goes by without drawing
    it. Writing each held value back through session state — Streamlit's
    documented way to keep widget state between pages — marks it as set by
    the app, so it survives. Only keys already held are written: nothing is
    invented before the dashboard has been drawn once.
    """
    state = st.session_state if state is None else state
    for key in RUN_CONTROL_KEYS:
        if key in state:
            state[key] = state[key]


def _init_state(state: MutableMapping[str, Any]) -> None:
    for key, value in _control_defaults().items():
        state.setdefault(key, value)
    state.setdefault(STATUS_KEY, RunStatus.EMPTY)
    state.setdefault(PAYLOAD_KEY, None)
    state.setdefault(TICK_SERIES_KEY, None)
    state.setdefault(ERROR_KEY, None)
    state.setdefault(BATCH_STATUS_KEY, RunStatus.EMPTY)
    state.setdefault(BATCH_VIEW_KEY, None)
    state.setdefault(BATCH_ERROR_KEY, None)
    state.setdefault(COMPARISON_STATUS_KEY, RunStatus.EMPTY)
    state.setdefault(COMPARISON_VIEW_KEY, None)
    state.setdefault(COMPARISON_ERROR_KEY, None)


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
    left.number_input("Ticks", min_value=1, max_value=MAX_TICKS, step=1, key="coin_dashboard_ticks")
    middle.selectbox("Pricing mode", PRICING_MODES, key="coin_dashboard_pricing_mode")
    right.selectbox("Manipulation scenario", (_NO_SCENARIO, *SCENARIOS), key="coin_dashboard_scenario")

    toggles = st.columns(3)
    toggles[0].checkbox("Traders", key="coin_dashboard_traders")
    toggles[0].checkbox("Whales", key="coin_dashboard_whales")
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


# --- batch panel (Phase 20, Step 6) --------------------------------------------------------------------


def _render_batch_panel(
    state: MutableMapping[str, Any], batch_runner: Callable[[SimulationParams, int], DashboardBatch]
) -> None:
    """The batch controls, then the batch's work if one was requested,
    then its result. Drawn after every single-run view, whatever state the
    single run is in, and reading and writing only the batch keys."""
    st.markdown(BATCH_SECTION_HEADING)
    st.caption(
        "Runs the configuration set above many times, each run under its own seed derived from one "
        "base seed, and describes how the successful simulated runs were spread. The single-run "
        "results above are left as they are."
    )
    st.number_input(
        "Batch runs",
        min_value=MIN_BATCH_RUNS,
        max_value=MAX_DASHBOARD_BATCH_RUNS,
        step=1,
        key=BATCH_RUNS_KEY,
        help=(
            f"Dashboard batch limit: {MAX_DASHBOARD_BATCH_RUNS} runs, because a dashboard batch runs "
            f"while the page waits. The batch service itself allows up to {MAX_BATCH_RUNS} "
            "(scripts/simulate_coin.py --batch)."
        ),
    )
    st.caption(
        f"Dashboard batch limit: {MAX_DASHBOARD_BATCH_RUNS} runs per batch "
        f"(the batch service limit, used by the CLI, is {MAX_BATCH_RUNS})."
    )
    st.button("Run batch", key="coin_dashboard_run_batch", on_click=_request_batch)

    if state[BATCH_STATUS_KEY] is RunStatus.RUNNING:
        placeholder = st.empty()
        placeholder.info(BATCH_RUNNING_MESSAGE)
        _execute_batch(state, batch_runner)
        placeholder.empty()

    render_batch(state[BATCH_VIEW_KEY], error=state[BATCH_ERROR_KEY])


def _request_batch() -> None:
    """Batch button callback: mark a batch as requested and drop only the
    previous batch result. The single run's keys are not touched."""
    st.session_state[BATCH_STATUS_KEY] = RunStatus.RUNNING
    st.session_state[BATCH_VIEW_KEY] = None
    st.session_state[BATCH_ERROR_KEY] = None


def _execute_batch(
    state: MutableMapping[str, Any], batch_runner: Callable[[SimulationParams, int], DashboardBatch]
) -> None:
    """Run one batch of the current configuration and keep its serialized
    reduced result, or the error. Failed runs inside a batch are part of
    its result; this error is a batch that could not run at all."""
    try:
        batch = batch_runner(_params_from_widgets(state), int(state.get(BATCH_RUNS_KEY, DEFAULT_BATCH_RUNS)))
        state[BATCH_VIEW_KEY] = batch_to_dict(batch)
        state[BATCH_ERROR_KEY] = None
        state[BATCH_STATUS_KEY] = RunStatus.SUCCESS
    except Exception as exc:  # noqa: BLE001 - the UI reports any failure rather than crashing
        state[BATCH_VIEW_KEY] = None
        state[BATCH_ERROR_KEY] = f"{type(exc).__name__}: {exc}"
        state[BATCH_STATUS_KEY] = RunStatus.ERROR


# --- scenario comparison panel (Phase 20, Step 7) --------------------------------------------------------


def _none_to_widget(value: str | None) -> str:
    return _NO_SCENARIO if value is None else value


def _widget_to_none(value: str) -> str | None:
    return None if value == _NO_SCENARIO else value


def _comparison_selection(state: MutableMapping[str, Any]) -> tuple[ComparisonConfiguration, ...]:
    """The configurations the three multiselects describe."""
    return comparison_configurations(
        state.get(COMPARISON_PRICING_MODES_KEY, []),
        [_widget_to_none(value) for value in state.get(COMPARISON_SCENARIOS_KEY, [])],
        [_widget_to_none(value) for value in state.get(COMPARISON_MARKET_CONDITIONS_KEY, [])],
    )


def _render_comparison_panel(
    state: MutableMapping[str, Any], comparison_runner: Callable[..., ScenarioComparison]
) -> None:
    """The comparison controls and plan, then the comparison's work if one
    was requested, then its result. Reads and writes only comparison keys."""
    st.markdown(COMPARISON_SECTION_HEADING)
    st.caption(
        "Runs one batch per selected configuration — every combination of the pricing modes, "
        "manipulation scenarios and market conditions selected here — with every other run option "
        "above held constant and one shared base seed, and shows the batches side by side."
    )
    columns = st.columns(3)
    columns[0].multiselect(
        "Pricing modes", PRICING_MODES,
        format_func=lambda mode: f"{PRICING_MODE_LABELS[mode]} ({mode})", key=COMPARISON_PRICING_MODES_KEY,
    )
    columns[1].multiselect(
        "Manipulation scenarios", [_none_to_widget(v) for v in COMPARISON_SCENARIOS],
        format_func=lambda value: SCENARIO_LABELS[_widget_to_none(value)], key=COMPARISON_SCENARIOS_KEY,
    )
    columns[2].multiselect(
        "Market conditions", [_none_to_widget(v) for v in COMPARISON_MARKET_CONDITIONS],
        format_func=lambda value: MARKET_CONDITION_LABELS[_widget_to_none(value)],
        key=COMPARISON_MARKET_CONDITIONS_KEY,
        help="Neutral (no preset) is the default market configuration, not an unknown one.",
    )
    left, right = st.columns(2)
    left.number_input(
        "Runs per configuration", min_value=MIN_BATCH_RUNS, max_value=MAX_DASHBOARD_BATCH_RUNS,
        step=1, key=COMPARISON_RUNS_KEY,
        help=(
            f"At most {MAX_DASHBOARD_BATCH_RUNS} per configuration (the dashboard batch limit) and "
            f"{MAX_COMPARISON_RUNS} simulations in total (the dashboard comparison limit)."
        ),
    )
    right.number_input(
        "Shared base seed", min_value=MIN_SEED, max_value=MAX_SEED, step=1,
        key=COMPARISON_SEED_KEY,
        help="Every configuration's batch derives its run seeds from this one base seed.",
    )
    configurations = _comparison_selection(state)
    runs = int(state.get(COMPARISON_RUNS_KEY, DEFAULT_COMPARISON_RUNS))
    base_seed = int(state.get(COMPARISON_SEED_KEY, configured_seed()))
    plan = plan_comparison(_params_from_widgets(state), configurations, runs)
    render_comparison_plan(plan_to_dict(plan), base_seed=base_seed)
    st.caption(
        f"Dashboard comparison limit: {MAX_COMPARISON_RUNS} simulations in total and "
        f"{MAX_DASHBOARD_BATCH_RUNS} per configuration (the batch service limit, used by the CLI, is "
        f"{MAX_BATCH_RUNS} per batch)."
    )
    st.button(
        "Run comparison", key="coin_dashboard_run_comparison", on_click=_request_comparison,
        disabled=bool(plan.problems),
    )

    if state[COMPARISON_STATUS_KEY] is RunStatus.RUNNING:
        placeholder = st.empty()
        placeholder.info(COMPARISON_RUNNING_MESSAGE)
        _execute_comparison(state, comparison_runner, configurations, runs, base_seed)
        placeholder.empty()

    render_comparison(state[COMPARISON_VIEW_KEY], error=state[COMPARISON_ERROR_KEY])


def _request_comparison() -> None:
    """Comparison button callback: mark a comparison as requested and drop
    only the previous comparison result."""
    st.session_state[COMPARISON_STATUS_KEY] = RunStatus.RUNNING
    st.session_state[COMPARISON_VIEW_KEY] = None
    st.session_state[COMPARISON_ERROR_KEY] = None


def _execute_comparison(
    state: MutableMapping[str, Any],
    comparison_runner: Callable[..., ScenarioComparison],
    configurations: tuple[ComparisonConfiguration, ...],
    runs: int,
    base_seed: int,
) -> None:
    """Run the planned comparison and keep its serialized reduced result,
    or the error. The runner re-checks the plan, so a comparison that is
    not valid never runs."""
    try:
        comparison = comparison_runner(
            _params_from_widgets(state), configurations, runs, base_seed=base_seed
        )
        state[COMPARISON_VIEW_KEY] = comparison_to_dict(comparison)
        state[COMPARISON_ERROR_KEY] = None
        state[COMPARISON_STATUS_KEY] = RunStatus.SUCCESS
    except Exception as exc:  # noqa: BLE001 - the UI reports any failure rather than crashing
        state[COMPARISON_VIEW_KEY] = None
        state[COMPARISON_ERROR_KEY] = f"{type(exc).__name__}: {exc}"
        state[COMPARISON_STATUS_KEY] = RunStatus.ERROR
