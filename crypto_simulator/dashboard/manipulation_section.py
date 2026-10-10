"""The manipulation section of the dashboard (Phase 10, Step 6).

Display only. The section receives the serialized ``report.manipulation``
— ``analyze_manipulation``' own ``ManipulationReport``, which embeds
``analyze_market``' ``VolumeBreakdown`` for every top-level volume figure,
one ``PumpAndDumpSummary`` per recorded manipulator (each carrying its own
``MarketSummary``), one aggregate ``WashSummary``, the side-by-side
``ActivityComparison`` and ``analyze_traders``' ``StrategySummary`` for the
two manipulation strategies — and lays it out. It computes no figure: no
scenario count, volume, share, return, phase boundary, wash split,
coverage or fill total is derived here. Every number on screen is a value
the report holds, passed through a format spec from
``dashboard.formatting``.

**Layout** (one payload, read once):

    overview    the report's own manipulation volume, shares and timing
    scenarios   one row per manipulation kind, from its strategy summary
    phases      one row per manipulator and recorded phase
    windows     each manipulator's observed span and its market summary
    wash        the aggregate wash-trading record
    comparison  manipulation and organic activity side by side

**Recorded, never inferred.** A fill is manipulation exactly when the
simulator recorded it as one — a wash leg, or a registered manipulation
strategy. The section reclassifies nothing: a large trade, a fast price
move, a big trader or an unusual volume is never shown as manipulation,
and the phases are the ``accumulate``/``pump``/``dump`` fills the
analytics counted from each fill's own recorded reason, never
reconstructed from a price path here.

**Kinds stay apart.** Pump-and-dump and wash trading are reported
separately, exactly as the analytics report them; the section never merges
them into a single invented figure. ``coverage`` is the analytics' own
word for which *kinds* were observed (none / partial / complete) and is
shown as such — it is not a claim that any scenario's full extent fell
inside the analysed ticks, which the analytics say they cannot know.

**Descriptive, never causal.** Every figure describes what was recorded
during the ticks a scenario was active in. Nothing here says manipulation
moved a price, that a wash leg lifted the market, or that a price move
belongs to a scheme: the span figures are labelled as observed during the
scenario's own ticks, and a test reads back everything on screen to keep
the wording that way.

**Missing is missing.** A phase with no recorded fills has no ticks, shown
as ``n/a`` rather than tick zero; a run with no manipulation fills says so
instead of presenting zeros as an analysis; and a share the analytics
could not compute (a zero denominator) stays ``n/a``. Zero *is* reported
where the analytics define it as a fact: trader fills are always fully
recorded, so "no wash legs" is an observation, not a coverage gap.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.analytics.manipulation import COVERAGE_NONE, COVERAGE_PARTIAL
from crypto_simulator.dashboard.formatting import (
    NOTIONAL_SPEC,
    RATIO_SPEC,
    SIGNED_NOTIONAL_SPEC,
    SIGNED_VOLUME_SPEC,
    UNAVAILABLE,
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
from crypto_simulator.dashboard.notes import render_notes

__all__ = [
    "COMPARISON_ROWS",
    "NO_MANIPULATION_MESSAGE",
    "NO_SCENARIO_MESSAGE",
    "NO_WASH_MESSAGE",
    "PHASE_FIELDS",
    "SCENARIO_KINDS",
    "UNAVAILABLE_MESSAGE",
    "WASH_ROWS",
    "render_manipulation",
]

UNAVAILABLE_MESSAGE = (
    "This payload carries no manipulation report, so there are no manipulation analytics to show."
)
NO_SCENARIO_MESSAGE = (
    "This run was configured without a manipulation scenario, and the report records no "
    "manipulation fills. Pick a scenario in the run options to observe one."
)
NO_MANIPULATION_MESSAGE = (
    "The report records no manipulation fills for this run: no wash legs, and no fills by a "
    "registered manipulation strategy."
)
NO_WASH_MESSAGE = (
    "The report records no wash-trading legs for this run. Trader fills are always fully "
    "recorded, so this is an observation rather than a gap in the analytics."
)
NO_PUMP_AND_DUMP_MESSAGE = (
    "The report records no pump-and-dump fills for this run, so it summarises no manipulator "
    "phases."
)
PARTIAL_NOTE = (
    "Partial coverage: one of the two manipulation kinds was observed in the analysed ticks. "
    "The analytics do not read this as a scenario being half-finished — a kind with no fills may "
    "never have run, or may lie outside the analysed range, and they keep the two apart."
)
SPAN_NOTE = (
    "A manipulator's span runs from its earliest recorded fill to its latest, whichever phase "
    "each belongs to. The figures alongside are the market summary the analytics computed over "
    "those same ticks — what the market recorded during the span, reported next to it."
)

# --- value kinds ------------------------------------------------------------------------------------------

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

#: The two manipulation kinds the report keeps apart, each with the field
#: holding its ``StrategySummary``. The kind label names which field the
#: row reads; the strategy name itself comes from the report.
SCENARIO_KINDS: tuple[tuple[str, str], ...] = (
    ("pump-and-dump", "pump_and_dump_strategy"),
    ("wash trading", "wash_strategy"),
)

#: One row per manipulator and recorded phase: the phase's own fill count,
#: volume and first/last tick, exactly as ``PumpAndDumpSummary`` names
#: them. The phase names are the reasons the simulator recorded on the
#: fills themselves; nothing here decides which fill belongs to which.
PHASE_FIELDS: tuple[tuple[str, str, str, str, str], ...] = (
    ("accumulate", "accumulation_fills", "accumulation_volume",
     "first_accumulation_tick", "last_accumulation_tick"),
    ("pump", "pump_fills", "pump_volume", "pump_start_tick", "pump_end_tick"),
    ("dump", "dump_fills", "dump_volume", "dump_start_tick", "dump_end_tick"),
)

#: ``WashSummary``, as the wash table lists it.
WASH_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Wash legs", "fill_count", COUNT),
    ("Wash volume", "volume", VOLUME),
    ("Wash buy volume", "buy_volume", VOLUME),
    ("Wash sell volume", "sell_volume", VOLUME),
    ("Wash notional", "notional", NOTIONAL),
    ("Active ticks", "active_ticks", COUNT),
    ("First tick", "first_tick", TICK),
    ("Last tick", "last_tick", TICK),
    ("Average volume per active tick", "average_volume_per_active_tick", VOLUME),
)

#: ``ActivityComparison``: one row per figure, manipulation beside
#: organic, as the analytics pair them.
COMPARISON_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("Volume", "manipulation_volume", "organic_volume", VOLUME),
    ("Buy volume", "manipulation_buy_volume", "organic_buy_volume", VOLUME),
    ("Sell volume", "manipulation_sell_volume", "organic_sell_volume", VOLUME),
    ("Notional", "manipulation_notional", "organic_notional", NOTIONAL),
    ("Active ticks", "manipulation_active_ticks", "organic_active_ticks", COUNT),
    ("Average fill size", "manipulation_average_fill_size", "organic_average_fill_size", VOLUME),
)


def _field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    return lambda row: _FORMATTERS[kind](row[name])


def _market_field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column from the manipulator's own embedded ``MarketSummary``."""
    return lambda row: _FORMATTERS[kind](row["market"][name])


#: One row per manipulation kind, from that kind's ``StrategySummary``.
SCENARIO_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Kind", _field("kind", TEXT)),
    ("Strategy", _field("strategy", TEXT)),
    ("Recorded", _field("recorded", FLAG)),
    ("Registered manipulation strategy", _field("is_manipulation_strategy", FLAG)),
    ("Traders", _field("trader_count", COUNT)),
    ("Active traders", _field("active_trader_count", COUNT)),
    ("Participation", _field("participation", RATIO)),
    ("Fills", _field("fill_count", COUNT)),
    ("Buy volume", _field("buy_volume", VOLUME)),
    ("Sell volume", _field("sell_volume", VOLUME)),
    ("Wash volume", _field("wash_volume", VOLUME)),
    ("Total volume", _field("total_volume", VOLUME)),
    ("Notional", _field("total_notional", NOTIONAL)),
    ("VWAP", _field("vwap", PRICE)),
    ("Net coins", _field("net_coin_flow", SIGNED_VOLUME)),
    ("Net cash", _field("net_cash_flow", SIGNED_NOTIONAL)),
    ("Fill ratio", _field("fill_ratio", RATIO)),
    ("Average fill", _field("average_fill_size", VOLUME)),
    ("P&L", _field("pnl", SIGNED_NOTIONAL)),
)

#: One row per manipulator and phase.
PHASE_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Manipulator", _field("trader_id", TEXT)),
    ("Phase", _field("phase", TEXT)),
    ("Fills", _field("fills", COUNT)),
    ("Volume", _field("volume", VOLUME)),
    ("First tick", _field("first_tick", TICK)),
    ("Last tick", _field("last_tick", TICK)),
)

#: One row per manipulator: its recorded span, its totals, and the market
#: summary the analytics computed over that span.
SPAN_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Manipulator", _field("trader_id", TEXT)),
    ("Observed ticks", lambda row: tick_range(row["first_tick"], row["last_tick"])),
    ("Duration", _field("duration", COUNT)),
    ("Total fills", _field("total_fills", COUNT)),
    ("Total volume", _field("total_volume", VOLUME)),
    ("Price at accumulation start", _field("price_at_accumulation_start", PRICE)),
    ("Price at dump start", _field("price_at_dump_start", PRICE)),
    ("Ticks in span", _market_field("ticks", COUNT)),
    ("Open", _market_field("open_price", PRICE)),
    ("Close", _market_field("close_price", PRICE)),
    ("Return over span", _market_field("cumulative_return", RETURN)),
    ("High", _market_field("high_price", PRICE)),
    ("High tick", _market_field("high_tick", TICK)),
    ("Low", _market_field("low_price", PRICE)),
    ("Low tick", _market_field("low_tick", TICK)),
    ("Max drawdown", _market_field("max_drawdown", RATIO)),
    ("Drawdown peak tick", _market_field("drawdown_peak_tick", TICK)),
    ("Drawdown trough tick", _market_field("drawdown_trough_tick", TICK)),
    ("Recovery tick", _market_field("recovery_tick", TICK)),
)


def render_manipulation(
    manipulation: dict[str, Any] | None,
    *,
    symbol: str,
    simulation: dict[str, Any] | None = None,
    heading: bool = True,
) -> None:
    """Render the manipulation section from the serialized
    ``report.manipulation``.

    ``simulation`` is the payload's run metadata, used only to say why a
    run has no manipulation fills (no scenario was chosen).

    ``heading`` (Phase 24, Step 5) draws the section's own heading; the
    Simulate workspace passes ``False``, since its tab already names the section.
    """
    if heading:
        st.markdown("**Manipulation**")
    if manipulation is None:
        st.info(UNAVAILABLE_MESSAGE)
        return

    _coverage(manipulation)
    if manipulation["coverage"] == COVERAGE_NONE:
        st.info(_no_activity_message(simulation))
        return

    _overview(manipulation, symbol)
    _scenarios(manipulation)
    _pump_and_dump(manipulation["pump_and_dump"])
    _wash(manipulation["wash"])
    _comparison(manipulation["activity_comparison"])


# --- sections --------------------------------------------------------------------------------------------


def _coverage(manipulation: dict[str, Any]) -> None:
    st.caption(
        f"kinds observed {text(manipulation['coverage'])} · ticks analysed "
        f"{count(manipulation['ticks'])} · active ticks {count(manipulation['active_ticks'])} "
        f"· recorded ticks {tick_range(manipulation['first_tick'], manipulation['last_tick'])} · "
        f"pricing mode {text(manipulation['pricing_mode'])}"
    )
    render_notes(
        "'Kinds observed' is the analytics' own coverage word for which manipulation kinds "
        "(pump-and-dump, wash trading) had recorded fills. It is not a statement that a "
        "scenario's whole run fell inside the analysed ticks — the analytics say they cannot "
        "tell a phase that never ran from one outside the range, and neither does this section."
    )
    if manipulation["coverage"] == COVERAGE_PARTIAL:
        st.caption(PARTIAL_NOTE)


def _no_activity_message(simulation: dict[str, Any] | None) -> str:
    params = (simulation or {}).get("params") or {}
    if params.get("scenario") is None:
        return NO_SCENARIO_MESSAGE
    return NO_MANIPULATION_MESSAGE


def _overview(manipulation: dict[str, Any], symbol: str) -> None:
    render_metric_row([
        ("Manipulation volume", number(manipulation["manipulation_volume"], VOLUME_SPEC)),
        ("Manipulation share of total volume", percent(manipulation["manipulation_share_of_total"], RATIO_SPEC)),
        (
            "Manipulation share of participant volume",
            percent(manipulation["manipulation_share_of_participants"], RATIO_SPEC),
        ),
        ("Manipulation active ticks", count(manipulation["active_ticks"])),
    ])
    st.caption(
        f"pump-and-dump volume {number(manipulation['pump_and_dump_volume'], VOLUME_SPEC)} · "
        f"wash volume {number(manipulation['wash_volume'], VOLUME_SPEC)} · market volume "
        f"{number(manipulation['total_market_volume'], VOLUME_SPEC)} · participant volume "
        f"{number(manipulation['participant_volume'], VOLUME_SPEC)} {symbol}"
    )
    st.caption(
        f"manipulation fills {count(manipulation['fill_count'])} · buy volume "
        f"{number(manipulation['buy_volume'], VOLUME_SPEC)} · sell volume "
        f"{number(manipulation['sell_volume'], VOLUME_SPEC)} · manipulation notional "
        f"{number(manipulation['notional'], NOTIONAL_SPEC)}"
    )
    render_notes(
        "Both shares are the analytics' own, and their denominators differ on purpose: the share "
        "of total volume pairs manipulator and wash volume with the market total, while the share "
        "of participant volume pairs the non-wash manipulator volume with participant volume, "
        "which excludes the self-cancelling wash leg. Each figure above is the report's, and the "
        "notional is the one the report carries under that name."
    )


def _scenarios(manipulation: dict[str, Any]) -> None:
    st.markdown("**Manipulation kinds**")
    _table(SCENARIO_COLUMNS, [_scenario_row(manipulation, kind, field) for kind, field in SCENARIO_KINDS])
    st.caption(
        "One row per manipulation kind the analytics keep apart, read from that kind's own "
        "strategy summary. A kind with no recorded fills has no summary at all, so its row is "
        "n/a throughout rather than zero — the analytics attach no reason to that absence, and "
        "none is invented here."
    )
    render_notes(
        "P&L is n/a by design: the manipulation report is built from ticks alone and carries no "
        "wallet balances, so the analytics record none. The trader section shows P&L for a run "
        "whose balances were supplied."
    )


def _scenario_row(manipulation: dict[str, Any], kind: str, field: str) -> dict[str, Any]:
    """One kind's strategy summary, or an empty record when the report has
    none for it. Checking for that ``None`` is the only decision made."""
    summary = manipulation[field]
    if summary is None:
        return {"kind": kind, "recorded": False, "strategy": None,
                **{name: None for name in _SCENARIO_FIELDS}}
    return {"kind": kind, "recorded": True, **summary}


#: The ``StrategySummary`` fields the scenario table reads, so a kind with
#: no summary can be shown as n/a in each of them.
_SCENARIO_FIELDS: tuple[str, ...] = (
    "is_manipulation_strategy", "trader_count", "active_trader_count", "participation",
    "fill_count", "buy_volume", "sell_volume", "wash_volume", "total_volume", "total_notional",
    "vwap", "net_coin_flow", "net_cash_flow", "fill_ratio", "average_fill_size", "pnl",
)


def _pump_and_dump(summaries: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Pump-and-dump**")
    if not summaries:
        st.info(NO_PUMP_AND_DUMP_MESSAGE)
        return
    st.caption(f"manipulators summarised {count(len(summaries))}")
    _table(PHASE_COLUMNS, list(_phase_rows(summaries)))
    st.caption(
        "One row per manipulator and phase, as the analytics counted them from each fill's own "
        "recorded reason. A phase with no recorded fills has no first or last tick, shown as n/a: "
        "the analytics cannot tell a phase that never ran from one whose ticks fall outside the "
        "analysed range, and this section keeps that distinction open."
    )
    _table(SPAN_COLUMNS, summaries)
    st.caption(SPAN_NOTE)
    render_notes(
        "Phases are per manipulator, as the analytics keep them: each pump-and-dump trader runs "
        "its own schedule, and the summaries are never merged into one."
    )


def _phase_rows(summaries: Sequence[dict[str, Any]]):
    """One flattened row per manipulator and phase, reading the report's
    own per-phase fields."""
    for summary in summaries:
        for phase, fills, volume, first, last in PHASE_FIELDS:
            yield {
                "trader_id": summary["trader_id"],
                "phase": phase,
                "fills": summary[fills],
                "volume": summary[volume],
                "first_tick": summary[first],
                "last_tick": summary[last],
            }


def _wash(wash: dict[str, Any]) -> None:
    st.markdown("**Wash trading**")
    if not wash["fill_count"]:
        st.info(NO_WASH_MESSAGE)
    _table(
        (("Metric", _field("metric", TEXT)), ("Value", _field("value", TEXT))),
        [{"metric": label, "value": _FORMATTERS[kind](wash[name])} for label, name, kind in WASH_ROWS],
    )
    st.caption(
        "The aggregate wash record: every fill the simulator flagged as a wash leg, on both "
        "sides, whichever trader recorded it. The volume is the analytics' own — the buy and sell "
        "legs are already counted the way they define wash volume, and nothing is re-counted "
        "here. A run with no wash legs keeps its zeros and has no first or last tick."
    )


def _comparison(comparison: dict[str, Any]) -> None:
    st.markdown("**Manipulation beside organic activity**")
    rows = [
        {
            "figure": label,
            "manipulation": _FORMATTERS[kind](comparison[left]),
            "organic": _FORMATTERS[kind](comparison[right]),
        }
        for label, left, right, kind in COMPARISON_ROWS
    ]
    _table(
        (
            ("Figure", _field("figure", TEXT)),
            ("Manipulation", _field("manipulation", TEXT)),
            ("Organic", _field("organic", TEXT)),
        ),
        rows,
    )
    st.caption(
        f"manipulation share of the two {percent(comparison['manipulation_volume_share'], RATIO_SPEC)}"
    )
    st.caption(
        "The analytics' own side-by-side record of manipulation activity (wash legs and "
        "registered manipulation fills) and organic trader activity over the same ticks. It is a "
        "comparison of two sets of recorded fills — not a ranking, and not a statement that "
        "either set moved the market or answered the other."
    )
    render_notes(
        "Notional in this table is the figure the report carries for manipulation activity as a "
        "whole. Each kind's own notional is in the kinds table above, which is where a "
        "per-strategy notional is reported."
    )


def _table(
    columns: Sequence[tuple[str, Callable[[dict[str, Any]], str]]],
    rows: Sequence[dict[str, Any]],
) -> None:
    """One row per record, in the report's order, every cell formatted."""
    frame = pd.DataFrame([{header: render(row) for header, render in columns} for row in rows])
    st.dataframe(frame, hide_index=True, width="stretch")
