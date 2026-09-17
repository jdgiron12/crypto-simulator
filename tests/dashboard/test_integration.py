"""The dashboard path against the simulator itself (Phase 10).

A dashboard run must be the run the CLI would have done, and the figures
it shows must be the figures the analytics produce for that run. So these
tests build the same simulation by hand — the way
``scripts/simulate_coin.py`` does — and require bit-for-bit agreement:
the same price path, the same ``SimulationReport``, and the same rendered
report. If the dashboard ever computed a figure of its own, or nudged the
simulation, this is where it would show.

The Step 2 cases at the end go the whole way through the real UI: they set
the controls, press Run, and compare the market figures on screen with
``analyze_market``'s own values for the same recorded ticks, in both
pricing modes.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from crypto_simulator.analytics import analyze_market, build_report, render_report
from crypto_simulator.config import get_settings
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.services.coin_simulation import (
    DEMO_EVENTS,
    DEMO_RANDOM_EVENT_PROBABILITY,
    build_coin_simulator,
)

CASES = [
    SimulationParams(ticks=30),
    SimulationParams(ticks=25, pricing_mode="amm", include_whales=False),
    SimulationParams(ticks=40, events=True, psychology=True, whale_observation=True),
    SimulationParams(ticks=30, pricing_mode="amm", include_whales=False, scenario="pump_and_dump"),
    SimulationParams(ticks=30, events=True, random_events=True),
    SimulationParams(ticks=20, include_traders=False),
]


def _balances(sim):
    return {t.trader_id: (t.wallet.cash, t.wallet.coins) for t in sim.traders}


def _reference(params: SimulationParams):
    """The same run, built the way the CLI builds it."""
    settings = get_settings()
    events = settings.coin.events
    if params.events:
        events = replace(events, scheduled=list(DEMO_EVENTS))
    if params.random_events:
        events = replace(events, random=replace(events.random, probability=DEMO_RANDOM_EVENT_PROBABILITY))
    if events is not settings.coin.events:
        settings = replace(settings, coin=replace(settings.coin, events=events))
    sim = build_coin_simulator(
        settings,
        include_traders=params.include_traders,
        include_whales=params.include_whales,
        pricing_mode=params.pricing_mode,
        scenario=params.scenario,
        psychology=params.psychology,
        whale_observation=params.whale_observation,
    )
    start_balances = _balances(sim)
    ticks = sim.run(params.ticks)
    timeline = random_ids = None
    if sim.events is not None:
        timeline = sim.events.events
        generated = sim.event_generator.generated_events if sim.event_generator else ()
        random_ids = [event.event_id for event in generated]
    report = build_report(
        ticks,
        events=timeline,
        random_event_ids=random_ids,
        initial_price=sim.coin.starting_price,
        total_supply=sim.coin.initial_supply,
        start_balances=start_balances,
        end_balances=_balances(sim),
    )
    return sim, ticks, report


@pytest.mark.parametrize("params", CASES, ids=lambda p: f"{p.pricing_mode}-{p.ticks}-{p.scenario}")
def test_the_dashboard_runs_the_simulation_the_cli_would_have_run(params):
    payload = run_simulation(params)
    _, ticks, _ = _reference(params)
    assert [point.tick for point in payload.price_series] == [tick.tick for tick in ticks]
    assert [point.price for point in payload.price_series] == [tick.price for tick in ticks]
    assert [point.volume for point in payload.price_series] == [tick.volume for tick in ticks]
    assert [point.market_cap for point in payload.price_series] == [tick.market_cap for tick in ticks]


@pytest.mark.parametrize("params", CASES, ids=lambda p: f"{p.pricing_mode}-{p.ticks}-{p.scenario}")
def test_the_payload_report_is_the_report_the_analytics_produce(params):
    payload = run_simulation(params)
    _, _, expected = _reference(params)
    assert payload.report == expected


@pytest.mark.parametrize("params", CASES, ids=lambda p: f"{p.pricing_mode}-{p.ticks}-{p.scenario}")
def test_the_payload_renders_to_the_cli_report(params):
    """The same report the ``--report`` flag prints, character for
    character."""
    payload = run_simulation(params)
    _, _, expected = _reference(params)
    assert render_report(payload.report) == render_report(expected)


def test_displayed_market_figures_come_from_the_analytics():
    """The market values the dashboard shows are ``analyze_market``'s own,
    over the same recorded ticks."""
    params = SimulationParams(ticks=30, events=True)
    payload = run_simulation(params)
    _, ticks, _ = _reference(params)
    settings = get_settings()
    market = analyze_market(
        ticks, initial_price=settings.coin.starting_price, total_supply=settings.coin.initial_supply
    )
    shown = payload_to_dict(payload)["report"]["market"]
    assert shown["close_price"] == market.close_price == ticks[-1].price
    assert shown["open_price"] == market.open_price
    assert shown["cumulative_return"] == market.cumulative_return
    assert shown["volume_breakdown"]["total_volume"] == market.volume_breakdown.total_volume
    assert (shown["first_tick"], shown["last_tick"]) == (market.first_tick, market.last_tick)


def test_two_dashboard_runs_leave_the_simulator_unchanged():
    """Running through the dashboard twice gives the same run both times:
    the dashboard holds no state the simulator can see."""
    params = SimulationParams(ticks=25, events=True, psychology=True)
    first = payload_to_dict(run_simulation(params))
    _reference(params)  # an unrelated run in between
    second = payload_to_dict(run_simulation(params))
    assert first == second


def test_a_dashboard_run_does_not_touch_the_application_settings():
    params = SimulationParams(ticks=5, events=True, random_events=True)
    before = get_settings()
    run_simulation(params)
    after = get_settings()
    assert after is before
    assert after.coin.events == before.coin.events
    assert after.coin.events.scheduled == []


# --- the market dashboard, end to end (Phase 10, Step 2) -------------------------------------------------


def _dashboard_app(runner=None):
    """The whole dashboard, as AppTest runs it."""
    from crypto_simulator.dashboard.data import run_simulation
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard(runner=runner or run_simulation)


def _run_dashboard(params: SimulationParams):
    """Drive the real UI: set the controls, press Run, return what is on
    screen together with the run the simulator would have produced."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_dashboard_app, kwargs={"runner": None}, default_timeout=90).run()
    at.number_input(key="coin_dashboard_ticks").set_value(params.ticks)
    at.selectbox(key="coin_dashboard_pricing_mode").set_value(params.pricing_mode)
    at.checkbox(key="coin_dashboard_traders").set_value(params.include_traders)
    at.checkbox(key="coin_dashboard_whales").set_value(params.include_whales)
    at.checkbox(key="coin_dashboard_events").set_value(params.events)
    at.checkbox(key="coin_dashboard_psychology").set_value(params.psychology)
    at.button(key="coin_dashboard_run").click().run()
    return at


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=25, events=True),
        SimulationParams(ticks=25, pricing_mode="amm", include_whales=False),
    ],
    ids=["random_walk", "amm"],
)
def test_the_market_dashboard_displays_the_analytics_figures(params):
    """simulation -> build_report -> payload -> market dashboard, checked
    against ``analyze_market`` over the same recorded ticks."""
    at = _run_dashboard(params)
    assert not at.exception

    _, ticks, _ = _reference(params)
    settings = get_settings()
    market = analyze_market(
        ticks, initial_price=settings.coin.starting_price, total_supply=settings.coin.initial_supply
    )
    shown = {metric.label: metric.value for metric in at.metric}
    assert shown["Close price"] == format(market.close_price, ",.4f")
    assert shown["Open price"] == format(market.open_price, ",.4f")
    assert shown["High"] == format(market.high_price, ",.4f")
    assert shown["Low"] == format(market.low_price, ",.4f")
    assert shown["Return"] == format(market.cumulative_return, "+.2%")
    assert shown["Total volume"] == format(market.volume_breakdown.total_volume, ",.0f")
    assert shown["Volatility (per tick)"] == format(market.volatility, ",.4f")
    assert shown["Max drawdown"] == format(market.max_drawdown, ".2%")
    assert shown["Turnover"] == format(market.turnover, ".2%")

    statistics = at.table[-1].value
    rows = dict(zip(statistics.index, statistics["Value"]))
    assert rows["Tick range"] == f"{market.first_tick}-{market.last_tick}"
    assert rows["Trader VWAP"] == format(market.trader_vwap, ",.4f")
    assert rows["Realized volatility"] == format(market.realized_volatility, ",.4f")


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=20, events=True),
        SimulationParams(ticks=20, pricing_mode="amm", include_whales=False),
    ],
    ids=["random_walk", "amm"],
)
def test_the_dashboard_chart_plots_the_simulated_price_path(params):
    at = _run_dashboard(params)
    _, ticks, _ = _reference(params)
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert spec["data"][0]["x"] == [tick.tick for tick in ticks]
    assert spec["data"][0]["y"] == [tick.price for tick in ticks]


def test_a_second_run_replaces_the_first_runs_market_figures():
    first = _run_dashboard(SimulationParams(ticks=10))
    shown_first = {metric.label: metric.value for metric in first.metric}

    first.number_input(key="coin_dashboard_ticks").set_value(40)
    first.button(key="coin_dashboard_run").click().run()
    shown_second = {metric.label: metric.value for metric in first.metric}

    _, ticks, _ = _reference(SimulationParams(ticks=40))
    settings = get_settings()
    market = analyze_market(
        ticks, initial_price=settings.coin.starting_price, total_supply=settings.coin.initial_supply
    )
    assert shown_second["Close price"] == format(market.close_price, ",.4f")
    assert shown_second["Ticks analysed"] == "40"
    assert shown_first["Close price"] != shown_second["Close price"]


def test_a_failed_run_removes_the_market_tables():
    at = _run_dashboard(SimulationParams(ticks=10))
    assert at.table.len > 0

    at.selectbox(key="coin_dashboard_pricing_mode").set_value("amm")  # AMM rejects whales
    at.button(key="coin_dashboard_run").click().run()
    assert at.table.len == 0
    assert at.metric.len == 0
    assert "Whales are not supported" in at.error[0].value
