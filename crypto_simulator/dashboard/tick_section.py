"""The tick-level views of the dashboard (Phase 20, Step 4).

Display only. The section receives the serialized ``TickSeries`` of the run
(``dashboard.data.tick_series_to_dict``) and draws four views from its
recorded per-tick columns; it runs no simulation and rebuilds no analytics.
Changing the synthetic OHLC window re-renders the stored series — only the
Run button runs a simulation.

**Layout** (one tick series, read once):

    synthetic OHLC   windows of recorded tick prices (5/10/20/50 ticks)
    volume           per-tick recorded volume, stacked by its recorded split
    pool state       AMM reserves, invariant, cumulative fees and swaps
    event state      recorded sentiment, multipliers and live-event count

**Not duplicated here.** The price path is the market section's chart; in
AMM mode the recorded price is the pool's spot price, so there is no second
spot-price line. The per-tick psychology components are the psychology
section's chart.

**No tick series, no views.** A run without a tick series — a saved run,
since the tick series is never persisted, or a payload from a runner that
returns only a payload — shows ``TICK_SERIES_UNAVAILABLE_MESSAGE`` and
nothing is rebuilt from the payload.

**Recorded state, described as such.** Event columns are the event state
the simulator recorded on each tick, shown next to each other and to
nothing else; the section says what was recorded, never why the market
moved.
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.data import TICK_SERIES_UNAVAILABLE_MESSAGE
from crypto_simulator.visualization.charts import component_lines_chart
from crypto_simulator.visualization.tick_charts import (
    SYNTHETIC_OHLC_DISCLOSURE,
    synthetic_ohlc,
    synthetic_ohlc_chart,
    volume_composition_chart,
)

__all__ = [
    "NO_EVENT_STATE_MESSAGE",
    "NO_POOL_STATE_MESSAGE",
    "NO_TICKS_MESSAGE",
    "OHLC_WINDOW_KEY",
    "OHLC_WINDOWS",
    "OHLC_DEFAULT_WINDOW",
    "SECTION_HEADING",
    "render_tick_views",
]

SECTION_HEADING = "**Tick-level views**"
OHLC_WINDOW_KEY = "coin_dashboard_ohlc_window"
OHLC_WINDOWS: tuple[int, ...] = (5, 10, 20, 50)
OHLC_DEFAULT_WINDOW = 10

NO_TICKS_MESSAGE = "This run recorded no ticks, so there are no tick-level views."
NO_POOL_STATE_MESSAGE = "No pool state is recorded for this run."
NO_EVENT_STATE_MESSAGE = (
    "This run had no news events, so no event state was recorded per tick. Turn on 'Scheduled news' "
    "or 'Random news' in the sidebar's Run setup to record it."
)

#: Volume components in stacking order: (column, label). Whale and
#: background exist only where the tick series records them.
_VOLUME_COMPONENTS = (
    ("organic_volume", "Organic"),
    ("manipulator_volume", "Manipulator"),
    ("wash_volume", "Wash"),
    ("whale_volume", "Whale"),
    ("background_volume", "Background"),
)


def render_tick_views(tick_series: dict[str, Any] | None, *, symbol: str, heading: bool = True) -> None:
    """Render the tick-level views from a serialized ``TickSeries``, or the
    unavailable message when the run has none.

    ``heading`` (Phase 24, Step 5) draws the section's own heading; the
    Simulate workspace passes ``False``, since its tab already names the section.
    """
    if heading:
        st.markdown(SECTION_HEADING)
    if tick_series is None:
        st.info(TICK_SERIES_UNAVAILABLE_MESSAGE)
        return
    data = tick_series["data"]
    if not tick_series["rows"]:
        st.info(NO_TICKS_MESSAGE)
        return
    ticks = data["tick"]
    _ohlc(ticks, data["price"], symbol)
    _volume(ticks, data, symbol)
    _pool(ticks, data, symbol)
    _events(ticks, data)


def _ohlc(ticks: Sequence[int], prices: Sequence[float], symbol: str) -> None:
    window = st.selectbox(
        "Synthetic OHLC window (recorded ticks)",
        OHLC_WINDOWS,
        index=OHLC_WINDOWS.index(OHLC_DEFAULT_WINDOW),
        key=OHLC_WINDOW_KEY,
    )
    windows = synthetic_ohlc(ticks, prices, int(window))
    st.plotly_chart(
        synthetic_ohlc_chart(windows, title=f"{symbol} synthetic OHLC, {window}-tick windows"),
        width="stretch", theme=None,
    )
    partial = " The last window is partial." if windows[-1].partial else ""
    st.caption(
        f"{SYNTHETIC_OHLC_DISCLOSURE} Each candle summarizes {window} consecutive recorded ticks: "
        f"open is the first recorded price, high the highest, low the lowest and close the last. "
        f"The simulator records one price per tick, so these are not exchange candles.{partial}"
    )


def _volume(ticks: Sequence[int], data: dict[str, Any], symbol: str) -> None:
    components = [
        (label, data[column])
        for column, label in _VOLUME_COMPONENTS
        if all(value is not None for value in data[column])
    ]
    st.plotly_chart(
        volume_composition_chart(
            ticks, components, title=f"Recorded volume per tick by component ({symbol})", unit=symbol
        ),
        width="stretch", theme=None,
    )
    shown = ", ".join(label.lower() for label, _ in components)
    st.caption(
        f"The recorded volume of each tick, split into {shown}. Every recorded quantity is in exactly "
        "one component, so the stacks add up to the tick's recorded volume. Whale volume appears only "
        "for runs with whales, and background (synthetic) volume only in random-walk mode."
    )


def _pool(ticks: Sequence[int], data: dict[str, Any], symbol: str) -> None:
    st.markdown("*Recorded pool state*")
    if data["pool_coin_reserve"][0] is None:
        st.info(NO_POOL_STATE_MESSAGE)
        return
    reserves = pd.DataFrame({
        "tick": ticks,
        f"Coin reserve ({symbol})": data["pool_coin_reserve"],
        "Cash reserve (cash)": data["pool_cash_reserve"],
    })
    st.plotly_chart(
        component_lines_chart(reserves, series=reserves.columns[1:].tolist(),
                              title="Pool reserves after each tick", value_title="Reserve"),
        width="stretch", theme=None,
    )
    invariant = pd.DataFrame({"tick": ticks, "Invariant (coin x cash)": data["pool_invariant"]})
    st.plotly_chart(
        component_lines_chart(invariant, series=["Invariant (coin x cash)"],
                              title="Pool invariant after each tick", value_title="Coin x cash"),
        width="stretch", theme=None,
    )
    fees = pd.DataFrame({
        "tick": ticks,
        f"Fees collected ({symbol})": data["pool_fees_collected_coins"],
        "Fees collected (cash)": data["pool_fees_collected_cash"],
    })
    st.plotly_chart(
        component_lines_chart(fees, series=fees.columns[1:].tolist(),
                              title="Cumulative pool fees", value_title="Fees collected"),
        width="stretch", theme=None,
    )
    swaps = pd.DataFrame({"tick": ticks, "Swaps (cumulative)": data["pool_swap_count"]})
    st.plotly_chart(
        component_lines_chart(swaps, series=["Swaps (cumulative)"],
                              title="Cumulative pool swap count", value_title="Swaps"),
        width="stretch", theme=None,
    )
    st.caption(
        "The pool snapshot recorded after each tick: reserves, their product, and the cumulative fee "
        "and swap counters. The pool's spot price is the recorded price in the market section's chart."
    )


def _events(ticks: Sequence[int], data: dict[str, Any]) -> None:
    st.markdown("*Recorded event state*")
    if data["event_sentiment"][0] is None:
        st.info(NO_EVENT_STATE_MESSAGE)
        return
    frame = pd.DataFrame({
        "tick": ticks,
        "Sentiment": data["event_sentiment"],
        "Volatility multiplier": data["event_volatility_multiplier"],
        "Attention multiplier": data["event_attention_multiplier"],
        "Live events": [len(live) for live in data["event_live"]],
    })
    st.plotly_chart(
        component_lines_chart(frame, series=frame.columns[1:].tolist(),
                              title="Recorded event state per tick", value_title="Value"),
        width="stretch", theme=None,
    )
    st.caption(
        "The event state the simulator recorded on each tick: combined sentiment, the volatility and "
        "attention multipliers (1.0 is neutral) and how many events were live. This is recorded state "
        "shown on the tick axis; it is not an account of price movement."
    )
