"""Whale state and accumulation/distribution (Phase 8, Step 1).

Unfunded whales (the default) must behave exactly as the original Whale;
funded whales hold a Wallet, settle against a reserve, and express a
persistent behavior without ever creating coins or cash.
"""

import dataclasses
import math
import random

import pytest

from crypto_simulator.core.whale import Whale, WhaleBehavior, WhaleState, WhaleTrade
from crypto_simulator.models.wallet import Wallet

SUPPLY = 1_000_000.0
PRICE = 2.0


def _legacy_reference(seed, holdings, activity, max_fraction, coefficient, ticks):
    """The original Whale.maybe_trade, line for line."""
    rng = random.Random(seed)
    trades = []
    for _ in range(ticks):
        if rng.random() > activity:
            trades.append(None)
            continue
        side = rng.choice(("buy", "sell"))
        requested = rng.uniform(0.0, max_fraction) * SUPPLY
        if side == "sell":
            quantity = min(holdings, requested)
            holdings -= quantity
        else:
            quantity = requested
            holdings += quantity
        impact = 1.0 + coefficient * (quantity / SUPPLY)
        trades.append(WhaleTrade("w", side, quantity, impact if side == "buy" else 1.0 / impact))
    return trades, holdings, rng.getstate()


def _funded(behavior="neutral", cash=100_000.0, coins=0.0, seed=1, **kwargs):
    kwargs.setdefault("activity_probability", 1.0)
    return Whale("w", coins, starting_cash=cash, behavior=behavior, seed=seed, **kwargs)


def _reserve(cash=1e9, coins=1e9):
    return Wallet(cash=cash, coins=coins)


def _run(whale, ticks, price=PRICE, reserve=None):
    reserve = _reserve() if reserve is None else reserve
    return [whale.maybe_trade(SUPPLY, price=price, reserve=reserve) for _ in range(ticks)], reserve


# --- 1. default whale ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seed, holdings, activity, max_fraction, coefficient",
    [(1, 10_000.0, 0.5, 0.05, 2.0), (7, 100.0, 1.0, 1.0, 3.0), (42, 0.0, 0.15, 0.04, 2.0), (3, 5e5, 0.9, 0.2, 0.0)],
)
def test_the_default_whale_reproduces_the_original_algorithm(seed, holdings, activity, max_fraction, coefficient):
    whale = Whale("w", holdings, activity_probability=activity, max_trade_fraction=max_fraction,
                  impact_coefficient=coefficient, seed=seed)
    trades, final_holdings, rng_state = _legacy_reference(seed, holdings, activity, max_fraction, coefficient, 300)
    assert [whale.maybe_trade(SUPPLY) for _ in range(300)] == trades
    assert whale.holdings == final_holdings
    assert whale._rng.getstate() == rng_state


def test_the_default_whale_is_unfunded_neutral_and_ignores_price_and_reserve():
    plain, offered = Whale("w", 1_000.0, activity_probability=1.0, seed=5), Whale("w", 1_000.0, activity_probability=1.0, seed=5)
    reserve = _reserve(cash=10.0, coins=10.0)
    assert [plain.maybe_trade(SUPPLY) for _ in range(50)] == [
        offered.maybe_trade(SUPPLY, price=3.0, reserve=reserve) for _ in range(50)
    ]
    assert (reserve.cash, reserve.coins) == (10.0, 10.0)
    assert offered.state() == WhaleState("w", WhaleBehavior.NEUTRAL, False, None, offered.holdings, None, 0)
    assert not offered.funded and offered.wallet is None


# --- 2-4. behaviors -------------------------------------------------------------------------------


def test_an_accumulating_whale_only_buys_and_its_coins_come_from_the_reserve():
    whale = _funded("accumulate", cash=1e8)
    trades, reserve = _run(whale, 30)
    assert all(t is not None and t.side == "buy" and t.price_impact > 1.0 for t in trades)
    bought = math.fsum(t.quantity for t in trades)
    assert whale.holdings == pytest.approx(bought)
    assert reserve.coins == pytest.approx(1e9 - bought)
    assert whale.wallet.cash == pytest.approx(1e8 - 2.0 * bought)


def test_a_distributing_whale_only_sells_until_its_coins_run_out():
    whale = _funded("distribute", cash=0.0, coins=50_000.0, max_trade_fraction=0.02)
    trades, reserve = _run(whale, 40)
    sells = [t for t in trades if t is not None]
    assert sells and all(t.side == "sell" and t.price_impact < 1.0 for t in sells)
    assert whale.holdings == 0.0
    assert trades[-1] is None  # nothing left to sell
    assert whale.wallet.cash == pytest.approx(2.0 * 50_000.0)


def test_a_funded_neutral_whale_draws_the_same_sides_as_an_unfunded_twin():
    funded, unfunded = _funded("neutral", cash=1e12, coins=1e12, seed=9), Whale("w", 1e12, activity_probability=1.0, seed=9)
    funded_trades, _ = _run(funded, 60)
    unfunded_trades = [unfunded.maybe_trade(SUPPLY) for _ in range(60)]
    assert [t.side for t in funded_trades] == [t.side for t in unfunded_trades]
    assert [t.quantity for t in funded_trades] == [t.quantity for t in unfunded_trades]  # never clamped here
    assert {t.side for t in funded_trades} == {"buy", "sell"}


def test_behavior_changes_direction_only_never_the_draws():
    runs = {}
    for behavior in WhaleBehavior:
        whale = _funded(behavior, cash=1e12, coins=1e12, seed=4, activity_probability=0.4)
        trades, _ = _run(whale, 200)
        runs[behavior] = ([t is not None for t in trades], [t.quantity if t else None for t in trades],
                          whale._rng.getstate())
    assert runs[WhaleBehavior.ACCUMULATE] == runs[WhaleBehavior.DISTRIBUTE] == runs[WhaleBehavior.NEUTRAL]


# --- 5. target allocation ---------------------------------------------------------------------------


def _allocation(whale, price=PRICE):
    wallet = whale.wallet
    return wallet.coins * price / (wallet.cash + wallet.coins * price)


def test_accumulating_toward_a_target_stops_at_it_without_crossing():
    whale = _funded("accumulate", cash=1_000_000.0, target_coin_fraction=0.3, max_trade_fraction=0.02)
    trades, _ = _run(whale, 50)
    assert _allocation(whale) == pytest.approx(0.3)
    assert _allocation(whale) <= 0.3 + 1e-12
    assert trades[-1] is None  # at the target: nothing to do, and it never sells back
    assert all(t.side == "buy" for t in trades if t is not None)


def test_distributing_toward_a_target_stops_at_it_without_crossing():
    whale = _funded("distribute", cash=0.0, coins=500_000.0, target_coin_fraction=0.2, max_trade_fraction=0.05)
    trades, _ = _run(whale, 50)
    assert _allocation(whale) == pytest.approx(0.2)
    assert _allocation(whale) >= 0.2 - 1e-12
    assert trades[-1] is None and all(t.side == "sell" for t in trades if t is not None)


def test_the_target_gives_direction_only_when_the_whale_gets_a_chance_to_trade():
    whale = _funded("accumulate", cash=1_000_000.0, target_coin_fraction=0.3, min_trade_fraction=1.0,
                    max_trade_fraction=1.0)  # every requested chunk is bigger than the distance to the target
    (first,), reserve = _run(whale, 1)
    assert _allocation(whale) == pytest.approx(0.3)  # one active tick, sized to just reach the target
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
    # After the price halves, the whale sits below its target and buys again.
    assert whale.maybe_trade(SUPPLY, price=1.0, reserve=reserve).side == "buy"
    assert _allocation(whale, price=1.0) == pytest.approx(0.3)


def test_a_whale_already_past_its_target_does_nothing():
    whale = _funded("accumulate", cash=100.0, coins=1_000.0, target_coin_fraction=0.5)
    trades, reserve = _run(whale, 10)
    assert trades == [None] * 10
    assert (whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) == (100.0, 1_000.0, 1e9, 1e9)


# --- 6. trade sizing ---------------------------------------------------------------------------------


def test_trade_size_stays_within_the_configured_fraction_band():
    whale = Whale("w", 0.0, activity_probability=1.0, min_trade_fraction=0.01, max_trade_fraction=0.03, seed=2)
    buys = [t for t in (whale.maybe_trade(SUPPLY) for _ in range(400)) if t.side == "buy"]
    assert all(0.01 * SUPPLY <= t.quantity <= 0.03 * SUPPLY for t in buys)
    fixed = Whale("w", 0.0, activity_probability=1.0, min_trade_fraction=0.02, max_trade_fraction=0.02, seed=2)
    assert {t.quantity for t in (fixed.maybe_trade(SUPPLY) for _ in range(50)) if t.side == "buy"} == {0.02 * SUPPLY}


def test_min_trade_fraction_zero_is_the_original_size_draw():
    a = Whale("w", 1_000.0, activity_probability=1.0, seed=6)
    b = Whale("w", 1_000.0, activity_probability=1.0, min_trade_fraction=0.0, seed=6)
    assert [a.maybe_trade(SUPPLY) for _ in range(100)] == [b.maybe_trade(SUPPLY) for _ in range(100)]


# --- 7. cooldown ---------------------------------------------------------------------------------------


def test_cooldown_sits_out_the_next_ticks_without_drawing():
    whale = _funded("accumulate", cash=1e9, cooldown_ticks=3)
    reserve = _reserve()
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None
    for remaining in (3, 2, 1):
        assert whale.state().cooldown_remaining == remaining
        rng_state = whale._rng.getstate()
        assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is None
        assert whale._rng.getstate() == rng_state
    assert whale.state().cooldown_remaining == 0
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=reserve) is not None


def test_cooldown_applies_to_unfunded_whales_and_zero_means_none():
    cooling = Whale("w", 1_000.0, activity_probability=1.0, cooldown_ticks=2, seed=3)
    pattern = [cooling.maybe_trade(SUPPLY) is not None for _ in range(9)]
    assert pattern == [True, False, False] * 3
    plain = Whale("w", 1_000.0, activity_probability=1.0, seed=3)
    zero = Whale("w", 1_000.0, activity_probability=1.0, cooldown_ticks=0, seed=3)
    assert [plain.maybe_trade(SUPPLY) for _ in range(60)] == [zero.maybe_trade(SUPPLY) for _ in range(60)]


def test_a_trade_that_moves_no_coins_starts_no_cooldown():
    broke = _funded("accumulate", cash=0.0, cooldown_ticks=5)
    assert broke.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) is None
    assert broke.state().cooldown_remaining == 0
    zero_seen = False
    for seed in range(1, 30):  # unfunded with nothing to sell: a sell prints a zero-quantity trade
        empty = Whale("w", 0.0, activity_probability=1.0, cooldown_ticks=5, seed=seed)
        trade = empty.maybe_trade(SUPPLY)
        assert empty.state().cooldown_remaining == (0 if trade.quantity == 0.0 else 5)
        zero_seen |= trade.quantity == 0.0
    assert zero_seen


# --- 8-9. insufficient balances --------------------------------------------------------------------------


def test_insufficient_cash_clamps_and_then_stops_buying():
    whale = _funded("accumulate", cash=1_000.0, max_trade_fraction=0.05)
    trade = whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve())
    assert trade.quantity == 1_000.0 / PRICE  # everything it can afford, not the requested chunk
    assert whale.wallet.cash == 0.0
    assert whale.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve()) is None


def test_insufficient_coins_means_no_sell():
    whale = _funded("distribute", cash=500.0, coins=0.0)
    assert _run(whale, 10)[0] == [None] * 10


def test_the_reserve_limits_funded_trades_too():
    buyer = _funded("accumulate", cash=1e9)
    assert buyer.maybe_trade(SUPPLY, price=PRICE, reserve=_reserve(coins=0.0)) is None
    thin = _reserve(cash=1e9, coins=7.0)
    assert buyer.maybe_trade(SUPPLY, price=PRICE, reserve=thin).quantity == 7.0
    seller = _funded("distribute", cash=0.0, coins=1e6)
    poor = _reserve(cash=10.0)
    assert seller.maybe_trade(SUPPLY, price=PRICE, reserve=poor).quantity == 5.0
    assert poor.cash == 0.0


def test_a_funded_whale_needs_a_price_and_a_reserve():
    whale = _funded("neutral")
    with pytest.raises(ValueError, match="price and the market reserve"):
        whale.maybe_trade(SUPPLY)
    for bad in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="price"):
            _funded("neutral").maybe_trade(SUPPLY, price=bad, reserve=_reserve())


# --- 10. invalid configuration ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"whale_id": ""}, "whale_id"),
        ({"holdings": -1.0}, "holdings"),
        ({"holdings": math.nan}, "holdings"),
        ({"holdings": True}, "holdings"),
        ({"activity_probability": 1.5}, "activity_probability"),
        ({"activity_probability": True}, "activity_probability"),
        ({"activity_probability": math.nan}, "activity_probability"),
        ({"max_trade_fraction": 0.0}, "max_trade_fraction"),
        ({"max_trade_fraction": 1.5}, "max_trade_fraction"),
        ({"impact_coefficient": -1.0}, "impact_coefficient"),
        ({"impact_coefficient": math.inf}, "impact_coefficient"),
        ({"min_trade_fraction": -0.1}, "min_trade_fraction"),
        ({"min_trade_fraction": 0.5, "max_trade_fraction": 0.05}, "min_trade_fraction"),
        ({"min_trade_fraction": True}, "min_trade_fraction"),
        ({"cooldown_ticks": -1}, "cooldown_ticks"),
        ({"cooldown_ticks": 1.5}, "cooldown_ticks"),
        ({"cooldown_ticks": True}, "cooldown_ticks"),
        ({"behavior": "hodl"}, "behavior"),
        ({"starting_cash": -1.0}, "starting_cash"),
        ({"starting_cash": math.nan}, "starting_cash"),
        ({"starting_cash": False}, "starting_cash"),
        ({"behavior": "accumulate"}, "needs starting_cash"),
        ({"behavior": "distribute"}, "needs starting_cash"),
        ({"starting_cash": 1.0, "target_coin_fraction": 0.5}, "accumulate or distribute"),
        ({"starting_cash": 1.0, "behavior": "accumulate", "target_coin_fraction": 1.5}, "target_coin_fraction"),
        ({"starting_cash": 1.0, "behavior": "accumulate", "target_coin_fraction": math.nan}, "target_coin_fraction"),
    ],
)
def test_invalid_configuration_is_rejected_not_clamped(kwargs, message):
    args = {"whale_id": "w", "holdings": 100.0, **kwargs}
    with pytest.raises(ValueError, match=message):
        Whale(args.pop("whale_id"), args.pop("holdings"), **args)


def test_behavior_accepts_the_enum_or_its_value():
    assert _funded(WhaleBehavior.DISTRIBUTE).behavior is _funded("distribute").behavior is WhaleBehavior.DISTRIBUTE


# --- 11-14. RNG --------------------------------------------------------------------------------------------


def _trajectory(whale, ticks=150):
    trades, reserve = _run(whale, ticks)
    return trades, whale.state(), (reserve.cash, reserve.coins), whale._rng.getstate()


def test_same_seed_same_trades_and_state():
    for make in (lambda: _funded("accumulate", cash=5e5, activity_probability=0.3, seed=11, cooldown_ticks=2),
                 lambda: Whale("w", 1e4, activity_probability=0.3, seed=11)):
        assert _trajectory(make()) == _trajectory(make())


def test_different_seeds_give_different_trades():
    a = _trajectory(_funded("neutral", cash=1e9, coins=1e9, activity_probability=0.5, seed=1))[0]
    b = _trajectory(_funded("neutral", cash=1e9, coins=1e9, activity_probability=0.5, seed=2))[0]
    assert a != b


def test_each_whale_has_its_own_stream_and_touches_no_global_randomness():
    state = random.getstate()
    alone = _funded("accumulate", cash=1e9, activity_probability=0.4, seed=5)
    reference, _ = _run(alone, 100)
    first, second = (_funded("accumulate", cash=1e9, activity_probability=0.4, seed=5),
                     _funded("distribute", cash=0.0, coins=1e6, activity_probability=0.6, seed=6))
    reserve = _reserve()
    interleaved = []
    for _ in range(100):
        interleaved.append(first.maybe_trade(SUPPLY, price=PRICE, reserve=reserve))
        second.maybe_trade(SUPPLY, price=PRICE, reserve=reserve)
    assert interleaved == reference
    assert random.getstate() == state


# --- 15-16. balances and conservation -------------------------------------------------------------------------


def test_no_negative_balances_and_conservation_across_random_configurations():
    rng = random.Random(0)
    for case in range(200):
        behavior = rng.choice(list(WhaleBehavior))
        target = rng.choice([None, rng.random()]) if behavior is not WhaleBehavior.NEUTRAL else None
        whale = Whale(
            "w", rng.choice([0.0, rng.uniform(0, 2e5)]), starting_cash=rng.choice([0.0, rng.uniform(0, 5e5)]),
            behavior=behavior, target_coin_fraction=target, activity_probability=rng.random(),
            max_trade_fraction=rng.uniform(0.001, 0.2), cooldown_ticks=rng.randint(0, 3), seed=case,
        )
        reserve = _reserve(cash=rng.uniform(0, 3e5), coins=rng.uniform(0, 3e5))
        coins = whale.wallet.coins + reserve.coins
        cash = whale.wallet.cash + reserve.cash
        for _ in range(60):
            whale.maybe_trade(SUPPLY, price=rng.uniform(0.5, 4.0), reserve=reserve)
            assert min(whale.wallet.cash, whale.wallet.coins, reserve.cash, reserve.coins) >= 0.0
        assert whale.wallet.coins + reserve.coins == pytest.approx(coins, rel=1e-12, abs=1e-6)
        assert whale.wallet.cash + reserve.cash == pytest.approx(cash, rel=1e-12, abs=1e-6)


def test_state_is_a_frozen_snapshot():
    whale = _funded("accumulate", cash=1_000.0, target_coin_fraction=0.4, cooldown_ticks=2)
    before = whale.state()
    assert before == WhaleState("w", WhaleBehavior.ACCUMULATE, True, 1_000.0, 0.0, 0.4, 0)
    _run(whale, 1)
    assert before.cash == 1_000.0 and whale.state() != before
    with pytest.raises(dataclasses.FrozenInstanceError):
        before.cash = 0.0
