"""Tick-level Plotly chart builders (Phase 20, Step 4).

Pure functions over the recorded per-tick values a run's ``TickSeries``
holds: sequences in, a ``go.Figure`` (or plain frozen records) out. No
Streamlit, no simulation, no data access, no clock; inputs are never
mutated, and the same inputs always give the same figure. The x-axis is
always the simulation tick.

**Synthetic OHLC.** The simulator records one price per tick, so there is
no intra-tick open, high, low or close. ``synthetic_ohlc`` groups the
recorded tick prices into consecutive windows of rows and summarizes each
window — open is the window's first recorded price, high its maximum, low
its minimum, close its last. Every figure built from it says so
(``SYNTHETIC_OHLC_DISCLOSURE``); it is not exchange OHLC data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import plotly.graph_objects as go

from crypto_simulator.visualization.style import CHART_LAYOUT

__all__ = [
    "SYNTHETIC_OHLC_DISCLOSURE",
    "OhlcWindow",
    "synthetic_ohlc",
    "synthetic_ohlc_chart",
    "volume_composition_chart",
]

SYNTHETIC_OHLC_DISCLOSURE = "Synthetic OHLC aggregated from recorded simulation-tick prices."


@dataclass(frozen=True)
class OhlcWindow:
    """One window of consecutive recorded ticks.

    ``rows`` is how many recorded ticks the window holds; ``partial`` is
    True for a final window holding fewer rows than the window size.
    """

    first_tick: int
    last_tick: int
    rows: int
    open: float
    high: float
    low: float
    close: float
    partial: bool


def synthetic_ohlc(ticks: Sequence[int], prices: Sequence[float], window: int) -> tuple[OhlcWindow, ...]:
    """Group recorded tick prices into windows of ``window`` rows, in order.

    Windows are counted in recorded rows from the first row; the last one
    may be shorter and is then marked ``partial``. One pass, and nothing
    is interpolated: every open, high, low and close is a recorded price.

    Raises:
        ValueError: ``window`` is not a positive int, or ``ticks`` and
            ``prices`` differ in length.
    """
    if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive int (got {window!r})")
    if len(ticks) != len(prices):
        raise ValueError(f"ticks and prices differ in length ({len(ticks)} vs {len(prices)})")
    windows: list[OhlcWindow] = []
    for start in range(0, len(ticks), window):
        chunk = prices[start:start + window]
        rows = len(chunk)
        windows.append(OhlcWindow(
            first_tick=ticks[start],
            last_tick=ticks[start + rows - 1],
            rows=rows,
            open=chunk[0],
            high=max(chunk),
            low=min(chunk),
            close=chunk[-1],
            partial=rows < window,
        ))
    return tuple(windows)


def synthetic_ohlc_chart(windows: Sequence[OhlcWindow], *, title: str) -> go.Figure:
    """Candles for ``synthetic_ohlc`` windows, each placed at its first
    tick; hover gives the window's tick range and row count. The title
    carries ``SYNTHETIC_OHLC_DISCLOSURE``."""
    hover = [
        f"Ticks {w.first_tick}-{w.last_tick} ({w.rows} recorded "
        f"{'tick' if w.rows == 1 else 'ticks'}{', partial window' if w.partial else ''})"
        f"<br>Open {w.open:,.4f}<br>High {w.high:,.4f}<br>Low {w.low:,.4f}<br>Close {w.close:,.4f}"
        for w in windows
    ]
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=[w.first_tick for w in windows],
                open=[w.open for w in windows],
                high=[w.high for w in windows],
                low=[w.low for w in windows],
                close=[w.close for w in windows],
                name="Synthetic OHLC",
                text=hover,
                hoverinfo="text",
            )
        ]
    )
    fig.update_layout(
        title=f"{title}<br><sup>{SYNTHETIC_OHLC_DISCLOSURE}</sup>",
        xaxis_title="Simulation tick (window start)",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        **CHART_LAYOUT,
    )
    return fig


def volume_composition_chart(
    ticks: Sequence[int],
    components: Sequence[tuple[str, Sequence[float]]],
    *,
    title: str,
    unit: str,
) -> go.Figure:
    """Stacked per-tick bars, one trace per ``(name, values)`` component,
    in the order given. ``barmode="relative"`` stacks a (rounding-sized)
    negative value below zero rather than hiding it.

    Raises:
        ValueError: a component's length differs from ``ticks``.
    """
    for name, values in components:
        if len(values) != len(ticks):
            raise ValueError(f"component {name!r} has {len(values)} values for {len(ticks)} ticks")
    fig = go.Figure(
        data=[
            go.Bar(
                x=list(ticks),
                y=list(values),
                name=name,
                hovertemplate=f"Tick %{{x}}<br>{name} %{{y:,.4f}} {unit}<extra></extra>",
            )
            for name, values in components
        ]
    )
    fig.update_layout(
        title=title,
        barmode="relative",
        xaxis_title="Simulation tick",
        yaxis_title=f"Volume ({unit})",
        **CHART_LAYOUT,
    )
    return fig
