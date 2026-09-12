import pytest

from crypto_simulator.core.traders.base import MarketContext, TradeAction
from crypto_simulator.core.traders.manipulation import PumpAndDump, SchemePhase, WashTrader
from crypto_simulator.core.traders.registry import (
    MANIPULATION_STRATEGIES,
    TRADER_STRATEGIES,
    create_manipulator,
    create_trader,
)


def _ctx(tick, price=2.0):
    return MarketContext(tick=tick, price=price, price_history=(price,), total_supply=1_000_000.0)


def _pnd(**kwargs):
    defaults = dict(
        starting_cash=10_000.0, trade_probability=1.0, max_trade_size=1e9, risk_tolerance=1.0,
        start_tick=3, accumulate_ticks=4, accumulate_share=0.4, pump_ticks=2, dump_ticks=2, seed=1,
    )
    return PumpAndDump("pd", **{**defaults, **kwargs})


def _fill_buy(trader, decision, price):
    """Settle a buy the way the simulator would, without a counterparty."""
    trader.wallet.withdraw_cash(decision.quantity * price)
    trader.wallet.deposit_coins(decision.quantity, cost=decision.quantity * price)


# --- pump and dump ----------------------------------------------------------------------


def test_phase_schedule_follows_ticks():
    pd = _pnd()
    phases = [pd.phase(t) for t in range(1, 12)]
    assert phases[:2] == [SchemePhase.WAITING] * 2
    assert phases[2:6] == [SchemePhase.ACCUMULATE] * 4  # ticks 3-6
    assert phases[6:8] == [SchemePhase.PUMP] * 2  # ticks 7-8
    # Dump from tick 9 onward — reported as done while it holds no coins.
    assert phases[8:] == [SchemePhase.DONE] * 3
    pd.wallet.deposit_coins(1.0)
    assert pd.phase(9) is SchemePhase.DUMP
    assert pd.phase(50) is SchemePhase.DUMP


def test_waits_before_start_tick():
    decision = _pnd().decide(_ctx(1))
    assert decision.action is TradeAction.HOLD
    assert decision.reason == "waiting"


def test_accumulates_a_fixed_slice_of_the_budget_each_tick():
    pd = _pnd()
    per_tick_cash = 10_000.0 * 0.4 / 4
    for tick in range(3, 7):
        decision = pd.decide(_ctx(tick, price=2.0))
        assert decision.action is TradeAction.BUY
        assert decision.reason == "accumulate"
        assert decision.quantity == pytest.approx(per_tick_cash / 2.0)
        _fill_buy(pd, decision, 2.0)
    assert pd.wallet.cash == pytest.approx(6_000.0)


def test_pump_spends_the_rest_of_the_budget_evenly_over_remaining_pump_ticks():
    pd = _pnd()
    for tick in range(3, 7):
        _fill_buy(pd, pd.decide(_ctx(tick)), 2.0)
    first = pd.decide(_ctx(7, price=3.0))
    assert first.action is TradeAction.BUY and first.reason == "pump"
    assert first.quantity == pytest.approx(6_000.0 / 2 / 3.0)
    _fill_buy(pd, first, 3.0)
    last = pd.decide(_ctx(8, price=4.0))
    assert last.quantity == pytest.approx(3_000.0 / 4.0)  # everything left
    _fill_buy(pd, last, 4.0)
    assert pd.wallet.cash == pytest.approx(0.0, abs=1e-9)
    assert pd.decide(_ctx(8)).action is TradeAction.HOLD  # budget spent


def test_pump_catches_up_after_a_skipped_tick():
    pd = _pnd(accumulate_ticks=0, pump_ticks=4)
    decision = pd.decide(_ctx(5, price=1.0))  # ticks 3-4 skipped: 2 pump ticks left
    assert decision.quantity == pytest.approx(10_000.0 / 2)


def test_dump_sells_evenly_then_everything_left_after_the_window():
    pd = _pnd(dump_ticks=4)
    pd.wallet.deposit_coins(1_000.0)
    first = pd.decide(_ctx(9))  # dump window is ticks 9-12
    assert (first.action, first.reason, first.quantity) == (TradeAction.SELL, "dump", 250.0)
    assert pd.decide(_ctx(11)).quantity == 500.0
    assert pd.decide(_ctx(12)).quantity == 1_000.0
    assert pd.decide(_ctx(40)).quantity == 1_000.0  # window over: sell it all


def test_done_once_coins_are_gone():
    pd = _pnd()
    decision = pd.decide(_ctx(20))
    assert decision.action is TradeAction.HOLD
    assert decision.reason == "done"


def test_risk_tolerance_sets_the_budget_and_the_rest_is_never_spent():
    pd = _pnd(risk_tolerance=0.5, accumulate_ticks=0, pump_ticks=1)
    assert pd.budget == 5_000.0
    decision = pd.decide(_ctx(3, price=1.0))
    assert decision.quantity == pytest.approx(5_000.0)
    _fill_buy(pd, decision, 1.0)
    assert pd.wallet.cash == pytest.approx(5_000.0)


def test_orders_are_capped_at_max_trade_size():
    pd = _pnd(max_trade_size=100.0, accumulate_ticks=0, pump_ticks=1)
    assert pd.decide(_ctx(3, price=1.0)).quantity == 100.0
    pd.wallet.deposit_coins(1_000.0)
    assert pd.decide(_ctx(20)).quantity == 100.0


def test_trade_probability_gate_still_applies():
    pd = _pnd(trade_probability=0.0)
    assert all(pd.decide(_ctx(t)).action is TradeAction.HOLD for t in range(1, 20))


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"start_tick": 0}, "start_tick"),
        ({"accumulate_ticks": -1}, "accumulate_ticks"),
        ({"pump_ticks": 0}, "pump_ticks"),
        ({"dump_ticks": 0}, "dump_ticks"),
        ({"accumulate_share": 1.5}, "accumulate_share"),
    ],
)
def test_pump_and_dump_rejects_bad_parameters(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _pnd(**kwargs)


# --- wash trader ------------------------------------------------------------------------


def test_wash_trader_decides_wash_sized_like_a_buy():
    trader = WashTrader("w", starting_cash=1_000.0, trade_probability=1.0, max_trade_size=1e9, risk_tolerance=0.5)
    decision = trader.decide(_ctx(1, price=2.0))
    assert decision.action is TradeAction.WASH
    assert decision.quantity == 250.0
    capped = WashTrader("w", starting_cash=1_000.0, trade_probability=1.0, max_trade_size=10.0)
    assert capped.decide(_ctx(1)).quantity == 10.0


def test_wash_trader_without_cash_holds():
    trader = WashTrader("w", starting_coins=100.0, trade_probability=1.0)
    assert trader.decide(_ctx(1)).action is TradeAction.HOLD


# --- registry ---------------------------------------------------------------------------


def test_manipulation_registry_is_separate_from_organic_strategies():
    assert set(MANIPULATION_STRATEGIES) == {"pump_and_dump", "wash_trader"}
    assert not set(MANIPULATION_STRATEGIES) & set(TRADER_STRATEGIES)


def test_create_manipulator_builds_and_passes_params():
    pd = create_manipulator("pump_and_dump", "pd", params={"pump_ticks": 7}, starting_cash=5.0)
    assert isinstance(pd, PumpAndDump)
    assert pd.pump_ticks == 7
    assert isinstance(create_manipulator("wash_trader", "w"), WashTrader)


def test_manipulation_strategies_are_rejected_as_organic_traders_with_a_hint():
    with pytest.raises(ValueError, match="coin.manipulators"):
        create_trader("wash_trader", "w")
    with pytest.raises(ValueError, match="Unknown manipulator strategy"):
        create_manipulator("momentum", "m")
    with pytest.raises(ValueError, match="Invalid parameters for 'pump_and_dump' manipulator"):
        create_manipulator("pump_and_dump", "pd", params={"nope": 1})
