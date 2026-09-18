"""Running one configuration many times (Phase 14).

What matters here: a batch is reproducible from its base seed, each run
gets a seed of its own that cannot collide with another run's internals,
a run that fails does not take the batch with it, and the batch computes
nothing across runs — that is Phase 15's job.
"""

from __future__ import annotations

import random

import pytest

from crypto_simulator.config import get_settings
from crypto_simulator.dashboard.data import payload_to_dict, run_simulation
from crypto_simulator.services.batch import (
    MAX_BATCH_RUNS,
    MIN_BATCH_RUNS,
    BatchResult,
    BatchRun,
    batch_seed,
    run_batch,
)
from crypto_simulator.services.coin_simulation import (
    BATCH_SEED_STRIDE,
    MANIPULATOR_SEED_OFFSET,
    RANDOM_EVENT_SEED_OFFSET,
    TRADER_SEED_OFFSET,
    WHALE_SEED_OFFSET,
)
from crypto_simulator.services.simulation_params import SimulationParams

SHORT = SimulationParams(ticks=5, random_seed=48291)


def _seeds_only(params):
    """A runner that records the request instead of simulating it."""
    return params.random_seed


# --- basics ---------------------------------------------------------------------------------------------


def test_a_one_run_batch(): 
    result = run_batch(SHORT, 1, runner=_seeds_only)
    assert isinstance(result, BatchResult)
    assert result.requested_runs == 1
    assert len(result.runs) == 1
    assert isinstance(result.runs[0], BatchRun)


def test_a_many_run_batch_runs_each_one():
    calls = []
    run_batch(SHORT, 25, runner=lambda params: calls.append(params.random_seed))
    assert len(calls) == 25


def test_runs_are_indexed_in_order():
    result = run_batch(SHORT, 10, runner=_seeds_only)
    assert [run.index for run in result.runs] == list(range(10))


def test_the_batch_echoes_what_it_was_asked_for():
    result = run_batch(SHORT, 4, runner=_seeds_only, base_seed=777)
    assert result.requested_runs == 4
    assert result.base_seed == 777
    assert result.params.random_seed == 777, "the batch's params carry the base it derived from"
    assert result.params.ticks == SHORT.ticks


# --- run count validation -------------------------------------------------------------------------------


@pytest.mark.parametrize("runs", [0, -1, MAX_BATCH_RUNS + 1])
def test_a_run_count_outside_the_bounds_is_rejected(runs):
    with pytest.raises(ValueError, match="runs must be between"):
        run_batch(SHORT, runs, runner=_seeds_only)


@pytest.mark.parametrize("runs", [1.0, "5", True, None])
def test_a_non_integer_run_count_is_rejected(runs):
    with pytest.raises(ValueError, match="runs must be an integer"):
        run_batch(SHORT, runs, runner=_seeds_only)


@pytest.mark.parametrize("runs", [MIN_BATCH_RUNS, MAX_BATCH_RUNS])
def test_the_bounds_themselves_are_accepted(runs):
    result = run_batch(SHORT, runs, runner=_seeds_only)
    assert len(result.runs) == runs


def test_params_must_be_a_request():
    with pytest.raises(ValueError, match="must be a SimulationParams"):
        run_batch({"ticks": 5}, 2, runner=_seeds_only)


@pytest.mark.parametrize("base", [1.5, "42", True])
def test_a_non_integer_base_seed_is_rejected(base):
    with pytest.raises(ValueError, match="base_seed must be an integer"):
        run_batch(SHORT, 2, runner=_seeds_only, base_seed=base)


def test_a_derived_seed_past_the_seed_bound_is_reported():
    """The stride can run a large base off the end of the seed range;
    that is an error about the batch, not a run that quietly used
    something else."""
    with pytest.raises(ValueError, match="random_seed must be between"):
        run_batch(SHORT, 5, runner=_seeds_only, base_seed=4294967290)


# --- seeds ----------------------------------------------------------------------------------------------


def test_each_run_gets_its_own_seed():
    result = run_batch(SHORT, 20, runner=_seeds_only, base_seed=1000)
    seeds = [run.seed for run in result.runs]
    assert len(set(seeds)) == 20


def test_seeds_are_the_projects_own_derivation_strided():
    result = run_batch(SHORT, 5, runner=_seeds_only, base_seed=48291)
    assert [run.seed for run in result.runs] == [
        48291 + index * BATCH_SEED_STRIDE for index in range(5)
    ]


def test_batch_seed_answers_the_same_question_on_its_own():
    """A caller reproducing one run of a batch must not have to rederive
    the arithmetic."""
    result = run_batch(SHORT, 6, runner=_seeds_only, base_seed=99)
    assert [batch_seed(99, index) for index in range(6)] == [run.seed for run in result.runs]


def test_the_seed_reaches_the_run_that_was_given_it():
    result = run_batch(SHORT, 5, runner=_seeds_only, base_seed=48291)
    for run in result.runs:
        assert run.payload == run.seed, "the request each run received carried its own seed"


def test_one_runs_seed_space_cannot_reach_another_runs():
    """The reason for the stride. A run's base seed is also the origin
    its participants' seeds are offset from, so runs spaced by less than
    the widest offset would hand one run's price engine a seed another
    run already gave a whale."""
    participants = 50  # far more of each kind than any config here has
    widest = max(
        WHALE_SEED_OFFSET + participants,
        TRADER_SEED_OFFSET + participants,
        MANIPULATOR_SEED_OFFSET + participants,
        RANDOM_EVENT_SEED_OFFSET,
    )
    assert BATCH_SEED_STRIDE > widest

    result = run_batch(SHORT, 8, runner=_seeds_only, base_seed=48291)
    bases = [run.seed for run in result.runs]
    used_within_runs = set()
    for base in bases:
        used_within_runs |= {base + RANDOM_EVENT_SEED_OFFSET}
        for index in range(participants):
            used_within_runs |= {
                base + WHALE_SEED_OFFSET + index,
                base + TRADER_SEED_OFFSET + index,
                base + MANIPULATOR_SEED_OFFSET + index,
            }
    assert not set(bases) & used_within_runs


def test_no_global_random_state_is_touched():
    """Every seed is computed; the batch draws nothing."""
    random.seed(12345)
    before = random.getstate()
    run_batch(SHORT, 10, runner=lambda params: run_simulation(params))
    assert random.getstate() == before


# --- where the base seed comes from ----------------------------------------------------------------------


def test_an_explicit_base_seed_wins():
    result = run_batch(SHORT, 2, runner=_seeds_only, base_seed=5)
    assert result.base_seed == 5


def test_without_one_the_requests_own_seed_is_the_base():
    result = run_batch(SimulationParams(ticks=3, random_seed=321), 2, runner=_seeds_only)
    assert result.base_seed == 321


def test_without_either_the_configured_seed_is_the_base():
    """Naming no seed still means a deterministic batch, not a drawn one."""
    result = run_batch(SimulationParams(ticks=3), 2, runner=_seeds_only)
    assert result.base_seed == get_settings().simulation.random_seed


def test_a_batch_with_no_seed_named_is_still_reproducible():
    first = run_batch(SimulationParams(ticks=3), 4, runner=_seeds_only)
    second = run_batch(SimulationParams(ticks=3), 4, runner=_seeds_only)
    assert [r.seed for r in first.runs] == [r.seed for r in second.runs]


# --- determinism ------------------------------------------------------------------------------------------


def test_the_same_batch_twice_is_the_same_batch():
    first = run_batch(SHORT, 5, runner=run_simulation, base_seed=48291)
    second = run_batch(SHORT, 5, runner=run_simulation, base_seed=48291)
    assert [payload_to_dict(p) for p in first.payloads] == [
        payload_to_dict(p) for p in second.payloads
    ]


def test_a_different_base_seed_gives_a_different_batch():
    one = run_batch(SHORT, 5, runner=run_simulation, base_seed=1)
    two = run_batch(SHORT, 5, runner=run_simulation, base_seed=2)
    assert [p.price_series for p in one.payloads] != [p.price_series for p in two.payloads]


def test_a_batchs_runs_differ_from_one_another():
    """Independent seeds mean independent runs, not five copies."""
    result = run_batch(SHORT, 5, runner=run_simulation, base_seed=48291)
    paths = {tuple(point.price for point in p.price_series) for p in result.payloads}
    assert len(paths) == 5


def test_one_run_of_a_batch_equals_that_run_on_its_own():
    """A batch is not a special way of simulating: run three of a batch
    is exactly the single run at run three's seed."""
    result = run_batch(SHORT, 4, runner=run_simulation, base_seed=48291)
    third = result.runs[3]
    alone = run_simulation(SimulationParams(ticks=SHORT.ticks, random_seed=third.seed))
    assert payload_to_dict(third.payload) == payload_to_dict(alone)


# --- results ------------------------------------------------------------------------------------------------


def test_the_payload_is_kept_exactly_as_the_runner_returned_it():
    """The batch layer stores results without interpreting them."""
    sentinel = object()
    result = run_batch(SHORT, 3, runner=lambda params: sentinel)
    assert all(run.payload is sentinel for run in result.runs)


def test_completed_and_failed_split_the_runs():
    result = run_batch(SHORT, 4, runner=_seeds_only)
    assert len(result.completed) == 4
    assert result.failed == ()
    assert all(run.ok for run in result.runs)


def test_payloads_are_the_finished_runs_results():
    result = run_batch(SHORT, 3, runner=_seeds_only)
    assert result.payloads == tuple(run.seed for run in result.runs)


def test_simulation_ids_are_preserved_per_run():
    result = run_batch(SHORT, 4, runner=run_simulation, base_seed=48291)
    ids = [run.payload.simulation.simulation_id for run in result.runs]
    assert len(set(ids)) == 4
    for run in result.runs:
        assert run.payload.simulation.random_seed == run.seed


def test_the_batch_computes_nothing_across_runs():
    """Phase 14 collects; Phase 15 aggregates. ``BatchResult`` must not
    have grown a statistic."""
    result = run_batch(SHORT, 3, runner=_seeds_only)
    forbidden = {"mean", "median", "average", "percentile", "stdev", "summary", "aggregate"}
    assert not {name for name in dir(result) if not name.startswith("_")} & forbidden


# --- failures ------------------------------------------------------------------------------------------------


def _fails_on(index_to_fail):
    seen = {"count": -1}

    def runner(params):
        seen["count"] += 1
        if seen["count"] == index_to_fail:
            raise RuntimeError("this run went wrong")
        return params.random_seed

    return runner


def test_a_failed_run_is_recorded_and_the_batch_continues():
    result = run_batch(SHORT, 5, runner=_fails_on(2))
    assert len(result.runs) == 5
    assert len(result.completed) == 4
    assert [run.index for run in result.failed] == [2]


def test_a_failure_keeps_enough_to_diagnose_it():
    result = run_batch(SHORT, 3, runner=_fails_on(1))
    failure = result.failed[0]
    assert failure.error == "RuntimeError: this run went wrong"
    assert failure.payload is None
    assert failure.seed == batch_seed(SHORT.random_seed, 1)
    assert not failure.ok


def test_failures_are_deterministic():
    assert [r.index for r in run_batch(SHORT, 5, runner=_fails_on(3)).failed] == [
        r.index for r in run_batch(SHORT, 5, runner=_fails_on(3)).failed
    ]


def test_an_interrupt_stops_the_batch_rather_than_being_collected():
    def interrupted(params):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_batch(SHORT, 5, runner=interrupted)


def test_a_configuration_the_simulator_rejects_fails_every_run():
    """AMM mode does not support whales; the batch reports it rather than
    softening it into partial results."""
    params = SimulationParams(ticks=3, pricing_mode="amm", include_whales=True, random_seed=1)
    result = run_batch(params, 3, runner=run_simulation)
    assert len(result.failed) == 3
    assert all("Whales are not supported" in run.error for run in result.failed)


# --- across the simulator's features --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=10, random_seed=48291),
        SimulationParams(ticks=10, pricing_mode="amm", include_whales=False, random_seed=48291),
        SimulationParams(
            ticks=20, pricing_mode="amm", include_whales=False,
            scenario="pump_and_dump", random_seed=48291,
        ),
        SimulationParams(ticks=20, scenario="wash_trading", random_seed=48291),
        SimulationParams(
            ticks=12, events=True, random_events=True, psychology=True,
            whale_observation=True, random_seed=48291,
        ),
    ],
    ids=["random_walk", "amm", "amm-pump_and_dump", "wash_trading", "events-psychology-whales"],
)
def test_a_batch_runs_every_supported_configuration(params):
    result = run_batch(params, 3, runner=run_simulation)
    assert len(result.completed) == 3
    for run in result.runs:
        assert run.payload.simulation.pricing_mode == params.pricing_mode
        assert run.payload.simulation.completed_ticks == params.ticks
    assert len({tuple(p.price_series) for p in result.payloads}) == 3


def test_a_batch_of_a_saved_scenario(tmp_path):
    """A scenario becomes an ordinary validated request before it reaches
    the batch runner, which never sees a database."""
    from crypto_simulator.data.database import connect, init_db
    from crypto_simulator.services.scenarios import ScenarioService

    params = SimulationParams(ticks=10, pricing_mode="amm", include_whales=False, random_seed=48291)
    conn = connect(tmp_path / "scenarios.db")
    init_db(conn)
    ScenarioService(conn).save("amm-nightly", params)
    loaded = ScenarioService(conn).load("amm-nightly")
    conn.close()

    result = run_batch(loaded, 4, runner=run_simulation)
    assert len(result.completed) == 4
    assert result.base_seed == 48291
    assert result.params.pricing_mode == "amm"
