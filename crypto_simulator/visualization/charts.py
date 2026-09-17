"""Plotly chart builders.

Pure functions: a pandas DataFrame in, a ``go.Figure`` out. No Streamlit
calls, no data access — callers (the app layer) fetch data via services
and hand it here for rendering.
"""

from __future__ import annotations

from typing import Sequence

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


def price_path_chart(
    df: pd.DataFrame,
    *,
    title: str = "Price",
    markers: Sequence[tuple[str, float, float]] = (),
) -> go.Figure:
    """Build a line chart of a simulated price path over tick numbers.

    Expects columns: ``tick``, ``price``; an optional ``volume`` column is
    added to the hover text. Used by the coin-economy dashboard, whose
    time axis is the tick number rather than a timestamp (the simulation
    clock is anchored to wall-clock time, so tick numbers are what stays
    the same between two identical runs).

    ``markers`` are ``(label, tick, price)`` points to annotate — the
    caller supplies them (e.g. the analytics' own high and low), and this
    function neither picks nor computes them. Rows are plotted in the
    order given, so the same data always yields the same figure.
    """
    required = {"tick", "price"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"price_path_chart: missing columns {sorted(missing)}")

    hover = "Tick %{x}<br>Price %{y:,.4f}"
    extra: dict[str, object] = {}
    if "volume" in df.columns:
        extra["customdata"] = df["volume"]
        hover += "<br>Volume %{customdata:,.0f}"

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df["tick"],
                y=df["price"],
                mode="lines",
                name="Price",
                hovertemplate=f"{hover}<extra></extra>",
                **extra,
            )
        ]
    )
    if markers:
        fig.add_trace(
            go.Scatter(
                x=[point[1] for point in markers],
                y=[point[2] for point in markers],
                mode="markers+text",
                text=[point[0] for point in markers],
                textposition="top center",
                name="High / low",
                hovertemplate="%{text}: %{y:,.4f} at tick %{x}<extra></extra>",
            )
        )
    fig.update_layout(title=title, xaxis_title="Tick", yaxis_title="Price")
    return fig


def component_lines_chart(
    df: pd.DataFrame,
    *,
    series: Sequence[str],
    title: str = "Components",
    value_title: str = "Value",
) -> go.Figure:
    """Build a multi-series line chart over tick numbers.

    Expects a ``tick`` column plus one column per name in ``series``, each
    already holding the values to plot (the coin-economy dashboard passes
    the psychology components the report recorded per tick). Series are
    drawn in the order given, so the same data always yields the same
    figure.
    """
    missing = {"tick", *series} - set(df.columns)
    if missing:
        raise ValueError(f"component_lines_chart: missing columns {sorted(missing)}")

    fig = go.Figure(
        data=[
            go.Scatter(
                x=df["tick"],
                y=df[name],
                mode="lines",
                name=name,
                hovertemplate=f"Tick %{{x}}<br>{name} %{{y:.4f}}<extra></extra>",
            )
            for name in series
        ]
    )
    fig.update_layout(title=title, xaxis_title="Tick", yaxis_title=value_title)
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
