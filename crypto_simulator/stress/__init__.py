"""Stress testing the existing simulator (Phase 16).

Runs demanding but valid configurations, and deliberately invalid ones,
through the simulator's ordinary entry points, then checks that what came
back is possible. It adds no market mechanic, no participant type and no
limit; it exercises what is already there.
"""

from crypto_simulator.stress.cases import (
    HARNESS_MAX_TRADERS,
    STRESS_CASES,
    Expectation,
    StressCase,
    heavy_cases,
    light_cases,
)
from crypto_simulator.stress.checks import check_accounting, check_payload
from crypto_simulator.stress.runner import (
    StressOutcome,
    StressReport,
    StressStatus,
    run_case,
    run_stress_suite,
)

__all__ = [
    "HARNESS_MAX_TRADERS",
    "STRESS_CASES",
    "Expectation",
    "StressCase",
    "StressOutcome",
    "StressReport",
    "StressStatus",
    "check_accounting",
    "check_payload",
    "heavy_cases",
    "light_cases",
    "run_case",
    "run_stress_suite",
]
