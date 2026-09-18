"""Market-condition presets on the demo CLI (Phase 17).

What matters here: the flag is opt-in and the default command line is
untouched, the preset reaches the run, an explicitly typed event flag
still overrules it, and the whole thing rides inside a saved scenario and
a batch without either system changing.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from crypto_simulator.config import clear_settings_cache
from crypto_simulator.data.database import connect, init_db
from crypto_simulator.services.market_conditions import MARKET_CONDITION_NAMES
from crypto_simulator.services.scenarios import ScenarioService

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "conditions.db"
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


def _news_line(output):
    return next((line for line in output.splitlines() if "news events" in line), "")


# --- opt-in ----------------------------------------------------------------------------------------------


def test_a_run_without_the_flag_says_nothing_about_a_market_condition(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5")
    assert "market condition" not in output


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_each_preset_runs_and_reports_itself(monkeypatch, capsys, name):
    output = _run(monkeypatch, capsys, "--ticks", "10", "--seed", "48291",
                  "--market-condition", name)
    assert f"market condition: {name}" in output
    assert len(_prices(output)) == 10


def test_an_unknown_preset_is_refused_by_the_parser(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--market-condition", "moon")
    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_a_preset_changes_the_run(monkeypatch, capsys):
    plain = _prices(_run(monkeypatch, capsys, "--ticks", "20", "--seed", "48291"))
    bull = _prices(_run(monkeypatch, capsys, "--ticks", "20", "--seed", "48291",
                        "--market-condition", "bull"))
    assert plain != bull


def test_a_preset_configures_the_news_the_run_reports(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5", "--market-condition", "bull")
    assert "random 0.15/tick" in _news_line(output)
    assert "drift_per_sentiment 0.004" in _news_line(output)


# --- the AMM caveat --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", MARKET_CONDITION_NAMES)
def test_every_preset_runs_in_amm_mode(monkeypatch, capsys, name):
    """A drift coefficient leaking into AMM would abort the run."""
    output = _run(monkeypatch, capsys, "--ticks", "10", "--pricing-mode", "amm",
                  "--no-whales", "--market-condition", name)
    assert len(_prices(output)) == 10
    assert "drift_per_sentiment 0.0" in _news_line(output) or "news events" not in output


# --- precedence ------------------------------------------------------------------------------------------


def test_a_typed_random_events_flag_overrules_the_presets_rate(monkeypatch, capsys):
    """saved scenario -> market condition -> explicit event flags."""
    preset_only = _run(monkeypatch, capsys, "--ticks", "5", "--market-condition", "bull")
    overridden = _run(monkeypatch, capsys, "--ticks", "5", "--market-condition", "bull",
                      "--random-events")
    assert "random 0.15/tick" in _news_line(preset_only)
    assert "random 0.1/tick" in _news_line(overridden)


def test_a_typed_events_flag_adds_its_schedule_on_top_of_a_preset(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "10", "--market-condition", "bull", "--events")
    line = _news_line(output)
    assert "2 scheduled" in line or "scheduled" in line
    assert "random 0.15/tick" in line, "the preset's rate survives an unrelated flag"


def test_a_preset_composes_with_a_manipulation_scenario(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "20", "--pricing-mode", "amm", "--no-whales",
                  "--scenario", "pump_and_dump", "--market-condition", "bear")
    assert "scenario       : pump_and_dump" in output
    assert "market condition: bear" in output


def test_a_preset_composes_with_seed_and_ticks(monkeypatch, capsys):
    first = _run(monkeypatch, capsys, "--ticks", "7", "--seed", "4242", "--market-condition", "meme")
    second = _run(monkeypatch, capsys, "--ticks", "7", "--seed", "4242", "--market-condition", "meme")
    assert first == second
    assert len(_prices(first)) == 7
    assert "random seed    : 4242" in first


# --- saved scenarios, with no schema change ----------------------------------------------------------------


def test_a_market_condition_is_saved_and_reloaded_with_a_scenario(db, monkeypatch, capsys):
    saved = _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291",
                 "--market-condition", "bear", "--save-scenario", "bear-nightly")
    conn = connect(db)
    init_db(conn)
    params = ScenarioService(conn).load("bear-nightly")
    conn.close()
    assert params.market_condition == "bear"

    loaded = _run(monkeypatch, capsys, "--load-scenario", "bear-nightly")
    assert "market condition: bear" in loaded
    assert _prices(loaded) == _prices(saved)


def test_a_typed_preset_overrides_the_one_in_a_scenario(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "10", "--seed", "1",
         "--market-condition", "bear", "--save-scenario", "cfg")
    output = _run(monkeypatch, capsys, "--load-scenario", "cfg", "--market-condition", "bull")
    assert "market condition: bull" in output


def test_a_scenario_saved_without_a_condition_still_has_none(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "5", "--seed", "1", "--save-scenario", "plain")
    conn = connect(db)
    init_db(conn)
    stored = ScenarioService(conn).describe("plain")
    params = ScenarioService(conn).load("plain")
    conn.close()
    assert params.market_condition is None
    assert stored.params["market_condition"] is None


def test_the_scenario_schema_is_unchanged(db, monkeypatch, capsys):
    """The preset rides inside params_json; Phase 17 adds no table."""
    _run(monkeypatch, capsys, "--ticks", "5", "--market-condition", "meme",
         "--save-scenario", "meme-cfg")
    conn = connect(db)
    init_db(conn)
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {row[1] for row in conn.execute("PRAGMA table_info(coin_scenarios)")}
    conn.close()
    assert not any("market" in table for table in tables)
    assert columns == {"scenario_id", "name", "description", "created_at", "updated_at", "params_json"}


# --- batches ---------------------------------------------------------------------------------------------


def test_a_batch_runs_under_a_preset(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "20", "--batch", "5", "--seed", "48291",
                  "--market-condition", "bull")
    assert "market condition: bull" in output
    rows = [line.split() for line in output.splitlines()
            if len(line.split()) >= 5 and line.split()[0].isdigit() and line.split()[1].isdigit()]
    assert len(rows) == 5
    assert "Aggregate statistics" in output


def test_a_batch_under_a_preset_is_deterministic(monkeypatch, capsys):
    first = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "4", "--seed", "1",
                 "--market-condition", "meme")
    second = _run(monkeypatch, capsys, "--ticks", "10", "--batch", "4", "--seed", "1",
                  "--market-condition", "meme")
    assert first == second


def test_a_scenario_batch_carries_its_condition(db, monkeypatch, capsys):
    _run(monkeypatch, capsys, "--ticks", "10", "--seed", "48291",
         "--market-condition", "bull", "--save-scenario", "bull-cfg")
    output = _run(monkeypatch, capsys, "--load-scenario", "bull-cfg", "--batch", "3")
    assert "market condition: bull" in output
