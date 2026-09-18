"""Persistence for finished coin-economy runs (Phase 12).

The coin simulation was ephemeral before this module: a run existed only
for as long as the process that produced it. ``CoinRunRepository`` stores
a *completed* run and reads it back, so later phases can reload one
(Phase 13, scenario save/load), keep many (Phase 14, batch simulation)
and aggregate across them (Phase 15).

**Observer, like the dashboard.** Nothing here runs, drives or influences
a simulation. The repository is handed a finished run and writes it down;
it draws no random numbers, touches no wallet, tick, pool or RNG, and
importing it cannot change what a simulation does.

**What it stores.** One already-serialized run payload — the same
``{"simulation": ..., "report": ..., "price_series": ...}`` mapping the
dashboard reads, which is plain JSON-compatible data by construction. The
repository takes that mapping rather than a ``DashboardPayload`` so that
it depends on no front end: the CLI, the dashboard and a future batch
runner can all save through the same call, and ``data`` keeps importing
nothing from ``dashboard``.

**How it stores it.** The run's metadata and its per-tick series become
columns — Phase 15 will aggregate over prices and volumes, and SQL is the
right tool for that — while the request and the analytics report are kept
as JSON text, because they are read whole and never queried field by
field. Nothing is pickled: every stored value is an INTEGER, a REAL or
TEXT.

**What it does not store.** Individual fills, event records, pool
reserves and per-participant state are *not* separate tables. The
report's analytics already describe them, and no approved phase needs the
raw records; adding tables for them would widen the boundary with nothing
reading them. Nor is this a checkpoint: a stored run is a finished
result, and loading one gives back that result — it cannot resume a live
``CoinSimulator``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

__all__ = ["CoinRunRepository", "StoredRun"]

#: The payload keys a run must have to be storable.
_REQUIRED_KEYS = ("simulation", "report", "price_series")

#: The metadata a run's ``simulation`` block must carry, as a column each.
_SIMULATION_COLUMNS = (
    "simulation_id",
    "random_seed",
    "pricing_mode",
    "coin_symbol",
    "coin_name",
    "initial_supply",
    "starting_price",
    "requested_ticks",
    "completed_ticks",
)

_TICK_FIELDS = ("tick", "price", "market_cap", "volume")


@dataclass(frozen=True)
class StoredRun:
    """One row of ``list_runs`` — a stored run's metadata, without its
    report or series, so a listing stays cheap however long the runs are.
    """

    run_id: int
    simulation_id: str
    saved_at: str
    random_seed: int
    pricing_mode: str
    coin_symbol: str
    requested_ticks: int
    completed_ticks: int


def _dumps(value: Any) -> str:
    """Canonical JSON: sorted keys and no incidental whitespace, so the
    same payload always produces the same text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class CoinRunRepository:
    """Reads and writes finished coin runs in the ``coin_runs`` and
    ``coin_run_ticks`` tables.

    Takes a live connection and never opens or closes one, exactly as the
    trading-platform repositories in ``repositories.py`` do —
    ``database.py`` owns connections, this owns the SQL.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- writing -----------------------------------------------------------------------------------

    def save(self, payload: Mapping[str, Any], *, saved_at: str | None = None) -> int:
        """Store one finished run and return its ``run_id``.

        The run and every one of its ticks are written in a single
        transaction: if any part fails, the whole save rolls back and no
        half-written run is left behind. ``saved_at`` defaults to now, in
        UTC, and is accepted explicitly so a caller that needs a fixed
        timestamp (a test, a replay) can give one.
        """
        simulation, series = _validated(payload)
        stamp = saved_at or datetime.now(timezone.utc).isoformat()
        values = tuple(simulation[name] for name in _SIMULATION_COLUMNS)
        with self._conn:  # commits on success, rolls back on any exception
            cursor = self._conn.execute(
                f"""
                INSERT INTO coin_runs (
                    {", ".join(_SIMULATION_COLUMNS)}, saved_at, params_json, report_json
                ) VALUES ({", ".join("?" * len(_SIMULATION_COLUMNS))}, ?, ?, ?)
                """,
                (*values, stamp, _dumps(simulation["params"]), _dumps(payload["report"])),
            )
            run_id = int(cursor.lastrowid)
            self._conn.executemany(
                "INSERT INTO coin_run_ticks (run_id, tick, price, market_cap, volume) "
                "VALUES (?, ?, ?, ?, ?)",
                [(run_id, *(point[field] for field in _TICK_FIELDS)) for point in series],
            )
        return run_id

    # --- reading -----------------------------------------------------------------------------------

    def load(self, run_id: int) -> dict[str, Any] | None:
        """The stored run as the payload it was saved from, or ``None``
        if no such run exists.

        What comes back equals what went in — the same mapping, with the
        series in tick order.
        """
        row = self._conn.execute(
            "SELECT * FROM coin_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        ticks = self._conn.execute(
            "SELECT tick, price, market_cap, volume FROM coin_run_ticks "
            "WHERE run_id = ? ORDER BY tick",
            (run_id,),
        ).fetchall()
        simulation = {name: row[name] for name in _SIMULATION_COLUMNS}
        simulation["params"] = json.loads(row["params_json"])
        return {
            "simulation": simulation,
            "report": json.loads(row["report_json"]),
            "price_series": [dict(zip(_TICK_FIELDS, tuple(tick))) for tick in ticks],
        }

    def list_runs(self, *, limit: int | None = None) -> list[StoredRun]:
        """Stored runs, newest first. Metadata only — neither the report
        nor the series is read, so listing a database of long runs costs
        the same as listing a database of short ones."""
        sql = (
            "SELECT run_id, simulation_id, saved_at, random_seed, pricing_mode, "
            "coin_symbol, requested_ticks, completed_ticks FROM coin_runs "
            "ORDER BY run_id DESC"
        )
        if limit is None:
            rows = self._conn.execute(sql).fetchall()
        else:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise ValueError(f"limit must be a non-negative integer (got {limit!r})")
            rows = self._conn.execute(f"{sql} LIMIT ?", (limit,)).fetchall()
        return [StoredRun(**dict(row)) for row in rows]


def _validated(payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]:
    """Check a payload's shape before any of it is written.

    A bad payload is rejected here, with a message naming what is wrong,
    rather than part-way through the insert — the transaction would roll
    it back either way, but the caller gets a clear error instead of a
    database one.
    """
    missing = [key for key in _REQUIRED_KEYS if key not in payload]
    if missing:
        raise ValueError(f"payload is missing {missing}; expected {list(_REQUIRED_KEYS)}")
    simulation = payload["simulation"]
    if not isinstance(simulation, Mapping):
        raise ValueError(f"payload['simulation'] must be a mapping (got {type(simulation).__name__})")
    absent = [name for name in (*_SIMULATION_COLUMNS, "params") if name not in simulation]
    if absent:
        raise ValueError(f"payload['simulation'] is missing {absent}")
    series = payload["price_series"]
    if isinstance(series, (str, bytes)) or not isinstance(series, Sequence):
        raise ValueError(f"payload['price_series'] must be a sequence (got {type(series).__name__})")
    for index, point in enumerate(series):
        if not isinstance(point, Mapping):
            raise ValueError(f"price_series[{index}] must be a mapping (got {type(point).__name__})")
        lacking = [field for field in _TICK_FIELDS if field not in point]
        if lacking:
            raise ValueError(f"price_series[{index}] is missing {lacking}")
    return simulation, series
