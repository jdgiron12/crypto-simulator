"""The stress cases themselves (Phase 16).

The light tier runs in full here, which is the point: the suite is the
stress test. The two heavy cases are marked ``slow`` and left out of an
ordinary run — ``pytest -m slow`` or ``scripts/stress_test.py --heavy``
runs them.
"""

from __future__ import annotations

import pytest

from crypto_simulator.analytics.aggregate import aggregate_batch
from crypto_simulator.dashboard.data import run_simulation
from crypto_simulator.services.batch import MAX_BATCH_RUNS, run_batch
from crypto_simulator.services.coin_simulation import MAX_SEED, MIN_SEED
from crypto_simulator.services.simulation_params import MAX_TICKS, SimulationParams
from crypto_simulator.stress import (
    HARNESS_MAX_TRADERS,
    STRESS_CASES,
    Expectation,
    StressStatus,
    heavy_cases,
    light_cases,
    run_case,
    run_stress_suite,
)
from crypto_simulator.stress.cases import settings_for


def _case(name):
    return next(case for case in STRESS_CASES if case.name == name)


# --- the catalogue ---------------------------------------------------------------------------------------


def test_every_case_has_a_distinct_name():
    names = [case.name for case in STRESS_CASES]
    assert len(set(names)) == len(names)


def test_the_tiers_partition_the_cases():
    """Compared by name: a case carries its parameters as a mapping, so
    it is not hashable."""
    light = [case.name for case in light_cases()]
    heavy = [case.name for case in heavy_cases()]
    assert sorted(light + heavy) == sorted(case.name for case in STRESS_CASES)
    assert not set(light) & set(heavy)
    assert heavy, "the heavy tier should not be empty"


def test_a_rejected_case_must_say_what_it_expects():
    with pytest.raises(ValueError, match="must say what error it expects"):
        type(STRESS_CASES[0])(
            name="x", description="y", expectation=Expectation.REJECTED
        )


def test_the_cases_test_the_simulators_own_boundaries():
    """The numbers in the catalogue are the simulator's, not invented."""
    assert _case("ticks-maximum").params["ticks"] == MAX_TICKS
    assert _case("invalid-ticks-above-maximum").params["ticks"] == MAX_TICKS + 1
    assert _case("seed-minimum").params["random_seed"] == MIN_SEED
    assert _case("seed-maximum").params["random_seed"] == MAX_SEED
    assert _case("invalid-seed-above-maximum").params["random_seed"] == MAX_SEED + 1
    assert _case("heavy-batch-maximum").runs == MAX_BATCH_RUNS
    assert _case("invalid-batch-above-maximum").runs == MAX_BATCH_RUNS + 1


def test_the_trader_ceiling_is_the_harnesss_own():
    """The simulator defines no participant maximum; this is the
    harness's bound and Phase 16 adds none to the simulator."""
    from crypto_simulator.config import get_settings

    assert _case("traders-many").traders == HARNESS_MAX_TRADERS
    settings = get_settings()
    assert not hasattr(settings.coin, "max_traders")
    assert len(settings.coin.traders) == 5, "the configured population is untouched"


def test_a_trader_override_builds_the_requested_population():
    overridden = settings_for(_case("traders-many"))
    assert len(overridden.coin.traders) == HARNESS_MAX_TRADERS
    assert all(trader.strategy == "retail" for trader in overridden.coin.traders)
    assert len({trader.id for trader in overridden.coin.traders}) == HARNESS_MAX_TRADERS


def test_a_trader_override_leaves_the_rest_of_the_configuration_alone():
    from crypto_simulator.config import get_settings

    base = get_settings()
    overridden = settings_for(_case("traders-many"))
    assert overridden.coin.symbol == base.coin.symbol
    assert overridden.coin.initial_supply == base.coin.initial_supply
    assert overridden.coin.whales == base.coin.whales
    assert overridden.simulation == base.simulation
    assert get_settings() is base, "the application's settings are untouched"


def test_a_case_without_a_population_uses_the_configured_one():
    assert settings_for(_case("ticks-ordinary")) is None


# --- the light tier, run in full -------------------------------------------------------------------------


@pytest.mark.parametrize("case", light_cases(), ids=lambda case: case.name)
def test_each_light_case(case):
    outcome = run_case(case)
    assert outcome.ok, f"{case.name}: {outcome.error} {outcome.findings}"
    if case.expectation is Expectation.REJECTED:
        assert outcome.status is StressStatus.REJECTED
        assert case.expected_error in outcome.error
    else:
        assert outcome.status is StressStatus.PASSED
        assert outcome.findings == ()


def test_the_light_suite_as_a_whole():
    report = run_stress_suite(light_cases())
    assert report.ok
    assert len(report.failed) == 0
    assert len(report.passed) + len(report.rejected) == len(light_cases())


def test_the_suite_covers_both_pricing_modes():
    modes = {case.params.get("pricing_mode", "random_walk") for case in STRESS_CASES}
    assert {"random_walk", "amm"} <= modes


def test_the_suite_covers_both_manipulation_presets():
    scenarios = {case.params.get("scenario") for case in STRESS_CASES}
    assert {"pump_and_dump", "wash_trading"} <= scenarios


def test_the_suite_covers_the_optional_features():
    for feature in ("events", "random_events", "psychology", "whale_observation"):
        assert any(case.params.get(feature) for case in STRESS_CASES), feature


# --- what the checks actually catch ------------------------------------------------------------------------


def test_a_completed_case_really_ran_its_ticks():
    outcome = run_case(_case("ticks-maximum"))
    assert outcome.status is StressStatus.PASSED
    payload = run_simulation(SimulationParams(**dict(_case("ticks-maximum").params)))
    assert payload.simulation.completed_ticks == MAX_TICKS


def test_the_checks_reject_an_impossible_price():
    """Guarding the guard: a payload with a bad price must be caught."""
    from dataclasses import replace

    from crypto_simulator.stress.checks import check_payload

    payload = run_simulation(SimulationParams(ticks=5, random_seed=1))
    broken = replace(
        payload,
        price_series=(replace(payload.price_series[0], price=-1.0),) + payload.price_series[1:],
    )
    findings = check_payload(broken, requested_ticks=5)
    assert any("impossible price" in finding for finding in findings)


def test_the_checks_reject_a_short_run():
    from crypto_simulator.stress.checks import check_payload

    payload = run_simulation(SimulationParams(ticks=5, random_seed=1))
    findings = check_payload(payload, requested_ticks=6)
    assert any("completed 5 of 6" in finding for finding in findings)


def test_the_checks_reject_a_non_finite_value():
    from dataclasses import replace

    from crypto_simulator.stress.checks import check_payload

    payload = run_simulation(SimulationParams(ticks=5, random_seed=1))
    broken = replace(
        payload,
        price_series=(replace(payload.price_series[0], volume=float("nan")),)
        + payload.price_series[1:],
    )
    findings = check_payload(broken, requested_ticks=5)
    assert any("not finite" in finding for finding in findings)


# --- batch stress integrates with Phase 14 and Phase 15 ------------------------------------------------------


def test_a_batch_case_keeps_every_run_and_a_seed_apiece():
    outcome = run_case(_case("batch-small"))
    assert outcome.runs_completed == 50
    assert outcome.runs_failed == 0
    assert outcome.statistics.metric("close_price").count == 50


def test_a_stress_batch_can_be_aggregated_by_the_existing_analytics():
    """Phase 16 produces batches Phase 15 reads without adaptation."""
    case = _case("batch-small")
    result = run_batch(
        SimulationParams(**dict(case.params)), case.runs, runner=run_simulation
    )
    stats = aggregate_batch(result)
    assert stats.successful_runs == case.runs
    assert stats.metric("cumulative_return").count == case.runs


# --- the heavy tier --------------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("case", heavy_cases(), ids=lambda case: case.name)
def test_each_heavy_case(case):
    outcome = run_case(case)
    assert outcome.ok, f"{case.name}: {outcome.error} {outcome.findings}"
    assert outcome.status is StressStatus.PASSED


@pytest.mark.slow
def test_the_largest_batch_loses_nothing():
    outcome = run_case(_case("heavy-batch-maximum"))
    assert outcome.runs_completed == MAX_BATCH_RUNS
    assert outcome.runs_failed == 0
    assert outcome.statistics.successful_runs == MAX_BATCH_RUNS
    assert outcome.statistics.metric("close_price").count == MAX_BATCH_RUNS
