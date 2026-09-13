"""``CoinSimulator``: the minimum-viable single-coin market simulation.

Composes a ``Coin``'s fixed economics with a ``SimulationClock``, a
``MarketEngine`` price process, and a ``VolumeModel`` into a per-tick
simulation loop. Optionally takes:

- ``Whale`` participants, each of which may nudge a tick's price and
  volume with an outsized trade. An unfunded whale (the default) trades
  outside the reserve's accounting; a funded one settles against the
  market reserve like a trader (see ``core/whale.py``).
- ``TraderAgent`` participants (``core/traders``), whose rule-based
  decisions settle against a market reserve ``Wallet`` so coins and cash
  are conserved, and whose net flow moves price.

Two pricing modes (``PricingMode``), kept on separate code paths:

- ``random_walk`` (default): GBM random walk + linear whale/trader impact;
  traders settle against the market reserve at one price per tick.
- ``amm``: no random walk — price is the spot price of a constant-product
  ``AMMPool`` (``core/liquidity``) seeded by the market reserve; traders
  swap through it in list order. Whales are not supported in this mode yet.

Manipulators (``core/traders/manipulation.py``) are just more traders in
the list; the only special case is a WASH decision, which settles as two
self-cancelling legs (``execute_wash`` / ``execute_wash_via_pool``) whose
coins count toward reported volume (``SimulationTick.wash_volume``).

Optional news/external events (``core/events``). Each tick's
``EventState`` reaches the market two ways, and never sets a price:

- traders (both modes): its aggregate sentiment and attention go into
  ``MarketContext``; strategies may trade differently, and those trades
  move price through the normal fills / pool swaps;
- random-walk mode only: it scales the random walk's volatility and, only
  if ``drift_per_sentiment`` is nonzero (default 0.0), adds a drift of
  ``drift_per_sentiment × sentiment``. AMM mode has no random walk, so
  there events act through traders alone.

Events are scheduled up front in the ``EventEngine`` and/or started by an
optional ``RandomEventGenerator``, which is asked at the start of each tick
— before that tick's ``EventState`` is read — so a random event is live
from the tick it starts.

Optional whale observation (``whale_observation=True``; off by default).
Each tick records one read-only ``WhaleObservation`` per whale on
``SimulationTick.whale_observations`` — each whale's state, the price its
settlement used, and what it filled. A recording only: nothing in the
simulation reads it, it draws no randomness and moves no balance, so a run
with it on is identical to the same run with it off. Post-run summaries
live in ``analytics/whales.py``.

Optional market psychology (``psychology=True``; off by default). Each
tick, before traders decide, ``compute_psychology`` turns ``MarketSignals``
into one market-wide ``PsychologyState``: returns, momentum and volatility
from the closes of the last ``SIGNAL_WINDOW`` completed ticks (never the
tick being simulated), and sentiment, attention and aggregate severity
(``live_event_severity``) from the tick's ``EventState``. Traders get it on
a ``PsychologyContext`` and each strategy applies its own bounded
modifiers. It never sets a price: in both modes it acts only through the
traders' ordinary fills and swaps. With psychology off, traders get the
plain ``MarketContext`` and every run is exactly what it was before.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from crypto_simulator.core.clock import SimulationClock
from crypto_simulator.core.events.engine import EventEngine, EventState
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.liquidity.pool import AMMPool, PoolState
from crypto_simulator.core.liquidity.settlement import (
    execute_decision_via_pool,
    execute_wash_via_pool,
    seed_pool_from_wallet,
)
from crypto_simulator.core.market_engine import MarketEngine
from crypto_simulator.core.psychology import (
    SIGNAL_WINDOW,
    MarketSignals,
    PsychologyState,
    aggregate_event_severity,
    compute_psychology,
    signals_from_closes,
)
from crypto_simulator.core.traders.base import MarketContext, PsychologyContext, TradeAction, TraderAgent
from crypto_simulator.core.traders.execution import (
    TraderTrade,
    execute_decision,
    execute_wash,
    net_flow_price_impact,
)
from crypto_simulator.core.volume_model import VolumeModel
from crypto_simulator.core.whale import Whale, WhaleObservation, WhaleTrade
from crypto_simulator.models.coin import Coin
from crypto_simulator.models.wallet import Wallet

RESERVE_PROVIDER_ID = "market-reserve"


class PricingMode(str, Enum):
    RANDOM_WALK = "random_walk"
    AMM = "amm"


def live_event_severity(event_state: EventState, engine: EventEngine) -> float:
    """How severe the strongest event live in ``event_state`` is, in [0, 1].

    ``EventState`` reports each live event's current intensity but not its
    severity, so the severity is read from the engine's ``MarketEvent``
    with the same id; nothing in the events package changes for this. The
    aggregate is ``aggregate_event_severity``: the largest
    ``severity × intensity`` (so decay fades it), 0.0 with no live event,
    never a sum of overlapping events, and independent of their order.
    """
    severity = {event.event_id: event.severity for event in engine.events}
    return aggregate_event_severity((severity[status.event_id], status.intensity) for status in event_state.events)


@dataclass(frozen=True)
class SimulationTick:
    """A single tick's simulated coin state.

    ``pool_state`` is the AMM pool snapshot after the tick (``None`` in
    random-walk mode). ``event_state`` is the ground-truth ``EventState``
    applied this tick — neutral if no event was live — or ``None`` when the
    simulation has no event engine. ``psychology`` is the market-wide
    ``PsychologyState`` traders saw this tick, or ``None`` when psychology
    is off. ``whale_observations`` holds one read-only ``WhaleObservation``
    per whale, in whale-list order, when the simulation runs with
    ``whale_observation=True``; it is empty otherwise (and always in AMM
    mode, which has no whales).
    """

    tick: int
    timestamp: str
    price: float
    market_cap: float
    volume: float
    whale_trades: tuple[WhaleTrade, ...] = field(default_factory=tuple)
    trader_trades: tuple[TraderTrade, ...] = field(default_factory=tuple)
    pool_state: PoolState | None = None
    event_state: EventState | None = None
    psychology: PsychologyState | None = None
    whale_observations: tuple[WhaleObservation, ...] = field(default_factory=tuple)

    @property
    def wash_volume(self) -> float:
        """Coins traded in wash legs this tick (already included in
        ``volume``) — the part of reported volume that was a self-trade."""
        return sum(trade.quantity for trade in self.trader_trades if trade.wash)


class CoinSimulator:
    """Runs the simulation loop for a single fictional ``Coin``."""

    def __init__(
        self,
        coin: Coin,
        *,
        seed: int | None = None,
        volatility: float = 0.02,
        base_volume_pct: float = 0.01,
        tick_interval_seconds: float = 1.0,
        whales: list[Whale] | None = None,
        traders: list[TraderAgent] | None = None,
        reserve_cash: float | None = None,
        trader_impact_coefficient: float = 2.0,
        pricing_mode: PricingMode | str = PricingMode.RANDOM_WALK,
        amm_pool_coins: float | None = None,
        amm_fee_rate: Decimal | float | str = "0.003",
        events: EventEngine | None = None,
        drift_per_sentiment: float = 0.0,
        event_generator: RandomEventGenerator | None = None,
        psychology: bool = False,
        whale_observation: bool = False,
    ):
        if not isinstance(psychology, bool):
            raise ValueError(f"psychology must be True or False (got {psychology!r})")
        if not isinstance(whale_observation, bool):
            raise ValueError(f"whale_observation must be True or False (got {whale_observation!r})")
        try:
            self.pricing_mode = PricingMode(pricing_mode)
        except ValueError:
            raise ValueError(
                f"Unknown pricing_mode {pricing_mode!r}; expected one of "
                f"{[mode.value for mode in PricingMode]}"
            ) from None
        if self.pricing_mode is PricingMode.AMM and whales:
            raise ValueError(
                "Whales are not supported with pricing_mode='amm' yet: they hold no cash "
                "and trade against unlimited external liquidity, so routing them through "
                "the pool would change their behavior. Remove the whales or use "
                "pricing_mode='random_walk' (see docs/ROADMAP.md)."
            )
        if (
            isinstance(drift_per_sentiment, bool)
            or not isinstance(drift_per_sentiment, (int, float))
            or not math.isfinite(drift_per_sentiment)
            or drift_per_sentiment < 0
        ):
            raise ValueError(
                f"drift_per_sentiment must be a finite number >= 0 (got {drift_per_sentiment!r})"
            )
        if self.pricing_mode is PricingMode.AMM and drift_per_sentiment:
            raise ValueError(
                "drift_per_sentiment only applies to pricing_mode='random_walk'; in amm mode "
                "events move price only through trader reactions"
            )
        # Events are ground truth for the whole run; drift_per_sentiment is
        # the random walk's log-drift per tick at sentiment +/-1. A random
        # generator needs an engine to inject into.
        if event_generator is not None and events is None:
            events = EventEngine()
        self.events = events
        self.event_generator = event_generator
        self.drift_per_sentiment = drift_per_sentiment
        self.coin = coin
        self.whales = list(whales) if whales else []
        whale_holdings = sum(whale.holdings for whale in self.whales)
        if whale_holdings > coin.initial_supply:
            raise ValueError(
                f"Combined whale holdings ({whale_holdings}) exceed "
                f"coin.initial_supply ({coin.initial_supply})"
            )

        self.traders = list(traders) if traders else []
        trader_ids = [trader.trader_id for trader in self.traders]
        if len(set(trader_ids)) != len(trader_ids):
            raise ValueError(f"Trader ids must be unique; got {trader_ids}")
        trader_coins = sum(trader.wallet.coins for trader in self.traders)
        reserve_coins = coin.initial_supply - whale_holdings - trader_coins
        if reserve_coins < 0:
            raise ValueError(
                f"Whale ({whale_holdings}) plus trader ({trader_coins}) holdings "
                f"exceed coin.initial_supply ({coin.initial_supply})"
            )
        if trader_impact_coefficient < 0:
            raise ValueError("trader_impact_coefficient must not be negative")
        # The rest of the market: every coin not held by a whale or trader,
        # plus a fixed cash float. Traders settle against it; by default it
        # holds cash equal to its coins' value at the starting price.
        self.reserve = Wallet(
            cash=reserve_coins * coin.starting_price if reserve_cash is None else reserve_cash,
            coins=reserve_coins,
        )
        for wallet in [trader.wallet for trader in self.traders] + [w.wallet for w in self.whales if w.funded]:
            if wallet.coins > 0 and wallet.average_cost == 0:
                wallet.average_cost = coin.starting_price
        self.trader_impact_coefficient = trader_impact_coefficient
        history_window = max([trader.lookback for trader in self.traders], default=0)
        self._recent_closes: deque[float] = deque(
            [coin.starting_price], maxlen=max(1, history_window)
        )

        self.clock = SimulationClock(tick_interval=tick_interval_seconds)
        self._price_engine = MarketEngine(
            [coin.symbol],
            self.clock,
            seed=seed,
            initial_prices={coin.symbol: coin.starting_price},
            volatility=volatility,
        )
        # Distinct (but still deterministic) seeds keep each RNG stream from
        # replaying the same draws as the others.
        volume_seed = seed if seed is None else seed + 1
        self._volume_model = VolumeModel(
            coin.initial_supply, base_volume_pct=base_volume_pct, seed=volume_seed
        )
        self.history: list[SimulationTick] = []

        self.pool: AMMPool | None = None
        if self.pricing_mode is PricingMode.AMM:
            self.pool = self._seed_pool(amm_pool_coins, amm_fee_rate)
            spot = float(self.pool.spot_price())
            self._price_engine.set_price(coin.symbol, spot)
            self._recent_closes = deque([spot], maxlen=self._recent_closes.maxlen)

        # Completed closes behind the psychology signals (SIGNAL_WINDOW
        # returns need SIGNAL_WINDOW + 1 closes), opening with the same first
        # close traders see. Kept apart from _recent_closes so traders' price_history is
        # exactly what it is without psychology.
        self.psychology_enabled = psychology
        # A read-only recording of what the whales did; the simulation
        # itself never consults it.
        self.whale_observation_enabled = whale_observation
        self._psychology_closes: deque[float] | None = (
            deque([self._recent_closes[-1]], maxlen=SIGNAL_WINDOW + 1) if psychology else None
        )

    def _seed_pool(self, pool_coins: float | None, fee_rate) -> AMMPool:
        """The market reserve provides the pool's initial liquidity, at the
        coin's starting price, and holds every LP share."""
        price = self.coin.starting_price
        if pool_coins is None:
            pool_coins = min(self.reserve.coins, self.reserve.cash / price)
        pool_cash = pool_coins * price
        if pool_coins > self.reserve.coins:
            raise ValueError(
                f"amm pool needs {pool_coins} coins but only {self.reserve.coins} are "
                "unallocated (supply minus whale and trader holdings)"
            )
        if pool_cash > self.reserve.cash:
            raise ValueError(
                f"amm pool needs {pool_cash} cash ({pool_coins} coins x {price}) but the "
                f"market reserve holds {self.reserve.cash}; raise the reserve cash"
            )
        return seed_pool_from_wallet(
            self.reserve,
            coins=pool_coins,
            cash=pool_cash,
            fee_rate=fee_rate,
            provider_id=RESERVE_PROVIDER_ID,
        )

    def accounting_totals(self) -> tuple[Decimal, Decimal]:
        """Exact (coins, cash) held by traders, funded whales, the market
        reserve and the pool reserves (which include collected fees).
        Unfunded whales trade against external liquidity and are outside
        this system."""
        wallets = [t.wallet for t in self.traders] + [w.wallet for w in self.whales if w.funded]
        coin_parts = [Decimal(self.reserve.coins), *(Decimal(w.coins) for w in wallets)]
        cash_parts = [Decimal(self.reserve.cash), *(Decimal(w.cash) for w in wallets)]
        if self.pool is not None:
            coin_parts.append(self.pool.coin_reserve)
            cash_parts.append(self.pool.cash_reserve)
        coins, cash = Decimal(0), Decimal(0)
        for part in coin_parts:
            coins = EXACT.add(coins, part)
        for part in cash_parts:
            cash = EXACT.add(cash, part)
        return coins, cash

    @property
    def current_price(self) -> float:
        return self._price_engine.current_price(self.coin.symbol)

    def market_cap(self, price: float | None = None) -> float:
        """Market cap = price * total supply.

        Phase 1 has no minting/burning, so supply is always
        ``coin.initial_supply`` — a later phase changing supply over time
        would read the current supply from somewhere other than the coin's
        static config.
        """
        return (price if price is not None else self.current_price) * self.coin.initial_supply

    def step(self) -> SimulationTick:
        """Advance the simulation by one tick and record a snapshot."""
        if self.pricing_mode is PricingMode.AMM:
            tick = self._step_amm()
        else:
            tick = self._step_random_walk()
        self.history.append(tick)
        return tick

    def _step_random_walk(self) -> SimulationTick:
        """One random-walk tick.

        Order of operations: the base price process ticks first (with this
        tick's event drift and volatility, if there's an event engine), then
        each whale is given a chance to trade and multiply price by its
        impact factor (a funded whale first settles against the reserve at
        the running price), then traders decide and fill at that price, and their
        net flow applies one more impact factor. The engine's stored price is
        synced to the adjusted value via ``set_price`` so the *next* tick's
        random walk compounds from what actually happened this tick.
        """
        # MarketEngine.step() advances the clock, so ask for the tick it is
        # about to produce.
        event_state = self._event_state_for(self.clock.tick + 1)
        psychology = self._psychology_for(event_state)
        if event_state is None:
            prices = self._price_engine.step()
        else:
            prices = self._price_engine.step(
                drift=self.drift_per_sentiment * event_state.sentiment,
                volatility_scale=event_state.volatility_multiplier,
            )
        price = prices[self.coin.symbol]
        volume = self._volume_model.next_volume()

        whale_trades = []
        whale_observations = []
        for whale in self.whales:
            # Snapshot before the trade and complete it after, both at the
            # price this whale actually settles at: `price` still carries
            # only earlier whales' impact at this point.
            snapshot = whale.observe(price) if self.whale_observation_enabled else None
            trade = whale.maybe_trade(self.coin.initial_supply, price=price, reserve=self.reserve)
            if snapshot is not None:
                whale_observations.append(whale.complete_observation(snapshot, trade))
            if trade is None:
                continue
            whale_trades.append(trade)
            price *= trade.price_impact
            volume += trade.quantity

        trader_trades = self._run_traders(price, event_state, psychology) if self.traders else []
        net_trader_flow = 0.0
        # Wash legs are summed apart so a filled round trip contributes an
        # exact 0.0 rather than float residue from interleaving with others.
        wash_flow = 0.0
        for trade in trader_trades:
            volume += trade.quantity
            signed = trade.quantity if trade.side is TradeAction.BUY else -trade.quantity
            if trade.wash:
                wash_flow += signed
            else:
                net_trader_flow += signed
        net_trader_flow += wash_flow
        if net_trader_flow != 0:
            price *= net_flow_price_impact(
                net_trader_flow, self.coin.initial_supply, self.trader_impact_coefficient
            )

        if whale_trades or net_trader_flow != 0:
            self._price_engine.set_price(self.coin.symbol, price)
        self._record_close(price)

        return SimulationTick(
            tick=self.clock.tick,
            timestamp=self.clock.simulated_time.isoformat(),
            price=price,
            market_cap=self.market_cap(price),
            volume=volume,
            whale_trades=tuple(whale_trades),
            trader_trades=tuple(trader_trades),
            event_state=event_state,
            psychology=psychology,
            whale_observations=tuple(whale_observations),
        )

    def _step_amm(self) -> SimulationTick:
        """One AMM tick: no random walk; traders swap through the pool.

        Price is the pool's spot price after the tick's swaps, synced into
        the ``MarketEngine`` so ``current_price`` works in both modes.
        Volume is the coins actually swapped (no synthetic background
        volume — every trade is modeled). Events reach the pool only
        through the traders' swaps.
        """
        event_state = self._event_state_for(self.clock.tick + 1)
        psychology = self._psychology_for(event_state)
        self.clock.advance()
        trader_trades = self._run_traders_amm(event_state, psychology) if self.traders else []
        price = float(self.pool.spot_price())
        self._price_engine.set_price(self.coin.symbol, price)
        self._record_close(price)
        return SimulationTick(
            tick=self.clock.tick,
            timestamp=self.clock.simulated_time.isoformat(),
            price=price,
            market_cap=self.market_cap(price),
            volume=sum(trade.quantity for trade in trader_trades),
            trader_trades=tuple(trader_trades),
            pool_state=self.pool.state(),
            event_state=event_state,
            psychology=psychology,
        )

    def _record_close(self, price: float) -> None:
        self._recent_closes.append(price)
        if self._psychology_closes is not None:
            self._psychology_closes.append(price)

    def _event_state_for(self, tick: int) -> EventState | None:
        """The ``EventState`` for the tick about to be simulated, after the
        random generator (if any) has had its chance to start an event that
        tick. ``None`` when the simulation has no events at all."""
        if self.events is None:
            return None
        if self.event_generator is not None:
            self.event_generator.maybe_inject(self.events, tick)
        return self.events.state(tick)

    def market_signals(self, event_state: EventState | None) -> MarketSignals:
        """The ``MarketSignals`` for the tick about to be simulated.

        Price terms come only from completed closes (``signals_from_closes``
        over the last ``SIGNAL_WINDOW + 1``, the starting price counting as
        the first); news terms from this tick's ``EventState``, or neutral
        without an event engine. Requires ``psychology=True``.
        """
        if self._psychology_closes is None:
            raise RuntimeError("market_signals needs a CoinSimulator built with psychology=True")
        if event_state is None:
            return signals_from_closes(self._psychology_closes)
        return signals_from_closes(
            self._psychology_closes,
            event_sentiment=event_state.sentiment,
            event_severity=live_event_severity(event_state, self.events),
            attention=event_state.attention_multiplier,
        )

    def _psychology_for(self, event_state: EventState | None) -> PsychologyState | None:
        if self._psychology_closes is None:
            return None
        return compute_psychology(self.market_signals(event_state))

    def _market_context(
        self, price: float, event_state: EventState | None, psychology: PsychologyState | None
    ) -> MarketContext:
        """Only the public, aggregate news signal is passed on — never which
        events are live — plus, with psychology on, the market psychology."""
        fields = dict(
            tick=self.clock.tick,
            price=price,
            price_history=tuple(self._recent_closes),
            total_supply=self.coin.initial_supply,
        )
        if event_state is not None:
            fields.update(sentiment=event_state.sentiment, attention_multiplier=event_state.attention_multiplier)
        if psychology is None:
            return MarketContext(**fields)
        return PsychologyContext(**fields, psychology=psychology)

    def _run_traders(
        self, price: float, event_state: EventState | None, psychology: PsychologyState | None
    ) -> list[TraderTrade]:
        """Let each trader decide on the same snapshot and fill at ``price``.

        Traders act in list order; if the reserve runs short, later traders
        in the list get smaller (or no) fills that tick.
        """
        context = self._market_context(price, event_state, psychology)
        trades = []
        for trader in self.traders:
            decision = trader.decide(context)
            if decision.action is TradeAction.WASH:
                trades.extend(execute_wash(trader, decision, price, self.reserve))
                continue
            trade = execute_decision(trader, decision, price, self.reserve)
            if trade is not None:
                trades.append(trade)
        return trades

    def _run_traders_amm(
        self, event_state: EventState | None, psychology: PsychologyState | None
    ) -> list[TraderTrade]:
        """Every trader decides on the same pre-trade snapshot, then swaps
        in list order — each swap moves the pool, so later traders in the
        list execute at the price earlier swaps left behind."""
        price = float(self.pool.spot_price())
        context = self._market_context(price, event_state, psychology)
        trades = []
        for trader in self.traders:
            decision = trader.decide(context)
            if decision.action is TradeAction.WASH:
                trades.extend(execute_wash_via_pool(trader, decision, self.pool, reference_price=price))
                continue
            trade = execute_decision_via_pool(trader, decision, self.pool, reference_price=price)
            if trade is not None:
                trades.append(trade)
        return trades

    def run(self, ticks: int) -> list[SimulationTick]:
        """Run the simulation loop for ``ticks`` steps.

        Returns just the snapshots produced by this call (also appended to
        ``self.history``, so callers don't have to choose up front how much
        history to keep).
        """
        if ticks <= 0:
            raise ValueError("ticks must be positive")
        return [self.step() for _ in range(ticks)]
