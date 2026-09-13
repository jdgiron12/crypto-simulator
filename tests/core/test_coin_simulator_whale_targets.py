"""Target-allocation whales inside the simulation (Phase 8, Step 2).

The unit tests in ``test_whale_target_allocation.py`` drive the whale
directly at a fixed price. These run it inside ``CoinSimulator``, where
the price moves under it every tick, alongside traders, events,
manipulators and psychology — none of which the whale reads.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

import crypto_simulator.core.whale as whale_module
from crypto_simulator.config import WhaleSettings, get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin


class _Observed(Whale):
    """A whale that records the price it was offered and its allocation on
    either side of each trade, so a test can check the non-crossing
    invariant at the price the fill actually happened at."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = []

    def maybe_trade(self, total_supply, *, price=None, reserve=None):
        before = self.allocation(price) if price is not None else None
        trade = super().maybe_trade(total_supply, price=price, reserve=reserve)
        after = self.allocation(price) if price is not None else None
        self.observations.append((price, before, after, trade))
        return trade


def _accumulator(whale_id="acc", cash=400_000.0, coins=0.0, target=0.5, seed=21, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.02)
    return _Observed(whale_id, coins, starting_cash=cash, behavior="accumulate",
                     target_coin_fraction=target, seed=seed, **kwargs)


def _distributor(whale_id="dist", cash=0.0, coins=80_000.0, target=0.3, seed=22, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.02)
    return _Observed(whale_id, coins, starting_cash=cash, behavior="distribute",
                     target_coin_fraction=target, seed=seed, **kwargs)


def _sim(whales, traders=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0, **kwargs)


def _balances_ok(sim):
    wallets = [sim.reserve, *(t.wallet for t in sim.traders), *(w.wallet for w in sim.whales if w.funded)]
    return all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)


def _conserved(before, after):
    return all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(after, before))


def _never_crossed(whale):
    """Every fill moved toward the target and stopped at or short of it,
    measured at the price that fill happened at."""
    target = whale.target_coin_fraction
    filled = 0
    for _price, before, after, trade in whale.observations:
        if trade is None or trade.quantity == 0:
            assert before == after
            continue
        filled += 1
        if whale.behavior.value == "accumulate":
            assert before.coin_fraction < after.coin_fraction <= target + TARGET_DEAD_ZONE
        else:
            assert before.coin_fraction > after.coin_fraction >= target - TARGET_DEAD_ZONE
    return filled


# --- random walk + one funded whale --------------------------------------------------------------


def test_a_targeted_accumulator_buys_toward_its_target_as_the_price_moves():
    whale = _accumulator(target=0.6)
    sim = _sim([whale])
    reserve_coins = sim.reserve.coins
    totals = sim.accounting_totals()
    ticks = sim.run(200)
    trades = [w for t in ticks for w in t.whale_trades]
    assert all(w.side == "buy" for w in trades)
    assert _never_crossed(whale) == len(trades) > 10
    assert sim.reserve.coins == pytest.approx(reserve_coins - whale.holdings)
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    # It ends managed against its target rather than all-in on coins.
    assert whale.allocation(sim.current_price).coin_fraction == pytest.approx(0.6, abs=0.05)
    assert whale.wallet.cash > 0.0


def test_a_targeted_distributor_sells_toward_its_target_and_then_settles_down():
    whale = _distributor(target=0.25, coins=120_000.0)
    sim = _sim([whale])
    ticks = sim.run(200)
    trades = [w for t in ticks for w in t.whale_trades]
    assert trades and all(w.side == "sell" for w in trades)
    assert _never_crossed(whale) == len(trades)
    # A target stops it well short of selling out; the same whale without
    # one keeps selling until its coins are gone.
    assert whale.wallet.coins > 0.0
    bare = Whale("bare", 120_000.0, starting_cash=0.0, behavior="distribute",
                 activity_probability=0.5, max_trade_fraction=0.02, seed=22)
    _sim([bare]).run(200)
    assert bare.holdings == 0.0 and whale.wallet.coins > 10_000.0
    early = sum(len(t.whale_trades) for t in ticks[:40])
    late = sum(len(t.whale_trades) for t in ticks[160:])
    assert early > late  # the approach front-loads; afterwards only price moves reopen a gap


def test_a_whale_already_past_its_target_never_trades_in_the_simulation():
    whale = _accumulator(cash=10_000.0, coins=400_000.0, target=0.2)
    sim = _sim([whale])
    ticks = sim.run(120)
    assert all(t.whale_trades == () for t in ticks)
    assert (sim.reserve.cash, sim.reserve.coins) == (500_000.0, 600_000.0)
    assert [t.price for t in ticks] == [t.price for t in _sim([]).run(120)]  # no impact at all


# --- several funded whales with different targets -------------------------------------------------


def test_whales_with_different_targets_manage_to_their_own_and_share_one_reserve():
    whales = [
        _accumulator("acc-low", cash=300_000.0, target=0.2, seed=31),
        _accumulator("acc-high", cash=300_000.0, target=0.85, seed=32),
        _distributor("dist", cash=20_000.0, coins=150_000.0, target=0.4, seed=33),
    ]
    sim = _sim(whales)
    totals = sim.accounting_totals()
    sim.run(300)
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    price = sim.current_price
    for whale in whales:
        assert _never_crossed(whale) > 0
    # Different targets really do end in different places, ordered the way
    # the targets are. (The exact fractions drift off target between
    # fills, because the price keeps moving after the last one.)
    low, high, dist = (w.allocation(price).coin_fraction for w in whales)
    assert low < high and low < 0.5 < high
    assert all(w.wallet.cash > 0.0 and w.wallet.coins > 0.0 for w in whales)


def test_a_targeted_whale_keeps_its_own_rng_stream_alongside_others():
    alone = _sim([_accumulator(target=0.7)])
    alone.run(150)
    together = _sim([_accumulator(target=0.7), _distributor(target=0.2),
                     Whale("legacy", 30_000.0, activity_probability=0.4, seed=23)])
    together.run(150)
    assert together.whales[0]._rng.getstate() == alone.whales[0]._rng.getstate()


def test_the_same_seed_replays_a_targeted_run_inside_the_simulator():
    def run():
        sim = _sim([_accumulator(target=0.55, cooldown_ticks=2), _distributor(target=0.15)],
                   traders=_all_five())
        ticks = sim.run(150)
        return ([(t.price, t.whale_trades, t.trader_trades) for t in ticks],
                [w.state() for w in sim.whales],
                [w.allocation(sim.current_price) for w in sim.whales])

    assert run() == run()


# --- funded whales + traders ----------------------------------------------------------------------


def test_targeted_whales_and_traders_conserve_coins_and_cash_over_a_long_run():
    whales = [_accumulator(cash=300_000.0, target=0.45), _distributor(coins=60_000.0, target=0.3, cooldown_ticks=2)]
    sim = _sim(whales, traders=_all_five())
    totals = sim.accounting_totals()
    for _ in range(500):
        sim.step()
        assert _balances_ok(sim)
    assert _conserved(totals, sim.accounting_totals())
    assert sum(_never_crossed(w) for w in whales) > 20


def test_trader_flow_moves_the_price_and_so_reopens_the_whales_gap():
    """The whale is marked at whatever price the market leaves it at, so a
    target that traders push it away from is one it works back toward."""
    whale = _accumulator(target=0.5, cash=200_000.0)
    sim = _sim([whale], traders=_all_five())
    sim.run(300)
    prices = {round(p, 8) for p, *_ in whale.observations}
    assert len(prices) > 100  # it really was marked at a moving price
    filled = [i for i, (_p, _b, _a, trade) in enumerate(whale.observations) if trade is not None]
    # The gap closes early, then trader flow keeps reopening it, so fills
    # go on happening long after the initial approach is done.
    assert min(filled) < 20 and max(filled) > 200
    assert _never_crossed(whale) == len(filled) > 5
    # Every fill either landed exactly on the target or was bounded by the
    # drawn trade size — never past it.
    for _p, _b, after, trade in whale.observations:
        if trade is not None:
            assert after.allocation_gap >= -TARGET_DEAD_ZONE


# --- funded whales + events -----------------------------------------------------------------------


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


def test_events_reach_a_targeted_whale_only_through_the_price():
    """Its draws are identical with and without news; only the prices it is
    marked at, and so its fills, can differ."""
    def run(events):
        whale = _accumulator(target=0.6)
        sim = _sim([whale], traders=_all_five(), events=events)
        sim.run(120)
        return whale, sim

    plain_whale, plain = run(None)
    newsy_whale, newsy = run(_news())
    assert plain_whale._rng.getstate() == newsy_whale._rng.getstate()
    assert _never_crossed(plain_whale) > 0 and _never_crossed(newsy_whale) > 0
    assert _conserved(plain.accounting_totals(), plain.accounting_totals())
    assert _balances_ok(newsy)


def test_targeted_whales_conserve_balances_through_an_event_window():
    whales = [_accumulator(target=0.5), _distributor(target=0.35)]
    sim = _sim(whales, traders=_all_five(), events=_news())
    totals = sim.accounting_totals()
    sim.run(120)
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    assert all(_never_crossed(w) >= 0 for w in whales)


# --- funded whales + manipulation -----------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_a_targeted_whale_runs_alongside_a_manipulation_scenario_without_joining_it(scenario):
    settings = get_settings()
    whales = [WhaleSettings("acc", 0.0, activity_probability=0.4, max_trade_fraction=0.01,
                            starting_cash=200_000.0, behavior="accumulate", target_coin_fraction=0.5)]
    sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)), scenario=scenario)
    totals = sim.accounting_totals()
    ticks = sim.run(60)
    (whale,) = sim.whales
    assert {w.side for t in ticks for w in t.whale_trades} <= {"buy"}  # it only ever accumulates
    assert any(t.whale_trades for t in ticks)
    assert _conserved(totals, sim.accounting_totals()) and _balances_ok(sim)
    # The scheme still runs its own schedule; the whale is not part of it.
    reasons = {f.reason for t in ticks for f in t.trader_trades}
    assert reasons and not any(f.trader_id == "acc" for t in ticks for f in t.trader_trades)
    # Managed, not all-in: the target leaves it holding both sides.
    assert whale.wallet.cash > 0.0 and whale.wallet.coins > 0.0


# --- psychology on/off ----------------------------------------------------------------------------


def test_psychology_does_not_reach_a_targeted_whale():
    def run(psychology, traders):
        whales = [_accumulator(target=0.6), _distributor(target=0.3)]
        sim = _sim(whales, traders=traders, psychology=psychology, events=_news())
        ticks = sim.run(120)
        return ([t.whale_trades for t in ticks], [w._rng.getstate() for w in sim.whales],
                [w.state() for w in sim.whales])

    # With no traders psychology has no channel at all, so even the fills match.
    assert run(True, None) == run(False, None)
    # With traders it moves the price, so fills may differ — but the draws
    # the whales take must not.
    on, off = run(True, _all_five()), run(False, _all_five())
    assert on[1] == off[1]


def test_the_whale_module_still_reads_no_psychology_news_or_manipulation():
    tree = ast.parse(Path(whale_module.__file__).read_text())
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert not any(part in module for module in imported for part in ("psychology", "events", "manipulation"))
    source = Path(whale_module.__file__).read_text()
    assert not any(word in source for word in ("fear", "FOMO", "conviction", "uncertainty", "social"))


# --- AMM ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("make", [_accumulator, _distributor])
def test_amm_mode_still_rejects_targeted_whales(make):
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[make()], reserve_cash=2_000_000.0, pricing_mode="amm")


def test_a_target_in_the_config_does_not_make_amm_accept_whales():
    settings = get_settings()
    whales = [WhaleSettings("acc", 0.0, starting_cash=1_000.0, behavior="accumulate", target_coin_fraction=0.5)]
    tweaked = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales))
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        build_coin_simulator(tweaked, pricing_mode="amm")
    assert build_coin_simulator(tweaked, pricing_mode="amm", include_whales=False).whales == []


# --- configuration ---------------------------------------------------------------------------------


def test_a_configured_target_reaches_the_whale_and_drives_it():
    settings = get_settings()
    whales = [WhaleSettings("acc", 0.0, activity_probability=1.0, max_trade_fraction=0.05,
                            starting_cash=100_000.0, behavior="accumulate", target_coin_fraction=0.4)]
    sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)))
    (whale,) = sim.whales
    assert whale.target_coin_fraction == 0.4
    assert whale.allocation(sim.coin.starting_price).allocation_gap == 0.4
    sim.run(100)
    # The target is what stops it: the same whale without one spends every
    # last unit of cash on coins.
    assert whale.wallet.cash > 10_000.0 and whale.wallet.coins > 0.0
    untargeted = dataclasses.replace(whales[0], target_coin_fraction=None, behavior="accumulate")
    bare_sim = build_coin_simulator(
        dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=[untargeted])))
    bare_sim.run(100)
    assert bare_sim.whales[0].wallet.cash == 0.0
