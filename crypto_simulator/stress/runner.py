"""Running the stress cases (Phase 16).

The harness owns no simulation. Every case goes through
``dashboard.data.run_simulation`` — the entry point the CLI and the
dashboard use — and a case with more than one run goes through Phase 14's
``run_batch``, which seeds the runs and collects their failures. Batch
statistics come from Phase 15's ``aggregate_batch``. Nothing here
recomputes a price, a metric or a seed.

**Accounting without a second run loop.** Conservation is checked through
the seam ``run_simulation`` already offers: a builder is injected that
constructs the simulator exactly as the default one does, then records it
and its opening ``accounting_totals()``. After the run the same simulator
is asked again and the two tallies are compared. The run itself is the
ordinary one.

**What a case produces.** An outcome: whether it did what it was supposed
to, how long it took, what went wrong if anything did, and the findings
of the invariant checks. Payloads are not kept — a thousand-run batch
would be tens of megabytes of analytics nobody reads — but a batch's
aggregate statistics are, because they are small and are the thing worth
looking at.

**Failures are structured, never swallowed.** An unexpected exception is
recorded with its type and message and the suite continues to the next,
independent case. ``BaseException`` is not caught, so an interrupt stops
the suite at once.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Iterable, Sequence

from crypto_simulator.analytics.aggregate import AggregateStatistics, aggregate_batch
from crypto_simulator.dashboard.data import run_simulation
from crypto_simulator.services.batch import run_batch
from crypto_simulator.services.coin_simulation import build_coin_simulator
from crypto_simulator.services.simulation_params import SimulationParams
from crypto_simulator.stress.cases import (
    STRESS_CASES,
    Expectation,
    StressCase,
    settings_for,
)
from crypto_simulator.stress.checks import check_accounting, check_payload

__all__ = [
    "StressOutcome",
    "StressReport",
    "StressStatus",
    "run_case",
    "run_stress_suite",
]


class StressStatus(str, Enum):
    """What became of a case."""

    #: Ran, and every check held.
    PASSED = "passed"
    #: Was refused, as a deliberately invalid case should be.
    REJECTED = "rejected"
    #: Did something it should not have: raised unexpectedly, survived a
    #: configuration that should have been refused, or broke an invariant.
    FAILED = "failed"

    @property
    def ok(self) -> bool:
        return self is not StressStatus.FAILED


@dataclass(frozen=True)
class StressOutcome:
    """One case's result."""

    case: StressCase
    status: StressStatus
    seconds: float
    runs_completed: int = 0
    runs_failed: int = 0
    error: str | None = None
    findings: tuple[str, ...] = ()
    statistics: AggregateStatistics | None = None

    @property
    def ok(self) -> bool:
        return self.status.ok


@dataclass(frozen=True)
class StressReport:
    """Every case that was run."""

    outcomes: tuple[StressOutcome, ...]
    seconds: float

    @property
    def passed(self) -> tuple[StressOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status is StressStatus.PASSED)

    @property
    def rejected(self) -> tuple[StressOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status is StressStatus.REJECTED)

    @property
    def failed(self) -> tuple[StressOutcome, ...]:
        return tuple(o for o in self.outcomes if o.status is StressStatus.FAILED)

    @property
    def ok(self) -> bool:
        """True when no case did something it should not have."""
        return not self.failed


def run_case(case: StressCase, *, settings: Any = None) -> StressOutcome:
    """Run one stress case and say what became of it."""
    started = time.perf_counter()
    try:
        outcome = _execute(case, settings)
    except Exception as exc:  # noqa: BLE001 - recorded below, never swallowed
        elapsed = time.perf_counter() - started
        return _on_error(case, exc, elapsed)
    return outcome


def _execute(case: StressCase, settings: Any) -> StressOutcome:
    started = time.perf_counter()
    overrides = settings_for(case, settings)
    # A deliberately invalid request raises here, which is the rejection
    # the case is testing; it is caught by run_case.
    params = SimulationParams(**dict(case.params))

    if case.runs == 1:
        findings, completed, failed, statistics = _run_once(params, overrides)
    else:
        findings, completed, failed, statistics = _run_many(case, params, overrides)

    if case.repeat_for_determinism and not findings:
        findings = _determinism_findings(case, params, overrides)

    elapsed = time.perf_counter() - started
    if case.expectation is Expectation.REJECTED:
        # It should not have got this far.
        return StressOutcome(
            case=case,
            status=StressStatus.FAILED,
            seconds=elapsed,
            runs_completed=completed,
            runs_failed=failed,
            findings=(f"expected to be refused with {case.expected_error!r}, but it ran",),
            statistics=statistics,
        )
    return StressOutcome(
        case=case,
        status=StressStatus.FAILED if findings else StressStatus.PASSED,
        seconds=elapsed,
        runs_completed=completed,
        runs_failed=failed,
        findings=findings,
        statistics=statistics,
    )


def _run_once(params: SimulationParams, overrides: Any):
    """One run, with its accounting watched through the builder seam."""
    ledger: list[tuple[Any, tuple[Decimal, Decimal]]] = []
    payload = run_simulation(params, settings=overrides, builder=_watching_builder(ledger))
    findings = list(check_payload(payload, requested_ticks=params.ticks))
    findings.extend(_accounting_findings(ledger, params.pricing_mode))
    return tuple(findings), 1, 0, None


def _run_many(case: StressCase, params: SimulationParams, overrides: Any):
    """A batch, run and seeded by Phase 14 and described by Phase 15."""
    ledger: list[tuple[Any, tuple[Decimal, Decimal]]] = []

    def runner(request: SimulationParams):
        return run_simulation(request, settings=overrides, builder=_watching_builder(ledger))

    result = run_batch(params, case.runs, runner=runner, settings=overrides)
    findings: list[str] = []
    for run in result.failed:
        findings.append(f"run {run.index} (seed {run.seed}) failed: {run.error}")
    for run in result.completed:
        findings.extend(
            f"run {run.index} (seed {run.seed}): {finding}"
            for finding in check_payload(run.payload, requested_ticks=params.ticks)
        )
    seeds = [run.seed for run in result.runs]
    if len(set(seeds)) != len(seeds):
        findings.append("two runs of the batch were given the same seed")
    findings.extend(_accounting_findings(ledger, params.pricing_mode))

    statistics = aggregate_batch(result)
    if statistics.successful_runs != len(result.completed):
        findings.append("the aggregate statistics disagree with the batch about what completed")
    return tuple(findings), len(result.completed), len(result.failed), statistics


def _watching_builder(ledger: list) -> Callable[..., Any]:
    """The ordinary builder, with the simulator and its opening tally
    recorded on the way past."""

    def builder(settings, **kwargs):
        simulator = build_coin_simulator(settings, **kwargs)
        ledger.append((simulator, simulator.accounting_totals()))
        return simulator

    return builder


def _accounting_findings(ledger: Sequence[tuple[Any, tuple[Decimal, Decimal]]], mode: str):
    """Conservation, for every simulator the case built."""
    if not ledger:
        return ("no simulator was built, so nothing could be checked",)
    findings: list[str] = []
    for index, (simulator, before) in enumerate(ledger):
        findings.extend(
            f"run {index}: {finding}"
            for finding in check_accounting(before, simulator.accounting_totals(), pricing_mode=mode)
        )
    return tuple(findings)


def _determinism_findings(case: StressCase, params: SimulationParams, overrides: Any):
    """The same request, run again, must give the same run."""
    from crypto_simulator.dashboard.data import payload_to_dict

    if case.runs != 1:
        return ()
    first = payload_to_dict(run_simulation(params, settings=overrides))
    second = payload_to_dict(run_simulation(params, settings=overrides))
    if first != second:
        return ("running the same request twice gave two different runs",)
    return ()


def _on_error(case: StressCase, exc: Exception, elapsed: float) -> StressOutcome:
    """An exception is the right answer for an invalid case and the wrong
    one for every other."""
    message = f"{type(exc).__name__}: {exc}"
    if case.expectation is Expectation.REJECTED:
        if case.expected_error and case.expected_error not in str(exc):
            return StressOutcome(
                case=case,
                status=StressStatus.FAILED,
                seconds=elapsed,
                error=message,
                findings=(
                    f"refused, but not for the expected reason "
                    f"(wanted {case.expected_error!r})",
                ),
            )
        return StressOutcome(case=case, status=StressStatus.REJECTED, seconds=elapsed, error=message)
    return StressOutcome(case=case, status=StressStatus.FAILED, seconds=elapsed, error=message)


def run_stress_suite(
    cases: Iterable[StressCase] | None = None, *, settings: Any = None
) -> StressReport:
    """Run every case in order and collect the outcomes.

    One case's failure does not stop the next: the cases are independent,
    and a suite that stopped at the first problem would hide the rest.
    """
    started = time.perf_counter()
    outcomes = tuple(run_case(case, settings=settings) for case in (cases or STRESS_CASES))
    return StressReport(outcomes=outcomes, seconds=time.perf_counter() - started)
