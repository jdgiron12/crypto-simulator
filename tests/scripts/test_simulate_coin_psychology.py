"""The demo CLI's opt-in psychology observations (--psychology)."""

import pytest

from crypto_simulator.config import get_settings
from tests.scripts.test_simulate_coin import _row, _run

CAUSAL_WORDS = ("caused", "because", "impact", "effect", "drives", "driven", "proves", "predicts", "due to")


def _section(output):
    start = output.index("Psychology observations")
    end = output.find("\ntrader ", start)
    return output[start:] if end == -1 else output[start:end]


def test_default_output_has_no_psychology(monkeypatch, capsys):
    output = _run(monkeypatch, capsys)
    assert "psychology" not in output.lower()


def test_psychology_flag_prints_the_observations(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--psychology", "--ticks", "30")
    assert "psychology     : on (calibration deferred)" in output
    section = _section(output)
    assert "ticks with psychology: 30 of 30" in section
    for name in ("fear", "fomo", "conviction", "uncertainty"):
        assert f"\n  {name:<12} " in section
    assert "longest run >=0.75" in section
    assert "Descriptive comparison — dominant component vs. trader fills on the same ticks:" in section
    assert "Event-period comparison" not in section  # no events configured


def test_psychology_flag_leaves_the_tick_rows_format_alone(monkeypatch, capsys):
    plain = _run(monkeypatch, capsys, "--ticks", "5")
    with_psychology = _run(monkeypatch, capsys, "--ticks", "5", "--psychology")
    assert _row(plain, 1) == _row(with_psychology, 1)  # tick 1: psychology is neutral, so nobody reacts yet


def test_psychology_with_events_adds_the_event_period_comparison(monkeypatch, capsys):
    section = _section(_run(monkeypatch, capsys, "--psychology", "--events", "--ticks", "30"))
    assert "Event-period comparison —" in section
    assert "ticks with a live event vs." in section
    assert "(ground-truth timing)" in section


def test_psychology_works_in_amm_mode_with_exact_accounting(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--psychology", "--pricing-mode", "amm", "--no-whales", "--ticks", "30")
    assert "Psychology observations" in output
    assert "conserved exactly : True" in output


@pytest.mark.parametrize("flags", [(), ("--events",), ("--random-events", "--pricing-mode", "amm", "--no-whales")])
def test_the_psychology_section_makes_no_causal_claims(monkeypatch, capsys, flags):
    section = _section(_run(monkeypatch, capsys, "--psychology", "--ticks", "40", *flags)).lower()
    for word in CAUSAL_WORDS:
        assert word not in section, word


def test_psychology_flag_does_not_touch_the_cached_settings(monkeypatch, capsys):
    before = get_settings()
    _run(monkeypatch, capsys, "--psychology", "--events")
    assert get_settings() == before
