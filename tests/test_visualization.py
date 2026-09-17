import pandas as pd
import pytest

from crypto_simulator.visualization.charts import (
    allocation_chart,
    candlestick_chart,
    equity_curve_chart,
    price_path_chart,
)


def test_candlestick_chart_builds_figure():
    df = pd.DataFrame(
        {
            "timestamp": ["2024-01-01", "2024-01-02"],
            "open": [100, 105],
            "high": [110, 108],
            "low": [95, 100],
            "close": [105, 102],
        }
    )
    fig = candlestick_chart(df)
    assert fig.data[0].type == "candlestick"


def test_candlestick_chart_requires_columns():
    with pytest.raises(ValueError):
        candlestick_chart(pd.DataFrame({"timestamp": [1]}))


def test_equity_curve_chart_builds_figure():
    df = pd.DataFrame({"timestamp": ["2024-01-01", "2024-01-02"], "equity": [100000, 101000]})
    fig = equity_curve_chart(df)
    assert fig.data[0].type == "scatter"


def test_allocation_chart_builds_figure():
    fig = allocation_chart({"BTC": 60000.0, "ETH": 3000.0})
    assert fig.data[0].type == "pie"


def test_price_path_chart_builds_figure():
    df = pd.DataFrame({"tick": [1, 2, 3], "price": [1.0, 1.1, 1.05]})
    fig = price_path_chart(df)
    assert fig.data[0].type == "scatter"
    assert list(fig.data[0].x) == [1, 2, 3]
    assert list(fig.data[0].y) == [1.0, 1.1, 1.05]


def test_price_path_chart_requires_columns():
    with pytest.raises(ValueError):
        price_path_chart(pd.DataFrame({"tick": [1]}))
