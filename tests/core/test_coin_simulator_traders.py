"""CoinSimulator + trader-agent integration tests.

The GOLDEN_* values were captured from the pre-trader-phase code (whales
only) with the same seeds, so they pin the "traders disabled" path to the
exact previous behavior, bit for bit.
"""

import pytest

from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.traders.base import MarketContext, TradeAction, TradeDecision, TraderAgent
from crypto_simulator.core.traders.execution import net_flow_price_impact
from crypto_simulator.core.traders.strategies import (
    DipBuyer,
    LongTermHolder,
    MomentumTrader,
    PanicSeller,
    RetailTrader,
)
from crypto_simulator.core.whale import Whale
from crypto_simulator.models.coin import Coin

SUPPLY = 1_000_000.0

GOLDEN_PLAIN_PRICES = [2.051786497049282, 2.111713678574698, 2.1140943214438366, 2.081597506619962, 2.036213929617202, 2.037082947811938, 1.995464376819724, 1.9385498715777192, 1.945903598432376, 1.9507110288847211]
GOLDEN_PLAIN_VOLUMES = [21690.83368087951, 6685.730459665896, 11974.298106155815, 10732.607236196907, 14175.742898336812, 2989.451057635724, 7926.1104742548305, 6242.699236436091, 4626.836285593887, 5780.855929583091]
GOLDEN_WHALE_PRICES = [2.1327958489171674, 2.275361071794709, 2.286467437028144, 2.3055019540350425, 2.255236749004671, 2.469962771723644, 2.4195002605757687, 2.3504914314214047, 2.347765416639538, 2.4217271095091837, 2.5876017414260866, 2.540223474639208, 2.5399697333974554, 2.630622294734987, 2.5520675948538463]
GOLDEN_WHALE_VOLUMES = [41432.00850203818, 24970.176305295172, 13849.08102825506, 22765.75724254816, 14175.742898336812, 50361.936093010096, 7926.1104742548305, 6242.699236436091, 7106.30195508246, 20261.320246166906, 35983.41257203904, 8566.031092123563, 5466.480573811352, 30729.936963913573, 7262.449551528529]
GOLDEN_WHALE_TRADES = [(1, "buy", 19741.174821158675), (2, "buy", 18284.445845629278), (3, "buy", 1874.7829220992442), (4, "buy", 12033.150006351252), (6, "buy", 47372.485035374375), (9, "sell", 2479.4656694885734), (10, "buy", 14480.464316583813), (11, "buy", 28545.68448233672), (14, "buy", 18619.877136286563)]
GOLDEN_WHALE_FINAL_HOLDINGS = 258472.5988963314


def _coin():
    return Coin("FIC", "FictiCoin (Simulated)", SUPPLY, 2.0)


def _golden_whale():
    return Whale("w1", 100_000.0, activity_probability=0.5, seed=7)


def _all_five(seed_base=10, trade_probability=None):
    def common(i, cash, coins, prob, max_size, risk):
        return dict(
            starting_cash=cash,
            starting_coins=coins,
            trade_probability=prob if trade_probability is None else trade_probability,
            max_trade_size=max_size,
            risk_tolerance=risk,
            seed=seed_base + i,
        )

    return [
        RetailTrader("retail", **common(0, 5_000.0, 5_000.0, 0.6, 2_000.0, 0.3)),
        MomentumTrader("momentum", lookback=5, **common(1, 40_000.0, 10_000.0, 0.7, 15_000.0, 0.5)),
        DipBuyer("dip", lookback=10, **common(2, 40_000.0, 0.0, 0.6, 15_000.0, 0.5)),
        PanicSeller("panic", lookback=5, **common(3, 5_000.0, 30_000.0, 0.8, 20_000.0, 0.8)),
        LongTermHolder("holder", **common(4, 20_000.0, 60_000.0, 0.1, 5_000.0, 0.25)),
    ]


def _market_view(ticks):
    """Everything in a tick except its wall-clock-derived timestamp."""
    return [(t.tick, t.price, t.market_cap, t.volume, t.whale_trades, t.trader_trades) for t in ticks]


def _totals(sim):
    return (
        sim.reserve.coins + sum(t.wallet.coins for t in sim.traders),
        sim.reserve.cash + sum(t.wallet.cash for t in sim.traders),
    )


# --- backwards compatibility --------------------------------------------------


@pytest.mark.parametrize("traders", [None, []])
def test_no_traders_no_whales_matches_pre_phase_golden_output(traders):
    ticks = CoinSimulator(_coin(), seed=1, traders=traders).run(10)
    assert [t.price for t in ticks] == GOLDEN_PLAIN_PRICES
    assert [t.volume for t in ticks] == GOLDEN_PLAIN_VOLUMES
    assert all(t.trader_trades == () and t.whale_trades == () for t in ticks)


def test_whale_only_matches_pre_phase_golden_output():
    whale = _golden_whale()
    ticks = CoinSimulator(_coin(), seed=1, whales=[whale]).run(15)
    assert [t.price for t in ticks] == GOLDEN_WHALE_PRICES
    assert [t.volume for t in ticks] == GOLDEN_WHALE_VOLUMES
    assert [(t.tick, w.side, w.quantity) for t in ticks for w in t.whale_trades] == GOLDEN_WHALE_TRADES
    assert whale.holdings == GOLDEN_WHALE_FINAL_HOLDINGS


def test_inactive_traders_leave_whale_simulation_unchanged():
    ticks = CoinSimulator(
        _coin(), seed=1, whales=[_golden_whale()], traders=_all_five(trade_probability=0.0)
    ).run(15)
    assert [t.price for t in ticks] == GOLDEN_WHALE_PRICES
    assert [t.volume for t in ticks] == GOLDEN_WHALE_VOLUMES
    assert all(t.trader_trades == () for t in ticks)


def test_whale_behavior_preserved_when_traders_active():
    with_traders = CoinSimulator(_coin(), seed=1, whales=[_golden_whale()], traders=_all_five()).run(15)
    assert [(t.tick, w.side, w.quantity) for t in with_traders for w in t.whale_trades] == GOLDEN_WHALE_TRADES


# --- trader activity, volume, price impact ------------------------------------


def _always_buyer(cash=100_000.0, max_size=10_000.0, seed=1):
    return RetailTrader(
        "buyer", starting_cash=cash, buy_bias=1.0, trade_probability=1.0,
        max_trade_size=max_size, risk_tolerance=1.0, seed=seed,
    )


def _always_seller(coins=100_000.0, max_size=10_000.0, seed=1):
    return RetailTrader(
        "seller", starting_coins=coins, buy_bias=0.0, trade_probability=1.0,
        max_trade_size=max_size, risk_tolerance=1.0, seed=seed,
    )


def test_trader_fills_are_recorded_on_ticks():
    tick = CoinSimulator(_coin(), seed=1, traders=[_always_buyer()]).step()
    assert len(tick.trader_trades) == 1
    fill = tick.trader_trades[0]
    assert (fill.trader_id, fill.strategy, fill.side) == ("buyer", "retail", TradeAction.BUY)
    assert fill.quantity == 10_000.0
    assert fill.price == pytest.approx(GOLDEN_PLAIN_PRICES[0])


def test_trader_volume_added_to_tick_volume():
    ticks = CoinSimulator(_coin(), seed=1, traders=[_always_buyer(cash=1e9)]).run(10)
    for tick, background in zip(ticks, GOLDEN_PLAIN_VOLUMES):
        trader_volume = sum(f.quantity for f in tick.trader_trades)
        assert trader_volume > 0
        assert tick.volume == pytest.approx(background + trader_volume)


def test_whale_and_trader_volume_both_counted():
    tick = CoinSimulator(_coin(), seed=1, whales=[_golden_whale()], traders=[_always_buyer()]).step()
    whale_volume = sum(w.quantity for w in tick.whale_trades)
    trader_volume = sum(f.quantity for f in tick.trader_trades)
    assert whale_volume > 0 and trader_volume > 0
    assert tick.volume == pytest.approx(GOLDEN_PLAIN_VOLUMES[0] + whale_volume + trader_volume)


def test_net_buying_raises_price_by_impact_factor():
    tick = CoinSimulator(_coin(), seed=1, traders=[_always_buyer()]).step()
    expected = GOLDEN_PLAIN_PRICES[0] * net_flow_price_impact(10_000.0, SUPPLY, 2.0)
    assert tick.price == pytest.approx(expected)
    assert tick.price > GOLDEN_PLAIN_PRICES[0]
    assert tick.market_cap == pytest.approx(tick.price * SUPPLY)


def test_net_selling_lowers_price_by_impact_factor():
    tick = CoinSimulator(_coin(), seed=1, traders=[_always_seller()]).step()
    expected = GOLDEN_PLAIN_PRICES[0] * net_flow_price_impact(-10_000.0, SUPPLY, 2.0)
    assert tick.price == pytest.approx(expected)
    assert tick.price < GOLDEN_PLAIN_PRICES[0]


def test_balanced_flow_leaves_price_unchanged():
    buyer = _always_buyer(max_size=5_000.0)
    seller = _always_seller(max_size=5_000.0)
    tick = CoinSimulator(_coin(), seed=1, traders=[buyer, seller]).step()
    assert len(tick.trader_trades) == 2
    assert tick.price == GOLDEN_PLAIN_PRICES[0]


def test_price_impact_goes_through_market_engine_and_persists():
    sim = CoinSimulator(_coin(), seed=1, traders=[_always_buyer()])
    tick = sim.step()
    assert sim.current_price == tick.price
    # The next random-walk step compounds from the impacted price.
    next_no_trade = GOLDEN_PLAIN_PRICES[1] / GOLDEN_PLAIN_PRICES[0] * tick.price
    sim.traders.clear()
    assert sim.step().price == pytest.approx(next_no_trade)


def test_zero_impact_coefficient_moves_volume_but_not_price():
    ticks = CoinSimulator(_coin(), seed=1, traders=[_always_buyer()], trader_impact_coefficient=0.0).run(5)
    assert [t.price for t in ticks] == GOLDEN_PLAIN_PRICES[:5]
    assert ticks[0].volume > GOLDEN_PLAIN_VOLUMES[0]


# --- balances & accounting ----------------------------------------------------


def test_buyer_stops_buying_when_cash_runs_out():
    buyer = _always_buyer(cash=25_000.0)
    sim = CoinSimulator(_coin(), seed=1, traders=[buyer])
    ticks = sim.run(10)
    assert buyer.wallet.cash == 0.0
    assert sum(f.notional for t in ticks for f in t.trader_trades) == pytest.approx(25_000.0)
    assert ticks[-1].trader_trades == ()


def test_seller_stops_selling_when_holdings_run_out():
    seller = _always_seller(coins=25_000.0)
    sim = CoinSimulator(_coin(), seed=1, traders=[seller])
    ticks = sim.run(10)
    assert seller.wallet.coins == 0.0
    assert sum(f.quantity for t in ticks for f in t.trader_trades) == pytest.approx(25_000.0)
    assert ticks[-1].trader_trades == ()


def test_coins_and_cash_conserved_over_long_run_with_all_trader_types():
    sim = CoinSimulator(_coin(), seed=3, whales=[_golden_whale()], traders=_all_five(), reserve_cash=500_000.0)
    coins_before, cash_before = _totals(sim)
    for _ in range(500):
        sim.step()
        for wallet in (sim.reserve, *(t.wallet for t in sim.traders)):
            assert wallet.cash >= 0.0
            assert wallet.coins >= 0.0
    coins_after, cash_after = _totals(sim)
    assert coins_after == pytest.approx(coins_before, rel=1e-12)
    assert cash_after == pytest.approx(cash_before, rel=1e-12)
    assert sum(len(t.trader_trades) for t in sim.history) > 100


def test_every_trader_type_trades_in_a_long_run():
    sim = CoinSimulator(_coin(), seed=3, traders=_all_five(), volatility=0.04)
    sim.run(500)
    strategies = {f.strategy for t in sim.history for f in t.trader_trades}
    assert strategies == {"retail", "momentum", "dip_buyer", "panic_seller", "long_term_holder"}


def test_reserve_starts_with_unallocated_supply_and_default_cash():
    traders = _all_five()
    trader_coins = sum(t.wallet.coins for t in traders)
    sim = CoinSimulator(_coin(), seed=1, whales=[_golden_whale()], traders=traders)
    assert sim.reserve.coins == SUPPLY - 100_000.0 - trader_coins
    assert sim.reserve.cash == sim.reserve.coins * 2.0


def test_starting_holdings_get_cost_basis_at_starting_price():
    sim = CoinSimulator(_coin(), seed=1, traders=_all_five())
    for trader in sim.traders:
        expected = 2.0 if trader.wallet.coins > 0 else 0.0
        assert trader.wallet.average_cost == expected


def test_rejects_holdings_exceeding_supply():
    trader = RetailTrader("rich", starting_coins=950_000.0)
    with pytest.raises(ValueError):
        CoinSimulator(_coin(), whales=[_golden_whale()], traders=[trader])


def test_rejects_duplicate_trader_ids():
    with pytest.raises(ValueError):
        CoinSimulator(_coin(), traders=[RetailTrader("same"), RetailTrader("same")])


def test_rejects_negative_impact_coefficient():
    with pytest.raises(ValueError):
        CoinSimulator(_coin(), traders=[RetailTrader("r")], trader_impact_coefficient=-1.0)


# --- determinism --------------------------------------------------------------


def _full_run(trader_seed_base=10):
    sim = CoinSimulator(_coin(), seed=3, whales=[_golden_whale()], traders=_all_five(trader_seed_base))
    return sim, sim.run(200)


def test_same_seeds_reproduce_ticks_and_wallets_exactly():
    sim_a, ticks_a = _full_run()
    sim_b, ticks_b = _full_run()
    assert _market_view(ticks_a) == _market_view(ticks_b)
    assert [t.wallet for t in sim_a.traders] == [t.wallet for t in sim_b.traders]
    assert sim_a.reserve == sim_b.reserve


def test_different_trader_seeds_change_trader_activity():
    _, ticks_a = _full_run(trader_seed_base=10)
    _, ticks_b = _full_run(trader_seed_base=20)
    assert [t.trader_trades for t in ticks_a] != [t.trader_trades for t in ticks_b]


# --- extension point ------------------------------------------------------------


class _RecordingTrader(TraderAgent):
    """A custom strategy defined only in tests: proves new strategies plug in
    without touching CoinSimulator, and exposes what traders observe."""

    strategy_name = "recorder"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contexts: list[MarketContext] = []

    @property
    def lookback(self) -> int:
        return 3

    def _decide(self, context: MarketContext) -> TradeDecision:
        self.contexts.append(context)
        return TradeDecision.hold("observing")


def test_custom_strategy_sees_current_price_and_bounded_history():
    recorder = _RecordingTrader("rec", trade_probability=1.0, seed=1)
    ticks = CoinSimulator(_coin(), seed=1, traders=[recorder]).run(6)
    contexts = recorder.contexts
    assert [c.tick for c in contexts] == [1, 2, 3, 4, 5, 6]
    assert [c.price for c in contexts] == [t.price for t in ticks]
    assert contexts[0].price_history == (2.0,)
    assert contexts[1].price_history == (2.0, ticks[0].price)
    assert contexts[5].price_history == tuple(t.price for t in ticks[2:5])
    assert all(c.total_supply == SUPPLY for c in contexts)
