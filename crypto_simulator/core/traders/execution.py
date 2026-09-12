"""Settling trader decisions against the market reserve.

``execute_decision`` is the only code that moves trader balances. Every
fill is a two-sided transfer between the trader's ``Wallet`` and the
reserve ``Wallet`` using the *same* amounts, so total coins and total cash
across traders + reserve never change — nothing is created or destroyed.

Fills are clamped to what both sides can actually cover. When a clamp is
"everything the payer has", the exact balance is transferred rather than
``quantity * price``, so float rounding can't push a balance below zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crypto_simulator.core.traders.base import TradeAction, TradeDecision, TraderAgent
from crypto_simulator.models.wallet import Wallet

if TYPE_CHECKING:
    from crypto_simulator.core.liquidity.pool import SwapResult


@dataclass(frozen=True)
class TraderTrade:
    """One trader fill for a single tick.

    ``price`` is the fill price (random-walk mode) or the realized
    execution price including fees (AMM mode, where ``swap`` carries the
    full ``SwapResult``: fee, slippage, spot before/after).
    """

    trader_id: str
    strategy: str
    side: TradeAction
    requested_quantity: float
    quantity: float
    price: float
    notional: float
    reason: str = ""
    swap: SwapResult | None = None


def execute_decision(
    trader: TraderAgent, decision: TradeDecision, price: float, reserve: Wallet
) -> TraderTrade | None:
    """Fill ``decision`` at ``price`` against ``reserve``.

    Returns ``None`` for holds and for trades that clamp to nothing
    (no cash, no coins, or an exhausted reserve).
    """
    if price <= 0:
        raise ValueError("price must be positive")
    if decision.action is TradeAction.HOLD or decision.quantity <= 0:
        return None

    wallet = trader.wallet
    if decision.action is TradeAction.BUY:
        affordable = wallet.cash / price
        quantity = min(decision.quantity, affordable, reserve.coins)
        if quantity <= 0:
            return None
        cash_amount = wallet.cash if quantity == affordable else min(quantity * price, wallet.cash)
        wallet.withdraw_cash(cash_amount)
        reserve.deposit_cash(cash_amount)
        reserve.withdraw_coins(quantity)
        wallet.deposit_coins(quantity, cost=cash_amount)
    else:
        payable = reserve.cash / price
        quantity = min(decision.quantity, wallet.coins, payable)
        if quantity <= 0:
            return None
        cash_amount = reserve.cash if quantity == payable else min(quantity * price, reserve.cash)
        wallet.withdraw_coins(quantity)
        reserve.deposit_coins(quantity)
        reserve.withdraw_cash(cash_amount)
        wallet.deposit_cash(cash_amount)

    return TraderTrade(
        trader_id=trader.trader_id,
        strategy=trader.strategy_name,
        side=decision.action,
        requested_quantity=decision.quantity,
        quantity=quantity,
        price=price,
        notional=cash_amount,
        reason=decision.reason,
    )


def net_flow_price_impact(net_quantity: float, total_supply: float, coefficient: float) -> float:
    """Multiplicative price factor for a tick's net trader flow.

    Same linear shape as a whale trade's impact: net buying multiplies
    price by ``1 + coefficient * |net| / supply``; net selling divides by
    it. Balanced flow leaves price unchanged.
    """
    if net_quantity == 0 or total_supply <= 0:
        return 1.0
    factor = 1.0 + coefficient * abs(net_quantity) / total_supply
    return factor if net_quantity > 0 else 1.0 / factor
