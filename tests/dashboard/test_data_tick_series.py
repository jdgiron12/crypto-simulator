"""The dashboard's tick-series path (Phase 20, Step 3).

``run_dashboard_simulation`` runs the simulation once and returns the same
payload ``run_simulation`` returns plus the run's ``TickSeries``. The tick
series is ephemeral: it is never part of the payload, never saved, and a
saved run has none. Batch execution keeps returning plain payloads.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pytest

from crypto_simulator.analytics.tick_series import COLUMNS, TickSeries
from crypto_simulator.data import CoinRunRepository, connect, init_db
from crypto_simulator.dashboard import data as data_module
from crypto_simulator.dashboard.data import (
    TICK_SERIES_UNAVAILABLE_MESSAGE,
    DashboardPayload,
    DashboardRun,
    SimulationParams,
    payload_to_dict,
    run_dashboard_simulation,
    run_simulation,
    tick_series_to_dict,
)
from crypto_simulator.services.batch import run_batch
from crypto_simulator.services.coin_simulation import build_coin_simulator

PARAMS = [
    SimulationParams(ticks=25, random_seed=48291),
    SimulationParams(ticks=25, random_seed=7, psychology=True, events=True, random_events=True,
                     scenario="pump_and_dump"),
    SimulationParams(ticks=25, random_seed=11, pricing_mode="amm", include_whales=False, psychology=True,
                     events=True, scenario="wash_trading"),
]
IDS = ["rw-default", "rw-psychology-events-pump", "amm-psychology-events-wash"]


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


@pytest.mark.parametrize("params", PARAMS, ids=IDS)
def test_the_run_carries_the_same_payload_run_simulation_returns(params):
    run = run_dashboard_simulation(params)
    assert isinstance(run, DashboardRun)
    assert isinstance(run.payload, DashboardPayload)
    assert isinstance(run.tick_series, TickSeries)
    assert _dumps(payload_to_dict(run.payload)) == _dumps(payload_to_dict(run_simulation(params)))


@pytest.mark.parametrize("params", PARAMS, ids=IDS)
def test_the_tick_series_describes_the_payloads_run(params):
    run = run_dashboard_simulation(params)
    series, payload = run.tick_series, run.payload
    assert series.rows == payload.simulation.completed_ticks
    assert series.data["tick"] == tuple(p.tick for p in payload.price_series)
    assert series.data["price"] == tuple(p.price for p in payload.price_series)
    assert series.data["volume"] == tuple(p.volume for p in payload.price_series)
    assert series.data["market_cap"] == tuple(p.market_cap for p in payload.price_series)


def test_the_payload_keeps_exactly_its_three_keys():
    run = run_dashboard_simulation(PARAMS[0])
    assert set(payload_to_dict(run.payload)) == {"simulation", "report", "price_series"}
    assert [f.name for f in dataclasses.fields(DashboardPayload)] == ["simulation", "report", "price_series"]


def test_the_simulation_runs_exactly_once():
    calls = []

    def counting_builder(*args, **kwargs):
        sim = build_coin_simulator(*args, **kwargs)
        original = sim.run

        def run(ticks):
            calls.append(ticks)
            return original(ticks)

        sim.run = run
        return sim

    run_dashboard_simulation(PARAMS[0], builder=counting_builder)
    assert calls == [PARAMS[0].ticks]


def test_the_population_is_the_built_simulators():
    run = run_dashboard_simulation(PARAMS[1])
    sim = build_coin_simulator(
        data_module._with_seed_override(
            data_module._with_event_overrides(
                data_module._with_market_condition(data_module.get_settings(), PARAMS[1]), PARAMS[1]),
            PARAMS[1]),
        scenario=PARAMS[1].scenario, psychology=PARAMS[1].psychology,
    )
    expected: dict[str, int] = {}
    for trader in sim.traders:
        expected[trader.strategy_name] = expected.get(trader.strategy_name, 0) + 1
    assert dict(run.tick_series.population) == dict(sorted(expected.items()))
    assert run.tick_series.whale_count == len(sim.whales)


def test_builder_errors_still_propagate_unchanged():
    def failing_builder(*args, **kwargs):
        raise ValueError("unsupported combination")

    with pytest.raises(ValueError, match="unsupported combination"):
        run_dashboard_simulation(PARAMS[0], builder=failing_builder)


# --- serialization -------------------------------------------------------------------------------------


@pytest.mark.parametrize("params", PARAMS, ids=IDS)
def test_serialization_is_columnar_json_safe_and_deterministic(params):
    first = tick_series_to_dict(run_dashboard_simulation(params).tick_series)
    second = tick_series_to_dict(run_dashboard_simulation(params).tick_series)
    assert _dumps(first) == _dumps(second)
    assert set(first) == {"columns", "rows", "data", "classes", "population", "whale_count"}
    assert first["columns"] == list(COLUMNS)
    assert set(first["data"]) == set(COLUMNS)
    assert all(len(values) == first["rows"] for values in first["data"].values())
    assert list(first["classes"]) == sorted(first["classes"])
    json.loads(_dumps(first))  # strict JSON: no NaN or infinity anywhere


def test_none_serializes_as_null_and_enums_as_their_values():
    params = SimulationParams(ticks=25, random_seed=7, events=True)
    as_dict = tick_series_to_dict(run_dashboard_simulation(params).tick_series)
    assert set(as_dict["data"]["fear"]) == {None}  # psychology off
    assert set(as_dict["data"]["pool_spot_price"]) == {None}  # random-walk mode
    live = [event for row in as_dict["data"]["event_live"] for event in row]
    assert live, "the demo events should be live on some tick"
    assert all(isinstance(event["phase"], str) for event in live)
    assert set(live[0]) == {"event_id", "category", "phase", "intensity"}


def test_amm_decimals_arrive_as_floats():
    as_dict = tick_series_to_dict(run_dashboard_simulation(PARAMS[2]).tick_series)
    assert all(isinstance(v, float) for v in as_dict["data"]["pool_coin_reserve"])
    assert all(isinstance(v, int) for v in as_dict["data"]["pool_swap_count"])


def test_a_non_finite_value_is_rejected():
    series = run_dashboard_simulation(PARAMS[0]).tick_series
    data = dict(series.data)
    data["price"] = (math.nan,) + data["price"][1:]
    with pytest.raises(ValueError):
        tick_series_to_dict(dataclasses.replace(series, data=data))


def test_only_a_tick_series_is_accepted():
    with pytest.raises(TypeError):
        tick_series_to_dict(run_simulation(PARAMS[0]))


# --- persistence and batch are untouched ----------------------------------------------------------------


def test_a_saved_run_has_no_tick_series_and_is_unchanged():
    conn = connect(":memory:")
    init_db(conn)
    try:
        repo = CoinRunRepository(conn)
        run = run_dashboard_simulation(PARAMS[0])
        payload = payload_to_dict(run.payload)
        loaded = repo.load(repo.save(payload))
        assert loaded == payload
        assert "tick_series" not in loaded
    finally:
        conn.close()
    assert TICK_SERIES_UNAVAILABLE_MESSAGE == "Tick-level data was not recorded for this saved run."


def test_persistence_code_does_not_know_about_tick_series():
    import crypto_simulator.data.coin_runs as coin_runs

    assert "tick_series" not in Path(coin_runs.__file__).read_text()


def test_batch_runs_keep_returning_plain_payloads():
    result = run_batch(SimulationParams(ticks=5), 2, runner=run_simulation, base_seed=3)
    assert all(isinstance(run.payload, DashboardPayload) for run in result.runs)
    assert not any(isinstance(run.payload, DashboardRun) for run in result.runs)
