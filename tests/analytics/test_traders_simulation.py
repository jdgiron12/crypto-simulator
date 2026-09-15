"""Trader analytics on real simulations (Phase 9, Step 2).

The simulator's wallets are the source of truth. These tests prove that
the records the analytics read are exactly what settlement did — by
replaying them against the actual wallets (random walk, bit for bit) and
against the pool's exact amounts (AMM, in ``Decimal``) — that the P&L is
the demo CLI's own figure, and that the analytics stay downstream: pure,
deterministic, order-independent and invisible to the simulation. The
replays live here, in the tests; the analytics module never reconstructs
a balance.
"""

import ast
import copy
import io
import contextlib
import random
import runpy
import sys
from decimal import Decimal
from pathlib import Path

import pytest

import crypto_simulator.analytics.traders as traders_module
import crypto_simulator.services.coin_simulation as services
from crypto_simulator.analytics import analyze_market, analyze_traders
from crypto_simulator.config.settings import clear_settings_cache
from crypto_simulator.core.liquidity.amounts import EXACT
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.wallet import Wallet
from tests.core.test_coin_simulator_traders import _all_five, _coin

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulate_coin.py"


def _balances(sim):
    return {t.trader_id: (t.wallet.cash, t.wallet.coins) for t in sim.traders}


def _world(seed, mode="random_walk", reserve_cash=None, whales=True, ticks=150):
    g = random.Random(seed)
    traders = _all_five(seed_base=seed) + [
        PumpAndDump("pump", starting_cash=50_000.0, trade_probability=1.0, max_trade_size=5_000.0,
                    risk_tolerance=0.5, seed=seed + 50),
        WashTrader("wash", starting_cash=20_000.0, starting_coins=20_000.0, trade_probability=1.0,
                   max_trade_size=2_000.0, risk_tolerance=0.5, seed=seed + 51)]
    extras = {}
    if g.random() < 0.5:
        extras = dict(psychology=True, events=EventEngine([MarketEvent(
            event_id="n", category="custom", severity=0.8, sentiment=-0.6, volatility_boost=1.0,
            attention=1.0, start_tick=20, duration=30)]))
    whale_list = []
    if whales and mode == "random_walk":
        whale_list = [Whale("u", 30_000.0, activity_probability=0.5, seed=seed + 60),
                      Whale("f", 20_000.0, starting_cash=100_000.0, behavior="accumulate",
                            activity_probability=0.5, max_trade_fraction=0.01, seed=seed + 61)]
    if reserve_cash is None:
        reserve_cash = 2_000_000.0 if mode == "amm" else 500_000.0
    sim = CoinSimulator(_coin(), seed=seed, traders=traders, whales=whale_list, pricing_mode=mode,
                        reserve_cash=reserve_cash, **extras)
    start = _balances(sim)
    wallets = {t.trader_id: copy.copy(t.wallet) for t in sim.traders}
    pool_before = None if sim.pool is None else (sim.pool.cash_reserve, sim.pool.coin_reserve)
    reserve_before = (sim.reserve.cash, sim.reserve.coins)
    out = sim.run(ticks)
    return sim, out, start, wallets, pool_before, reserve_before


def _report(sim, ticks, start):
    return analyze_traders(ticks, start_balances=start, end_balances=_balances(sim),
                           initial_price=sim.coin.starting_price)


# --- the records are exactly what settlement did --------------------------------------------------------


@pytest.mark.parametrize("reserve_cash", [500_000.0, 3_000.0])
def test_random_walk_records_replay_to_the_actual_wallets_bit_for_bit(reserve_cash):
    """Replaying each trader's fills with the same Wallet calls, in the
    order ``settle_against_reserve`` makes them — buy: withdraw cash then
    deposit coins at that cost; sell: withdraw coins then deposit cash —
    lands exactly on the simulator's wallets, partial fills and wash round
    trips included. (A small reserve forces partial fills.)"""
    partial = 0
    for seed in range(8):
        sim, ticks, _, wallets, _, _ = _world(seed, reserve_cash=reserve_cash)
        for tick in ticks:
            for fill in tick.trader_trades:
                wallet = wallets[fill.trader_id]
                if fill.side is TradeAction.BUY:
                    wallet.withdraw_cash(fill.notional)
                    wallet.deposit_coins(fill.quantity, cost=fill.notional)
                else:
                    wallet.withdraw_coins(fill.quantity)
                    wallet.deposit_cash(fill.notional)
                partial += fill.quantity < fill.requested_quantity
        for trader in sim.traders:
            replayed, actual = wallets[trader.trader_id], trader.wallet
            assert (replayed.cash, replayed.coins, replayed.average_cost) == (actual.cash, actual.coins, actual.average_cost)
    if reserve_cash < 10_000.0:
        assert partial > 0  # the small reserve does force clamped fills


def test_amm_exact_flows_land_exactly_on_the_actual_wallets():
    for seed in range(8):
        sim, ticks, start, _, _, _ = _world(seed, mode="amm")
        report = _report(sim, ticks, start)
        for trader in sim.traders:
            summary = report.trader(trader.trader_id)
            cash0, coins0 = start[trader.trader_id]
            # EXACT, not ``+``: default-context Decimal arithmetic rounds to 28 digits.
            assert EXACT.add(Decimal(cash0), summary.exact_cash_flow) == Decimal(trader.wallet.cash)
            assert EXACT.add(Decimal(coins0), summary.exact_coin_flow) == Decimal(trader.wallet.coins)


def test_amm_records_are_the_float_values_of_the_exact_swap_amounts():
    sim, ticks, _, _, _, _ = _world(4, mode="amm")
    partial = 0
    for tick in ticks:
        for fill in tick.trader_trades:
            swap = fill.swap
            if fill.side is TradeAction.BUY:
                assert (fill.notional, fill.quantity) == (float(swap.amount_in), float(swap.amount_out))
            else:
                assert (fill.quantity, fill.notional) == (float(swap.amount_in), float(swap.amount_out))
            partial += fill.quantity < fill.requested_quantity
    assert partial > 0  # fees and slippage leave buys short of the coins requested


def test_an_amm_buy_only_receives_more_than_requested_after_the_pool_price_fell():
    """A buy asks for coins worth its budget at the tick's opening price; if
    earlier swaps that tick lowered the pool price, the budget buys more."""
    over = 0
    for seed in range(200, 206):
        sim, ticks, _, _, _, _ = _world(seed, mode="amm", ticks=120)
        for tick in ticks:
            for fill in tick.trader_trades:
                if fill.side is TradeAction.BUY and fill.quantity > fill.requested_quantity:
                    over += 1
                    assert fill.swap.spot_price_before < tick.trader_trades[0].swap.spot_price_before
    assert over > 0


def test_amm_fees_are_the_pools_fees_attributed_without_double_counting():
    for seed in range(6):
        sim, ticks, start, _, _, _ = _world(seed, mode="amm")
        report = _report(sim, ticks, start)
        pool = analyze_market(ticks).pool_activity
        assert report.fees_paid_cash == pool.fees_cash == ticks[-1].pool_state.fees_collected_cash
        assert report.fees_paid_coins == pool.fees_coins == ticks[-1].pool_state.fees_collected_coins


def test_trader_flows_reconcile_with_the_counterparty():
    """Traders settle against the reserve (random walk) or the pool (AMM),
    so their flows are that counterparty's change, reversed — exactly in
    AMM, to float precision in random walk (whales off: funded whales use
    the same reserve)."""
    for seed in range(5):
        sim, ticks, start, _, _, reserve_before = _world(seed, whales=False)
        report = _report(sim, ticks, start)
        assert report.net_cash_flow == pytest.approx(-(sim.reserve.cash - reserve_before[0]), rel=1e-12, abs=1e-6)
        assert report.net_coin_flow == pytest.approx(-(sim.reserve.coins - reserve_before[1]), rel=1e-12, abs=1e-6)
        sim, ticks, start, _, pool_before, _ = _world(seed, mode="amm")
        report = _report(sim, ticks, start)
        total_cash = total_coins = Decimal(0)
        for t in report.traders:
            total_cash, total_coins = EXACT.add(total_cash, t.exact_cash_flow), EXACT.add(total_coins, t.exact_coin_flow)
        # copy_negate is exact; unary minus would round to the default context.
        assert total_cash.copy_negate() == EXACT.subtract(sim.pool.cash_reserve, pool_before[0])
        assert total_coins.copy_negate() == EXACT.subtract(sim.pool.coin_reserve, pool_before[1])


def test_flows_match_each_traders_balance_change():
    for mode in ("random_walk", "amm"):
        sim, ticks, start, _, _, _ = _world(9, mode=mode)
        report = _report(sim, ticks, start)
        for trader in sim.traders:
            summary, (cash0, coins0) = report.trader(trader.trader_id), start[trader.trader_id]
            assert summary.net_cash_flow == pytest.approx(trader.wallet.cash - cash0, rel=1e-12, abs=1e-6)
            assert summary.net_coin_flow == pytest.approx(trader.wallet.coins - coins0, rel=1e-12, abs=1e-6)


def test_volumes_agree_with_the_market_breakdown():
    for mode in ("random_walk", "amm"):
        sim, ticks, start, _, _, _ = _world(12, mode=mode)
        report = _report(sim, ticks, start)
        volume = analyze_market(ticks).volume_breakdown
        assert report.wash_volume == volume.wash_volume
        assert report.buy_volume + report.sell_volume == pytest.approx(volume.organic_volume + volume.manipulator_volume,
                                                                      rel=1e-12)
        manipulators = [t for t in report.traders if t.is_manipulator]
        assert pytest.approx(volume.manipulator_volume, rel=1e-12) == sum(
            t.buy_volume + t.sell_volume for t in manipulators)


# --- the P&L is the demo CLI's P&L -----------------------------------------------------------------------


def _run_cli(monkeypatch, *flags):
    """Run the demo CLI in-process, capturing the simulator it builds (and
    its wallets at the moment the CLI records its starting equity)."""
    captured = {}
    original = services.build_coin_simulator

    def capturing(*args, **kwargs):
        sim = original(*args, **kwargs)
        captured["sim"], captured["start"] = sim, _balances(sim)
        return sim

    monkeypatch.setattr(services, "build_coin_simulator", capturing)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *flags])
    for key in [k for k in list(__import__("os").environ) if k.startswith("CRYPTOSIM_")]:
        monkeypatch.delenv(key)
    clear_settings_cache()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    clear_settings_cache()
    return out.getvalue(), captured["sim"], captured["start"]


def _cli_pnl_column(output):
    lines = output.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("trader ") and line.rstrip().endswith("P&L"))
    rows = {}
    for line in lines[header + 1:]:
        if not line.strip() or line.startswith(("Manipulation", "AMM", "Accounting")):
            break
        rows[line.split()[0]] = line[-11:]
    return rows


@pytest.mark.parametrize("flags", [
    ("--ticks", "40"),
    ("--ticks", "60", "--scenario", "pump_and_dump"),
    ("--ticks", "60", "--scenario", "wash_trading"),
    ("--ticks", "40", "--psychology", "--events"),
    ("--ticks", "40", "--pricing-mode", "amm", "--no-whales"),
    ("--ticks", "60", "--pricing-mode", "amm", "--no-whales", "--scenario", "pump_and_dump"),
    ("--ticks", "60", "--pricing-mode", "amm", "--no-whales", "--scenario", "wash_trading", "--random-events"),
])
def test_analytics_pnl_is_the_clis_pnl(monkeypatch, flags):
    output, sim, start = _run_cli(monkeypatch, *flags)
    report = _report(sim, sim.history, start)
    printed = _cli_pnl_column(output)
    assert set(printed) == {t.trader_id for t in sim.traders}
    last_price = sim.history[-1].price
    for trader in sim.traders:
        summary = report.trader(trader.trader_id)
        cli_start = Wallet(cash=start[trader.trader_id][0], coins=start[trader.trader_id][1]).equity(sim.coin.starting_price)
        assert summary.pnl == trader.wallet.equity(last_price) - cli_start  # the CLI's own formula, exactly
        assert f"{summary.pnl:>+11,.2f}" == printed[trader.trader_id]      # and what it printed


# --- properties over many runs ------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_invariants_hold_across_many_runs(mode):
    for seed in range(12):
        sim, ticks, start, _, _, _ = _world(200 + seed, mode=mode, ticks=120)
        report = _report(sim, ticks, start)
        assert sum(t.records for t in report.traders) == sum(len(t.trader_trades) for t in ticks)
        assert sum(s.trader_count for s in report.strategies) == report.population == len(sim.traders)
        for t in report.traders:
            assert t.fill_count == t.buy_count + t.sell_count + t.wash_leg_count
            assert t.total_volume == pytest.approx(t.buy_volume + t.sell_volume + t.wash_volume, rel=1e-12)
            if t.fill_ratio is not None:
                # Random-walk settlement only clamps; AMM can deliver more (see the next test).
                assert 0.0 <= t.fill_ratio and (mode == "amm" or t.fill_ratio <= 1.0 + 1e-12)
            prices = [f.price for tick in ticks for f in tick.trader_trades if f.trader_id == t.trader_id]
            if t.vwap is not None:
                assert min(prices) - 1e-9 <= t.vwap <= max(prices) + 1e-9
            # A trader that never recorded a trade has no recorded label (None), and so no flag.
            assert t.is_manipulator == (None if t.strategy is None else t.strategy in MANIPULATION_STRATEGIES)
        assert report.pnl == pytest.approx(sum(t.pnl for t in report.traders), rel=1e-12, abs=1e-9)
        shuffled = list(ticks)
        random.Random(seed).shuffle(shuffled)
        assert analyze_traders(shuffled, start_balances=start, end_balances=_balances(sim),
                               initial_price=sim.coin.starting_price) == report


# --- purity, determinism and no feedback -------------------------------------------------------------------


def _rng_states(sim):
    return (sim._price_engine._rng.getstate(), sim._volume_model._rng.getstate(),
            [w._rng.getstate() for w in sim.whales], [t._rng.getstate() for t in sim.traders])


def test_analysis_is_pure_and_repeatable():
    sim, ticks, start, _, _, _ = _world(31)
    end = _balances(sim)
    snapshot = (copy.deepcopy(ticks), dict(start), dict(end))
    states, global_state = _rng_states(sim), random.getstate()
    first = analyze_traders(ticks, start_balances=start, end_balances=end, initial_price=1.0)
    assert analyze_traders(ticks, start_balances=start, end_balances=end, initial_price=1.0) == first
    assert (ticks, start, end) == snapshot
    assert _rng_states(sim) == states and random.getstate() == global_state


def test_analysing_mid_run_does_not_change_the_rest_of_the_run():
    def run(analyse):
        sim, ticks, start, _, _, _ = _world(44, ticks=60)
        if analyse:
            analyze_traders(ticks, start_balances=start, end_balances=_balances(sim), initial_price=1.0)
            analyze_traders(ticks, trader_ids=[sim.traders[0].trader_id])
        rest = sim.run(60)
        return ([(t.tick, t.price, t.volume, t.trader_trades, t.whale_trades) for t in rest],
                [(t.trader_id, t.wallet.cash, t.wallet.coins) for t in sim.traders], _rng_states(sim))

    assert run(True) == run(False)


def test_the_module_only_reads_records():
    tree = ast.parse(Path(traders_module.__file__).read_text())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported <= {"__future__", "math", "dataclasses", "decimal", "typing",
                        "crypto_simulator.analytics._series", "crypto_simulator.core.coin_simulator",
                        "crypto_simulator.core.liquidity.amounts", "crypto_simulator.core.liquidity.pool",
                        "crypto_simulator.core.traders.base", "crypto_simulator.core.traders.registry"}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    # No settlement, no pool calls, no simulation control.
    forbidden = {"random", "_rng", "step", "run", "set_price", "decide", "maybe_trade", "withdraw_cash",
                 "deposit_cash", "withdraw_coins", "deposit_coins", "settle_against_reserve", "execute_decision",
                 "buy", "sell", "quote_buy", "quote_sell"}
    assert not used & forbidden, used & forbidden


def test_equity_is_wallet_equity_bit_for_bit():
    g = random.Random(5)
    for _ in range(2_000):
        cash, coins, price = g.uniform(0, 1e6), g.uniform(0, 1e6), g.uniform(1e-6, 1e3)
        assert traders_module._equity(cash, coins, price) == Wallet(cash=cash, coins=coins).equity(price)


def test_the_module_makes_no_causal_claims_or_recommendations():
    text = Path(traders_module.__file__).read_text().lower()
    for phrase in ("caused", "led to", "drove", "because of", "due to", "resulted in", "predict", "should buy",
                   "should sell", "optimal"):
        assert phrase not in text, phrase
