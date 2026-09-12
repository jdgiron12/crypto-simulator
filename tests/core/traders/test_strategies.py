import pytest

from crypto_simulator.core.traders.base import MarketContext, TradeAction
from crypto_simulator.core.traders.strategies import (
    DipBuyer,
    LongTermHolder,
    MomentumTrader,
    PanicSeller,
    RetailTrader,
)

COMMON = dict(trade_probability=1.0, max_trade_size=1_000_000.0, risk_tolerance=0.5, seed=1)


def _ctx(price, history):
    return MarketContext(tick=len(history), price=price, price_history=tuple(history), total_supply=1_000_000.0)


# --- shared TraderAgent behavior ---------------------------------------------


def test_zero_trade_probability_always_holds():
    trader = RetailTrader("r", starting_cash=1_000.0, **{**COMMON, "trade_probability": 0.0})
    decisions = [trader.decide(_ctx(1.0, [1.0])) for _ in range(200)]
    assert all(d.action is TradeAction.HOLD for d in decisions)


def test_full_trade_probability_always_evaluates_strategy():
    trader = RetailTrader("r", starting_cash=1_000.0, buy_bias=1.0, **COMMON)
    decisions = [trader.decide(_ctx(1.0, [1.0])) for _ in range(50)]
    assert all(d.action is TradeAction.BUY for d in decisions)


def test_partial_trade_probability_holds_some_ticks():
    trader = RetailTrader("r", starting_cash=1_000.0, buy_bias=1.0, **{**COMMON, "trade_probability": 0.3})
    actions = [trader.decide(_ctx(1.0, [1.0])).action for _ in range(500)]
    buys = actions.count(TradeAction.BUY)
    assert 0 < buys < 500
    assert buys == pytest.approx(150, abs=50)


def test_buy_size_uses_risk_tolerance_of_cash():
    trader = RetailTrader("r", starting_cash=10_000.0, buy_bias=1.0, **COMMON)
    decision = trader.decide(_ctx(2.0, [2.0]))
    assert decision.quantity == pytest.approx(0.5 * 10_000.0 / 2.0)


def test_sell_size_uses_risk_tolerance_of_holdings():
    trader = RetailTrader("r", starting_coins=800.0, buy_bias=0.0, **COMMON)
    assert trader.decide(_ctx(1.0, [1.0])).quantity == pytest.approx(400.0)


def test_trade_size_capped_by_max_trade_size():
    trader = RetailTrader("r", starting_cash=10_000.0, buy_bias=1.0, **{**COMMON, "max_trade_size": 250.0})
    assert trader.decide(_ctx(1.0, [1.0])).quantity == 250.0


def test_decisions_are_reproducible_given_same_seed():
    def actions(seed):
        trader = RetailTrader(
            "r", starting_cash=1_000.0, starting_coins=1_000.0, **{**COMMON, "trade_probability": 0.5, "seed": seed}
        )
        return [trader.decide(_ctx(1.0, [1.0])) for _ in range(100)]

    assert actions(5) == actions(5)
    assert actions(5) != actions(6)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trade_probability": 1.5},
        {"trade_probability": -0.1},
        {"max_trade_size": 0.0},
        {"risk_tolerance": 0.0},
        {"risk_tolerance": 1.1},
        {"starting_cash": -1.0},
        {"starting_coins": -1.0},
    ],
)
def test_invalid_common_characteristics_rejected(kwargs):
    with pytest.raises(ValueError):
        RetailTrader("r", **kwargs)


def test_empty_trader_id_rejected():
    with pytest.raises(ValueError):
        RetailTrader("")


# --- RetailTrader -------------------------------------------------------------


def test_retail_buy_bias_one_buys_and_zero_sells():
    buyer = RetailTrader("r1", starting_cash=100.0, starting_coins=100.0, buy_bias=1.0, **COMMON)
    seller = RetailTrader("r2", starting_cash=100.0, starting_coins=100.0, buy_bias=0.0, **COMMON)
    assert buyer.decide(_ctx(1.0, [1.0])).action is TradeAction.BUY
    assert seller.decide(_ctx(1.0, [1.0])).action is TradeAction.SELL


def test_retail_holds_when_chosen_side_has_no_balance():
    broke_buyer = RetailTrader("r1", starting_cash=0.0, starting_coins=100.0, buy_bias=1.0, **COMMON)
    empty_seller = RetailTrader("r2", starting_cash=100.0, starting_coins=0.0, buy_bias=0.0, **COMMON)
    assert broke_buyer.decide(_ctx(1.0, [1.0])).action is TradeAction.HOLD
    assert empty_seller.decide(_ctx(1.0, [1.0])).action is TradeAction.HOLD


def test_retail_rejects_invalid_buy_bias():
    with pytest.raises(ValueError):
        RetailTrader("r", buy_bias=1.5)


# --- MomentumTrader -----------------------------------------------------------


def _momentum():
    return MomentumTrader(
        "m", starting_cash=10_000.0, starting_coins=5_000.0, lookback=5,
        entry_threshold=0.03, exit_threshold=0.03, **COMMON,
    )


def test_momentum_buys_uptrend():
    decision = _momentum().decide(_ctx(1.05, [1.0] * 5))
    assert decision.action is TradeAction.BUY


def test_momentum_sells_downtrend():
    decision = _momentum().decide(_ctx(0.95, [1.0] * 5))
    assert decision.action is TradeAction.SELL


def test_momentum_holds_without_clear_trend():
    assert _momentum().decide(_ctx(1.01, [1.0] * 5)).action is TradeAction.HOLD


def test_momentum_holds_without_enough_history():
    assert _momentum().decide(_ctx(2.0, [1.0] * 3)).action is TradeAction.HOLD


def test_momentum_reports_lookback_and_validates_params():
    assert _momentum().lookback == 5
    with pytest.raises(ValueError):
        MomentumTrader("m", lookback=0)
    with pytest.raises(ValueError):
        MomentumTrader("m", entry_threshold=-0.1)


# --- DipBuyer -----------------------------------------------------------------


def test_dip_buyer_buys_after_dip():
    trader = DipBuyer("d", starting_cash=10_000.0, lookback=10, dip_threshold=0.06, **COMMON)
    decision = trader.decide(_ctx(1.0, [1.0, 1.1, 1.05]))
    assert decision.action is TradeAction.BUY


def test_dip_buyer_holds_without_dip():
    trader = DipBuyer("d", starting_cash=10_000.0, lookback=10, dip_threshold=0.06, **COMMON)
    assert trader.decide(_ctx(1.0, [1.0, 1.02])).action is TradeAction.HOLD


def test_dip_buyer_takes_profit_above_cost_basis():
    trader = DipBuyer("d", starting_coins=1_000.0, lookback=10, take_profit=0.12, **COMMON)
    trader.wallet.average_cost = 1.0
    decision = trader.decide(_ctx(1.2, [1.15, 1.2]))
    assert decision.action is TradeAction.SELL
    assert decision.quantity == pytest.approx(500.0)


def test_dip_buyer_does_not_take_profit_below_target():
    trader = DipBuyer("d", starting_coins=1_000.0, lookback=10, take_profit=0.12, **COMMON)
    trader.wallet.average_cost = 1.0
    assert trader.decide(_ctx(1.1, [1.08, 1.1])).action is TradeAction.HOLD


def test_dip_buyer_validates_params():
    with pytest.raises(ValueError):
        DipBuyer("d", take_profit=0.0)
    with pytest.raises(ValueError):
        DipBuyer("d", dip_threshold=2.0)


# --- PanicSeller --------------------------------------------------------------


def _panic(**overrides):
    kwargs = dict(starting_cash=10_000.0, starting_coins=1_000.0, lookback=5, panic_threshold=0.08, reentry_threshold=0.08)
    kwargs.update(overrides)
    return PanicSeller("p", **kwargs, **COMMON)


def test_panic_seller_sells_on_sharp_drop():
    decision = _panic().decide(_ctx(0.9, [1.0, 1.0]))
    assert decision.action is TradeAction.SELL
    assert decision.quantity == pytest.approx(500.0)


def test_panic_seller_holds_during_panic_with_no_coins():
    assert _panic(starting_coins=0.0).decide(_ctx(0.9, [1.0, 1.0])).action is TradeAction.HOLD


def test_panic_seller_buys_back_on_fomo_rally():
    decision = _panic().decide(_ctx(1.0, [0.9, 0.92]))
    assert decision.action is TradeAction.BUY


def test_panic_seller_holds_when_calm():
    assert _panic().decide(_ctx(1.01, [1.0, 1.0])).action is TradeAction.HOLD


def test_panic_seller_validates_params():
    with pytest.raises(ValueError):
        PanicSeller("p", reentry_threshold=0.0)
    with pytest.raises(ValueError):
        PanicSeller("p", lookback=0)


# --- LongTermHolder -----------------------------------------------------------


def _holder():
    trader = LongTermHolder(
        "l", starting_cash=10_000.0, starting_coins=1_000.0,
        take_profit_multiple=3.0, max_buy_premium=0.2, **COMMON,
    )
    trader.wallet.average_cost = 1.0
    return trader


def test_long_term_holder_accumulates_near_cost_basis():
    assert _holder().decide(_ctx(1.1, [1.0])).action is TradeAction.BUY


def test_long_term_holder_buys_without_cost_basis():
    trader = LongTermHolder("l", starting_cash=1_000.0, **COMMON)
    assert trader.decide(_ctx(50.0, [50.0])).action is TradeAction.BUY


def test_long_term_holder_holds_when_price_too_far_above_cost():
    assert _holder().decide(_ctx(1.5, [1.4])).action is TradeAction.HOLD


def test_long_term_holder_sells_at_take_profit_multiple():
    decision = _holder().decide(_ctx(3.0, [2.9]))
    assert decision.action is TradeAction.SELL


def test_long_term_holder_validates_params():
    with pytest.raises(ValueError):
        LongTermHolder("l", take_profit_multiple=1.0)
    with pytest.raises(ValueError):
        LongTermHolder("l", max_buy_premium=-0.1)
