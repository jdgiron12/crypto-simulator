"""Per-tick price-path bands across a batch's runs (Phase 20, Step 8).

``aggregate_price_paths`` lines a batch's successful runs up by tick and
hands each tick's prices to Phase 15's ``aggregate_values``. The fixtures
below are worked by hand with the project's percentile (linear interpolation
at rank p/100 x (n - 1)); the rest checks the validation that keeps runs from
being truncated, padded or repaired.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

import pytest

from crypto_simulator.analytics import PricePathBands, aggregate_price_paths
from crypto_simulator.analytics.aggregate import aggregate_values
from crypto_simulator.dashboard.data import SimulationParams, run_simulation
from crypto_simulator.services.batch import run_batch


@dataclass(frozen=True)
class Point:
    tick: Any
    price: Any


@dataclass(frozen=True)
class Payload:
    price_series: Any


@dataclass(frozen=True)
class Run:
    index: int
    payload: Any = None


@dataclass(frozen=True)
class Result:
    completed: tuple


def _batch(*paths, ticks=None):
    """A batch result whose run ``i`` recorded ``paths[i]`` at ``ticks``."""
    runs = []
    for index, prices in enumerate(paths):
        tick_numbers = ticks or range(1, len(prices) + 1)
        runs.append(Run(index, Payload(tuple(Point(t, p) for t, p in zip(tick_numbers, prices)))))
    return Result(tuple(runs))


# Five runs, three ticks. Tick 1 holds 1..5 in order, tick 2 is flat at 10,
# tick 3 holds 1..5 out of run order.
FIXTURE = _batch(
    (1.0, 10.0, 5.0),
    (2.0, 10.0, 1.0),
    (3.0, 10.0, 4.0),
    (4.0, 10.0, 2.0),
    (5.0, 10.0, 3.0),
)


@pytest.fixture(scope="module")
def bands():
    return aggregate_price_paths(FIXTURE)


# --- the hand-computed fixture ---------------------------------------------------------------------------


def test_the_fixture_has_one_entry_per_tick_and_counts_the_runs(bands):
    assert isinstance(bands, PricePathBands)
    assert bands.runs == 5
    assert bands.ticks == (1, 2, 3)
    for column in ("minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"):
        assert len(getattr(bands, column)) == 3, column


def test_p5_is_interpolated_at_rank_0_2(bands):
    # rank 5/100 x 4 = 0.2: 1 + 0.2 x (2 - 1)
    assert bands.p5 == pytest.approx((1.2, 10.0, 1.2), abs=1e-12)


def test_p25_is_the_second_value(bands):
    # rank 25/100 x 4 = 1
    assert bands.p25 == (2.0, 10.0, 2.0)


def test_the_median_is_the_middle_value(bands):
    assert bands.median == (3.0, 10.0, 3.0)


def test_p75_is_the_fourth_value(bands):
    assert bands.p75 == (4.0, 10.0, 4.0)


def test_p95_is_interpolated_at_rank_3_8(bands):
    # rank 95/100 x 4 = 3.8: 4 + 0.8 x (5 - 4)
    assert bands.p95 == pytest.approx((4.8, 10.0, 4.8), abs=1e-12)


def test_minimum_and_maximum(bands):
    assert bands.minimum == (1.0, 10.0, 1.0)
    assert bands.maximum == (5.0, 10.0, 5.0)


def test_mean(bands):
    assert bands.mean == (3.0, 10.0, 3.0)


def test_every_tick_is_exactly_aggregate_values_of_its_prices(bands):
    for position, prices in enumerate(((1, 2, 3, 4, 5), (10,) * 5, (5, 1, 4, 2, 3))):
        entry = aggregate_values("price", [float(p) for p in prices])
        assert bands.minimum[position] == entry.minimum
        assert bands.p5[position] == entry.percentile(5)
        assert bands.p25[position] == entry.percentile(25)
        assert bands.median[position] == entry.median == entry.percentile(50)
        assert bands.p75[position] == entry.percentile(75)
        assert bands.p95[position] == entry.percentile(95)
        assert bands.maximum[position] == entry.maximum
        assert bands.mean[position] == entry.mean


# --- shapes of the spread -------------------------------------------------------------------------------


def test_identical_paths_collapse_every_band_onto_the_path():
    path = (1.0, 1.1, 0.9, 1.3)
    bands = aggregate_price_paths(_batch(path, path, path))
    for column in ("minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"):
        assert getattr(bands, column) == pytest.approx(path, abs=1e-12), column


def test_varying_paths_give_ordered_statistics_at_every_tick():
    paths = [tuple(1.0 + 0.01 * ((run * 7 + tick * 3) % 11) for tick in range(20)) for run in range(9)]
    bands = aggregate_price_paths(_batch(*paths))
    for i in range(20):
        assert (bands.minimum[i] <= bands.p5[i] <= bands.p25[i] <= bands.median[i]
                <= bands.p75[i] <= bands.p95[i] <= bands.maximum[i])
        assert bands.minimum[i] <= bands.mean[i] <= bands.maximum[i]


def test_one_run_is_its_own_path():
    path = (2.0, 2.5, 1.5)
    bands = aggregate_price_paths(_batch(path))
    assert bands.runs == 1
    assert bands.median == bands.p5 == bands.p95 == bands.minimum == bands.maximum == path


def test_ticks_need_not_start_at_one_but_must_be_consecutive():
    bands = aggregate_price_paths(_batch((1.0, 2.0), (3.0, 4.0), ticks=(7, 8)))
    assert bands.ticks == (7, 8)


# --- failed runs and empty batches ----------------------------------------------------------------------


def test_zero_successful_runs_gives_none():
    assert aggregate_price_paths(Result(())) is None


def test_failed_runs_are_excluded():
    params = SimulationParams(ticks=6, random_seed=48291)
    calls = {"n": 0}

    def runner(request):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("refused")
        return run_simulation(request)

    result = run_batch(params, 4, runner=runner)
    bands = aggregate_price_paths(result)
    assert bands.runs == 3 == len(result.completed)
    assert bands.ticks == (1, 2, 3, 4, 5, 6)
    first = [point.price for point in result.completed[0].payload.price_series]
    columns = list(zip(*([p.price for p in run.payload.price_series] for run in result.completed)))
    assert bands.median == tuple(aggregate_values("p", list(c)).median for c in columns)
    assert bands.minimum[0] <= first[0] <= bands.maximum[0]


def test_an_all_failed_batch_gives_none():
    result = run_batch(SimulationParams(ticks=3), 2, runner=lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    assert result.completed == ()
    assert aggregate_price_paths(result) is None


def test_a_real_batch_is_aligned_on_ticks_one_to_n():
    result = run_batch(SimulationParams(ticks=9, random_seed=5), 3, runner=run_simulation)
    bands = aggregate_price_paths(result)
    assert bands.ticks == tuple(range(1, 10))
    assert bands.runs == 3


# --- validation -----------------------------------------------------------------------------------------


def test_a_result_without_completed_runs_is_refused():
    with pytest.raises(ValueError, match="batch result"):
        aggregate_price_paths([1, 2, 3])


def test_mismatched_tick_sequences_are_refused():
    result = Result((
        Run(0, Payload((Point(1, 1.0), Point(2, 1.0), Point(3, 1.0)))),
        Run(4, Payload((Point(1, 1.0), Point(2, 1.0), Point(4, 1.0)))),
    ))
    with pytest.raises(ValueError, match="run 4 recorded tick 4 at position 2 where the first successful run "
                                         "recorded tick 3"):
        aggregate_price_paths(result)


def test_a_shorter_run_is_refused_not_truncated():
    with pytest.raises(ValueError, match="run 1 recorded 2 ticks where the first successful run recorded 3"):
        aggregate_price_paths(_batch((1.0, 1.0, 1.0), (1.0, 1.0)))


def test_a_longer_run_is_refused_not_padded():
    with pytest.raises(ValueError, match="run 1 recorded 4 ticks"):
        aggregate_price_paths(_batch((1.0, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0)))


def test_a_missing_tick_is_refused():
    with pytest.raises(ValueError, match="run 0 recorded tick 3 after tick 1"):
        aggregate_price_paths(_batch((1.0, 1.0), ticks=(1, 3)))


def test_out_of_order_ticks_are_refused():
    with pytest.raises(ValueError, match="run 0 recorded tick 1 after tick 2"):
        aggregate_price_paths(_batch((1.0, 1.0, 1.0), ticks=(2, 1, 3)))


def test_a_repeated_tick_is_refused():
    with pytest.raises(ValueError, match="run 0 recorded tick 1 after tick 1"):
        aggregate_price_paths(_batch((1.0, 1.0), ticks=(1, 1)))


def test_a_non_integer_tick_is_refused():
    with pytest.raises(ValueError, match="non-integer tick"):
        aggregate_price_paths(_batch((1.0, 1.0), ticks=(1, 2.0)))


def test_a_completed_run_without_a_payload_is_refused():
    with pytest.raises(ValueError, match="run 3 is marked completed but has no payload"):
        aggregate_price_paths(Result((Run(3, None),)))


def test_a_missing_price_series_is_refused():
    with pytest.raises(ValueError, match="run 2 has no recorded price series"):
        aggregate_price_paths(Result((Run(2, Payload(None)),)))
    with pytest.raises(ValueError, match="run 2 has no recorded price series"):
        aggregate_price_paths(Result((Run(2, object()),)))


def test_an_empty_series_is_refused():
    with pytest.raises(ValueError, match="run 0 has an empty price series"):
        aggregate_price_paths(Result((Run(0, Payload(())),)))


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_non_positive_prices_are_refused(price):
    with pytest.raises(ValueError, match=r"run 1 has an invalid price .* at tick 2"):
        aggregate_price_paths(_batch((1.0, 1.0), (1.0, price)))


@pytest.mark.parametrize("price", [math.nan, math.inf, -math.inf, None, "1.0", True])
def test_non_finite_or_non_numeric_prices_are_refused(price):
    with pytest.raises(ValueError, match="invalid price"):
        aggregate_price_paths(_batch((1.0, price)))


# --- purity ---------------------------------------------------------------------------------------------


def test_inputs_are_not_mutated():
    before = copy.deepcopy(FIXTURE)
    aggregate_price_paths(FIXTURE)
    assert FIXTURE == before


def test_the_same_batch_gives_the_same_bands():
    assert aggregate_price_paths(FIXTURE) == aggregate_price_paths(FIXTURE)
    result = run_batch(SimulationParams(ticks=7, random_seed=11), 3, runner=run_simulation)
    again = run_batch(SimulationParams(ticks=7, random_seed=11), 3, runner=run_simulation)
    assert aggregate_price_paths(result) == aggregate_price_paths(again)


def test_the_analytics_module_imports_no_services_or_dashboard():
    from pathlib import Path

    import crypto_simulator.analytics.price_paths as module

    source = Path(module.__file__).read_text()
    assert "crypto_simulator.services" not in source
    assert "crypto_simulator.dashboard" not in source
