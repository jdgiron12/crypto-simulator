"""``Wallet``: cash + coin balances for one coin-economy participant.

Every mutation goes through a guarded method that refuses to take a
balance below zero, so an accounting bug elsewhere surfaces as an
exception instead of a silently negative balance.
"""

from __future__ import annotations

from dataclasses import dataclass


class InsufficientBalanceError(ValueError):
    """Raised when a withdrawal exceeds the available balance."""


def _require_non_negative(name: str, amount: float) -> None:
    if amount < 0:
        raise ValueError(f"{name} must not be negative (got {amount})")


@dataclass
class Wallet:
    """Cash and coin balances, plus the average cost of held coins.

    ``average_cost`` uses the average-cost method: buys blend into it,
    sells leave it unchanged, and it resets to 0 once holdings hit 0.
    """

    cash: float = 0.0
    coins: float = 0.0
    average_cost: float = 0.0

    def __post_init__(self) -> None:
        _require_non_negative("cash", self.cash)
        _require_non_negative("coins", self.coins)
        _require_non_negative("average_cost", self.average_cost)

    def withdraw_cash(self, amount: float) -> None:
        _require_non_negative("amount", amount)
        if amount > self.cash:
            raise InsufficientBalanceError(
                f"Cannot withdraw {amount} cash; only {self.cash} available"
            )
        self.cash -= amount

    def deposit_cash(self, amount: float) -> None:
        _require_non_negative("amount", amount)
        self.cash += amount

    def withdraw_coins(self, quantity: float) -> None:
        _require_non_negative("quantity", quantity)
        if quantity > self.coins:
            raise InsufficientBalanceError(
                f"Cannot withdraw {quantity} coins; only {self.coins} held"
            )
        self.coins -= quantity
        if self.coins == 0:
            self.average_cost = 0.0

    def deposit_coins(self, quantity: float, *, cost: float | None = None) -> None:
        """Add coins; when ``cost`` is given, blend it into ``average_cost``."""
        _require_non_negative("quantity", quantity)
        if cost is None:
            self.coins += quantity
            return
        _require_non_negative("cost", cost)
        total_cost = self.coins * self.average_cost + cost
        self.coins += quantity
        if self.coins > 0:
            self.average_cost = total_cost / self.coins

    def equity(self, price: float) -> float:
        """Cash plus coins marked to ``price``."""
        return self.cash + self.coins * price
