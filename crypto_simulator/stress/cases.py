"""The configurations the stress suite runs (Phase 16).

A stress case is a demanding but *valid* request — or a deliberately
invalid one, to check that it is refused cleanly. Nothing here adds a
market mechanic, a participant type or a limit: every case is expressed
in the options the simulator already accepts, and the boundaries it tests
are the ones the simulator already validates.

**Where the numbers come from.** ``ticks`` 1-2000 is ``MAX_TICKS``, seeds
0-2**32-1 are ``MIN_SEED``/``MAX_SEED``, batch runs 1-1000 are
``MAX_BATCH_RUNS``, and whales-with-AMM is the combination
``build_coin_simulator`` refuses. The one number that is *not* the
simulator's is the trader population: ``coin.traders`` is a configuration
list with no validated maximum, so ``HARNESS_MAX_TRADERS`` below is this
harness's own ceiling, chosen to stay inside a few seconds and tens of
megabytes. It is not a simulator limit, and Phase 16 does not add one.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping

from crypto_simulator.config import get_settings
from crypto_simulator.config.settings import Settings, TraderSettings
from crypto_simulator.services.batch import MAX_BATCH_RUNS
from crypto_simulator.services.coin_simulation import MAX_SEED, MIN_SEED
from crypto_simulator.services.simulation_params import MAX_TICKS

__all__ = [
    "HARNESS_MAX_TRADERS",
    "STRESS_CASES",
    "Expectation",
    "StressCase",
    "heavy_cases",
    "light_cases",
    "settings_for",
]

#: This harness's trader ceiling — *not* a simulator maximum, which does
#: not exist. Cost is roughly ticks x traders, so this is the population
#: that keeps the heaviest case (paired with ``MAX_TICKS``) within a few
#: seconds and well under a hundred megabytes on a developer machine.
HARNESS_MAX_TRADERS = 200


class Expectation(str, Enum):
    """What a case is supposed to do."""

    COMPLETES = "completes"
    REJECTED = "rejected"


@dataclass(frozen=True)
class StressCase:
    """One demanding configuration and what should become of it.

    ``params`` holds ``SimulationParams`` keyword arguments rather than a
    built request, because a case may deliberately be invalid and a
    built request would have raised before the suite could run it — the
    rejection is the thing under test.
    """

    name: str
    description: str
    params: Mapping[str, Any] = field(default_factory=dict)
    runs: int = 1
    traders: int | None = None
    expectation: Expectation = Expectation.COMPLETES
    expected_error: str | None = None
    heavy: bool = False
    repeat_for_determinism: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a stress case needs a name")
        if self.expectation is Expectation.REJECTED and not self.expected_error:
            raise ValueError(f"{self.name}: a rejected case must say what error it expects")
        if self.traders is not None and self.traders < 0:
            raise ValueError(f"{self.name}: traders must not be negative")


def settings_for(case: StressCase, base: Settings | None = None) -> Settings | None:
    """The settings a case runs against, or ``None`` for the configured
    ones.

    Only the trader population is ever overridden, and only by replacing
    the configuration list the builder already reads — no new
    configuration mechanism, and the application's own settings are left
    untouched.
    """
    if case.traders is None:
        return None
    settings = base or get_settings()
    population = [
        TraderSettings(
            id=f"stress-trader-{index}",
            strategy="retail",
            starting_cash=10_000.0,
            starting_coins=1_000.0,
            trade_probability=0.5,
            max_trade_size=5_000.0,
            risk_tolerance=0.5,
        )
        for index in range(case.traders)
    ]
    return replace(settings, coin=replace(settings.coin, traders=population))


#: Every stress case, in the order the suite runs them.
STRESS_CASES: tuple[StressCase, ...] = (
    # --- tick count, at the validated boundaries -------------------------------------------
    StressCase(
        name="ticks-minimum",
        description=f"the shortest run the simulator accepts ({1} tick)",
        params={"ticks": 1, "random_seed": 48291},
        repeat_for_determinism=True,
    ),
    StressCase(
        name="ticks-ordinary",
        description="a routine run, as a baseline for the rest",
        params={"ticks": 200, "random_seed": 48291},
    ),
    StressCase(
        name="ticks-maximum",
        description=f"the longest run the simulator accepts ({MAX_TICKS} ticks)",
        params={"ticks": MAX_TICKS, "random_seed": 48291},
        repeat_for_determinism=True,
    ),
    # --- seeds, at the validated boundaries ------------------------------------------------
    StressCase(
        name="seed-minimum",
        description=f"seed {MIN_SEED}, the lowest accepted",
        params={"ticks": 100, "random_seed": MIN_SEED},
        repeat_for_determinism=True,
    ),
    StressCase(
        name="seed-maximum",
        description=f"seed {MAX_SEED}, the highest accepted",
        params={"ticks": 100, "random_seed": MAX_SEED},
        repeat_for_determinism=True,
    ),
    # --- participants ----------------------------------------------------------------------
    StressCase(
        name="traders-none",
        description="a market with no traders at all",
        params={"ticks": 100, "include_traders": False, "random_seed": 48291},
    ),
    StressCase(
        name="traders-many",
        description=f"{HARNESS_MAX_TRADERS} traders (a harness ceiling, not a simulator one)",
        params={"ticks": 100, "random_seed": 48291},
        traders=HARNESS_MAX_TRADERS,
    ),
    StressCase(
        name="participants-none",
        description="neither traders nor whales: price process alone",
        params={"ticks": 100, "include_traders": False, "include_whales": False,
                "random_seed": 48291},
    ),
    # --- pricing modes and feature combinations ---------------------------------------------
    StressCase(
        name="amm-ordinary",
        description="AMM pricing, which settles every fill through the pool",
        params={"ticks": 200, "pricing_mode": "amm", "include_whales": False,
                "random_seed": 48291},
        repeat_for_determinism=True,
    ),
    StressCase(
        name="amm-everything",
        description="AMM with a manipulation scheme, news and psychology at once",
        params={"ticks": 200, "pricing_mode": "amm", "include_whales": False,
                "scenario": "pump_and_dump", "events": True, "random_events": True,
                "psychology": True, "random_seed": 48291},
    ),
    StressCase(
        name="random-walk-everything",
        description="random walk with whales, wash trading, news, psychology and observation",
        params={"ticks": 200, "scenario": "wash_trading", "events": True,
                "random_events": True, "psychology": True, "whale_observation": True,
                "random_seed": 48291},
    ),
    # --- batches ----------------------------------------------------------------------------
    StressCase(
        name="batch-single",
        description="a batch of one, the smallest accepted",
        params={"ticks": 50, "random_seed": 48291},
        runs=1,
    ),
    StressCase(
        name="batch-small",
        description="a batch of 50 runs with psychology and news",
        params={"ticks": 50, "events": True, "psychology": True, "random_seed": 48291},
        runs=50,
    ),
    # --- deliberately invalid: each must be refused, not survived ----------------------------
    StressCase(
        name="invalid-ticks-zero",
        description="fewer ticks than the simulator accepts",
        params={"ticks": 0},
        expectation=Expectation.REJECTED,
        expected_error="ticks must be between",
    ),
    StressCase(
        name="invalid-ticks-above-maximum",
        description=f"one tick more than {MAX_TICKS}",
        params={"ticks": MAX_TICKS + 1},
        expectation=Expectation.REJECTED,
        expected_error="ticks must be between",
    ),
    StressCase(
        name="invalid-seed-negative",
        description="a seed below the accepted range",
        params={"ticks": 10, "random_seed": MIN_SEED - 1},
        expectation=Expectation.REJECTED,
        expected_error="random_seed must be between",
    ),
    StressCase(
        name="invalid-seed-above-maximum",
        description="a seed above the accepted range",
        params={"ticks": 10, "random_seed": MAX_SEED + 1},
        expectation=Expectation.REJECTED,
        expected_error="random_seed must be between",
    ),
    StressCase(
        name="invalid-pricing-mode",
        description="a pricing mode the simulator does not have",
        params={"ticks": 10, "pricing_mode": "moonmath"},
        expectation=Expectation.REJECTED,
        expected_error="unknown pricing_mode",
    ),
    StressCase(
        name="invalid-scenario",
        description="a manipulation preset that does not exist",
        params={"ticks": 10, "scenario": "rug_pull"},
        expectation=Expectation.REJECTED,
        expected_error="unknown scenario",
    ),
    StressCase(
        name="invalid-whales-in-amm",
        description="whales with AMM pricing, which the builder refuses",
        params={"ticks": 10, "pricing_mode": "amm", "include_whales": True},
        expectation=Expectation.REJECTED,
        expected_error="Whales are not supported",
    ),
    StressCase(
        name="invalid-batch-zero-runs",
        description="a batch of no runs",
        params={"ticks": 10, "random_seed": 48291},
        runs=0,
        expectation=Expectation.REJECTED,
        expected_error="runs must be between",
    ),
    StressCase(
        name="invalid-batch-above-maximum",
        description=f"one run more than {MAX_BATCH_RUNS}",
        params={"ticks": 10, "random_seed": 48291},
        runs=MAX_BATCH_RUNS + 1,
        expectation=Expectation.REJECTED,
        expected_error="runs must be between",
    ),
    # --- the heavy tier, kept out of the ordinary test run ------------------------------------
    StressCase(
        name="heavy-max-ticks-many-traders",
        description=f"{MAX_TICKS} ticks x {HARNESS_MAX_TRADERS} traders, the costliest corner",
        params={"ticks": MAX_TICKS, "random_seed": 48291},
        traders=HARNESS_MAX_TRADERS,
        heavy=True,
    ),
    StressCase(
        name="heavy-batch-maximum",
        description=f"{MAX_BATCH_RUNS} runs, the largest batch accepted",
        params={"ticks": 20, "random_seed": 48291},
        runs=MAX_BATCH_RUNS,
        heavy=True,
    ),
)


def light_cases() -> tuple[StressCase, ...]:
    """Every case cheap enough for an ordinary test run."""
    return tuple(case for case in STRESS_CASES if not case.heavy)


def heavy_cases() -> tuple[StressCase, ...]:
    """The cases kept behind the opt-in tier."""
    return tuple(case for case in STRESS_CASES if case.heavy)
