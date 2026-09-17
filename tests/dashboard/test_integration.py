"""The dashboard path against the simulator itself (Phase 10, Step 1).

A dashboard run must be the run the CLI would have done, and the figures
it shows must be the figures the analytics produce for that run. So these
tests build the same simulation by hand — the way
``scripts/simulate_coin.py`` does — and require bit-for-bit agreement:
the same price path, the same ``SimulationReport``, and the same rendered
report. If the dashboard ever computed a figure of its own, or nudged the
simulation, this is where it would show.
"""

from __future__ import annotations

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
