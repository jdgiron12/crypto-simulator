"""Trader-agent abstraction: what a trader sees, decides, and holds.

A strategy only implements ``_decide(context)``. Everything shared —
the trade-probability gate, position sizing, wallet ownership, seeded RNG
— lives in ``TraderAgent`` so new strategies can't get it subtly wrong.
Traders never mutate balances themselves; they return a ``TradeDecision``
and ``execution.execute_decision`` settles it (clamping to what is
actually affordable/held).
"""

from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from crypto_simulator.core.psychology.state import PsychologyState
from crypto_simulator.models.wallet import Wallet

# The largest float below 1: psychology may make acting likelier, never certain.
_JUST_BELOW_ONE = math.nextafter(1.0, 0.0)


class TradeAction(str, Enum):
    """What a trader decides to do; fills (``TraderTrade.side``) are only
    ever BUY or SELL.

    WASH is a self-trade: buy ``quantity`` and immediately sell the same
    coins back, so the trader's position doesn't change but two trades are
    printed (see ``execute_wash`` / ``execute_wash_via_pool``).
    """

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    WASH = "wash"


@dataclass(frozen=True)
class TradeDecision:
    """A trader's intent for one tick; quantity is in coins."""

    action: TradeAction
    quantity: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        if self.quantity < 0:
            raise ValueError("TradeDecision.quantity must not be negative")

    @classmethod
    def hold(cls, reason: str = "") -> TradeDecision:
        return cls(TradeAction.HOLD, 0.0, reason)


@dataclass(frozen=True)
class MarketContext:
    """Read-only market information available to traders at one tick.

    ``price`` is the current tick's price after the base random walk and
    any whale trades, before trader flow. ``price_history`` holds prior
    ticks' closing prices, oldest first; its last element is the previous
    close (the coin's starting price on tick 1). It is a bounded window
    sized to the longest lookback any registered trader needs.

    ``sentiment`` (in [-1, 1]) and ``attention_multiplier`` (>= 1) are the
    public, aggregate news signal for this tick — how good or bad the news
    is and how much attention the market is paying. Traders never see which
    events are behind them. The defaults mean "no news".
    """

    tick: int
    price: float
    price_history: tuple[float, ...]
    total_supply: float
    sentiment: float = 0.0
    attention_multiplier: float = 1.0

    def return_over(self, lookback: int) -> float | None:
        """Fractional price change over ``lookback`` ticks, or ``None`` if
        there isn't that much history yet."""
        if lookback <= 0 or len(self.price_history) < lookback:
            return None
        return self.price / self.price_history[-lookback] - 1.0

    def recent_high(self, lookback: int) -> float:
        return max((*self.price_history[-lookback:], self.price))

    def recent_low(self, lookback: int) -> float:
        return min((*self.price_history[-lookback:], self.price))

    def drawdown_from_high(self, lookback: int) -> float:
        """How far (as a fraction) the price sits below the recent high."""
        return 1.0 - self.price / self.recent_high(lookback)

    def rise_from_low(self, lookback: int) -> float:
        """How far (as a fraction) the price sits above the recent low."""
        return self.price / self.recent_low(lookback) - 1.0


@dataclass(frozen=True)
class PsychologyContext(MarketContext):
    """A ``MarketContext`` that also carries this tick's market-wide
    ``PsychologyState``.

    ``CoinSimulator`` passes one only when built with ``psychology=True``;
    otherwise traders receive a plain ``MarketContext``, exactly as before.
    Each strategy decides for itself how (and whether) the psychology bends
    its rules — see ``TraderAgent.market_psychology``.
    """

    psychology: PsychologyState = PsychologyState()


class TraderAgent(ABC):
    """Base class for rule-based coin-economy traders.

    Common characteristics:
        starting_cash / starting_coins: initial ``Wallet`` balances.
        trade_probability: chance per tick the trader evaluates its
            strategy at all; otherwise it holds.
        max_trade_size: hard cap, in coins, on any single trade.
        risk_tolerance: fraction (0, 1] of the available balance — cash
            when buying, coins when selling — committed in one trade.
        sentiment_sensitivity: >= 0; how strongly public news sentiment
            bends the strategy's own parameters (0 = ignores sentiment).
            ``None`` uses the strategy's ``default_sentiment_sensitivity``.

    News reaches a trader two ways, both no-ops without news: attention
    raises its chance of acting at all (``participation_probability``), and
    ``sentiment_pressure`` — sensitivity × sentiment, clamped to [-1, 1] —
    is what a strategy uses to adjust its thresholds. Strategies define
    that adjustment themselves; without one, sentiment is ignored.

    Psychology (only with a ``PsychologyContext``) is a separate layer on
    top of the news: each emotion's pull on a trader is
    ``psychology_strength`` — the class's ``psychology_sensitivity`` ×
    emotion, capped at 1. A strategy may name one emotion that makes it
    likelier to act (``participation_emotion``) and may bend its own
    thresholds; it keeps deciding by its own rules. Both default to no
    effect, as does ``psychology_sensitivity`` 0.
    """

    strategy_name: ClassVar[str]
    default_sentiment_sensitivity: ClassVar[float] = 0.0
    psychology_sensitivity: ClassVar[float] = 0.0
    # False for scripted participants (manipulators): no news effect at all.
    responds_to_news: ClassVar[bool] = True

    def __init__(
        self,
        trader_id: str,
        *,
        starting_cash: float = 0.0,
        starting_coins: float = 0.0,
        trade_probability: float = 0.5,
        max_trade_size: float = 1_000.0,
        risk_tolerance: float = 0.5,
        sentiment_sensitivity: float | None = None,
        seed: int | None = None,
    ):
        if not trader_id:
            raise ValueError("trader_id must not be empty")
        if not 0.0 <= trade_probability <= 1.0:
            raise ValueError("trade_probability must be within [0, 1]")
        if max_trade_size <= 0:
            raise ValueError("max_trade_size must be positive")
        if not 0.0 < risk_tolerance <= 1.0:
            raise ValueError("risk_tolerance must be within (0, 1]")
        if sentiment_sensitivity is None:
            sentiment_sensitivity = self.default_sentiment_sensitivity
        if (
            isinstance(sentiment_sensitivity, bool)
            or not isinstance(sentiment_sensitivity, (int, float))
            or not math.isfinite(sentiment_sensitivity)
            or sentiment_sensitivity < 0
        ):
            raise ValueError(f"sentiment_sensitivity must be a finite number >= 0 (got {sentiment_sensitivity!r})")
        if sentiment_sensitivity and not self.responds_to_news:
            raise ValueError(f"{type(self).__name__} ignores news; sentiment_sensitivity must be 0")
        self.trader_id = trader_id
        self.wallet = Wallet(cash=starting_cash, coins=starting_coins)
        self.trade_probability = trade_probability
        self.max_trade_size = max_trade_size
        self.risk_tolerance = risk_tolerance
        self.sentiment_sensitivity = sentiment_sensitivity
        self._rng = random.Random(seed)

    @property
    def lookback(self) -> int:
        """Ticks of closing-price history this strategy needs."""
        return 0

    def participation_probability(self, context: MarketContext) -> float:
        """Chance of acting this tick, in two layers.

        News: ``trade_probability``, scaled up by the attention multiplier
        and capped at 1. Psychology, on top: with the trader's
        ``participation_urge`` u in [0, 1], that probability p becomes
        ``p × (1 + u × (1 - p))`` — at most ``1 - (1 - p)²``. So a trader
        that never acts still never does, and psychology alone never makes
        acting certain.
        """
        if not self.responds_to_news or context.attention_multiplier == 1.0:
            probability = self.trade_probability
        else:
            probability = min(1.0, self.trade_probability * context.attention_multiplier)
        urge = self.participation_urge(context)
        if urge == 0.0 or probability in (0.0, 1.0):
            return probability
        # The cap only guards float rounding when p is within ~1e-8 of 1.
        return min(probability * (1.0 + urge * (1.0 - probability)), _JUST_BELOW_ONE)

    def market_psychology(self, context: MarketContext) -> PsychologyState | None:
        """This tick's ``PsychologyState``, or ``None`` when there is none to
        react to: a plain ``MarketContext`` (psychology off), a trader that
        ignores news (manipulators), or ``psychology_sensitivity`` 0."""
        if not self.responds_to_news or self.psychology_sensitivity == 0:
            return None
        return context.psychology if isinstance(context, PsychologyContext) else None

    def psychology_strength(self, emotion: float) -> float:
        """How hard one emotion (in [0, 1]) pulls on this trader:
        ``psychology_sensitivity × emotion``, capped at 1."""
        return min(1.0, self.psychology_sensitivity * emotion)

    def participation_emotion(self, psychology: PsychologyState) -> float:
        """The emotion, in [0, 1], that makes this strategy likelier to act.
        None by default."""
        return 0.0

    def participation_urge(self, context: MarketContext) -> float:
        """``psychology_strength`` of the ``participation_emotion`` — 0.0
        without psychology."""
        psychology = self.market_psychology(context)
        if psychology is None:
            return 0.0
        return self.psychology_strength(self.participation_emotion(psychology))

    def sentiment_pressure(self, context: MarketContext) -> float:
        """``sentiment_sensitivity × sentiment``, clamped to [-1, 1].

        Exactly 0.0 when either factor is zero (or the trader ignores news),
        so strategies can skip every adjustment and behave as before.
        """
        if not self.responds_to_news or self.sentiment_sensitivity == 0 or context.sentiment == 0:
            return 0.0
        return max(-1.0, min(1.0, self.sentiment_sensitivity * context.sentiment))

    def decide(self, context: MarketContext) -> TradeDecision:
        # `>=` so probability 0 never acts and 1 always acts
        # (`random()` is in [0, 1)). Exactly one draw, whatever the news
        # or psychology.
        if self._rng.random() >= self.participation_probability(context):
            return TradeDecision.hold("inactive this tick")
        return self._decide(context)

    @abstractmethod
    def _decide(self, context: MarketContext) -> TradeDecision:
        """Strategy logic, called only on ticks the trader is active."""

    def _buy(self, price: float, reason: str) -> TradeDecision:
        quantity = min(self.max_trade_size, self.risk_tolerance * self.wallet.cash / price)
        if quantity <= 0:
            return TradeDecision.hold(f"{reason}; no cash")
        return TradeDecision(TradeAction.BUY, quantity, reason)

    def _sell(self, reason: str) -> TradeDecision:
        quantity = min(self.max_trade_size, self.risk_tolerance * self.wallet.coins)
        if quantity <= 0:
            return TradeDecision.hold(f"{reason}; no coins")
        return TradeDecision(TradeAction.SELL, quantity, reason)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.trader_id!r}, wallet={self.wallet})"
