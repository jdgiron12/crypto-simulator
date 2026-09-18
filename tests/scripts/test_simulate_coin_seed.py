"""The demo CLI's ``--seed`` override (Phase 11).

Phase 10 Step 7 gave the dashboard a seed control; this closes the same
gap on the command line. What matters here: omitting ``--seed`` is the
configured-seed run the CLI always did, a named seed is the seed the run
actually uses, the same seed reproduces a run and a different one does
not, an out-of-range seed is a clean parser error rather than a
traceback, and a CLI seed and a dashboard seed mean the same thing.
"""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from crypto_simulator.config import get_settings
from crypto_simulator.dashboard import data as dashboard_data
from crypto_simulator.dashboard.data import SimulationParams, run_simulation
from crypto_simulator.services.coin_simulation import MAX_SEED, MIN_SEED

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


def _run(monkeypatch, capsys, *args):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return capsys.readouterr().out


def _prices(output):
    """The recorded price column, one entry per tick row."""
    prices = []
    for line in output.splitlines():
        head = line[:4].strip()
        if head.isdigit():
            prices.append(line.split()[1])
    return prices


# --- the flag ----------------------------------------------------------------------------------------


def test_a_default_run_prints_no_seed_line(monkeypatch, capsys):
    """Phase 11 is opt-in: without ``--seed`` the output is what it was."""
    output = _run(monkeypatch, capsys, "--ticks", "5")
    assert "random seed" not in output


def test_a_seeded_run_reports_the_seed_it_used(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "5", "--seed", "48291")
    assert "random seed    : 48291 (overrides config)" in output


# --- Test A: the seed reaches the simulation ---------------------------------------------------------


def test_the_cli_seed_is_the_seed_the_run_uses(monkeypatch, capsys):
    """Compared against the run built the way the configuration would
    build it with that seed — the repository's own reference method."""
    seed = 48291
    settings = get_settings()
    seeded = replace(settings, simulation=replace(settings.simulation, random_seed=seed))
    from crypto_simulator.services.coin_simulation import build_coin_simulator

    sim = build_coin_simulator(seeded)
    expected = [format(tick.price, ">9,.4f").strip() for tick in sim.run(8)]

    output = _run(monkeypatch, capsys, "--ticks", "8", "--seed", str(seed))
    assert _prices(output) == expected


# --- Test B: omitting the flag ------------------------------------------------------------------------


def test_omitting_the_seed_runs_on_the_configured_seed(monkeypatch, capsys):
    """Naming the configured seed and naming nothing are the same run."""
    configured = get_settings().simulation.random_seed
    default_run = _prices(_run(monkeypatch, capsys, "--ticks", "10"))
    explicit = _prices(_run(monkeypatch, capsys, "--ticks", "10", "--seed", str(configured)))
    assert default_run == explicit


def test_a_seeded_run_does_not_change_the_cached_settings(monkeypatch, capsys):
    before = get_settings().simulation.random_seed
    _run(monkeypatch, capsys, "--ticks", "3", "--seed", "777")
    assert get_settings().simulation.random_seed == before


# --- Test C: deterministic reproduction ---------------------------------------------------------------


def test_the_same_seed_reproduces_the_run(monkeypatch, capsys):
    first = _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291")
    second = _run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291")
    assert first == second


# --- Test D: different seeds --------------------------------------------------------------------------


def test_a_different_seed_gives_a_different_run(monkeypatch, capsys):
    """The point of the flag: the same options, another sample path."""
    one = _prices(_run(monkeypatch, capsys, "--ticks", "12", "--seed", "48291"))
    two = _prices(_run(monkeypatch, capsys, "--ticks", "12", "--seed", "48292"))
    assert one != two


# --- Test E: invalid input ----------------------------------------------------------------------------


@pytest.mark.parametrize("seed", ["-1", "4294967296"])
def test_an_out_of_range_seed_is_a_clean_parser_error(monkeypatch, capsys, seed):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--ticks", "3", "--seed", seed)
    assert exit_info.value.code == 2
    assert "--seed must be between" in capsys.readouterr().err


def test_a_non_integer_seed_is_a_clean_parser_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--ticks", "3", "--seed", "abc")
    assert exit_info.value.code == 2
    assert "invalid int value" in capsys.readouterr().err


@pytest.mark.parametrize("seed", [MIN_SEED, MAX_SEED])
def test_the_bounds_themselves_are_accepted(monkeypatch, capsys, seed):
    output = _run(monkeypatch, capsys, "--ticks", "2", "--seed", str(seed))
    assert f"random seed    : {seed} (overrides config)" in output


# --- Test F: parity with the dashboard ----------------------------------------------------------------


def test_a_cli_seed_and_a_dashboard_seed_mean_the_same_thing(monkeypatch, capsys):
    """Phase 11's whole point: a run seeded from the command line is the
    run the dashboard gives for that seed."""
    seed = 48291
    payload = run_simulation(SimulationParams(ticks=8, random_seed=seed))
    expected = [format(point.price, ">9,.4f").strip() for point in payload.price_series]

    output = _run(monkeypatch, capsys, "--ticks", "8", "--seed", str(seed))
    assert _prices(output) == expected


def test_both_front_ends_share_one_seed_bound(monkeypatch, capsys):
    """The bound lives with the derivation it bounds; neither front end
    carries a copy, so neither can drift from the other."""
    assert (dashboard_data.MIN_SEED, dashboard_data.MAX_SEED) == (MIN_SEED, MAX_SEED)
    assert "MIN_SEED = " not in Path(dashboard_data.__file__).read_text()
    assert "MIN_SEED = " not in SCRIPT.read_text()
