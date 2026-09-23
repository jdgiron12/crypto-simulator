"""The lag-1 organic crowd-flow observation (Phase 19, Step 2).

Step 2 adds an *observation*: ``crowd_observation=True`` puts the previous
completed tick's organic signed flow on each tick's ``MarketContext`` as
``crowd_flow``. Every test here is about what the number *is* and about
the observation on its own leaving the run unchanged. What a trader does
with it is Steps 4 and 7's, and lives in
``tests/core/traders/test_crowd_response.py`` (participation) and
``test_crowd_direction.py`` (direction); the identity tests below still
hold because every ``crowd_sensitivity`` and every
``crowd_direction_sensitivity`` is 0 unless a caller asks for that
response.

Covered: the first tick has no observation; a tick sees exactly tick
t - 1 and never its own flow; organic fills count; manipulator fills and
wash legs do not; the sign; the normalization and its bound; no extra
random draws; and default-off identity in both pricing modes, with
psychology off and on, and under a Phase 17 market condition.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from crypto_simulator.config.settings import DEFAULT_CONFIG_PATH, build_settings
from crypto_simulator.core.coin_simulator import CoinSimulator, organic_crowd_flow
from crypto_simulator.core.events.engine import EventEngine
from crypto_simulator.core.events.event import MarketEvent
from crypto_simulator.core.traders.base import (
    MarketContext,
    PsychologyContext,
    TradeAction,
    TradeDecision,
    TraderAgent,
)
from crypto_simulator.core.traders.execution import TraderTrade
from crypto_simulator.core.traders.manipulation import PumpAndDump, WashTrader
from crypto_simulator.core.traders.strategies import MomentumTrader, RetailTrader
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.coin import Coin
from crypto_simulator.services.coin_simulation import build_coin_simulator
from crypto_simulator.services.market_conditions import apply_market_condition

SUPPLY = 1_000_000.0


def _coin():
    return Coin("FIC", "FictiCoin (Simulated)", SUPPLY, 1.0)


def _fill(strategy, side, quantity, *, wash=False, trader_id="t"):
    return TraderTrade(
        trader_id=trader_id,
        strategy=strategy,
        side=side,
        requested_quantity=quantity,
        quantity=quantity,
        price=1.0,
        notional=quantity,
        wash=wash,
    )


class _Recorder(TraderAgent):
    """Records the context it is handed and never trades, so the ticks it
    observes are not the ticks it changes."""

    strategy_name = "recorder"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def _decide(self, context):
        self.seen.append(context)
        return TradeDecision.hold("recording")


class _Scripted(TraderAgent):
    """Buys or sells a fixed quantity on the ticks it is told to, so the
    flow a later tick should observe is known exactly."""

    strategy_name = "scripted"

    def __init__(self, trader_id, script, **kwargs):
        super().__init__(trader_id, **kwargs)
        self.script = script

    def _decide(self, context):
        action = self.script.get(context.tick)
        if action is None:
            return TradeDecision.hold("nothing scripted")
        side, quantity = action
        return TradeDecision(side, quantity, "scripted")


def _sim(traders, *, mode="random_walk", crowd=True, **kwargs):
    return CoinSimulator(
        _coin(),
        seed=7,
        traders=traders,
        reserve_cash=2_000_000.0,
        pricing_mode=mode,
        crowd_observation=crowd,
        **kwargs,
    )


def _settings():
    import yaml

    with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as handle:
        return build_settings(yaml.safe_load(handle), DEFAULT_CONFIG_PATH)


def _run_digest(sim, ticks):
    """Everything the run produced plus every RNG stream's end state, so an
    extra draw anywhere shows as a difference."""
    return (
        [
            (t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades,
             t.pool_state, t.event_state, t.psychology)
            for t in ticks
        ],
        [(tr.trader_id, tr.wallet.cash, tr.wallet.coins, tr.wallet.average_cost) for tr in sim.traders],
        [(w.whale_id, w.holdings, w._rng.getstate()) for w in sim.whales],
        (sim.reserve.cash, sim.reserve.coins),
        sim.accounting_totals(),
        sim._price_engine._rng.getstate(),
        sim._volume_model._rng.getstate(),
        [tr._rng.getstate() for tr in sim.traders],
    )


# --- A: the first tick has no observation -----------------------------------------------------------


def test_the_first_tick_has_no_previous_flow_to_observe():
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([recorder])
    sim.run(3)
    assert recorder.seen[0].crowd_flow is None
    assert all(c.crowd_flow is not None for c in recorder.seen[1:])


def test_before_any_tick_the_observation_is_none():
    sim = _sim([_Recorder("rec", trade_probability=1.0)])
    assert sim.observed_crowd_flow() is None


def test_none_means_no_observation_not_a_flow_of_zero():
    """A quiet previous tick reports 0.0; *no* previous tick reports None.
    The two are different facts and are never conflated."""
    quiet = _Scripted("s", {}, trade_probability=1.0, starting_cash=10_000.0)
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([quiet, recorder])
    sim.run(2)
    assert recorder.seen[0].crowd_flow is None
    assert recorder.seen[1].crowd_flow == 0.0


# --- B, C: lag-1, and no leak from the tick being simulated ------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_a_tick_observes_exactly_the_previous_completed_ticks_flow(mode):
    scripted = _Scripted(
        "s",
        {1: (TradeAction.BUY, 1_000.0), 2: (TradeAction.SELL, 400.0), 3: (TradeAction.BUY, 250.0)},
        trade_probability=1.0,
        starting_cash=100_000.0,
        starting_coins=50_000.0,
        max_trade_size=10_000.0,
    )
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([scripted, recorder], mode=mode)
    ticks = sim.run(4)

    def organic(tick):
        return sum(
            (f.quantity if f.side is TradeAction.BUY else -f.quantity)
            for f in tick.trader_trades
            if not f.wash
        ) / SUPPLY

    # Tick n's context carries tick n-1's flow, for every n.
    for n in range(1, len(ticks)):
        assert recorder.seen[n].crowd_flow == pytest.approx(organic(ticks[n - 1]), abs=1e-15)


def test_the_current_ticks_own_flow_cannot_reach_its_own_context():
    """The scripted trader buys on tick 1 only. Tick 1's context must not
    see that buy; tick 2's must."""
    scripted = _Scripted(
        "s", {1: (TradeAction.BUY, 5_000.0)}, trade_probability=1.0, starting_cash=100_000.0
    )
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([scripted, recorder])
    ticks = sim.run(2)
    assert ticks[0].trader_trades  # the buy really happened on tick 1
    assert recorder.seen[0].crowd_flow is None
    assert recorder.seen[1].crowd_flow > 0


def test_the_observation_is_the_finished_tick_not_the_one_being_built():
    """``observed_crowd_flow`` after n steps equals what step n+1 sees."""
    scripted = _Scripted(
        "s",
        {1: (TradeAction.BUY, 3_000.0), 2: (TradeAction.SELL, 1_000.0)},
        trade_probability=1.0,
        starting_cash=100_000.0,
        starting_coins=50_000.0,
    )
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([scripted, recorder])
    for expected_index in range(3):
        before_step = sim.observed_crowd_flow()
        sim.step()
        assert recorder.seen[expected_index].crowd_flow == before_step


# --- D, E, F, G: what counts as organic, and the sign ------------------------------------------------


def test_organic_fills_are_included_and_the_sign_follows_the_side():
    buy = organic_crowd_flow([_fill("retail", TradeAction.BUY, 2_000.0)], SUPPLY)
    sell = organic_crowd_flow([_fill("retail", TradeAction.SELL, 2_000.0)], SUPPLY)
    assert buy == pytest.approx(0.002) and sell == pytest.approx(-0.002)
    assert organic_crowd_flow([], SUPPLY) == 0.0


def test_net_buying_is_positive_and_net_selling_negative_across_traders():
    trades = [
        _fill("retail", TradeAction.BUY, 3_000.0, trader_id="a"),
        _fill("momentum", TradeAction.BUY, 1_000.0, trader_id="b"),
        _fill("panic_seller", TradeAction.SELL, 1_500.0, trader_id="c"),
    ]
    assert organic_crowd_flow(trades, SUPPLY) == pytest.approx(0.0025)
    flipped = [dataclasses.replace(t, side=TradeAction.SELL if t.side is TradeAction.BUY else TradeAction.BUY)
               for t in trades]
    assert organic_crowd_flow(flipped, SUPPLY) == pytest.approx(-0.0025)


def test_balanced_organic_flow_is_exactly_zero():
    trades = [
        _fill("retail", TradeAction.BUY, 1_234.5, trader_id="a"),
        _fill("dip_buyer", TradeAction.SELL, 1_234.5, trader_id="b"),
    ]
    assert organic_crowd_flow(trades, SUPPLY) == 0.0


def test_manipulator_fills_are_excluded_by_their_recorded_strategy():
    """Identification is the registry label, never the behavior."""
    trades = [
        _fill("retail", TradeAction.BUY, 1_000.0, trader_id="a"),
        _fill(PumpAndDump.strategy_name, TradeAction.BUY, 500_000.0, trader_id="pump"),
    ]
    assert organic_crowd_flow(trades, SUPPLY) == pytest.approx(0.001)


def test_wash_legs_are_excluded_whoever_made_them():
    """Both legs, and a wash leg printed by an organic strategy too."""
    trades = [
        _fill("retail", TradeAction.BUY, 1_000.0, trader_id="a"),
        _fill(WashTrader.strategy_name, TradeAction.BUY, 9_000.0, wash=True, trader_id="w"),
        _fill(WashTrader.strategy_name, TradeAction.SELL, 9_000.0, wash=True, trader_id="w"),
        _fill("retail", TradeAction.BUY, 4_000.0, wash=True, trader_id="a"),
    ]
    assert organic_crowd_flow(trades, SUPPLY) == pytest.approx(0.001)


def test_a_manipulated_market_reports_only_the_organic_crowd_in_a_real_run():
    pump = PumpAndDump(
        "pump", start_tick=1, accumulate_ticks=1, pump_ticks=1, dump_ticks=1,
        trade_probability=1.0, starting_cash=200_000.0, max_trade_size=100_000.0, risk_tolerance=1.0,
    )
    wash = WashTrader("wash", trade_probability=1.0, starting_cash=50_000.0, risk_tolerance=1.0)
    retail = RetailTrader("retail", trade_probability=1.0, starting_cash=10_000.0, starting_coins=10_000.0, seed=1)
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([retail, pump, wash, recorder])
    ticks = sim.run(6)
    for n in range(1, len(ticks)):
        previous = ticks[n - 1].trader_trades
        assert any(f.strategy in ("pump_and_dump", "wash_trader") or f.wash for f in previous)
        organic = sum(
            (f.quantity if f.side is TradeAction.BUY else -f.quantity)
            for f in previous
            if not f.wash and f.strategy not in ("pump_and_dump", "wash_trader")
        )
        assert recorder.seen[n].crowd_flow == pytest.approx(organic / SUPPLY, abs=1e-15)


def test_whale_trades_are_not_trader_fills_and_never_reach_the_signal():
    whale = Whale("w", 100_000.0, activity_probability=1.0, max_trade_fraction=0.03, seed=3)
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = _sim([recorder], whales=[whale])
    ticks = sim.run(5)
    assert any(t.whale_trades for t in ticks)  # the whale really traded
    assert all(c.crowd_flow in (None, 0.0) for c in recorder.seen)


# --- H, I: normalization and bound -------------------------------------------------------------------


def test_normalization_is_the_supply_and_is_deterministic():
    trades = [_fill("retail", TradeAction.BUY, 2_500.0)]
    assert organic_crowd_flow(trades, SUPPLY) == 2_500.0 / SUPPLY
    assert organic_crowd_flow(trades, 500_000.0) == 2_500.0 / 500_000.0
    assert organic_crowd_flow(trades, SUPPLY) == organic_crowd_flow(trades, SUPPLY)


def test_the_sum_is_exact_so_recording_order_does_not_matter():
    rng = random.Random(11)
    trades = [
        _fill("retail", rng.choice((TradeAction.BUY, TradeAction.SELL)), rng.uniform(0.0, 5_000.0),
              trader_id=f"t{i}")
        for i in range(40)
    ]
    shuffled = trades[:]
    rng.shuffle(shuffled)
    assert organic_crowd_flow(trades, SUPPLY) == organic_crowd_flow(shuffled, SUPPLY)


def test_the_observation_stays_within_its_bound():
    huge_buy = [_fill("retail", TradeAction.BUY, SUPPLY * 5)]
    huge_sell = [_fill("retail", TradeAction.SELL, SUPPLY * 5)]
    assert organic_crowd_flow(huge_buy, SUPPLY) == 1.0
    assert organic_crowd_flow(huge_sell, SUPPLY) == -1.0


@pytest.mark.parametrize("supply", [0.0, -1.0, float("inf"), float("nan"), True, "1000"])
def test_an_invalid_supply_is_rejected_rather_than_producing_a_number(supply):
    with pytest.raises(ValueError, match="total_supply"):
        organic_crowd_flow([_fill("retail", TradeAction.BUY, 1.0)], supply)


@pytest.mark.parametrize("value", [1, 0, "yes", None])
def test_the_flag_must_be_a_bool(value):
    with pytest.raises(ValueError, match="crowd_observation must be True or False"):
        CoinSimulator(_coin(), seed=1, crowd_observation=value)


def test_the_accessor_needs_the_feature_to_be_on():
    sim = CoinSimulator(_coin(), seed=1)
    sim.run(2)
    with pytest.raises(RuntimeError, match="crowd_observation=True"):
        sim.observed_crowd_flow()


# --- J: no extra randomness --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_the_observation_draws_no_randomness(mode):
    """Same seed, feature off vs on: every RNG stream ends in the same
    state, so not one extra draw was taken."""
    def run(crowd):
        traders = [
            RetailTrader("retail", trade_probability=0.7, starting_cash=10_000.0, starting_coins=10_000.0, seed=4),
            MomentumTrader("momentum", trade_probability=0.7, starting_cash=10_000.0, starting_coins=10_000.0, seed=5),
        ]
        sim = _sim(traders, mode=mode, crowd=crowd)
        return _run_digest(sim, sim.run(60))

    assert run(True) == run(False)


def test_a_crowd_observation_run_touches_no_global_randomness():
    state = random.getstate()
    for mode in ("random_walk", "amm"):
        _sim([RetailTrader("r", trade_probability=1.0, starting_cash=10_000.0, seed=2)], mode=mode).run(30)
    assert random.getstate() == state


# --- K, L, M, N: the default-off (and observation-on) run is unchanged ---------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("psychology", [False, True])
def test_the_feature_is_off_by_default_and_contexts_carry_no_observation(mode, psychology):
    recorder = _Recorder("rec", trade_probability=1.0)
    sim = CoinSimulator(
        _coin(), seed=3, traders=[recorder], reserve_cash=2_000_000.0,
        pricing_mode=mode, psychology=psychology,
    )
    sim.run(5)
    assert sim.crowd_observation_enabled is False
    assert all(c.crowd_flow is None for c in recorder.seen)
    expected = PsychologyContext if psychology else MarketContext
    assert all(type(c) is expected for c in recorder.seen)


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
@pytest.mark.parametrize("psychology", [False, True])
def test_observation_on_is_identical_to_observation_off(mode, psychology):
    """Nothing consumes the value, so turning it on must change nothing —
    prices, fills, balances, events, psychology and every RNG state."""
    def run(crowd):
        traders = [
            RetailTrader("retail", trade_probability=0.6, starting_cash=10_000.0, starting_coins=10_000.0, seed=6),
            MomentumTrader("momentum", trade_probability=0.7, starting_cash=10_000.0, starting_coins=10_000.0, seed=7),
            WashTrader("wash", trade_probability=1.0, starting_cash=20_000.0, risk_tolerance=0.5, seed=8),
        ]
        sim = CoinSimulator(
            _coin(), seed=9, traders=traders, reserve_cash=2_000_000.0, pricing_mode=mode,
            psychology=psychology, crowd_observation=crowd,
            events=EventEngine([MarketEvent(event_id="e", category="custom", severity=0.8, sentiment=-0.6,
                                            volatility_boost=1.5, attention=2.0, start_tick=5, duration=6)]),
        )
        return _run_digest(sim, sim.run(40))

    assert run(True) == run(False)


@pytest.mark.parametrize("condition", ["bull", "bear", "meme"])
def test_a_phase_17_market_condition_run_is_unchanged_by_the_observation(condition):
    def run(crowd):
        settings = apply_market_condition(_settings(), condition, pricing_mode="random_walk")
        sim = build_coin_simulator(settings, psychology=True)
        sim.crowd_observation_enabled = crowd
        return _run_digest(sim, sim.run(60))

    assert run(True) == run(False)


def test_exactly_two_places_read_the_observation():
    """Step 2 added the observation, Step 4 its first reader and Step 7 its
    second. This is the guard the Step 2 version asked for when it said it
    should be updated "with a behavioral suite alongside it, not on its
    own" — those suites are ``tests/core/traders/test_crowd_response.py``
    and ``test_crowd_direction.py``.

    The invariant is a counted one: **exactly two** things read
    ``crowd_flow``, and they are the two named channel terms —
    ``crowd_pressure`` (its magnitude, for participation) and
    ``crowd_direction_tilt`` (its sign, for direction). A third reader
    appearing without this test being updated deliberately is the thing
    worth catching. No concrete strategy reads it, no manipulator reads
    it, and nothing in the psychology package has ever heard of it — the
    crowd never reaches ``compute_psychology``.
    """
    import inspect
    from pathlib import Path

    from crypto_simulator.core.psychology import signals, state
    from crypto_simulator.core.traders import base, manipulation, strategies

    base_source = Path(base.__file__).read_text()
    assert "crowd_flow: float | None" in base_source  # still declared here
    # Exactly two reads in the whole module, and they are the two channel
    # terms — asked of the function objects rather than of character
    # offsets, so moving or reformatting a method cannot quietly turn this
    # guard into a tautology.
    assert base_source.count(".crowd_flow") == 2, "crowd_flow must have exactly two readers"
    readers = (base.TraderAgent.crowd_pressure, base.TraderAgent.crowd_direction_tilt)
    for reader in readers:
        assert inspect.getsource(reader).count(".crowd_flow") == 1, reader.__name__

    # Concrete strategies name a sensitivity at most; they never read the
    # signal, because neither channel's transform is theirs to compute.
    for module in (strategies, manipulation):
        source = Path(module.__file__).read_text()
        assert "crowd_flow" not in source, module.__name__
    manipulation_source = Path(manipulation.__file__).read_text()
    assert "crowd_sensitivity" not in manipulation_source
    assert "crowd_direction_sensitivity" not in manipulation_source

    # Psychology is downstream of prices and events and nothing else.
    for module in (signals, state):
        assert "crowd" not in Path(module.__file__).read_text(), module.__name__
