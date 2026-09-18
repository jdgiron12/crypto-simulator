"""The dashboard data interface (Phase 10, Steps 1 and 7).

What matters here: parameters are a validated closed set, one request
runs one simulation and builds one report, the payload carries the
report's own values (never recomputed ones) plus the simulator's own
recorded price path, and the same request always gives the same payload.

Step 7 adds the seed to that closed set. Its tests are at the end: a
defaulted request must still be the configured-seed run it always was, a
requested seed must be the seed the run actually used, and the seed must
reach the run through the settings the builder already reads rather than
through any new path into the simulator.
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
    MAX_SEED,
    MAX_TICKS,
    MIN_SEED,
    PRICING_MODES,
    SCENARIOS,
    DashboardPayload,
    SimulationParams,
    configured_seed,
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


# --- the requested seed (Phase 10, Step 7) ---------------------------------------------------------------


def test_a_default_request_names_no_seed():
    """Step 7 is opt-in: the default request is the pre-Step-7 request."""
    assert SimulationParams().random_seed is None


def test_a_request_without_a_seed_runs_on_the_configured_seed():
    payload = run_simulation(SimulationParams(ticks=4))
    assert payload.simulation.random_seed == configured_seed()


def test_configured_seed_is_the_settings_seed():
    assert configured_seed() == get_settings().simulation.random_seed


def test_a_requested_seed_is_the_seed_the_run_reports():
    payload = run_simulation(SimulationParams(ticks=4, random_seed=123))
    assert payload.simulation.random_seed == 123
    assert payload.simulation.params.random_seed == 123


def test_the_same_seed_reproduces_the_whole_payload():
    first = payload_to_dict(run_simulation(SimulationParams(ticks=10, random_seed=99)))
    second = payload_to_dict(run_simulation(SimulationParams(ticks=10, random_seed=99)))
    assert first == second


def test_a_different_seed_gives_a_different_run():
    """The point of the control: the same options, another sample path."""
    one = run_simulation(SimulationParams(ticks=10, random_seed=1))
    two = run_simulation(SimulationParams(ticks=10, random_seed=2))
    assert one.price_series != two.price_series


def test_requesting_the_configured_seed_matches_requesting_no_seed():
    """Naming the configured seed is the configured run, not another one."""
    implicit = payload_to_dict(run_simulation(SimulationParams(ticks=8)))
    explicit = payload_to_dict(run_simulation(SimulationParams(ticks=8, random_seed=configured_seed())))
    assert implicit["price_series"] == explicit["price_series"]
    assert implicit["report"] == explicit["report"]


def test_simulation_id_follows_the_seed():
    same = run_simulation(SimulationParams(ticks=6, random_seed=5)).simulation.simulation_id
    again = run_simulation(SimulationParams(ticks=6, random_seed=5)).simulation.simulation_id
    other = run_simulation(SimulationParams(ticks=6, random_seed=6)).simulation.simulation_id
    assert same == again != other


@pytest.mark.parametrize("seed", [MIN_SEED, MAX_SEED, 42])
def test_seeds_inside_the_bounds_are_accepted(seed):
    assert SimulationParams(random_seed=seed).random_seed == seed


@pytest.mark.parametrize("seed", [-1, MIN_SEED - 1, MAX_SEED + 1])
def test_seeds_outside_the_bounds_are_rejected(seed):
    with pytest.raises(ValueError, match="random_seed must be between"):
        SimulationParams(random_seed=seed)


@pytest.mark.parametrize("seed", [1.0, "42", True, object()])
def test_non_integer_seeds_are_rejected(seed):
    with pytest.raises(ValueError, match="random_seed must be an integer"):
        SimulationParams(random_seed=seed)


def test_the_seed_reaches_the_run_through_the_settings_not_a_new_argument():
    """The seed is a selected simulator input, not a new one: the builder
    is called with the arguments it always was, and the seed arrives in
    the settings it already reads."""
    calls = []

    def builder(settings, **kwargs):
        calls.append((settings, kwargs))
        raise RuntimeError("stop here")

    with pytest.raises(RuntimeError):
        run_simulation(SimulationParams(ticks=3, random_seed=77), builder=builder)
    settings, kwargs = calls[0]
    assert settings.simulation.random_seed == 77
    assert set(kwargs) == {
        "include_traders", "include_whales", "pricing_mode", "scenario",
        "psychology", "whale_observation",
    }


def test_an_unseeded_request_passes_the_settings_through_untouched():
    """``None`` must not rebuild the settings: the builder receives the
    very object the caller passed, so the defaulted path is unchanged."""
    calls = []
    given = get_settings()

    def builder(settings, **kwargs):
        calls.append(settings)
        raise RuntimeError("stop here")

    with pytest.raises(RuntimeError):
        run_simulation(SimulationParams(ticks=3), settings=given, builder=builder)
    assert calls[0] is given


def test_a_seeded_run_does_not_touch_the_application_settings():
    before = get_settings()
    run_simulation(SimulationParams(ticks=4, random_seed=321))
    after = get_settings()
    assert after is before
    assert after.simulation.random_seed == before.simulation.random_seed


def test_the_seed_is_carried_into_the_serialized_payload():
    payload = payload_to_dict(run_simulation(SimulationParams(ticks=4, random_seed=8)))
    assert payload["simulation"]["random_seed"] == 8
    assert payload["simulation"]["params"]["random_seed"] == 8


def test_an_unseeded_payload_reports_the_configured_seed_not_null():
    """``random_seed`` in the payload is the seed the run used, so it is
    never ``null`` just because the request named none."""
    payload = payload_to_dict(run_simulation(SimulationParams(ticks=4)))
    assert payload["simulation"]["params"]["random_seed"] is None
    assert payload["simulation"]["random_seed"] == configured_seed()
