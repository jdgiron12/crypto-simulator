"""The market section of the dashboard (Phase 10, Step 2).

Everything here is display. The section receives the serialized
``report.market`` — ``analyze_market``'s own ``MarketSummary`` — plus the
run's recorded price series, and lays them out. It computes no figure: no
return, volatility, drawdown, turnover, VWAP, market cap or volume
component is derived here, and no value is combined with another. Each
number on screen is a value the report holds, passed through a format
spec from ``dashboard.formatting``.

**Layout** (one payload, read once):

    headline        close, return, total volume, ticks analysed
    price           open / high / low, and the price chart
    volume          the analytics' own VolumeBreakdown, fills included
    volatility      volatility and drawdown as the report states them
    valuation       market cap, turnover, trade size, VWAP
    pool            AMM swap activity, or why there is none
    statistics      the compact table of every market figure shown

``render_market`` draws all of it in that order. The Simulate workspace
(Phase 24, Step 4) draws the same parts in two places instead:
``render_market_overview`` (the heading, the headline figures and the
price chart) above the run's detail tabs, and ``render_market_details``
(the price figures and everything after them) in the Market details tab.
Together they draw exactly what ``render_market`` draws.

**Missing stays missing.** ``None`` renders as ``n/a`` and never as zero.
Figures the analytics do not define for a mode keep that meaning:
background volume is ``n/a (AMM mode)`` because AMM runs have no synthetic
volume, pool activity is absent in random-walk mode because there are no
swaps, and turnover needs a total supply. Both pricing modes use this one
section — there is no mode-specific dashboard.

**Not derived here.** The report defines no absolute price change, so the
headline shows the return it does define rather than subtracting one price
from another. The report defines drawdown as scalars (maximum, its peak
and trough ticks, recovery, and the drawdown at close) and not as a
series, so there is no drawdown chart: building one would mean
reimplementing the analytics' drawdown formula in the frontend. The
chart's markers are the report's own high and low.
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.formatting import (
    RATIO_SPEC,
    UNAVAILABLE,
    VOLUME_SPEC,
    count,
    number,
    percent,
    text,
    tick,
    tick_range,
)
from crypto_simulator.visualization.charts import price_path_chart

__all__ = [
    "NO_TICKS_MESSAGE",
    "STATISTICS_COLUMNS",
    "render_market",
    "render_market_details",
    "render_market_overview",
]

NO_TICKS_MESSAGE = "No ticks were analysed for this run, so there are no market figures to show."
NO_POOL_MESSAGE = "n/a — random-walk mode records no swaps."
STATISTICS_COLUMNS = ("Metric", "Value")

#: The volume breakdown rows: label, payload key, and whether the figure
#: is a coin volume (the rest are fill counts).
_VOLUME_ROWS: tuple[tuple[str, str, bool], ...] = (
    ("Total volume", "total_volume", True),
    ("Background (synthetic)", "background_volume", True),
    ("Whale", "whale_volume", True),
    ("Organic traders", "organic_volume", True),
    ("Manipulators", "manipulator_volume", True),
    ("Wash legs", "wash_volume", True),
    ("Participants (whale + organic + manipulator)", "participant_volume", True),
    ("Whale fills", "whale_fills", False),
    ("Zero-quantity whale trades", "zero_quantity_whale_trades", False),
    ("Organic fills", "organic_fills", False),
    ("Manipulator fills", "manipulator_fills", False),
    ("Wash legs recorded", "wash_legs", False),
    ("Fills in total", "fills", False),
)


def render_market(
    market: dict[str, Any],
    *,
    symbol: str,
    price_series: Sequence[dict[str, Any]],
    scope: tuple[Any, Any] = (None, None),
) -> None:
    """Render the market section for one run.

    ``market`` is the serialized ``report.market``; ``price_series`` the
    payload's recorded ticks; ``scope`` the report's requested
    ``(start_tick, end_tick)``, shown when the run was analysed over a
    window rather than in full.
    """
    st.markdown("**Market summary**")
    if not market["ticks"]:
        st.info(NO_TICKS_MESSAGE)
        return

    _headline(market, symbol)
    _price(market, symbol, price_series)
    _volume(market["volume_breakdown"], symbol)
    _volatility_and_drawdown(market)
    _valuation(market)
    _pool(market["pool_activity"])
    _statistics(market, scope)


def render_market_overview(
    market: dict[str, Any], *, symbol: str, price_series: Sequence[dict[str, Any]]
) -> None:
    """The top of the market section: its heading, the headline figures and
    the price chart — the parts a run is read by first."""
    st.markdown("**Market summary**")
    if not market["ticks"]:
        st.info(NO_TICKS_MESSAGE)
        return
    _headline(market, symbol)
    _chart(market, symbol, price_series)


def render_market_details(
    market: dict[str, Any], *, symbol: str, scope: tuple[Any, Any] = (None, None)
) -> None:
    """The rest of the market section: the price figures, volume,
    volatility and drawdown, valuation, pool activity and the statistics
    table. Draws nothing for a run with no analysed ticks, whose overview
    already says so."""
    if not market["ticks"]:
        return
    _price_figures(market)
    _volume(market["volume_breakdown"], symbol)
    _volatility_and_drawdown(market)
    _valuation(market)
    _pool(market["pool_activity"])
    _statistics(market, scope)


# --- sections --------------------------------------------------------------------------------------------


def _headline(market: dict[str, Any], symbol: str) -> None:
    """The four figures Step 1 showed, unchanged. The close carries the
    report's return as its delta — the report defines no absolute change,
    so none is invented."""
    columns = st.columns(4)
    columns[0].metric("Close price", number(market["close_price"]), delta=percent(market["cumulative_return"]))
    columns[1].metric("Return", percent(market["cumulative_return"]))
    columns[2].metric("Total volume", number(market["volume_breakdown"]["total_volume"], VOLUME_SPEC))
    columns[3].metric("Ticks analysed", str(market["ticks"]))
    st.caption(
        f"open {number(market['open_price'])} · "
        f"high {number(market['high_price'])} · low {number(market['low_price'])} · "
        f"tick range {tick_range(market['first_tick'], market['last_tick'])} · "
        f"volatility {number(market['volatility'])} per tick"
    )
    st.caption(f"Figures are the report's own values for {symbol}; 'n/a' means not computable.")


def _price(market: dict[str, Any], symbol: str, price_series: Sequence[dict[str, Any]]) -> None:
    _price_figures(market)
    _chart(market, symbol, price_series)


def _price_figures(market: dict[str, Any]) -> None:
    st.markdown("**Price**")
    columns = st.columns(4)
    columns[0].metric("Open price", number(market["open_price"]))
    columns[1].metric("High", number(market["high_price"]))
    columns[2].metric("Low", number(market["low_price"]))
    columns[3].metric("Mean price", number(market["mean_price"]))
    st.caption(
        f"high at tick {tick(market['high_tick'])} · low at tick {tick(market['low_tick'])} · "
        f"log return {number(market['log_return'], '+.4f')} · "
        f"the open is the pre-run price at tick 0 when tick 1 is analysed, which the chart's "
        f"recorded ticks do not include"
    )


def _chart(market: dict[str, Any], symbol: str, price_series: Sequence[dict[str, Any]]) -> None:
    if not price_series:
        st.info("This run recorded no ticks to chart.")
        return
    frame = pd.DataFrame(price_series)
    st.plotly_chart(
        price_path_chart(
            frame,
            title=f"{symbol} price path (simulated)",
            markers=_markers(market, frame),
        ),
        width="stretch", theme=None,
    )
    st.caption(
        "The recorded price of every analysed tick, in tick order. Hover for a tick's price and "
        "volume; markers are the report's high and low."
    )


def _markers(market: dict[str, Any], frame: pd.DataFrame) -> tuple[tuple[str, float, float], ...]:
    """The report's high and low as chart annotations.

    Both the tick and the price come from the report. A point whose tick
    is not one of the recorded ticks — the pre-run point at tick 0, which
    ``analyze_market`` includes in the path — is left off rather than
    moved onto a tick it did not happen at.
    """
    ticks = set(frame["tick"])
    points = (("High", market["high_tick"], market["high_price"]),
              ("Low", market["low_tick"], market["low_price"]))
    return tuple(
        (label, point, price)
        for label, point, price in points
        if point is not None and price is not None and point in ticks
    )


def _volume(volume: dict[str, Any], symbol: str) -> None:
    st.markdown("**Volume**")
    rows = [
        {
            STATISTICS_COLUMNS[0]: label,
            STATISTICS_COLUMNS[1]: _volume_value(volume, key, is_volume),
        }
        for label, key, is_volume in _VOLUME_ROWS
    ]
    st.table(pd.DataFrame(rows).set_index(STATISTICS_COLUMNS[0]))
    st.caption(
        f"Volumes are in {symbol}, decomposed by the report: total = background + whale + organic + "
        "manipulator + wash. Background volume is synthetic and is n/a in AMM mode, where every "
        "recorded coin came from a swap."
    )


def _volume_value(volume: dict[str, Any], key: str, is_volume: bool) -> str:
    value = volume[key]
    if key == "background_volume" and value is None:
        return f"{UNAVAILABLE} (AMM mode)"
    return number(value, VOLUME_SPEC) if is_volume else count(value)


def _volatility_and_drawdown(market: dict[str, Any]) -> None:
    st.markdown("**Volatility and drawdown**")
    columns = st.columns(4)
    columns[0].metric("Volatility (per tick)", number(market["volatility"]))
    columns[1].metric("Realized volatility", number(market["realized_volatility"]))
    columns[2].metric("Max drawdown", percent(market["max_drawdown"], RATIO_SPEC))
    columns[3].metric("Drawdown at close", percent(market["end_drawdown"], RATIO_SPEC))
    st.caption(
        f"volatility is the sample standard deviation of {count(market['return_count'])} log returns, "
        f"not annualized (a tick is simulated time) · mean return "
        f"{number(market['mean_return'], '+.4f')}"
    )
    st.caption(
        f"drawdown peak tick {tick(market['drawdown_peak_tick'])} · "
        f"trough tick {tick(market['drawdown_trough_tick'])} · "
        f"{_recovery(market)} · missing ticks {count(market['missing_tick_count'])}"
    )


def _recovery(market: dict[str, Any]) -> str:
    if market["drawdown_peak_tick"] is None:
        return "no drawdown recorded"
    if market["recovery_tick"] is None:
        return "not recovered"
    return f"recovered at tick {market['recovery_tick']}"


def _valuation(market: dict[str, Any]) -> None:
    st.markdown("**Market cap and turnover**")
    columns = st.columns(4)
    columns[0].metric("Market cap (open)", number(market["market_cap_start"], VOLUME_SPEC))
    columns[1].metric("Market cap (close)", number(market["market_cap_end"], VOLUME_SPEC))
    columns[2].metric("Turnover", percent(market["turnover"], RATIO_SPEC))
    columns[3].metric("Participant turnover", percent(market["participant_turnover"], RATIO_SPEC))
    st.caption(
        f"average trade size {number(market['average_trade_size'], VOLUME_SPEC)} · "
        f"trader VWAP {number(market['trader_vwap'])} · "
        "market cap and turnover need the run's total supply, and are n/a without it"
    )


def _pool(pool: dict[str, Any] | None) -> None:
    st.markdown("**AMM pool activity**")
    if pool is None:
        st.caption(NO_POOL_MESSAGE)
        return
    columns = st.columns(4)
    columns[0].metric("Swaps", count(pool["swap_count"]))
    columns[1].metric("Fees (cash)", number(pool["fees_cash"]))
    columns[2].metric("Fees (coins)", number(pool["fees_coins"]))
    columns[3].metric("Largest price impact", percent(pool["max_abs_price_impact"], RATIO_SPEC))
    st.caption(
        "Swap counts and fees are the pool's own, recorded per swap; fees are charged in the input "
        "asset, so cash and coins are reported apart and never added together."
    )


def _statistics(market: dict[str, Any], scope: tuple[Any, Any]) -> None:
    st.markdown("**Market statistics**")
    st.table(pd.DataFrame(_statistics_rows(market, scope)).set_index(STATISTICS_COLUMNS[0]))
    st.caption(
        "Every figure above is a field of the run's SimulationReport (analytics.analyze_market); "
        "the dashboard formats them and computes none of them."
    )


def _statistics_rows(market: dict[str, Any], scope: tuple[Any, Any]) -> list[dict[str, str]]:
    metric, value = STATISTICS_COLUMNS
    rows = [
        ("Pricing mode", text(market["pricing_mode"])),
        ("Ticks analysed", count(market["ticks"])),
        ("Tick range", tick_range(market["first_tick"], market["last_tick"])),
        ("Requested range", tick_range(*scope) if any(end is not None for end in scope) else "full run"),
        ("Missing ticks", count(market["missing_tick_count"])),
        ("Open", number(market["open_price"])),
        ("Close", number(market["close_price"])),
        ("Return", percent(market["cumulative_return"])),
        ("Log return", number(market["log_return"], "+.4f")),
        ("High", f"{number(market['high_price'])} at tick {tick(market['high_tick'])}"),
        ("Low", f"{number(market['low_price'])} at tick {tick(market['low_tick'])}"),
        ("Mean price", number(market["mean_price"])),
        ("Returns observed", count(market["return_count"])),
        ("Mean return", number(market["mean_return"], "+.4f")),
        ("Volatility (per tick)", number(market["volatility"])),
        ("Realized volatility", number(market["realized_volatility"])),
        ("Max drawdown", percent(market["max_drawdown"], RATIO_SPEC)),
        ("Drawdown at close", percent(market["end_drawdown"], RATIO_SPEC)),
        ("Total volume", number(market["volume_breakdown"]["total_volume"], VOLUME_SPEC)),
        ("Participant volume", number(market["volume_breakdown"]["participant_volume"], VOLUME_SPEC)),
        ("Market cap (open)", number(market["market_cap_start"], VOLUME_SPEC)),
        ("Market cap (close)", number(market["market_cap_end"], VOLUME_SPEC)),
        ("Turnover", percent(market["turnover"], RATIO_SPEC)),
        ("Participant turnover", percent(market["participant_turnover"], RATIO_SPEC)),
        ("Average trade size", number(market["average_trade_size"], VOLUME_SPEC)),
        ("Trader VWAP", number(market["trader_vwap"])),
    ]
    return [{metric: label, value: shown} for label, shown in rows]
