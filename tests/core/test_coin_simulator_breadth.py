"""Participation breadth inside the simulation (Phase 19, Step 14).

``organic_breadth`` is the one calculation; the simulator hands each
news-responding trader its own leave-self-out value of the previous completed
tick as ``crowd_breadth`` on a copy of the shared context. With every breadth
sensitivity 0 (arm A1) a run is bit-identical to the same run with the
observation off (A0); with retail's response on (A2b) retail's stream consumes
exactly the draws it always did, its participation gate never moves on its
own, and nothing but retail's side can differ first.
"""

from __future__ import annotations

import dataclasses
import random

import pytest
import yaml

from crypto_simulator.config.settings import DEFAULT_CONFIG_PATH, build_settings
from crypto_simulator.core.coin_simulator import CoinSimulator, organic_breadth
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.execution import TraderTrade
from crypto_simulator.core.traders.strategies import RetailTrader
from crypto_simulator.models.coin import Coin
from crypto_simulator.services.coin_simulation import DEMO_EVENTS, build_coin_simulator


def trade(trader_id, side, quantity, *, strategy="momentum", wash=False):
    action = TradeAction.BUY if side == "buy" else TradeAction.SELL
    return TraderTrade(trader_id, strategy, action, quantity, quantity, 1.0, quantity, wash=wash)


def settings(seed=0, events=None):
    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as handle:
        s = build_settings(yaml.safe_load(handle), DEFAULT_CONFIG_PATH)
    s = dataclasses.replace(s, simulation=dataclasses.replace(s.simulation, random_seed=seed))
    if events == "scheduled":
        s = dataclasses.replace(s, coin=dataclasses.replace(
            s.coin, events=dataclasses.replace(s.coin.events, scheduled=list(DEMO_EVENTS))))
    return s


def build(arm, mode="random_walk", *, seed=0, psychology=False, events=None, **extra):
    flags = {"A0": (False, False), "A1": (True, False), "A2b": (True, True)}[arm]
    return build_coin_simulator(settings(seed, events), pricing_mode=mode, psychology=psychology,
                                include_whales=(mode == "random_walk"),
                                breadth_observation=flags[0], breadth_response=flags[1], **extra)


def digest(sim, ticks):
    return repr((
        [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades, t.pool_state,
          t.event_state, t.psychology) for t in ticks],
        [(t.trader_id, t.wallet.cash, t.wallet.coins, t.wallet.average_cost, t._rng.getstate())
         for t in sim.traders],
        [(w.whale_id, w._rng.getstate()) for w in sim.whales],
        (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals(),
        sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
    ))


def capture(sim):
    """Record the context each trader was handed, per tick (test-only wrap)."""
    seen = []
    for trader in sim.traders:
        original = trader.decide

        def decide(ctx, _trader=trader, _original=original):
            seen.append((_trader.trader_id, ctx))
            return _original(ctx)

        trader.decide = decide
    return seen


# --- the one calculation ---------------------------------------------------------------


def test_breadth_counts_each_other_trader_once_by_net_side():
    trades = [trade("a", "buy", 5), trade("a", "buy", 1),  # a: one buyer, not two
              trade("b", "buy", 5), trade("b", "sell", 3),  # b nets to a buyer
              trade("c", "buy", 3), trade("c", "sell", 3),  # c nets to zero: neither side
              trade("d", "sell", 1)]
    assert organic_breadth(trades) == (2 - 1) / 3
    assert organic_breadth(trades, "a") == (1 - 1) / 2
    assert organic_breadth(trades, "d") == 1.0


def test_the_responder_is_left_out():
    trades = [trade("me", "buy", 100, strategy="retail"), trade("x", "sell", 1)]
    assert organic_breadth(trades, "me") == -1.0
    assert organic_breadth(trades) == 0.0


def test_wash_legs_and_manipulators_are_excluded():
    trades = [trade("w", "buy", 9, wash=True), trade("w", "sell", 9, wash=True),
              trade("p", "buy", 9, strategy="pump_and_dump"), trade("x", "sell", 1)]
    assert organic_breadth(trades) == -1.0


@pytest.mark.parametrize("trades,exclude", [([], None), ([trade("me", "buy", 1)], "me"),
                                            ([trade("w", "buy", 1, wash=True)], None)])
def test_no_other_active_trader_gives_zero(trades, exclude):
    assert organic_breadth(trades, exclude) == 0.0


def test_breadth_is_bounded_and_draws_nothing():
    state = random.getstate()
    rng = random.Random(1)
    for _ in range(200):
        trades = [trade(f"t{i}", rng.choice(("buy", "sell")), rng.random() + 0.01)
                  for i in range(rng.randint(0, 6))]
        assert -1.0 <= organic_breadth(trades) <= 1.0
    assert random.getstate() == state


# --- delivery: lag, leave-self-out, per trader, shared snapshot untouched --------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("arm", ["A1", "A2b"])
def test_each_trader_sees_only_the_previous_ticks_leave_self_out_breadth(mode, arm):
    sim = build(arm, mode, seed=10000, psychology=True)
    seen = capture(sim)
    ticks = sim.run(60)
    news_traders = {t.trader_id for t in sim.traders if t.responds_to_news}
    by_tick, i = [], 0
    per_tick = len(sim.traders)
    for tick_index in range(60):
        by_tick.append(seen[i:i + per_tick]); i += per_tick
    differs = False
    for tick_index, contexts in enumerate(by_tick):
        values = {}
        for trader_id, ctx in contexts:
            if trader_id not in news_traders:
                assert ctx.crowd_breadth is None
                continue
            expected = None if tick_index == 0 else organic_breadth(ticks[tick_index - 1].trader_trades, trader_id)
            assert ctx.crowd_breadth == expected
            values[trader_id] = ctx.crowd_breadth
        differs |= len(set(values.values())) > 1
    assert differs  # leave-self-out really is per trader


def test_the_shared_context_is_never_mutated_and_only_breadth_differs():
    sim = build("A2b", seed=20000)
    shared = []
    original = sim._market_context

    def market_context(*args):
        ctx = original(*args)
        shared.append(ctx)
        return ctx

    sim._market_context = market_context
    seen = capture(sim)
    sim.run(30)
    assert all(ctx.crowd_breadth is None for ctx in shared)
    per_tick = len(sim.traders)
    for tick_index, ctx in enumerate(shared):
        for _, view in seen[tick_index * per_tick:(tick_index + 1) * per_tick]:
            assert dataclasses.replace(view, crowd_breadth=None) == ctx


def test_whale_trades_never_reach_breadth():
    sim = build("A1", seed=30000)
    assert sim.whales
    seen = capture(sim)
    ticks = sim.run(80)
    assert any(t.whale_trades for t in ticks)
    retail = [ctx.crowd_breadth for tid, ctx in seen if tid == "retail-1"]
    for i in range(1, 80):
        assert retail[i] == organic_breadth(ticks[i - 1].trader_trades, "retail-1")


def test_manipulators_receive_no_breadth():
    sim = build_coin_simulator(settings(40000), pricing_mode="amm", include_whales=False,
                               scenario="pump_and_dump", breadth_observation=True, breadth_response=True)
    seen = capture(sim)
    sim.run(30)
    manipulators = {t.trader_id for t in sim.traders if not t.responds_to_news}
    assert manipulators
    assert all(ctx.crowd_breadth is None for tid, ctx in seen if tid in manipulators)


# --- configuration ---------------------------------------------------------------------


def test_a_response_without_observation_is_refused():
    with pytest.raises(ValueError, match="breadth_observation"):
        build_coin_simulator(settings(), breadth_observation=False, breadth_response=True)
    with pytest.raises(ValueError, match="breadth_observation"):
        CoinSimulator(Coin("X", "X", 1_000_000.0, 1.0), seed=0,
                      traders=[RetailTrader("r", breadth_direction_sensitivity=0.25)])
    with pytest.raises(ValueError, match="breadth_observation"):
        CoinSimulator(Coin("X", "X", 1_000_000.0, 1.0), seed=0, breadth_observation=1)


def test_only_retail_responds_and_step_7_stays_off():
    sim = build("A2b", psychology=True)
    for t in sim.traders:
        assert t.breadth_direction_sensitivity == (0.25 if t.strategy_name == "retail" else 0.0)
        assert t.crowd_sensitivity == 0.0 and t.crowd_direction_sensitivity == 0.0
    assert not sim.crowd_observation_enabled
    assert getattr(sim, "external_market", None) is None


# --- identity and invariance -----------------------------------------------------------


CASES = [(mode, psy, ev) for mode in ("random_walk", "amm") for psy in (False, True)
         for ev in (None, "scheduled")]


@pytest.mark.parametrize("mode,psychology,events", CASES)
@pytest.mark.parametrize("seed", [0, 50000])
def test_observation_alone_changes_nothing(mode, psychology, events, seed):
    runs = {}
    for arm in ("A0", "A1"):
        sim = build(arm, mode, seed=seed, psychology=psychology, events=events)
        runs[arm] = digest(sim, sim.run(120))
    assert runs["A0"] == runs["A1"]


class _Counting:
    """Delegates to the real stream and counts calls (test-only)."""

    def __init__(self, rng):
        self.rng, self.calls = rng, 0

    def random(self):
        self.calls += 1
        return self.rng.random()

    def getstate(self):
        return self.rng.getstate()


@pytest.mark.parametrize("mode,psychology,events", CASES)
def test_the_response_consumes_no_extra_draw_and_moves_no_gate_on_its_own(mode, psychology, events):
    """Zero extra draws: in every arm, at every tick, retail draws exactly
    once when inactive and twice when active. Its stream and gate are
    identical in A1 and A2b until its participation probability first
    differs — which, with psychology on, prices can legitimately cause
    once retail's side has moved them; with psychology off the probability
    never differs, so the gate sequence is identical throughout."""
    sims = {arm: build(arm, mode, seed=60000, psychology=psychology, events=events) for arm in ("A1", "A2b")}
    streams = lambda sim: ([t._rng.getstate() for t in sim.traders] + [w._rng.getstate() for w in sim.whales]
                           + [sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate()])
    assert streams(sims["A1"]) == streams(sims["A2b"])
    logs = {arm: [] for arm in sims}
    for arm, sim in sims.items():
        retail = next(t for t in sim.traders if t.strategy_name == "retail")
        retail._rng = counter = _Counting(retail._rng)
        original = retail.decide

        def decide(ctx, _retail=retail, _original=original, _log=logs[arm], _counter=counter):
            before = _counter.calls
            p = _retail.participation_probability(ctx)
            d = _original(ctx)
            active = d.reason != "inactive this tick"
            assert _counter.calls - before == (2 if active else 1)  # never an extra draw
            _log.append((p, active, _counter.getstate()))
            return d

        retail.decide = decide
        sim.run(120)
    first_p = next((i for i, (x, y) in enumerate(zip(logs["A1"], logs["A2b"])) if x[0] != y[0]), None)
    if not psychology:
        assert first_p is None
    horizon = len(logs["A1"]) if first_p is None else first_p
    for (p1, g1, s1), (p2, g2, s2) in zip(logs["A1"][:horizon], logs["A2b"][:horizon]):
        assert g1 == g2 and s1 == s2
    a1 = [t.trader_trades for t in sims["A1"].history]
    a2 = [t.trader_trades for t in sims["A2b"].history]
    assert a1 != a2  # the response is live, so the checks above are not vacuous
    first = next(i for i, (x, y) in enumerate(zip(a1, a2)) if x != y)
    assert [(f.trader_id, f.side) for f in a1[first] if f.strategy != "retail"] == \
           [(f.trader_id, f.side) for f in a2[first] if f.strategy != "retail"]  # retail moved first
