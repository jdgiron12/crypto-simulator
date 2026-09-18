"""Batch mode on the demo CLI (Phase 14).

What matters here: the single-run command line is untouched, a batch
prints one line per run rather than one line per tick, the summary
identifies every run, a batch is reproducible from its base seed, and a
batch with a failed run is not a successful command.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from crypto_simulator.config import clear_settings_cache
from crypto_simulator.data.database import connect, init_db
from crypto_simulator.services.coin_simulation import BATCH_SEED_STRIDE
from crypto_simulator.services.scenarios import ScenarioService
from crypto_simulator.services.simulation_params import SimulationParams

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "batch.db"
    monkeypatch.setenv("CRYPTOSIM_DB_PATH", str(path))
    clear_settings_cache()
    yield path
    clear_settings_cache()


def _run(monkeypatch, capsys, *args):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return capsys.readouterr().out


def _rows(output):
    """The summary's per-run lines: (index, seed, id, ticks, result)."""
    rows = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit() and parts[1].isdigit():
            rows.append(parts)
    return rows


# --- the single-run command line is untouched -------------------------------------------------------------


def test_a_run_without_batch_says_nothing_about_batches(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5")
    assert "Batch" not in output
    assert "Simulating" in output


def test_batch_mode_replaces_the_tick_table(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "3", "--seed", "48291")
    assert "Simulating" not in output
    assert "Batch of 3 runs" in output


# --- the summary ------------------------------------------------------------------------------------------


def test_the_summary_has_a_line_for_every_run(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5", "--batch", "6", "--seed", "48291")
    rows = _rows(output)
    assert [row[0] for row in rows] == [str(i) for i in range(6)]
    assert all(row[-1] == "ok" for row in rows)


def test_the_summary_identifies_each_run(monkeypatch, capsys):
    """Requested runs, each run's seed, its simulation id, and whether it
    succeeded."""
    output = _run(monkeypatch, capsys, "--ticks", "5", "--batch", "4", "--seed", "48291")
    rows = _rows(output)
    assert [int(row[1]) for row in rows] == [48291 + i * BATCH_SEED_STRIDE for i in range(4)]
    assert all(len(row[2]) == 16 for row in rows), "a simulation id per run"
    assert len({row[2] for row in rows}) == 4
    assert "base seed      : 48291" in output
    assert "completed      : 4 of 4" in output


def test_the_summary_does_not_dump_payloads(monkeypatch, capsys):
    """A hundred runs of analytics is not something to print."""
    output = _run(monkeypatch, capsys, "--ticks", "20", "--batch", "10", "--seed", "48291")
    assert len(output.splitlines()) < 30
    assert "Market summary" not in output


def test_the_summary_reports_no_statistics(monkeypatch, capsys):
    """Phase 15 aggregates; Phase 14 lists."""
    output = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "5", "--seed", "1")
    lowered = output.lower()
    for word in ("mean", "median", "average", "percentile", "std", "distribution"):
        assert word not in lowered


# --- run count --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("runs", ["0", "-1", "1001"])
def test_an_out_of_range_run_count_is_a_clean_error(monkeypatch, capsys, runs):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--batch", runs)
    assert exit_info.value.code == 2
    assert "runs must be between" in capsys.readouterr().err


def test_a_non_integer_run_count_is_a_clean_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--batch", "many")
    assert exit_info.value.code == 2
    assert "invalid int value" in capsys.readouterr().err


def test_a_one_run_batch_is_allowed(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5", "--batch", "1", "--seed", "1")
    assert len(_rows(output)) == 1


# --- determinism ------------------------------------------------------------------------------------------


def test_the_same_batch_command_gives_the_same_batch(monkeypatch, capsys):
    first = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "5", "--seed", "48291")
    second = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "5", "--seed", "48291")
    assert first == second


def test_a_different_base_seed_gives_a_different_batch(monkeypatch, capsys):
    one = _rows(_run(monkeypatch, capsys, "--ticks", "10", "--batch", "5", "--seed", "48291"))
    two = _rows(_run(monkeypatch, capsys, "--ticks", "10", "--batch", "5", "--seed", "48292"))
    assert [row[2] for row in one] != [row[2] for row in two]


def test_a_batch_without_a_seed_is_still_deterministic(monkeypatch, capsys):
    first = _run(monkeypatch, capsys, "--ticks", "5", "--batch", "3")
    second = _run(monkeypatch, capsys, "--ticks", "5", "--batch", "3")
    assert first == second


def test_one_run_of_a_batch_matches_that_seed_run_alone(monkeypatch, capsys):
    from crypto_simulator.dashboard.data import run_simulation

    output = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "3", "--seed", "48291")
    rows = _rows(output)
    alone = run_simulation(SimulationParams(ticks=10, random_seed=int(rows[2][1])))
    assert rows[2][2] == alone.simulation.simulation_id


# --- both pricing modes and the manipulation presets -------------------------------------------------------


@pytest.mark.parametrize(
    "flags",
    [
        ["--ticks", "10"],
        ["--ticks", "10", "--pricing-mode", "amm", "--no-whales"],
        ["--ticks", "20", "--pricing-mode", "amm", "--no-whales", "--scenario", "pump_and_dump"],
        ["--ticks", "20", "--scenario", "wash_trading"],
        ["--ticks", "12", "--events", "--random-events", "--psychology", "--whale-observation"],
    ],
    ids=["random_walk", "amm", "amm-pump", "wash_trading", "events-psychology-whales"],
)
def test_a_batch_of_each_configuration(monkeypatch, capsys, flags):
    output = _run(monkeypatch, capsys, *flags, "--batch", "3", "--seed", "48291")
    rows = _rows(output)
    assert len(rows) == 3
    assert all(row[-1] == "ok" for row in rows)


# --- failures ------------------------------------------------------------------------------------------------


def test_a_batch_whose_runs_all_fail_exits_non_zero(monkeypatch, capsys):
    """AMM mode does not support whales. Every run fails, each is listed,
    and the command is not a success."""
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--ticks", "5", "--pricing-mode", "amm", "--batch", "3")
    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert output.count("FAILED") == 3
    assert "Whales are not supported" in output
    assert "completed      : 0 of 3" in output


# --- scenarios ------------------------------------------------------------------------------------------------


def test_a_batch_of_a_saved_scenario(db, monkeypatch, capsys):
    _run(
        monkeypatch, capsys,
        "--ticks", "10", "--pricing-mode", "amm", "--no-whales",
        "--seed", "48291", "--save-scenario", "amm-nightly",
    )
    output = _run(monkeypatch, capsys, "--load-scenario", "amm-nightly", "--batch", "4")
    assert "from scenario  : amm-nightly" in output
    assert "configuration  : 10 ticks, amm" in output
    assert len(_rows(output)) == 4
    assert "base seed      : 48291" in output


def test_a_typed_flag_still_overrides_a_scenario_in_batch_mode(db, monkeypatch, capsys):
    """Phase 13 precedence is unchanged by batch mode."""
    _run(monkeypatch, capsys, "--ticks", "10", "--seed", "48291", "--save-scenario", "nightly")
    output = _run(
        monkeypatch, capsys, "--load-scenario", "nightly", "--ticks", "3", "--batch", "2"
    )
    assert "configuration  : 3 ticks" in output


def test_a_batch_can_save_the_configuration_it_ran(db, monkeypatch, capsys):
    output = _run(
        monkeypatch, capsys,
        "--ticks", "8", "--seed", "48291", "--batch", "3", "--save-scenario", "batched",
    )
    assert "saved scenario : batched" in output

    conn = connect(db)
    init_db(conn)
    params = ScenarioService(conn).load("batched")
    conn.close()
    assert params.ticks == 8
    assert params.random_seed == 48291, "the base seed is what was saved, not a derived one"


def test_batch_is_not_part_of_a_saved_scenario(db, monkeypatch, capsys):
    """A scenario says what to simulate, not how many times."""
    _run(monkeypatch, capsys, "--ticks", "5", "--seed", "1", "--batch", "4", "--save-scenario", "cfg")
    conn = connect(db)
    init_db(conn)
    stored = ScenarioService(conn).describe("cfg")
    conn.close()
    assert "batch" not in stored.params


# --- combinations that do not make sense -----------------------------------------------------------------------


def test_report_cannot_be_combined_with_batch(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--batch", "3", "--report")
    assert exit_info.value.code == 2
    assert "cannot be combined with --batch" in capsys.readouterr().err


# --- no database is written --------------------------------------------------------------------------------------


def test_a_batch_writes_no_run_to_the_database(db, monkeypatch, capsys):
    """Phase 14 keeps results in memory; a batch must not quietly fill a
    database with rows."""
    _run(monkeypatch, capsys, "--ticks", "5", "--batch", "5", "--seed", "1")
    assert not db.exists(), "a batch without a scenario flag opens no database at all"


def test_a_batch_that_saves_a_scenario_stores_only_the_scenario(db, monkeypatch, capsys):
    from crypto_simulator.data.coin_runs import CoinRunRepository

    _run(monkeypatch, capsys, "--ticks", "5", "--batch", "5", "--seed", "1", "--save-scenario", "cfg")
    conn = connect(db)
    init_db(conn)
    runs = CoinRunRepository(conn).list_runs()
    conn.close()
    assert runs == [], "no run rows: batch persistence is not part of this phase"
