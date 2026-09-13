"""Whale intent strength (Phase 8, Step 5).

``intent_strength`` scales how hard a directional whale leans: it
multiplies the size drawn for a trade before the target cap and
settlement clamp it. 1.0 is the default and changes nothing; neutral
whales ignore it; it survives behavior transitions; and it adds no
randomness and bypasses no constraint.
"""

import math
import random

import pytest

from crypto_simulator.core.whale import (
    INTENT_STRENGTH_DEFAULT,
    INTENT_STRENGTH_MAX,
    INTENT_STRENGTH_MIN,
    TARGET_DEAD_ZONE,
    Whale,
    WhaleBehavior,
    WhaleState,
)
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0
BEHAVIORS = ("neutral", "accumulate", "distribute")


def _whale(behavior="accumulate", cash=1e9, coins=1e6, seed=1, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.01)
    return Whale("w", coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _reserve(cash=1e15, coins=1e15):
    return Wallet(cash=cash, coins=coins)


def _run(whale, ticks, price=PRICE, reserve=None):
    reserve = _reserve() if reserve is None else reserve
    return [whale.maybe_trade(SUPPLY, price=price, reserve=reserve) for _ in range(ticks)], reserve


def _snapshot(whale):
    """Everything setting the intent must leave alone."""
    return (
        whale.behavior, whale.wallet.cash, whale.wallet.coins, whale.wallet.average_cost,
        whale.target_coin_fraction, whale.min_trade_fraction, whale.max_trade_fraction,
        whale.activity_probability, whale.cooldown_ticks, whale.min_trade_interval_ticks,
        whale.state().cooldown_remaining, whale.interval_remaining, whale._rng.getstate(),
    )


class _RecordingRNG:
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


# --- validation -----------------------------------------------------------------------------------


def test_the_documented_range_is_what_the_module_exposes():
    assert (INTENT_STRENGTH_MIN, INTENT_STRENGTH_DEFAULT, INTENT_STRENGTH_MAX) == (0.0, 1.0, 2.0)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0, 1.5, 2.0, 0.25, 1.999, 1, 2])
def test_values_inside_the_range_are_accepted(value):
    assert _whale(intent_strength=value).intent_strength == value
    whale = _whale()
    assert whale.set_intent_strength(value) == 1.0
    assert whale.intent_strength == value


@pytest.mark.parametrize(
    "bad",
    [-0.1, -1.0, 2.1, 3.0, 1e9, math.nan, math.inf, -math.inf, True, False, "1.0", None, [1.0], object()],
)
def test_values_outside_the_range_are_rejected_not_clamped(bad):
    with pytest.raises(ValueError, match="intent_strength"):
        _whale(intent_strength=bad)
    whale = _whale(intent_strength=1.5)
    with pytest.raises(ValueError, match="intent_strength"):
        whale.set_intent_strength(bad)
    assert whale.intent_strength == 1.5  # the rejected value never landed


def test_the_default_is_one_and_omitting_it_is_the_same_as_passing_it():
    assert _whale().intent_strength == 1.0
    a, b = _whale(seed=4), _whale(seed=4, intent_strength=1.0)
    ra, rb = _reserve(), _reserve()
    assert [a.maybe_trade(SUPPLY, price=PRICE, reserve=ra) for _ in range(200)] == [
        b.maybe_trade(SUPPLY, price=PRICE, reserve=rb) for _ in range(200)
    ]
    assert _snapshot(a) == _snapshot(b)


# --- the sizing effect ------------------------------------------------------------------------------


@pytest.mark.parametrize("behavior, side", [("accumulate", "buy"), ("distribute", "sell")])
@pytest.mark.parametrize("intent", [0.25, 0.5, 1.0, 1.5, 2.0])
def test_a_directional_whale_asks_for_the_drawn_size_times_its_intent(behavior, side, intent):
    """Same seed, so the same draw; the filled size is that draw scaled."""
    baseline = _whale(behavior, seed=7, min_trade_fraction=0.004, max_trade_fraction=0.004)
    scaled = _whale(behavior, seed=7, min_trade_fraction=0.004, max_trade_fraction=0.004,
                    intent_strength=intent)
    (base_trade,), _ = _run(baseline, 1)
    (scaled_trade,), _ = _run(scaled, 1)
    assert base_trade.side == scaled_trade.side == side
    assert scaled_trade.quantity == pytest.approx(base_trade.quantity * intent)


def test_zero_intent_is_no_directional_pressure_at_all():
    for behavior in ("accumulate", "distribute"):
        whale = _whale(behavior, intent_strength=0.0)
        trades, reserve = _run(whale, 20)
        assert trades == [None] * 20
        assert (whale.wallet.cash, whale.wallet.coins) == (1e9, 1e6)
        assert (reserve.cash, reserve.coins) == (1e15, 1e15)


def test_stronger_intent_reaches_a_target_in_fewer_trades():
    def trades_to_target(intent):
        whale = _whale("accumulate", cash=1_000_000.0, coins=0.0, target_coin_fraction=0.5,
                       min_trade_fraction=0.01, max_trade_fraction=0.01, intent_strength=intent)
        trades, _ = _run(whale, 200)
        assert whale.allocation(PRICE).at_target
        return len([t for t in trades if t is not None])

    assert trades_to_target(2.0) < trades_to_target(1.0) < trades_to_target(0.5)


def test_neutral_ignores_intent_entirely():
    for intent in (0.0, 0.5, 2.0):
        plain = _whale("neutral", seed=11)
        leaning = _whale("neutral", seed=11, intent_strength=intent)
        a, b = _reserve(), _reserve()
        assert [plain.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(200)] == [
            leaning.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(200)
        ]
        assert (a.cash, a.coins) == (b.cash, b.coins)
        assert leaning.intent_strength == intent  # stored, just not read


def test_intent_does_not_create_a_trade_where_the_rules_give_none():
    # At its target: a dead-zone hold, however hard the whale leans.
    at_target = _whale("accumulate", cash=50_000.0, coins=25_000.0, target_coin_fraction=0.5,
                       intent_strength=2.0)
    assert _run(at_target, 15)[0] == [None] * 15
    # Past its target the other way: still a hold, never a reversal.
    past = _whale("accumulate", cash=100.0, coins=1_000.0, target_coin_fraction=0.5, intent_strength=2.0)
    assert _run(past, 15)[0] == [None] * 15
    # Nothing to sell.
    broke = _whale("distribute", cash=500.0, coins=0.0, intent_strength=2.0)
    assert _run(broke, 15)[0] == [None] * 15
    # Inactive ticks stay inactive.
    idle = _whale("accumulate", activity_probability=0.0, intent_strength=2.0)
    assert _run(idle, 15)[0] == [None] * 15


# --- intent never bypasses a constraint ---------------------------------------------------------------


def test_strong_intent_cannot_exceed_the_target_room():
    whale = _whale("accumulate", cash=1_000_000.0, coins=0.0, target_coin_fraction=0.5,
                   min_trade_fraction=1.0, max_trade_fraction=1.0, intent_strength=2.0)
    (trade,), _ = _run(whale, 1)
    # The draw is the whole supply, doubled to 2M; the target room is 250k.
    assert trade.quantity == 250_000.0
    assert whale.allocation(PRICE).coin_fraction == pytest.approx(0.5)
    assert whale.allocation(PRICE).at_target
    assert _run(whale, 5)[0] == [None] * 5


def test_strong_intent_cannot_cross_a_target_at_any_price():
    for behavior, target in (("accumulate", 0.7), ("distribute", 0.3)):
        whale = _whale(behavior, cash=500_000.0, coins=200_000.0, target_coin_fraction=target,
                       intent_strength=2.0, max_trade_fraction=0.05, seed=8, activity_probability=0.8)
        reserve = _reserve()
        rng = random.Random(3)
        for _ in range(300):
            price = rng.uniform(0.5, 4.0)
            before = whale.allocation(price).coin_fraction
            trade = whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
            after = whale.allocation(price).coin_fraction
            if trade is None:
                continue
            if behavior == "accumulate":
                assert before < after <= target + TARGET_DEAD_ZONE
            else:
                assert before > after >= target - TARGET_DEAD_ZONE


def test_strong_intent_cannot_overdraw_cash_coins_or_the_reserve():
    buyer = _whale("accumulate", cash=1_000.0, coins=0.0, intent_strength=2.0, max_trade_fraction=0.05)
    assert buyer.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == 500.0
    assert buyer.wallet.cash == 0.0
    seller = _whale("distribute", cash=0.0, coins=7.0, intent_strength=2.0, max_trade_fraction=0.05)
    assert seller.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == 7.0
    assert seller.wallet.coins == 0.0
    thin = _whale("accumulate", cash=1e9, coins=0.0, intent_strength=2.0, max_trade_fraction=0.05)
    assert thin.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve(coins=3.0)).quantity == 3.0


def test_weak_intent_still_moves_only_whole_valid_fills():
    """A scaled-down request is still settled by the ordinary rules: it
    either fills something positive or nothing at all."""
    whale = _whale("accumulate", cash=1e9, coins=0.0, intent_strength=0.01, seed=9)
    trades, _ = _run(whale, 200)
    filled = [t for t in trades if t is not None]
    assert filled and all(t.quantity > 0 for t in filled)
    # Scaled well below the configured band, which bounds the draw, not the fill.
    assert all(t.quantity < 0.01 * SUPPLY for t in filled)


# --- the setter changes only the intent -----------------------------------------------------------------


@pytest.mark.parametrize("behavior", BEHAVIORS)
def test_setting_the_intent_changes_nothing_else(behavior):
    whale = _whale(behavior, cash=400_000.0, coins=50_000.0, seed=3,
                   target_coin_fraction=None if behavior == "neutral" else 0.4,
                   cooldown_ticks=3, min_trade_interval_ticks=5, min_trade_fraction=0.001)
    before = _snapshot(whale)
    assert whale.set_intent_strength(1.75) == 1.0
    assert whale.intent_strength == 1.75
    assert _snapshot(whale) == before


def test_setting_the_intent_places_no_trade():
    whale = _whale("accumulate", cash=1e6, coins=0.0, target_coin_fraction=0.9)
    reserve = _reserve()
    before = (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins)
    whale.set_intent_strength(2.0)
    assert (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) == before


def test_setting_the_intent_mid_cooldown_or_interval_does_not_reset_either():
    whale = _whale("accumulate", cash=1e9, coins=0.0, cooldown_ticks=3, min_trade_interval_ticks=5)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    assert (whale.state().cooldown_remaining, whale.interval_remaining) == (3, 5)
    whale.set_intent_strength(0.25)
    assert (whale.state().cooldown_remaining, whale.interval_remaining) == (3, 5)
    for _ in range(5):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


def test_changing_the_intent_every_tick_never_shortens_the_wait():
    whale = _whale("accumulate", cash=1e9, coins=0.0, cooldown_ticks=2, min_trade_interval_ticks=4)
    reserve = _reserve()
    traded = []
    for tick in range(20):
        whale.set_intent_strength(0.5 + 0.1 * (tick % 10))
        if whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None:
            traded.append(tick)
    assert traded == [0, 5, 10, 15]


def test_a_weak_intent_that_fills_nothing_starts_no_scheduling():
    whale = _whale("accumulate", cash=1e9, coins=0.0, intent_strength=0.0,
                   cooldown_ticks=5, min_trade_interval_ticks=5)
    assert _run(whale, 10)[0] == [None] * 10
    assert whale.state().cooldown_remaining == 0 and whale.interval_remaining == 0


def test_a_partial_fill_under_strong_intent_still_starts_scheduling():
    whale = _whale("accumulate", cash=1e9, coins=0.0, intent_strength=2.0,
                   cooldown_ticks=0, min_trade_interval_ticks=4, max_trade_fraction=0.05)
    trade = whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve(coins=9.0))
    assert trade.quantity == 9.0  # clamped hard by the reserve, but coins moved
    assert whale.interval_remaining == 4


# --- interaction with Step 4 transitions -----------------------------------------------------------------


def test_intent_survives_a_behavior_transition():
    whale = _whale("accumulate", intent_strength=2.0)
    for step in ("neutral", "distribute", "neutral", "accumulate"):
        whale.set_behavior(step)
        assert whale.intent_strength == 2.0


def test_set_behavior_does_not_touch_intent_and_set_intent_does_not_touch_behavior():
    whale = _whale("accumulate", intent_strength=0.5)
    assert whale.set_behavior("distribute") is WhaleBehavior.ACCUMULATE
    assert whale.intent_strength == 0.5
    assert whale.set_intent_strength(1.5) == 0.5
    assert whale.behavior is WhaleBehavior.DISTRIBUTE


def test_intent_set_while_neutral_applies_once_the_whale_is_directional():
    whale = _whale("neutral", cash=1e9, coins=1e6, seed=13)
    whale.set_intent_strength(2.0)
    plain = _whale("neutral", cash=1e9, coins=1e6, seed=13)
    a, b = _reserve(), _reserve()
    # Ignored while neutral...
    assert [whale.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(20)] == [
        plain.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(20)
    ]
    # ...and in force the moment it becomes directional.
    whale.set_behavior("accumulate")
    plain.set_behavior("accumulate")
    leaning = whale.maybe_trade(SUPPLY, price=PRICE, reserve=a)
    ordinary = plain.maybe_trade(SUPPLY, price=PRICE, reserve=b)
    assert leaning.quantity == pytest.approx(ordinary.quantity * 2.0)


def test_a_transitioned_whale_matches_one_configured_that_way():
    transitioned = _whale("neutral", cash=800_000.0, coins=50_000.0, seed=15, max_trade_fraction=0.005)
    transitioned.set_behavior("accumulate")
    transitioned.set_intent_strength(1.5)
    native = _whale("accumulate", cash=800_000.0, coins=50_000.0, seed=15, max_trade_fraction=0.005,
                    intent_strength=1.5)
    a, b = _reserve(), _reserve()
    assert [transitioned.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(200)] == [
        native.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(200)
    ]


def test_intent_never_creates_or_changes_a_target():
    whale = _whale("accumulate", cash=1e6, coins=0.0)
    assert whale.target_coin_fraction is None
    whale.set_intent_strength(2.0)
    assert whale.target_coin_fraction is None
    assert whale.allocation(PRICE).target_coin_fraction is None
    targeted = _whale("accumulate", cash=1e6, coins=0.0, target_coin_fraction=0.3)
    targeted.set_intent_strength(0.0)
    assert targeted.target_coin_fraction == 0.3


# --- observability and unfunded whales ---------------------------------------------------------------------


def test_whale_state_keeps_its_shape_and_the_intent_is_read_from_the_whale():
    whale = _whale("accumulate", cash=1_000.0, coins=0.0, target_coin_fraction=0.4, intent_strength=1.5)
    assert whale.state() == WhaleState("w", WhaleBehavior.ACCUMULATE, True, 1_000.0, 0.0, 0.4, 0)
    assert len(whale.state().__dataclass_fields__) == 7  # unchanged for Step 2-4 callers
    assert whale.intent_strength == 1.5


@pytest.mark.parametrize("intent", [0.0, 0.5, 1.0, 2.0])
def test_an_unfunded_whale_is_unaffected_whatever_its_intent(intent):
    """Unfunded whales are always neutral, and neutral ignores intent, so
    it is stored but permanently inert for them."""
    plain = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    leaning = Whale("w", 1_000.0, activity_probability=1.0, seed=5, intent_strength=intent)
    assert [plain.maybe_trade(SUPPLY) for _ in range(150)] == [
        leaning.maybe_trade(SUPPLY) for _ in range(150)
    ]
    assert leaning.intent_strength == intent and not leaning.funded
    assert leaning.holdings == plain.holdings


def test_an_unfunded_whale_still_cannot_become_directional_to_use_its_intent():
    whale = Whale("w", 1_000.0, intent_strength=2.0)
    with pytest.raises(ValueError, match="unfunded whale cannot become"):
        whale.set_behavior("accumulate")
    assert whale.intent_strength == 2.0 and not whale.funded


# --- randomness -----------------------------------------------------------------------------------------------


def test_setting_the_intent_consumes_no_randomness():
    whale = _whale("accumulate", cash=1e9, coins=0.0)
    whale._rng = _RecordingRNG(3)
    for value in (0.0, 0.5, 1.0, 2.0, 1.25):
        whale.set_intent_strength(value)
    assert whale._rng.calls == []
    whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve())
    assert whale._rng.calls == ["random", "choice", "uniform"]


@pytest.mark.parametrize("intent", [0.0, 0.5, 1.0, 2.0])
def test_intent_never_changes_the_draws_only_what_is_done_with_them(intent):
    def calls(value):
        whale = _whale("accumulate", cash=1e12, coins=1e12, seed=6, activity_probability=0.5,
                       intent_strength=value)
        whale._rng = _RecordingRNG(6)
        _run(whale, 300)
        return whale._rng.calls, whale._rng.getstate()

    assert calls(intent) == calls(1.0)


def test_changing_the_intent_every_tick_does_not_shift_the_rng_sequence():
    def calls(changing):
        whale = _whale("accumulate", cash=1e12, coins=1e12, seed=6, activity_probability=0.5)
        whale._rng = _RecordingRNG(6)
        reserve = _reserve()
        for tick in range(300):
            if changing:
                whale.set_intent_strength((tick % 5) * 0.5)
            whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
        return whale._rng.calls, whale._rng.getstate()

    assert calls(True) == calls(False)


# --- determinism ------------------------------------------------------------------------------------------------


def test_the_same_intent_schedule_replays_identically():
    def run():
        whale = _whale("accumulate", cash=600_000.0, coins=120_000.0, seed=21, activity_probability=0.5,
                       target_coin_fraction=0.7, cooldown_ticks=2, min_trade_interval_ticks=3)
        reserve = _reserve(cash=2e6, coins=2e6)
        trades = []
        for tick in range(300):
            if tick % 20 == 0:
                whale.set_intent_strength(0.5 * ((tick // 20) % 5))
            if tick % 70 == 0:
                whale.set_behavior(BEHAVIORS[(tick // 70) % 3])
            trades.append(whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve))
        return (trades, whale.state(), whale.intent_strength, whale.interval_remaining,
                (reserve.cash, reserve.coins), whale._rng.getstate())

    assert run() == run()


def test_different_intents_give_different_runs():
    def run(intent):
        whale = _whale("accumulate", cash=1e6, coins=0.0, seed=21, activity_probability=0.6,
                       intent_strength=intent)
        return [None if t is None else t.quantity for t in _run(whale, 200)[0]]

    assert run(0.5) != run(1.0) != run(2.0)


# --- accounting --------------------------------------------------------------------------------------------------


def test_intent_never_breaks_conservation_or_produces_a_negative_balance():
    rng = random.Random(0)
    for case in range(200):
        target = rng.choice([None, rng.random()])
        start = "neutral" if target is None else rng.choice(["accumulate", "distribute"])
        whale = Whale(
            "w", rng.choice([0.0, rng.uniform(0, 2e5)]), starting_cash=rng.choice([0.0, rng.uniform(0, 5e5)]),
            behavior=start, target_coin_fraction=target, activity_probability=rng.random(),
            max_trade_fraction=rng.uniform(0.001, 0.2), cooldown_ticks=rng.randint(0, 3),
            min_trade_interval_ticks=rng.randint(0, 4), intent_strength=rng.uniform(0.0, 2.0), seed=case,
        )
        reserve = Wallet(cash=rng.uniform(0, 3e5), coins=rng.uniform(0, 3e5))
        coins = whale.wallet.coins + reserve.coins
        cash = whale.wallet.cash + reserve.cash
        for _ in range(60):
            if rng.random() < 0.15:
                whale.set_intent_strength(rng.uniform(0.0, 2.0))
            if rng.random() < 0.1:
                whale.set_behavior(rng.choice(BEHAVIORS))
            whale.maybe_trade(SUPPLY, price=rng.uniform(0.5, 4.0), reserve=reserve)
            assert min(whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) >= 0.0
        assert whale.wallet.coins + reserve.coins == pytest.approx(coins, rel=1e-12, abs=1e-6)
        assert whale.wallet.cash + reserve.cash == pytest.approx(cash, rel=1e-12, abs=1e-6)


def test_several_whales_with_different_intents_share_a_reserve_safely():
    whales = [_whale("accumulate", cash=300_000.0, coins=20_000.0, seed=1, target_coin_fraction=0.7,
                     activity_probability=0.6, intent_strength=2.0),
              _whale("distribute", cash=50_000.0, coins=150_000.0, seed=2, target_coin_fraction=0.2,
                     activity_probability=0.6, intent_strength=0.25),
              _whale("neutral", cash=100_000.0, coins=100_000.0, seed=3, intent_strength=1.5)]
    reserve = Wallet(cash=400_000.0, coins=400_000.0)
    coins = math.fsum([w.wallet.coins for w in whales] + [reserve.coins])
    cash = math.fsum([w.wallet.cash for w in whales] + [reserve.cash])
    rng = random.Random(9)
    for _ in range(400):
        price = rng.uniform(0.8, 3.0)
        for whale in whales:
            whale.maybe_trade(SUPPLY, price=price, reserve=reserve)
            assert whale.wallet.cash >= 0.0 and whale.wallet.coins >= 0.0
        assert reserve.cash >= 0.0 and reserve.coins >= 0.0
    assert math.fsum([w.wallet.coins for w in whales] + [reserve.coins]) == pytest.approx(coins, abs=1e-6)
    assert math.fsum([w.wallet.cash for w in whales] + [reserve.cash]) == pytest.approx(cash, abs=1e-6)
