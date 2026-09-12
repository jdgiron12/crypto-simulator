"""The initial rule-based trader strategies.

Each class only encodes *when* to buy or sell; sizing, the activity gate,
and balance enforcement are inherited from ``TraderAgent`` or handled at
execution. Thresholds are fractions (0.05 = 5%).

News: a strategy that reacts to public sentiment does so in one small
``effective_*`` method that bends its *own* parameters by the trader's
``sentiment_pressure`` p in [-1, 1] (returning them unchanged when p is 0).
Moves toward a bound are proportional to the room left, so every
parameter stays valid. The class-level ``default_sentiment_sensitivity``
sets how strongly each strategy reacts; these reactions are modelling
assumptions, meant to be calibrated.
"""

from __future__ import annotations

from crypto_simulator.core.traders.base import MarketContext, TradeDecision, TraderAgent


def _require_fraction(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be within [0, 1]")


def _require_lookback(lookback: int) -> None:
    if lookback < 1:
        raise ValueError("lookback must be at least 1")


class RetailTrader(TraderAgent):
    """Noise trader: when active, buys or sells at random.

    ``buy_bias`` is the probability an active tick is a buy (0.5 = no
    directional preference).
    """

    strategy_name = "retail"
    default_sentiment_sensitivity = 1.0

    def __init__(self, trader_id: str, *, buy_bias: float = 0.5, **kwargs):
        super().__init__(trader_id, **kwargs)
        _require_fraction("buy_bias", buy_bias)
        self.buy_bias = buy_bias

    def effective_buy_bias(self, context: MarketContext) -> float:
        """Good news moves ``buy_bias`` toward 1, bad news toward 0."""
        pressure = self.sentiment_pressure(context)
        if pressure > 0:
            return self.buy_bias + (1.0 - self.buy_bias) * pressure
        if pressure < 0:
            return self.buy_bias * (1.0 + pressure)
        return self.buy_bias

    def _decide(self, context: MarketContext) -> TradeDecision:
        if self._rng.random() < self.effective_buy_bias(context):
            return self._buy(context.price, "retail impulse buy")
        return self._sell("retail impulse sell")


class MomentumTrader(TraderAgent):
    """Trend follower: buys after a rise, sells after a fall.

    Compares the current price with the close ``lookback`` ticks ago; buys
    when the return is at least ``entry_threshold``, sells when it is at
    most ``-exit_threshold``. Holds until enough history exists.
    """

    strategy_name = "momentum"
    default_sentiment_sensitivity = 0.8

    def __init__(
        self,
        trader_id: str,
        *,
        lookback: int = 5,
        entry_threshold: float = 0.02,
        exit_threshold: float = 0.02,
        **kwargs,
    ):
        super().__init__(trader_id, **kwargs)
        _require_lookback(lookback)
        _require_fraction("entry_threshold", entry_threshold)
        _require_fraction("exit_threshold", exit_threshold)
        self._lookback = lookback
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold

    @property
    def lookback(self) -> int:
        return self._lookback

    def effective_thresholds(self, context: MarketContext) -> tuple[float, float]:
        """``(entry, exit)``: news reads as trend confirmation — good news
        lowers the entry threshold, bad news lowers the exit threshold."""
        pressure = self.sentiment_pressure(context)
        if pressure > 0:
            return self.entry_threshold * (1.0 - pressure), self.exit_threshold
        if pressure < 0:
            return self.entry_threshold, self.exit_threshold * (1.0 + pressure)
        return self.entry_threshold, self.exit_threshold

    def _decide(self, context: MarketContext) -> TradeDecision:
        change = context.return_over(self._lookback)
        if change is None:
            return TradeDecision.hold("not enough history")
        entry_threshold, exit_threshold = self.effective_thresholds(context)
        if change >= entry_threshold:
            return self._buy(context.price, f"uptrend {change:+.2%}")
        if change <= -exit_threshold:
            return self._sell(f"downtrend {change:+.2%}")
        return TradeDecision.hold("no clear trend")


class DipBuyer(TraderAgent):
    """Buys when price has fallen ``dip_threshold`` below its recent high;
    takes profit once price is ``take_profit`` above its average cost.

    A dip takes priority over taking profit.

    Deliberately no sentiment reaction yet: whether bad news makes a dip a
    bargain or a falling knife is an open calibration question. (Attention
    still raises its participation, like every trader's.)
    """

    strategy_name = "dip_buyer"

    def __init__(
        self,
        trader_id: str,
        *,
        lookback: int = 10,
        dip_threshold: float = 0.05,
        take_profit: float = 0.10,
        **kwargs,
    ):
        super().__init__(trader_id, **kwargs)
        _require_lookback(lookback)
        _require_fraction("dip_threshold", dip_threshold)
        if take_profit <= 0:
            raise ValueError("take_profit must be positive")
        self._lookback = lookback
        self.dip_threshold = dip_threshold
        self.take_profit = take_profit

    @property
    def lookback(self) -> int:
        return self._lookback

    def _decide(self, context: MarketContext) -> TradeDecision:
        drawdown = context.drawdown_from_high(self._lookback)
        if drawdown >= self.dip_threshold:
            return self._buy(context.price, f"dip {drawdown:.2%} below recent high")
        cost = self.wallet.average_cost
        if self.wallet.coins > 0 and cost > 0 and context.price >= cost * (1 + self.take_profit):
            return self._sell(f"take profit at {context.price / cost - 1:+.2%} vs cost")
        return TradeDecision.hold("no dip")


class PanicSeller(TraderAgent):
    """Sells when price drops ``panic_threshold`` below its recent high;
    buys back in (FOMO) once price rises ``reentry_threshold`` above its
    recent low. Panic takes priority.
    """

    strategy_name = "panic_seller"
    default_sentiment_sensitivity = 1.0

    def __init__(
        self,
        trader_id: str,
        *,
        lookback: int = 5,
        panic_threshold: float = 0.08,
        reentry_threshold: float = 0.06,
        **kwargs,
    ):
        super().__init__(trader_id, **kwargs)
        _require_lookback(lookback)
        _require_fraction("panic_threshold", panic_threshold)
        if reentry_threshold <= 0:
            raise ValueError("reentry_threshold must be positive")
        self._lookback = lookback
        self.panic_threshold = panic_threshold
        self.reentry_threshold = reentry_threshold

    @property
    def lookback(self) -> int:
        return self._lookback

    def effective_thresholds(self, context: MarketContext) -> tuple[float, float]:
        """``(panic, reentry)``: bad news lowers the panic threshold, good
        news lowers the FOMO re-entry threshold."""
        pressure = self.sentiment_pressure(context)
        if pressure < 0:
            return self.panic_threshold * (1.0 + pressure), self.reentry_threshold
        if pressure > 0:
            return self.panic_threshold, self.reentry_threshold * (1.0 - pressure)
        return self.panic_threshold, self.reentry_threshold

    def _decide(self, context: MarketContext) -> TradeDecision:
        panic_threshold, reentry_threshold = self.effective_thresholds(context)
        drawdown = context.drawdown_from_high(self._lookback)
        if drawdown >= panic_threshold:
            return self._sell(f"panic: {drawdown:.2%} below recent high")
        rise = context.rise_from_low(self._lookback)
        if rise >= reentry_threshold:
            return self._buy(context.price, f"FOMO: {rise:+.2%} above recent low")
        return TradeDecision.hold("calm")


class LongTermHolder(TraderAgent):
    """Accumulates steadily and rarely sells.

    When active: sells only if price reaches ``take_profit_multiple`` times
    its average cost; otherwise buys, as long as price is no more than
    ``max_buy_premium`` above its average cost (or it has no cost basis
    yet). Pair with a low ``trade_probability`` for DCA-like behavior.
    """

    strategy_name = "long_term_holder"
    default_sentiment_sensitivity = 0.2

    def __init__(
        self,
        trader_id: str,
        *,
        take_profit_multiple: float = 3.0,
        max_buy_premium: float = 0.25,
        **kwargs,
    ):
        super().__init__(trader_id, **kwargs)
        if take_profit_multiple <= 1.0:
            raise ValueError("take_profit_multiple must be greater than 1")
        if max_buy_premium < 0:
            raise ValueError("max_buy_premium must not be negative")
        self.take_profit_multiple = take_profit_multiple
        self.max_buy_premium = max_buy_premium

    def effective_max_buy_premium(self, context: MarketContext) -> float:
        """Good news makes it willing to pay a bit more above its cost basis,
        bad news a bit less; its take-profit target never moves. The low
        default sensitivity keeps long-term behavior dominant."""
        pressure = self.sentiment_pressure(context)
        if pressure == 0:
            return self.max_buy_premium
        return self.max_buy_premium * (1.0 + pressure)

    def _decide(self, context: MarketContext) -> TradeDecision:
        cost = self.wallet.average_cost
        if self.wallet.coins > 0 and cost > 0 and context.price >= cost * self.take_profit_multiple:
            return self._sell(f"long-term target hit ({context.price / cost:.2f}x cost)")
        if cost == 0 or context.price <= cost * (1 + self.effective_max_buy_premium(context)):
            return self._buy(context.price, "accumulating")
        return TradeDecision.hold("price too far above cost basis to add")
