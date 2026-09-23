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

# --- Crowd response (Phase 19, Step 4) ----------------------------------------
# The observation Step 2 put on the context is the *previous completed*
# tick's organic signed net flow as a fraction of total supply. These two
# constants are the whole of what Step 4 adds to turn it into behaviour.
#
# CROWD_FLOW_SCALE is the flow magnitude at which the response reaches
# tanh(1) = 76% of its own maximum. 0.01 of supply is the upper-middle of
# the measured per-tick |flow| distribution (Phase 19 Step 3: mean 0.005-
# 0.013, p95 0.013-0.037 across the 24-cell grid), so the response is
# gentle on a typical tick and saturates in the tail rather than acting
# as an on/off switch.
CROWD_FLOW_SCALE = 0.01

# The hard ceiling on the crowd participation urge — half the psychology
# layer's own ceiling of 1.0, so the crowd can never be the larger of the
# two engagement terms. With every shipped sensitivity <= this value and
# tanh < 1, it is a guard that does not bind (the same relationship Step
# 2's [-1, 1] flow clamp has to conservation of coins); it is here so the
# bound holds for any sensitivity a caller supplies.
CROWD_URGE_CAP = 0.5

# --- Crowd direction (Phase 19, Step 7) ---------------------------------------
# The *second* crowd channel, and a different one: Step 4 asks a loud crowd
# to make a trader show up, this asks a one-sided crowd to pull a trader
# toward the side it took. It reads the same observable with its **sign**
# kept, where the participation term takes the magnitude, so the two cannot
# be confused for versions of each other.
#
# The ceiling, in the units `strategies.PSYCHOLOGY_MAX_SHIFT` uses: at full
# strength the tilt moves a directional parameter at most this fraction of
# the way toward its bound. 0.25 is half of PSYCHOLOGY_MAX_SHIFT (0.5), the
# same "the crowd is never the larger influence" relationship CROWD_URGE_CAP
# has to psychology's own participation ceiling of 1.0. Every shipped
# sensitivity is <= this and tanh < 1, so the clamp is a guard that does not
# bind; it is kept so the bound holds for any sensitivity a caller supplies.
# It deliberately reuses CROWD_FLOW_SCALE rather than introducing a second
# flow scale that could drift from the first.
CROWD_DIRECTION_MAX_SHIFT = 0.25

# --- Participation breadth (Phase 19, Step 14) --------------------------------
# A third, separate crowd channel, preregistered in Step 13: the *number* of
# other participants on each side of the previous completed tick, not their
# coins. It reads the context's `crowd_breadth` field (leave-self-out signed breadth
# in [-1, 1]) and tilts direction only, by at most this fraction of the way
# toward a bound. Frozen by the preregistration; not tuned.
BREADTH_DIRECTION_MAX_SHIFT = 0.25


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

    ``crowd_flow`` (Phase 19) is the other public, aggregate signal: what
    the organic crowd *did* on the previous completed tick, as a signed
    fraction of total supply in [-1, 1] (positive = net buying). Like
    ``sentiment`` it is a market-wide number read off the public tape, not
    a view of any individual participant: traders still never see another
    trader's identity, position or decision. ``None`` — the default, and
    what every tick carries unless the simulation was built with
    ``crowd_observation=True`` — means no observation is available, which
    is also the case on the first tick, since nothing has completed yet.
    Computed by ``CoinSimulator.organic_crowd_flow``; **nothing reads it
    yet** (Phase 19 Step 2 adds the observation only).

    ``crowd_breadth`` (Phase 19 Step 14) is signed participation breadth
    of the previous completed tick, *leaving the receiving trader out*:
    ``(buyers - sellers) / (buyers + sellers)`` over the other organic
    traders that filled, in [-1, 1], 0.0 when none of them did. It is one
    anonymous count ratio — no identities, classes, sizes or flow — so it
    is per trader, and ``CoinSimulator`` hands each trader its own copy of
    the tick's shared context with only this field set. ``None`` — the
    default — without ``breadth_observation`` and on the first tick.
    """

    tick: int
    price: float
    price_history: tuple[float, ...]
    total_supply: float
    sentiment: float = 0.0
    attention_multiplier: float = 1.0
    crowd_flow: float | None = None
    crowd_breadth: float | None = None

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

    The **crowd-flow participation response** (Phase 19 Step 4) is a third
    engagement layer, and the narrowest of them: ``crowd_urge`` —
    ``crowd_sensitivity`` × a bounded saturating transform of the previous
    tick's observed organic flow — is a second application of the very
    operator psychology already uses, and it touches **participation and
    nothing else**. It never reaches sizing, direction, a threshold or a
    price target, and it never enters psychology. ``crowd_sensitivity`` is
    0 by default on every strategy, so a trader built the ordinary way
    behaves exactly as it did before; the value a strategy takes when the
    response is switched on is its class ``default_crowd_sensitivity``,
    which the *service* layer supplies deliberately
    (``build_coin_simulator(crowd_response=True)``). It is opt-in and
    default-off at both levels.

    **What this was measured to do, and what it was not.** Call it a
    crowd-flow participation response and nothing grander. It is **not a
    demonstrated market-level herding mechanism, and not social
    influence**: the Phase 19 Step 4 experiment (A2 − A1, the response on
    versus the same observable present and ignored, paired seed-for-seed
    over 24 cells × 20 seeds × 2 pricing modes) found

    - a real, targeted effect on the class that carries a sensitivity —
      momentum participation rose in 23 of 24 cells;
    - and **no detectable market-level herding signature**: the primary
      aggregate metric, M5b (the conditional association between lag-1
      organic flow and subsequent trader direction), moved by a median of
      +0.0035 against a structural baseline of about 0.09, was
      **significant in 0 of 24 cells**, and **exceeded twice the null
      floor in 0 of 24 cells** — the null floor being the same estimator
      run against the participation gate, a channel that provably cannot
      respond to crowd flow at all.

    So one participant's fills do change another participant's propensity
    to act, which is participant-to-participant feedback; the market-wide
    herding that such feedback is often assumed to produce was looked for
    with a pre-registered metric and was not found. Anyone extending this
    should treat the aggregate result as an open question, not a settled
    one, and should not describe this layer as herding or social influence
    without saying that the experiment did not establish either.
    """

    strategy_name: ClassVar[str]
    default_sentiment_sensitivity: ClassVar[float] = 0.0
    psychology_sensitivity: ClassVar[float] = 0.0
    # What `crowd_sensitivity` this strategy is given when a caller turns
    # the crowd response ON. It is NOT applied on its own: the constructor
    # defaults to 0.0, so the response is opt-in at the point a simulation
    # is built, never by merely instantiating a trader.
    default_crowd_sensitivity: ClassVar[float] = 0.0
    # The directional crowd channel's equivalent, and deliberately a
    # *separate* field: reusing `crowd_sensitivity` would silently hand
    # momentum a directional response as well and destroy the whole point of
    # measuring one channel at a time.
    default_crowd_direction_sensitivity: ClassVar[float] = 0.0
    # The breadth channel's (Step 14), separate again: breadth and flow are
    # different observations, and one must be switchable without the other.
    default_breadth_direction_sensitivity: ClassVar[float] = 0.0
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
        crowd_sensitivity: float = 0.0,
        crowd_direction_sensitivity: float = 0.0,
        breadth_direction_sensitivity: float = 0.0,
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
        if (
            isinstance(crowd_sensitivity, bool)
            or not isinstance(crowd_sensitivity, (int, float))
            or not math.isfinite(crowd_sensitivity)
            or crowd_sensitivity < 0
        ):
            raise ValueError(f"crowd_sensitivity must be a finite number >= 0 (got {crowd_sensitivity!r})")
        if crowd_sensitivity and not self.responds_to_news:
            # Manipulators run a script; a crowd they helped make must not
            # feed back into it, or the exclusion Step 2 built would leak
            # back in through participation.
            raise ValueError(f"{type(self).__name__} ignores news; crowd_sensitivity must be 0")
        if (
            isinstance(crowd_direction_sensitivity, bool)
            or not isinstance(crowd_direction_sensitivity, (int, float))
            or not math.isfinite(crowd_direction_sensitivity)
            or crowd_direction_sensitivity < 0
        ):
            raise ValueError(
                "crowd_direction_sensitivity must be a finite number >= 0 "
                f"(got {crowd_direction_sensitivity!r})"
            )
        if crowd_direction_sensitivity and not self.responds_to_news:
            # Same reasoning as the participation term: a manipulator runs a
            # script, and a crowd it helped make must not steer it back.
            raise ValueError(
                f"{type(self).__name__} ignores news; crowd_direction_sensitivity must be 0"
            )
        if (
            isinstance(breadth_direction_sensitivity, bool)
            or not isinstance(breadth_direction_sensitivity, (int, float))
            or not math.isfinite(breadth_direction_sensitivity)
            or breadth_direction_sensitivity < 0
        ):
            raise ValueError(
                "breadth_direction_sensitivity must be a finite number >= 0 "
                f"(got {breadth_direction_sensitivity!r})"
            )
        if breadth_direction_sensitivity and not self.responds_to_news:
            raise ValueError(
                f"{type(self).__name__} ignores news; breadth_direction_sensitivity must be 0"
            )
        self.trader_id = trader_id
        self.wallet = Wallet(cash=starting_cash, coins=starting_coins)
        self.trade_probability = trade_probability
        self.max_trade_size = max_trade_size
        self.risk_tolerance = risk_tolerance
        self.sentiment_sensitivity = sentiment_sensitivity
        self.crowd_sensitivity = float(crowd_sensitivity)
        self.crowd_direction_sensitivity = float(crowd_direction_sensitivity)
        self.breadth_direction_sensitivity = float(breadth_direction_sensitivity)
        self._rng = random.Random(seed)

    @property
    def lookback(self) -> int:
        """Ticks of closing-price history this strategy needs."""
        return 0

    def participation_probability(self, context: MarketContext) -> float:
        """Chance of acting this tick, in three layers.

        News: ``trade_probability``, scaled up by the attention multiplier
        and capped at 1. Psychology, on top: with the trader's
        ``participation_urge`` u in [0, 1], that probability p becomes
        ``p × (1 + u × (1 - p))`` — at most ``1 - (1 - p)²``. Crowd
        response (Phase 19 Step 4), on top of that: the *same* operator
        applied once more with ``crowd_urge``, which is 0 for every trader
        unless a caller switched the response on.

        Each layer can only move p toward 1, never past it, and a trader
        with ``trade_probability`` 0 never acts however loud the crowd is.
        With ``crowd_urge`` 0 the third layer returns its input unchanged —
        bit-for-bit, not approximately — which is what makes a crowd-off
        run identical to a pre-Step-4 run.
        """
        if not self.responds_to_news or context.attention_multiplier == 1.0:
            probability = self.trade_probability
        else:
            probability = min(1.0, self.trade_probability * context.attention_multiplier)
        probability = self._engage(probability, self.participation_urge(context))
        return self._engage(probability, self.crowd_urge(context))

    @staticmethod
    def _engage(probability: float, urge: float) -> float:
        """One bounded engagement increment: ``p × (1 + u × (1 - p))``.

        Monotone in both arguments, fixed at p for u = 0 and at 0 and 1 for
        those p, and never above ``_JUST_BELOW_ONE``. Composing it is what
        keeps every engagement layer inside the same guarantee instead of
        each inventing its own.
        """
        if urge == 0.0 or probability in (0.0, 1.0):
            return probability
        # The cap only guards float rounding when p is within ~1e-8 of 1.
        return min(probability * (1.0 + urge * (1.0 - probability)), _JUST_BELOW_ONE)

    def crowd_pressure(self, context: MarketContext) -> float:
        """How loud the previous tick's organic crowd was, in [0, 1).

        ``tanh(|crowd_flow| / CROWD_FLOW_SCALE)``: continuous and smooth
        everywhere, odd-symmetric in the flow's *sign* — which is to say it
        ignores it, because this term feeds participation only and a crowd
        that sold hard is exactly as attention-grabbing as one that bought
        hard. It is 0 at zero flow, strictly increasing in |flow|, and
        saturates below 1, so no flow however extreme can make it blow up:
        at the observable's own bound (|flow| = 1, i.e. the entire supply
        in one tick) it is 1 to within float precision.

        0.0 whenever there is nothing to react to — no observation on the
        context (the first tick, or crowd observation off), a trader that
        ignores news, or ``crowd_sensitivity`` 0 — so the ordinary run
        never even evaluates the transform.
        """
        if self.crowd_sensitivity == 0.0 or not self.responds_to_news:
            return 0.0
        flow = context.crowd_flow
        if flow is None:
            return 0.0
        return math.tanh(abs(flow) / CROWD_FLOW_SCALE)

    def crowd_urge(self, context: MarketContext) -> float:
        """``crowd_sensitivity × crowd_pressure``, capped at
        ``CROWD_URGE_CAP``. The trader's whole reaction to the crowd, and
        a participation term only — see ``TraderAgent``'s docstring for
        what the Step 4 experiment measured this to do (a targeted
        participation effect) and what it measured this *not* to do (any
        detectable market-level herding: M5b significant in 0 of 24
        cells)."""
        return min(CROWD_URGE_CAP, self.crowd_sensitivity * self.crowd_pressure(context))

    def crowd_direction_tilt(self, context: MarketContext) -> float:
        """Which way the previous tick's crowd pulls this trader, in
        ``[-CROWD_DIRECTION_MAX_SHIFT, +CROWD_DIRECTION_MAX_SHIFT]``
        (Phase 19, Step 7).

        ``crowd_direction_sensitivity × tanh(crowd_flow / CROWD_FLOW_SCALE)``,
        clamped. Where ``crowd_pressure`` takes the flow's *magnitude* and
        asks whether to act at all, this keeps its **sign** and asks which
        side to take — the two read the same number and answer different
        questions, which is why they are separate terms with separate
        sensitivities rather than one knob.

        Positive flow (the crowd was a net buyer) gives a positive tilt,
        negative flow a negative one, and ``tanh`` makes the map
        antisymmetric — ``tilt(-f) == -tilt(f)`` exactly — continuous,
        smooth, strictly increasing in the flow and saturating below the
        clamp, so no flow however extreme can make it jump or blow up.

        0.0 whenever there is nothing to react to: no observation on the
        context (the first tick, or crowd observation off), a trader that
        ignores news, or ``crowd_direction_sensitivity`` 0. Deterministic
        and RNG-free — it only changes the number an existing draw is
        compared against.
        """
        if self.crowd_direction_sensitivity == 0.0 or not self.responds_to_news:
            return 0.0
        flow = context.crowd_flow
        if flow is None:
            return 0.0
        tilt = self.crowd_direction_sensitivity * math.tanh(flow / CROWD_FLOW_SCALE)
        return max(-CROWD_DIRECTION_MAX_SHIFT, min(CROWD_DIRECTION_MAX_SHIFT, tilt))

    def breadth_direction_tilt(self, context: MarketContext) -> float:
        """Which way the other participants' previous-tick breadth pulls
        this trader, in ``[-BREADTH_DIRECTION_MAX_SHIFT,
        +BREADTH_DIRECTION_MAX_SHIFT]`` (Phase 19, Step 14).

        ``breadth_direction_sensitivity × crowd_breadth``, clamped. Linear
        in the breadth, so it is sign-preserving, monotone and antisymmetric;
        ``crowd_breadth`` is already in [-1, 1], so the clamp is a guard.
        The sole reader of ``crowd_breadth``. 0.0 with no observation (the
        first tick, or breadth observation off), zero breadth, a trader that
        ignores news, or sensitivity 0. Deterministic and RNG-free.
        """
        if self.breadth_direction_sensitivity == 0.0 or not self.responds_to_news:
            return 0.0
        breadth = context.crowd_breadth
        if breadth is None:
            return 0.0
        tilt = self.breadth_direction_sensitivity * breadth
        return max(-BREADTH_DIRECTION_MAX_SHIFT, min(BREADTH_DIRECTION_MAX_SHIFT, tilt))

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
