import pytest

from crypto_simulator.core.traders.base import MarketContext


def _ctx(price, history):
    return MarketContext(tick=len(history), price=price, price_history=tuple(history), total_supply=1_000_000.0)


def test_return_over_needs_enough_history():
    ctx = _ctx(1.1, [1.0, 1.0])
    assert ctx.return_over(3) is None
    assert ctx.return_over(2) == pytest.approx(0.1)


def test_return_over_uses_close_lookback_ticks_ago():
    ctx = _ctx(1.2, [1.0, 1.5, 1.1])
    assert ctx.return_over(1) == pytest.approx(1.2 / 1.1 - 1)
    assert ctx.return_over(3) == pytest.approx(0.2)


def test_recent_high_low_include_current_price():
    ctx = _ctx(0.8, [1.0, 1.2, 0.9])
    assert ctx.recent_high(3) == 1.2
    assert ctx.recent_low(3) == 0.8
    assert ctx.recent_high(1) == 0.9


def test_drawdown_and_rise():
    ctx = _ctx(0.9, [1.0, 0.75])
    assert ctx.drawdown_from_high(2) == pytest.approx(0.1)
    assert ctx.rise_from_low(2) == pytest.approx(0.2)
