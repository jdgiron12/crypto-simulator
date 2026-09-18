"""Running one configuration many times (Phase 14).

A batch is the same request run repeatedly under independent
deterministic seeds, so that later work can look across the runs rather
than at one of them. This module is the orchestration only: it decides
what each run is asked for and keeps what each run returned.

**It does not run simulations itself.** ``run_batch`` is given a
``runner`` and calls it once per run. That keeps the simulation engine
where it already is — there is exactly one of it, and this is not a
second — and keeps this module in ``services`` rather than reaching up
into a front end for the entry point it would otherwise need. It is the
same injection ``build_coin_simulator`` already gets from
``run_simulation``, one layer further out.

**Seeds.** Each run's base seed is ``_derive_seed(base_seed, index *
BATCH_SEED_STRIDE)`` — the derivation every participant seed already
comes from, applied once more at the batch level. The stride matters:
see ``BATCH_SEED_STRIDE``. Nothing here reads or writes global random
state, and the batch draws no random number of its own — every seed is
computed from the base.

**Serial, in memory, deterministic.** Runs execute in index order, one
after another. A run takes a few milliseconds and its payload a few tens
of kilobytes, so a batch of hundreds costs seconds and tens of megabytes;
parallelism would buy little and would put ordering and reproducibility
at risk, so it is deliberately not here.

**What a batch does not do.** It computes nothing across runs — no mean,
no distribution, no comparison. ``BatchResult`` is a collection of
individual results plus the identity of the batch that produced them;
reading across them is Phase 15's job. It also stores nothing: a batch
writes no database row.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Protocol

from crypto_simulator.config import get_settings
from crypto_simulator.config.settings import Settings
from crypto_simulator.services.coin_simulation import BATCH_SEED_STRIDE, _derive_seed
from crypto_simulator.services.simulation_params import SimulationParams

__all__ = [
    "MAX_BATCH_RUNS",
    "MIN_BATCH_RUNS",
    "BatchResult",
    "BatchRun",
    "run_batch",
]

#: Bounds on how many runs one batch may hold.
#:
#: The upper bound is about memory, not about the simulator: a batch keeps
#: every run's payload, and at a few tens of kilobytes each a thousand of
#: them is tens of megabytes held at once. It is deliberately not lower —
#: a few hundred runs is an ordinary experiment — and raising it would
#: mean handing results out as they are produced rather than at the end,
#: which no phase needs yet.
MIN_BATCH_RUNS = 1
MAX_BATCH_RUNS = 1000


class SimulationRunner(Protocol):
    """What ``run_batch`` needs: something that runs one request."""

    def __call__(self, params: SimulationParams) -> Any: ...


@dataclass(frozen=True)
class BatchRun:
    """One run of a batch, whether it finished or raised.

    ``payload`` is whatever the runner returned, kept as it came back —
    this module never looks inside it, so a batch is not tied to any one
    shape of result. Exactly one of ``payload`` and ``error`` is set.
    """

    index: int
    seed: int
    payload: Any | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class BatchResult:
    """What a batch was asked for, and what came back.

    ``params`` is the request every run shared — its ``random_seed`` is
    the base the per-run seeds were derived from, so the batch can be
    repeated exactly from this object alone.
    """

    params: SimulationParams
    base_seed: int
    requested_runs: int
    runs: tuple[BatchRun, ...]

    @property
    def completed(self) -> tuple[BatchRun, ...]:
        """The runs that finished, in index order."""
        return tuple(run for run in self.runs if run.ok)

    @property
    def failed(self) -> tuple[BatchRun, ...]:
        """The runs that raised, in index order, with their messages."""
        return tuple(run for run in self.runs if not run.ok)

    @property
    def payloads(self) -> tuple[Any, ...]:
        """Every finished run's result — what Phase 15 will read across."""
        return tuple(run.payload for run in self.completed)


def batch_seed(base_seed: int, index: int) -> int:
    """The base seed of run ``index`` of a batch.

    Public because a caller reproducing one run of a batch on its own
    needs the same answer, and should not have to rederive it.
    """
    return _derive_seed(base_seed, index * BATCH_SEED_STRIDE)


def run_batch(
    params: SimulationParams,
    runs: int,
    *,
    runner: SimulationRunner,
    base_seed: int | None = None,
    settings: Settings | None = None,
) -> BatchResult:
    """Run ``params`` ``runs`` times under derived seeds.

    ``base_seed`` defaults to the request's own ``random_seed``, and then
    to the configured ``simulation.random_seed`` — so a batch is
    deterministic whether or not a seed was named, and naming none does
    not mean drawing one. Every run is the same request with its seed
    replaced, so nothing else about the configuration varies between
    them.

    A run that raises is recorded and the batch continues: one seed that
    trips a failure should not discard the runs either side of it.
    ``BaseException`` is not caught, so an interrupt still stops the
    batch immediately.
    """
    if not isinstance(params, SimulationParams):
        raise ValueError(f"params must be a SimulationParams (got {type(params).__name__})")
    if not isinstance(runs, int) or isinstance(runs, bool):
        raise ValueError(f"runs must be an integer (got {runs!r})")
    if not MIN_BATCH_RUNS <= runs <= MAX_BATCH_RUNS:
        raise ValueError(
            f"runs must be between {MIN_BATCH_RUNS} and {MAX_BATCH_RUNS} (got {runs})"
        )
    if base_seed is not None and (not isinstance(base_seed, int) or isinstance(base_seed, bool)):
        raise ValueError(f"base_seed must be an integer or None (got {base_seed!r})")

    effective_base = _effective_base_seed(params, base_seed, settings)
    results = []
    for index in range(runs):
        seed = batch_seed(effective_base, index)
        # Validates the derived seed the way any other request is
        # validated: a stride that ran past the seed bound is an error
        # about the batch, not a run that quietly used something else.
        run_params = replace(params, random_seed=seed)
        try:
            payload = runner(run_params)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            results.append(BatchRun(index=index, seed=seed, error=f"{type(exc).__name__}: {exc}"))
        else:
            results.append(BatchRun(index=index, seed=seed, payload=payload))
    return BatchResult(
        params=replace(params, random_seed=effective_base),
        base_seed=effective_base,
        requested_runs=runs,
        runs=tuple(results),
    )


def _effective_base_seed(
    params: SimulationParams, base_seed: int | None, settings: Settings | None
) -> int:
    """The seed the batch is derived from: the one given, else the
    request's, else the configured one. Never drawn."""
    if base_seed is not None:
        return base_seed
    if params.random_seed is not None:
        return params.random_seed
    return (settings or get_settings()).simulation.random_seed
