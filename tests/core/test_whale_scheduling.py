"""Whale trade scheduling / patience (Phase 8, Step 3).

``min_trade_interval_ticks`` is the minimum number of ticks a *funded*
whale waits between successful trades — execution pacing, not psychology:
it reads nothing but its own tick counter. A trade at tick T with the
setting at N blocks exactly the next N ticks, so the earliest next trade
is T + N + 1. It composes with the Step 1 ``cooldown_ticks`` (the whale
waits out whichever is longer) and sits above the Step 2 target
allocation, which still decides direction and size.
"""

import math
import random

import pytest

from crypto_simulator.core.whale import TARGET_DEAD_ZONE, Whale, WhaleBehavior
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0


def _funded(behavior="neutral", cash=1e12, coins=1e12, seed=1, **kwargs):
    """A funded whale rich enough that nothing but pacing stops it."""
    kwargs.setdefault("activity_probability", 1.0)
    kwargs.setdefault("max_trade_fraction", 0.02)
    return Whale("w", coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _reserve(cash=1e15, coins=1e15):
    return Wallet(cash=cash, coins=coins)


def _pattern(whale, ticks, price=PRICE, reserve=None):
    """Which ticks the whale traded on, as booleans."""
    reserve = _reserve() if reserve is None else reserve
    return [whale.maybe_trade(SUPPLY, price=price, reserve=reserve) is not None for _ in range(ticks)]


class _RecordingRNG:
    """Records the top-level draws a whale takes."""

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


# --- 1-5. exact tick semantics -----------------------------------------------------------------


def test_omitting_the_setting_leaves_the_whale_exactly_as_it_was():
    for behavior, kwargs in (("neutral", {}), ("accumulate", {"target_coin_fraction": 0.5}),
                             ("distribute", {"target_coin_fraction": 0.2}),
                             ("neutral", {"cooldown_ticks": 3})):
        omitted = _funded(behavior, seed=7, activity_probability=0.5, **kwargs)
        explicit = _funded(behavior, seed=7, activity_probability=0.5, min_trade_interval_ticks=0, **kwargs)
        a, b = _reserve(), _reserve()
        assert [omitted.maybe_trade(SUPPLY, price=PRICE, reserve=a) for _ in range(300)] == [
            explicit.maybe_trade(SUPPLY, price=PRICE, reserve=b) for _ in range(300)
        ]
        assert omitted._rng.getstate() == explicit._rng.getstate()
        assert (a.cash, a.coins) == (b.cash, b.coins)
        assert omitted.interval_remaining == explicit.interval_remaining == 0


def test_interval_zero_blocks_nothing():
    assert _pattern(_funded(min_trade_interval_ticks=0), 10) == [True] * 10


def test_interval_one_blocks_exactly_the_next_tick():
    # Trade at tick 0, next eligible tick 2 (= 0 + 1 + 1).
    assert _pattern(_funded(min_trade_interval_ticks=1), 9) == [True, False] * 4 + [True]


def test_interval_two_blocks_exactly_the_next_two_ticks():
    # Trade at tick 0, next eligible tick 3 (= 0 + 2 + 1).
    assert _pattern(_funded(min_trade_interval_ticks=2), 10) == [True, False, False] * 3 + [True]


@pytest.mark.parametrize("interval", [0, 1, 2, 3, 5, 8, 20])
def test_a_trade_at_T_blocks_exactly_N_ticks_and_the_next_is_T_plus_N_plus_1(interval):
    whale = _funded(min_trade_interval_ticks=interval)
    pattern = _pattern(whale, 4 * (interval + 1))
    traded = [i for i, t in enumerate(pattern) if t]
    assert traded == list(range(0, 4 * (interval + 1), interval + 1))
    # Stated the other way round: between consecutive trades there are
    # exactly `interval` blocked ticks, never `interval - 1` or `+ 1`.
    assert all(b - a == interval + 1 for a, b in zip(traded, traded[1:]))
    assert sum(not t for t in pattern[traded[0] + 1:traded[1]]) == interval


def test_the_counter_counts_down_to_the_eligible_tick():
    whale = _funded(min_trade_interval_ticks=3)
    reserve = _reserve()
    assert whale.interval_remaining == 0  # never traded: nothing to wait for
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    for remaining in (3, 2, 1):
        assert whale.interval_remaining == remaining
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
    assert whale.interval_remaining == 0
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


# --- 6-7. the first trade ------------------------------------------------------------------------


@pytest.mark.parametrize("interval", [0, 1, 4, 50])
def test_a_whale_that_has_never_traded_is_eligible_immediately(interval):
    whale = _funded(min_trade_interval_ticks=interval)
    assert whale.interval_remaining == 0
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) is not None
    assert whale.interval_remaining == interval


def test_only_a_successful_trade_starts_the_interval():
    whale = _funded("accumulate", cash=1e9, coins=0.0, min_trade_interval_ticks=4,
                    activity_probability=0.5, seed=3)
    reserve = _reserve()
    started = []
    for _ in range(200):
        trade = whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
        started.append((trade is not None, whale.interval_remaining))
    # The counter is at its maximum on exactly the ticks a trade filled.
    assert all((remaining == 4) == traded for traded, remaining in started)
    assert any(traded for traded, _ in started)


# --- 8-10. what does not start the interval ------------------------------------------------------


def test_an_inactive_tick_does_not_start_the_interval():
    whale = _funded(min_trade_interval_ticks=5, activity_probability=0.0)
    assert _pattern(whale, 30) == [False] * 30
    assert whale.interval_remaining == 0


def test_a_no_fill_against_an_empty_reserve_does_not_start_the_interval():
    whale = _funded("accumulate", cash=1e9, coins=0.0, min_trade_interval_ticks=6)
    empty = _reserve(coins=0.0)
    assert _pattern(whale, 5, reserve=empty) == [False] * 5  # attempted every tick, filled none
    assert whale.interval_remaining == 0
    # Still eligible the moment a reserve can fill it.
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) is not None
    assert whale.interval_remaining == 6


def test_a_dead_zone_hold_does_not_start_the_interval():
    # Sitting exactly on its target: a hold, not a trade.
    whale = _funded("accumulate", cash=50_000.0, coins=25_000.0, target_coin_fraction=0.5,
                    min_trade_interval_ticks=7, max_trade_fraction=1.0)
    assert whale.allocation(PRICE).at_target
    assert _pattern(whale, 10) == [False] * 10
    assert whale.interval_remaining == 0
    # A price move reopens the gap, and it trades on the very next tick —
    # no interval was ever started by the holds.
    assert whale.maybe_trade(SUPPLY, price=1.0, reserve=_reserve()) is not None
    assert whale.interval_remaining == 7


def test_a_whale_past_its_target_holds_without_starting_the_interval():
    whale = _funded("accumulate", cash=100.0, coins=1_000.0, target_coin_fraction=0.5,
                    min_trade_interval_ticks=9)
    assert _pattern(whale, 15) == [False] * 15
    assert whale.interval_remaining == 0


def test_insufficient_cash_does_not_start_the_interval():
    whale = _funded("accumulate", cash=0.0, coins=0.0, min_trade_interval_ticks=8)
    assert _pattern(whale, 6) == [False] * 6
    assert whale.interval_remaining == 0


def test_insufficient_coins_does_not_start_the_interval():
    whale = _funded("distribute", cash=500.0, coins=0.0, min_trade_interval_ticks=8)
    assert _pattern(whale, 6) == [False] * 6
    assert whale.interval_remaining == 0


def test_a_partial_fill_is_still_a_successful_trade():
    whale = _funded("accumulate", cash=1e9, coins=0.0, min_trade_interval_ticks=3, max_trade_fraction=1.0,
                    min_trade_fraction=1.0)
    thin = _reserve(coins=5.0)
    trade = whale.maybe_trade(SUPPLY, price=PRICE, reserve=thin)
    assert trade.quantity == 5.0 < SUPPLY  # clamped hard by the reserve, but coins moved
    assert whale.interval_remaining == 3


# --- 11-13. cooldown interaction -----------------------------------------------------------------


def test_cooldown_alone_is_unchanged_by_the_new_setting():
    with_setting = _funded(cooldown_ticks=2, min_trade_interval_ticks=0, seed=4, activity_probability=0.6)
    without = _funded(cooldown_ticks=2, seed=4, activity_probability=0.6)
    assert _pattern(with_setting, 200) == _pattern(without, 200)
    unfunded_cooling = Whale("w", 1_000.0, activity_probability=1.0, cooldown_ticks=2, seed=3)
    assert [unfunded_cooling.maybe_trade(SUPPLY) is not None for _ in range(9)] == [True, False, False] * 3


@pytest.mark.parametrize(
    "cooldown, interval, blocked",
    [(0, 0, 0), (3, 0, 3), (0, 3, 3), (2, 2, 2), (5, 2, 5), (2, 5, 5), (1, 7, 7), (7, 1, 7)],
)
def test_the_whale_waits_out_whichever_restriction_is_longer(cooldown, interval, blocked):
    whale = _funded(cooldown_ticks=cooldown, min_trade_interval_ticks=interval)
    pattern = _pattern(whale, 3 * (blocked + 1))
    traded = [i for i, t in enumerate(pattern) if t]
    assert traded == list(range(0, 3 * (blocked + 1), blocked + 1))


def test_both_counters_run_down_together():
    whale = _funded(cooldown_ticks=2, min_trade_interval_ticks=5)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    assert (whale.state().cooldown_remaining, whale.interval_remaining) == (2, 5)
    for cooldown, interval in ((1, 4), (0, 3), (0, 2), (0, 1), (0, 0)):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert (whale.state().cooldown_remaining, whale.interval_remaining) == (cooldown, interval)
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


def test_neither_counter_is_restarted_by_a_blocked_tick():
    whale = _funded(cooldown_ticks=4, min_trade_interval_ticks=4)
    pattern = _pattern(whale, 30)
    assert [i for i, t in enumerate(pattern) if t] == [0, 5, 10, 15, 20, 25]


# --- 14-16, 20-23. target allocation still rules ---------------------------------------------------


def test_scheduling_does_not_let_a_whale_cross_its_target():
    whale = _funded("accumulate", cash=1_000_000.0, coins=0.0, target_coin_fraction=0.4,
                    min_trade_interval_ticks=3, max_trade_fraction=1.0, min_trade_fraction=1.0)
    _pattern(whale, 40)
    assert whale.allocation(PRICE).coin_fraction == pytest.approx(0.4)
    assert whale.allocation(PRICE).coin_fraction <= 0.4 + TARGET_DEAD_ZONE


@pytest.mark.parametrize("behavior, target, side", [("accumulate", 0.9, "buy"), ("distribute", 0.1, "sell")])
def test_scheduling_never_changes_the_direction_a_whale_trades(behavior, target, side):
    whale = _funded(behavior, cash=500_000.0, coins=250_000.0, target_coin_fraction=target,
                    min_trade_interval_ticks=4, seed=6)
    reserve = _reserve()
    rng = random.Random(11)
    sides = set()
    for _ in range(400):
        trade = whale.maybe_trade(SUPPLY, price=rng.uniform(0.5, 4.0), reserve=reserve)
        if trade is not None:
            sides.add(trade.side)
    assert sides == {side}


def test_scheduling_still_respects_cash_coins_and_the_reserve():
    buyer = _funded("accumulate", cash=1_000.0, coins=0.0, min_trade_interval_ticks=2, max_trade_fraction=0.05)
    assert buyer.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == 500.0  # all it can afford
    assert buyer.wallet.cash == 0.0 and buyer.interval_remaining == 2
    seller = _funded("distribute", cash=0.0, coins=7.0, min_trade_interval_ticks=2, max_trade_fraction=0.05)
    assert seller.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()).quantity == 7.0  # all it holds
    assert seller.wallet.coins == 0.0
    thin = _funded("accumulate", cash=1e9, coins=0.0, min_trade_interval_ticks=2, max_trade_fraction=0.05)
    assert thin.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve(coins=3.0)).quantity == 3.0


def test_the_min_trade_fraction_band_is_unaffected_by_scheduling():
    whale = _funded(min_trade_interval_ticks=2, min_trade_fraction=0.01, max_trade_fraction=0.03, seed=2)
    reserve = _reserve()
    sizes = [t.quantity for t in (whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) for _ in range(300))
             if t is not None]
    assert sizes and all(0.01 * SUPPLY <= q <= 0.03 * SUPPLY for q in sizes)


def test_a_scheduled_whale_still_settles_onto_its_target_and_then_holds():
    whale = _funded("accumulate", cash=1_000_000.0, coins=0.0, target_coin_fraction=0.5,
                    min_trade_interval_ticks=2, max_trade_fraction=0.05)
    pattern = _pattern(whale, 400)
    traded = [i for i, t in enumerate(pattern) if t]
    # Paced approach, then a dead-zone hold for good — no churn afterwards.
    assert all(b - a == 3 for a, b in zip(traded, traded[1:]))
    assert max(traded) < 100 and whale.allocation(PRICE).at_target
    assert whale.interval_remaining == 0  # the last trade's interval long expired


# --- 24-26. RNG ------------------------------------------------------------------------------------


def test_a_blocked_tick_consumes_no_randomness():
    whale = _funded(min_trade_interval_ticks=3)
    whale._rng = _RecordingRNG(1)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    after_trade = list(whale._rng.calls)
    for _ in range(3):
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert whale._rng.calls == after_trade  # not one extra draw
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    assert whale._rng.calls == after_trade + ["random", "choice", "uniform"]


@pytest.mark.parametrize("cooldown, interval", [(3, 0), (0, 3), (2, 5), (5, 2)])
def test_only_eligible_ticks_draw_whatever_is_blocking(cooldown, interval):
    whale = _funded(cooldown_ticks=cooldown, min_trade_interval_ticks=interval)
    whale._rng = _RecordingRNG(1)
    blocked = max(cooldown, interval)
    _pattern(whale, 4 * (blocked + 1))
    assert whale._rng.calls == ["random", "choice", "uniform"] * 4


def test_disabled_scheduling_replays_the_baseline_rng_sequence_exactly():
    def record(**kwargs):
        whale = _funded("accumulate", cash=1e9, coins=1e5, target_coin_fraction=0.6, seed=5,
                        activity_probability=0.45, **kwargs)
        whale._rng = _RecordingRNG(5)
        _pattern(whale, 400)
        return whale._rng.calls

    baseline = record()
    assert record(min_trade_interval_ticks=0) == baseline
    # Enabling it removes draws (blocked ticks take none); it never adds any.
    paced = record(min_trade_interval_ticks=4)
    assert len(paced) < len(baseline)
    assert set(paced) <= {"random", "choice", "uniform"}


def test_same_seed_replays_a_scheduled_run_exactly():
    def run():
        whale = _funded("accumulate", cash=5e5, coins=1e5, target_coin_fraction=0.7, seed=13,
                        activity_probability=0.4, cooldown_ticks=2, min_trade_interval_ticks=3)
        reserve = _reserve(cash=1e6, coins=1e6)
        trades = [whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) for _ in range(300)]
        return trades, whale.state(), whale.interval_remaining, (reserve.cash, reserve.coins), whale._rng.getstate()

    assert run() == run()


def test_different_seeds_can_still_differ_under_scheduling():
    def run(seed):
        whale = _funded("accumulate", cash=1e9, coins=0.0, seed=seed, activity_probability=0.4,
                        min_trade_interval_ticks=2)
        return [t.quantity if t else None for t in
                (whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) for _ in range(300))]

    assert run(1) != run(2)


# --- 27. unfunded whales ---------------------------------------------------------------------------


def test_an_unfunded_whale_is_untouched_and_rejects_the_setting():
    plain = Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    explicit = Whale("w", 1_000.0, activity_probability=1.0, seed=5, min_trade_interval_ticks=0)
    assert [plain.maybe_trade(SUPPLY) for _ in range(150)] == [
        explicit.maybe_trade(SUPPLY) for _ in range(150)
    ]
    assert explicit.interval_remaining == 0
    with pytest.raises(ValueError, match="min_trade_interval_ticks applies only to funded whales"):
        Whale("w", 1_000.0, min_trade_interval_ticks=1)


def test_a_zero_quantity_unfunded_sell_still_starts_no_pacing():
    zero_seen = False
    for seed in range(1, 30):
        empty = Whale("w", 0.0, activity_probability=1.0, cooldown_ticks=5, seed=seed)
        trade = empty.maybe_trade(SUPPLY)
        assert empty.state().cooldown_remaining == (0 if trade.quantity == 0.0 else 5)
        assert empty.interval_remaining == 0
        zero_seen |= trade.quantity == 0.0
    assert zero_seen


# --- configuration validation -----------------------------------------------------------------------


@pytest.mark.parametrize("bad", [-1, -10, 1.5, 0.0, True, False, "2", None, math.nan])
def test_the_setting_is_validated_not_coerced(bad):
    with pytest.raises(ValueError, match="min_trade_interval_ticks"):
        Whale("w", 100.0, starting_cash=1_000.0, min_trade_interval_ticks=bad)


@pytest.mark.parametrize("good", [0, 1, 2, 1_000])
def test_any_non_negative_integer_is_accepted_for_a_funded_whale(good):
    assert Whale("w", 100.0, starting_cash=1_000.0,
                 min_trade_interval_ticks=good).min_trade_interval_ticks == good


# --- accounting --------------------------------------------------------------------------------------


def test_scheduling_does_not_change_settlement_or_conservation():
    rng = random.Random(0)
    for case in range(200):
        behavior = rng.choice(list(WhaleBehavior))
        target = rng.choice([None, rng.random()]) if behavior is not WhaleBehavior.NEUTRAL else None
        whale = Whale(
            "w", rng.choice([0.0, rng.uniform(0, 2e5)]), starting_cash=rng.choice([0.0, rng.uniform(0, 5e5)]),
            behavior=behavior, target_coin_fraction=target, activity_probability=rng.random(),
            max_trade_fraction=rng.uniform(0.001, 0.2), cooldown_ticks=rng.randint(0, 3),
            min_trade_interval_ticks=rng.randint(0, 6), seed=case,
        )
        reserve = Wallet(cash=rng.uniform(0, 3e5), coins=rng.uniform(0, 3e5))
        coins = whale.wallet.coins + reserve.coins
        cash = whale.wallet.cash + reserve.cash
        for _ in range(60):
            whale.maybe_trade(SUPPLY, price=rng.uniform(0.5, 4.0), reserve=reserve)
            assert min(whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) >= 0.0
            assert whale.interval_remaining <= whale.min_trade_interval_ticks
        assert whale.wallet.coins + reserve.coins == pytest.approx(coins, rel=1e-12, abs=1e-6)
        assert whale.wallet.cash + reserve.cash == pytest.approx(cash, rel=1e-12, abs=1e-6)


def test_several_paced_whales_share_one_reserve_safely():
    whales = [
        _funded("accumulate", cash=300_000.0, coins=0.0, target_coin_fraction=0.8, seed=1,
                activity_probability=0.6, min_trade_interval_ticks=2),
        _funded("distribute", cash=0.0, coins=120_000.0, target_coin_fraction=0.2, seed=2,
                activity_probability=0.6, min_trade_interval_ticks=5),
        _funded("neutral", cash=80_000.0, coins=80_000.0, seed=3, cooldown_ticks=3,
                min_trade_interval_ticks=1),
    ]
    reserve = Wallet(cash=250_000.0, coins=250_000.0)
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


def test_pacing_holds_over_hundreds_of_ticks():
    whale = _funded(min_trade_interval_ticks=7, cooldown_ticks=3)
    pattern = _pattern(whale, 800)
    traded = [i for i, t in enumerate(pattern) if t]
    assert len(traded) == 100 and traded == list(range(0, 800, 8))
    assert all(b - a == 8 for a, b in zip(traded, traded[1:]))
