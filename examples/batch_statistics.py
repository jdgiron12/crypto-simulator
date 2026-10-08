#!/usr/bin/env python
"""Example 3: a small batch of seeded runs and its aggregate statistics.

    python examples/batch_statistics.py

``run_batch`` (``services/batch.py``) runs one request many times. Run *i*
uses seed ``base_seed + i * 10000`` (``BATCH_SEED_STRIDE``), so the whole
batch is reproducible from its base seed, and any single run can be rerun
on its own with that seed. The batch does not run simulations itself: it
calls the ``runner`` it is given, here the same ``run_simulation`` the CLI
and the dashboard use.

``aggregate_batch`` (``analytics/aggregate.py``) then describes how each
report metric was spread across the successful runs. The figures are
descriptive statistics of synthetic runs, not probabilities of real
outcomes. Nothing is written to disk.
"""

from __future__ import annotations

from crypto_simulator.analytics import aggregate_batch
from crypto_simulator.dashboard.data import SimulationParams, run_simulation
from crypto_simulator.services.batch import run_batch

BASE_SEED = 48291
RUNS = 20
TICKS = 50


def main() -> None:
    params = SimulationParams(ticks=TICKS)
    batch = run_batch(params, RUNS, runner=run_simulation, base_seed=BASE_SEED)
    stats = aggregate_batch(batch)

    print(f"Batch of {RUNS} runs, {TICKS} ticks each")
    print(f"  Base seed       : {batch.base_seed}")
    print(f"  First run seeds : {', '.join(str(run.seed) for run in batch.runs[:3])}, ...")
    print(f"  Successful runs : {stats.successful_runs} of {stats.requested_runs}")
    print()

    close = stats.metric("close_price")
    print("  Close price across runs")
    print(f"    mean   : {close.mean:.4f}")
    print(f"    median : {close.median:.4f}")
    print(f"    std dev: {close.standard_deviation:.4f} (sample)")
    print(f"    P5-P95 : {close.percentile(5):.4f} to {close.percentile(95):.4f}")

    drawdown = stats.metric("max_drawdown")
    print(f"  Median max drawdown: {drawdown.median:.2%} (min {drawdown.minimum:.2%}, max {drawdown.maximum:.2%})")


if __name__ == "__main__":
    main()
