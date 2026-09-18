"""``ScenarioService``: named simulation configurations (Phase 13).

The boundary between a stored scenario and a runnable request. The
repository below it (``data.coin_scenarios``) knows rows and JSON; this
knows ``SimulationParams``, and callers — the CLI, and anything later —
talk to this rather than to the repository, the same way
``MarketService`` fronts its repositories.

**Two senses of "scenario".** A *saved scenario* is what this module
handles: a whole ``SimulationParams`` under a user-chosen name. A
*manipulation preset* is the older sense — ``pump_and_dump`` and
``wash_trading`` in ``MANIPULATION_SCENARIOS``, selected by the
``scenario`` field *inside* a request. A saved scenario can name a
manipulation preset; it is not one.

**Inputs, not outputs, and not a checkpoint.** What is stored is the
request. Loading one rebuilds that request and runs it again from tick
one — reproducing the original run exactly, because the seed is part of
what was saved. Nothing here pauses or resumes a live ``CoinSimulator``;
``data.coin_runs`` stores what a run produced, and that is a separate
thing.

**Validation is the existing validation.** A loaded scenario becomes a
``SimulationParams``, so a stored request is held to exactly the rules a
typed-in one is — there is no second definition of what a valid request
is, and a scenario that fails them is reported rather than quietly
turned into a different, valid one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import fields
from typing import Any, Mapping

from crypto_simulator.data.coin_scenarios import (
    CoinScenarioRepository,
    ScenarioSummary,
    StoredScenario,
)
from crypto_simulator.services.simulation_params import SimulationParams

__all__ = ["ScenarioNotFound", "ScenarioService", "ScenarioSummary", "params_to_dict"]

_FIELD_NAMES = tuple(field.name for field in fields(SimulationParams))


class ScenarioNotFound(LookupError):
    """No scenario is saved under that name."""


def params_to_dict(params: SimulationParams) -> dict[str, Any]:
    """A request as a plain mapping, field by declared field.

    Written out explicitly rather than with ``dataclasses.asdict`` so
    that what is stored is this module's decision and not a side effect
    of the dataclass: every value here is already a ``str``, ``int``,
    ``bool`` or ``None``.
    """
    return {name: getattr(params, name) for name in _FIELD_NAMES}


def params_from_dict(params: Mapping[str, Any], *, source: str = "scenario") -> SimulationParams:
    """Turn stored parameters back into a validated request.

    Unknown and missing fields are named in the error rather than left to
    a ``TypeError`` from the constructor, so a scenario written by a
    different version of the project says what is wrong with it.
    """
    if not isinstance(params, Mapping):
        raise ValueError(f"{source} parameters must be a mapping (got {type(params).__name__})")
    unknown = sorted(set(params) - set(_FIELD_NAMES))
    if unknown:
        raise ValueError(
            f"{source} has unknown parameters {unknown}; expected only {list(_FIELD_NAMES)}"
        )
    missing = [name for name in _FIELD_NAMES if name not in params]
    if missing:
        raise ValueError(f"{source} is missing parameters {missing}")
    # SimulationParams validates on construction; a bad value raises from
    # there, with that type's own message.
    return SimulationParams(**dict(params))


class ScenarioService:
    """Save, load, list and delete named simulation configurations."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._scenarios = CoinScenarioRepository(conn)

    def save(
        self,
        name: str,
        params: SimulationParams,
        *,
        description: str | None = None,
        now: str | None = None,
    ) -> int:
        """Store ``params`` under ``name``, replacing that name's previous
        configuration if it had one. Returns the scenario's id."""
        if not isinstance(params, SimulationParams):
            raise ValueError(
                f"params must be a SimulationParams (got {type(params).__name__})"
            )
        return self._scenarios.save(
            name, params_to_dict(params), description=description, now=now
        )

    def load(self, name: str) -> SimulationParams:
        """The request saved under ``name``, validated.

        Raises ``ScenarioNotFound`` if there is no such scenario, and
        ``ValueError`` if what was stored is not a request this version
        can run.
        """
        stored = self._scenarios.load(name)
        if stored is None:
            raise ScenarioNotFound(f"no scenario named {name!r}")
        return params_from_dict(stored.params, source=f"scenario {name!r}")

    def describe(self, name: str) -> StoredScenario:
        """A scenario exactly as stored — parameters unvalidated, plus its
        name, description and timestamps. Reads a row this version might
        not be able to run, which ``load`` deliberately refuses to."""
        stored = self._scenarios.load(name)
        if stored is None:
            raise ScenarioNotFound(f"no scenario named {name!r}")
        return stored

    def list_scenarios(self) -> list[ScenarioSummary]:
        """Every saved scenario, by name."""
        return self._scenarios.list_scenarios()

    def delete(self, name: str) -> bool:
        """Remove a saved scenario. ``True`` if one was removed."""
        return self._scenarios.delete(name)
