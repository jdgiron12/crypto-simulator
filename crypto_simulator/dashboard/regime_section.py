"""The market-regimes section of the dashboard (Phase 10, Step 6).

Display only. The section receives the serialized ``report.regimes`` —
``analyze_regimes``' own ``RegimeReport``, which carries one
``RegimeObservation`` per window (each embedding that window's
``MarketSummary`` and its ``RegimeContext``) and the report's own label
tallies — and lays it out. It computes no figure and assigns no label: no
direction, volatility class, volume class, market state, description,
quartile reference, count, distribution or completeness is derived here.
Every value on screen is one the report holds, passed through a format
spec from ``dashboard.formatting``.

**Layout** (one payload, read once):

    overview      windows, completeness, window size, the analysed grid
    windows       one row per window: its labels and its description
    figures       one row per window: the market figures the labels read
    context       one row per window: what else was recorded in it
    distribution  the report's own tallies per label
    chart         the recorded volume per observed tick, by window

**Labels are the analytics'.** ``rising``/``falling``/``flat``,
``low_volatility``/``normal_volatility``/``high_volatility``,
``low_volume``/``normal_volume``/``high_volume`` and
``at_high``/``drawdown``/``recovery`` are shown with the exact spelling
and casing the report uses. There is no combined regime label, since the
analytics define none, and the description is the report's own — the four
labels as it joins them, never re-joined here.

**Descriptive of one past window.** A regime is a label for what the
recorded market looked like over a stretch of ticks that has already
happened. Nothing here says a regime moved a trader, explains a price, or
says anything about the ticks that follow it; ``recovery`` describes a
drawdown that had already narrowed by the window's close, not one still to
come. A test reads back everything on screen to keep the wording that way.

**Early windows stay unlabelled.** A volatility or volume class needs
enough earlier complete windows for a quartile reference, and a direction
needs enough returns inside the window. Until then the analytics report no
label, which is shown as ``n/a`` and left that way — never filled in from
the window's own figures, and never carried over from a neighbour. A
window shorter than the grid says it is incomplete rather than being
padded.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.analytics.regimes import COVERAGE_PARTIAL, MIN_REFERENCE_WINDOWS
from crypto_simulator.dashboard.formatting import (
    RATIO_SPEC,
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
from crypto_simulator.dashboard.notes import render_notes
from crypto_simulator.visualization.charts import component_lines_chart

__all__ = [
    "DISTRIBUTIONS",
    "NO_WINDOWS_MESSAGE",
    "UNAVAILABLE_MESSAGE",
    "VOLUME_CHART_TITLE",
    "render_regimes",
]

UNAVAILABLE_MESSAGE = (
    "This payload carries no regime report, so there are no market regimes to show."
)
NO_WINDOWS_MESSAGE = (
    "The report describes no regime windows for this run: a window needs at least one analysed "
    "tick to be reported."
)
VOLUME_CHART_TITLE = "Recorded volume per observed tick, by window"
INCOMPLETE_NOTE = (
    "A window is complete when it holds every tick of its grid span. A shorter window — the last "
    "one of a run, or one with a gap — is reported on the ticks it has and marked incomplete; it "
    "is never padded, and its figures cover only its own ticks."
)

# --- value kinds ------------------------------------------------------------------------------------------

TEXT, FLAG, COUNT, TICK = "text", "flag", "count", "tick"
PRICE, VOLUME, RATIO, RETURN = "price", "volume", "ratio", "return"
#: A log return carries its sign and is not a percentage.
SIGNED_VALUE = "signed_value"

_FORMATTERS: dict[str, Callable[[Any], str]] = {
    TEXT: text,
    FLAG: flag,
    COUNT: count,
    TICK: tick,
    PRICE: number,
    VOLUME: lambda value: number(value, VOLUME_SPEC),
    RATIO: lambda value: percent(value, RATIO_SPEC),
    RETURN: percent,
    SIGNED_VALUE: lambda value: number(value, "+.4f"),
}

#: The four dimensions the report tallies, with the field holding each
#: tally. The labels inside them are the report's own.
DISTRIBUTIONS: tuple[tuple[str, str], ...] = (
    ("direction", "direction_counts"),
    ("volatility", "volatility_counts"),
    ("volume", "volume_counts"),
    ("market state", "market_state_counts"),
)


def _field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    return lambda row: _FORMATTERS[kind](row[name])


def _market_field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column from the window's own embedded ``MarketSummary``."""
    return lambda row: _FORMATTERS[kind](row["market"][name])


def _context_field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column from the window's own ``RegimeContext``."""
    return lambda row: _FORMATTERS[kind](row["context"][name])


def _reference(name: str) -> Callable[[dict[str, Any]], str]:
    """The lower and upper quartile the analytics compared this window
    against, or ``n/a`` while there were too few earlier complete windows
    for them to have one."""

    def render(row: dict[str, Any]) -> str:
        bounds = row[name]
        if bounds is None:
            return UNAVAILABLE
        lower, upper = bounds
        return f"{number(lower)} to {number(upper)}"

    return render


def _recorded_names(name: str) -> Callable[[dict[str, Any]], str]:
    """A window's recorded event ids or categories, as the report lists
    them."""
    return lambda row: ", ".join(row["context"][name]) or "none"


#: One row per window: the labels the analytics assigned, and their own
#: description of the window.
WINDOW_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Window", _field("window_index", COUNT)),
    ("Ticks", lambda row: tick_range(row["start_tick"], row["end_tick"])),
    ("Observed ticks", _field("tick_count", COUNT)),
    ("Grid span", _field("expected_tick_count", COUNT)),
    ("Complete", _field("complete", FLAG)),
    ("Direction", _field("direction", TEXT)),
    ("Volatility", _field("volatility", TEXT)),
    ("Volume", _field("volume", TEXT)),
    ("Market state", _field("market_state", TEXT)),
    ("Description", _field("description", TEXT)),
)

#: One row per window: the figures the labels are read from, kept beside
#: them so each label can be checked against the report by hand.
FIGURE_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Window", _field("window_index", COUNT)),
    ("Ticks", lambda row: tick_range(row["start_tick"], row["end_tick"])),
    ("Open", _market_field("open_price", PRICE)),
    ("Close", _market_field("close_price", PRICE)),
    ("Return", _market_field("cumulative_return", RETURN)),
    ("Net log return", _field("net_log_return", SIGNED_VALUE)),
    ("Volatility", _market_field("volatility", PRICE)),
    ("Realized volatility", _market_field("realized_volatility", PRICE)),
    ("Volatility reference", _reference("volatility_reference")),
    ("Volume", lambda row: number(row["market"]["volume_breakdown"]["total_volume"], VOLUME_SPEC)),
    ("Volume per tick", _field("volume_per_tick", VOLUME)),
    ("Volume reference", _reference("volume_reference")),
    ("Running peak", _field("running_peak", PRICE)),
    ("Drawdown at start", _field("drawdown_at_start", RATIO)),
    ("Drawdown at end", _field("drawdown_at_end", RATIO)),
)

#: One row per window: what else the analytics recorded in it. Context is
#: recorded alongside the labels and takes no part in assigning them.
CONTEXT_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Window", _field("window_index", COUNT)),
    ("Ticks", lambda row: tick_range(row["start_tick"], row["end_tick"])),
    ("Event state ticks", _context_field("event_state_ticks", COUNT)),
    ("Event active ticks", _context_field("event_active_ticks", COUNT)),
    ("Event live", _context_field("event_active", FLAG)),
    ("Most events at once", _context_field("max_concurrent_events", COUNT)),
    ("Events", _recorded_names("event_ids")),
    ("Categories", _recorded_names("event_categories")),
    ("Psychology ticks", _context_field("psychology_ticks", COUNT)),
    ("Mean fear", _context_field("mean_fear", PRICE)),
    ("Mean FOMO", _context_field("mean_fomo", PRICE)),
    ("Mean conviction", _context_field("mean_conviction", PRICE)),
    ("Mean uncertainty", _context_field("mean_uncertainty", PRICE)),
    ("Whale observed ticks", _context_field("whale_observed_ticks", COUNT)),
)

#: The report's own tallies: one row per dimension and label.
DISTRIBUTION_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Dimension", _field("dimension", TEXT)),
    ("Label", _field("label", TEXT)),
    ("Windows", _field("windows", COUNT)),
)


def render_regimes(
    regimes: dict[str, Any] | None,
    *,
    symbol: str,
    simulation: dict[str, Any] | None = None,
    heading: bool = True,
) -> None:
    """Render the regime section from the serialized ``report.regimes``.

    ``heading`` (Phase 24, Step 5) draws the section's own heading; the
    Simulate workspace passes ``False``, since its tab already names the section.
    """
    if heading:
        st.markdown("**Market regimes**")
    if regimes is None:
        st.info(UNAVAILABLE_MESSAGE)
        return

    _coverage(regimes)
    observations = regimes["observations"]
    if not observations:
        st.info(NO_WINDOWS_MESSAGE)
        return

    _overview(regimes, observations)
    _windows(observations)
    _figures(observations)
    _context(observations)
    _distribution(regimes)
    _chart(observations, symbol)


# --- sections --------------------------------------------------------------------------------------------


def _coverage(regimes: dict[str, Any]) -> None:
    st.caption(
        f"window coverage {text(regimes['coverage'])} · window size "
        f"{count(regimes['window_size'])} ticks · ticks analysed {count(regimes['ticks'])} · "
        f"pricing mode {text(regimes['pricing_mode'])}"
    )
    if regimes["coverage"] == COVERAGE_PARTIAL:
        st.caption(INCOMPLETE_NOTE)


def _overview(regimes: dict[str, Any], observations: Sequence[dict[str, Any]]) -> None:
    columns = st.columns(4)
    columns[0].metric("Regime windows", count(regimes["total_windows"]))
    columns[1].metric("Complete windows", count(regimes["complete_windows"]))
    columns[2].metric("Incomplete windows", count(regimes["incomplete_windows"]))
    columns[3].metric("Window size (ticks)", count(regimes["window_size"]))
    first, last = observations[0], observations[-1]
    st.caption(
        f"window grid {tick_range(first['start_tick'], last['end_tick'])} · first window "
        f"{tick_range(first['start_tick'], first['end_tick'])} · last window "
        f"{tick_range(last['start_tick'], last['end_tick'])}"
    )
    st.caption(
        "Windows are fixed on tick numbers, so the grid spans whole windows even where the run "
        "stops part-way through the last one. Every window and completeness figure above is the "
        "report's own."
    )
    st.caption(
        "Each label describes its own window only. The four dimensions are reported separately, "
        "as the analytics define them; there is no combined regime label, and no label says "
        "anything about the ticks after its window."
    )


def _windows(observations: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Regime windows**")
    _table(WINDOW_COLUMNS, observations)
    st.caption(
        "One row per window, in the report's order, with the labels the analytics assigned and "
        "their own description of the window. The description is the report's field, shown as it "
        "stands."
    )
    render_notes(
        f"A label shown as n/a is one the analytics report as unavailable: a direction needs "
        f"enough returns inside the window, and a volatility or volume class needs at least "
        f"{MIN_REFERENCE_WINDOWS} earlier complete windows for its quartile reference. Early "
        f"windows therefore stay unlabelled, and n/a keeps that meaning rather than standing for "
        f"a normal or absent reading.",
        "The description is the report's own field, joining the same four labels; it writes a "
        "missing label as 'unavailable' where the columns beside it show n/a. Both stand for the "
        "same thing: the analytics assigned no label there.",
        INCOMPLETE_NOTE,
    )


def _figures(observations: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Window figures**")
    _table(FIGURE_COLUMNS, observations)
    st.caption(
        "The figures each label is read from, as the analytics recorded them: the window's own "
        "market summary, its net log return over consecutive ticks, the quartile reference of the "
        "earlier complete windows, and the drawdown from the highest price observed up to each "
        "end of the window."
    )
    render_notes(
        "A window with no quartile reference yet shows n/a there and carries no volatility or "
        "volume class in the table above — the two go together, and neither is filled in."
    )


def _context(observations: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Recorded alongside each window**")
    _table(CONTEXT_COLUMNS, observations)
    st.caption(
        "What else the analytics recorded within each window: live events, the psychology means "
        "over the ticks that carried a state, and the ticks carrying whale observations. This is "
        "recorded beside the labels and takes no part in assigning them — a window with a live "
        "event and a high-volatility class is two observations reported side by side."
    )
    render_notes(
        "'Event live' is n/a when no tick in the window recorded an event state at all, which the "
        "analytics keep apart from a window whose events were simply not live."
    )


def _distribution(regimes: dict[str, Any]) -> None:
    st.markdown("**Label distribution**")
    rows = [
        {"dimension": dimension, "label": label, "windows": windows}
        for dimension, field in DISTRIBUTIONS
        for label, windows in regimes[field]
    ]
    _table(DISTRIBUTION_COLUMNS, rows)
    st.caption(
        "The report's own tallies, one row per dimension and label, including the windows for "
        "which the dimension was unavailable (the n/a row). Nothing is counted or grouped here — "
        "these are the counts the analytics carry."
    )


def _chart(observations: Sequence[dict[str, Any]], symbol: str) -> None:
    frame = pd.DataFrame(
        [
            {"tick": observation["start_tick"], "volume_per_tick": observation["volume_per_tick"]}
            for observation in observations
        ]
    )
    st.plotly_chart(
        component_lines_chart(
            frame,
            series=("volume_per_tick",),
            title=VOLUME_CHART_TITLE,
            value_title=f"Volume per observed tick ({symbol})",
        ),
        width="stretch", theme=None,
    )
    st.caption(
        "Each window's own volume-per-observed-tick figure, placed at the tick its window starts "
        "at. The values are the report's; an incomplete window's figure covers the ticks it has."
    )


def _table(
    columns: Sequence[tuple[str, Callable[[dict[str, Any]], str]]],
    rows: Sequence[dict[str, Any]],
) -> None:
    """One row per record, in the report's order, every cell formatted."""
    frame = pd.DataFrame([{header: render(row) for header, render in columns} for row in rows])
    st.dataframe(frame, hide_index=True, width="stretch")
