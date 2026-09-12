"""``PortfolioCalculator``: balance and valuation math for an ``Account``.

Pure functions/methods over ``Account`` + current prices — no persistence,
no order matching. Keeping this separate from ``OrderEngine`` means fee
schedules, valuation methods (mark-to-market vs. average cost), and P&L
reporting can evolve independently of matching logic.

Scaffolding stage: interface only, minimal math implemented.
"""

from __future__ import annotations

from crypto_simulator.models.account import Account


class PortfolioCalculator:
    """Computes derived values (equity, P&L) for a simulated account."""

    @staticmethod
    def cash_value(account: Account) -> float:
        """Return the account's uninvested cash balance."""
        return account.cash_balance

    @staticmethod
    def holdings_value(account: Account, current_prices: dict[str, float]) -> float:
        """Mark-to-market value of all held positions at ``current_prices``.

        Raises ``KeyError`` if a held symbol has no price supplied — callers
        are expected to pass a complete price snapshot from ``MarketEngine``.
        """
        return sum(
            holding.quantity * current_prices[symbol]
            for symbol, holding in account.holdings.items()
            if holding.quantity != 0
        )

    @classmethod
    def total_equity(cls, account: Account, current_prices: dict[str, float]) -> float:
        """Total simulated net worth: cash + mark-to-market holdings."""
        return cls.cash_value(account) + cls.holdings_value(account, current_prices)

    @staticmethod
    def unrealized_pnl(account: Account, current_prices: dict[str, float]) -> dict[str, float]:
        """Per-symbol unrealized P&L vs. average cost basis.

        Not yet implemented beyond the basic formula below — realized P&L,
        fees, and cost-basis methods (FIFO/LIFO/average) are TODO
        (see roadmap).
        """
        return {
            symbol: holding.quantity * (current_prices[symbol] - holding.average_cost)
            for symbol, holding in account.holdings.items()
            if holding.quantity != 0
        }
