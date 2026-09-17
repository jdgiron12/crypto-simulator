"""The dashboard data interface (Phase 10, Step 1).

What matters here: parameters are a validated closed set, one request
runs one simulation and builds one report, the payload carries the
report's own values (never recomputed ones) plus the simulator's own
recorded price path, and the same request always gives the same payload.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from crypto_simulator.analytics.report import SimulationReport
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import PricingMode
from crypto_simulator.dashboard import data as data_module
from crypto_simulator.dashboard.data import (
    MAX_TICKS,
    PRICING_MODES,
    SCENARIOS,
    DashboardPayload,
    SimulationParams,
    payload_to_dict,
    run_simulation,
)
from crypto_simulator.services.coin_simulation import MANIPULATION_SCENARIOS

from tests.dashboard.conftest import FULL_PARAMS


# --- parameters ------------------------------------------------------------------------------------------


def test_defaults_match_the_cli_defaults():
    params = SimulationParams()
    assert params.ticks == 20
    assert params.pricing_mode == PricingMode.RANDOM_WALK.value
    assert (params.include_traders, params.include_whales) == (True, True)
    assert not any(
        (params.events, params.random_events, params.psychology, params.whale_observation)
    )
    assert params.scenario is None


def test_the_option_sets_come_from_the_simulator():
    assert PRICING_MODES == tuple(mode.value for mode in PricingMode)
    assert SCENARIOS == tuple(sorted(MANIPULATION_SCENARIOS))


@pytest.mark.parametrize("ticks", [0, -1, MAX_TICKS + 1])
def test_ticks_outside_the_bound_are_rejected(ticks):
    with pytest.raises(ValueError, match="ticks must be"):
        SimulationParams(ticks=ticks)


@pytest.mark.parametrize("ticks", [1.0, "20", True, None])
def test_non_integer_ticks_are_rejected(ticks):
    with pytest.raises(ValueError, match="ticks must be"):
        SimulationParams(ticks=ticks)


def test_unknown_pricing_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown pricing_mode"):
        SimulationParams(pricing_mode="amm; rm -rf /")


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError, match="unknown scenario"):
        SimulationParams(scenario="__import__")


def test_non_boolean_flags_are_rejected():
    with pytest.raises(ValueError, match="psychology must be"):
        SimulationParams(psychology="yes")


def test_params_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        SimulationParams().ticks = 5


# --- running ---------------------------------------------------------------------------------------------


def test_run_returns_a_payload_for_the_requested_run(payload):
    assert isinstance(payload, DashboardPayload)
    assert isinstance(payload.report, SimulationReport)
    assert payload.simulation.params == FULL_PARAMS
    assert payload.simulation.requested_ticks == FULL_PARAMS.ticks
    assert payload.simulation.completed_ticks == FULL_PARAMS.ticks
    assert payload.report.ticks == FULL_PARAMS.ticks


def test_metadata_comes_from_the_run(payload):
    settings = get_settings()
    meta = payload.simulation
    assert (meta.coin_symbol, meta.coin_name) == (settings.coin.symbol, settings.coin.name)
    assert meta.initial_supply == settings.coin.initial_supply
    assert meta.starting_price == settings.coin.starting_price
    assert meta.pricing_mode == PricingMode.RANDOM_WALK.value
    assert meta.random_seed == settings.simulation.random_seed


def test_price_series_is_the_recorded_path_not_a_derived_one(payload):
    series = payload.price_series
    assert [point.tick for point in series] == list(range(1, FULL_PARAMS.ticks + 1))
    assert series[-1].price == payload.report.market.close_price
    assert series[-1].market_cap == series[-1].price * payload.simulation.initial_supply
    assert all(point.volume >= 0 for point in series)


def test_price_series_carries_no_wall_clock_timestamp(payload):
    assert "timestamp" not in {field.name for field in dataclasses.fields(payload.price_series[0])}


def test_run_uses_the_options_it_is_given():
    params = SimulationParams(ticks=5, pricing_mode="amm", include_whales=False,
                              scenario="wash_trading")
    payload = run_simulation(params)
    assert payload.simulation.pricing_mode == "amm"
    assert payload.report.market.pool_activity is not None
    assert payload.report.manipulation.wash is not None


def test_a_rejected_combination_raises_from_the_simulator():
    """AMM mode does not support whales; the data layer does not soften
    that into a partial result."""
    with pytest.raises(ValueError, match="Whales are not supported"):
        run_simulation(SimulationParams(ticks=3, pricing_mode="amm", include_whales=True))


def test_no_simulation_runs_until_asked(monkeypatch):
    calls = []

    def builder(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop here")

    with pytest.raises(RuntimeError):
        run_simulation(SimulationParams(ticks=3), builder=builder)
    assert len(calls) == 1
    assert calls[0]["pricing_mode"] == PricingMode.RANDOM_WALK.value


# --- determinism and the serialized contract -------------------------------------------------------------


def test_the_same_request_gives_the_same_payload():
    first = payload_to_dict(run_simulation(SimulationParams(ticks=12, events=True)))
    second = payload_to_dict(run_simulation(SimulationParams(ticks=12, events=True)))
    assert first == second


def test_simulation_id_is_derived_from_the_request_only():
    one = run_simulation(SimulationParams(ticks=7)).simulation.simulation_id
    again = run_simulation(SimulationParams(ticks=7)).simulation.simulation_id
    other = run_simulation(SimulationParams(ticks=8)).simulation.simulation_id
    assert one == again != other


def test_payload_dict_has_the_three_top_level_parts(payload_dict):
    assert set(payload_dict) == {"simulation", "report", "price_series"}
    assert payload_dict["simulation"]["completed_ticks"] == FULL_PARAMS.ticks
    assert len(payload_dict["price_series"]) == FULL_PARAMS.ticks


def test_payload_dict_is_valid_json(payload_dict):
    assert json.loads(json.dumps(payload_dict, allow_nan=False)) == payload_dict


def test_payload_dict_rejects_anything_else():
    with pytest.raises(TypeError, match="DashboardPayload"):
        payload_to_dict({"simulation": {}})


# --- the layer stays an observer -------------------------------------------------------------------------


def test_nothing_in_the_simulator_imports_the_dashboard():
    root = Path(data_module.__file__).resolve().parents[1]
    for package in ("core", "services", "analytics", "models", "data", "config"):
        for path in (root / package).rglob("*.py"):
            assert "crypto_simulator.dashboard" not in path.read_text(), path


def test_the_data_layer_computes_no_analytics():
    """Its only arithmetic is the tick bound; every figure is the
    report's or the tick's own."""
    source = Path(data_module.__file__).read_text()
    for banned in ("analyze_market", "analyze_traders", "sum(", "fsum", "statistics"):
        assert banned not in source
