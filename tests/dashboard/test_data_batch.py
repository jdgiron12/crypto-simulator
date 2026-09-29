"""The dashboard's batch entry point (Phase 20, Step 6).

``run_dashboard_batch`` is Phase 14's ``run_batch`` with ``run_simulation`` as
its runner, described by Phase 15's ``aggregate_batch``, reduced at once. The
reduction keeps the aggregate unchanged, each successful run's aggregated
metric values exactly as the aggregate read them, and every failure — and no
payload, price series or tick series.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

import crypto_simulator.dashboard.data as data_module
from crypto_simulator.analytics.aggregate import AGGREGATED_METRICS, aggregate_batch
from crypto_simulator.analytics.tick_series import TickSeries
from crypto_simulator.dashboard.data import (
    BATCH_HISTOGRAM_METRICS,
    MAX_DASHBOARD_BATCH_RUNS,
    BatchRunFailure,
    BatchRunValues,
    DashboardBatch,
    DashboardPayload,
    PricePoint,
    SimulationParams,
    batch_to_dict,
    configured_seed,
    payload_to_dict,
    reduce_batch,
    run_dashboard_batch,
    run_dashboard_simulation,
    run_simulation,
)
from crypto_simulator.services import batch as batch_module
from crypto_simulator.services.batch import MAX_BATCH_RUNS, batch_seed, run_batch

PARAMS = SimulationParams(ticks=15, random_seed=48291)


@pytest.fixture(scope="module")
def batch():
    return run_dashboard_batch(PARAMS, 5)


@pytest.fixture(scope="module")
def reference():
    """The same batch through the service, as the CLI runs it."""
    return run_batch(PARAMS, 5, runner=run_simulation)


def _failing_on(indices):
    """A runner that raises on the given run indices and runs the rest."""
    seeds = {batch_seed(PARAMS.random_seed, index) for index in indices}

    def runner(params):
        if params.random_seed in seeds:
            raise RuntimeError(f"seed {params.random_seed} refused")
        return run_simulation(params)

    return runner


# --- the existing batch and aggregate are the ones used -------------------------------------------------


def test_the_default_runner_is_run_simulation_not_the_tick_series_runner():
    default = inspect.signature(run_dashboard_batch).parameters["runner"].default
    assert default is run_simulation
    assert default is not run_dashboard_simulation


def test_the_batch_is_run_batch_with_run_simulation(monkeypatch):
    calls = []

    def spy(params, runs, **kwargs):
        calls.append((params, runs, kwargs))
        return run_batch(params, runs, **kwargs)

    monkeypatch.setattr(data_module, "run_batch", spy)
    run_dashboard_batch(PARAMS, 2)
    assert len(calls) == 1
    params, runs, kwargs = calls[0]
    assert params == PARAMS and runs == 2
    assert kwargs["runner"] is run_simulation


def test_the_aggregate_is_aggregate_batch_of_the_same_batch(batch, reference):
    assert batch.aggregate == aggregate_batch(reference)


def test_the_aggregate_is_computed_by_aggregate_batch(monkeypatch):
    calls = []

    def spy(result):
        calls.append(result)
        return aggregate_batch(result)

    monkeypatch.setattr(data_module, "aggregate_batch", spy)
    run_dashboard_batch(PARAMS, 2)
    assert len(calls) == 1 and calls[0].requested_runs == 2


def test_batch_runs_still_return_plain_payloads(reference):
    assert all(type(run.payload) is DashboardPayload for run in reference.runs)


def test_the_data_layer_still_computes_no_statistics_of_its_own():
    source = Path(data_module.__file__).read_text()
    for banned in ("sum(", "fsum", "statistics", "median(", "stdev(", "percentile("):
        assert banned not in source, banned


# --- what is kept ---------------------------------------------------------------------------------------


def test_the_batch_identity_is_kept(batch, reference):
    assert batch.params == reference.params
    assert batch.base_seed == reference.base_seed == PARAMS.random_seed
    assert (batch.requested_runs, batch.successful_runs, batch.failed_runs) == (5, 5, 0)
    assert batch.failures == ()
    assert batch.coin_symbol == reference.completed[0].payload.simulation.coin_symbol


def test_each_run_keeps_its_index_seed_id_and_every_aggregated_metric(batch, reference):
    assert [run.index for run in batch.runs] == [0, 1, 2, 3, 4]
    for kept, run in zip(batch.runs, reference.completed):
        assert isinstance(kept, BatchRunValues)
        assert kept.seed == run.seed == batch_seed(PARAMS.random_seed, run.index)
        assert kept.simulation_id == run.payload.simulation.simulation_id
        assert list(kept.metrics) == list(AGGREGATED_METRICS)
        market = run.payload.report.market
        for metric in AGGREGATED_METRICS:
            if metric == "total_volume":
                assert kept.metrics[metric] == market.volume_breakdown.total_volume
            else:
                assert kept.metrics[metric] == getattr(market, metric), metric


def test_the_per_run_values_are_the_aggregates_observations(batch):
    for entry in batch.aggregate.metrics:
        values = sorted(run.metrics[entry.metric] for run in batch.runs if run.metrics[entry.metric] is not None)
        assert entry.count == len(values)
        if values:
            assert (entry.minimum, entry.maximum) == (values[0], values[-1])


def test_a_run_is_the_single_run_of_its_derived_seed(batch):
    first = batch.runs[0]
    alone = run_simulation(replace(PARAMS, random_seed=first.seed))
    assert alone.simulation.simulation_id == first.simulation_id
    assert alone.report.market.close_price == first.metrics["close_price"]


def test_the_histogram_metrics_are_aggregated_metrics():
    assert BATCH_HISTOGRAM_METRICS == ("close_price", "cumulative_return", "max_drawdown", "total_volume")
    assert set(BATCH_HISTOGRAM_METRICS) <= set(AGGREGATED_METRICS)


# --- what is not kept -----------------------------------------------------------------------------------


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


def test_no_payload_price_series_or_tick_series_survives_the_reduction(batch):
    held = list(_walk(batch))
    assert not any(isinstance(v, (DashboardPayload, PricePoint, TickSeries, batch_module.BatchRun,
                                  batch_module.BatchResult)) for v in held)
    serialized = json.dumps(batch_to_dict(batch))
    for key in ("price_series", "tick_series", "report", "psychology_market", "observations", "trades"):
        assert f'"{key}"' not in serialized, key


def test_the_serialized_batch_is_small_and_plain(batch):
    as_dict = batch_to_dict(batch)
    assert list(as_dict) == ["params", "base_seed", "requested_runs", "successful_runs", "failed_runs",
                             "coin_symbol", "runs", "failures", "aggregate", "price_paths"]
    assert json.loads(json.dumps(as_dict)) == as_dict
    assert [m["metric"] for m in as_dict["aggregate"]["metrics"]] == list(AGGREGATED_METRICS)
    assert len(json.dumps(as_dict)) < 20_000
    one_run = len(json.dumps(as_dict["runs"][0]))
    assert one_run < 2_000, "a run is a handful of scalars"
    payload = len(json.dumps(payload_to_dict(run_simulation(PARAMS))))
    assert one_run * 5 < payload


def test_batch_to_dict_refuses_anything_else(reference):
    with pytest.raises(TypeError, match="DashboardBatch"):
        batch_to_dict(reference)


# --- failures -------------------------------------------------------------------------------------------


def test_a_mixed_batch_keeps_its_failures_and_aggregates_the_rest():
    reduced = run_dashboard_batch(PARAMS, 5, runner=_failing_on({1, 3}))
    assert (reduced.requested_runs, reduced.successful_runs, reduced.failed_runs) == (5, 3, 2)
    assert [run.index for run in reduced.runs] == [0, 2, 4]
    assert reduced.failures == tuple(
        BatchRunFailure(index=i, seed=batch_seed(PARAMS.random_seed, i),
                        error=f"RuntimeError: seed {batch_seed(PARAMS.random_seed, i)} refused")
        for i in (1, 3)
    )
    assert reduced.aggregate.metric("close_price").count == 3
    assert reduced.aggregate == aggregate_batch(run_batch(PARAMS, 5, runner=_failing_on({1, 3})))


def test_an_all_failed_batch_has_failures_and_an_empty_aggregate():
    reduced = run_dashboard_batch(PARAMS, 3, runner=_failing_on({0, 1, 2}))
    assert (reduced.successful_runs, reduced.failed_runs) == (0, 3)
    assert reduced.runs == ()
    assert reduced.coin_symbol is None
    assert [f.index for f in reduced.failures] == [0, 1, 2]
    assert all(entry.count == 0 and entry.mean is None for entry in reduced.aggregate.metrics)
    batch_to_dict(reduced)


def test_an_unsupported_configuration_fails_every_run_rather_than_the_batch():
    reduced = run_dashboard_batch(SimulationParams(ticks=3, pricing_mode="amm"), 2)
    assert reduced.successful_runs == 0 and reduced.failed_runs == 2
    assert all("ValueError" in failure.error for failure in reduced.failures)


# --- edge cases -----------------------------------------------------------------------------------------


def test_one_successful_run_has_no_standard_deviation_and_no_spread():
    reduced = run_dashboard_batch(PARAMS, 1)
    entry = reduced.aggregate.metric("close_price")
    value = reduced.runs[0].metrics["close_price"]
    assert entry.count == 1
    assert entry.standard_deviation is None
    assert {p.value for p in entry.percentiles} == {value}
    assert entry.mean == entry.median == entry.minimum == entry.maximum == value


def test_a_metric_no_run_computed_has_count_zero_and_none_values():
    reduced = run_dashboard_batch(SimulationParams(ticks=1, random_seed=7), 3)
    entry = reduced.aggregate.metric("volatility")
    assert entry.count == 0 and entry.mean is None and entry.minimum is None
    assert all(run.metrics["volatility"] is None for run in reduced.runs)
    serialized = batch_to_dict(reduced)
    assert all(run["metrics"]["volatility"] is None for run in serialized["runs"])


def test_the_base_seed_defaults_to_the_configured_seed():
    reduced = run_dashboard_batch(SimulationParams(ticks=3), 2)
    assert reduced.base_seed == configured_seed()
    assert [run.seed for run in reduced.runs] == [batch_seed(configured_seed(), i) for i in range(2)]


def test_the_same_request_gives_the_same_batch(batch):
    assert run_dashboard_batch(PARAMS, 5) == batch
    assert batch_to_dict(run_dashboard_batch(PARAMS, 5)) == batch_to_dict(batch)


@pytest.mark.parametrize("runs", [0, -1, MAX_DASHBOARD_BATCH_RUNS + 1, MAX_BATCH_RUNS, True, 2.0, "3"])
def test_the_dashboard_batch_limit_is_enforced(runs, monkeypatch):
    monkeypatch.setattr(data_module, "run_batch", lambda *a, **k: pytest.fail("the batch should not run"))
    with pytest.raises(ValueError, match="runs must be"):
        run_dashboard_batch(PARAMS, runs)


def test_the_dashboard_limit_is_below_and_separate_from_the_service_limit():
    assert MAX_DASHBOARD_BATCH_RUNS == 200
    assert MAX_BATCH_RUNS == 1000
    assert MAX_DASHBOARD_BATCH_RUNS < MAX_BATCH_RUNS


def test_reduce_batch_accepts_a_service_result(reference):
    reduced = reduce_batch(reference)
    assert isinstance(reduced, DashboardBatch)
    assert reduced.successful_runs == len(reference.completed)


# --- the single-run path is untouched -------------------------------------------------------------------


def test_the_single_run_path_is_unchanged():
    single = payload_to_dict(run_simulation(PARAMS))
    assert payload_to_dict(run_dashboard_simulation(PARAMS).payload) == single
    run_dashboard_batch(PARAMS, 2)
    assert payload_to_dict(run_simulation(PARAMS)) == single


# --- price-path bands (Phase 20, Step 8) ----------------------------------------------------------------


def test_a_dashboard_batch_carries_the_price_path_bands_of_its_runs(batch, reference):
    from crypto_simulator.analytics.price_paths import PricePathBands, aggregate_price_paths

    assert isinstance(batch.price_paths, PricePathBands)
    assert batch.price_paths == aggregate_price_paths(reference)
    assert batch.price_paths.runs == batch.successful_runs == 5
    assert batch.price_paths.ticks == tuple(range(1, PARAMS.ticks + 1))


def test_price_paths_are_opt_in_in_the_reduction(reference):
    assert reduce_batch(reference).price_paths is None
    assert reduce_batch(reference, price_paths=True).price_paths is not None
    assert "price_paths" in inspect.signature(reduce_batch).parameters
    assert inspect.signature(reduce_batch).parameters["price_paths"].default is False


def test_price_path_bands_count_only_successful_runs():
    reduced = run_dashboard_batch(PARAMS, 5, runner=_failing_on({1, 3}))
    assert reduced.price_paths.runs == reduced.successful_runs == 3


def test_an_all_failed_batch_has_no_price_path_bands():
    assert run_dashboard_batch(PARAMS, 2, runner=_failing_on({0, 1})).price_paths is None


def test_the_serialized_bands_are_columns_of_numbers_only(batch):
    bands = batch_to_dict(batch)["price_paths"]
    assert list(bands) == ["runs", "ticks", "minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"]
    assert bands["runs"] == 5
    for column in ("minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"):
        assert len(bands[column]) == PARAMS.ticks
        assert all(isinstance(value, float) for value in bands[column])


def test_no_run_path_is_kept_beside_the_bands(batch, reference):
    """The bands are ticks x 9 numbers whatever the run count; no run's own
    recorded prices appear as a series anywhere in the reduced batch."""
    serialized = batch_to_dict(batch)
    for run in reference.completed:
        path = [point.price for point in run.payload.price_series]
        for key, value in serialized["price_paths"].items():
            assert value != path, key
    assert '"price_series"' not in json.dumps(serialized)
    held = list(_walk(batch))
    assert not any(isinstance(v, (DashboardPayload, PricePoint, TickSeries)) for v in held)


def test_a_comparison_does_not_compute_price_paths(monkeypatch):
    from crypto_simulator.dashboard.data import comparison_configurations, run_dashboard_comparison

    monkeypatch.setattr(data_module, "aggregate_price_paths",
                        lambda result: pytest.fail("a comparison must not build price paths"))
    result = run_dashboard_comparison(
        SimulationParams(ticks=5, include_whales=False),
        comparison_configurations(["random_walk"], [None], [None, "bull"]), 2, base_seed=9,
    )
    assert all(group.batch.price_paths is None for group in result.groups)
