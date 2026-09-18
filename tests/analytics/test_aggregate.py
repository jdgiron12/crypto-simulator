"""Describing a batch's runs as distributions (Phase 15).

Two halves. The first pins the arithmetic against datasets small enough
to work out by hand, including the percentile convention, which the
project defines once and this module must not redefine. The second runs
real batches and checks that what comes out is exactly what the runs'
own reports already said — the guard against the aggregate layer and the
analytics drifting apart.
"""

from __future__ import annotations

import math
import statistics

import pytest

from crypto_simulator.analytics._series import percentile
from crypto_simulator.dashboard.data import run_simulation
from crypto_simulator.analytics.aggregate import (
    AGGREGATED_METRICS,
    PERCENTILES,
    AggregateStatistics,
    MetricStatistics,
    aggregate_batch,
    aggregate_values,
)
from crypto_simulator.services.batch import BatchResult, BatchRun, run_batch
from crypto_simulator.services.simulation_params import SimulationParams


# --- the arithmetic, pinned ------------------------------------------------------------------------------


def test_an_odd_number_of_observations():
    """1 2 3 4 5: median is the middle value, and every percentile lands
    on a rank worked out by hand."""
    stats = aggregate_values("m", [3.0, 1.0, 5.0, 2.0, 4.0])
    assert stats.count == 5
    assert stats.mean == 3.0
    assert stats.median == 3.0
    assert (stats.minimum, stats.maximum) == (1.0, 5.0)
    assert stats.standard_deviation == pytest.approx(statistics.stdev([1, 2, 3, 4, 5]))
    # rank = p/100 x (n-1) = p/100 x 4
    assert stats.percentile(5) == pytest.approx(1.2)  # rank 0.2
    assert stats.percentile(25) == pytest.approx(2.0)  # rank 1.0
    assert stats.percentile(50) == pytest.approx(3.0)  # rank 2.0
    assert stats.percentile(75) == pytest.approx(4.0)  # rank 3.0
    assert stats.percentile(95) == pytest.approx(4.8)  # rank 3.8


def test_an_even_number_of_observations():
    """1 2 3 4: the median is the mean of the middle two, and p50 agrees."""
    stats = aggregate_values("m", [4.0, 2.0, 1.0, 3.0])
    assert stats.count == 4
    assert stats.mean == 2.5
    assert stats.median == 2.5
    assert stats.percentile(50) == pytest.approx(2.5)  # rank 1.5
    assert stats.percentile(25) == pytest.approx(1.75)  # rank 0.75
    assert stats.percentile(75) == pytest.approx(3.25)  # rank 2.25


def test_p50_is_always_the_median():
    for values in ([1.0], [1.0, 2.0], [5.0, 1.0, 3.0], [4.0, 2.0, 9.0, 1.0, 7.0, 3.0]):
        stats = aggregate_values("m", values)
        assert stats.percentile(50) == pytest.approx(stats.median), values


def test_the_percentile_is_the_projects_one_definition():
    """Not a second implementation: the same helper the psychology
    analytics use."""
    values = [0.5, 0.1, 0.9, 0.3, 0.7, 0.2]
    stats = aggregate_values("m", values)
    ordered = sorted(values)
    for entry in stats.percentiles:
        assert entry.value == percentile(ordered, entry.percent)


def test_a_single_observation():
    """Everything but dispersion is that one value; the sample standard
    deviation of one number is undefined, not zero."""
    stats = aggregate_values("m", [7.5])
    assert stats.count == 1
    assert stats.mean == stats.median == stats.minimum == stats.maximum == 7.5
    assert stats.standard_deviation is None
    assert all(entry.value == 7.5 for entry in stats.percentiles)


def test_no_observations():
    stats = aggregate_values("m", [])
    assert stats.count == 0
    assert stats.mean is None
    assert stats.median is None
    assert stats.minimum is None
    assert stats.maximum is None
    assert stats.standard_deviation is None
    assert [entry.value for entry in stats.percentiles] == [None] * len(PERCENTILES)


def test_negative_and_mixed_values():
    """A loss is a negative return and must average as one."""
    stats = aggregate_values("m", [-0.5, 0.5, -1.5, 1.5])
    assert stats.mean == 0.0
    assert stats.median == 0.0
    assert (stats.minimum, stats.maximum) == (-1.5, 1.5)
    assert stats.percentile(5) == pytest.approx(-1.35)


def test_every_value_the_same():
    stats = aggregate_values("m", [2.0] * 6)
    assert stats.mean == stats.median == stats.minimum == stats.maximum == 2.0
    assert stats.standard_deviation == 0.0, "no spread is a real zero, unlike an undefined one"
    assert all(entry.value == 2.0 for entry in stats.percentiles)


def test_the_mean_is_the_compensated_one():
    """The mean is ``fsum(values) / n``, the summation the rest of the
    analytics use, checked on a dataset where naive left-to-right
    addition would lose the small terms entirely. (CPython's own ``sum``
    compensates for floats too, so the two agree here — the point is that
    the convention is pinned, not that they differ.)"""
    values = [1.0, 1e100, 1.0, -1e100]
    naive = 0.0
    for value in values:
        naive += value
    assert naive == 0.0, "left-to-right addition loses both 1.0s"
    assert math.fsum(values) == 2.0
    assert aggregate_values("m", values).mean == math.fsum(values) / 4


def test_very_small_and_very_large_values_are_kept():
    stats = aggregate_values("m", [1e-12, 1e12])
    assert stats.minimum == 1e-12
    assert stats.maximum == 1e12


def test_stored_values_are_not_rounded():
    """Rounding belongs to display, not to the result."""
    stats = aggregate_values("m", [1 / 3, 2 / 3])
    assert stats.mean == pytest.approx(0.5, abs=0)
    assert stats.minimum == 1 / 3


def test_values_are_ordered_before_they_are_read():
    """Input order cannot change any figure."""
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0]
    assert aggregate_values("m", values) == aggregate_values("m", list(reversed(values)))


# --- missing values --------------------------------------------------------------------------------------


def test_none_is_an_absence_not_a_zero():
    stats = aggregate_values("m", [2.0, None, 4.0])
    assert stats.count == 2
    assert stats.mean == 3.0, "a None averaged as zero would give 2.0"
    assert stats.minimum == 2.0


def test_all_none_is_no_observations():
    stats = aggregate_values("m", [None, None, None])
    assert stats.count == 0
    assert stats.mean is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_a_non_finite_observation_is_an_error(bad):
    with pytest.raises(ValueError, match="must be finite"):
        aggregate_values("m", [1.0, bad])


@pytest.mark.parametrize("bad", ["2", True, object()])
def test_a_non_numeric_observation_is_an_error(bad):
    with pytest.raises(ValueError, match="must be a number or None"):
        aggregate_values("m", [1.0, bad])


def test_the_metric_keeps_its_name():
    assert aggregate_values("cumulative_return", [1.0]).metric == "cumulative_return"


def test_asking_for_a_percentile_that_is_not_reported_is_an_error():
    with pytest.raises(ValueError, match="no percentile 42"):
        aggregate_values("m", [1.0]).percentile(42)


# --- batches ---------------------------------------------------------------------------------------------


def _batch(runs=5, **kwargs):
    kwargs.setdefault("ticks", 20)
    params = SimulationParams(**kwargs)
    return run_batch(params, runs, runner=run_simulation, base_seed=48291)


def test_a_batch_is_described_metric_by_metric():
    stats = aggregate_batch(_batch())
    assert isinstance(stats, AggregateStatistics)
    assert [m.metric for m in stats.metrics] == list(AGGREGATED_METRICS)
    assert all(isinstance(m, MetricStatistics) for m in stats.metrics)


def test_the_run_counts_come_from_the_batch():
    stats = aggregate_batch(_batch(runs=6))
    assert (stats.requested_runs, stats.successful_runs, stats.failed_runs) == (6, 6, 0)


def test_the_aggregate_is_the_reports_own_numbers():
    """The guard against drift: every figure must be a statistic of the
    values the runs' own reports hold, not a recomputation."""
    batch = _batch(runs=7)
    returns = [run.payload.report.market.cumulative_return for run in batch.completed]

    stats = aggregate_batch(batch).metric("cumulative_return")
    ordered = sorted(returns)
    assert stats.count == 7
    assert stats.mean == math.fsum(returns) / 7
    assert stats.median == statistics.median(ordered)
    assert stats.minimum == ordered[0]
    assert stats.maximum == ordered[-1]
    assert stats.standard_deviation == statistics.stdev(ordered)
    assert stats.percentile(95) == percentile(ordered, 95)


def test_total_volume_is_the_analytics_own_property():
    batch = _batch(runs=4)
    volumes = [run.payload.report.market.volume_breakdown.total_volume for run in batch.completed]
    assert aggregate_batch(batch).metric("total_volume").mean == math.fsum(volumes) / 4


def test_asking_for_a_metric_that_is_not_aggregated_is_an_error():
    with pytest.raises(ValueError, match="no metric"):
        aggregate_batch(_batch(runs=2)).metric("price_change")


def test_no_absolute_price_change_is_reported():
    """The report defines none, so neither does this — inventing one
    would put a second definition of the same idea in the project."""
    assert "price_change" not in AGGREGATED_METRICS
    assert "absolute_change" not in AGGREGATED_METRICS


def test_only_a_batch_result_can_be_aggregated():
    """Taken by shape, not by type — this package must not import
    ``services`` — so the error names the shape it wanted."""
    with pytest.raises(ValueError, match="must be a batch result"):
        aggregate_batch([1, 2, 3])


def test_the_aggregate_layer_does_not_depend_on_the_simulators_layers():
    """``analytics`` observes finished runs; nothing in it may reach back
    into the simulator's own packages for a type."""
    from pathlib import Path

    from crypto_simulator.analytics import aggregate as module

    source = Path(module.__file__).read_text()
    assert "crypto_simulator.services" not in source
    assert "crypto_simulator.dashboard" not in source
    assert "crypto_simulator.data" not in source


# --- failed runs -----------------------------------------------------------------------------------------


def _mixed_batch(fail_at):
    """A real batch with some runs replaced by failures."""
    batch = _batch(runs=5)
    runs = tuple(
        BatchRun(index=run.index, seed=run.seed, error="RuntimeError: broke")
        if run.index in fail_at
        else run
        for run in batch.runs
    )
    return BatchResult(
        params=batch.params,
        base_seed=batch.base_seed,
        requested_runs=batch.requested_runs,
        runs=runs,
    )


def test_failed_runs_are_counted_but_not_observed():
    batch = _mixed_batch({1, 3})
    stats = aggregate_batch(batch)
    assert (stats.requested_runs, stats.successful_runs, stats.failed_runs) == (5, 3, 2)
    assert stats.metric("close_price").count == 3


def test_a_failed_run_is_never_a_zero():
    batch = _mixed_batch({0})
    kept = [run.payload.report.market.close_price for run in batch.completed]
    assert aggregate_batch(batch).metric("close_price").mean == math.fsum(kept) / len(kept)


def test_a_batch_where_everything_failed_is_described_as_empty():
    batch = _mixed_batch({0, 1, 2, 3, 4})
    stats = aggregate_batch(batch)
    assert (stats.successful_runs, stats.failed_runs) == (0, 5)
    assert all(metric.count == 0 for metric in stats.metrics)
    assert all(metric.mean is None for metric in stats.metrics)


def test_a_metric_can_have_fewer_observations_than_successful_runs():
    """Volatility needs two returns; a one-tick run has one. The run
    succeeds, and contributes to close_price but not to volatility."""
    batch = run_batch(SimulationParams(ticks=1), 4, runner=run_simulation, base_seed=48291)
    stats = aggregate_batch(batch)
    assert stats.successful_runs == 4
    assert stats.metric("close_price").count == 4
    assert stats.metric("volatility").count == 0
    assert stats.metric("volatility").mean is None


# --- determinism -----------------------------------------------------------------------------------------


def test_aggregating_the_same_batch_twice_gives_the_same_answer():
    batch = _batch(runs=6)
    assert aggregate_batch(batch) == aggregate_batch(batch)


def test_the_same_batch_command_gives_the_same_aggregate():
    assert aggregate_batch(_batch(runs=5)) == aggregate_batch(_batch(runs=5))


def test_a_different_base_seed_gives_a_different_aggregate():
    one = aggregate_batch(run_batch(SimulationParams(ticks=20), 5, runner=run_simulation, base_seed=1))
    two = aggregate_batch(run_batch(SimulationParams(ticks=20), 5, runner=run_simulation, base_seed=2))
    assert one.metric("close_price").mean != two.metric("close_price").mean


def test_the_aggregate_is_built_from_the_runs_a_seed_actually_produces():
    """Run 2 of the batch is the single run at run 2's seed, and its
    close price is one of the observations."""
    batch = _batch(runs=4)
    run = batch.runs[2]
    alone = run_simulation(SimulationParams(ticks=20, random_seed=run.seed))
    assert run.payload.report.market.close_price == alone.report.market.close_price

    stats = aggregate_batch(batch).metric("close_price")
    assert stats.minimum <= alone.report.market.close_price <= stats.maximum


# --- across the simulator's configurations -----------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=20),
        SimulationParams(ticks=20, pricing_mode="amm", include_whales=False),
        SimulationParams(ticks=25, pricing_mode="amm", include_whales=False, scenario="pump_and_dump"),
        SimulationParams(ticks=25, scenario="wash_trading"),
        SimulationParams(
            ticks=20, events=True, random_events=True, psychology=True, whale_observation=True
        ),
    ],
    ids=["random_walk", "amm", "amm-pump_and_dump", "wash_trading", "events-psychology-whales"],
)
def test_every_configuration_aggregates(params):
    batch = run_batch(params, 4, runner=run_simulation, base_seed=48291)
    stats = aggregate_batch(batch)
    assert stats.successful_runs == 4
    for name in ("close_price", "cumulative_return", "volatility", "max_drawdown", "total_volume"):
        assert stats.metric(name).count == 4, name


def test_an_amm_batch_aggregates_its_pool_driven_prices():
    batch = run_batch(
        SimulationParams(ticks=20, pricing_mode="amm", include_whales=False),
        4, runner=run_simulation, base_seed=48291,
    )
    prices = [run.payload.report.market.close_price for run in batch.completed]
    assert aggregate_batch(batch).metric("close_price").mean == math.fsum(prices) / 4


def test_a_batch_of_a_saved_scenario_aggregates(tmp_path):
    """save -> load -> batch -> aggregate. The statistics layer never
    learns that a database was involved."""
    from crypto_simulator.data.database import connect, init_db
    from crypto_simulator.services.scenarios import ScenarioService

    params = SimulationParams(ticks=20, pricing_mode="amm", include_whales=False, random_seed=48291)
    conn = connect(tmp_path / "scenarios.db")
    init_db(conn)
    ScenarioService(conn).save("amm-nightly", params)
    loaded = ScenarioService(conn).load("amm-nightly")
    conn.close()

    stats = aggregate_batch(run_batch(loaded, 5, runner=run_simulation))
    assert stats.successful_runs == 5
    assert stats.metric("close_price").count == 5
