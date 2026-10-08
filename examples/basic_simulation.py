#!/usr/bin/env python
"""Example 1: one reproducible, seeded coin-economy simulation.

    python examples/basic_simulation.py

Runs a single synthetic simulation with an explicit seed, prints a few
figures from its analytics report, then runs the same request again and
checks that the two results are identical.

``run_simulation`` (in ``crypto_simulator/dashboard/data.py``) is the
project's single-run entry point: it builds the simulator with
``build_coin_simulator``, runs it, and builds the ``SimulationReport``. The
CLI's batch mode, the stress harness and the dashboard all go through it.
Nothing is written to disk.

Same seed, same options -> same run, on the same platform and Python
version (see docs/REPRODUCIBILITY.md for what that does and does not
guarantee). Everything here is fictional; no figure says anything about a
real market.
"""

from __future__ import annotations

from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation

SEED = 48291
TICKS = 50


def main() -> None:
    params = SimulationParams(ticks=TICKS, random_seed=SEED)

    payload = run_simulation(params)
    market = payload.report.market  # the report's MarketSummary

    print("Basic seeded simulation")
    print(f"  Seed            : {payload.simulation.random_seed}")
    print(f"  Ticks           : {payload.simulation.completed_ticks}")
    print(f"  Pricing mode    : {payload.simulation.pricing_mode}")
    print(f"  Simulation id   : {payload.simulation.simulation_id}")
    print(f"  Final price     : {market.close_price:.4f} (started at {market.open_price:.4f})")
    print(f"  Return          : {market.cumulative_return:+.2%} (cumulative)")
    print(f"  Max drawdown    : {market.max_drawdown:.2%}")
    print(f"  Total volume    : {market.volume_breakdown.total_volume:,.0f} {payload.simulation.coin_symbol}")

    # The same request again: every recorded figure must come back identical.
    repeat = run_simulation(params)
    matches = payload_to_dict(repeat) == payload_to_dict(payload)
    print(f"  Repeated run matches: {matches}")
    assert matches, "the same seed and options gave a different run"


if __name__ == "__main__":
    main()
