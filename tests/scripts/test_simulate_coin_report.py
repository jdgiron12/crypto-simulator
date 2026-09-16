"""The demo CLI's opt-in ``--report`` flag (Phase 9, Step 8b), run in-process.

The flag must be an observer: without it the output is unchanged (the
compatibility grid also pins those bytes), and with it the ordinary output
is printed exactly as before and the rendered analytics report follows.
The report must be the one ``build_report``/``render_report`` produce for
the same run.
"""

import runpy
from pathlib import Path

import pytest

from crypto_simulator.analytics import build_report, render_report
from crypto_simulator.config import get_settings
from crypto_simulator.services.coin_simulation import build_coin_simulator

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"
REPORT_START = "\n=============================================================================="


def _run(monkeypatch, capsys, *args):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return capsys.readouterr().out


def _split(output):
    index = output.index(REPORT_START + "\nSIMULATION REPORT")
    return output[:index], output[index + 1:]


COMBINATIONS = [
    ("--ticks", "30"),
    ("--ticks", "45", "--pricing-mode", "amm", "--no-whales"),
    ("--ticks", "40", "--events", "--random-events", "--psychology", "--whale-observation",
     "--scenario", "pump_and_dump"),
    ("--ticks", "40", "--pricing-mode", "amm", "--no-whales", "--events", "--psychology", "--scenario",
     "wash_trading"),
    ("--ticks", "25", "--no-traders"),
    ("--ticks", "3"),
]


def test_the_default_run_prints_no_report(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "30")
    assert "SIMULATION REPORT" not in output


@pytest.mark.parametrize("flags", COMBINATIONS, ids=" ".join)
def test_report_output_is_the_unchanged_run_output_followed_by_the_report(monkeypatch, capsys, flags):
    plain = _run(monkeypatch, capsys, *flags)
    with_report = _run(monkeypatch, capsys, *flags, "--report")
    before, report = _split(with_report)
    assert before == plain
    assert report.startswith("==============================================================================\n"
                             "SIMULATION REPORT\n")
    for heading in ("MARKET", "TRADERS", "WHALE ACTIVITY", "EVENT WINDOWS", "PSYCHOLOGY", "MANIPULATION",
                    "REGIMES"):
        assert f"\n{heading}\n" in report


@pytest.mark.parametrize("flags, pricing_mode, include_whales", [
    (("--ticks", "30"), None, True),
    (("--ticks", "30", "--pricing-mode", "amm", "--no-whales"), "amm", False),
])
def test_the_printed_report_is_build_report_of_the_same_run(monkeypatch, capsys, flags, pricing_mode,
                                                             include_whales):
    _, printed = _split(_run(monkeypatch, capsys, *flags, "--report"))
    sim = build_coin_simulator(get_settings(), pricing_mode=pricing_mode, include_whales=include_whales)
    start = {t.trader_id: (t.wallet.cash, t.wallet.coins) for t in sim.traders}
    ticks = sim.run(30)
    end = {t.trader_id: (t.wallet.cash, t.wallet.coins) for t in sim.traders}
    expected = render_report(build_report(ticks, initial_price=sim.coin.starting_price,
                                          total_supply=sim.coin.initial_supply, start_balances=start,
                                          end_balances=end))
    assert printed == expected


def test_the_report_is_deterministic(monkeypatch, capsys):
    flags = ("--ticks", "40", "--events", "--random-events", "--psychology", "--scenario", "pump_and_dump",
             "--report")
    assert _run(monkeypatch, capsys, *flags) == _run(monkeypatch, capsys, *flags)


def test_unavailable_features_are_reported_as_unavailable(monkeypatch, capsys):
    _, report = _split(_run(monkeypatch, capsys, "--ticks", "30", "--report"))
    assert "unavailable: no event timeline was supplied" in report
    assert "unavailable: no psychology was recorded" in report
    assert "no whale observations recorded" in report
    assert "no manipulation fills recorded" in report


def test_enabled_features_fill_their_sections(monkeypatch, capsys):
    _, report = _split(_run(monkeypatch, capsys, "--ticks", "40", "--events", "--random-events", "--psychology",
                            "--whale-observation", "--scenario", "pump_and_dump", "--report"))
    assert "demo-listing (exchange_listing, scheduled)" in report
    assert "coverage                 complete (40 of 40 ticks" in report
    assert "observation coverage     complete (40 of 40 ticks)" in report
    assert ": recorded phases" in report
    assert "combined P&L             n/a" not in report  # the CLI supplies wallet balances


def test_scheduled_events_without_a_generator_report_scheduled_provenance(monkeypatch, capsys):
    _, report = _split(_run(monkeypatch, capsys, "--ticks", "25", "--events", "--report"))
    assert "demo-listing (exchange_listing, scheduled)" in report
    assert "provenance unknown" not in report


def test_help_lists_the_flag(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--help"])
    with pytest.raises(SystemExit):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert "--report" in capsys.readouterr().out
