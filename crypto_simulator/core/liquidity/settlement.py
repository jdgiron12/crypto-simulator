"""Moving float ``Wallet`` balances into and out of an ``AMMPool``.

The pool keeps exact ``Decimal`` accounting; wallets hold floats (the
random-walk mode and every trader strategy depend on that). At the
boundary:

- Debits: the wallet's float balance changes by ``before - amount``
  (rounded), and the pool is credited with the *exact* change
  ``Decimal(before) - Decimal(after)`` — never the nominal amount.
- Credits: the wallet receives the largest float amount whose exact effect
  on its balance does not exceed the pool's output; the pool pays out
  exactly that effect and keeps the sub-ulp remainder.

So ``sum(Decimal(wallet balances)) + pool reserves`` (fees live in the
reserves) is conserved exactly, and the pool never pays more than its
formula allows.
Anything that would round to nothing is rejected before a balance moves.
"""

from __future__ import annotations

import math
from decimal import Decimal

from crypto_simulator.core.liquidity.amounts import EXACT, ZERO, float_at_most, to_amount
from crypto_simulator.core.liquidity.pool import AMMError, AMMPool
from crypto_simulator.core.traders.base import TradeAction, TradeDecision, TraderAgent
from crypto_simulator.core.traders.execution import TraderTrade
from crypto_simulator.models.wallet import Wallet

_MAX_CREDIT_ADJUSTMENTS = 64


def planned_debit(balance: float, amount: float) -> tuple[float, Decimal]:
    """Balance after withdrawing ``amount`` and the exact amount removed."""
    after = balance - amount
    return after, EXACT.subtract(Decimal(balance), Decimal(after))


def planned_credit(balance: float, limit: Decimal) -> tuple[float, Decimal]:
    """Float deposit ``g`` and the exact increase it causes, with the
    increase guaranteed to be <= ``limit`` (``(0.0, 0)`` if nothing fits)."""
    if limit <= 0:
        return 0.0, ZERO
    exact_balance = Decimal(balance)
    target = float_at_most(EXACT.add(exact_balance, limit))
    deposit = target - balance
    for _ in range(_MAX_CREDIT_ADJUSTMENTS):
        if deposit <= 0:
            return 0.0, ZERO
        increase = EXACT.subtract(Decimal(balance + deposit), exact_balance)
        if increase <= limit:
            return (deposit, increase) if increase > 0 else (0.0, ZERO)
        deposit = math.nextafter(deposit, 0.0)
    return 0.0, ZERO


def seed_pool_from_wallet(
    wallet: Wallet,
    *,
    coins: float,
    cash: float,
    fee_rate: Decimal | float | str,
    provider_id: str,
) -> AMMPool:
    """Create a pool funded from ``wallet``; ``provider_id`` gets all shares."""
    if coins <= 0 or cash <= 0:
        raise ValueError("initial pool coins and cash must be positive")
    if coins > wallet.coins:
        raise ValueError(f"Cannot seed pool with {coins} coins; wallet holds {wallet.coins}")
    if cash > wallet.cash:
        raise ValueError(f"Cannot seed pool with {cash} cash; wallet holds {wallet.cash}")
    coins_after, coins_moved = planned_debit(wallet.coins, coins)
    cash_after, cash_moved = planned_debit(wallet.cash, cash)
    pool = AMMPool(coins_moved, cash_moved, fee_rate=fee_rate, initial_provider=provider_id)
    wallet.withdraw_coins(coins)
    wallet.withdraw_cash(cash)
    assert (wallet.coins, wallet.cash) == (coins_after, cash_after)
    return pool


def execute_decision_via_pool(
    trader: TraderAgent,
    decision: TradeDecision,
    pool: AMMPool,
    *,
    reference_price: float | None = None,
) -> TraderTrade | None:
    """Settle a trader's decision as a pool swap; ``None`` if nothing trades.

    BUY: an exact-input swap of ``decision.quantity * reference_price``
    cash (the budget the strategy sized its order at), capped at the
    trader's cash — slippage means fewer coins, never more cash spent.
    SELL: swaps ``min(decision.quantity, coins held)``.
    """
    if decision.action is TradeAction.HOLD or decision.quantity <= 0:
        return None
    if decision.action is TradeAction.BUY:
        return _buy(trader, decision, pool, reference_price)
    return _sell(trader, decision, pool)


def _buy(trader, decision, pool, reference_price) -> TraderTrade | None:
    wallet = trader.wallet
    price = to_amount(reference_price) if reference_price is not None else pool.spot_price()
    budget = min(wallet.cash, float_at_most(EXACT.multiply(to_amount(decision.quantity), price)))
    if budget <= 0:
        return None
    cash_after, paid = planned_debit(wallet.cash, budget)
    if paid <= 0:
        return None
    try:
        quote = pool.quote_buy(paid)
    except AMMError:
        return None
    coin_deposit, received = planned_credit(wallet.coins, quote.amount_out)
    if received <= 0:
        return None

    result = pool.buy(paid, coins_out=received)
    wallet.withdraw_cash(budget)
    wallet.deposit_coins(coin_deposit, cost=budget)
    assert wallet.cash == cash_after
    return _trade(trader, decision, result, coins=received, cash=paid)


def _sell(trader, decision, pool) -> TraderTrade | None:
    wallet = trader.wallet
    quantity = min(decision.quantity, wallet.coins)
    if quantity <= 0:
        return None
    coins_after, sent = planned_debit(wallet.coins, quantity)
    if sent <= 0:
        return None
    try:
        quote = pool.quote_sell(sent)
    except AMMError:
        return None
    cash_deposit, received = planned_credit(wallet.cash, quote.amount_out)
    if received <= 0:
        return None

    result = pool.sell(sent, cash_out=received)
    wallet.withdraw_coins(quantity)
    wallet.deposit_cash(cash_deposit)
    assert wallet.coins == coins_after
    return _trade(trader, decision, result, coins=sent, cash=received)


def _trade(trader, decision, result, *, coins: Decimal, cash: Decimal) -> TraderTrade:
    return TraderTrade(
        trader_id=trader.trader_id,
        strategy=trader.strategy_name,
        side=decision.action,
        requested_quantity=decision.quantity,
        quantity=float(coins),
        price=float(result.execution_price),
        notional=float(cash),
        reason=decision.reason,
        swap=result,
    )
