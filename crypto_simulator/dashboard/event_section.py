"""The events section of the dashboard (Phase 10, Step 5).

Display only. The section receives the serialized
``report.event_windows`` — ``analyze_event_windows``' own
``EventWindowReport``, which carries each event's ground truth and the
market summary of each window around it — and lays it out. It computes no
figure: no return, price change, volatility, volume, severity, duration,
overlap or category total is derived here. Every number on screen is a
value the report holds, passed through a format spec from
``dashboard.formatting``.

**Layout** (one payload, read once):

    overview    what the report covers
    events      one row per event: its recorded ground truth and overlap
    windows     one row per event window: what the market did during it
    categories  the report's own per-category activity
    detail      one event's ground truth and windows

**Descriptive, never causal.** Every window is a stretch of ticks around
an event, and the figures are what the market recorded *during* that
stretch. Nothing here says an event moved the price, and where two events'
windows overlap the report lists them side by side rather than attributing
the move to either. The wording stays with "during", "observed" and
"overlapping", and a test reads back everything on screen to keep it that
way.

**Provenance is recorded, not guessed.** An event is scheduled or randomly
generated because ``EventGroundTruth.randomly_generated`` says so; without
that flag the provenance is unknown, which is shown as such and never
inferred from an event's id or category.

**Unavailable is not empty.** A run with no event timeline (``None``) is
kept distinct from a timeline in which no event started in the analysed
range (an empty list), because the analytics keep them distinct.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.formatting import (
    NOTIONAL_SPEC,
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
    "ALL_EVENTS",
    "DETAIL_COLUMNS",
    "EVENT_SELECT_KEY",
    "NO_EVENTS_IN_RANGE_MESSAGE",
    "NO_TIMELINE_MESSAGE",
    "WINDOW_NAMES",
    "render_events",
]

NO_TIMELINE_MESSAGE = (
    "This run had no news events, so the report has no event timeline. Turn on 'News events' or "
    "'Random news events' in the run options to observe some."
)
NO_EVENTS_IN_RANGE_MESSAGE = (
    "This run has an event timeline, but no event started in the analysed ticks, so there are no "
    "event windows to describe."
)
SELECT_HINT = "Pick an event to see its recorded ground truth and each of its windows."
ALL_EVENTS = "All events"
SCHEDULED, RANDOM = "scheduled", "random"

EVENT_SELECT_KEY = "coin_dashboard_event"
DETAIL_COLUMNS = ("Metric", "Value")

#: The windows ``analyze_event_windows`` measures around an event, in the
#: order it defines them. ``pre_event`` and ``decay`` are ``None`` when the
#: event has no such window.
WINDOW_NAMES: tuple[str, ...] = ("pre_event", "active", "decay", "post_event", "effect")

TEXT, FLAG, COUNT, TICK = "text", "flag", "count", "tick"
PRICE, VOLUME, NOTIONAL = "price", "volume", "notional"
RETURN = "return"
#: An event's severity, sentiment, volatility boost and attention are
#: scalars on their own scales, shown the way ``analytics.rendering``
#: shows them: plain numbers, signed where the value can be negative.
VALUE, SIGNED_VALUE = "value", "signed_value"

_FORMATTERS: dict[str, Callable[[Any], str]] = {
    TEXT: text,
    FLAG: flag,
    COUNT: count,
    TICK: tick,
    PRICE: number,
    VALUE: number,
    SIGNED_VALUE: lambda value: number(value, "+.4f"),
    VOLUME: lambda value: number(value, VOLUME_SPEC),
    NOTIONAL: lambda value: number(value, NOTIONAL_SPEC),
    RETURN: percent,
}

#: Every field of ``EventGroundTruth``, as the detail view lists them.
GROUND_TRUTH_DETAIL: tuple[tuple[str, str, str], ...] = (
    ("Event", "event_id", TEXT),
    ("Category", "category", TEXT),
    ("Headline", "headline", TEXT),
    ("Severity", "severity", VALUE),
    ("Sentiment", "sentiment", SIGNED_VALUE),
    ("Volatility boost", "volatility_boost", VALUE),
    ("Attention", "attention", VALUE),
    ("Start tick", "start_tick", TICK),
    ("Last active tick", "last_active_tick", TICK),
    ("Duration", "duration", COUNT),
    ("Decay ticks", "decay_ticks", COUNT),
    ("Expires at", "expires_at", TICK),
    ("Randomly generated", "randomly_generated", FLAG),
)


def _ground_truth(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    return lambda event: _FORMATTERS[kind](event["ground_truth"][name])


def _field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    return lambda row: _FORMATTERS[kind](row[name])


def _provenance(event: dict[str, Any]) -> str:
    """Scheduled or randomly generated, as the analytics recorded it;
    unknown when no provenance was supplied."""
    recorded = event["ground_truth"]["randomly_generated"]
    if recorded is None:
        return f"{UNAVAILABLE} (not recorded)"
    return RANDOM if recorded else SCHEDULED


def _overlapping_ids(event: dict[str, Any]) -> str:
    return ", ".join(event["overlapping_event_ids"]) or "none"


#: One row per event: the ground truth the simulator recorded.
EVENT_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Event", _field("event_id", TEXT)),
    ("Category", _ground_truth("category", TEXT)),
    ("Provenance", _provenance),
    ("Severity", _ground_truth("severity", VALUE)),
    ("Sentiment", _ground_truth("sentiment", SIGNED_VALUE)),
    ("Volatility boost", _ground_truth("volatility_boost", VALUE)),
    ("Attention", _ground_truth("attention", VALUE)),
    ("Start", _ground_truth("start_tick", TICK)),
    ("Last active", _ground_truth("last_active_tick", TICK)),
    ("Duration", _ground_truth("duration", COUNT)),
    ("Decay ticks", _ground_truth("decay_ticks", COUNT)),
    ("Expires at", _ground_truth("expires_at", TICK)),
    ("Overlapping", _field("overlapping", FLAG)),
    ("Overlap count", _field("overlap_count", COUNT)),
    ("Overlapping events", _overlapping_ids),
)

#: One row per (event, window): what the market recorded during it. The
#: figures are the window's own ``MarketSummary``.
WINDOW_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Event", _field("event_id", TEXT)),
    ("Window", _field("window", TEXT)),
    ("Requested ticks", _field("ticks_requested", COUNT)),
    ("Observed ticks", _field("ticks_observed", COUNT)),
    ("Complete", _field("complete", FLAG)),
    ("Tick range", lambda row: tick_range(row["requested_start"], row["requested_end"])),
    ("Open", lambda row: number(row["market"]["open_price"])),
    ("Close", lambda row: number(row["market"]["close_price"])),
    ("Return", lambda row: percent(row["market"]["cumulative_return"])),
    ("Volatility", lambda row: number(row["market"]["volatility"])),
    ("Volume", lambda row: number(row["market"]["volume_breakdown"]["total_volume"], VOLUME_SPEC)),
    ("Volume per tick", _field("volume_per_tick", VOLUME)),
)

#: The report's own per-category activity.
CATEGORY_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Category", _field("category", TEXT)),
    ("Events", _field("event_count", COUNT)),
    ("Observed ticks", _field("observed_ticks", COUNT)),
    ("Mean severity", _field("mean_severity", VALUE)),
    ("Mean sentiment", _field("mean_sentiment", SIGNED_VALUE)),
    ("Active return", _field("active_return", RETURN)),
    ("Post-event return", _field("post_event_return", RETURN)),
    ("Volume", _field("volume", VOLUME)),
    ("Volatility", _field("volatility", VALUE)),
)


def render_events(
    events: dict[str, Any] | None,
    *,
    symbol: str,
    simulation: dict[str, Any] | None = None,
    heading: bool = True,
) -> None:
    """Render the events section from the serialized ``report.event_windows``.

    ``events`` is ``None`` when the run had no event timeline at all,
    which the analytics keep distinct from a timeline with no events.

    ``heading`` (Phase 24, Step 5) draws the section's own heading; the
    Simulate workspace passes ``False``, since its tab already names the section.
    """
    if heading:
        st.markdown("**Events**")
    if events is None:
        st.info(NO_TIMELINE_MESSAGE)
        return

    st.caption(f"ticks analysed {count(events['ticks'])}")
    if not events["events"]:
        st.info(NO_EVENTS_IN_RANGE_MESSAGE)
        return

    _overview(events)
    _events_table(events["events"])
    _windows_table(events["events"])
    _categories(events["categories"])
    _detail(events["events"])


# --- sections --------------------------------------------------------------------------------------------


def _overview(events: dict[str, Any]) -> None:
    render_metric_row([
        ("Events observed", count(len(events["events"]))),
        ("Categories", count(len(events["categories"]))),
        ("Ticks analysed", count(events["ticks"])),
    ])
    st.caption(
        "'Events observed' and 'Categories' count the rows below; the analytics define no event "
        "totals of their own. An event is reported only if it starts within the analysed ticks."
    )


def _events_table(events: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Event timeline**")
    _table(EVENT_COLUMNS, events)
    st.caption(
        "One row per event, with the ground truth the simulator recorded: its category, severity, "
        "sentiment, attention and timing. Provenance is the recorded 'randomly generated' flag, "
        "never read off an event's id."
    )
    st.caption(
        "Overlapping events are events whose windows share ticks. They are listed side by side; "
        "the analytics do not attribute a market move to one of them."
    )


def _windows_table(events: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Event windows**")
    _table(WINDOW_COLUMNS, list(_window_rows(events)))
    st.caption(
        "One row per window around an event: the ticks before it (pre_event), while it was active, "
        "while it decayed, the ticks after it (post_event), and the effect window. Every figure is "
        "the market summary the analytics computed for that window — what was observed during it."
    )
    render_notes(
        "A window is complete when it observed every tick it asked for; a shorter window (at the "
        "start or end of a run) is marked incomplete rather than padded."
    )


def _window_rows(events: Sequence[dict[str, Any]]):
    """One flattened row per window the report has for each event; a
    window the event does not have (no pre-run ticks, no decay) is left
    out rather than shown as an empty window."""
    for event in events:
        for name in WINDOW_NAMES:
            window = event[name]
            if window is not None:
                yield {"event_id": event["event_id"], "window": name, **window}


def _categories(categories: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Categories**")
    if not categories:
        st.caption("The report groups no categories for this run.")
        return
    _table(CATEGORY_COLUMNS, categories)
    st.caption(
        "The report's own grouping of events by category, with the means and window figures it "
        "computed for each group."
    )


def _detail(events: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Event detail**")
    identifiers = [event["event_id"] for event in events]
    selected = st.selectbox("Event", (ALL_EVENTS, *identifiers), key=EVENT_SELECT_KEY)
    if selected == ALL_EVENTS:
        st.caption(SELECT_HINT)
        return
    event = next((row for row in events if row["event_id"] == selected), None)
    if event is None:  # the payload changed under a stale selection
        st.caption(SELECT_HINT)
        return
    label, value = DETAIL_COLUMNS
    rows = [
        {label: name, value: _FORMATTERS[kind](event["ground_truth"][field])}
        for name, field, kind in GROUND_TRUTH_DETAIL
    ]
    rows.append({label: "Overlapping events", value: _overlapping_ids(event)})
    rows.append({label: "Overlap count", value: count(event["overlap_count"])})
    st.table(pd.DataFrame(rows).set_index(label))
    _table(WINDOW_COLUMNS, list(_window_rows([event])))
    st.caption(
        "Everything the analytics record for this event, and the market summary of each of its "
        "windows. Selecting an event filters the payload already on screen: it runs no simulation "
        "and no analytics."
    )


def _table(
    columns: Sequence[tuple[str, Callable[[dict[str, Any]], str]]],
    rows: Sequence[dict[str, Any]],
) -> None:
    """One row per record, in the report's order, every cell formatted."""
    frame = pd.DataFrame([{header: render(row) for header, render in columns} for row in rows])
    st.dataframe(frame, hide_index=True, width="stretch")
