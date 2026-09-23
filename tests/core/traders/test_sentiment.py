"""Trader reactions to public news: sentiment pressure and attention.

Traders see only ``MarketContext.sentiment`` / ``attention_multiplier``.
Sentiment bends each strategy's own parameters; attention only changes how
often a trader acts. Neither adds a random draw, and with no news (or zero
sensitivity) every decision is exactly what it was before.
"""

import dataclasses
import math
import random

import pytest

from crypto_simulator.core.traders.base import MarketContext, TradeAction, TradeDecision, TraderAgent
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import create_trader
from crypto_simulator.core.traders.strategies import (
    DipBuyer,
    LongTermHolder,
    MomentumTrader,
    PanicSeller,
    RetailTrader,
)

COMMON = dict(trade_probability=1.0, max_trade_size=1e9, risk_tolerance=0.5, seed=1)


def _ctx(price=1.0, history=(1.0,), sentiment=0.0, attention=1.0, tick=None):
    return MarketContext(
        tick=len(history) if tick is None else tick, price=price, price_history=tuple(history),
        total_supply=1_000_000.0, sentiment=sentiment, attention_multiplier=attention,
    )


def _holder(**kwargs):
    trader = LongTermHolder("h", starting_cash=10_000.0, starting_coins=100.0, **{**COMMON, **kwargs})
    trader.wallet.average_cost = 1.0
    return trader


def _organic(strategy, seed=1, **kwargs):
    common = {**COMMON, "seed": seed, **kwargs}
    return {
        "retail": lambda: RetailTrader("t", starting_cash=5_000.0, starting_coins=5_000.0, **common),
        "momentum": lambda: MomentumTrader("t", starting_cash=5_000.0, starting_coins=5_000.0, lookback=3, **common),
        "dip_buyer": lambda: DipBuyer("t", starting_cash=5_000.0, starting_coins=5_000.0, lookback=3, **common),
        "panic_seller": lambda: PanicSeller("t", starting_cash=5_000.0, starting_coins=5_000.0, lookback=3, **common),
        "long_term_holder": lambda: _holder(seed=seed, **kwargs),
    }[strategy]()


STRATEGIES = ["retail", "momentum", "dip_buyer", "panic_seller", "long_term_holder"]


def _random_contexts(n=400, seed=0, sentiment=None, attention=1.0):
    rng = random.Random(seed)
    contexts = []
    for tick in range(1, n + 1):
        history = tuple(rng.uniform(0.7, 1.3) for _ in range(4))
        s = rng.uniform(-1, 1) if sentiment is None else sentiment
        contexts.append(_ctx(price=rng.uniform(0.7, 1.3), history=history, sentiment=s, attention=attention, tick=tick))
    return contexts


def _decisions(trader, contexts):
    return [trader.decide(c) for c in contexts]


# --- MarketContext ------------------------------------------------------------------------


def test_market_context_defaults_to_no_news_and_old_construction_still_works():
    context = MarketContext(3, 1.5, (1.0, 1.2), 1_000_000.0)
    assert (context.sentiment, context.attention_multiplier) == (0.0, 1.0)
    assert context.return_over(2) == 0.5


def test_market_context_carries_only_public_market_wide_signals():
    """The guard this test has always been: nothing per-participant and
    nothing private reaches a trader. Phase 19 Step 2 added ``crowd_flow``,
    the same kind of figure as ``sentiment`` — one market-wide number off
    the public tape — so the list grew by exactly one name and still holds
    no event identity, trader identity, position or decision. It defaults
    to ``None``, so a context built as before is unchanged. Phase 19 Step 14
    added ``crowd_breadth`` — one anonymous headcount ratio of the previous
    tick, leaving the receiving trader out — and nothing else; it too
    defaults to ``None``.
    """
    fields = {f.name for f in dataclasses.fields(MarketContext)}
    assert fields == {"tick", "price", "price_history", "total_supply", "sentiment",
                      "attention_multiplier", "crowd_flow", "crowd_breadth"}
    assert MarketContext(3, 1.5, (1.0, 1.2), 1_000_000.0).crowd_flow is None
    assert MarketContext(3, 1.5, (1.0, 1.2), 1_000_000.0).crowd_breadth is None


# --- sensitivity ---------------------------------------------------------------------------


def test_default_sensitivities_per_strategy():
    defaults = {name: _organic(name).sentiment_sensitivity for name in STRATEGIES}
    assert defaults == {
        "retail": 1.0, "momentum": 0.8, "dip_buyer": 0.0, "panic_seller": 1.0, "long_term_holder": 0.2,
    }
    assert PumpAndDump("p").sentiment_sensitivity == 0.0
    assert WashTrader("w").sentiment_sensitivity == 0.0


def test_sensitivity_can_be_set_per_trader_including_through_strategy_params():
    assert RetailTrader("r", sentiment_sensitivity=0.3).sentiment_sensitivity == 0.3
    trader = create_trader("momentum", "m", params={"sentiment_sensitivity": 0.25})
    assert trader.sentiment_sensitivity == 0.25


@pytest.mark.parametrize("value", [-0.1, math.nan, math.inf, True, "1"])
def test_invalid_sensitivity_is_rejected(value):
    with pytest.raises(ValueError, match="sentiment_sensitivity"):
        RetailTrader("r", sentiment_sensitivity=value)


@pytest.mark.parametrize("cls", [PumpAndDump, WashTrader])
def test_manipulators_cannot_be_given_a_sensitivity(cls):
    with pytest.raises(ValueError, match="ignores news"):
        cls("m", sentiment_sensitivity=0.5)


def test_sentiment_pressure_is_sensitivity_times_sentiment_clamped():
    retail = RetailTrader("r", sentiment_sensitivity=0.5)
    assert retail.sentiment_pressure(_ctx(sentiment=0.6)) == 0.5 * 0.6
    assert RetailTrader("r", sentiment_sensitivity=3.0).sentiment_pressure(_ctx(sentiment=0.5)) == 1.0
    assert RetailTrader("r", sentiment_sensitivity=3.0).sentiment_pressure(_ctx(sentiment=-0.5)) == -1.0
    assert retail.sentiment_pressure(_ctx(sentiment=0.0)) == 0.0
    assert RetailTrader("r", sentiment_sensitivity=0.0).sentiment_pressure(_ctx(sentiment=0.9)) == 0.0


# --- retail -------------------------------------------------------------------------------------


def test_retail_buy_bias_rises_on_good_news_and_falls_on_bad_news():
    retail = RetailTrader("r", buy_bias=0.5, **COMMON)
    assert retail.effective_buy_bias(_ctx()) == 0.5
    assert retail.effective_buy_bias(_ctx(sentiment=0.5)) == 0.75
    assert retail.effective_buy_bias(_ctx(sentiment=-0.5)) == 0.25
    assert retail.effective_buy_bias(_ctx(sentiment=1.0)) == 1.0
    assert retail.effective_buy_bias(_ctx(sentiment=-1.0)) == 0.0


def test_retail_good_news_turns_some_sells_into_buys_and_never_the_reverse():
    def buys(sentiment):
        trader = RetailTrader("r", starting_cash=1e6, starting_coins=1e6, buy_bias=0.5, **COMMON)
        return [trader.decide(_ctx(sentiment=sentiment)).action is TradeAction.BUY for _ in range(2_000)]

    neutral, good, bad = buys(0.0), buys(0.6), buys(-0.6)
    assert all(g or not n for g, n in zip(good, neutral))  # every neutral buy is still a buy
    assert all(n or not b for n, b in zip(neutral, bad))
    assert sum(bad) < sum(neutral) < sum(good)


# --- momentum -------------------------------------------------------------------------------


def test_momentum_thresholds_ease_entry_on_good_news_and_exit_on_bad_news():
    momentum = MomentumTrader("m", entry_threshold=0.03, exit_threshold=0.05, **COMMON)
    assert momentum.effective_thresholds(_ctx()) == (0.03, 0.05)
    entry, exit_ = momentum.effective_thresholds(_ctx(sentiment=0.5))  # pressure 0.4
    assert (entry, exit_) == (pytest.approx(0.018), 0.05)
    entry, exit_ = momentum.effective_thresholds(_ctx(sentiment=-0.5))
    assert (entry, exit_) == (0.03, pytest.approx(0.03))


def test_momentum_enters_and_exits_on_smaller_moves_when_news_agrees():
    momentum = MomentumTrader("m", starting_cash=1_000.0, starting_coins=1_000.0, lookback=2,
                              entry_threshold=0.03, exit_threshold=0.03, **COMMON)
    up, down = (1.0, 1.0), (1.0, 1.0)
    assert momentum.decide(_ctx(1.02, up)).action is TradeAction.HOLD
    assert momentum.decide(_ctx(1.02, up, sentiment=0.8)).action is TradeAction.BUY
    assert momentum.decide(_ctx(0.98, down)).action is TradeAction.HOLD
    assert momentum.decide(_ctx(0.98, down, sentiment=-0.8)).action is TradeAction.SELL
    # Good news doesn't make it sell faster, bad news doesn't make it buy faster.
    assert momentum.decide(_ctx(0.98, down, sentiment=0.8)).action is TradeAction.HOLD
    assert momentum.decide(_ctx(1.02, up, sentiment=-0.8)).action is TradeAction.HOLD


# --- panic seller -------------------------------------------------------------------------------


def test_panic_thresholds_lower_panic_on_bad_news_and_reentry_on_good_news():
    panic = PanicSeller("p", panic_threshold=0.08, reentry_threshold=0.06, **COMMON)
    assert panic.effective_thresholds(_ctx()) == (0.08, 0.06)
    assert panic.effective_thresholds(_ctx(sentiment=-0.5)) == (0.04, 0.06)
    assert panic.effective_thresholds(_ctx(sentiment=0.5)) == (0.08, 0.03)


def test_bad_news_turns_a_calm_drawdown_into_panic_and_good_news_triggers_fomo():
    panic = PanicSeller("p", starting_cash=1_000.0, starting_coins=1_000.0, lookback=3,
                        panic_threshold=0.08, reentry_threshold=0.06, **COMMON)
    dip = _ctx(0.95, (1.0, 1.0, 1.0))
    assert panic.decide(dip).reason == "calm"
    assert panic.decide(dataclasses.replace(dip, sentiment=-0.5)).action is TradeAction.SELL
    rally = _ctx(1.04, (1.0, 1.0, 1.0))
    assert panic.decide(rally).reason == "calm"
    assert panic.decide(dataclasses.replace(rally, sentiment=0.5)).action is TradeAction.BUY


# --- dip buyer --------------------------------------------------------------------------------


@pytest.mark.parametrize("sensitivity", [None, 1.0])
def test_dip_buyer_does_not_react_to_sentiment(sensitivity):
    contexts = _random_contexts(sentiment=0.0)
    for sentiment in (1.0, -1.0):
        neutral = _organic("dip_buyer", sentiment_sensitivity=sensitivity)
        newsy = _organic("dip_buyer", sentiment_sensitivity=sensitivity)
        shifted = [dataclasses.replace(c, sentiment=sentiment) for c in contexts]
        assert _decisions(newsy, shifted) == _decisions(neutral, contexts)


# --- long-term holder -------------------------------------------------------------------------


def test_long_term_holder_reacts_weakly_through_its_buy_premium_only():
    holder = _holder(max_buy_premium=0.2, take_profit_multiple=3.0)
    assert holder.effective_max_buy_premium(_ctx()) == 0.2
    assert holder.effective_max_buy_premium(_ctx(sentiment=1.0)) == pytest.approx(0.24)
    assert holder.effective_max_buy_premium(_ctx(sentiment=-1.0)) == pytest.approx(0.16)
    assert holder.decide(_ctx(1.22)).action is TradeAction.HOLD
    assert holder.decide(_ctx(1.22, sentiment=1.0)).action is TradeAction.BUY
    assert holder.decide(_ctx(1.18)).action is TradeAction.BUY
    assert holder.decide(_ctx(1.18, sentiment=-1.0)).action is TradeAction.HOLD
    # Its long-term take-profit target doesn't move with the news.
    for sentiment in (-1.0, 0.0, 1.0):
        assert holder.decide(_ctx(3.0, sentiment=sentiment)).action is TradeAction.SELL


def test_long_term_holder_reacts_less_than_retail():
    holder, retail = _holder(), RetailTrader("r", **COMMON)
    for sentiment in (-1.0, -0.4, 0.3, 1.0):
        context = _ctx(sentiment=sentiment)
        assert abs(holder.sentiment_pressure(context)) == pytest.approx(0.2 * abs(retail.sentiment_pressure(context)))


# --- parameter bounds ----------------------------------------------------------------------------


def test_adjusted_parameters_always_stay_valid():
    rng = random.Random(4)
    for _ in range(3_000):
        context = _ctx(sentiment=rng.uniform(-1, 1))
        sensitivity = rng.choice([0.0, rng.uniform(0, 1), rng.uniform(1, 5)])
        bias = rng.choice([0.0, 1.0, rng.random()])
        assert 0.0 <= RetailTrader("r", buy_bias=bias, sentiment_sensitivity=sensitivity).effective_buy_bias(context) <= 1.0
        entry, exit_ = MomentumTrader("m", sentiment_sensitivity=sensitivity).effective_thresholds(context)
        panic, reentry = PanicSeller("p", sentiment_sensitivity=sensitivity).effective_thresholds(context)
        premium = LongTermHolder("h", sentiment_sensitivity=sensitivity).effective_max_buy_premium(context)
        assert min(entry, exit_, panic, reentry, premium) >= 0.0
        assert entry <= 0.02 and exit_ <= 0.02 and panic <= 0.08 and reentry <= 0.06 and premium <= 0.5


# --- attention -----------------------------------------------------------------------------------


def test_attention_scales_participation_up_to_certainty():
    trader = MomentumTrader("m", trade_probability=0.4)
    assert trader.participation_probability(_ctx()) == 0.4
    assert trader.participation_probability(_ctx(attention=1.5)) == pytest.approx(0.6)
    assert trader.participation_probability(_ctx(attention=4.0)) == 1.0


def test_attention_adds_active_ticks_without_choosing_a_direction():
    def active(attention):
        trader = MomentumTrader("m", starting_cash=1_000.0, starting_coins=1_000.0, trade_probability=0.3, seed=5)
        decisions = [trader.decide(_ctx(attention=attention)) for _ in range(1_000)]
        assert all(d.action is TradeAction.HOLD for d in decisions)  # flat market: nothing to do
        return [d.reason != "inactive this tick" for d in decisions]

    calm, busy = active(1.0), active(2.0)
    assert all(b or not c for b, c in zip(busy, calm))
    assert sum(busy) > sum(calm)


def test_bad_news_with_high_attention_does_not_force_everyone_to_sell():
    context = _ctx(1.0, sentiment=-1.0, attention=5.0)
    assert _holder().decide(context).action is TradeAction.BUY  # still accumulating near cost
    momentum = MomentumTrader("m", starting_cash=1_000.0, starting_coins=1_000.0, lookback=1, **COMMON)
    assert momentum.decide(_ctx(1.01, (1.0,), sentiment=-1.0, attention=5.0)).action is not TradeAction.SELL


# --- manipulators --------------------------------------------------------------------------------


def test_manipulators_ignore_sentiment_and_attention():
    def schedule(cls, **news):
        trader = cls("m", starting_cash=10_000.0, starting_coins=500.0, trade_probability=0.5, seed=3)
        return [trader.decide(_ctx(tick=t, **news)) for t in range(1, 40)]

    for cls in (PumpAndDump, WashTrader):
        neutral = schedule(cls)
        assert schedule(cls, sentiment=1.0, attention=5.0) == neutral
        assert schedule(cls, sentiment=-1.0, attention=5.0) == neutral
        manipulator = cls("m", trade_probability=0.5)
        assert manipulator.sentiment_pressure(_ctx(sentiment=1.0)) == 0.0
        assert manipulator.participation_probability(_ctx(attention=5.0)) == 0.5


# --- RNG and baseline ----------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_sentiment_never_adds_a_random_draw(strategy):
    neutral, newsy = _organic(strategy, trade_probability=0.6), _organic(strategy, trade_probability=0.6)
    _decisions(neutral, _random_contexts(sentiment=0.0))
    _decisions(newsy, _random_contexts())
    assert newsy._rng.getstate() == neutral._rng.getstate()


def test_the_participation_gate_draws_exactly_once_per_decision_whatever_the_attention():
    trader = MomentumTrader("m", trade_probability=0.3, seed=8)
    _decisions(trader, _random_contexts(n=500, attention=4.0))
    reference = random.Random(8)
    for _ in range(500):
        reference.random()
    assert trader._rng.getstate() == reference.getstate()


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_without_news_or_with_zero_sensitivity_decisions_are_unchanged(strategy):
    plain = [dataclasses.replace(c, sentiment=0.0) for c in _random_contexts()]
    legacy = [MarketContext(c.tick, c.price, c.price_history, c.total_supply) for c in plain]
    reference = _decisions(_organic(strategy, trade_probability=0.6), legacy)
    assert _decisions(_organic(strategy, trade_probability=0.6), plain) == reference
    deaf = _organic(strategy, trade_probability=0.6, sentiment_sensitivity=0.0)
    assert _decisions(deaf, _random_contexts()) == reference


def test_a_strategy_without_a_hook_ignores_sentiment_even_with_sensitivity():
    class Constant(TraderAgent):
        strategy_name = "constant"

        def _decide(self, context):
            return TradeDecision.hold("always")

    trader = Constant("c", sentiment_sensitivity=2.0, trade_probability=1.0)
    assert trader.sentiment_pressure(_ctx(sentiment=0.5)) == 1.0
    assert trader.decide(_ctx(sentiment=0.5)) == TradeDecision.hold("always")
