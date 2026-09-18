"""Saving and loading scenarios from the demo CLI (Phase 13).

What matters here: the default command line is untouched, a saved
scenario reproduces the run it was saved from, and precedence is one
unambiguous rule — the scenario is the baseline, a flag typed on the
command line replaces that field.

Each test points the CLI at its own database through ``CRYPTOSIM_DB_PATH``
(the configured path the app already uses), so nothing writes to the
project's own database.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from crypto_simulator.config import clear_settings_cache
from crypto_simulator.data.database import connect, init_db
from crypto_simulator.services.scenarios import ScenarioService

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A database of this test's own, as the CLI would be configured."""
    path = tmp_path / "scenarios.db"
    monkeypatch.setenv("CRYPTOSIM_DB_PATH", str(path))
    clear_settings_cache()
    yield path
    clear_settings_cache()


def _run(monkeypatch, capsys, *args):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return capsys.readouterr().out


def _prices(output):
    return [line.split()[1] for line in output.splitlines() if line[:4].strip().isdigit()]


def _service(path):
    conn = connect(path)
    init_db(conn)
    return conn, ScenarioService(conn)


# --- the default command line is untouched ---------------------------------------------------------------


def test_a_run_without_scenario_flags_says_nothing_about_scenarios(db, monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5")
    assert "scenario" not in output.lower()


def test_no_database_is_touched_when_no_scenario_flag_is_given(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "5")
    assert not db.exists(), "a plain run must not open, let alone create, a database"


# --- saving ----------------------------------------------------------------------------------------------


def test_saving_records_the_configuration_that_ran(db, monkeypatch, capsys):
    output = _run(
        monkeypatch, capsys,
        "--ticks", "12", "--seed", "48291", "--psychology", "--save-scenario", "nightly",
    )
    assert "saved scenario : nightly" in output

    conn, service = _service(db)
    params = service.load("nightly")
    conn.close()
    assert (params.ticks, params.random_seed, params.psychology) == (12, 48291, True)


def test_saving_pins_the_seed_that_actually_ran(db, monkeypatch, capsys):
    """Without ``--seed`` a run uses the configured seed; the scenario
    records that number, so it reproduces this run later rather than
    whatever the configuration says then."""
    from crypto_simulator.config import get_settings

    configured = get_settings().simulation.random_seed
    _run(monkeypatch, capsys, "--ticks", "5", "--save-scenario", "unpinned")

    conn, service = _service(db)
    params = service.load("unpinned")
    conn.close()
    assert params.random_seed == configured


def test_saving_pins_the_pricing_mode_that_actually_ran(db, monkeypatch, capsys):
    from crypto_simulator.config import get_settings

    _run(monkeypatch, capsys, "--ticks", "5", "--save-scenario", "default-mode")
    conn, service = _service(db)
    params = service.load("default-mode")
    conn.close()
    assert params.pricing_mode == get_settings().coin.pricing_mode


def test_saving_twice_under_one_name_keeps_one_scenario(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "5", "--save-scenario", "nightly")
    _run(monkeypatch, capsys, "--ticks", "9", "--save-scenario", "nightly")

    conn, service = _service(db)
    listed = service.list_scenarios()
    params = service.load("nightly")
    conn.close()
    assert [s.name for s in listed] == ["nightly"]
    assert params.ticks == 9


def test_an_unsavable_configuration_is_refused_cleanly(db, monkeypatch, capsys):
    """``--ticks`` is unbounded for a plain run but a saved scenario is
    held to the request bound, so this must be an error, not a traceback
    and not a silently different scenario."""
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--ticks", "5000", "--save-scenario", "too-long")
    assert exit_info.value.code == 2
    assert "cannot save scenario" in capsys.readouterr().err
    assert not db.exists() or _saved_names(db) == []


def _saved_names(path):
    conn, service = _service(path)
    names = [s.name for s in service.list_scenarios()]
    conn.close()
    return names


# --- loading ---------------------------------------------------------------------------------------------


def test_loading_reproduces_the_run_that_was_saved(db, monkeypatch, capsys):
    saved = _run(
        monkeypatch, capsys,
        "--ticks", "12", "--seed", "48291", "--psychology", "--save-scenario", "nightly",
    )
    loaded = _run(monkeypatch, capsys, "--load-scenario", "nightly")
    assert _prices(loaded) == _prices(saved)
    assert "from scenario  : nightly" in loaded


def test_loading_restores_every_option(db, monkeypatch, capsys):
    _run(
        monkeypatch, capsys,
        "--ticks", "8", "--pricing-mode", "amm", "--no-whales",
        "--scenario", "pump_and_dump", "--seed", "48291", "--save-scenario", "amm-pump",
    )
    output = _run(monkeypatch, capsys, "--load-scenario", "amm-pump")
    assert "pricing mode   : amm" in output
    assert "scenario       : pump_and_dump" in output
    assert len(_prices(output)) == 8


def test_loading_a_scenario_that_does_not_exist_is_a_clean_error(db, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--load-scenario", "never-saved")
    assert exit_info.value.code == 2
    assert "no scenario named" in capsys.readouterr().err


def test_a_stored_scenario_this_version_cannot_run_is_reported(db, monkeypatch, capsys):
    conn, service = _service(db)
    service._scenarios.save("broken", {"ticks": 5, "pricing_mode": "moonmath"})
    conn.close()

    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--load-scenario", "broken")
    assert exit_info.value.code == 2
    assert "cannot be run" in capsys.readouterr().err


# --- precedence ------------------------------------------------------------------------------------------


def test_a_flag_typed_on_the_command_line_overrides_the_scenario(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291", "--save-scenario", "nightly")
    output = _run(monkeypatch, capsys, "--load-scenario", "nightly", "--ticks", "3")
    assert len(_prices(output)) == 3


def test_a_flag_typed_with_the_parsers_own_default_still_overrides(db, monkeypatch, capsys):
    """``--ticks 20`` is the parser's default, so comparing against
    defaults could not tell it from silence; typing it must still win
    over the scenario's 12."""
    _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291", "--save-scenario", "nightly")
    output = _run(monkeypatch, capsys, "--load-scenario", "nightly", "--ticks", "20")
    assert len(_prices(output)) == 20


def test_an_untyped_flag_takes_the_scenarios_value_not_the_default(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291", "--save-scenario", "nightly")
    output = _run(monkeypatch, capsys, "--load-scenario", "nightly")
    assert len(_prices(output)) == 12, "the parser default of 20 must not win"


def test_a_typed_seed_overrides_the_scenarios_seed(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "10", "--seed", "1", "--save-scenario", "nightly")
    one = _run(monkeypatch, capsys, "--load-scenario", "nightly")
    two = _run(monkeypatch, capsys, "--load-scenario", "nightly", "--seed", "2")
    assert _prices(one) != _prices(two)
    assert "random seed    : 2" in two


def test_a_typed_switch_overrides_a_scenario_that_had_it_off(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "6", "--seed", "1", "--save-scenario", "quiet")
    output = _run(monkeypatch, capsys, "--load-scenario", "quiet", "--psychology")
    assert "psychology     : on" in output


def test_loading_and_saving_together_stores_the_effective_configuration(db, monkeypatch, capsys):
    """A scenario can be edited by loading it, overriding a flag and
    saving the result under a new name."""
    _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291", "--save-scenario", "base")
    _run(
        monkeypatch, capsys,
        "--load-scenario", "base", "--ticks", "4", "--save-scenario", "shorter",
    )
    conn, service = _service(db)
    base, shorter = service.load("base"), service.load("shorter")
    conn.close()
    assert base.ticks == 12
    assert shorter.ticks == 4
    assert shorter.random_seed == base.random_seed


# --- equivalence with a manual command line --------------------------------------------------------------


@pytest.mark.parametrize(
    "flags",
    [
        ["--ticks", "15", "--seed", "48291"],
        ["--ticks", "15", "--pricing-mode", "amm", "--no-whales", "--seed", "48291"],
        ["--ticks", "20", "--pricing-mode", "amm", "--no-whales",
         "--scenario", "pump_and_dump", "--seed", "48291"],
        ["--ticks", "20", "--scenario", "wash_trading", "--seed", "48291"],
        ["--ticks", "15", "--events", "--psychology", "--seed", "48291"],
    ],
    ids=["random_walk", "amm", "amm-pump", "wash_trading", "events-psychology"],
)
def test_a_loaded_scenario_runs_what_the_flags_ran(db, monkeypatch, capsys, flags):
    manual = _run(monkeypatch, capsys, *flags)
    _run(monkeypatch, capsys, *flags, "--save-scenario", "under-test")
    loaded = _run(monkeypatch, capsys, "--load-scenario", "under-test")
    assert _prices(loaded) == _prices(manual)
