import pandas as pd
import pytest

from crypto_simulator.visualization.charts import (
    allocation_chart,
    candlestick_chart,
    equity_curve_chart,
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
