"""SQLite connection management for the Crypto Market Simulator.

This module owns *how* we talk to SQLite (connections, schema
initialization). It knows nothing about business rules — repositories
build on top of it, and services build on top of repositories.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _ensure_parent_dir(db_path: str | Path) -> None:
    path = Path(db_path)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)


def connect(db_path: str | Path, *, echo: bool = False) -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults for this project.

    Uses ``:memory:`` as-is for tests; otherwise ensures the parent
    directory exists before connecting.
    """
    if str(db_path) != ":memory:":
        _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if echo:
        conn.set_trace_callback(print)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables defined in ``schema.sql`` if they don't exist."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    conn.commit()


@contextmanager
def get_connection(db_path: str | Path, *, echo: bool = False) -> Iterator[sqlite3.Connection]:
    """Context manager yielding an initialized connection, closed on exit."""
    conn = connect(db_path, echo=echo)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()
