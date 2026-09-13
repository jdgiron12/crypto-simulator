"""Whale behavior transitions inside the simulation (Phase 8, Step 4).

Transitions are driven from outside the whale — nothing in the simulator
triggers one — so these check that a whale moved between behaviors mid-run
keeps trading correctly, keeps its pacing, and leaves accounting intact,
with traders, news, manipulators and psychology all around it.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

import crypto_simulator.core.whale as whale_module
from crypto_simulator.config import WhaleSettings, get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale, WhaleBehavior
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin

BEHAVIORS = ("neutral", "accumulate", "distribute")


class _Observed(Whale):
    """Records the price the simulator offered and the allocation either
    side of each trade, so the non-crossing invariant can be checked at
    the price the fill actually happened at rather than at a tick price
    the whale never saw."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []

    def maybe_trade(self, total_supply, *, price=None, reserve=None):
        before = self.allocation(price) if price is not None else None
        behavior = self.behavior
        trade = super().maybe_trade(total_supply, price=price, reserve=reserve)
        self.observations.append((price, behavior, before, self.allocation(price) if price else None, trade))
        return trade


def _whale(whale_id="w", behavior="neutral", cash=500_000.0, coins=100_000.0, seed=21, **kwargs):
    kwargs.setdefault("activity_probability", 0.6)
    kwargs.setdefault("max_trade_fraction", 0.002)
    return Whale(whale_id, coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _sim(whales, traders=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0, **kwargs)


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


def _in_module_callers(tree, name):
    """Which functions in the whale module call ``name`` on self."""
    callers = set()
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name:
                callers.add(function.name)
    return callers


def _balances_ok(sim):
    wallets = [sim.reserve, *(t.wallet for t in sim.traders), *(w.wallet for w in sim.whales if w.funded)]
    return all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)


def _conserved(before, after):
    return all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(after, before))


def _run_with_schedule(sim, ticks, schedule):
    """Run ``ticks`` ticks, applying ``{tick: {whale_id: behavior}}`` before
    each one. Returns the per-tick whale trades."""
    out = []
    for tick in range(1, ticks + 1):
        for whale_id, behavior in schedule.get(tick, {}).items():
            next(w for w in sim.whales if w.whale_id == whale_id).set_behavior(behavior)
        out.append(sim.step().whale_trades)
    return out


# --- transitions drive direction inside the loop ---------------------------------------------------


def test_a_transition_mid_run_changes_the_side_the_whale_trades():
    whale = _whale("w", "accumulate", activity_probability=1.0)
    sim = _sim([whale])
    per_tick = _run_with_schedule(sim, 60, {31: {"w": "distribute"}})
    early = {t.side for trades in per_tick[:30] for t in trades}
    late = {t.side for trades in per_tick[30:] for t in trades}
    assert early == {"buy"} and late == {"sell"}
    assert _balances_ok(sim)


def test_a_long_transition_sequence_runs_cleanly_through_the_simulator():
    whale = _whale("w", "neutral", activity_probability=1.0)
    sim = _sim([whale], traders=_all_five())
    totals = sim.accounting_totals()
    schedule = {1: {"w": "accumulate"}, 41: {"w": "distribute"}, 81: {"w": "neutral"},
                121: {"w": "accumulate"}}
    per_tick = _run_with_schedule(sim, 160, schedule)
    windows = [{t.side for trades in per_tick[a:b] for t in trades}
               for a, b in ((0, 40), (40, 80), (80, 120), (120, 160))]
    assert windows[0] == {"buy"} and windows[1] == {"sell"} and windows[3] == {"buy"}
    assert windows[2] == {"buy", "sell"}  # neutral again
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert whale.behavior is WhaleBehavior.ACCUMULATE


def test_a_transition_before_any_trade_takes_effect_from_the_first_tick():
    whale = _whale("w", "neutral", activity_probability=1.0)
    sim = _sim([whale])
    whale.set_behavior("distribute")
    ticks = sim.run(20)
    assert {t.side for tick in ticks for t in tick.whale_trades} == {"sell"}


# --- scheduling survives a transition mid-simulation -------------------------------------------------


def test_a_transition_during_cooldown_does_not_let_the_whale_trade_early():
    whale = _whale("w", "accumulate", activity_probability=1.0, cooldown_ticks=4)
    sim = _sim([whale])
    per_tick = _run_with_schedule(sim, 30, {2: {"w": "distribute"}, 3: {"w": "neutral"},
                                            4: {"w": "accumulate"}})
    traded = [i + 1 for i, trades in enumerate(per_tick) if trades]
    assert traded == list(range(1, 31, 5))  # still one trade every five ticks


def test_a_transition_during_the_trade_interval_does_not_let_the_whale_trade_early():
    whale = _whale("w", "accumulate", activity_probability=1.0, min_trade_interval_ticks=6)
    sim = _sim([whale])
    schedule = {tick: {"w": BEHAVIORS[tick % 3]} for tick in range(2, 40)}  # churn every tick
    per_tick = _run_with_schedule(sim, 40, schedule)
    traded = [i + 1 for i, trades in enumerate(per_tick) if trades]
    assert traded == list(range(1, 41, 7))


# --- target allocation still rules --------------------------------------------------------------------


def test_a_transitioning_whale_still_never_crosses_its_target():
    whale = _Observed("w", 100_000.0, starting_cash=500_000.0, behavior="accumulate",
                      target_coin_fraction=0.5, activity_probability=0.7, max_trade_fraction=0.01, seed=5)
    sim = _sim([whale], traders=_all_five())
    for tick in range(1, 301):
        if tick % 40 == 0:
            whale.set_behavior("distribute" if whale.behavior is WhaleBehavior.ACCUMULATE else "accumulate")
        sim.step()
    filled = 0
    for _price, behavior, before, after, trade in whale.observations:
        if trade is None:
            assert before == after
            continue
        filled += 1
        if behavior is WhaleBehavior.ACCUMULATE:
            assert before.coin_fraction < after.coin_fraction <= 0.5 + TARGET_DEAD_ZONE
        else:
            assert before.coin_fraction > after.coin_fraction >= 0.5 - TARGET_DEAD_ZONE
    assert filled > 20 and _balances_ok(sim)
    # Both behaviors really did get a turn.
    assert {b for _p, b, _bf, _af, t in whale.observations if t is not None} == {
        WhaleBehavior.ACCUMULATE, WhaleBehavior.DISTRIBUTE}


def test_a_dormant_target_does_not_stop_a_whale_that_became_neutral():
    whale = Whale("w", 25_000.0, starting_cash=50_000.0, behavior="accumulate", target_coin_fraction=0.5,
                  activity_probability=1.0, max_trade_fraction=0.0005, seed=6)
    sim = _sim([whale])
    assert whale.allocation(sim.current_price).at_target
    assert all(t.whale_trades == () for t in sim.run(10))  # holding on the target
    whale.set_behavior("neutral")
    ticks = sim.run(40)
    assert {t.side for tick in ticks for t in tick.whale_trades} == {"buy", "sell"}
    assert whale.target_coin_fraction == 0.5


# --- determinism -------------------------------------------------------------------------------------


def test_the_same_transition_schedule_replays_identically():
    def run():
        whales = [_whale("a", "accumulate", target_coin_fraction=0.6, seed=21),
                  _whale("b", "distribute", cash=0.0, coins=150_000.0, target_coin_fraction=0.2,
                         seed=22, min_trade_interval_ticks=3)]
        sim = _sim(whales, traders=_all_five(), events=_news())
        per_tick = _run_with_schedule(sim, 200, {50: {"a": "neutral"}, 90: {"a": "distribute", "b": "accumulate"},
                                                 150: {"a": "accumulate", "b": "neutral"}})
        return (per_tick, [t.price for t in sim.history], [w.state() for w in sim.whales],
                [w._rng.getstate() for w in sim.whales], sim.accounting_totals())

    assert run() == run()


def test_different_transition_schedules_can_diverge():
    def run(switch_at):
        whale = _whale("w", "accumulate", activity_probability=1.0)
        sim = _sim([whale], traders=_all_five())
        _run_with_schedule(sim, 150, {switch_at: {"w": "distribute"}})
        return [t.price for t in sim.history]

    assert run(20) != run(100)


def test_a_run_with_no_transitions_matches_a_plain_step_3_run():
    def view(transition):
        whale = _whale("w", "accumulate", target_coin_fraction=0.6, cooldown_ticks=2,
                       min_trade_interval_ticks=3, seed=21)
        sim = _sim([whale], traders=_all_five(), events=_news(), psychology=True)
        if transition:
            whale.set_behavior("accumulate")  # a no-op transition to its current state
        ticks = sim.run(200)
        return ([(t.price, t.volume, t.whale_trades, t.trader_trades) for t in ticks],
                whale.state(), whale._rng.getstate(), sim.accounting_totals())

    assert view(False) == view(True)


# --- accounting ------------------------------------------------------------------------------------


def test_transitions_during_a_long_run_conserve_coins_and_cash():
    whales = [_whale("a", "accumulate", target_coin_fraction=0.7, seed=31),
              _whale("b", "distribute", cash=20_000.0, coins=150_000.0, target_coin_fraction=0.3, seed=32),
              _whale("c", "neutral", seed=33, cooldown_ticks=2, min_trade_interval_ticks=2),
              Whale("legacy", 30_000.0, activity_probability=0.4, seed=34)]
    sim = _sim(whales, traders=_all_five())
    totals = sim.accounting_totals()
    for tick in range(1, 501):
        for i, whale in enumerate(whales[:3]):
            if tick % (11 + i) == 0:
                whale.set_behavior(BEHAVIORS[(tick + i) % 3])
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    assert sum(len(t.whale_trades) for t in sim.history) > 100


def test_an_unfunded_whale_in_the_simulation_still_refuses_a_directional_behavior():
    legacy = Whale("legacy", 50_000.0, activity_probability=0.5, seed=21)
    sim = _sim([legacy], traders=_all_five())
    sim.run(50)
    with pytest.raises(ValueError, match="unfunded whale cannot become"):
        legacy.set_behavior("accumulate")
    assert legacy.behavior is WhaleBehavior.NEUTRAL and not legacy.funded
    before = [t.price for t in sim.history]
    sim.run(50)
    assert [t.price for t in sim.history][:50] == before  # history untouched by the rejection


# --- psychology, events, manipulation ------------------------------------------------------------------


@pytest.mark.parametrize("psychology", [False, True])
def test_transitions_are_unaffected_by_psychology_and_events(psychology):
    def run(events):
        whale = _whale("w", "neutral", activity_probability=1.0, seed=21)
        sim = _sim([whale], events=events, psychology=psychology)
        per_tick = _run_with_schedule(sim, 80, {21: {"w": "accumulate"}, 51: {"w": "distribute"}})
        return [{t.side for t in trades} for trades in per_tick], whale._rng.getstate(), whale.behavior

    plain, newsy = run(None), run(_news())
    assert plain[1] == newsy[1] and plain[2] is newsy[2] is WhaleBehavior.DISTRIBUTE
    # Sides are decided by the behavior alone, whatever the news.
    assert all(sides <= {"buy"} for sides in plain[0][20:50])
    assert all(sides <= {"sell"} for sides in plain[0][50:])
    assert all(sides <= {"sell"} for sides in newsy[0][50:])


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_a_transitioning_whale_runs_alongside_a_manipulation_scenario(scenario):
    settings = get_settings()
    whales = [WhaleSettings("w", 20_000.0, activity_probability=0.5, max_trade_fraction=0.005,
                            starting_cash=200_000.0, behavior="accumulate", target_coin_fraction=0.5)]
    sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)), scenario=scenario)
    (whale,) = sim.whales
    totals = sim.accounting_totals()
    per_tick = _run_with_schedule(sim, 80, {41: {"w": "distribute"}})
    assert {t.side for trades in per_tick[:40] for t in trades} <= {"buy"}
    assert {t.side for trades in per_tick[40:] for t in trades} <= {"sell"}
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert not any(f.trader_id == "w" for t in sim.history for f in t.trader_trades)


def test_the_whale_module_still_reads_no_psychology_news_or_manipulation():
    source = Path(whale_module.__file__).read_text()
    tree = ast.parse(source)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert imported <= {"__future__", "math", "random", "dataclasses", "enum",
                        "crypto_simulator.core.traders.base", "crypto_simulator.core.traders.execution",
                        "crypto_simulator.models.wallet"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    forbidden = ("fear", "fomo", "conviction", "uncertainty", "sentiment", "momentum",
                 "social", "psychology", "event", "news", "volatility", "manipul")
    assert not any(word in name.lower() for name in names for word in forbidden)


def test_a_whale_without_a_cycle_never_transitions_on_its_own():
    """Transitions come from outside. A long run with traders, news and
    psychology leaves every uncycled whale exactly where it started, and
    the module's only in-module caller of ``set_behavior`` is the Step 6
    cycle clock in ``maybe_trade`` — which reads no market input."""
    whales = [_whale("a", "accumulate", target_coin_fraction=0.6, seed=31),
              _whale("b", "distribute", cash=0.0, coins=120_000.0, target_coin_fraction=0.2, seed=32),
              _whale("c", "neutral", seed=33)]
    sim = _sim(whales, traders=_all_five(), events=_news(), psychology=True)
    sim.run(300)
    assert all(w.cycle is None for w in sim.whales)
    assert [w.behavior for w in sim.whales] == [WhaleBehavior.ACCUMULATE, WhaleBehavior.DISTRIBUTE,
                                                WhaleBehavior.NEUTRAL]
    tree = ast.parse(Path(whale_module.__file__).read_text())
    assert _in_module_callers(tree, "set_behavior") == {"maybe_trade"}
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert "set_behavior" in defined


# --- AMM -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("behavior", BEHAVIORS)
def test_amm_mode_still_rejects_whales_in_every_behavior(behavior):
    whale = _whale("w", behavior, cash=100_000.0, coins=1_000.0)
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[whale], reserve_cash=2_000_000.0, pricing_mode="amm")


def test_a_transition_cannot_sneak_a_whale_into_amm_mode():
    whale = _whale("w", "neutral")
    whale.set_behavior("accumulate")
    whale.set_behavior("neutral")
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[whale], reserve_cash=2_000_000.0, pricing_mode="amm")
    assert build_coin_simulator(get_settings(), pricing_mode="amm", include_whales=False).whales == []
