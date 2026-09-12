"""``TradingService``: orchestrates order submission end-to-end.

Combines ``OrderEngine`` (matching) with ``OrderRepository`` /
``TradeRepository`` (persistence). The UI layer calls this rather than
touching the engine or repositories directly.
"""

from __future__ import annotations

import sqlite3

from crypto_simulator.core.order_engine import OrderEngine
from crypto_simulator.data.repositories import OrderRepository, TradeRepository
from crypto_simulator.models.order import Order
from crypto_simulator.models.trade import Trade


class TradingService:
    def __init__(self, conn: sqlite3.Connection, order_engine: OrderEngine):
        self._orders = OrderRepository(conn)
        self._trades = TradeRepository(conn)
        self._order_engine = order_engine

    def place_order(self, order: Order) -> Trade:
        """Persist ``order``, attempt to fill it, and persist the resulting trade.

        Not yet implemented — depends on ``OrderEngine.submit``.
        """
        self._orders.add(order)
        trade = self._order_engine.submit(order)
        self._trades.add(trade)
        return trade

    def order_history(self, account_id: str) -> list[Order]:
        return self._orders.list_for_account(account_id)

    def trade_history(self, account_id: str) -> list[Trade]:
        return self._trades.list_for_account(account_id)
