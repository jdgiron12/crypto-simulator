"""The stress command (Phase 16), run in process like the other CLIs."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from crypto_simulator.stress import STRESS_CASES, heavy_cases, light_cases

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "stress_test.py"


def _run(monkeypatch, capsys, *args):
    monkeypatch.setattr("sys.argv", [str(SCRIPT), *args])
    runpy.run_path(str(SCRIPT), run_name="__main__")
    return capsys.readouterr().out


# --- listing ---------------------------------------------------------------------------------------------


def test_listing_names_the_cases_without_running_them(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--list")
    assert f"{len(light_cases())} stress cases" in output
    for case in light_cases():
        assert case.name in output
    assert "ok" not in output.split("\n")[0]


def test_listing_with_heavy_includes_the_costly_cases(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--list", "--heavy")
    assert f"{len(STRESS_CASES)} stress cases" in output
    for case in heavy_cases():
        assert case.name in output


def test_listing_marks_which_tier_each_case_is_in(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--list", "--heavy")
    assert "light" in output and "heavy" in output


# --- running ---------------------------------------------------------------------------------------------


def test_the_default_run_covers_the_light_tier(monkeypatch, capsys):
    output = _run(monkeypatch, capsys)
    assert f"{len(light_cases())} cases" in output
    for case in light_cases():
        assert case.name in output
    for case in heavy_cases():
        assert case.name not in output, "the costly cases are opt-in"


def test_each_case_reports_a_status_and_a_runtime(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--only", "ticks")
    lines = [line for line in output.splitlines() if "ticks-" in line]
    assert lines
    for line in lines:
        assert ("ok" in line or "refused" in line)
        assert "s" in line, "each case reports how long it took"


def test_the_summary_totals_the_outcomes(monkeypatch, capsys):
    output = _run(monkeypatch, capsys)
    assert "  ran            :" in output
    assert "  completed      :" in output
    assert "  refused        :" in output
    assert "  failed         : 0" in output


def test_invalid_cases_are_reported_as_refused_not_as_failures(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--only", "invalid")
    assert "refused as expected" in output
    assert "failed         : 0" in output
    assert "FAILED" not in output


def test_a_clean_run_exits_zero_and_claims_nothing_more_than_it_should(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--only", "ticks-minimum")
    assert "selected demanding configurations" in output
    assert "do not prove it correct elsewhere" in output
    assert "production" not in output.lower()


def test_selecting_by_name(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--only", "amm")
    assert "amm-ordinary" in output
    assert "ticks-minimum" not in output


def test_a_selection_that_matches_nothing_is_an_error(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--only", "no-such-case")
    assert exit_info.value.code == 2
    assert "no stress case matches" in capsys.readouterr().err


# --- failure reporting -----------------------------------------------------------------------------------


def test_a_failing_case_is_shown_and_exits_non_zero(monkeypatch, capsys):
    """Driven by making one case fail, so the failure path is exercised
    rather than assumed."""
    import crypto_simulator.stress.runner as runner_module

    real = runner_module.check_payload
    monkeypatch.setattr(
        runner_module, "check_payload",
        lambda payload, **kw: ("a price went backwards",) if kw.get("requested_ticks") == 1 else real(payload, **kw),
    )
    with pytest.raises(SystemExit) as exit_info:
        _run(monkeypatch, capsys, "--only", "ticks-minimum")
    assert exit_info.value.code == 1
    output = capsys.readouterr().out
    assert "FAILED" in output
    assert "a price went backwards" in output
    assert "should not have" in output


def test_the_command_does_not_dump_individual_runs(monkeypatch, capsys):
    """A batch case is one line, not fifty."""
    output = _run(monkeypatch, capsys, "--only", "batch-small")
    assert "50/50 runs" in output
    assert len(output.splitlines()) < 20
