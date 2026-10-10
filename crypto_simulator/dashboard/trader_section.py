"""The trader section of the dashboard (Phase 10, Step 3).

Display only. The section receives the serialized ``report.traders`` —
``analyze_traders``' own ``TraderReport``, with its ``TraderSummary`` and
``StrategySummary`` members — and lays it out. It computes no figure: no
P&L, equity, return, VWAP, volume, notional, fee, net flow, fill count,
fill ratio or participation rate is derived here, nothing is re-summed
per strategy, and no trader is ranked or classified by behavior. Every
number on screen is a value the report holds, passed through a format spec
from ``dashboard.formatting``.

**Layout** (one payload, read once):

    overview     the report's own totals for the population
    strategies   one row per recorded strategy, as the report groups them
    activity     one row per trader: fills, quantities, participation
    performance  one row per trader: notional, fees, flows, equity, P&L
    detail       every recorded figure for one selected trader

**The selector filters, it does not compute.** Choosing a trader picks a
row that is already in the payload. It runs no simulation and no
analytics: the Step 1 state machine only runs a simulation when the Run
button asked for one, so changing the selection just re-renders the stored
payload.

**P&L, equity and VWAP are the analytics'.** ``analyze_traders`` defines
P&L as end equity minus start equity at its own valuation prices and VWAP
as notional over volume; both arrive computed and are only formatted here.
A trader with no fills has no VWAP, and a run with no wallet balances has
no P&L — those render as ``n/a``, never as zero.

**Wash figures are the recorded classification.** A fill counts as a wash
leg because the simulator flagged it, and a strategy is a manipulation
strategy because that is its registered label — never because of how the
numbers look.

**Modes.** One section serves both. AMM-only figures (swap fees, the exact
``Decimal`` flows) are ``None`` in random-walk mode and say so rather than
showing zero.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.formatting import (
    NOTIONAL_SPEC,
    RATIO_SPEC,
    SIGNED_NOTIONAL_SPEC,
    SIGNED_VOLUME_SPEC,
    VOLUME_SPEC,
    count,
    flag,
    number,
    percent,
    text,
    tick,
    tick_range,
)
from crypto_simulator.dashboard.metric_row import render_metric_row

__all__ = [
    "ALL_TRADERS",
    "DETAIL_COLUMNS",
    "NO_TRADERS_MESSAGE",
    "TRADER_SELECT_KEY",
    "render_traders",
]

NO_TRADERS_MESSAGE = "No trader activity was recorded for this run."
NO_FEES_MESSAGE = "n/a (random-walk mode has no swap fees)"
NO_PNL_MESSAGE = "P&L needs the traders' wallet balances; this report has none."
SELECT_HINT = "Pick a trader to see every figure the report records for them."
ALL_TRADERS = "All traders"
UNLABELLED_STRATEGY = "(balances only)"
MANIPULATION_MARK = " *"
MANIPULATION_NOTE = "* registered manipulation strategy (the recorded label, not a judgement of behavior)"

TRADER_SELECT_KEY = "coin_dashboard_trader"
DETAIL_COLUMNS = ("Metric", "Value")

# --- value kinds ------------------------------------------------------------------------------------------
# Each analytics field is shown with the spec its kind implies, matching
# ``analytics.rendering`` so the dashboard and the CLI report agree.

TEXT, FLAG, COUNT, TICK = "text", "flag", "count", "tick"
PRICE, VOLUME, NOTIONAL = "price", "volume", "notional"
SIGNED_VOLUME, SIGNED_NOTIONAL = "signed_volume", "signed_notional"
RATIO, RETURN = "ratio", "return"

_FORMATTERS: dict[str, Callable[[Any], str]] = {
    TEXT: text,
    FLAG: flag,
    COUNT: count,
    TICK: tick,
    PRICE: number,
    VOLUME: lambda value: number(value, VOLUME_SPEC),
    NOTIONAL: lambda value: number(value, NOTIONAL_SPEC),
    SIGNED_VOLUME: lambda value: number(value, SIGNED_VOLUME_SPEC),
    SIGNED_NOTIONAL: lambda value: number(value, SIGNED_NOTIONAL_SPEC),
    RATIO: lambda value: percent(value, RATIO_SPEC),
    RETURN: percent,
}

#: Every field a ``TraderSummary`` carries, in the order the detail view
#: lists them: the analytics' own record of one trader, nothing added.
DETAIL_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Trader", "trader_id", TEXT),
    ("Strategy", "strategy", TEXT),
    ("Manipulation strategy", "is_manipulator", FLAG),
    ("Active", "active", FLAG),
    ("Records", "records", COUNT),
    ("Fills", "fill_count", COUNT),
    ("Buy fills", "buy_count", COUNT),
    ("Sell fills", "sell_count", COUNT),
    ("Wash legs", "wash_leg_count", COUNT),
    ("Buy volume", "buy_volume", VOLUME),
    ("Sell volume", "sell_volume", VOLUME),
    ("Wash volume", "wash_volume", VOLUME),
    ("Total volume", "total_volume", VOLUME),
    ("Buy notional", "buy_notional", NOTIONAL),
    ("Sell notional", "sell_notional", NOTIONAL),
    ("Wash notional", "wash_notional", NOTIONAL),
    ("Total notional", "total_notional", NOTIONAL),
    ("VWAP", "vwap", PRICE),
    ("Wash share of volume", "wash_share", RATIO),
    ("Net coin flow", "net_coin_flow", SIGNED_VOLUME),
    ("Net cash flow", "net_cash_flow", SIGNED_NOTIONAL),
    ("Requested volume", "requested_volume", VOLUME),
    ("Fill ratio", "fill_ratio", RATIO),
    ("Active ticks", "active_ticks", COUNT),
    ("First fill tick", "first_fill_tick", TICK),
    ("Last fill tick", "last_fill_tick", TICK),
    ("Average fill size", "average_fill_size", VOLUME),
    ("Fees paid (cash)", "fees_paid_cash", NOTIONAL),
    ("Fees paid (coins)", "fees_paid_coins", PRICE),
    ("Exact cash flow (AMM)", "exact_cash_flow", SIGNED_NOTIONAL),
    ("Exact coin flow (AMM)", "exact_coin_flow", SIGNED_VOLUME),
    ("Start cash", "start_cash", NOTIONAL),
    ("Start coins", "start_coins", VOLUME),
    ("End cash", "end_cash", NOTIONAL),
    ("End coins", "end_coins", VOLUME),
    ("Start equity", "start_equity", NOTIONAL),
    ("End equity", "end_equity", NOTIONAL),
    ("P&L", "pnl", SIGNED_NOTIONAL),
    ("Return", "equity_return", RETURN),
)


def _field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column showing one analytics field, formatted for its kind."""
    return lambda summary: _FORMATTERS[kind](summary[name])


def _strategy_label(summary: dict[str, Any]) -> str:
    """The recorded strategy label, marked when it is a registered
    manipulation strategy. Traders the analytics know only from balances
    have no recorded strategy."""
    label = summary["strategy"] or UNLABELLED_STRATEGY
    marked = summary.get("is_manipulation_strategy", summary.get("is_manipulator"))
    return f"{label}{MANIPULATION_MARK}" if marked else label


def _fill_span(summary: dict[str, Any]) -> str:
    return tick_range(summary["first_fill_tick"], summary["last_fill_tick"])


def _traders_in_group(summary: dict[str, Any]) -> str:
    return f"{summary['active_trader_count']} of {summary['trader_count']}"


#: Per-strategy columns: the report's own group figures, never re-summed.
STRATEGY_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Strategy", _strategy_label),
    ("Traders active", _traders_in_group),
    ("Participation", _field("participation", RATIO)),
    ("Fills", _field("fill_count", COUNT)),
    ("Volume", _field("total_volume", VOLUME)),
    ("Notional", _field("total_notional", NOTIONAL)),
    ("VWAP", _field("vwap", PRICE)),
    ("Buy volume", _field("buy_volume", VOLUME)),
    ("Sell volume", _field("sell_volume", VOLUME)),
    ("Wash volume", _field("wash_volume", VOLUME)),
    ("Net coins", _field("net_coin_flow", SIGNED_VOLUME)),
    ("Fill ratio", _field("fill_ratio", RATIO)),
    ("P&L", _field("pnl", SIGNED_NOTIONAL)),
)

#: Per-trader activity columns.
ACTIVITY_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Trader", _field("trader_id", TEXT)),
    ("Strategy", _strategy_label),
    ("Active", _field("active", FLAG)),
    ("Fills", _field("fill_count", COUNT)),
    ("Buy qty", _field("buy_volume", VOLUME)),
    ("Sell qty", _field("sell_volume", VOLUME)),
    ("Wash qty", _field("wash_volume", VOLUME)),
    ("Volume", _field("total_volume", VOLUME)),
    ("Requested", _field("requested_volume", VOLUME)),
    ("Fill ratio", _field("fill_ratio", RATIO)),
    ("Active ticks", _field("active_ticks", COUNT)),
    ("Fill ticks", _fill_span),
    ("Average fill", _field("average_fill_size", VOLUME)),
)

#: Per-trader performance columns.
PERFORMANCE_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Trader", _field("trader_id", TEXT)),
    ("Notional", _field("total_notional", NOTIONAL)),
    ("VWAP", _field("vwap", PRICE)),
    ("Wash share", _field("wash_share", RATIO)),
    ("Fees (cash)", _field("fees_paid_cash", NOTIONAL)),
    ("Fees (coins)", _field("fees_paid_coins", PRICE)),
    ("Net coins", _field("net_coin_flow", SIGNED_VOLUME)),
    ("Net cash", _field("net_cash_flow", SIGNED_NOTIONAL)),
    ("End cash", _field("end_cash", NOTIONAL)),
    ("End coins", _field("end_coins", VOLUME)),
    ("End equity", _field("end_equity", NOTIONAL)),
    ("P&L", _field("pnl", SIGNED_NOTIONAL)),
    ("Return", _field("equity_return", RETURN)),
)


def render_traders(traders: dict[str, Any], *, symbol: str, heading: bool = True) -> None:
    """Render the trader section from the serialized ``report.traders``.

    ``heading`` (Phase 24, Step 5) draws the section's own heading; the
    Simulate workspace passes ``False``, since its tab already names the section.
    """
    if heading:
        st.markdown("**Traders**")
    if not traders["population"]:
        st.info(NO_TRADERS_MESSAGE)
        return

    _overview(traders, symbol)
    _strategies(traders["strategies"])
    _per_trader(traders["traders"])
    _detail(traders["traders"])


# --- sections --------------------------------------------------------------------------------------------


def _overview(traders: dict[str, Any], symbol: str) -> None:
    render_metric_row([
        ("Traders active", f"{traders['active_traders']} of {traders['population']}"),
        ("Participation", percent(traders["participation_rate"], ".0%")),
        ("Trader fills", count(traders["fill_count"])),
        ("Trader volume", number(traders["total_volume"], VOLUME_SPEC)),
    ])

    render_metric_row([
        ("Trader notional", number(traders["total_notional"], NOTIONAL_SPEC)),
        ("VWAP (all fills)", number(traders["vwap"])),
        ("Net coin flow", number(traders["net_coin_flow"], SIGNED_VOLUME_SPEC)),
        ("Net cash flow", number(traders["net_cash_flow"], SIGNED_NOTIONAL_SPEC)),
    ])

    render_metric_row([
        ("Combined P&L", number(traders["pnl"], SIGNED_NOTIONAL_SPEC)),
        ("Combined return", percent(traders["equity_return"])),
        ("Start equity", number(traders["start_equity"], NOTIONAL_SPEC)),
        ("End equity", number(traders["end_equity"], NOTIONAL_SPEC)),
    ])

    st.caption(
        f"buy / sell / wash volume {number(traders['buy_volume'], VOLUME_SPEC)} / "
        f"{number(traders['sell_volume'], VOLUME_SPEC)} / "
        f"{number(traders['wash_volume'], VOLUME_SPEC)} {symbol} · "
        f"filled {number(traders['filled_volume'], VOLUME_SPEC)} of requested "
        f"{number(traders['requested_volume'], VOLUME_SPEC)} "
        f"(ratio {percent(traders['fill_ratio'], RATIO_SPEC)})"
    )
    st.caption(
        f"fees paid {_fees(traders)} · final price {number(traders['final_price'])} · "
        f"ticks {count(traders['ticks'])} · pricing mode {text(traders['pricing_mode'])}"
    )
    if traders["pnl"] is None:
        st.caption(NO_PNL_MESSAGE)


def _fees(figures: dict[str, Any]) -> str:
    """Swap fees, which only AMM runs have. Cash and coin fees are charged
    in different assets, so the report keeps them apart and so does this."""
    if figures["fees_paid_cash"] is None and figures["fees_paid_coins"] is None:
        return NO_FEES_MESSAGE
    return (f"{number(figures['fees_paid_cash'], NOTIONAL_SPEC)} cash + "
            f"{number(figures['fees_paid_coins'])} coins")


def _strategies(strategies: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Strategies**")
    if not strategies:
        st.caption("The report groups no strategies for this run.")
        return
    _table(STRATEGY_COLUMNS, strategies)
    notes = [
        "Each row is the report's own group of traders by recorded strategy label; "
        f"{UNLABELLED_STRATEGY} are traders the analytics know only from their balances.",
        "The analytics define no strategy-level return, so none is shown.",
    ]
    if any(row["is_manipulation_strategy"] for row in strategies):
        notes.insert(0, MANIPULATION_NOTE)
    for note in notes:
        st.caption(note)


def _per_trader(traders: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Trader activity**")
    if not traders:
        st.caption("The report records no individual traders for this run.")
        return
    _table(ACTIVITY_COLUMNS, traders)
    st.caption(
        "One row per trader, ordered by trader id as the report orders them. Buy and sell "
        "quantities exclude wash legs, which are counted on their own; a fill ratio needs a "
        "recorded requested quantity."
    )

    st.markdown("**Trader performance**")
    _table(PERFORMANCE_COLUMNS, traders)
    st.caption(
        "Equity, P&L and return are the analytics' own: equity is valued at the report's prices "
        "and P&L is end equity minus start equity, computed by analyze_traders and shown "
        "unchanged. Swap fees are informational — they are already inside the notional."
    )


def _detail(traders: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Trader detail**")
    identifiers = [summary["trader_id"] for summary in traders]
    selected = st.selectbox("Trader", (ALL_TRADERS, *identifiers), key=TRADER_SELECT_KEY)
    if selected == ALL_TRADERS:
        st.caption(SELECT_HINT)
        return
    summary = next((row for row in traders if row["trader_id"] == selected), None)
    if summary is None:  # the payload changed under a stale selection
        st.caption(SELECT_HINT)
        return
    rows = [
        {DETAIL_COLUMNS[0]: label, DETAIL_COLUMNS[1]: _FORMATTERS[kind](summary[field])}
        for label, field, kind in DETAIL_ROWS
    ]
    st.table(pd.DataFrame(rows).set_index(DETAIL_COLUMNS[0]))
    st.caption(
        "Every figure analyze_traders records for this trader. Selecting a trader filters the "
        "payload already on screen: it runs no simulation and no analytics."
    )


def _table(
    columns: Sequence[tuple[str, Callable[[dict[str, Any]], str]]],
    rows: Sequence[dict[str, Any]],
) -> None:
    """One row per summary, in the report's order, every cell formatted."""
    frame = pd.DataFrame(
        [{header: render(row) for header, render in columns} for row in rows]
    )
    st.dataframe(frame, hide_index=True, width="stretch")
