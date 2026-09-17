"""The psychology section of the dashboard (Phase 10, Step 5).

Display only. The section receives the serialized
``report.psychology_market`` — ``analyze_psychology_market``' own report,
which embeds ``analyze_psychology``' component summaries — and lays it
out. It computes no figure: no mean, median, percentile, correlation,
threshold occupancy, persistence run, group average or event-period
difference is derived here, and the four components are shown exactly as
recorded, on their own [0, 1] scale. There is no combined "sentiment
score": the analytics define none, so neither does the dashboard.

**Layout** (one payload, read once):

    coverage       how many ticks carried psychology at all
    components     mean, median, range and percentiles per component
    chart          the recorded components over ticks
    occupancy      ticks at or above each threshold, per component
    persistence    the analytics' own longest run per component
    correlations   the recorded associations, same-tick and lagged
    groups         market averages for low and high ticks of a component
    event periods  means during event windows and outside them
    observations   the per-tick record, including its dominant label

**Association, never causation.** A correlation is an association between
two recorded series and is labelled as one. Nothing here says a component
moved the market or that an event changed a mood: the group and
event-period tables are described as comparisons of what was *observed*
during each set of ticks, and a test reads back everything on screen to
keep the wording that way.

**Missing is missing.** Psychology is off by default. A run without it has
no components, correlations or groups at all, which the section says
plainly instead of showing neutral values; a correlation the analytics
could not compute carries their own reason (too few pairs, zero variance)
rather than a zero; and the event-period comparison is absent unless the
run recorded events.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.formatting import (
    RATIO_SPEC,
    RETURN_SPEC,
    UNAVAILABLE,
    VOLUME_SPEC,
    count,
    flag,
    number,
    percent,
    text,
    tick,
)
from crypto_simulator.visualization.charts import component_lines_chart

__all__ = [
    "COMPONENT_CHART_TITLE",
    "OBSERVATION_LEAD_FIELDS",
    "OBSERVATION_TAIL_FIELDS",
    "PARTIAL_COVERAGE",
    "NO_EVENT_PERIODS_MESSAGE",
    "NO_PSYCHOLOGY_MESSAGE",
    "PSYCHOLOGY_OFF_MESSAGE",
    "render_psychology",
]

PSYCHOLOGY_OFF_MESSAGE = (
    "This run was not given market psychology (it is off by default), so the report has no "
    "psychology to describe. Turn on 'Psychology' in the run options to record it."
)
NO_PSYCHOLOGY_MESSAGE = "The report records no psychology observations for this run."
NO_EVENT_PERIODS_MESSAGE = (
    "The report has no event-period comparison for this run: it needs ticks recorded with events "
    "to compare against ticks without them."
)
NO_DOMINANT_AGGREGATE_MESSAGE = (
    "The dominant component is recorded per tick (in the observations below). This report carries "
    "no dominant-component totals, so none are shown."
)
COMPONENT_CHART_TITLE = "Recorded psychology components"
OBSERVATIONS_LABEL = "Per-tick psychology observations"

#: ``analytics.psychology_market.COVERAGE_PARTIAL``, repeated rather than
#: imported: only the simulator and the psychology analytics themselves may
#: import that package (tests/core/psychology/test_signals.py enforces it),
#: so this section reads the coverage string the payload carries. A test
#: pins this literal to the analytics constant.
PARTIAL_COVERAGE = "partial"

VALUE = "value"  # a component reading on its own [0, 1] scale
#: A figure that carries its sign: a correlation, a difference between two
#: means, an event's sentiment.
SIGNED_VALUE = "signed_value"
TEXT, FLAG, COUNT, TICK = "text", "flag", "count", "tick"
PRICE, VOLUME, RATIO, RETURN = "price", "volume", "ratio", "return"

_FORMATTERS: dict[str, Callable[[Any], str]] = {
    TEXT: text,
    FLAG: flag,
    COUNT: count,
    TICK: tick,
    VALUE: number,
    SIGNED_VALUE: lambda value: number(value, "+.4f"),
    PRICE: number,
    VOLUME: lambda value: number(value, VOLUME_SPEC),
    RATIO: lambda value: percent(value, RATIO_SPEC),
    RETURN: percent,
}


def _field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    return lambda row: _FORMATTERS[kind](row[name])


def _nested(section: str, name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    def render(row: dict[str, Any]) -> str:
        record = row[section]
        return UNAVAILABLE if record is None else _FORMATTERS[kind](record[name])

    return render


#: One row per component: the summary ``analyze_psychology`` computed.
COMPONENT_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Component", _field("component", TEXT)),
    ("Ticks", _field("count", COUNT)),
    ("Mean", _field("mean", VALUE)),
    ("Median", _field("median", VALUE)),
    ("Minimum", _field("minimum", VALUE)),
    ("Maximum", _field("maximum", VALUE)),
    ("P90", _field("p90", VALUE)),
    ("P95", _field("p95", VALUE)),
)

#: One row per component and threshold, from the component's own
#: occupancy record.
OCCUPANCY_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Component", _field("component", TEXT)),
    ("Threshold", _field("threshold", VALUE)),
    ("Ticks at or above", _field("ticks", COUNT)),
    ("Share of ticks", _field("share", RATIO)),
)

#: One row per component: the analytics' own persistence record.
PERSISTENCE_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Component", _field("component", TEXT)),
    ("Threshold", _nested("persistence", "threshold", VALUE)),
    ("Longest run", _nested("persistence", "longest_run", COUNT)),
    ("Longest run starts", _nested("persistence", "longest_run_start", TICK)),
    ("Runs", _nested("persistence", "runs", COUNT)),
)

#: The recorded associations, with the analytics' own reason when a value
#: could not be computed.
CORRELATION_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Series", _field("x", TEXT)),
    ("Compared with", _field("y", TEXT)),
    ("Direction", _field("direction", TEXT)),
    ("Lag", _field("lag", COUNT)),
    ("Pairs", _field("pairs", COUNT)),
    ("Correlation", _field("value", SIGNED_VALUE)),
    ("Unavailable because", _field("unavailable_reason", TEXT)),
)

#: Market averages for the ticks below and at or above a threshold.
GROUP_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Component", _field("component", TEXT)),
    ("Threshold", _field("threshold", VALUE)),
    ("Low ticks", lambda row: count(row["low"]["ticks"])),
    ("Low mean log return", lambda row: number(row["low"]["mean_log_return"], "+.4f")),
    ("Low mean volume", lambda row: number(row["low"]["mean_volume"], VOLUME_SPEC)),
    ("Low mean participant volume",
     lambda row: number(row["low"]["mean_participant_volume"], VOLUME_SPEC)),
    ("High ticks", lambda row: count(row["high"]["ticks"])),
    ("High mean log return", lambda row: number(row["high"]["mean_log_return"], "+.4f")),
    ("High mean volume", lambda row: number(row["high"]["mean_volume"], VOLUME_SPEC)),
    ("High mean participant volume",
     lambda row: number(row["high"]["mean_participant_volume"], VOLUME_SPEC)),
)

#: Component means during event windows and outside them.
EVENT_PERIOD_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Component", _field("component", TEXT)),
    ("Mean during event ticks", _field("event_period_mean", VALUE)),
    ("Mean during other ticks", _field("other_period_mean", VALUE)),
    ("Difference", _field("difference", SIGNED_VALUE)),
)

#: The per-tick record the analytics kept, either side of the component
#: readings: the components themselves are named by the report, so the
#: table follows whatever components it summarised.
OBSERVATION_LEAD_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Tick", "tick", TICK),
    ("Price", "price", PRICE),
    ("Simple return", "simple_return", RETURN),
    ("Log return", "log_return", SIGNED_VALUE),
    ("Volume", "volume", VOLUME),
    ("Participant volume", "participant_volume", VOLUME),
    ("Whale volume", "whale_volume", VOLUME),
)
OBSERVATION_TAIL_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Dominant", "dominant", TEXT),
    ("Event active", "event_active", FLAG),
    ("Events live", "event_count", COUNT),
    ("Event sentiment", "event_sentiment", SIGNED_VALUE),
    ("Event attention", "event_attention", VALUE),
)


def observation_fields(components: Sequence[str]) -> tuple[tuple[str, str, str], ...]:
    """The observation columns for a report that summarised
    ``components`` — the report's own component names, in its own order."""
    return (
        *OBSERVATION_LEAD_FIELDS,
        *((component.capitalize(), component, VALUE) for component in components),
        *OBSERVATION_TAIL_FIELDS,
    )


def render_psychology(
    psychology: dict[str, Any],
    *,
    symbol: str,
    simulation: dict[str, Any] | None = None,
) -> None:
    """Render the psychology section from the serialized
    ``report.psychology_market``."""
    st.markdown("**Psychology**")
    _coverage(psychology)
    if not psychology["components"]:
        st.info(_unavailable_message(simulation))
        return

    names = _component_names(psychology["components"])
    _components(psychology["components"])
    _chart(psychology["observations"], names)
    _occupancy(psychology["components"])
    _persistence(psychology["components"])
    _correlations(psychology["correlations"])
    _groups(psychology["groups"])
    _event_periods(psychology["event_periods"])
    _observations(psychology["observations"], names)


# --- sections --------------------------------------------------------------------------------------------


def _coverage(psychology: dict[str, Any]) -> None:
    st.caption(
        f"psychology coverage {text(psychology['coverage'])} · ticks with psychology "
        f"{count(psychology['ticks_with_psychology'])} of {count(psychology['ticks'])} "
        f"· recorded ticks "
        f"{tick(psychology['first_psychology_tick'])}-{tick(psychology['last_psychology_tick'])} · "
        f"pricing mode {text(psychology['pricing_mode'])}"
    )
    if psychology["coverage"] == PARTIAL_COVERAGE:
        st.caption(
            "Partial coverage: some analysed ticks carry no psychology. The figures below describe "
            "the ticks that do."
        )


def _unavailable_message(simulation: dict[str, Any] | None) -> str:
    params = (simulation or {}).get("params") or {}
    if params.get("psychology") is False:
        return PSYCHOLOGY_OFF_MESSAGE
    return NO_PSYCHOLOGY_MESSAGE


def _component_names(components: Sequence[dict[str, Any]]) -> list[str]:
    """The components this report summarised, named by the report."""
    return [component["component"] for component in components]


def _components(components: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Components**")
    _table(COMPONENT_COLUMNS, components)
    st.caption(
        "Fear, FOMO, conviction and uncertainty as the analytics summarised them, each on its own "
        "0-1 scale and shown unchanged. They are not combined into a single score."
    )


def _chart(observations: Sequence[dict[str, Any]], components: Sequence[str]) -> None:
    if not observations:
        return
    frame = pd.DataFrame(observations)
    st.plotly_chart(
        component_lines_chart(
            frame, series=components, title=COMPONENT_CHART_TITLE, value_title="Component value"
        ),
        width="stretch",
    )
    st.caption(
        "The component values recorded at each tick, drawn from the report's own observations."
    )


def _occupancy(components: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Threshold occupancy**")
    rows = [
        {"component": component["component"], **occupancy}
        for component in components
        for occupancy in component["occupancy"]
    ]
    _table(OCCUPANCY_COLUMNS, rows)
    st.caption(
        "Ticks whose recorded value reached each threshold, counted by the analytics; the share is "
        "their own figure."
    )


def _persistence(components: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Persistence**")
    _table(PERSISTENCE_COLUMNS, components)
    st.caption(
        "The longest unbroken run of ticks at or above the persistence threshold, and how many "
        "such runs there were — the analytics' own counts. A component that never reached the "
        "threshold has a longest run of zero and no start tick."
    )


def _correlations(correlations: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Associations**")
    if not correlations:
        st.caption("The report records no associations for this run.")
        return
    _table(CORRELATION_COLUMNS, correlations)
    st.caption(
        "Correlation coefficients between the recorded series, same-tick and lagged, as the "
        "analytics computed them. These are associations observed together in one synthetic run — "
        "each describes how two series moved alongside each other, and nothing more."
    )
    st.caption(
        "A correlation the analytics could not compute keeps their reason (too few pairs, or a "
        "series with no variance) instead of a number; a computed one has no reason, shown as n/a."
    )


def _groups(groups: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Market averages by component level**")
    if not groups:
        st.caption("The report records no grouped comparison for this run.")
        return
    _table(GROUP_COLUMNS, groups)
    st.caption(
        "For each component, the market averages the analytics computed over the ticks below its "
        "threshold and over the ticks at or above it. A descriptive comparison of two sets of "
        "ticks, not a statement about either side."
    )


def _event_periods(event_periods: dict[str, Any] | None) -> None:
    st.markdown("**During event windows**")
    if event_periods is None:
        st.caption(NO_EVENT_PERIODS_MESSAGE)
        return
    st.caption(
        f"source {text(event_periods['source'])} · event ticks "
        f"{count(event_periods['event_period_ticks'])} · other ticks "
        f"{count(event_periods['other_period_ticks'])} · unclassified "
        f"{count(event_periods['unclassified_ticks'])}"
    )
    _table(EVENT_PERIOD_COLUMNS, event_periods["components"])
    st.caption(
        "The mean each component took during ticks with a live event and during the rest, with "
        "the analytics' own difference between them. Both are descriptions of what was observed "
        "in each set of ticks."
    )


def _observations(observations: Sequence[dict[str, Any]], components: Sequence[str]) -> None:
    st.caption(NO_DOMINANT_AGGREGATE_MESSAGE)
    columns = tuple(
        (header, _field(field, kind)) for header, field, kind in observation_fields(components)
    )
    with st.expander(OBSERVATIONS_LABEL):
        _table(columns, observations)
        st.caption(
            "One row per analysed tick: the recorded components, the dominant one the analytics "
            "named, and the market and event state alongside them."
        )


def _table(
    columns: Sequence[tuple[str, Callable[[dict[str, Any]], str]]],
    rows: Sequence[dict[str, Any]],
) -> None:
    """One row per record, in the report's order, every cell formatted."""
    frame = pd.DataFrame([{header: render(row) for header, render in columns} for row in rows])
    st.dataframe(frame, hide_index=True, width="stretch")
