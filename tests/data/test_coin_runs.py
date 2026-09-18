"""Persistence for finished coin runs (Phase 12).

What matters here: a finished run survives storage exactly — the payload
that comes back equals the one that went in — runs stay isolated from one
another, a failed save leaves nothing behind, initialization never
destroys stored runs, and none of it changes what a simulation does.

The runs under test are real ones, built through the same path the CLI
and the dashboard use, so these tests store what the simulator actually
produces rather than a hand-written fixture.
"""

from __future__ import annotations

import ast
import json
import sqlite3
from pathlib import Path

import pytest

from crypto_simulator.data import CoinRunRepository, StoredRun, connect, init_db
from crypto_simulator.data import coin_runs as coin_runs_module
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation


@pytest.fixture
def conn():
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn):
    return CoinRunRepository(conn)


def _payload(**kwargs):
    """A real finished run, serialized the way the dashboard serializes."""
    kwargs.setdefault("ticks", 8)
    kwargs.setdefault("random_seed", 48291)
    return payload_to_dict(run_simulation(SimulationParams(**kwargs)))


# --- initialization ------------------------------------------------------------------------------------


def test_init_db_creates_the_coin_tables(conn):
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"coin_runs", "coin_run_ticks"} <= tables


def test_the_trading_platform_tables_are_still_there(conn):
    """Phase 12 adds to the schema; it replaces nothing."""
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"assets", "accounts", "holdings", "orders", "trades", "price_history"} <= tables


def test_initializing_twice_is_safe(conn, repo):
    run_id = repo.save(_payload())
    init_db(conn)
    init_db(conn)
    assert repo.load(run_id) is not None, "re-initialization must not drop stored runs"


def test_initializing_an_existing_database_keeps_its_runs(tmp_path):
    """The destructive-initialization check, on a real file."""
    db = tmp_path / "runs.db"
    first = connect(db)
    init_db(first)
    run_id = CoinRunRepository(first).save(_payload())
    first.close()

    second = connect(db)
    init_db(second)
    assert CoinRunRepository(second).load(run_id) is not None
    second.close()


# --- saving and loading --------------------------------------------------------------------------------


def test_a_saved_run_comes_back_exactly(repo):
    payload = _payload()
    assert repo.load(repo.save(payload)) == payload


def test_the_run_metadata_is_stored_in_its_own_columns(conn, repo):
    payload = _payload(ticks=5, random_seed=777)
    run_id = repo.save(payload)
    row = conn.execute("SELECT * FROM coin_runs WHERE run_id = ?", (run_id,)).fetchone()
    simulation = payload["simulation"]
    assert row["simulation_id"] == simulation["simulation_id"]
    assert row["random_seed"] == 777
    assert row["pricing_mode"] == simulation["pricing_mode"]
    assert row["coin_symbol"] == simulation["coin_symbol"]
    assert (row["requested_ticks"], row["completed_ticks"]) == (5, 5)


def test_the_request_is_stored_so_a_later_phase_can_reread_it(conn, repo):
    """Phase 13 reloads a run's configuration from here."""
    payload = _payload(ticks=4, random_seed=12345, psychology=True)
    run_id = repo.save(payload)
    row = conn.execute("SELECT params_json FROM coin_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert json.loads(row["params_json"]) == payload["simulation"]["params"]
    assert json.loads(row["params_json"])["random_seed"] == 12345


def test_the_tick_series_is_stored_in_order_as_columns(conn, repo):
    payload = _payload(ticks=10)
    run_id = repo.save(payload)
    rows = conn.execute(
        "SELECT tick, price, market_cap, volume FROM coin_run_ticks WHERE run_id = ? ORDER BY tick",
        (run_id,),
    ).fetchall()
    assert [row["tick"] for row in rows] == [p["tick"] for p in payload["price_series"]]
    assert [row["price"] for row in rows] == [p["price"] for p in payload["price_series"]]


def test_float_precision_survives_storage(repo):
    """Prices go to SQLite REAL and back; not one of them may be rounded."""
    payload = _payload(ticks=25)
    loaded = repo.load(repo.save(payload))
    assert [p["price"] for p in loaded["price_series"]] == [
        p["price"] for p in payload["price_series"]
    ]
    assert [p["volume"] for p in loaded["price_series"]] == [
        p["volume"] for p in payload["price_series"]
    ]


def test_the_analytics_report_survives_storage(repo):
    payload = _payload(ticks=12, events=True, psychology=True)
    loaded = repo.load(repo.save(payload))
    assert loaded["report"] == payload["report"]
    assert loaded["report"]["market"] == payload["report"]["market"]


def test_loading_a_run_that_does_not_exist_is_none(repo):
    assert repo.load(999) is None


# --- both pricing modes --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=10, random_seed=48291),
        SimulationParams(ticks=10, pricing_mode="amm", include_whales=False, random_seed=48291),
    ],
    ids=["random_walk", "amm"],
)
def test_both_pricing_modes_round_trip(repo, params):
    payload = payload_to_dict(run_simulation(params))
    loaded = repo.load(repo.save(payload))
    assert loaded == payload
    assert loaded["simulation"]["pricing_mode"] == params.pricing_mode


def test_amm_pool_figures_survive_storage(repo):
    """AMM runs carry pool activity the random-walk report has none of."""
    payload = payload_to_dict(
        run_simulation(
            SimulationParams(ticks=12, pricing_mode="amm", include_whales=False, random_seed=7)
        )
    )
    assert payload["report"]["market"]["pool_activity"] is not None
    loaded = repo.load(repo.save(payload))
    assert loaded["report"]["market"]["pool_activity"] == payload["report"]["market"]["pool_activity"]


# --- several runs in one database ----------------------------------------------------------------------


def test_runs_are_isolated_from_one_another(repo):
    one = _payload(ticks=8, random_seed=1)
    two = _payload(ticks=12, random_seed=2)
    first, second = repo.save(one), repo.save(two)

    assert first != second
    assert repo.load(first) == one
    assert repo.load(second) == two


def test_the_same_request_can_be_saved_twice(repo):
    """simulation_id is derived from the request, so it is not the key."""
    payload = _payload()
    first, second = repo.save(payload), repo.save(payload)
    assert first != second
    assert repo.load(first) == repo.load(second) == payload


def test_list_runs_reports_each_stored_run_newest_first(repo):
    first = repo.save(_payload(ticks=4, random_seed=1))
    second = repo.save(_payload(ticks=6, random_seed=2))
    listed = repo.list_runs()
    assert [run.run_id for run in listed] == [second, first]
    assert isinstance(listed[0], StoredRun)
    assert listed[0].random_seed == 2
    assert listed[0].completed_ticks == 6


def test_list_runs_takes_a_limit(repo):
    for seed in range(3):
        repo.save(_payload(ticks=3, random_seed=seed))
    assert len(repo.list_runs(limit=2)) == 2
    assert repo.list_runs(limit=0) == []


@pytest.mark.parametrize("limit", [-1, 1.5, "2", True])
def test_list_runs_rejects_a_bad_limit(repo, limit):
    with pytest.raises(ValueError, match="limit must be"):
        repo.list_runs(limit=limit)


def test_an_empty_database_lists_nothing(repo):
    assert repo.list_runs() == []


# --- minimal and unusual runs --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=1, random_seed=5),
        SimulationParams(ticks=5, include_traders=False, random_seed=5),
        SimulationParams(ticks=5, include_whales=False, random_seed=5),
        SimulationParams(ticks=5, include_traders=False, include_whales=False, random_seed=5),
        SimulationParams(ticks=5, events=True, random_events=True, random_seed=5),
        SimulationParams(ticks=8, scenario="wash_trading", random_seed=5),
    ],
    ids=["one-tick", "no-traders", "no-whales", "neither", "events", "scenario"],
)
def test_unusual_runs_round_trip(repo, params):
    payload = payload_to_dict(run_simulation(params))
    assert repo.load(repo.save(payload)) == payload


def test_a_run_with_no_events_stores_its_nulls_as_nulls(repo):
    """``None`` in the report is absence, and must not come back a zero."""
    payload = _payload(ticks=6)
    assert payload["report"]["event_windows"] is None
    assert repo.load(repo.save(payload))["report"]["event_windows"] is None


# --- rejecting a bad payload ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["simulation", "report", "price_series"])
def test_a_payload_missing_a_top_level_key_is_rejected(repo, key):
    payload = _payload(ticks=3)
    del payload[key]
    with pytest.raises(ValueError, match="missing"):
        repo.save(payload)


def test_a_payload_missing_metadata_is_rejected(repo):
    payload = _payload(ticks=3)
    del payload["simulation"]["random_seed"]
    with pytest.raises(ValueError, match="random_seed"):
        repo.save(payload)


def test_a_malformed_tick_is_rejected(repo):
    payload = _payload(ticks=3)
    del payload["price_series"][1]["price"]
    with pytest.raises(ValueError, match=r"price_series\[1\]"):
        repo.save(payload)


# --- a failed save leaves nothing ----------------------------------------------------------------------


def test_a_rejected_payload_writes_no_row(conn, repo):
    payload = _payload(ticks=3)
    del payload["report"]
    with pytest.raises(ValueError):
        repo.save(payload)
    assert conn.execute("SELECT COUNT(*) FROM coin_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM coin_run_ticks").fetchone()[0] == 0


def test_a_save_that_fails_part_way_rolls_the_whole_run_back(conn, repo):
    """The ticks are written after the run row; if one of them fails, the
    run row must go with it rather than be left without its series."""
    payload = _payload(ticks=6)
    payload["price_series"][3]["price"] = object()  # unstorable, and only found mid-insert
    with pytest.raises(sqlite3.Error):  # the binding is refused; which subclass is version detail
        repo.save(payload)
    assert conn.execute("SELECT COUNT(*) FROM coin_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM coin_run_ticks").fetchone()[0] == 0


def test_a_failed_save_leaves_earlier_runs_alone(conn, repo):
    good = _payload(ticks=5, random_seed=1)
    run_id = repo.save(good)

    broken = _payload(ticks=5, random_seed=2)
    broken["price_series"][2]["volume"] = object()
    with pytest.raises(sqlite3.Error):
        repo.save(broken)

    assert repo.load(run_id) == good
    assert [run.run_id for run in repo.list_runs()] == [run_id]


# --- schema integrity ----------------------------------------------------------------------------------


def test_ticks_cannot_reference_a_run_that_does_not_exist(conn):
    """The foreign key is enforced, not decorative (database.py turns the
    pragma on for every connection)."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO coin_run_ticks (run_id, tick, price, market_cap, volume) "
            "VALUES (?, ?, ?, ?, ?)",
            (4242, 1, 1.0, 1.0, 1.0),
        )


def test_a_run_cannot_hold_the_same_tick_twice(conn, repo):
    run_id = repo.save(_payload(ticks=3))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO coin_run_ticks (run_id, tick, price, market_cap, volume) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, 1, 1.0, 1.0, 1.0),
        )


# --- SQL safety ----------------------------------------------------------------------------------------


def test_every_stored_value_is_bound_not_interpolated():
    """The module builds SQL text only from its own column-name
    constants; nothing that came from a payload is ever formatted into a
    statement. Checked by reading the source, so it holds for statements
    a test never happens to execute."""
    tree = ast.parse(Path(coin_runs_module.__file__).read_text())

    sql_statements = [
        node.args[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany"}
        and node.args
    ]
    assert sql_statements, "no statements found — the check would pass vacuously"

    interpolated = set()
    for statement in sql_statements:
        if isinstance(statement, ast.JoinedStr):  # an f-string used as SQL
            interpolated |= {
                inner.id for inner in ast.walk(statement) if isinstance(inner, ast.Name)
            }
    # Only the column list and its matching placeholders are interpolated,
    # both derived from this module's own constant — never from a payload.
    assert interpolated <= {"_SIMULATION_COLUMNS", "sql", "len"}, interpolated

    # And no other formatting mechanism reaches a statement.
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            assert not isinstance(node.left, ast.Constant), "%-formatted SQL"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "format", ".format()-built SQL"


def test_a_hostile_looking_value_is_stored_as_data(repo, conn):
    """A value that looks like SQL is a value, because it is bound."""
    payload = _payload(ticks=3)
    payload["simulation"]["coin_name"] = "'); DROP TABLE coin_runs; --"
    run_id = repo.save(payload)
    assert repo.load(run_id)["simulation"]["coin_name"] == "'); DROP TABLE coin_runs; --"
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "coin_runs" in tables


# --- persistence changes no simulation -----------------------------------------------------------------


def test_saving_a_run_does_not_change_the_run(repo):
    payload = _payload(ticks=10)
    before = json.dumps(payload, sort_keys=True)
    repo.save(payload)
    assert json.dumps(payload, sort_keys=True) == before, "save must not mutate its argument"


def test_a_simulation_is_identical_whether_or_not_it_is_persisted(repo):
    """Persistence observes; it must not consume an RNG draw or shift a
    price. The same request gives the same run with a save in between."""
    first = _payload(ticks=15, random_seed=2024)
    repo.save(first)
    second = _payload(ticks=15, random_seed=2024)
    assert second == first


def test_nothing_in_the_data_layer_imports_a_front_end():
    """``data`` must keep depending on no front end, so the CLI, the
    dashboard and a future batch runner can all save through it."""
    source = Path(coin_runs_module.__file__).read_text()
    assert "crypto_simulator.dashboard" not in source
    assert "streamlit" not in source


# --- the full round trip, on a real file -----------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=20, events=True, psychology=True, random_seed=48291),
        SimulationParams(
            ticks=20, pricing_mode="amm", include_whales=False, scenario="pump_and_dump",
            random_seed=48291,
        ),
    ],
    ids=["random_walk", "amm"],
)
def test_simulate_save_close_reopen_load_compare(tmp_path, params):
    """The whole point of the phase, end to end and across processes' worth
    of database lifetime: a run survives the connection that wrote it."""
    db = tmp_path / "runs.db"
    payload = payload_to_dict(run_simulation(params))

    writer = connect(db)
    init_db(writer)
    run_id = CoinRunRepository(writer).save(payload)
    writer.close()

    reader = connect(db)
    init_db(reader)
    reloaded = CoinRunRepository(reader).load(run_id)
    listed = CoinRunRepository(reader).list_runs()
    reader.close()

    assert reloaded == payload
    assert reloaded["simulation"]["simulation_id"] == payload["simulation"]["simulation_id"]
    assert reloaded["simulation"]["random_seed"] == 48291
    assert [p["tick"] for p in reloaded["price_series"]] == list(range(1, 21))
    assert reloaded["report"] == payload["report"]
    assert [run.run_id for run in listed] == [run_id]
    assert listed[0].pricing_mode == params.pricing_mode
