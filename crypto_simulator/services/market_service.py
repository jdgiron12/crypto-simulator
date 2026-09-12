"""``MarketService``: orchestrates the market engine with persistence.

The UI layer calls this, never ``core.MarketEngine`` or
``data.repositories`` directly.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from crypto_simulator.core.market_engine import MarketEngine
from crypto_simulator.data.repositories import AssetRepository, PriceHistoryRepository
from crypto_simulator.models.asset import Asset

PRICE_HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class MarketService:
    def __init__(self, conn: sqlite3.Connection, market_engine: MarketEngine):
        self._assets = AssetRepository(conn)
        self._price_history = PriceHistoryRepository(conn)
        self._market_engine = market_engine
        self._ensure_assets_seeded()

    def _ensure_assets_seeded(self) -> None:
        """Make sure every engine symbol has an ``assets`` row.

        ``price_history.symbol`` is a foreign key into ``assets``, so a
        tick can't be persisted for a symbol the table doesn't know about
        yet.
        """
        for symbol in self._market_engine.symbols:
            if self._assets.get(symbol) is None:
                self._assets.add(Asset(symbol=symbol, name=f"{symbol} (Simulated)"))

    def list_assets(self):
        return self._assets.list_all()

    def current_prices(self) -> dict[str, float]:
        """Return current simulated prices for every configured asset."""
        return {symbol: self._market_engine.current_price(symbol) for symbol in self._market_engine.symbols}

    def step(self) -> dict[str, float]:
        """Advance the market by one tick and persist the resulting prices.

        Each tick is stored as a degenerate OHLC bar (open == high == low
        == close == the tick price) — Phase 1 doesn't aggregate ticks into
        larger candles yet (see docs/ROADMAP.md).
        """
        new_prices = self._market_engine.step()
        timestamp = self._market_engine.clock.simulated_time
        for symbol, price in new_prices.items():
            self._price_history.add_bar(
                symbol, timestamp, open=price, high=price, low=price, close=price
            )
        return new_prices

    def price_history_df(self, symbol: str, *, limit: int | None = None) -> pd.DataFrame:
        """Return persisted OHLCV history for ``symbol`` as a DataFrame."""
        rows = self._price_history.list_for_symbol(symbol, limit=limit)
        df = pd.DataFrame([dict(row) for row in rows], columns=PRICE_HISTORY_COLUMNS)
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df
