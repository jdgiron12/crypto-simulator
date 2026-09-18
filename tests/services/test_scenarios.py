"""Named simulation configurations, as a service (Phase 13).

What matters here: a saved scenario reloads as the same validated
request, a stored request is held to exactly the rules a typed-in one is,
and a scenario that this version cannot run is reported rather than
quietly turned into a different, valid one.

The equivalence tests are the point of the phase: running a loaded
scenario must give the run the original configuration gave.
"""

from __future__ import annotations

import pytest

from crypto_simulator.data.database import connect, init_db
from crypto_simulator.dashboard.data import payload_to_dict, run_simulation
from crypto_simulator.services.scenarios import (
    ScenarioNotFound,
    ScenarioService,
    params_from_dict,
    params_to_dict,
)
from crypto_simulator.services.simulation_params import MAX_TICKS, SimulationParams

PARAMS = SimulationParams(
    ticks=20,
    pricing_mode="amm",
    include_whales=False,
    scenario="pump_and_dump",
    events=True,
    psychology=True,
    random_seed=48291,
)


@pytest.fixture
def service():
    conn = connect(":memory:")
    init_db(conn)
    yield ScenarioService(conn)
    conn.close()


# --- round trip ------------------------------------------------------------------------------------------


def test_a_saved_scenario_loads_as_the_same_request(service):
    service.save("nightly", PARAMS)
    assert service.load("nightly") == PARAMS


def test_a_default_request_round_trips(service):
    service.save("plain", SimulationParams())
    assert service.load("plain") == SimulationParams()


def test_every_field_survives(service):
    """A field added to the request must be saved too, or this fails."""
    service.save("full", PARAMS)
    loaded = service.load("full")
    for field in params_to_dict(PARAMS):
        assert getattr(loaded, field) == getattr(PARAMS, field), field


def test_loading_a_name_that_was_never_saved_raises(service):
    with pytest.raises(ScenarioNotFound, match="no scenario named"):
        service.load("nothing-here")


def test_saving_under_a_name_replaces_that_configuration(service):
    service.save("nightly", PARAMS)
    service.save("nightly", SimulationParams(ticks=7))
    assert service.load("nightly") == SimulationParams(ticks=7)
    assert [s.name for s in service.list_scenarios()] == ["nightly"]


def test_scenarios_can_be_listed_and_deleted(service):
    service.save("one", PARAMS, description="an AMM pump")
    service.save("two", SimulationParams())
    assert [s.name for s in service.list_scenarios()] == ["one", "two"]
    assert service.list_scenarios()[0].description == "an AMM pump"
    assert service.delete("one") is True
    assert [s.name for s in service.list_scenarios()] == ["two"]


def test_describe_returns_the_row_as_stored(service):
    service.save("nightly", PARAMS, description="kept")
    stored = service.describe("nightly")
    assert stored.name == "nightly"
    assert stored.description == "kept"
    assert stored.params == params_to_dict(PARAMS)


# --- validation ------------------------------------------------------------------------------------------


def test_saving_something_that_is_not_a_request_is_rejected(service):
    with pytest.raises(ValueError, match="must be a SimulationParams"):
        service.save("bad", {"ticks": 5})


def test_a_stored_request_is_held_to_the_same_rules_as_a_typed_one(service):
    """Validation is ``SimulationParams``' own — there is no second
    definition of a valid request."""
    service._scenarios.save("bad-mode", {**params_to_dict(PARAMS), "pricing_mode": "moonmath"})
    with pytest.raises(ValueError, match="unknown pricing_mode"):
        service.load("bad-mode")


@pytest.mark.parametrize(
    "bad, message",
    [
        ({"ticks": 0}, "ticks must be between"),
        ({"ticks": MAX_TICKS + 1}, "ticks must be between"),
        ({"ticks": "twenty"}, "ticks must be an integer"),
        ({"random_seed": -1}, "random_seed must be between"),
        ({"random_seed": "abc"}, "random_seed must be an integer"),
        ({"scenario": "not_a_preset"}, "unknown scenario"),
        ({"psychology": "yes"}, "psychology must be True or False"),
    ],
)
def test_an_invalid_stored_value_is_reported(service, bad, message):
    service._scenarios.save("bad", {**params_to_dict(SimulationParams()), **bad})
    with pytest.raises(ValueError, match=message):
        service.load("bad")


def test_a_stored_request_missing_a_field_is_reported(service):
    params = params_to_dict(PARAMS)
    del params["ticks"]
    service._scenarios.save("short", params)
    with pytest.raises(ValueError, match="missing parameters"):
        service.load("short")


def test_a_stored_request_with_an_unknown_field_is_reported(service):
    """A scenario written by a version that knew a field this one does
    not must say so, not drop it."""
    service._scenarios.save("future", {**params_to_dict(PARAMS), "liquidity_shock": True})
    with pytest.raises(ValueError, match="unknown parameters"):
        service.load("future")


def test_params_from_dict_rejects_a_non_mapping():
    with pytest.raises(ValueError, match="must be a mapping"):
        params_from_dict([1, 2, 3])


# --- simulation equivalence ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=20, random_seed=48291),
        SimulationParams(ticks=20, pricing_mode="amm", include_whales=False, random_seed=48291),
        SimulationParams(
            ticks=25, pricing_mode="amm", include_whales=False,
            scenario="pump_and_dump", random_seed=48291,
        ),
        SimulationParams(ticks=25, scenario="wash_trading", random_seed=48291),
        SimulationParams(
            ticks=20, events=True, random_events=True, psychology=True,
            whale_observation=True, random_seed=48291,
        ),
    ],
    ids=["random_walk", "amm", "amm-pump_and_dump", "wash_trading", "events-psychology"],
)
def test_a_loaded_scenario_runs_the_simulation_its_configuration_ran(service, params):
    """Manual configuration versus the same configuration saved, loaded
    and run — the whole payload must agree, report included."""
    direct = payload_to_dict(run_simulation(params))

    service.save("under-test", params)
    from_scenario = payload_to_dict(run_simulation(service.load("under-test")))

    assert from_scenario == direct


def test_loading_the_same_scenario_twice_runs_the_same_simulation(service):
    """A saved seed makes a scenario reproducible, not merely repeatable."""
    service.save("nightly", SimulationParams(ticks=15, random_seed=48291))
    first = payload_to_dict(run_simulation(service.load("nightly")))
    second = payload_to_dict(run_simulation(service.load("nightly")))
    assert first == second


def test_two_scenarios_with_different_seeds_run_differently(service):
    service.save("one", SimulationParams(ticks=15, random_seed=1))
    service.save("two", SimulationParams(ticks=15, random_seed=2))
    one = run_simulation(service.load("one"))
    two = run_simulation(service.load("two"))
    assert one.price_series != two.price_series


def test_a_scenario_that_pins_no_seed_still_round_trips(service):
    """``None`` means the configured seed, and stays ``None``."""
    service.save("unpinned", SimulationParams(ticks=10))
    assert service.load("unpinned").random_seed is None
    assert payload_to_dict(run_simulation(service.load("unpinned"))) == payload_to_dict(
        run_simulation(SimulationParams(ticks=10))
    )


# --- across connections ------------------------------------------------------------------------------------


def test_a_scenario_survives_the_database_being_closed_and_reopened(tmp_path):
    """create → save → close → reopen → load → run → compare."""
    db = tmp_path / "scenarios.db"
    params = SimulationParams(ticks=20, pricing_mode="amm", include_whales=False, random_seed=48291)
    expected = payload_to_dict(run_simulation(params))

    writer = connect(db)
    init_db(writer)
    ScenarioService(writer).save("amm-nightly", params, description="AMM, pinned seed")
    writer.close()

    reader = connect(db)
    init_db(reader)
    loaded = ScenarioService(reader).load("amm-nightly")
    reader.close()

    assert loaded == params
    assert payload_to_dict(run_simulation(loaded)) == expected
