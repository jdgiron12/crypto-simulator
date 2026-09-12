"""Shared pytest fixtures for the Crypto Market Simulator test suite."""

from __future__ import annotations

import sqlite3

import pytest

from crypto_simulator.data.database import connect, init_db


@pytest.fixture()
def db_conn() -> sqlite3.Connection:
    """An initialized, isolated in-memory SQLite connection per test."""
    conn = connect(":memory:")
    init_db(conn)
    yield conn
    conn.close()
