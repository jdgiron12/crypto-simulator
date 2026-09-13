"""Paced whales inside the simulation (Phase 8, Step 3).

``min_trade_interval_ticks`` is enforced entirely inside the whale, so
these check that it survives contact with the simulation loop: a moving
price, traders, news, manipulators and psychology all around it, none of
which it reads.
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
from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin


def _paced(whale_id="paced", interval=3, cash=500_000.0, coins=100_000.0, behavior="neutral",
           seed=21, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.001)
    return Whale(whale_id, coins, starting_cash=cash, behavior=behavior, seed=seed,
                 min_trade_interval_ticks=interval, **kwargs)


def _sim(whales, traders=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0, **kwargs)


def _trade_ticks(ticks, whale_id):
    return [t.tick for t in ticks for w in t.whale_trades if w.whale_id == whale_id]


def _gaps(trade_ticks):
    return {b - a for a, b in zip(trade_ticks, trade_ticks[1:])}


def _balances_ok(sim):
    wallets = [sim.reserve, *(t.wallet for t in sim.traders), *(w.wallet for w in sim.whales if w.funded)]
    return all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)


def _conserved(before, after):
    return all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(after, before))


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


# --- the interval holds inside the loop -------------------------------------------------------------


@pytest.mark.parametrize("interval", [0, 1, 2, 5, 11])
def test_a_paced_whale_trades_exactly_every_interval_plus_one_ticks(interval):
    whale = _paced(interval=interval)
    ticks = _sim([whale]).run(60)
    traded = _trade_ticks(ticks, "paced")
    assert traded == list(range(1, 61, interval + 1))
    assert _gaps(traded) == ({interval + 1} if len(traded) > 1 else set())


def test_pacing_survives_a_moving_price_and_a_reserve_that_pushes_back():
    whale = _paced(interval=4, cash=400_000.0, coins=0.0, behavior="accumulate")
    sim = _sim([whale], traders=_all_five())
    ticks = sim.run(300)
    traded = _trade_ticks(ticks, "paced")
    # Ticks it sat out are never fewer than the interval; they can be more
    # when a tick's attempt did not fill.
    assert traded and all(gap >= 5 for gap in _gaps(traded))
    assert _balances_ok(sim)


def test_pacing_slows_a_whale_without_changing_where_its_target_lands():
    def run(interval):
        whale = Whale("w", 0.0, starting_cash=1_000_000.0, behavior="accumulate", target_coin_fraction=0.5,
                      activity_probability=1.0, max_trade_fraction=1.0, min_trade_fraction=1.0,
                      min_trade_interval_ticks=interval, seed=4)
        sim = _sim([whale])
        ticks = sim.run(120)
        return whale, _trade_ticks(ticks, "w")

    quick, quick_ticks = run(0)
    slow, slow_ticks = run(6)
    assert len(slow_ticks) < len(quick_ticks)
    # Both end managed against the same target rather than all-in. They do
    # not land on identical balances: trading on different ticks means
    # meeting different prices, so each last rebalanced at a price of its
    # own. (Non-crossing is checked per fill, at the fill's own price, in
    # test_whale_scheduling.py.)
    for whale in (quick, slow):
        assert whale.wallet.cash > 0.0 and whale.wallet.coins > 0.0
        assert whale.allocation(2.0).coin_fraction == pytest.approx(0.5, abs=0.05)


def test_a_paced_accumulator_never_sells_and_a_paced_distributor_never_buys():
    acc = _paced("acc", interval=3, cash=400_000.0, coins=0.0, behavior="accumulate",
                 target_coin_fraction=0.7, activity_probability=0.6)
    dist = _paced("dist", interval=2, cash=0.0, coins=100_000.0, behavior="distribute",
                  target_coin_fraction=0.2, activity_probability=0.6, seed=22)
    ticks = _sim([acc, dist], traders=_all_five()).run(300)
    sides = {w.whale_id: {x.side for t in ticks for x in t.whale_trades if x.whale_id == w.whale_id}
             for w in (acc, dist)}
    assert sides == {"acc": {"buy"}, "dist": {"sell"}}


# --- backward compatibility with the Step 2 checkpoint -------------------------------------------


def test_omitting_the_setting_reproduces_the_step_2_run_exactly():
    def view(**kwargs):
        whales = [
            Whale("acc", 0.0, starting_cash=400_000.0, behavior="accumulate", target_coin_fraction=0.6,
                  activity_probability=0.5, max_trade_fraction=0.02, seed=21, **kwargs),
            Whale("dist", 80_000.0, starting_cash=0.0, behavior="distribute", target_coin_fraction=0.3,
                  activity_probability=0.5, max_trade_fraction=0.02, seed=22, cooldown_ticks=2, **kwargs),
            Whale("legacy", 30_000.0, activity_probability=0.4, seed=23),
        ]
        sim = CoinSimulator(_coin(), seed=3, whales=whales, traders=_all_five(), reserve_cash=500_000.0,
                            events=_news(), psychology=True)
        ticks = sim.run(200)
        return ([(t.price, t.volume, t.whale_trades, t.trader_trades, t.event_state, t.psychology) for t in ticks],
                [w.state() for w in sim.whales], [w._rng.getstate() for w in sim.whales],
                (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals())

    assert view() == view(min_trade_interval_ticks=0)


def test_an_unfunded_whale_in_the_simulation_is_untouched():
    def prices(whales):
        return [t.price for t in _sim(whales, traders=_all_five()).run(150)]

    legacy = [Whale("legacy", 50_000.0, activity_probability=0.5, max_trade_fraction=0.03, seed=21)]
    same = [Whale("legacy", 50_000.0, activity_probability=0.5, max_trade_fraction=0.03, seed=21)]
    assert prices(legacy) == prices(same)


# --- traders, events, psychology ------------------------------------------------------------------


@pytest.mark.parametrize("psychology", [False, True])
@pytest.mark.parametrize("with_traders", [False, True])
def test_the_schedule_is_the_same_with_or_without_traders_events_or_psychology(psychology, with_traders):
    """A whale rich enough to fill every eligible tick trades on exactly
    the same ticks whatever else is happening: nothing in the market can
    reach its pacing."""
    def traded(events, generator):
        whale = _paced(interval=4)
        sim = _sim([whale], traders=_all_five() if with_traders else None, events=events,
                   event_generator=generator, psychology=psychology)
        return _trade_ticks(sim.run(120), "paced"), whale._rng.getstate(), whale.interval_remaining

    plain = traded(None, None)
    assert traded(_news(), None) == plain
    assert traded(None, RandomEventGenerator(probability=0.1, seed=777)) == plain
    assert plain[0] == list(range(1, 121, 5))


def test_events_add_no_scheduling_draws():
    def calls(events):
        whale = _paced(interval=3, activity_probability=0.5, seed=8)
        sim = _sim([whale], traders=_all_five(), events=events)
        sim.run(200)
        return whale._rng.getstate()

    assert calls(None) == calls(_news())


def test_psychology_does_not_reach_a_paced_whale():
    def run(psychology, traders):
        whale = _paced(interval=3, cash=400_000.0, coins=0.0, behavior="accumulate",
                       target_coin_fraction=0.6, activity_probability=0.5)
        sim = _sim([whale], traders=traders, psychology=psychology, events=_news())
        ticks = sim.run(120)
        return [t.whale_trades for t in ticks], whale._rng.getstate(), whale.interval_remaining

    assert run(True, None) == run(False, None)
    on, off = run(True, _all_five()), run(False, _all_five())
    assert on[1] == off[1]  # identical draws; only the prices they met differ


def test_the_whale_module_still_reads_no_psychology_news_or_manipulation():
    source = Path(whale_module.__file__).read_text()
    tree = ast.parse(source)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(part in module for module in imported for part in ("psychology", "events", "manipulation"))
    assert imported <= {"__future__", "math", "random", "dataclasses", "enum",
                        "crypto_simulator.core.traders.base", "crypto_simulator.core.traders.execution",
                        "crypto_simulator.models.wallet"}
    # Prose may mention what a whale deliberately ignores, so check the
    # names the code actually touches rather than the raw text.
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)}
    forbidden = ("fear", "fomo", "conviction", "uncertainty", "sentiment", "momentum",
                 "social", "psychology", "event", "news", "volatility", "manipul")
    assert not any(word in name.lower() for name in names for word in forbidden)


# --- manipulation ----------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_a_paced_whale_runs_alongside_a_manipulation_scenario(scenario):
    settings = get_settings()
    whales = [WhaleSettings("acc", 0.0, activity_probability=0.5, max_trade_fraction=0.01,
                            starting_cash=200_000.0, behavior="accumulate", target_coin_fraction=0.5,
                            min_trade_interval_ticks=4)]
    sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)), scenario=scenario)
    totals = sim.accounting_totals()
    ticks = sim.run(80)
    traded = _trade_ticks(ticks, "acc")
    assert traded and all(gap >= 5 for gap in _gaps(traded))
    assert {w.side for t in ticks for w in t.whale_trades} <= {"buy"}
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert not any(f.trader_id == "acc" for t in ticks for f in t.trader_trades)


# --- several whales, accounting ---------------------------------------------------------------------


def test_paced_and_unpaced_whales_share_a_reserve_and_conserve_everything():
    whales = [
        _paced("fast", interval=1, cash=300_000.0, coins=0.0, behavior="accumulate",
               target_coin_fraction=0.6, activity_probability=0.6, seed=31),
        _paced("slow", interval=9, cash=20_000.0, coins=150_000.0, behavior="distribute",
               target_coin_fraction=0.3, activity_probability=0.6, seed=32),
        Whale("unpaced", 40_000.0, starting_cash=60_000.0, activity_probability=0.4,
              max_trade_fraction=0.02, seed=33),
        Whale("legacy", 30_000.0, activity_probability=0.4, seed=34),
    ]
    sim = _sim(whales, traders=_all_five())
    totals = sim.accounting_totals()
    for _ in range(500):
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    fast, slow = _trade_ticks(sim.history, "fast"), _trade_ticks(sim.history, "slow")
    assert all(gap >= 2 for gap in _gaps(fast)) and all(gap >= 10 for gap in _gaps(slow))
    assert len(fast) > len(slow)


def test_same_seed_replays_a_paced_simulation():
    def run():
        whales = [_paced("a", interval=3, cash=400_000.0, coins=0.0, behavior="accumulate",
                         target_coin_fraction=0.5, activity_probability=0.5),
                  _paced("b", interval=6, cash=0.0, coins=90_000.0, behavior="distribute",
                         target_coin_fraction=0.2, activity_probability=0.5, seed=22, cooldown_ticks=2)]
        sim = _sim(whales, traders=_all_five(), events=_news())
        ticks = sim.run(200)
        return ([(t.price, t.whale_trades, t.trader_trades) for t in ticks],
                [(w.state(), w.interval_remaining) for w in sim.whales])

    assert run() == run()


# --- AMM ---------------------------------------------------------------------------------------------


def test_amm_mode_still_rejects_a_paced_whale():
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[_paced()], reserve_cash=2_000_000.0, pricing_mode="amm")


def test_the_setting_does_not_make_amm_accept_whales():
    settings = get_settings()
    whales = [WhaleSettings("p", 0.0, starting_cash=1_000.0, min_trade_interval_ticks=5)]
    tweaked = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales))
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        build_coin_simulator(tweaked, pricing_mode="amm")
    assert build_coin_simulator(tweaked, pricing_mode="amm", include_whales=False).whales == []


# --- configuration -----------------------------------------------------------------------------------


def test_the_default_config_leaves_pacing_off():
    settings = get_settings()
    (whale_cfg,) = settings.coin.whales
    assert whale_cfg.min_trade_interval_ticks == 0
    (whale,) = build_coin_simulator(settings).whales
    assert whale.min_trade_interval_ticks == 0 and whale.interval_remaining == 0


def test_the_setting_is_parsed_from_config_and_reaches_the_whale():
    raw = load_config()
    raw["coin"]["whales"] = [{"id": "p", "holdings": 0.0, "starting_cash": 100_000.0,
                              "behavior": "accumulate", "target_coin_fraction": 0.4,
                              "cooldown_ticks": 2, "min_trade_interval_ticks": 6}]
    settings = build_settings(raw, DEFAULT_CONFIG_PATH)
    assert settings.coin.whales == [WhaleSettings("p", 0.0, starting_cash=100_000.0, behavior="accumulate",
                                                  target_coin_fraction=0.4, cooldown_ticks=2,
                                                  min_trade_interval_ticks=6)]
    (whale,) = build_coin_simulator(settings).whales
    assert whale.min_trade_interval_ticks == 6 and whale.cooldown_ticks == 2


def test_an_explicit_zero_matches_an_omitted_setting_end_to_end():
    settings = get_settings()
    explicit = dataclasses.replace(settings.coin.whales[0], min_trade_interval_ticks=0)
    same = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=[explicit]))

    def view(s):
        sim = build_coin_simulator(s)
        return [(t.price, t.volume, t.whale_trades, t.trader_trades) for t in sim.run(200)]

    assert view(same) == view(settings)


def test_an_unfunded_whale_config_rejects_the_setting():
    settings = get_settings()
    whales = [WhaleSettings("u", 1_000.0, min_trade_interval_ticks=3)]
    with pytest.raises(ValueError, match="min_trade_interval_ticks applies only to funded whales"):
        build_coin_simulator(dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)))
