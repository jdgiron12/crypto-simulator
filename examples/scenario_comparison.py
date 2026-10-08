#!/usr/bin/env python
"""Example 2: the same seeded run under different market-condition presets.

    python examples/scenario_comparison.py

A *market condition* (``bull``, ``bear``, ``meme`` in
``services/market_conditions.py``) is a named configuration preset: it
changes the news mix, how often news arrives, and, in random-walk mode,
how strongly the walk drifts with news sentiment. It is a different thing
from a *manipulation scenario* (``pump_and_dump``, ``wash_trading``) and
from a *saved scenario* (a stored request, CLI only).

Every configuration below uses the same base seed and the same options,
so the only difference between the runs is the preset. Each row is one
seeded run, not a distribution: a preset tilts the odds, it does not
decree an outcome, and any single run may move against it. For spreads
across many seeds, see examples/batch_statistics.py or the dashboard's
scenario-comparison panel. Nothing here forecasts a real market.
"""

from __future__ import annotations

from crypto_simulator.dashboard.data import SimulationParams, run_simulation

SEED = 48291
TICKS = 200

#: ``None`` is the neutral configuration (no preset).
CONDITIONS: tuple[str | None, ...] = (None, "bull", "bear")


def main() -> None:
    print(f"Market-condition comparison: {TICKS} ticks, random_walk, seed {SEED}")
    print()
    print(f"  {'Condition':<10} {'Final price':>12} {'Return':>9} {'Volatility':>11} {'Total volume':>14}")
    print("  " + "-" * 60)
    for condition in CONDITIONS:
        params = SimulationParams(ticks=TICKS, random_seed=SEED, market_condition=condition)
        market = run_simulation(params).report.market
        print(
            f"  {condition or 'neutral':<10} {market.close_price:>12.4f} "
            f"{market.cumulative_return:>+9.2%} {market.volatility:>11.4f} "
            f"{market.volume_breakdown.total_volume:>14,.0f}"
        )
    print()
    print("  One seeded synthetic run per preset; descriptive only, not a forecast.")


if __name__ == "__main__":
    main()
