"""Plotly chart builders.

Pure functions: a pandas DataFrame in, a ``go.Figure`` out. No Streamlit
calls, no data access — callers (the app layer) fetch data via services
and hand it here for rendering.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def candlestick_chart(df: pd.DataFrame, *, title: str = "Price") -> go.Figure:
    """Build a candlestick chart from OHLC data.

    Expects columns: ``timestamp``, ``open``, ``high``, ``low``, ``close``.
    """
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"candlestick_chart: missing columns {sorted(missing)}")

    fig = go.Figure(
        data=[
            go.Candlestick(
                x=df["timestamp"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
            )
        ]
    )
    fig.update_layout(title=title, xaxis_title="Time", yaxis_title="Price")
    return fig


def equity_curve_chart(df: pd.DataFrame, *, title: str = "Portfolio Equity") -> go.Figure:
    """Build a line chart of simulated portfolio value over time.

    Expects columns: ``timestamp``, ``equity``.
    """
    required = {"timestamp", "equity"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"equity_curve_chart: missing columns {sorted(missing)}")

    fig = go.Figure(
        data=[go.Scatter(x=df["timestamp"], y=df["equity"], mode="lines", name="Equity")]
    )
    fig.update_layout(title=title, xaxis_title="Time", yaxis_title="Equity")
    return fig


def allocation_chart(holdings: dict[str, float], *, title: str = "Allocation") -> go.Figure:
    """Build a pie chart of position value by symbol.

    ``holdings`` maps symbol -> current market value.
    """
    labels = list(holdings.keys())
    values = list(holdings.values())
    fig = go.Figure(data=[go.Pie(labels=labels, values=values)])
    fig.update_layout(title=title)
    return fig
