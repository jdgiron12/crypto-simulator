"""The dashboard's scenario-comparison entry point (Phase 20, Step 7).

A comparison is one Phase 14 ``run_batch`` per explicitly selected
configuration — pricing mode, manipulation preset, Phase 17 market
condition — from one shared base seed, with every other field of the request
held constant, each reduced by Step 6's ``reduce_batch``. The plan is checked
before anything runs; nothing the simulator refuses is quietly adjusted.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from dataclasses import replace

import pytest

import crypto_simulator.dashboard.data as data_module
from crypto_simulator.analytics.aggregate import aggregate_batch
from crypto_simulator.analytics.tick_series import TickSeries
from crypto_simulator.dashboard.data import (
    COMPARISON_MARKET_CONDITIONS,
    COMPARISON_SCENARIOS,
    MARKET_CONDITION_LABELS,
    MAX_COMPARISON_RUNS,
    MAX_DASHBOARD_BATCH_RUNS,
    PRICING_MODE_LABELS,
    PRICING_MODES,
    SCENARIO_LABELS,
    SCENARIOS,
    ComparisonConfiguration,
    DashboardBatch,
    DashboardPayload,
    PricePoint,
    ScenarioComparison,
    SimulationParams,
    comparison_configurations,
    comparison_to_dict,
    plan_comparison,
    plan_to_dict,
    reduce_batch,
    run_dashboard_comparison,
    run_dashboard_simulation,
    run_simulation,
)
from crypto_simulator.services import batch as batch_module
from crypto_simulator.services.batch import MAX_BATCH_RUNS, batch_seed, run_batch
from crypto_simulator.services.market_conditions import MARKET_CONDITION_NAMES, MARKET_CONDITIONS

HELD = SimulationParams(ticks=12, include_whales=False, events=True)
SEED = 4242
CONDITIONS = comparison_configurations(["random_walk"], [None], [None, "bull", "bear"])


@pytest.fixture(scope="module")
def comparison():
    return run_dashboard_comparison(HELD, CONDITIONS, 3, base_seed=SEED)


def _failing(predicate):
    def runner(params):
        if predicate(params):
            raise RuntimeError(f"refused {params.market_condition} seed {params.random_seed}")
        return run_simulation(params)

    return runner


# --- configurations -------------------------------------------------------------------------------------


def test_the_comparison_values_are_the_existing_ones_and_none():
    assert COMPARISON_SCENARIOS == (None, *SCENARIOS) == (None, "pump_and_dump", "wash_trading")
    assert COMPARISON_MARKET_CONDITIONS == (None, *MARKET_CONDITION_NAMES) == (None, "bear", "bull", "meme")
    assert set(PRICING_MODE_LABELS) == set(PRICING_MODES)
    assert set(SCENARIO_LABELS) == set(COMPARISON_SCENARIOS)
    assert set(MARKET_CONDITION_LABELS) == set(COMPARISON_MARKET_CONDITIONS)
    assert set(MARKET_CONDITIONS) == {"bull", "bear", "meme"}


def test_configurations_are_every_selected_combination_in_canonical_order():
    configs = comparison_configurations(["amm", "random_walk"], ["wash_trading", None], ["bull"])
    assert configs == (
        ComparisonConfiguration("random_walk", None, "bull"),
        ComparisonConfiguration("random_walk", "wash_trading", "bull"),
        ComparisonConfiguration("amm", None, "bull"),
        ComparisonConfiguration("amm", "wash_trading", "bull"),
    )
    assert comparison_configurations(["random_walk", "random_walk"], [None], [None]) == (
        ComparisonConfiguration("random_walk", None, None),)


def test_an_empty_dimension_gives_no_configurations():
    assert comparison_configurations(["random_walk"], [], [None]) == ()


@pytest.mark.parametrize("args", [(["hybrid"], [None], [None]), (["amm"], ["spoofing"], [None]),
                                  (["amm"], [None], ["crash"])])
def test_unknown_values_are_refused(args):
    with pytest.raises(ValueError, match="unknown"):
        comparison_configurations(*args)


def test_labels_name_every_dimension():
    assert ComparisonConfiguration("random_walk", None, None).label == "RW | No manipulation | Neutral (no preset)"
    assert ComparisonConfiguration("random_walk", "pump_and_dump", "bull").label == "RW | Pump & dump | Bull"
    assert ComparisonConfiguration("amm", "wash_trading", "meme").label == "AMM | Wash trading | Meme"


# --- the plan -------------------------------------------------------------------------------------------


def test_a_valid_plan_counts_the_simulations_and_names_what_is_compared():
    plan = plan_comparison(HELD, CONDITIONS, 5)
    assert plan.problems == ()
    assert (plan.configuration_count, plan.runs_per_configuration, plan.total_runs) == (3, 5, 15)
    assert plan.compared_dimensions == ("market condition",)
    assert plan.labels == tuple(c.label for c in CONDITIONS)
    assert plan.held_constant == HELD
    configs = comparison_configurations(["random_walk", "amm"], [None, "pump_and_dump"], [None])
    assert plan_comparison(HELD, configs, 2).compared_dimensions == ("pricing mode", "manipulation scenario")
    assert plan_comparison(HELD, configs[:1], 2).compared_dimensions == ()


def test_amm_with_whales_is_reported_not_adjusted():
    configs = comparison_configurations(["random_walk", "amm"], [None], [None])
    plan = plan_comparison(replace(HELD, include_whales=True), configs, 2)
    assert len(plan.problems) == 1
    assert "AMM configurations cannot run with whales" in plan.problems[0]
    assert "Turn off 'Whales'" in plan.problems[0]
    assert plan.held_constant.include_whales is True
    assert plan_comparison(replace(HELD, include_whales=True), configs[:1], 2).problems == ()


def test_the_total_budget_and_per_configuration_limit_are_reported():
    assert MAX_COMPARISON_RUNS == 400 and MAX_DASHBOARD_BATCH_RUNS == 200 and MAX_BATCH_RUNS == 1000
    four = comparison_configurations(["random_walk"], [None], list(COMPARISON_MARKET_CONDITIONS))
    assert plan_comparison(HELD, four, 100).problems == ()
    over = plan_comparison(HELD, four, 101)
    assert over.total_runs == 404
    assert "404 simulations, above the dashboard comparison limit of 400" in over.problems[0]
    assert "between 1 and 200" in plan_comparison(HELD, four[:1], 201).problems[0]
    assert "between 1 and 200" in plan_comparison(HELD, four[:1], 0).problems[0]


def test_an_empty_selection_is_reported():
    assert "Select at least one" in plan_comparison(HELD, (), 5).problems[0]


def test_plan_to_dict_is_plain(comparison):
    plan = plan_to_dict(plan_comparison(HELD, CONDITIONS, 3))
    assert json.loads(json.dumps(plan)) == plan
    with pytest.raises(TypeError, match="ComparisonPlan"):
        plan_to_dict(comparison)


# --- execution ------------------------------------------------------------------------------------------


def test_the_default_runner_is_run_simulation():
    default = inspect.signature(run_dashboard_comparison).parameters["runner"].default
    assert default is run_simulation and default is not run_dashboard_simulation


def test_one_run_batch_per_configuration_from_the_shared_seed(monkeypatch):
    calls = []

    def spy(params, runs, **kwargs):
        calls.append((params, runs, kwargs))
        return run_batch(params, runs, **kwargs)

    monkeypatch.setattr(data_module, "run_batch", spy)
    run_dashboard_comparison(HELD, CONDITIONS, 2, base_seed=SEED)
    assert len(calls) == 3
    for (params, runs, kwargs), config in zip(calls, CONDITIONS):
        assert runs == 2
        assert kwargs["base_seed"] == SEED
        assert kwargs["runner"] is run_simulation
        assert (params.pricing_mode, params.scenario, params.market_condition) == (
            config.pricing_mode, config.scenario, config.market_condition)
        assert replace(params, pricing_mode=HELD.pricing_mode, scenario=HELD.scenario,
                       market_condition=HELD.market_condition) == replace(HELD, random_seed=SEED)


def test_each_group_is_the_step_6_reduction_of_its_batch(comparison):
    for group, config in zip(comparison.groups, CONDITIONS):
        params = replace(HELD, market_condition=config.market_condition)
        reference = run_batch(params, 3, runner=run_simulation, base_seed=SEED)
        assert isinstance(group.batch, DashboardBatch)
        assert group.batch == reduce_batch(reference)
        assert group.batch.aggregate == aggregate_batch(reference)


def test_groups_carry_their_configuration(comparison):
    assert [g.label for g in comparison.groups] == [c.label for c in CONDITIONS]
    # Canonical order (``MARKET_CONDITION_NAMES`` is sorted), not selection order.
    assert [g.market_condition for g in comparison.groups] == [None, "bear", "bull"]
    assert all(g.pricing_mode == "random_walk" and g.scenario is None for g in comparison.groups)
    assert [g.batch.params.market_condition for g in comparison.groups] == [None, "bear", "bull"]


def test_the_comparison_records_what_was_held_constant(comparison):
    assert isinstance(comparison, ScenarioComparison)
    assert comparison.held_constant == replace(HELD, random_seed=SEED)
    assert (comparison.base_seed, comparison.runs_per_configuration) == (SEED, 3)
    assert comparison.compared_dimensions == ("market condition",)
    for group in comparison.groups:
        batch_params = group.batch.params
        assert (batch_params.ticks, batch_params.include_whales, batch_params.events) == (12, False, True)


def test_corresponding_runs_share_derived_seeds(comparison):
    expected = [batch_seed(SEED, i) for i in range(3)]
    for group in comparison.groups:
        assert group.batch.base_seed == SEED
        assert [run.seed for run in group.batch.runs] == expected


def test_the_configurations_do_differ(comparison):
    closes = [tuple(run.metrics["close_price"] for run in group.batch.runs) for group in comparison.groups]
    assert len(set(closes)) == 3


def test_the_same_comparison_is_the_same_result(comparison):
    assert run_dashboard_comparison(HELD, CONDITIONS, 3, base_seed=SEED) == comparison


@pytest.mark.parametrize("seed", [None, -1, True, 1.5])
def test_the_base_seed_must_be_given_and_valid(seed, monkeypatch):
    monkeypatch.setattr(data_module, "run_batch", lambda *a, **k: pytest.fail("nothing should run"))
    with pytest.raises(ValueError, match="base_seed"):
        run_dashboard_comparison(HELD, CONDITIONS, 2, base_seed=seed)


def test_an_invalid_plan_runs_nothing(monkeypatch):
    monkeypatch.setattr(data_module, "run_batch", lambda *a, **k: pytest.fail("nothing should run"))
    configs = comparison_configurations(["amm"], [None], [None])
    with pytest.raises(ValueError, match="cannot run with whales"):
        run_dashboard_comparison(replace(HELD, include_whales=True), configs, 2, base_seed=SEED)
    with pytest.raises(ValueError, match="comparison limit"):
        run_dashboard_comparison(HELD, CONDITIONS, 200, base_seed=SEED)


def test_amm_runs_once_whales_are_off():
    configs = comparison_configurations(["random_walk", "amm"], [None], ["bull"])
    result = run_dashboard_comparison(HELD, configs, 2, base_seed=SEED)
    assert [g.batch.successful_runs for g in result.groups] == [2, 2]
    assert [g.batch.params.pricing_mode for g in result.groups] == ["random_walk", "amm"]


# --- what is kept ---------------------------------------------------------------------------------------


def _walk(value):
    yield value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _walk(item)


def test_no_payload_price_path_or_tick_series_is_kept(comparison):
    assert not any(isinstance(v, (DashboardPayload, PricePoint, TickSeries, batch_module.BatchRun,
                                  batch_module.BatchResult)) for v in _walk(comparison))
    serialized = json.dumps(comparison_to_dict(comparison))
    for key in ("price_series", "tick_series", "report", "psychology_market", "trades"):
        assert f'"{key}"' not in serialized, key


def test_the_serialized_comparison_is_plain_and_small(comparison):
    as_dict = comparison_to_dict(comparison)
    assert list(as_dict) == ["held_constant", "base_seed", "runs_per_configuration", "compared_dimensions",
                             "groups"]
    assert list(as_dict["groups"][0]) == ["label", "pricing_mode", "scenario", "market_condition", "batch"]
    assert json.loads(json.dumps(as_dict)) == as_dict
    assert len(json.dumps(as_dict)) < 50_000
    with pytest.raises(TypeError, match="ScenarioComparison"):
        comparison_to_dict(comparison.groups[0].batch)


# --- failures -------------------------------------------------------------------------------------------


def test_partial_and_total_failures_stay_with_their_configuration():
    runner = _failing(lambda p: p.market_condition == "bear" or (
        p.market_condition == "bull" and p.random_seed == batch_seed(SEED, 1)))
    result = run_dashboard_comparison(HELD, CONDITIONS, 3, base_seed=SEED, runner=runner)
    neutral, bear, bull = result.groups
    assert (neutral.batch.successful_runs, neutral.batch.failed_runs) == (3, 0)
    assert (bull.batch.successful_runs, bull.batch.failed_runs) == (2, 1)
    assert [f.index for f in bull.batch.failures] == [1]
    assert (bear.batch.successful_runs, bear.batch.failed_runs) == (0, 3)
    assert all(entry.count == 0 for entry in bear.batch.aggregate.metrics)
    assert bear.batch.failures[0].error == f"RuntimeError: refused bear seed {SEED}"
    comparison_to_dict(result)
