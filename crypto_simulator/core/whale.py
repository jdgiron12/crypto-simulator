"""``Whale``: a large coin holder capable of moving price with one trade.

Phase 1's ``CoinSimulator`` drives price purely through ``MarketEngine``'s
random walk — nothing represents an actor whose trade size, relative to
total supply, is large enough to move price on its own. This adds exactly
that: on ticks it decides to act, a whale buys or sells a random fraction
of total supply and the resulting trade size determines a multiplicative
price-impact factor.

Deliberately minimal: no order book, no liquidity-depth curve — a plain
linear impact model (``impact = 1 + impact_coefficient * fraction_of_supply``).

Two kinds of whale (Phase 8, Step 1):

- **Unfunded** (the default, and the original behavior): holds coins only
  and trades against assumed external liquidity. Its buys are uncapped
  and its sells are capped at its holdings; it is outside the simulator's
  conserved accounting.
- **Funded** (``starting_cash`` given): holds a ``Wallet`` of cash and coins
  and settles every trade against the market reserve with the same
  clamp-and-transfer code traders use (``settle_against_reserve``), so it
  never creates or destroys coins or cash.

A funded whale also has a persistent ``WhaleBehavior``:

- ``NEUTRAL``: buys or sells at random when active, as unfunded whales do.
- ``ACCUMULATE``: buys when active; ``DISTRIBUTE``: sells when active.
  With a ``target_coin_fraction`` (the share of its portfolio value, marked
  at the trade price, it wants in coins), it accumulates only while below
  the target and distributes only while above it, and a trade is sized so
  it doesn't cross the target. It never rebalances in the other direction.

These are ordinary portfolio-management intents, not manipulation (that is
``core/traders/manipulation.py``), and whales read no news or psychology.

Randomness: one private ``random.Random(seed)`` stream per whale. Each
eligible tick draws the activity check, and on active ticks a side and a
size, in that order, whatever the behavior — the behavior decides the
direction, never the draws. After a trade that moved coins, a
``cooldown_ticks`` counter keeps the whale out for that many ticks, during
which it draws nothing. With the defaults (``cooldown_ticks`` 0,
``min_trade_fraction`` 0, unfunded) every draw and trade is exactly what
it was before.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum

from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import settle_against_reserve
from crypto_simulator.models.wallet import Wallet


class WhaleBehavior(str, Enum):
    NEUTRAL = "neutral"
    ACCUMULATE = "accumulate"
    DISTRIBUTE = "distribute"


@dataclass(frozen=True)
class WhaleTrade:
    """One whale's trade for a single tick."""

    whale_id: str
    side: str
    quantity: float
    price_impact: float


@dataclass(frozen=True)
class WhaleState:
    """A snapshot of a whale's persistent state. ``cash`` is ``None`` for an
    unfunded whale; ``cooldown_remaining`` is the number of upcoming ticks
    it will sit out."""

    whale_id: str
    behavior: WhaleBehavior
    funded: bool
    cash: float | None
    coins: float
    target_coin_fraction: float | None
    cooldown_remaining: int


def _require_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")


def _require_fraction(name: str, value: object) -> None:
    _require_number(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1] (got {value!r})")


class Whale:
    """A large holder that occasionally trades a chunk of total supply."""

    def __init__(
        self,
        whale_id: str,
        holdings: float,
        *,
        activity_probability: float = 0.1,
        max_trade_fraction: float = 0.05,
        impact_coefficient: float = 2.0,
        seed: int | None = None,
        starting_cash: float | None = None,
        behavior: WhaleBehavior | str = WhaleBehavior.NEUTRAL,
        target_coin_fraction: float | None = None,
        min_trade_fraction: float = 0.0,
        cooldown_ticks: int = 0,
    ):
        if not whale_id:
            raise ValueError("whale_id must not be empty")
        _require_number("holdings", holdings)
        if holdings < 0:
            raise ValueError("holdings must not be negative")
        _require_fraction("activity_probability", activity_probability)
        _require_number("max_trade_fraction", max_trade_fraction)
        if not 0.0 < max_trade_fraction <= 1.0:
            raise ValueError("max_trade_fraction must be within (0, 1]")
        _require_number("impact_coefficient", impact_coefficient)
        if impact_coefficient < 0:
            raise ValueError(f"impact_coefficient must not be negative (got {impact_coefficient!r})")
        _require_fraction("min_trade_fraction", min_trade_fraction)
        if min_trade_fraction > max_trade_fraction:
            raise ValueError(
                f"min_trade_fraction ({min_trade_fraction}) must not exceed max_trade_fraction ({max_trade_fraction})"
            )
        if isinstance(cooldown_ticks, bool) or not isinstance(cooldown_ticks, int) or cooldown_ticks < 0:
            raise ValueError(f"cooldown_ticks must be an integer >= 0 (got {cooldown_ticks!r})")
        try:
            behavior = WhaleBehavior(behavior)
        except ValueError:
            raise ValueError(
                f"Unknown whale behavior {behavior!r}; expected one of {[b.value for b in WhaleBehavior]}"
            ) from None
        if starting_cash is not None:
            _require_number("starting_cash", starting_cash)
            if starting_cash < 0:
                raise ValueError(f"starting_cash must not be negative (got {starting_cash!r})")
        elif behavior is not WhaleBehavior.NEUTRAL:
            raise ValueError(
                f"A {behavior.value} whale needs starting_cash: an unfunded whale trades against "
                "unlimited external liquidity, so it could accumulate coins that don't exist"
            )
        if target_coin_fraction is not None:
            _require_fraction("target_coin_fraction", target_coin_fraction)
            if behavior is WhaleBehavior.NEUTRAL:
                raise ValueError("target_coin_fraction applies only to accumulate or distribute whales")

        self.whale_id = whale_id
        self.activity_probability = activity_probability
        self.max_trade_fraction = max_trade_fraction
        self.min_trade_fraction = min_trade_fraction
        self.impact_coefficient = impact_coefficient
        self.behavior = behavior
        self.target_coin_fraction = target_coin_fraction
        self.cooldown_ticks = cooldown_ticks
        self._cooldown_remaining = 0
        # The wallet is the authoritative balance of a funded whale; an
        # unfunded whale keeps only a coin count.
        self.wallet: Wallet | None = None if starting_cash is None else Wallet(cash=starting_cash, coins=holdings)
        self._holdings = holdings
        self._rng = random.Random(seed)

    @property
    def funded(self) -> bool:
        return self.wallet is not None

    @property
    def holdings(self) -> float:
        """Coins currently held."""
        return self.wallet.coins if self.wallet is not None else self._holdings

    def state(self) -> WhaleState:
        return WhaleState(
            whale_id=self.whale_id,
            behavior=self.behavior,
            funded=self.funded,
            cash=self.wallet.cash if self.wallet is not None else None,
            coins=self.holdings,
            target_coin_fraction=self.target_coin_fraction,
            cooldown_remaining=self._cooldown_remaining,
        )

    def maybe_trade(
        self, total_supply: float, *, price: float | None = None, reserve: Wallet | None = None
    ) -> WhaleTrade | None:
        """With probability ``activity_probability``, execute one trade.

        Returns ``None`` on ticks the whale sits out (cooling down, inactive,
        or — for a funded whale — nothing to do or nothing fillable). An
        unfunded whale's sells are capped at its holdings and its buys are
        not (external liquidity is assumed). A funded whale needs the tick's
        ``price`` and the market ``reserve`` to settle against. A sell's
        price impact divides price by the impact factor; a buy's
        multiplies by it.
        """
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return None
        if self._rng.random() > self.activity_probability:
            return None

        side = self._rng.choice(("buy", "sell"))
        trade_fraction = self._rng.uniform(self.min_trade_fraction, self.max_trade_fraction)
        requested_quantity = trade_fraction * total_supply

        if self.wallet is None:
            if side == "sell":
                quantity = min(self._holdings, requested_quantity)
                self._holdings -= quantity
            else:
                quantity = requested_quantity
                self._holdings += quantity
        else:
            if price is None or reserve is None:
                raise ValueError("a funded whale needs the tick's price and the market reserve to trade")
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"price must be a positive finite number (got {price!r})")
            fill = self._funded_trade(side, requested_quantity, price, reserve)
            if fill is None:
                return None
            side, quantity = fill

        fraction_of_supply = quantity / total_supply if total_supply else 0.0
        impact = 1.0 + self.impact_coefficient * fraction_of_supply
        price_impact = impact if side == "buy" else 1.0 / impact
        if quantity > 0:
            self._cooldown_remaining = self.cooldown_ticks

        return WhaleTrade(
            whale_id=self.whale_id,
            side=side,
            quantity=quantity,
            price_impact=price_impact,
        )

    def _funded_trade(
        self, drawn_side: str, requested: float, price: float, reserve: Wallet
    ) -> tuple[str, float] | None:
        """Direction from the behavior (the drawn side only for NEUTRAL),
        size capped so a target isn't crossed, then settled against the
        reserve. ``None`` when there is nothing to do or nothing fills."""
        if self.behavior is WhaleBehavior.NEUTRAL:
            side = drawn_side
        else:
            side = "buy" if self.behavior is WhaleBehavior.ACCUMULATE else "sell"
        if self.target_coin_fraction is not None:
            wallet = self.wallet
            target_coins = self.target_coin_fraction * (wallet.cash + wallet.coins * price) / price
            room = target_coins - wallet.coins if side == "buy" else wallet.coins - target_coins
            if room <= 0:
                return None
            requested = min(requested, room)
        action = TradeAction.BUY if side == "buy" else TradeAction.SELL
        fill = settle_against_reserve(self.wallet, action, requested, price, reserve)
        if fill is None:
            return None
        return side, fill[0]
