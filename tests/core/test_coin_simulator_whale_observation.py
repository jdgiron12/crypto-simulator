"""Whale observation recording (Phase 8, Step 7).

``whale_observation=True`` records one read-only ``WhaleObservation`` per
whale per tick. It is a recording and nothing else: with it on, the
simulation must produce exactly what it produces with it off — same
prices, fills, balances, reserves, event and psychology state, and the
same RNG sequence and final state.
"""

import dataclasses
import random

import pytest

from crypto_simulator.config import WhaleSettings, get_settings
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.events import EventEngine, MarketEvent
from crypto_simulator.core.events.generator import RandomEventGenerator
from crypto_simulator.analytics.whales import (
    BLOCKED_BY_COOLDOWN,
    BLOCKED_BY_INTERVAL,
    HELD_AT_TARGET,
    INACTIVE,
    NO_FILL,
    TRADED,
    analyze_whales,
    classify,
)
from crypto_simulator.core.whale import (
    TARGET_DEAD_ZONE,
    Whale,
    WhaleAllocation,
    WhaleAttempt,
    WhaleBehavior,
    WhaleObservation,
)
from crypto_simulator.models.wallet import Wallet
from crypto_simulator.services.coin_simulation import build_coin_simulator
from tests.core.test_coin_simulator_traders import _all_five, _coin

SUPPLY = 1_000_000.0


def _acc(whale_id="acc", cash=400_000.0, coins=0.0, seed=21, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale(whale_id, coins, starting_cash=cash, behavior="accumulate", seed=seed, **kwargs)


def _dist(whale_id="dist", cash=0.0, coins=120_000.0, seed=22, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale(whale_id, coins, starting_cash=cash, behavior="distribute", seed=seed, **kwargs)


def _legacy(whale_id="legacy", holdings=50_000.0, seed=23, **kwargs):
    kwargs.setdefault("activity_probability", 0.5)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale(whale_id, holdings, seed=seed, **kwargs)


def _sim(whales, traders=None, **kwargs):
    return CoinSimulator(_coin(), seed=3, whales=whales, traders=traders, reserve_cash=500_000.0, **kwargs)


def _news():
    return EventEngine([MarketEvent(event_id="n", category="custom", severity=0.8, sentiment=-0.7,
                                    volatility_boost=1.0, attention=1.0, start_tick=5, duration=20)])


def _run_view(sim, ticks):
    """Everything that must be identical with observation on or off."""
    out = sim.run(ticks)
    # `timestamp` is excluded on purpose: SimulationClock stamps
    # `datetime.now()` at construction, so it differs between any two
    # simulators and says nothing about the simulation.
    return ([(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades,
              t.pool_state, t.event_state, t.psychology) for t in out],
            [(w.whale_id, w.holdings, w.state(), w.cycle_state(), w.intent_strength,
              w.interval_remaining, w._rng.getstate()) for w in sim.whales],
            [(tr.trader_id, tr.wallet.cash, tr.wallet.coins, tr.wallet.average_cost) for tr in sim.traders],
            (sim.reserve.cash, sim.reserve.coins), sim.accounting_totals())


# --- the flag ----------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [1, 0, "yes", None, [], 1.0])
def test_the_flag_must_be_a_bool(value):
    with pytest.raises(ValueError, match="whale_observation"):
        CoinSimulator(_coin(), whale_observation=value)


def test_observation_is_off_by_default():
    sim = _sim([_acc()], traders=_all_five())
    assert sim.whale_observation_enabled is False
    assert all(t.whale_observations == () for t in sim.run(60))


def test_the_flag_is_reachable_through_the_builder():
    sim = build_coin_simulator(get_settings(), whale_observation=True)
    assert sim.whale_observation_enabled is True
    assert all(len(t.whale_observations) == 1 for t in sim.run(20))
    assert build_coin_simulator(get_settings()).whale_observation_enabled is False


# --- observation ON == observation OFF ------------------------------------------------------------


@pytest.mark.parametrize("with_traders", [False, True])
@pytest.mark.parametrize("psychology", [False, True])
def test_recording_changes_nothing_about_the_simulation(with_traders, psychology):
    def run(observe):
        whales = [_acc(target_coin_fraction=0.6), _dist(target_coin_fraction=0.2, cooldown_ticks=2),
                  _legacy(), _acc("cycled", seed=24, cycle=[{"behavior": "accumulate", "duration": 8},
                                                            {"behavior": "distribute", "duration": 8}])]
        sim = _sim(whales, traders=_all_five() if with_traders else None, events=_news(),
                   psychology=psychology, whale_observation=observe)
        return _run_view(sim, 200)

    assert run(True) == run(False)


def test_recording_changes_nothing_with_a_random_event_generator():
    def run(observe):
        sim = _sim([_acc(), _legacy()], traders=_all_five(),
                   event_generator=RandomEventGenerator(probability=0.1, seed=777),
                   whale_observation=observe)
        return _run_view(sim, 150)

    assert run(True) == run(False)


def test_recording_draws_no_randomness():
    class _Recording:
        def __init__(self, seed):
            self._inner = random.Random(seed)
            self.calls = []

        def random(self):
            self.calls.append("random")
            return self._inner.random()

        def choice(self, seq):
            self.calls.append("choice")
            return self._inner.choice(seq)

        def uniform(self, a, b):
            self.calls.append("uniform")
            return self._inner.uniform(a, b)

        def getstate(self):
            return self._inner.getstate()

    def calls(observe):
        whale = _acc(target_coin_fraction=0.6, seed=9)
        whale._rng = _Recording(9)
        sim = _sim([whale], traders=_all_five(), whale_observation=observe)
        sim.run(200)
        return whale._rng.calls, whale._rng.getstate()

    assert calls(True) == calls(False)


def test_recording_conserves_coins_and_cash_exactly_as_before():
    def totals(observe):
        whales = [_acc(target_coin_fraction=0.7), _dist(target_coin_fraction=0.3), _legacy()]
        sim = _sim(whales, traders=_all_five(), whale_observation=observe)
        before = sim.accounting_totals()
        for _ in range(300):
            sim.step()
            wallets = [sim.reserve, *(t.wallet for t in sim.traders),
                       *(w.wallet for w in sim.whales if w.funded)]
            assert all(w.cash >= 0.0 and w.coins >= 0.0 for w in wallets)
        return before, sim.accounting_totals(), (sim.reserve.cash, sim.reserve.coins)

    on, off = totals(True), totals(False)
    assert on == off  # the recording changes no balance anywhere
    # Conservation itself holds to float precision, as elsewhere in the
    # project; the point here is that observation does not affect it.
    assert all(float(abs(a - b)) <= 1e-9 * float(abs(b)) for a, b in zip(on[1], on[0]))


# --- what gets recorded --------------------------------------------------------------------------


def test_one_observation_per_whale_per_tick_in_whale_list_order():
    whales = [_acc("a"), _dist("b"), _legacy("c")]
    sim = _sim(whales, whale_observation=True)
    ticks = sim.run(40)
    assert all(len(t.whale_observations) == 3 for t in ticks)
    assert all([o.whale_id for o in t.whale_observations] == ["a", "b", "c"] for t in ticks)


def test_an_observation_is_immutable():
    sim = _sim([_acc()], whale_observation=True)
    observation = sim.run(1)[0].whale_observations[0]
    assert isinstance(observation, WhaleObservation)
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.price = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.trade = None


def test_the_recorded_state_is_the_state_in_force_for_that_tick():
    cycle = [{"behavior": "accumulate", "duration": 4}, {"behavior": "distribute", "duration": 4}]
    whale = _acc("w", cash=1e9, coins=200_000.0, activity_probability=1.0, cycle=cycle,
                 intent_strength=1.5, target_coin_fraction=0.5)
    sim = _sim([whale], whale_observation=True)
    ticks = sim.run(16)
    behaviors = [t.whale_observations[0].behavior for t in ticks]
    assert behaviors == ([WhaleBehavior.ACCUMULATE] * 4 + [WhaleBehavior.DISTRIBUTE] * 4) * 2
    assert [t.whale_observations[0].cycle_phase_index for t in ticks] == [0] * 4 + [1] * 4 + [0] * 4 + [1] * 4
    assert [t.whale_observations[0].cycle_phase_elapsed for t in ticks] == [0, 1, 2, 3] * 4
    assert all(t.whale_observations[0].intent_strength == 1.5 for t in ticks)
    # The behavior recorded is the one the trade was made under.
    for tick in ticks:
        observation = tick.whale_observations[0]
        if observation.trade is not None:
            expected = "buy" if observation.behavior is WhaleBehavior.ACCUMULATE else "sell"
            assert observation.trade.side == expected


def test_a_whale_without_a_cycle_records_no_phase():
    sim = _sim([_acc()], whale_observation=True)
    for tick in sim.run(20):
        observation = tick.whale_observations[0]
        assert observation.cycle_phase_index is None and observation.cycle_phase_elapsed is None


def test_the_trade_recorded_is_the_trade_the_tick_produced():
    sim = _sim([_acc("a"), _dist("b")], traders=_all_five(), whale_observation=True)
    for tick in sim.run(200):
        recorded = [o.trade for o in tick.whale_observations if o.trade is not None]
        assert recorded == list(tick.whale_trades)


def test_balances_are_recorded_after_the_tick():
    whale = _acc(cash=400_000.0, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for _ in range(30):
        tick = sim.step()
        observation = tick.whale_observations[0]
        assert observation.cash == whale.wallet.cash and observation.coins == whale.wallet.coins


def test_pacing_counters_are_recorded_from_before_the_tick():
    whale = _acc(cash=1e9, activity_probability=1.0, cooldown_ticks=2, min_trade_interval_ticks=3)
    sim = _sim([whale], whale_observation=True)
    ticks = sim.run(12)
    observed = [(o.cooldown_remaining, o.interval_remaining, o.trade is not None)
                for o in (t.whale_observations[0] for t in ticks)]
    assert observed[:4] == [(0, 0, True), (2, 3, False), (1, 2, False), (0, 1, False)]
    assert observed[4] == (0, 0, True)  # eligible again on the fourth blocked tick's successor


# --- the recorded price is the whale's own fill price ------------------------------------------------


def test_the_recorded_price_is_the_one_that_whale_settled_at():
    """With one whale and no traders the tick price is the fill price times
    that whale's own impact, so the recording can be checked exactly."""
    whale = _acc(cash=1e9, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(40):
        observation = tick.whale_observations[0]
        if observation.trade is None:
            continue
        assert tick.price == pytest.approx(observation.price * observation.trade.price_impact, rel=1e-12)


def test_each_whale_records_the_price_before_later_whales_moved_it():
    first, second = _acc("first", cash=1e9, activity_probability=1.0), _acc("second", cash=1e9,
                                                                            activity_probability=1.0, seed=25)
    sim = _sim([first, second], whale_observation=True)
    for tick in sim.run(40):
        a, b = tick.whale_observations
        assert a.price <= b.price  # the first whale buys, lifting the price for the second
        if a.trade is not None:
            assert b.price == pytest.approx(a.price * a.trade.price_impact, rel=1e-12)
        else:
            assert b.price == a.price


def test_the_recorded_price_is_what_the_fill_actually_cost():
    whale = _acc(cash=1e9, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(40):
        observation = tick.whale_observations[0]
        if observation.trade is None:
            continue
        spent = observation.allocation_before.portfolio_value - observation.allocation_after.portfolio_value
        # Trading at the mark price is portfolio-value neutral, so the
        # recorded price is the one the allocation arithmetic used.
        assert spent == pytest.approx(0.0, abs=1e-6)
        gained = observation.trade.quantity * observation.price
        assert observation.allocation_after.coin_value == pytest.approx(
            observation.allocation_before.coin_value + gained)


# --- allocations ---------------------------------------------------------------------------------------


def test_allocations_bracket_the_trade_at_the_fill_price():
    whale = _acc(cash=600_000.0, coins=100_000.0, target_coin_fraction=0.5, activity_probability=0.8)
    sim = _sim([whale], traders=_all_five(), whale_observation=True)
    filled = 0
    for tick in sim.run(300):
        observation = tick.whale_observations[0]
        assert isinstance(observation.allocation_before, WhaleAllocation)
        assert observation.allocation_before.price == observation.price
        assert observation.allocation_after.price == observation.price
        if observation.trade is None:
            assert observation.allocation_before == observation.allocation_after
            continue
        filled += 1
        assert (observation.allocation_before.coin_fraction
                < observation.allocation_after.coin_fraction <= 0.5 + TARGET_DEAD_ZONE)
    assert filled > 10


def test_an_unfunded_whale_records_no_allocation_and_no_cash():
    sim = _sim([_legacy()], whale_observation=True)
    for tick in sim.run(40):
        observation = tick.whale_observations[0]
        assert observation.funded is False
        assert observation.allocation_before is None and observation.allocation_after is None
        assert observation.cash is None
        assert observation.coins >= 0.0  # it still holds coins


# --- edge cases ------------------------------------------------------------------------------------------


def test_a_simulation_with_no_whales_records_nothing():
    sim = _sim([], traders=_all_five(), whale_observation=True)
    assert all(t.whale_observations == () for t in sim.run(40))


def test_amm_mode_records_no_whale_observations():
    sim = build_coin_simulator(get_settings(), pricing_mode="amm", include_whales=False,
                               whale_observation=True)
    ticks = sim.run(60)
    assert all(t.whale_observations == () for t in ticks)
    assert sim.whales == []


def test_amm_still_rejects_whales_with_observation_on():
    with pytest.raises(ValueError, match="Whales are not supported with pricing_mode='amm'"):
        CoinSimulator(_coin(), seed=3, whales=[_acc()], reserve_cash=2e6, pricing_mode="amm",
                      whale_observation=True)


def test_blocked_and_inactive_ticks_are_still_recorded():
    whale = _acc(cash=1e9, activity_probability=0.3, cooldown_ticks=3, seed=31)
    sim = _sim([whale], whale_observation=True)
    ticks = sim.run(120)
    assert all(len(t.whale_observations) == 1 for t in ticks)
    kinds = {(o.trade is not None, o.cooldown_remaining > 0)
             for o in (t.whale_observations[0] for t in ticks)}
    assert (True, False) in kinds and (False, True) in kinds and (False, False) in kinds


def test_a_broke_whale_records_attempts_that_filled_nothing():
    whale = _acc(cash=0.0, coins=0.0, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(20):
        observation = tick.whale_observations[0]
        assert observation.trade is None and observation.cash == 0.0
        assert observation.cooldown_remaining == 0 and observation.interval_remaining == 0


# --- determinism -----------------------------------------------------------------------------------------


def test_the_same_seed_records_the_same_observations():
    def run():
        whales = [_acc(target_coin_fraction=0.6), _dist(target_coin_fraction=0.2), _legacy()]
        sim = _sim(whales, traders=_all_five(), events=_news(), psychology=True, whale_observation=True)
        return [t.whale_observations for t in sim.run(200)]

    assert run() == run()


def test_observe_is_read_only_and_draws_nothing():
    whale = _acc(cash=400_000.0, coins=50_000.0, target_coin_fraction=0.5, cooldown_ticks=2)
    reserve = Wallet(cash=1e9, coins=1e9)
    before = (whale.wallet.cash, whale.wallet.coins, whale.behavior, whale.intent_strength,
              whale.state(), whale.interval_remaining, whale._rng.getstate())
    for _ in range(10):
        whale.observe(2.0)
    assert (whale.wallet.cash, whale.wallet.coins, whale.behavior, whale.intent_strength,
            whale.state(), whale.interval_remaining, whale._rng.getstate()) == before
    assert (reserve.cash, reserve.coins) == (1e9, 1e9)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), "2", None, True])
def test_observe_rejects_an_unusable_price(bad):
    with pytest.raises(ValueError, match="price"):
        _acc().observe(bad)


def test_completing_another_whales_snapshot_is_rejected():
    a, b = _acc("a"), _acc("b")
    snapshot = a.observe(2.0)
    with pytest.raises(ValueError, match="belongs to whale"):
        b.complete_observation(snapshot, None)


# --- manipulation ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["pump_and_dump", "wash_trading"])
def test_observation_does_not_disturb_a_manipulation_scenario(scenario):
    def run(observe):
        settings = get_settings()
        whales = [WhaleSettings("w", 20_000.0, activity_probability=0.5, max_trade_fraction=0.005,
                                starting_cash=200_000.0, behavior="accumulate", target_coin_fraction=0.5)]
        sim = build_coin_simulator(
            dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales)),
            scenario=scenario, whale_observation=observe)
        return _run_view(sim, 80)

    assert run(True) == run(False)


# --- the recorded attempt: NO_FILL vs INACTIVE (Phase 8, Step 7 audit fix) ---------------------
#
# These drive the real execution path rather than hand-built records: the
# distinction has to come from what the whale actually did.


def test_an_inactive_activity_check_records_inactive():
    """A. The activity check said no, so nothing was attempted."""
    whale = _acc(cash=1e9, coins=0.0, activity_probability=0.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(30):
        observation = tick.whale_observations[0]
        assert observation.attempt is WhaleAttempt.INACTIVE
        assert observation.trade is None and classify(observation) == INACTIVE


def test_an_exhausted_reserve_records_no_fill_not_inactive():
    """B. The case the balance-based inference got wrong: the activity
    check passed and settlement clamped to nothing because the reserve had
    no coins — while the whale itself was flush with cash."""
    whale = _acc(cash=1e9, coins=0.0, activity_probability=1.0)
    sim = CoinSimulator(_coin(), seed=3, whales=[whale], reserve_cash=500_000.0,
                        whale_observation=True)
    sim.reserve.withdraw_coins(sim.reserve.coins)  # drain the reserve's coins
    for tick in sim.run(25):
        observation = tick.whale_observations[0]
        assert observation.cash > 0.0  # it had every means to buy
        assert observation.attempt is WhaleAttempt.NO_FILL
        assert classify(observation) == NO_FILL
    summary = analyze_whales(sim.history).whale("acc")
    assert summary.no_fill_ticks == 25 and summary.inactive_ticks == 0


def test_a_whale_with_no_cash_also_records_no_fill():
    whale = _acc(cash=0.0, coins=0.0, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(20):
        observation = tick.whale_observations[0]
        assert observation.attempt is WhaleAttempt.NO_FILL
        assert classify(observation) == NO_FILL


def test_a_successful_fill_records_filled():
    """C."""
    whale = _acc(cash=1e9, coins=0.0, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(20):
        observation = tick.whale_observations[0]
        assert observation.attempt is WhaleAttempt.FILLED
        assert observation.trade is not None and observation.trade.quantity > 0
        assert classify(observation) == TRADED


def test_cooldown_records_blocked_and_takes_precedence():
    """D."""
    whale = _acc(cash=1e9, coins=0.0, activity_probability=1.0, cooldown_ticks=2)
    sim = _sim([whale], whale_observation=True)
    outcomes = [classify(t.whale_observations[0]) for t in sim.run(9)]
    attempts = [t.whale_observations[0].attempt for t in sim.history]
    assert outcomes == [TRADED, BLOCKED_BY_COOLDOWN, BLOCKED_BY_COOLDOWN] * 3
    assert attempts == [WhaleAttempt.FILLED, WhaleAttempt.BLOCKED, WhaleAttempt.BLOCKED] * 3


def test_the_interval_records_blocked_once_cooldown_is_zero():
    """E. Cooldown 1, interval 3: the first blocked tick is the cooldown's,
    the rest the interval's."""
    whale = _acc(cash=1e9, coins=0.0, activity_probability=1.0, cooldown_ticks=1,
                 min_trade_interval_ticks=3)
    sim = _sim([whale], whale_observation=True)
    outcomes = [classify(t.whale_observations[0]) for t in sim.run(8)]
    assert outcomes == [TRADED, BLOCKED_BY_COOLDOWN, BLOCKED_BY_INTERVAL, BLOCKED_BY_INTERVAL] * 2
    assert all(t.whale_observations[0].attempt is WhaleAttempt.BLOCKED
               for t in sim.history if t.whale_observations[0].trade is None)


def test_sitting_on_the_target_records_held():
    """F."""
    whale = _acc(cash=50_000.0, coins=25_000.0, target_coin_fraction=0.5, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    ticks = sim.run(30)
    held = [t.whale_observations[0] for t in ticks if t.whale_observations[0].trade is None]
    assert held and all(o.attempt is WhaleAttempt.HELD for o in held)
    assert all(classify(o) == HELD_AT_TARGET for o in held)


def test_an_accumulator_past_its_target_records_held_not_no_fill():
    whale = _acc(cash=100.0, coins=1_000.0, target_coin_fraction=0.5, activity_probability=1.0)
    sim = _sim([whale], whale_observation=True)
    for tick in sim.run(20):
        observation = tick.whale_observations[0]
        assert observation.attempt is WhaleAttempt.HELD
        assert classify(observation) == HELD_AT_TARGET


def test_a_neutral_whale_with_a_dormant_target_is_never_held():
    """Neutral ignores its target, so nothing is ever held by it."""
    whale = _acc(cash=1e9, coins=200_000.0, target_coin_fraction=0.5, activity_probability=1.0)
    whale.set_behavior("neutral")
    sim = _sim([whale], whale_observation=True)
    attempts = {t.whale_observations[0].attempt for t in sim.run(30)}
    assert WhaleAttempt.HELD not in attempts


def test_every_recorded_attempt_agrees_with_what_the_tick_produced():
    """Across a busy mixed run, the recorded attempt and the trade record
    never contradict each other."""
    whales = [_acc(target_coin_fraction=0.6, cooldown_ticks=2, min_trade_interval_ticks=2),
              _dist(target_coin_fraction=0.3), _legacy(),
              _acc("broke", cash=0.0, coins=0.0, activity_probability=1.0)]
    sim = _sim(whales, traders=_all_five(), whale_observation=True)
    seen = set()
    for tick in sim.run(400):
        for observation in tick.whale_observations:
            seen.add(observation.attempt)
            if observation.attempt is WhaleAttempt.FILLED:
                assert observation.trade is not None and observation.trade.quantity > 0
            else:
                assert observation.trade is None or observation.trade.quantity == 0.0
            if observation.attempt is WhaleAttempt.BLOCKED:
                assert observation.cooldown_remaining > 0 or observation.interval_remaining > 0
            else:
                assert observation.cooldown_remaining == 0 and observation.interval_remaining == 0
    assert seen == set(WhaleAttempt)  # every branch exercised


def test_the_marker_does_not_disturb_the_simulation():
    """G/H/I. Recording the attempt is still a pure side-record: prices,
    fills, balances, reserves, RNG and accounting are untouched by the
    flag."""
    def run(observe):
        whales = [_acc(target_coin_fraction=0.6, cooldown_ticks=2), _dist(target_coin_fraction=0.2),
                  _legacy(), _acc("broke", cash=0.0, coins=0.0)]
        sim = _sim(whales, traders=_all_five(), events=_news(), psychology=True,
                   whale_observation=observe)
        return _run_view(sim, 250)

    assert run(True) == run(False)
