"""Storage for named simulation configurations (Phase 13).

What matters here: a scenario is stored by name, saving under a name that
exists updates it rather than duplicating it, scenarios stay isolated from
one another and from Phase 12's runs, a corrupted row is reported rather
than silently becoming a default request, and every value is bound.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from crypto_simulator.data import CoinRunRepository, connect, init_db
from crypto_simulator.data.coin_scenarios import CoinScenarioRepository, StoredScenario

PARAMS = {
    "ticks": 40,
    "pricing_mode": "amm",
    "include_traders": True,
    "include_whales": False,
    "scenario": "pump_and_dump",
    "events": True,
    "random_events": False,
    "psychology": True,
    "whale_observation": False,
    "random_seed": 48291,
}


@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn):
    return CoinScenarioRepository(conn)


# --- schema --------------------------------------------------------------------------------------------


def test_init_db_creates_the_scenarios_table(conn):
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "coin_scenarios" in tables


def test_the_phase_12_run_tables_are_untouched(conn):
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"coin_runs", "coin_run_ticks"} <= tables


def test_initializing_again_keeps_saved_scenarios(conn, repo):
    repo.save("nightly", PARAMS)
    init_db(conn)
    assert repo.load("nightly") is not None


# --- saving and loading --------------------------------------------------------------------------------


def test_a_saved_scenario_comes_back_as_it_went_in(repo):
    repo.save("nightly", PARAMS, description="the nightly run")
    stored = repo.load("nightly")
    assert isinstance(stored, StoredScenario)
    assert stored.name == "nightly"
    assert stored.description == "the nightly run"
    assert stored.params == PARAMS


def test_loading_a_name_that_was_never_saved_is_none(repo):
    assert repo.load("nothing-here") is None


def test_a_description_is_optional(repo):
    repo.save("plain", PARAMS)
    assert repo.load("plain").description is None


def test_timestamps_are_recorded(repo):
    repo.save("nightly", PARAMS, now="2026-01-01T00:00:00+00:00")
    stored = repo.load("nightly")
    assert stored.created_at == stored.updated_at == "2026-01-01T00:00:00+00:00"


# --- a name identifies one scenario ----------------------------------------------------------------------


def test_saving_under_an_existing_name_updates_that_scenario(repo):
    first = repo.save("nightly", PARAMS)
    second = repo.save("nightly", {**PARAMS, "ticks": 99})
    assert first == second
    assert repo.load("nightly").params["ticks"] == 99
    assert len(repo.list_scenarios()) == 1


def test_an_update_keeps_the_original_creation_time(repo):
    repo.save("nightly", PARAMS, now="2026-01-01T00:00:00+00:00")
    repo.save("nightly", {**PARAMS, "ticks": 7}, now="2026-06-01T00:00:00+00:00")
    stored = repo.load("nightly")
    assert stored.created_at == "2026-01-01T00:00:00+00:00"
    assert stored.updated_at == "2026-06-01T00:00:00+00:00"


def test_updating_one_scenario_leaves_the_others_alone(repo):
    repo.save("one", PARAMS)
    repo.save("two", {**PARAMS, "ticks": 11})
    repo.save("one", {**PARAMS, "ticks": 22})
    assert repo.load("one").params["ticks"] == 22
    assert repo.load("two").params["ticks"] == 11


def test_two_names_are_two_scenarios(repo):
    assert repo.save("one", PARAMS) != repo.save("two", PARAMS)
    assert [s.name for s in repo.list_scenarios()] == ["one", "two"]


# --- listing and deleting --------------------------------------------------------------------------------


def test_list_scenarios_is_by_name_and_carries_no_parameters(repo):
    repo.save("zulu", PARAMS)
    repo.save("alpha", PARAMS, description="first")
    listed = repo.list_scenarios()
    assert [s.name for s in listed] == ["alpha", "zulu"]
    assert listed[0].description == "first"
    assert not hasattr(listed[0], "params")


def test_an_empty_database_lists_nothing(repo):
    assert repo.list_scenarios() == []


def test_deleting_removes_one_scenario_and_says_so(repo):
    repo.save("one", PARAMS)
    repo.save("two", PARAMS)
    assert repo.delete("one") is True
    assert repo.load("one") is None
    assert [s.name for s in repo.list_scenarios()] == ["two"]


def test_deleting_something_that_is_not_there_is_false(repo):
    assert repo.delete("never-saved") is False


# --- rejecting bad input ----------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "   ", None, 5])
def test_a_name_that_identifies_nothing_is_rejected(repo, name):
    with pytest.raises(ValueError, match="scenario name"):
        repo.save(name, PARAMS)


def test_params_must_be_a_mapping(repo):
    with pytest.raises(ValueError, match="params must be a mapping"):
        repo.save("bad", [1, 2, 3])


def test_a_description_must_be_text(repo):
    with pytest.raises(ValueError, match="description must be"):
        repo.save("bad", PARAMS, description=42)


def test_a_rejected_save_writes_nothing(conn, repo):
    with pytest.raises(ValueError):
        repo.save("", PARAMS)
    assert conn.execute("SELECT COUNT(*) FROM coin_scenarios").fetchone()[0] == 0


# --- a corrupted row is reported, never guessed at ---------------------------------------------------------


def test_unreadable_stored_json_is_reported(conn, repo):
    repo.save("nightly", PARAMS)
    conn.execute("UPDATE coin_scenarios SET params_json = ? WHERE name = ?", ("{not json", "nightly"))
    conn.commit()
    with pytest.raises(ValueError, match="unreadable stored parameters"):
        repo.load("nightly")


def test_stored_json_that_is_not_an_object_is_reported(conn, repo):
    repo.save("nightly", PARAMS)
    conn.execute("UPDATE coin_scenarios SET params_json = ? WHERE name = ?", ("[1, 2]", "nightly"))
    conn.commit()
    with pytest.raises(ValueError, match="must be a JSON object"):
        repo.load("nightly")


# --- storage form ----------------------------------------------------------------------------------------


def test_parameters_are_stored_as_json_text_not_pickled(conn, repo):
    repo.save("nightly", PARAMS)
    raw = conn.execute("SELECT params_json FROM coin_scenarios WHERE name = ?", ("nightly",)).fetchone()
    assert json.loads(raw["params_json"]) == PARAMS


def test_the_stored_text_is_canonical(conn, repo):
    """The same parameters always produce the same text, whatever order
    the mapping happened to be built in."""
    repo.save("one", PARAMS)
    repo.save("two", dict(reversed(list(PARAMS.items()))))
    rows = conn.execute("SELECT params_json FROM coin_scenarios ORDER BY name").fetchall()
    assert rows[0]["params_json"] == rows[1]["params_json"]


def test_types_survive_storage(repo):
    """Booleans stay booleans, ``None`` stays ``None``, ints stay ints."""
    params = {**PARAMS, "scenario": None, "psychology": False, "random_seed": 0}
    repo.save("typed", params)
    stored = repo.load("typed").params
    assert stored["scenario"] is None
    assert stored["psychology"] is False
    assert stored["random_seed"] == 0 and isinstance(stored["random_seed"], int)


# --- scenarios and runs are separate ----------------------------------------------------------------------


def test_scenarios_and_runs_do_not_disturb_each_other(conn, repo):
    """Phase 12 stores what a run produced; Phase 13 stores what to ask
    for. They share a database and nothing else."""
    from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation

    payload = payload_to_dict(run_simulation(SimulationParams(ticks=4, random_seed=3)))
    run_id = CoinRunRepository(conn).save(payload)
    repo.save("nightly", PARAMS)

    assert CoinRunRepository(conn).load(run_id) == payload
    assert repo.load("nightly").params == PARAMS
    assert repo.delete("nightly") is True
    assert CoinRunRepository(conn).load(run_id) == payload, "deleting a scenario must not touch runs"


# --- SQL safety ------------------------------------------------------------------------------------------


def test_a_hostile_looking_name_is_stored_as_data(conn, repo):
    name = "'); DROP TABLE coin_scenarios; --"
    repo.save(name, PARAMS)
    assert repo.load(name).params == PARAMS
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "coin_scenarios" in tables


# --- across connections ------------------------------------------------------------------------------------


def test_a_scenario_survives_the_connection_that_wrote_it(tmp_path):
    db = tmp_path / "scenarios.db"
    writer = connect(db)
    init_db(writer)
    CoinScenarioRepository(writer).save("nightly", PARAMS, description="kept")
    writer.close()

    reader = connect(db)
    init_db(reader)
    stored = CoinScenarioRepository(reader).load("nightly")
    reader.close()

    assert stored.params == PARAMS
    assert stored.description == "kept"
