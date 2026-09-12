"""Market-manipulation participants for the coin economy (educational).

These are ordinary ``TraderAgent`` subclasses — they hold a ``Wallet`` and
settle through the same reserve / pool paths as every other trader, so
coins and cash stay conserved — but they are registered separately
(``MANIPULATION_STRATEGIES``) and configured under ``coin.manipulators``,
never mixed into the organic ``coin.traders`` population.

- ``PumpAndDump``: accumulates quietly, pumps the price with concentrated
  buying, then dumps its coins on whoever followed the move up.
- ``WashTrader``: trades with itself (``TradeAction.WASH``) to inflate
  reported volume without changing its position.
"""

from __future__ import annotations

from enum import Enum

from crypto_simulator.core.traders.base import MarketContext, TradeAction, TradeDecision, TraderAgent


class SchemePhase(str, Enum):
    WAITING = "waiting"
    ACCUMULATE = "accumulate"
    PUMP = "pump"
    DUMP = "dump"
    DONE = "done"


class PumpAndDump(TraderAgent):
    """A scheduled pump-and-dump, phased by ``MarketContext.tick``:

    - ``start_tick`` .. +``accumulate_ticks``: **accumulate** — buy a fixed
      ``accumulate_share`` of the budget, spread evenly over the phase.
    - next ``pump_ticks``: **pump** — spend the rest of the budget, split
      evenly over the pump ticks still left.
    - from then on: **dump** — sell holdings evenly over the ``dump_ticks``
      still left; once that window has passed, sell everything left. Holds
      once the coins are gone (``done``).

    The budget is ``risk_tolerance`` × starting cash; the remainder is never
    spent. Every order is capped at ``max_trade_size`` coins, and the usual
    ``trade_probability`` gate still applies (pump and dump sizing catch up
    after a skipped tick; accumulation doesn't). There is no hype model —
    the only thing that draws followers in is the price move itself.
    """

    strategy_name = "pump_and_dump"

    def __init__(
        self,
        trader_id: str,
        *,
        start_tick: int = 1,
        accumulate_ticks: int = 10,
        accumulate_share: float = 0.3,
        pump_ticks: int = 5,
        dump_ticks: int = 5,
        **kwargs,
    ):
        super().__init__(trader_id, **kwargs)
        if start_tick < 1:
            raise ValueError("start_tick must be at least 1")
        if accumulate_ticks < 0:
            raise ValueError("accumulate_ticks must not be negative")
        if pump_ticks < 1 or dump_ticks < 1:
            raise ValueError("pump_ticks and dump_ticks must be at least 1")
        if not 0.0 <= accumulate_share <= 1.0:
            raise ValueError("accumulate_share must be within [0, 1]")
        self.start_tick = start_tick
        self.accumulate_ticks = accumulate_ticks
        self.accumulate_share = accumulate_share
        self.pump_ticks = pump_ticks
        self.dump_ticks = dump_ticks
        self.budget = self.risk_tolerance * self.wallet.cash
        self._untouchable_cash = self.wallet.cash - self.budget
        self._pump_start = start_tick + accumulate_ticks
        self._dump_start = self._pump_start + pump_ticks
        self._dump_end = self._dump_start + dump_ticks

    def phase(self, tick: int) -> SchemePhase:
        if tick < self.start_tick:
            return SchemePhase.WAITING
        if tick < self._pump_start:
            return SchemePhase.ACCUMULATE
        if tick < self._dump_start:
            return SchemePhase.PUMP
        return SchemePhase.DUMP if self.wallet.coins > 0 else SchemePhase.DONE

    def _decide(self, context: MarketContext) -> TradeDecision:
        phase = self.phase(context.tick)
        if phase is SchemePhase.ACCUMULATE:
            cash = self.budget * self.accumulate_share / self.accumulate_ticks
            return self._spend(cash, context.price, "accumulate")
        if phase is SchemePhase.PUMP:
            cash = self._spendable_cash() / (self._dump_start - context.tick)
            return self._spend(cash, context.price, "pump")
        if phase is SchemePhase.DUMP:
            ticks_left = max(1, self._dump_end - context.tick)
            quantity = min(self.max_trade_size, self.wallet.coins / ticks_left)
            return TradeDecision(TradeAction.SELL, quantity, "dump")
        return TradeDecision.hold(phase.value)

    def _spendable_cash(self) -> float:
        return max(0.0, self.wallet.cash - self._untouchable_cash)

    def _spend(self, cash: float, price: float, reason: str) -> TradeDecision:
        quantity = min(self.max_trade_size, min(cash, self._spendable_cash()) / price)
        if quantity <= 0:
            return TradeDecision.hold(f"{reason}; budget spent")
        return TradeDecision(TradeAction.BUY, quantity, reason)


class WashTrader(TraderAgent):
    """Trades with itself to inflate reported volume.

    When active, returns a WASH decision sized like an ordinary buy
    (``risk_tolerance`` × cash, capped at ``max_trade_size`` coins). The
    round trip leaves its position unchanged: in random-walk mode it is
    free and price-neutral; through an AMM pool it pays the swap fee on
    both legs. No other participant reads volume yet, so the fake volume
    misleads only whoever reads the tape.
    """

    strategy_name = "wash_trader"

    def _decide(self, context: MarketContext) -> TradeDecision:
        quantity = min(self.max_trade_size, self.risk_tolerance * self.wallet.cash / context.price)
        if quantity <= 0:
            return TradeDecision.hold("wash trade; no cash")
        return TradeDecision(TradeAction.WASH, quantity, "wash trade")
