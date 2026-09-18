"""``SimulationParams``: what to run, validated (Phase 10, moved Phase 13).

The coin track's canonical simulation *input* type — the closed set of
user-controlled options a run is requested with, as opposed to the run's
output (``SimulationReport``) or a stored result (``data.coin_runs``).

It began in ``dashboard/data.py`` in Phase 10, where the dashboard was its
only caller. Phase 13 saves and reloads these as named scenarios through
a service, and ``services`` may not import ``dashboard``, so the type
moved here — beside ``build_coin_simulator``, whose keyword arguments its
fields mirror. ``dashboard.data`` re-exports every name below, so nothing
that imported them from there had to change, and no field, default,
validation rule or declaration order changed in the move: the same
request still serializes the same way and still derives the same
``simulation_id``.
"""

from __future__ import annotations

from dataclasses import dataclass

from crypto_simulator.core.coin_simulator import PricingMode
from crypto_simulator.services.coin_simulation import (
    MANIPULATION_SCENARIOS,
    MAX_SEED,
    MIN_SEED,
)

__all__ = ["MAX_TICKS", "PRICING_MODES", "SCENARIOS", "SimulationParams"]

#: Upper bound on a *validated* request — a dashboard run, or a scenario
#: saved in Phase 13. A dashboard run is synchronous, so the bound keeps
#: one request from blocking the UI indefinitely, and a stored scenario
#: is held to the same limit so that anything saved can also be run from
#: the browser. It is not a simulator limit: ``scripts/simulate_coin.py
#: --ticks`` is unbounded, as it always has been.
MAX_TICKS = 2000

PRICING_MODES: tuple[str, ...] = tuple(mode.value for mode in PricingMode)
SCENARIOS: tuple[str, ...] = tuple(sorted(MANIPULATION_SCENARIOS))


@dataclass(frozen=True)
class SimulationParams:
    """What to run — the CLI's flags, validated.

    Each field mirrors an option of ``scripts/simulate_coin.py``:
    ``ticks`` (``--ticks``), ``pricing_mode`` (``--pricing-mode``),
    ``include_traders``/``include_whales`` (``--no-traders``/
    ``--no-whales``), ``scenario`` (``--scenario``), ``events``
    (``--events``), ``random_events`` (``--random-events``),
    ``psychology`` (``--psychology``) and ``whale_observation``
    (``--whale-observation``). The defaults are the CLI's defaults.

    ``scenario`` names a *manipulation preset* from
    ``MANIPULATION_SCENARIOS`` (``pump_and_dump``, ``wash_trading``) — one
    field of a request, not the whole request. A Phase 13 *saved
    scenario* is a named copy of an entire ``SimulationParams``; the two
    senses of the word are documented in ``services/scenarios.py``.

    ``random_seed`` mirrors ``--seed`` (Phase 11) and the dashboard's seed
    control (Phase 10 Step 7). ``None`` means the configured seed —
    ``simulation.random_seed`` — which is what every run used before those
    phases; an integer runs the same request against a different seed. The
    seed is not a new simulator input, only a selected one: it is the
    value ``build_coin_simulator`` already derives every participant seed
    from.

    Validation happens on construction and rejects anything outside the
    known set, so an invalid request never reaches the builder — whether
    it came from the dashboard's controls or out of a stored scenario.
    """

    ticks: int = 20
    pricing_mode: str = PricingMode.RANDOM_WALK.value
    include_traders: bool = True
    include_whales: bool = True
    scenario: str | None = None
    events: bool = False
    random_events: bool = False
    psychology: bool = False
    whale_observation: bool = False
    random_seed: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ticks, int) or isinstance(self.ticks, bool):
            raise ValueError(f"ticks must be an integer (got {self.ticks!r})")
        if not 1 <= self.ticks <= MAX_TICKS:
            raise ValueError(f"ticks must be between 1 and {MAX_TICKS} (got {self.ticks})")
        if self.pricing_mode not in PRICING_MODES:
            raise ValueError(
                f"unknown pricing_mode {self.pricing_mode!r}; expected one of {list(PRICING_MODES)}"
            )
        if self.scenario is not None and self.scenario not in MANIPULATION_SCENARIOS:
            raise ValueError(
                f"unknown scenario {self.scenario!r}; expected one of {list(SCENARIOS)} or None"
            )
        for name in ("include_traders", "include_whales", "events", "random_events",
                     "psychology", "whale_observation"):
            value = getattr(self, name)
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be True or False (got {value!r})")
        if self.random_seed is not None:
            if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
                raise ValueError(
                    f"random_seed must be an integer or None (got {self.random_seed!r})"
                )
            if not MIN_SEED <= self.random_seed <= MAX_SEED:
                raise ValueError(
                    f"random_seed must be between {MIN_SEED} and {MAX_SEED} "
                    f"(got {self.random_seed})"
                )
