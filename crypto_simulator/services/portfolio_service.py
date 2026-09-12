"""``PortfolioService``: orchestrates account state + valuation for the UI."""

from __future__ import annotations

import sqlite3

from crypto_simulator.core.portfolio import PortfolioCalculator
from crypto_simulator.data.repositories import AccountRepository
from crypto_simulator.models.account import Account


class PortfolioService:
    def __init__(self, conn: sqlite3.Connection):
        self._accounts = AccountRepository(conn)

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)

    def open_account(self, account: Account) -> None:
        self._accounts.add(account)

    def total_equity(self, account_id: str, current_prices: dict[str, float]) -> float:
        account = self._accounts.get(account_id)
        if account is None:
            raise ValueError(f"No account with id {account_id!r}")
        return PortfolioCalculator.total_equity(account, current_prices)
