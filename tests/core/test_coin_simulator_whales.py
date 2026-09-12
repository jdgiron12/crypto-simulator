"""Funded and unfunded whales inside the simulation (Phase 8, Step 1)."""

import ast
import dataclasses
from decimal import Decimal
from pathlib import Path

import pytest

import crypto_simulator.core.whale as whale_module
from crypto_simulator.config import WhaleSettings, get_settings
from crypto_simulator.config.settings import DEFAULT_CONFIG_PATH, build_settings, load_config
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.whale import Whale, WhaleBehavior
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import (
    GOLDEN_WHALE_FINAL_HOLDINGS,
    GOLDEN_WHALE_PRICES,
    GOLDEN_WHALE_TRADES,
    SUPPLY,
    _all_five,
    _coin,
    _golden_whale,
)


def _accumulator(whale_id="acc", cash=400_000.0, seed=21, **kwargs):
    return Whale(whale_id, 0.0, starting_cash=cash, behavior="accumulate", activity_probability=0.5,
                 max_trade_fraction=0.02, seed=seed, **kwargs)


def _distributor(whale_id="dist", coins=80_000.0, seed=22, **kwargs):
    return Whale(whale_id, coins, starting_cash=0.0, behavior="distribute", activity_probability=0.5,
                 max_trade_fraction=0.02, seed=seed, **kwargs)


def _sim(whales, traders=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0, **kwargs)


def _balances_ok(sim):
    wallets = [sim.reserve, *(t.wallet for t in sim.traders), *(w.wallet for w in sim.whales if w.funded)]
    return all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)


def _conserved(before, after):
    return all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(after, before))


# --- backward compatibility ------------------------------------------------------------------


def test_the_golden_whale_run_is_unchanged():
    whale = _golden_whale()
    ticks = CoinSimulator(_coin(), seed=1, whales=[whale]).run(15)
    assert [t.price for t in ticks] == GOLDEN_WHALE_PRICES
    assert [(t.tick, w.side, w.quantity) for t in ticks for w in t.whale_trades] == GOLDEN_WHALE_TRADES
    assert whale.holdings == GOLDEN_WHALE_FINAL_HOLDINGS


def test_config_without_the_new_fields_builds_the_original_whale():
    settings = get_settings()
    (whale_cfg,) = settings.coin.whales
    assert (whale_cfg.starting_cash, whale_cfg.behavior, whale_cfg.target_coin_fraction,
            whale_cfg.min_trade_fraction, whale_cfg.cooldown_ticks) == (None, "neutral", None, 0.0, 0)
    (whale,) = build_coin_simulator(settings).whales
    assert not whale.funded and whale.behavior is WhaleBehavior.NEUTRAL and whale.cooldown_ticks == 0


def test_explicit_default_fields_match_omitted_ones():
    settings = get_settings()
    explicit = dataclasses.replace(settings.coin.whales[0], starting_cash=None, behavior="neutral",
                                   target_coin_fraction=None, min_trade_fraction=0.0, cooldown_ticks=0)
    same = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=[explicit]))

    def view(s):
        return [(t.price, t.volume, t.whale_trades, t.trader_trades) for t in build_coin_simulator(s).run(150)]

    assert view(same) == view(settings)


def test_whale_fields_are_parsed_from_config():
    raw = load_config()
    raw["coin"]["whales"] = [{"id": "w", "holdings": 10.0, "starting_cash": 5.0, "behavior": "accumulate",
                              "target_coin_fraction": 0.4, "min_trade_fraction": 0.01, "cooldown_ticks": 3}]
    settings = build_settings(raw, DEFAULT_CONFIG_PATH)
    assert settings.coin.whales == [WhaleSettings("w", 10.0, starting_cash=5.0, behavior="accumulate",
                                                  target_coin_fraction=0.4, min_trade_fraction=0.01, cooldown_ticks=3)]


def test_the_builder_passes_every_whale_field_through():
    settings = get_settings()
    funded = WhaleSettings("w-acc", 1_000.0, activity_probability=0.3, max_trade_fraction=0.02, starting_cash=50_000.0,
                           behavior="accumulate", target_coin_fraction=0.5, min_trade_fraction=0.005, cooldown_ticks=4)
    sim = build_coin_simulator(dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=[funded])))
    (whale,) = sim.whales
    assert whale.state().cash == 50_000.0 and whale.holdings == 1_000.0
    assert (whale.behavior, whale.target_coin_fraction, whale.min_trade_fraction, whale.cooldown_ticks) == (
        WhaleBehavior.ACCUMULATE, 0.5, 0.005, 4)
    assert whale.wallet.average_cost == settings.coin.starting_price  # starting coins get a cost basis, like traders


# --- random walk ------------------------------------------------------------------------------


def test_an_accumulating_whale_buys_from_the_reserve_and_moves_price_through_the_existing_impact():
    whale = _accumulator()
    sim = _sim([whale])
    reserve_coins = sim.reserve.coins
    totals = sim.accounting_totals()
    ticks = sim.run(60)
    trades = [w for t in ticks for w in t.whale_trades]
    assert trades and all(w.side == "buy" and w.price_impact == 1.0 + 2.0 * w.quantity / SUPPLY for w in trades)
    assert sim.reserve.coins == pytest.approx(reserve_coins - whale.holdings)
    assert _conserved(totals, sim.accounting_totals())
    # Volume carries the whale's coins, as it always has.
    assert all(t.volume >= sum(w.quantity for w in t.whale_trades) for t in ticks)


def test_multiple_whales_keep_their_own_streams():
    alone = _sim([_accumulator()])
    alone.run(80)
    together = _sim([_accumulator(), _distributor(), Whale("legacy", 30_000.0, activity_probability=0.4, seed=23)])
    ticks = together.run(80)
    assert together.whales[0]._rng.getstate() == alone.whales[0]._rng.getstate()
    sides = {w.whale_id: {x.side for t in ticks for x in t.whale_trades if x.whale_id == w.whale_id}
             for w in together.whales}
    assert sides == {"acc": {"buy"}, "dist": {"sell"}, "legacy": {"buy", "sell"}}
    assert _balances_ok(together)


def test_funded_whales_and_traders_conserve_coins_and_cash_over_a_long_run():
    sim = _sim([_accumulator(cash=300_000.0), _distributor(coins=60_000.0, cooldown_ticks=2),
                Whale("neutral", 20_000.0, starting_cash=40_000.0, activity_probability=0.3, seed=24)],
               traders=_all_five())
    totals = sim.accounting_totals()
    for _ in range(500):
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    assert sum(len(t.whale_trades) for t in sim.history) > 50


def test_unfunded_whales_stay_outside_the_accounting_totals():
    with_legacy = _sim([_golden_whale()], traders=_all_five())
    without = _sim([], traders=_all_five())
    assert with_legacy.accounting_totals()[1] == without.accounting_totals()[1]  # no whale cash
    funded = _sim([Whale("f", 0.0, starting_cash=12_345.0)], traders=_all_five())
    assert funded.accounting_totals()[1] == without.accounting_totals()[1] + Decimal(12_345.0)


def test_same_seed_same_whale_run():
    def run():
        sim = _sim([_accumulator(target_coin_fraction=0.6, cooldown_ticks=3), _distributor()], traders=_all_five())
        ticks = sim.run(120)
        return [(t.price, t.whale_trades, t.trader_trades) for t in ticks], [w.state() for w in sim.whales]

    assert run() == run()


# --- events, manipulation, psychology -----------------------------------------------------------------


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


def test_whales_run_with_events_and_unfunded_whale_trades_ignore_them():
    plain = _sim([_golden_whale()], traders=_all_five()).run(60)
    newsy = _sim([_golden_whale()], traders=_all_five(), events=_news()).run(60)
    assert [t.whale_trades for t in newsy] == [t.whale_trades for t in plain]
    sim = _sim([_accumulator(), _distributor()], traders=_all_five(), events=_news())
    totals = sim.accounting_totals()
    sim.run(60)
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)


def test_whales_run_alongside_a_manipulation_scenario():
    settings = get_settings()
    whales = [WhaleSettings("acc", 0.0, activity_probability=0.4, max_trade_fraction=0.01,
                            starting_cash=200_000.0, behavior="accumulate")]
    sim = build_coin_simulator(dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)),
                               scenario="pump_and_dump")
    totals = sim.accounting_totals()
    ticks = sim.run(40)
    reasons = {f.reason for t in ticks for f in t.trader_trades if f.trader_id.startswith("pump")}
    assert {"accumulate", "pump", "dump"} <= reasons  # the scheme still runs its schedule
    assert any(t.whale_trades for t in ticks)
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)


@pytest.mark.parametrize("make", [lambda: [_accumulator(), _distributor()], lambda: [_golden_whale()]])
def test_psychology_does_not_change_whale_behavior(make):
    """Without traders, psychology has no channel at all; with traders,
    unfunded whales trade identically and every whale draws identically."""
    def run(psychology, traders):
        sim = _sim(make(), traders=traders, psychology=psychology, events=_news())
        ticks = sim.run(80)
        return [t.whale_trades for t in ticks], [w._rng.getstate() for w in sim.whales]

    assert run(True, None) == run(False, None)
    on, off = run(True, _all_five()), run(False, _all_five())
    assert on[1] == off[1]
    if not make()[0].funded:
        assert on[0] == off[0]


def test_the_whale_module_reads_no_psychology_news_or_manipulation():
    tree = ast.parse(Path(whale_module.__file__).read_text())
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(part in module for module in imported for part in ("psychology", "events", "manipulation"))
    assert imported <= {"__future__", "math", "random", "dataclasses", "enum", "crypto_simulator.core.traders.base",
                        "crypto_simulator.core.traders.execution", "crypto_simulator.models.wallet"}


# --- AMM contract ------------------------------------------------------------------------------------


@pytest.mark.parametrize("make", [_golden_whale, _accumulator, _distributor])
def test_amm_mode_still_rejects_every_kind_of_whale(make):
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[make()], reserve_cash=2_000_000.0, pricing_mode="amm")


def test_amm_without_whales_is_unaffected():
    settings = get_settings()
    sim = build_coin_simulator(settings, pricing_mode="amm", include_whales=False)
    totals = sim.accounting_totals()
    sim.run(100)
    assert sim.accounting_totals() == totals and sim.whales == []
