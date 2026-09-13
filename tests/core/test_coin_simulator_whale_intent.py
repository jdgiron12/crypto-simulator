"""Whale intent strength inside the simulation (Phase 8, Step 5).

Intent scales what a directional whale asks for; the target, its balances
and the reserve still decide what it gets. These run that through the
simulation loop with traders, news, manipulators and psychology around
it, none of which the whale reads.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

import crypto_simulator.core.whale as whale_module
from crypto_simulator.config import WhaleSettings, get_settings
from crypto_simulator.config.settings import DEFAULT_CONFIG_PATH, build_settings, load_config
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale, WhaleBehavior
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin

BEHAVIORS = ("neutral", "accumulate", "distribute")


class _Observed(Whale):
    """Records the price offered and the allocation either side of each
    trade, so invariants can be checked at the fill's own price."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []

    def maybe_trade(self, total_supply, *, price=None, reserve=None):
        before = self.allocation(price) if price is not None else None
        behavior, intent = self.behavior, self.intent_strength
        trade = super().maybe_trade(total_supply, price=price, reserve=reserve)
        after = self.allocation(price) if price is not None else None
        self.observations.append((price, behavior, intent, before, after, trade))
        return trade


def _whale(whale_id="w", behavior="accumulate", cash=400_000.0, coins=60_000.0, seed=21, observed=False,
           **kwargs):
    kwargs.setdefault("activity_probability", 0.6)
    kwargs.setdefault("max_trade_fraction", 0.005)
    cls = _Observed if observed else Whale
    return cls(whale_id, coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


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


# --- intent drives size inside the loop ----------------------------------------------------------


@pytest.mark.parametrize("intent", [0.5, 2.0])
def test_intent_scales_what_the_whale_asks_for_run_against_the_default(intent):
    """Same seed and the same market: every fill is the default run's fill
    scaled, until a cap binds."""
    def run(value):
        whale = _whale("w", "accumulate", cash=1e9, coins=0.0, activity_probability=1.0,
                       min_trade_fraction=0.002, max_trade_fraction=0.002, intent_strength=value)
        ticks = _sim([whale]).run(30)
        return [t.quantity for tick in ticks for t in tick.whale_trades]

    base, scaled = run(1.0), run(intent)
    assert len(base) == len(scaled) == 30
    assert scaled == pytest.approx([q * intent for q in base])


def test_a_stronger_whale_moves_price_further_over_the_same_ticks():
    def final_price(intent):
        whale = _whale("w", "accumulate", cash=1e9, coins=0.0, activity_probability=1.0,
                       intent_strength=intent)
        return _sim([whale]).run(60)[-1].price

    assert final_price(2.0) > final_price(1.0) > final_price(0.5)


def test_zero_intent_leaves_the_market_exactly_as_if_the_whale_were_absent():
    whale = _whale("w", "accumulate", intent_strength=0.0, activity_probability=1.0)
    with_whale = _sim([whale], traders=_all_five()).run(120)
    without = _sim([], traders=_all_five()).run(120)
    assert [t.price for t in with_whale] == [t.price for t in without]
    assert all(t.whale_trades == () for t in with_whale)
    assert (whale.wallet.cash, whale.wallet.coins) == (400_000.0, 60_000.0)


def test_neutral_ignores_intent_inside_the_simulation():
    def run(intent):
        whale = _whale("w", "neutral", cash=1e9, coins=200_000.0, intent_strength=intent,
                       activity_probability=1.0)
        ticks = _sim([whale], traders=_all_five()).run(120)
        return [(t.price, t.whale_trades) for t in ticks], whale._rng.getstate()

    assert run(0.0) == run(1.0) == run(2.0)


# --- constraints still bind -------------------------------------------------------------------------


def test_a_strong_whale_still_never_crosses_its_target():
    whale = _whale("w", "accumulate", cash=600_000.0, coins=100_000.0, target_coin_fraction=0.5,
                   intent_strength=2.0, max_trade_fraction=0.02, activity_probability=0.8, observed=True)
    sim = _sim([whale], traders=_all_five())
    sim.run(300)
    filled = 0
    for _price, behavior, intent, before, after, trade in whale.observations:
        if trade is None:
            assert before == after
            continue
        filled += 1
        assert intent == 2.0 and behavior is WhaleBehavior.ACCUMULATE
        assert before.coin_fraction < after.coin_fraction <= 0.5 + TARGET_DEAD_ZONE
    assert filled > 10 and _balances_ok(sim)


def test_strong_intent_cannot_drain_the_reserve_or_the_wallet():
    whale = _whale("w", "accumulate", cash=1e9, coins=0.0, intent_strength=2.0,
                   max_trade_fraction=0.5, activity_probability=1.0)
    sim = _sim([whale], traders=_all_five())
    totals = sim.accounting_totals()
    for _ in range(200):
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    assert sim.reserve.coins >= 0.0


# --- runtime changes ---------------------------------------------------------------------------------


def test_changing_the_intent_mid_run_changes_the_size_not_the_side():
    whale = _whale("w", "accumulate", cash=1e9, coins=0.0, activity_probability=1.0,
                   min_trade_fraction=0.002, max_trade_fraction=0.002, observed=True)
    sim = _sim([whale])
    for tick in range(1, 61):
        if tick == 31:
            assert whale.set_intent_strength(2.0) == 1.0
        sim.step()
    sizes = [t.quantity for tick in sim.history for t in tick.whale_trades]
    assert {t.side for tick in sim.history for t in tick.whale_trades} == {"buy"}
    assert all(b == pytest.approx(2.0 * a) for a, b in zip(sizes[:30], sizes[30:]))


def test_intent_and_behavior_transitions_compose_in_the_simulation():
    whale = _whale("w", "neutral", cash=1e9, coins=200_000.0, activity_probability=1.0, observed=True)
    sim = _sim([whale], traders=_all_five())
    totals = sim.accounting_totals()
    schedule = {1: ("accumulate", 2.0), 41: ("distribute", 0.5), 81: ("neutral", 1.0),
                121: ("accumulate", 1.5)}
    for tick in range(1, 161):
        if tick in schedule:
            behavior, intent = schedule[tick]
            whale.set_behavior(behavior)
            whale.set_intent_strength(intent)
        sim.step()
    windows = [{t.side for tick in sim.history[a:b] for t in tick.whale_trades}
               for a, b in ((0, 40), (40, 80), (80, 120), (120, 160))]
    assert windows[0] == {"buy"} and windows[1] == {"sell"} and windows[3] == {"buy"}
    assert windows[2] == {"buy", "sell"}
    assert whale.intent_strength == 1.5 and whale.behavior is WhaleBehavior.ACCUMULATE
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)


def test_intent_survives_a_transition_through_neutral_inside_the_simulation():
    whale = _whale("w", "accumulate", cash=1e9, coins=1e6, intent_strength=2.0, activity_probability=1.0)
    sim = _sim([whale])
    sim.run(10)
    whale.set_behavior("neutral")
    sim.run(10)
    assert whale.intent_strength == 2.0
    whale.set_behavior("accumulate")
    sim.run(10)
    assert whale.intent_strength == 2.0


# --- determinism -----------------------------------------------------------------------------------------


def test_the_same_intent_schedule_replays_identically():
    def run():
        whales = [_whale("a", "accumulate", target_coin_fraction=0.6, seed=21, intent_strength=1.5),
                  _whale("b", "distribute", cash=0.0, coins=150_000.0, target_coin_fraction=0.2,
                         seed=22, min_trade_interval_ticks=3, intent_strength=0.5)]
        sim = _sim(whales, traders=_all_five(), events=_news())
        for tick in range(1, 201):
            if tick % 50 == 0:
                whales[0].set_intent_strength(0.5 * ((tick // 50) % 4))
                whales[1].set_behavior(BEHAVIORS[(tick // 50) % 3])
            sim.step()
        return ([(t.price, t.whale_trades, t.trader_trades) for t in sim.history],
                [(w.state(), w.intent_strength, w.interval_remaining) for w in sim.whales],
                [w._rng.getstate() for w in sim.whales], sim.accounting_totals())

    assert run() == run()


def test_a_default_intent_run_matches_one_that_never_mentions_intent():
    def view(explicit):
        kwargs = {"intent_strength": 1.0} if explicit else {}
        whale = _whale("w", "accumulate", target_coin_fraction=0.6, cooldown_ticks=2,
                       min_trade_interval_ticks=3, seed=21, **kwargs)
        sim = _sim([whale], traders=_all_five(), events=_news(), psychology=True)
        ticks = sim.run(200)
        return ([(t.price, t.volume, t.whale_trades, t.trader_trades) for t in ticks],
                whale.state(), whale._rng.getstate(), sim.accounting_totals())

    assert view(False) == view(True)


# --- accounting -------------------------------------------------------------------------------------------


def test_a_long_run_with_mixed_intents_conserves_coins_and_cash():
    whales = [_whale("a", "accumulate", target_coin_fraction=0.7, seed=31, intent_strength=2.0),
              _whale("b", "distribute", cash=20_000.0, coins=150_000.0, target_coin_fraction=0.3,
                     seed=32, intent_strength=0.25),
              _whale("c", "neutral", seed=33, cooldown_ticks=2, intent_strength=1.5),
              Whale("legacy", 30_000.0, activity_probability=0.4, seed=34, intent_strength=2.0)]
    sim = _sim(whales, traders=_all_five())
    totals = sim.accounting_totals()
    for tick in range(1, 501):
        for i, whale in enumerate(whales[:3]):
            if tick % (13 + i) == 0:
                whale.set_intent_strength(((tick + i) % 5) * 0.5)
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    assert sum(len(t.whale_trades) for t in sim.history) > 100


# --- psychology, events, manipulation, isolation --------------------------------------------------------------


@pytest.mark.parametrize("psychology", [False, True])
def test_intent_is_untouched_by_psychology_and_events(psychology):
    def run(events):
        whale = _whale("w", "accumulate", cash=1e9, coins=0.0, intent_strength=1.5,
                       activity_probability=1.0, seed=21)
        sim = _sim([whale], events=events, psychology=psychology)
        sim.run(100)
        return whale.intent_strength, whale._rng.getstate(), whale.behavior

    assert run(None) == run(_news())
    assert run(None)[0] == 1.5  # nothing adjusted it


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_a_leaning_whale_runs_alongside_a_manipulation_scenario(scenario):
    settings = get_settings()
    whales = [WhaleSettings("w", 20_000.0, activity_probability=0.5, max_trade_fraction=0.005,
                            starting_cash=200_000.0, behavior="accumulate", target_coin_fraction=0.5,
                            intent_strength=2.0)]
    sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)), scenario=scenario)
    (whale,) = sim.whales
    assert whale.intent_strength == 2.0
    totals = sim.accounting_totals()
    ticks = sim.run(80)
    assert {t.side for tick in ticks for t in tick.whale_trades} <= {"buy"}
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert not any(f.trader_id == "w" for t in ticks for f in t.trader_trades)


def test_the_whale_module_still_reads_no_psychology_news_or_manipulation():
    tree = ast.parse(Path(whale_module.__file__).read_text())
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


def test_nothing_adjusts_intent_or_behavior_on_its_own():
    """Intent is never adjusted in-module at all, and behavior only by the
    Step 6 cycle clock — never in response to anything in the market."""
    tree = ast.parse(Path(whale_module.__file__).read_text())
    assert _in_module_callers(tree, "set_intent_strength") == set()
    assert _in_module_callers(tree, "set_behavior") == {"maybe_trade"}
    whales = [_whale("a", "accumulate", target_coin_fraction=0.6, seed=31, intent_strength=0.5),
              _whale("b", "distribute", cash=0.0, coins=120_000.0, target_coin_fraction=0.2, seed=32,
                     intent_strength=2.0)]
    sim = _sim(whales, traders=_all_five(), events=_news(), psychology=True)
    sim.run(300)
    assert [w.intent_strength for w in sim.whales] == [0.5, 2.0]
    assert [w.behavior for w in sim.whales] == [WhaleBehavior.ACCUMULATE, WhaleBehavior.DISTRIBUTE]


# --- AMM ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("intent", [0.0, 1.0, 2.0])
def test_amm_mode_still_rejects_whales_at_every_intent(intent):
    whale = _whale("w", "accumulate", cash=100_000.0, coins=1_000.0, intent_strength=intent)
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[whale], reserve_cash=2_000_000.0, pricing_mode="amm")


def test_intent_in_the_config_does_not_make_amm_accept_whales():
    settings = get_settings()
    whales = [WhaleSettings("w", 0.0, starting_cash=1_000.0, behavior="accumulate", intent_strength=2.0)]
    tweaked = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales))
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        build_coin_simulator(tweaked, pricing_mode="amm")
    assert build_coin_simulator(tweaked, pricing_mode="amm", include_whales=False).whales == []


# --- configuration -------------------------------------------------------------------------------------------------


def test_the_default_config_leaves_intent_at_one():
    settings = get_settings()
    (whale_cfg,) = settings.coin.whales
    assert whale_cfg.intent_strength == 1.0
    (whale,) = build_coin_simulator(settings).whales
    assert whale.intent_strength == 1.0


def test_intent_is_parsed_from_config_and_reaches_the_whale():
    raw = load_config()
    raw["coin"]["whales"] = [{"id": "w", "holdings": 0.0, "starting_cash": 100_000.0,
                              "behavior": "accumulate", "target_coin_fraction": 0.4,
                              "intent_strength": 1.75}]
    settings = build_settings(raw, DEFAULT_CONFIG_PATH)
    assert settings.coin.whales == [WhaleSettings("w", 0.0, starting_cash=100_000.0, behavior="accumulate",
                                                  target_coin_fraction=0.4, intent_strength=1.75)]
    (whale,) = build_coin_simulator(settings).whales
    assert whale.intent_strength == 1.75


def test_an_invalid_configured_intent_is_rejected_by_the_builder():
    settings = get_settings()
    for bad in (-0.5, 2.5, True, "1.0"):
        whales = [WhaleSettings("w", 0.0, starting_cash=1_000.0, intent_strength=bad)]
        with pytest.raises(ValueError, match="intent_strength"):
            build_coin_simulator(
                dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)))


def test_an_explicit_default_matches_an_omitted_setting_end_to_end():
    settings = get_settings()
    explicit = dataclasses.replace(settings.coin.whales[0], intent_strength=1.0)
    same = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=[explicit]))

    def view(s):
        return [(t.price, t.volume, t.whale_trades, t.trader_trades) for t in build_coin_simulator(s).run(200)]

    assert view(same) == view(settings)
