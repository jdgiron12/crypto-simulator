"""Repositories: the only place SQL is written for a given model.

Each repository takes a live ``sqlite3.Connection`` and exposes
model-shaped CRUD methods. Repositories do not open/close connections
(that's ``database.py``'s job) and do not contain business rules (that's
``core``/``services``' job) — they translate between rows and dataclasses.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from crypto_simulator.models.account import Account, Holding
from crypto_simulator.models.asset import Asset
from crypto_simulator.models.order import Order, OrderSide, OrderStatus, OrderType
from crypto_simulator.models.trade import Trade


class AssetRepository:
    """CRUD access to the ``assets`` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, asset: Asset) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO assets (symbol, name, base_currency) VALUES (?, ?, ?)",
            (asset.symbol, asset.name, asset.base_currency),
        )
        self._conn.commit()

    def get(self, symbol: str) -> Asset | None:
        row = self._conn.execute(
            "SELECT symbol, name, base_currency FROM assets WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return Asset(**dict(row)) if row else None

    def list_all(self) -> list[Asset]:
        rows = self._conn.execute(
            "SELECT symbol, name, base_currency FROM assets ORDER BY symbol"
        ).fetchall()
        return [Asset(**dict(row)) for row in rows]


class AccountRepository:
    """CRUD access to the ``accounts`` and ``holdings`` tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, account: Account) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO accounts (id, cash_balance, base_currency) VALUES (?, ?, ?)",
            (account.id, account.cash_balance, account.base_currency),
        )
        self._conn.commit()

    def get(self, account_id: str) -> Account | None:
        row = self._conn.execute(
            "SELECT id, cash_balance, base_currency FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()
        if row is None:
            return None
        account = Account(
            id=row["id"],
            cash_balance=row["cash_balance"],
            base_currency=row["base_currency"],
        )
        for h_row in self._conn.execute(
            "SELECT symbol, quantity, average_cost FROM holdings WHERE account_id = ?",
            (account_id,),
        ).fetchall():
            account.holdings[h_row["symbol"]] = Holding(**dict(h_row))
        return account

    def upsert_holding(self, account_id: str, holding: Holding) -> None:
        self._conn.execute(
            """
            INSERT INTO holdings (account_id, symbol, quantity, average_cost)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id, symbol)
            DO UPDATE SET quantity = excluded.quantity, average_cost = excluded.average_cost
            """,
            (account_id, holding.symbol, holding.quantity, holding.average_cost),
        )
        self._conn.commit()


class OrderRepository:
    """CRUD access to the ``orders`` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, order: Order) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO orders
                (id, account_id, symbol, side, order_type, quantity, limit_price, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.id,
                order.account_id,
                order.symbol,
                order.side.value,
                order.order_type.value,
                order.quantity,
                order.limit_price,
                order.status.value,
                order.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get(self, order_id: str) -> Order | None:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return self._row_to_order(row) if row else None

    def list_for_account(self, account_id: str) -> list[Order]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE account_id = ? ORDER BY created_at DESC",
            (account_id,),
        ).fetchall()
        return [self._row_to_order(row) for row in rows]

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> Order:
        return Order(
            id=row["id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            side=OrderSide(row["side"]),
            order_type=OrderType(row["order_type"]),
            quantity=row["quantity"],
            limit_price=row["limit_price"],
            status=OrderStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class PriceHistoryRepository:
    """CRUD access to the ``price_history`` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add_bar(
        self,
        symbol: str,
        timestamp: datetime,
        *,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float = 0.0,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO price_history
                (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (symbol, timestamp.isoformat(), open, high, low, close, volume),
        )
        self._conn.commit()

    def list_for_symbol(self, symbol: str, *, limit: int | None = None) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            """
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM price_history WHERE symbol = ? ORDER BY timestamp ASC
            """,
            (symbol,),
        ).fetchall()
        return rows[-limit:] if limit is not None else rows


class TradeRepository:
    """CRUD access to the ``trades`` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, trade: Trade) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO trades
                (id, order_id, account_id, symbol, side, quantity, price, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.id,
                trade.order_id,
                trade.account_id,
                trade.symbol,
                trade.side.value,
                trade.quantity,
                trade.price,
                trade.executed_at.isoformat(),
            ),
        )
        self._conn.commit()

    def list_for_account(self, account_id: str) -> list[Trade]:
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE account_id = ? ORDER BY executed_at DESC",
            (account_id,),
        ).fetchall()
        return [
            Trade(
                id=row["id"],
                order_id=row["order_id"],
                account_id=row["account_id"],
                symbol=row["symbol"],
                side=OrderSide(row["side"]),
                quantity=row["quantity"],
                price=row["price"],
                executed_at=datetime.fromisoformat(row["executed_at"]),
            )
            for row in rows
        ]
