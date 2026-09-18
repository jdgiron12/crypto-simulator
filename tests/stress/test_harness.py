"""The stress harness itself (Phase 16).

These test the harness — that it runs what it is given, judges outcomes
correctly, records failures instead of swallowing them, and adds no
simulation of its own. The stress *cases* are exercised in
``test_cases.py``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from crypto_simulator.stress import (
    Expectation,
    StressCase,
    StressStatus,
    check_accounting,
    run_case,
    run_stress_suite,
)
from crypto_simulator.stress import runner as runner_module


def _case(**kwargs) -> StressCase:
    kwargs.setdefault("name", "under-test")
    kwargs.setdefault("description", "a case")
    kwargs.setdefault("params", {"ticks": 5, "random_seed": 48291})
    return StressCase(**kwargs)


# --- running cases ---------------------------------------------------------------------------------------


def test_a_valid_case_passes():
    outcome = run_case(_case())
    assert outcome.status is StressStatus.PASSED
    assert outcome.ok
    assert outcome.findings == ()
    assert outcome.runs_completed == 1
    assert outcome.seconds >= 0


def test_an_invalid_case_is_refused_and_that_is_a_pass():
    outcome = run_case(
        _case(
            params={"ticks": 0},
            expectation=Expectation.REJECTED,
            expected_error="ticks must be between",
        )
    )
    assert outcome.status is StressStatus.REJECTED
    assert outcome.ok, "being refused is what an invalid case is for"
    assert "ticks must be between" in outcome.error


def test_a_case_refused_for_the_wrong_reason_fails():
    """Being refused is not enough; it must be refused for the stated
    reason, or the case is no longer testing what it says."""
    outcome = run_case(
        _case(
            params={"ticks": 0},
            expectation=Expectation.REJECTED,
            expected_error="whales are not supported",
        )
    )
    assert outcome.status is StressStatus.FAILED
    assert "not for the expected reason" in outcome.findings[0]


def test_a_case_that_should_have_been_refused_but_ran_fails():
    outcome = run_case(
        _case(expectation=Expectation.REJECTED, expected_error="something that never happens")
    )
    assert outcome.status is StressStatus.FAILED
    assert "but it ran" in outcome.findings[0]


def test_an_unexpected_failure_is_recorded_not_swallowed(monkeypatch):
    monkeypatch.setattr(
        runner_module, "run_simulation",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the simulator broke")),
    )
    outcome = run_case(_case())
    assert outcome.status is StressStatus.FAILED
    assert outcome.error == "RuntimeError: the simulator broke"


def test_an_interrupt_stops_the_harness_rather_than_being_recorded(monkeypatch):
    monkeypatch.setattr(
        runner_module, "run_simulation",
        lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    with pytest.raises(KeyboardInterrupt):
        run_case(_case())


def test_a_broken_invariant_fails_the_case(monkeypatch):
    monkeypatch.setattr(runner_module, "check_payload", lambda *a, **k: ("price went backwards",))
    outcome = run_case(_case())
    assert outcome.status is StressStatus.FAILED
    assert outcome.findings == ("price went backwards",)


# --- suites ----------------------------------------------------------------------------------------------


def test_a_suite_runs_every_case_in_order():
    cases = (_case(name="one"), _case(name="two"), _case(name="three"))
    report = run_stress_suite(cases)
    assert [o.case.name for o in report.outcomes] == ["one", "two", "three"]
    assert report.ok


def test_a_failing_case_does_not_stop_the_ones_after_it():
    cases = (
        _case(name="fine-before"),
        _case(name="doomed", expectation=Expectation.REJECTED, expected_error="never happens"),
        _case(name="fine-after"),
    )
    report = run_stress_suite(cases)
    assert [o.case.name for o in report.failed] == ["doomed"]
    assert [o.case.name for o in report.passed] == ["fine-before", "fine-after"]
    assert not report.ok


def test_a_report_splits_the_outcomes():
    cases = (
        _case(name="runs"),
        _case(name="refused", params={"ticks": 0},
              expectation=Expectation.REJECTED, expected_error="ticks must be between"),
    )
    report = run_stress_suite(cases)
    assert len(report.passed) == 1 and len(report.rejected) == 1 and not report.failed
    assert report.ok
    assert report.seconds >= 0


# --- batches, reusing Phase 14 and Phase 15 ----------------------------------------------------------------


def test_a_multi_run_case_goes_through_the_batch_runner():
    outcome = run_case(_case(params={"ticks": 10, "random_seed": 48291}, runs=6))
    assert outcome.status is StressStatus.PASSED
    assert outcome.runs_completed == 6
    assert outcome.runs_failed == 0


def test_a_batch_case_carries_phase_15_statistics():
    outcome = run_case(_case(params={"ticks": 10, "random_seed": 48291}, runs=5))
    assert outcome.statistics is not None
    assert outcome.statistics.successful_runs == 5
    assert outcome.statistics.metric("close_price").count == 5


def test_a_single_run_case_keeps_no_statistics():
    """Aggregating one run would be a distribution of one."""
    assert run_case(_case()).statistics is None


def test_a_batch_case_notices_a_failed_run():
    """Whales with AMM are refused per run, so every run fails and the
    case does not quietly report success."""
    outcome = run_case(
        _case(params={"ticks": 5, "pricing_mode": "amm", "include_whales": True,
                      "random_seed": 1}, runs=3)
    )
    assert outcome.status is StressStatus.FAILED
    assert outcome.runs_failed == 3
    assert any("Whales are not supported" in finding for finding in outcome.findings)


def test_no_payloads_are_retained():
    """A thousand-run batch would be tens of megabytes of analytics that
    nothing reads."""
    outcome = run_case(_case(params={"ticks": 10, "random_seed": 1}, runs=10))
    assert not hasattr(outcome, "payloads")
    assert not hasattr(outcome, "runs")


# --- determinism -------------------------------------------------------------------------------------------


def test_a_case_marked_for_determinism_is_run_twice_and_compared():
    outcome = run_case(_case(repeat_for_determinism=True))
    assert outcome.status is StressStatus.PASSED


def test_a_non_deterministic_run_would_be_caught(monkeypatch):
    """Guarding the guard: if two runs of one request ever differed, the
    determinism check must say so."""
    payloads = iter([{"a": 1}, {"a": 2}])
    monkeypatch.setattr(runner_module, "run_simulation", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "check_payload", lambda *a, **k: ())
    monkeypatch.setattr(runner_module, "_accounting_findings", lambda *a, **k: ())
    monkeypatch.setattr(
        "crypto_simulator.dashboard.data.payload_to_dict", lambda payload: next(payloads)
    )
    outcome = run_case(_case(repeat_for_determinism=True))
    assert outcome.status is StressStatus.FAILED
    assert "two different runs" in outcome.findings[0]


def test_the_same_case_twice_gives_the_same_outcome():
    first, second = run_case(_case()), run_case(_case())
    assert (first.status, first.findings, first.runs_completed) == (
        second.status, second.findings, second.runs_completed
    )


# --- accounting --------------------------------------------------------------------------------------------


def test_accounting_that_balances_has_nothing_to_report():
    totals = (Decimal("1000000"), Decimal("1110000"))
    assert check_accounting(totals, totals, pricing_mode="amm") == ()


def test_amm_accounting_must_balance_exactly():
    before = (Decimal("1000000"), Decimal("1110000"))
    after = (Decimal("1000000.0000000000000001"), Decimal("1110000"))
    findings = check_accounting(before, after, pricing_mode="amm")
    assert findings and "not conserved exactly in AMM mode" in findings[0]


def test_random_walk_accounting_tolerates_representation_drift():
    """Float wallets accumulate rounding over a long run; that is not a
    leak, and the README says so."""
    before = (Decimal("950000"), Decimal("1110000"))
    after = (Decimal("949999.99999999997999111"), Decimal("1110000.0000000003447269"))
    assert check_accounting(before, after, pricing_mode="random_walk") == ()


def test_random_walk_accounting_still_catches_a_real_loss():
    before = (Decimal("950000"), Decimal("1110000"))
    after = (Decimal("949000"), Decimal("1110000"))  # a thousand coins gone
    findings = check_accounting(before, after, pricing_mode="random_walk")
    assert findings and "beyond rounding" in findings[0]


def test_uncaptured_accounting_is_a_finding_not_a_pass():
    assert check_accounting(None, None, pricing_mode="amm") == (
        "the run's accounting totals were never captured",
    )


def test_accounting_is_watched_through_the_builder_seam():
    """The harness must not rebuild the run loop to see the simulator: it
    injects a builder into the ordinary entry point."""
    source = Path(runner_module.__file__).read_text()
    assert "builder=_watching_builder" in source
    assert "accounting_totals()" in source
    assert "sim.run(" not in source, "the harness must not drive a simulator itself"


# --- the harness owns no simulation ---------------------------------------------------------------------------


def test_the_harness_runs_simulations_only_through_the_existing_entry_points():
    source = Path(runner_module.__file__).read_text()
    assert "run_simulation" in source
    assert "run_batch" in source
    assert "aggregate_batch" in source
    for reinvented in ("def _step", "random.Random", "MarketEngine", "statistics.mean"):
        assert reinvented not in source, f"{reinvented} suggests logic that already exists"
