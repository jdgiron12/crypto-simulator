"""The demo CLI (scripts/simulate_coin.py), run in-process."""

import runpy
from pathlib import Path

import pytest

from crypto_simulator.config import EventSettings, get_settings

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


def _run(monkeypatch, capsys, *args):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return capsys.readouterr().out


def _row(output, tick):
    return next(line for line in output.splitlines() if line.startswith(f"{tick:>4}  "))


def test_default_run_shows_no_news(monkeypatch, capsys):
    output = _run(monkeypatch, capsys)
    assert "pricing mode   : random_walk" in output
    assert "news" not in output.lower()
    assert sum(1 for line in output.splitlines() if line[:4].strip().isdigit()) == 20


def test_events_flag_shows_the_demo_schedule_as_ground_truth(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--events")
    assert "news events    : 2 scheduled (drift_per_sentiment 0.0)" in output
    assert "news (ground truth)" in output
    assert "demo-" not in _row(output, 3)
    assert "demo-listing active 1.00" in _row(output, 4)
    assert "demo-listing decaying 0.80" in _row(output, 8)
    assert "demo-incident active 1.00" in _row(output, 13)
    assert "demo-incident decaying 0.20" in _row(output, 19)
    assert "demo-" not in _row(output, 12) and "demo-" not in _row(output, 20)
    assert "News schedule (simulator ground truth, not observable market data):" in output
    assert "active ticks 4-7, fading ticks 8-11" in output
    assert "active ticks 13-15, fading ticks 16-19" in output


def test_events_output_makes_no_claims_about_what_the_news_did(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--events", "--ticks", "25").lower()
    for claim in ("caused", "detected", "because of", "due to the", "impact of the event", "event impact"):
        assert claim not in output


def test_events_work_in_amm_mode_with_exact_accounting(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--events", "--pricing-mode", "amm", "--no-whales", "--ticks", "25")
    assert "pricing mode   : amm" in output
    assert "demo-incident active 1.00" in _row(output, 13)
    assert "conserved exactly : True" in output


def test_events_flag_does_not_change_the_cached_settings(monkeypatch, capsys):
    _run(monkeypatch, capsys, "--events")
    assert get_settings().coin.events == EventSettings()


def test_invalid_combinations_still_fail_through_the_parser(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _run(monkeypatch, capsys, "--events", "--pricing-mode", "amm")  # whales aren't supported in amm
    assert "Whales are not supported" in capsys.readouterr().err


def test_random_events_flag_generates_news_through_the_config_path(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--random-events", "--ticks", "40")
    assert "news events    : 0 scheduled, random 0.1/tick (drift_per_sentiment 0.0)" in output
    rows = [line for line in output.splitlines() if line[:4].strip().isdigit()]
    assert any("random-000001 active" in row for row in rows)
    assert "News events, scheduled and random (simulator ground truth, not observable market data):" in output
    assert get_settings().coin.events == EventSettings()


def test_scheduled_and_random_demo_flags_combine(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--events", "--random-events", "--ticks", "30")
    assert "news events    : 2 scheduled, random 0.1/tick" in output
    assert "demo-listing" in output and "random-000001" in output


def test_event_analysis_is_shown_for_event_runs_and_labels_its_sources(monkeypatch, capsys):
    assert "Event analysis" not in _run(monkeypatch, capsys)
    output = _run(monkeypatch, capsys, "--events")
    section = output[output.index("Event analysis"):]
    assert "observed market data over each event's ground-truth window; descriptive, not causal" in section
    assert "demo-listing (exchange_listing), event window ticks 4-7" in section
    assert "ground truth : severity 0.80, sentiment +0.56" in section
    assert "event-window return" in section and "realized volatility" in section
    assert "overlapping  : none" in section


def test_amm_random_event_analysis_reports_pool_activity_without_causal_claims(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--random-events", "--pricing-mode", "amm", "--no-whales", "--ticks", "60")
    section = output[output.index("Event analysis"):]
    assert "random-000001" in section and "pool:" in section and "swaps, reserves" in section
    for claim in ("caused", "detected", "because of", "due to the", "impact of the event", "event impact"):
        assert claim not in section.lower()


def test_event_analysis_labels_scheduled_and_random_events(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--events", "--random-events", "--ticks", "30")
    lines = output[output.index("Event analysis"):].splitlines()
    source = {}
    for header, truth in zip(lines, lines[1:]):
        if header.startswith("  ") and not header.startswith("   ") and "ground truth" in truth:
            source[header.split()[0]] = truth.rsplit(", ", 1)[1]
    assert source == {
        "demo-listing": "scheduled event",
        "random-000001": "random event",
        "demo-incident": "scheduled event",
    }


# --- argument validation and help (Phase 23) -------------------------------------------------------------


@pytest.mark.parametrize("args", [("--ticks", "0"), ("--ticks", "-1"), ("--ticks=-5",)])
def test_a_tick_count_below_one_is_a_clean_parser_error(monkeypatch, capsys, args):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, *args)
    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert "argument --ticks: ticks must be at least 1" in captured.err
    assert "Traceback" not in captured.err and captured.out == ""


def test_a_non_integer_tick_count_is_a_clean_parser_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--ticks", "abc")
    assert exit_info.value.code == 2
    assert "argument --ticks: invalid int value: 'abc'" in capsys.readouterr().err


def test_one_tick_is_still_a_valid_run(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "1")
    assert sum(1 for line in output.splitlines() if line[:4].strip().isdigit()) == 1


def test_help_no_longer_calls_psychology_uncalibrated_and_keeps_its_examples(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--help")
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "uncalibrated" not in help_text
    assert "Turn on market psychology (off by default)" in " ".join(help_text.split())
    # The usage examples keep one command per line instead of being reflowed.
    assert "\n    python scripts/simulate_coin.py --ticks 20 --seed 48291\n" in help_text
