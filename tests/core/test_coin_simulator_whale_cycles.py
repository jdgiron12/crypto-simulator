"""Cycling whales inside the simulation (Phase 8, Step 6).

The cycle clock runs off the whale's own tick count, so these check it
keeps time inside the simulation loop — with traders, news, manipulators
and psychology around it, none of which it reads — and that everything
Steps 1-5 established still holds inside each phase.
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
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale, WhaleBehavior, WhalePhase
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin

CYCLE = [{"behavior": "accumulate", "duration": 10}, {"behavior": "neutral", "duration": 5},
         {"behavior": "distribute", "duration": 10}, {"behavior": "neutral", "duration": 5}]


class _Observed(Whale):
    """Records the phase in force and the allocation either side of each
    tick, so invariants can be checked against the fill's own price and
    the phase it actually ran under."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []

    def maybe_trade(self, total_supply, *, price=None, reserve=None):
        phase = self.cycle_state()
        before = self.allocation(price) if price is not None else None
        trade = super().maybe_trade(total_supply, price=price, reserve=reserve)
        after = self.allocation(price) if price is not None else None
        self.observations.append((price, phase, before, after, trade))
        return trade


def _whale(whale_id="w", cycle=CYCLE, cash=400_000.0, coins=60_000.0, seed=21, observed=False, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.002)
    cls = _Observed if observed else Whale
    return cls(whale_id, coins, starting_cash=cash, seed=seed, cycle=cycle, **kwargs)


def _sim(whales, traders=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0, **kwargs)


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


def _balances_ok(sim):
    wallets = [sim.reserve, *(t.wallet for t in sim.traders), *(w.wallet for w in sim.whales if w.funded)]
    return all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)


def _conserved(before, after):
    return all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(after, before))


def _sides_per_tick(sim, ticks, whale_id="w"):
    out = []
    for _ in range(ticks):
        tick = sim.step()
        out.append({t.side for t in tick.whale_trades if t.whale_id == whale_id})
    return out


# --- the clock keeps time inside the loop --------------------------------------------------------


def test_a_cycling_whale_trades_the_phase_it_is_in():
    whale = _whale(cash=1e9, coins=200_000.0)
    sim = _sim([whale])
    sides = _sides_per_tick(sim, 60)
    for start in (0, 30):  # two full passes through the 30-tick cycle
        assert all(s == {"buy"} for s in sides[start:start + 10])
        assert all(s <= {"buy", "sell"} for s in sides[start + 10:start + 15])
        assert all(s == {"sell"} for s in sides[start + 15:start + 25])
    assert whale.cycle_state().phase_index == 0 and whale.cycle_state().phase_elapsed == 0


def test_phase_boundaries_land_on_exact_ticks():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 3},
                          {"behavior": "distribute", "duration": 3}], cash=1e9, coins=200_000.0)
    sim = _sim([whale])
    sides = _sides_per_tick(sim, 12)
    assert sides == [{"buy"}] * 3 + [{"sell"}] * 3 + [{"buy"}] * 3 + [{"sell"}] * 3


def test_the_clock_runs_on_ticks_the_whale_sits_out():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 4},
                          {"behavior": "distribute", "duration": 4}],
                   cash=1e9, coins=200_000.0, cooldown_ticks=1)
    sim = _sim([whale])
    sides = _sides_per_tick(sim, 16)
    # Paced to every other tick, but the phases still turn over on schedule.
    assert sides == [{"buy"}, set(), {"buy"}, set(), {"sell"}, set(), {"sell"}, set()] * 2


# --- Steps 1-5 still hold inside each phase --------------------------------------------------------


def test_a_cycling_whale_never_crosses_its_target_in_any_phase():
    whale = _whale(cash=600_000.0, coins=100_000.0, target_coin_fraction=0.5,
                   max_trade_fraction=0.02, activity_probability=0.8, intent_strength=1.5,
                   observed=True)
    sim = _sim([whale], traders=_all_five())
    sim.run(400)
    filled = 0
    for _price, phase, before, after, trade in whale.observations:
        if trade is None:
            assert before == after
            continue
        filled += 1
        if phase.behavior is WhaleBehavior.ACCUMULATE:
            assert before.coin_fraction < after.coin_fraction <= 0.5 + TARGET_DEAD_ZONE
        elif phase.behavior is WhaleBehavior.DISTRIBUTE:
            assert before.coin_fraction > after.coin_fraction >= 0.5 - TARGET_DEAD_ZONE
    assert filled > 20 and _balances_ok(sim)
    seen = {o[1].behavior for o in whale.observations if o[4] is not None}
    assert seen == {WhaleBehavior.ACCUMULATE, WhaleBehavior.NEUTRAL, WhaleBehavior.DISTRIBUTE}


def test_target_and_intent_survive_every_phase_in_a_long_run():
    whale = _whale(cash=600_000.0, coins=100_000.0, target_coin_fraction=0.45, intent_strength=1.8)
    sim = _sim([whale], traders=_all_five())
    for _ in range(400):
        sim.step()
        assert whale.target_coin_fraction == 0.45 and whale.intent_strength == 1.8


def test_scheduling_still_paces_a_cycling_whale_in_the_simulation():
    whale = _whale(cycle=[{"behavior": "accumulate", "duration": 4},
                          {"behavior": "distribute", "duration": 4}],
                   cash=1e9, coins=200_000.0, cooldown_ticks=2, min_trade_interval_ticks=4)
    sim = _sim([whale])
    sides = _sides_per_tick(sim, 40)
    traded = [i for i, s in enumerate(sides) if s]
    assert traded == list(range(0, 40, 5))


def test_a_cycle_places_no_trade_at_a_phase_boundary():
    whale = _whale(activity_probability=0.0, cash=400_000.0, coins=60_000.0)
    sim = _sim([whale], traders=_all_five())
    totals = sim.accounting_totals()
    ticks = sim.run(120)
    assert all(t.whale_trades == () for t in ticks)
    assert (whale.wallet.cash, whale.wallet.coins) == (400_000.0, 60_000.0)
    assert _conserved(totals, sim.accounting_totals())


# --- compatibility ----------------------------------------------------------------------------------


def test_a_whale_without_a_cycle_is_untouched():
    def view(pass_none):
        kwargs = {"cycle": None} if pass_none else {}
        whale = Whale("w", 60_000.0, starting_cash=400_000.0, behavior="accumulate",
                      target_coin_fraction=0.6, activity_probability=0.6, max_trade_fraction=0.005,
                      cooldown_ticks=2, min_trade_interval_ticks=3, intent_strength=1.5, seed=21, **kwargs)
        sim = _sim([whale], traders=_all_five(), events=_news(), psychology=True)
        ticks = sim.run(200)
        return ([(t.price, t.volume, t.whale_trades, t.trader_trades) for t in ticks],
                whale.state(), whale._rng.getstate(), sim.accounting_totals())

    assert view(False) == view(True)


def test_an_unfunded_whale_in_the_simulation_still_refuses_a_cycle():
    legacy = Whale("legacy", 50_000.0, activity_probability=0.5, seed=21)
    sim = _sim([legacy], traders=_all_five())
    sim.run(50)
    assert legacy.cycle is None and not legacy.cycle_state().configured
    with pytest.raises(ValueError, match="cycle applies only to funded whales"):
        Whale("legacy", 50_000.0, cycle=CYCLE)


# --- determinism ---------------------------------------------------------------------------------------


def test_the_same_cycle_and_seed_replay_identically():
    def run():
        whales = [_whale("a", cash=300_000.0, coins=40_000.0, target_coin_fraction=0.6, seed=21),
                  _whale("b", cycle=[{"behavior": "distribute", "duration": 7},
                                     {"behavior": "accumulate", "duration": 7}],
                         cash=100_000.0, coins=150_000.0, target_coin_fraction=0.3, seed=22,
                         min_trade_interval_ticks=3, intent_strength=1.5)]
        sim = _sim(whales, traders=_all_five(), events=_news(), psychology=True)
        ticks = sim.run(250)
        return ([(t.price, t.whale_trades, t.trader_trades) for t in ticks],
                [(w.state(), w.cycle_state(), w.intent_strength, w.interval_remaining) for w in sim.whales],
                [w._rng.getstate() for w in sim.whales], sim.accounting_totals())

    assert run() == run()


def test_different_cycles_diverge():
    def run(cycle):
        whale = _whale(cycle=cycle, cash=1e9, coins=200_000.0)
        return [t.price for t in _sim([whale], traders=_all_five()).run(150)]

    fast = [{"behavior": "accumulate", "duration": 5}, {"behavior": "distribute", "duration": 5}]
    slow = [{"behavior": "accumulate", "duration": 40}, {"behavior": "distribute", "duration": 40}]
    assert run(fast) != run(slow)


def test_two_whales_with_the_same_cycle_and_seed_keep_step():
    a = _whale("a", cash=1e9, coins=100_000.0, seed=30)
    b = _whale("b", cash=1e9, coins=100_000.0, seed=30)
    sim = _sim([a, b])
    for _ in range(90):
        sim.step()
        assert a.cycle_state() == dataclasses.replace(b.cycle_state())
    per_tick = [[t for t in tick.whale_trades] for tick in sim.history]
    for trades in per_tick:
        if len(trades) == 2:
            assert trades[0].side == trades[1].side


# --- events, psychology, manipulation ---------------------------------------------------------------------


@pytest.mark.parametrize("psychology", [False, True])
def test_the_cycle_keeps_the_same_time_whatever_the_market_is_doing(psychology):
    def phases(events, generator):
        whale = _whale(cash=1e9, coins=200_000.0)
        sim = _sim([whale], traders=_all_five(), events=events, event_generator=generator,
                   psychology=psychology)
        seen = []
        for _ in range(120):
            seen.append(whale.cycle_state().behavior)
            sim.step()
        return seen, whale.cycle_state().phase_index, whale.cycle_state().phase_elapsed

    plain = phases(None, None)
    assert phases(_news(), None) == plain
    assert phases(None, RandomEventGenerator(probability=0.1, seed=777)) == plain


def test_events_add_no_draws_to_a_cycling_whale():
    def state(events):
        whale = _whale(cash=1e9, coins=200_000.0, activity_probability=0.5, seed=8)
        _sim([whale], traders=_all_five(), events=events).run(200)
        return whale._rng.getstate(), whale.cycle_state()

    assert state(None) == state(_news())


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_a_cycling_whale_runs_alongside_a_manipulation_scenario(scenario):
    settings = get_settings()
    whales = [WhaleSettings("w", 20_000.0, activity_probability=0.5, max_trade_fraction=0.005,
                            starting_cash=200_000.0, target_coin_fraction=0.5,
                            cycle=[{"behavior": "accumulate", "duration": 20},
                                   {"behavior": "distribute", "duration": 20}])]
    sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)), scenario=scenario)
    (whale,) = sim.whales
    totals = sim.accounting_totals()
    sides = _sides_per_tick(sim, 80)
    assert all(s <= {"buy"} for s in sides[:20]) and all(s <= {"sell"} for s in sides[20:40])
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert not any(f.trader_id == "w" for t in sim.history for f in t.trader_trades)


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
                 "social", "psychology", "news", "volatility", "manipul")
    assert not any(word in name.lower() for name in names for word in forbidden)


def test_the_cycle_is_driven_by_its_own_clock_and_nothing_else():
    """The phase at any tick depends only on the tick count, so it can be
    predicted without running the market at all."""
    whale = _whale(cash=1e9, coins=200_000.0)
    sim = _sim([whale], traders=_all_five(), events=_news(), psychology=True)
    expected = []
    for phase in whale.cycle.phases:
        expected += [phase.behavior] * phase.duration
    for tick in range(120):
        assert whale.cycle_state().behavior is expected[tick % len(expected)]
        sim.step()


# --- accounting -------------------------------------------------------------------------------------------


def test_cycling_whales_and_traders_conserve_coins_and_cash_over_a_long_run():
    whales = [_whale("a", cash=300_000.0, coins=40_000.0, target_coin_fraction=0.7, seed=31,
                     intent_strength=2.0),
              _whale("b", cycle=[{"behavior": "distribute", "duration": 9}, {"behavior": "neutral", "duration": 4}],
                     cash=20_000.0, coins=150_000.0, target_coin_fraction=0.3, seed=32),
              _whale("c", cycle=[{"behavior": "neutral", "duration": 6}], cash=80_000.0, coins=80_000.0,
                     seed=33, cooldown_ticks=2),
              Whale("legacy", 30_000.0, activity_probability=0.4, seed=34)]
    sim = _sim(whales, traders=_all_five())
    totals = sim.accounting_totals()
    for _ in range(500):
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    assert sum(len(t.whale_trades) for t in sim.history) > 100


# --- AMM ------------------------------------------------------------------------------------------------------


def test_amm_mode_still_rejects_a_cycling_whale():
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[_whale()], reserve_cash=2_000_000.0, pricing_mode="amm")


def test_a_cycle_in_the_config_does_not_make_amm_accept_whales():
    settings = get_settings()
    whales = [WhaleSettings("w", 0.0, starting_cash=1_000.0, cycle=CYCLE)]
    tweaked = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales))
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        build_coin_simulator(tweaked, pricing_mode="amm")
    assert build_coin_simulator(tweaked, pricing_mode="amm", include_whales=False).whales == []


# --- configuration -----------------------------------------------------------------------------------------------


def test_the_default_config_has_no_cycle():
    settings = get_settings()
    (whale_cfg,) = settings.coin.whales
    assert whale_cfg.cycle is None
    (whale,) = build_coin_simulator(settings).whales
    assert whale.cycle is None and not whale.cycle_state().configured


def test_a_cycle_is_parsed_from_config_and_reaches_the_whale():
    raw = load_config()
    raw["coin"]["whales"] = [{"id": "w", "holdings": 0.0, "starting_cash": 100_000.0,
                              "target_coin_fraction": 0.4,
                              "cycle": [{"behavior": "accumulate", "duration": 30},
                                        {"behavior": "neutral", "duration": 10}]}]
    settings = build_settings(raw, DEFAULT_CONFIG_PATH)
    assert settings.coin.whales == [WhaleSettings(
        "w", 0.0, starting_cash=100_000.0, target_coin_fraction=0.4,
        cycle=[{"behavior": "accumulate", "duration": 30}, {"behavior": "neutral", "duration": 10}])]
    (whale,) = build_coin_simulator(settings).whales
    assert whale.cycle.phases == (WhalePhase(WhaleBehavior.ACCUMULATE, 30),
                                  WhalePhase(WhaleBehavior.NEUTRAL, 10))
    assert whale.behavior is WhaleBehavior.ACCUMULATE


def test_a_malformed_configured_cycle_is_rejected_by_the_builder():
    settings = get_settings()
    for bad, message in (([], "at least one phase"),
                         ([{"behavior": "hodl", "duration": 2}], "Unknown whale behavior"),
                         ([{"behavior": "accumulate", "duration": 0}], "duration must be an integer >= 1"),
                         ([{"behavior": "accumulate"}], "needs both a behavior and a duration")):
        whales = [WhaleSettings("w", 0.0, starting_cash=1_000.0, cycle=bad)]
        with pytest.raises(ValueError, match=message):
            build_coin_simulator(
                dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)))


def test_an_unfunded_configured_whale_with_a_cycle_is_rejected_by_the_builder():
    settings = get_settings()
    whales = [WhaleSettings("w", 1_000.0, cycle=CYCLE)]
    with pytest.raises(ValueError, match="cycle applies only to funded whales"):
        build_coin_simulator(
            dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)))


def test_omitting_the_cycle_matches_passing_none_end_to_end():
    settings = get_settings()
    explicit = dataclasses.replace(settings.coin.whales[0], cycle=None)
    same = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=[explicit]))

    def view(s):
        return [(t.price, t.volume, t.whale_trades, t.trader_trades) for t in build_coin_simulator(s).run(200)]

    assert view(same) == view(settings)
