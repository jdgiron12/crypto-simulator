"""Storage for named, reusable simulation configurations (Phase 13).

A *scenario* here is a set of simulation **inputs** saved under a name:
what to ask for, kept so it can be asked for again. That is a different
thing from a *run* (``coin_runs.py``, Phase 12), which is what one
request produced, and different again from a live simulator, which
nothing in this package stores — loading a scenario rebuilds a request
and runs it from the start, it does not resume anything.

**Dicts in, dicts out**, like ``CoinRunRepository``. The stored
parameters are a plain mapping, so this module depends on no front end
and on no service: ``services.scenarios`` owns turning one into a
validated ``SimulationParams``, and this owns the SQL. Values are stored
as JSON text — never pickled — so what comes back is data, not a Python
object a stored row could choose.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

__all__ = ["CoinScenarioRepository", "StoredScenario"]


@dataclass(frozen=True)
class StoredScenario:
    """One saved scenario, as it is stored.

    ``params`` is the request as a plain mapping; validating it into a
    ``SimulationParams`` is the service layer's job, so a row that was
    written by an older version can be read and reported on even if it no
    longer validates.
    """

    scenario_id: int
    name: str
    description: str | None
    created_at: str
    updated_at: str
    params: dict[str, Any]


@dataclass(frozen=True)
class ScenarioSummary:
    """A scenario's identity without its parameters, for listings."""

    scenario_id: int
    name: str
    description: str | None
    created_at: str
    updated_at: str


class CoinScenarioRepository:
    """Reads and writes saved scenarios in the ``coin_scenarios`` table.

    Takes a live connection and never opens or closes one, as every other
    repository here does.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- writing -----------------------------------------------------------------------------------

    def save(
        self,
        name: str,
        params: Mapping[str, Any],
        *,
        description: str | None = None,
        now: str | None = None,
    ) -> int:
        """Save ``params`` under ``name`` and return the scenario's id.

        Saving under a name that already exists **updates** that scenario
        rather than adding a second one: a name is the identity a user
        refers to, so two scenarios may not share one. The update keeps
        the original ``created_at`` and moves ``updated_at``. Write and
        timestamp go in one transaction.
        """
        name = _validated_name(name)
        if not isinstance(params, Mapping):
            raise ValueError(f"params must be a mapping (got {type(params).__name__})")
        if description is not None and not isinstance(description, str):
            raise ValueError(f"description must be a string or None (got {description!r})")
        stamp = now or datetime.now(timezone.utc).isoformat()
        payload = json.dumps(dict(params), sort_keys=True, separators=(",", ":"))
        with self._conn:  # commits on success, rolls back on any exception
            self._conn.execute(
                """
                INSERT INTO coin_scenarios (name, description, created_at, updated_at, params_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (name) DO UPDATE SET
                    description = excluded.description,
                    updated_at  = excluded.updated_at,
                    params_json = excluded.params_json
                """,
                (name, description, stamp, stamp, payload),
            )
            row = self._conn.execute(
                "SELECT scenario_id FROM coin_scenarios WHERE name = ?", (name,)
            ).fetchone()
        return int(row["scenario_id"])

    def delete(self, name: str) -> bool:
        """Remove a saved scenario. ``True`` if one was removed.

        A named registry a user writes to needs a way to unwrite an entry;
        the run log in ``coin_runs`` is append-only and has no equivalent.
        """
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM coin_scenarios WHERE name = ?", (_validated_name(name),)
            )
        return cursor.rowcount > 0

    # --- reading -----------------------------------------------------------------------------------

    def load(self, name: str) -> StoredScenario | None:
        """The scenario saved under ``name``, or ``None`` if there is none.

        Raises ``ValueError`` if the stored JSON cannot be read or does
        not describe a mapping — a corrupted row is reported, never
        quietly turned into an empty or default request.
        """
        row = self._conn.execute(
            "SELECT * FROM coin_scenarios WHERE name = ?", (_validated_name(name),)
        ).fetchone()
        if row is None:
            return None
        try:
            params = json.loads(row["params_json"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"scenario {name!r} has unreadable stored parameters: {exc}") from exc
        if not isinstance(params, dict):
            raise ValueError(
                f"scenario {name!r} stored parameters must be a JSON object "
                f"(got {type(params).__name__})"
            )
        return StoredScenario(
            scenario_id=row["scenario_id"],
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            params=params,
        )

    def list_scenarios(self) -> list[ScenarioSummary]:
        """Every saved scenario by name, without reading its parameters."""
        rows = self._conn.execute(
            "SELECT scenario_id, name, description, created_at, updated_at "
            "FROM coin_scenarios ORDER BY name"
        ).fetchall()
        return [ScenarioSummary(**dict(row)) for row in rows]


def _validated_name(name: str) -> str:
    """A scenario name is a non-empty string, used as given.

    It reaches SQL only as a bound parameter, so nothing here is about
    escaping; this rejects the names that cannot identify anything.
    """
    if not isinstance(name, str):
        raise ValueError(f"scenario name must be a string (got {type(name).__name__})")
    if not name.strip():
        raise ValueError("scenario name must not be empty")
    return name
