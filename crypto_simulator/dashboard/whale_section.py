"""The whale section of the dashboard (Phase 10, Step 4).

Display only. The section receives the serialized
``report.whale_activity`` — ``analyze_whale_activity``' own
``WhaleActivityReport``, which embeds ``analyze_whales``' ``WhaleSummary``
per whale — and lays it out. It computes no figure: no volume, share, net
flow, VWAP, allocation, gap, target statistic, behavior or cycle
occupancy, outcome count, co-fill ratio or cohort total is derived here.
Every number on screen is a value the report holds, passed through a
format spec from ``dashboard.formatting``.

**Layout** (one payload, read once):

    overview     the report's own whale totals and observation coverage
    activity     one row per observed whale: trades, volume, flows, pacing
    outcomes     what each whale's ticks were recorded as
    behavior     the report's per-behavior activity, and per-whale ticks
    allocation   targets, allocation path and gap statistics
    cohorts      cohort activity and its co-fill statistics
    detail       every recorded figure for one selected whale

**Recorded, not inferred.** A whale's behavior is the behavior the
simulator recorded for that tick, never a guess from the size or side of a
trade. A tick's outcome is the recorded outcome: a whale that did not fill
is ``no_fill``, one the pacing rules stopped is ``blocked_by_cooldown`` or
``blocked_by_interval``, one holding its target is ``held_at_target``, and
only a tick the analytics call ``inactive`` is inactive. The dashboard
never reclassifies one as another.

**Co-fill is co-occurrence.** ``CoFillStats`` counts ticks on which cohort
members filled together. Cohorts follow a fixed schedule set before the
run, so this describes what happened at the same time — it is not
evidence that one whale moved another, and the section never calls it
herding, influence or coordination in that sense.

**Unavailable is not zero.** Whale analytics need whale observation to be
recorded. A run without whales, a run whose whales were not observed, and
an AMM run (whose pricing mode does not support whales at all) each give a
report with no whales; the section says which of those happened, using the
run's own parameters, rather than showing zeros. Coverage
(``none``/``partial``/``complete``) and the observed tick count are always
shown.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import pandas as pd
import streamlit as st

from crypto_simulator.analytics.whale_activity import COVERAGE_PARTIAL
from crypto_simulator.analytics.whales import TICK_OUTCOMES
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
)
from crypto_simulator.dashboard.metric_row import render_metric_row

__all__ = [
    "ALL_WHALES",
    "AMM_MESSAGE",
    "DETAIL_COLUMNS",
    "NOT_OBSERVED_MESSAGE",
    "NO_ACTIVITY_MESSAGE",
    "NO_COHORTS_MESSAGE",
    "NO_WHALES_MESSAGE",
    "WHALE_SELECT_KEY",
    "render_whales",
]

AMM_MESSAGE = (
    "This run used AMM pricing, which the simulator does not support whales in, so there is no "
    "whale activity to observe."
)
NO_WHALES_MESSAGE = "This run was configured without whales, so the report records no whale activity."
NOT_OBSERVED_MESSAGE = (
    "This run's whales were not observed ('Record whale detail' was off), so the whale analytics have "
    "nothing to describe. Whale trades are still counted in the market section's volume breakdown."
)
NO_ACTIVITY_MESSAGE = "The report records no whale activity for this run."
NO_COHORTS_MESSAGE = (
    "The report records no whale cohorts for this run. Cohorts are set through the Python API "
    "(CoinSimulator(whale_cohorts=...)), not through the sidebar's Run setup."
)
NO_CO_FILL_MESSAGE = "No cohort in this run has co-fill statistics."
SELECT_HINT = "Pick a whale to see every figure the report records for it."
ALL_WHALES = "All whales"
COFILL_NOTE = (
    "Co-fill counts ticks on which cohort members filled at the same time. A cohort follows a "
    "fixed schedule set before the run, so this describes co-occurrence — not one whale moving "
    "another."
)

WHALE_SELECT_KEY = "coin_dashboard_whale"
DETAIL_COLUMNS = ("Metric", "Value")

# --- value kinds ------------------------------------------------------------------------------------------

TEXT, FLAG, COUNT, TICK = "text", "flag", "count", "tick"
PRICE, VOLUME, NOTIONAL = "price", "volume", "notional"
SIGNED_VOLUME, SIGNED_NOTIONAL = "signed_volume", "signed_notional"
RATIO = "ratio"

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
}

#: ``WhaleActivity`` fields, then its embedded ``WhaleSummary`` fields,
#: as the detail view lists them. The nested allocation, gap, target and
#: per-tick mappings are expanded separately below.
ACTIVITY_DETAIL: tuple[tuple[str, str, str], ...] = (
    ("First fill tick", "first_fill_tick", TICK),
    ("Last fill tick", "last_fill_tick", TICK),
    ("Average fill size", "average_fill_size", VOLUME),
    ("Share of whale volume", "volume_share_of_whale_volume", RATIO),
)
SUMMARY_DETAIL: tuple[tuple[str, str, str], ...] = (
    ("Whale", "whale_id", TEXT),
    ("Funded", "funded", FLAG),
    ("Cohort", "cohort_id", TEXT),
    ("Observed ticks", "observed_ticks", COUNT),
    ("Trades", "trade_count", COUNT),
    ("Buy trades", "buy_count", COUNT),
    ("Sell trades", "sell_count", COUNT),
    ("Buy volume", "buy_volume", VOLUME),
    ("Sell volume", "sell_volume", VOLUME),
    ("Total volume", "total_volume", VOLUME),
    ("Buy notional", "buy_notional", NOTIONAL),
    ("Sell notional", "sell_notional", NOTIONAL),
    ("Notional", "notional", NOTIONAL),
    ("VWAP", "vwap", PRICE),
    ("Net coin flow", "net_coin_flow", SIGNED_VOLUME),
    ("Net cash flow", "net_cash_flow", SIGNED_NOTIONAL),
)
#: ``AllocationPath`` (``analyze_whales``' own allocation record).
ALLOCATION_DETAIL: tuple[tuple[str, str, str], ...] = (
    ("Allocation ticks", "ticks", COUNT),
    ("Target coin fraction", "target_coin_fraction", RATIO),
    ("First coin fraction", "first_coin_fraction", RATIO),
    ("Last coin fraction", "last_coin_fraction", RATIO),
    ("Mean coin fraction", "mean_coin_fraction", RATIO),
    ("Minimum coin fraction", "min_coin_fraction", RATIO),
    ("Maximum coin fraction", "max_coin_fraction", RATIO),
    ("Ticks at target", "ticks_at_target", COUNT),
    ("Maximum absolute gap", "max_abs_gap", RATIO),
    ("Crossed target", "crossed_target", FLAG),
    ("Dormant crossings", "dormant_crossings", COUNT),
)
#: ``AllocationGapStats`` and ``TargetReaching`` (``analyze_whale_activity``).
GAP_DETAIL: tuple[tuple[str, str, str], ...] = (
    ("Gap samples", "sample_count", COUNT),
    ("Mean absolute gap", "mean_absolute_gap", RATIO),
    ("Maximum absolute gap (observed)", "max_absolute_gap", RATIO),
    ("Mean signed gap", "mean_signed_gap", RATIO),
)
TARGET_DETAIL: tuple[tuple[str, str, str], ...] = (
    ("Ticks observed at target", "target_observation_count", COUNT),
    ("First tick at target", "first_tick_at_target", TICK),
    ("Ticks to target", "ticks_to_target", COUNT),
)


def _field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column showing one analytics field, formatted for its kind."""
    return lambda row: _FORMATTERS[kind](row[name])


def _summary_field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column showing one field of the whale's embedded summary."""
    return lambda activity: _FORMATTERS[kind](activity["summary"][name])


def _nested(section: str, name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column from a nested record the report may not have for this row
    (a cohort without co-fill statistics, a whale without a target)."""

    def render(row: dict[str, Any]) -> str:
        record = row[section]
        return UNAVAILABLE if record is None else _FORMATTERS[kind](record[name])

    return render


def _allocation_field(name: str, kind: str) -> Callable[[dict[str, Any]], str]:
    """A column from the whale's ``AllocationPath``, which only a whale
    managing a target has."""

    def render(activity: dict[str, Any]) -> str:
        record = activity["summary"]["allocation"]
        return UNAVAILABLE if record is None else _FORMATTERS[kind](record[name])

    return render


def _outcome_field(outcome: str) -> Callable[[dict[str, Any]], str]:
    """One recorded per-tick outcome, as the analytics counted it."""
    return lambda activity: count(activity["summary"]["outcome_ticks"].get(outcome))


def _pairs(mapping: dict[str, Any] | None) -> str:
    """A recorded per-key tick count, e.g. behaviors or cycle phases. The
    payload's keys are already sorted, so the text is stable."""
    if not mapping:
        return "none"
    return ", ".join(f"{name} {count(value)}" for name, value in mapping.items())


#: Per-whale activity columns.
ACTIVITY_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Whale", _summary_field("whale_id", TEXT)),
    ("Funded", _summary_field("funded", FLAG)),
    ("Cohort", _summary_field("cohort_id", TEXT)),
    ("Observed ticks", _summary_field("observed_ticks", COUNT)),
    ("Trades", _summary_field("trade_count", COUNT)),
    ("Volume", _summary_field("total_volume", VOLUME)),
    ("Share of whale volume", _field("volume_share_of_whale_volume", RATIO)),
    ("VWAP", _summary_field("vwap", PRICE)),
    ("Net coins", _summary_field("net_coin_flow", SIGNED_VOLUME)),
    ("Net cash", _summary_field("net_cash_flow", SIGNED_NOTIONAL)),
    ("First fill", _field("first_fill_tick", TICK)),
    ("Last fill", _field("last_fill_tick", TICK)),
    ("Average fill", _field("average_fill_size", VOLUME)),
)

#: Per-whale recorded tick outcomes, one column per outcome the analytics
#: define (``TICK_OUTCOMES``), plus what the whale was doing meanwhile.
OUTCOME_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Whale", _summary_field("whale_id", TEXT)),
    *((outcome, _outcome_field(outcome)) for outcome in TICK_OUTCOMES),
    ("Behavior ticks", lambda activity: _pairs(activity["summary"]["behavior_ticks"])),
    ("Cycle phase ticks", lambda activity: _pairs(activity["summary"]["phase_ticks"])),
)

#: Report-level behavior activity, one row per recorded behavior.
BEHAVIOR_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Behavior", _field("behavior", TEXT)),
    ("Observation ticks", _field("observation_ticks", COUNT)),
    ("Fills", _field("fill_count", COUNT)),
    ("Buy volume", _field("buy_volume", VOLUME)),
    ("Sell volume", _field("sell_volume", VOLUME)),
    ("Total volume", _field("total_volume", VOLUME)),
    ("Net coins", _field("net_coin_flow", SIGNED_VOLUME)),
)

#: Per-whale allocation and target statistics.
ALLOCATION_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Whale", _summary_field("whale_id", TEXT)),
    ("Target", _allocation_field("target_coin_fraction", RATIO)),
    ("First allocation", _allocation_field("first_coin_fraction", RATIO)),
    ("Last allocation", _allocation_field("last_coin_fraction", RATIO)),
    ("Mean allocation", _allocation_field("mean_coin_fraction", RATIO)),
    ("Ticks at target", _allocation_field("ticks_at_target", COUNT)),
    ("Crossed target", _allocation_field("crossed_target", FLAG)),
    ("Dormant crossings", _allocation_field("dormant_crossings", COUNT)),
    ("Mean absolute gap", _nested("allocation_gap", "mean_absolute_gap", RATIO)),
    ("Max absolute gap", _nested("allocation_gap", "max_absolute_gap", RATIO)),
    ("Mean signed gap", _nested("allocation_gap", "mean_signed_gap", RATIO)),
    ("Ticks observed at target", _nested("target_reaching", "target_observation_count", COUNT)),
    ("First tick at target", _nested("target_reaching", "first_tick_at_target", TICK)),
    ("Ticks to target", _nested("target_reaching", "ticks_to_target", COUNT)),
)

#: Cohort activity, as the report groups it.
COHORT_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Cohort", _field("cohort_id", TEXT)),
    ("Members", _field("member_count", COUNT)),
    ("Active members", _field("active_member_count", COUNT)),
    ("Observation ticks", _field("observation_ticks", COUNT)),
    ("Fills", _field("fill_count", COUNT)),
    ("Buy volume", _field("buy_volume", VOLUME)),
    ("Sell volume", _field("sell_volume", VOLUME)),
    ("Total volume", _field("total_volume", VOLUME)),
    ("Net coins", _field("net_coin_flow", SIGNED_VOLUME)),
    ("Share of whale volume", _field("volume_share_of_whale_volume", RATIO)),
)

#: Cohort co-fill statistics, kept apart from the activity table so the
#: wording can stay descriptive.
CO_FILL_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], str]], ...] = (
    ("Cohort", _field("cohort_id", TEXT)),
    ("Co-fill ratio", _nested("co_fill", "co_fill_ratio", RATIO)),
    ("Eligible member ticks", _nested("co_fill", "eligible_member_ticks", COUNT)),
    ("Co-fill member ticks", _nested("co_fill", "co_fill_member_ticks", COUNT)),
    ("Simultaneous fill ticks", _nested("co_fill", "simultaneous_fill_ticks", COUNT)),
    ("Same-side simultaneous", _nested("co_fill", "same_side_simultaneous_ticks", COUNT)),
    ("Mixed-side simultaneous", _nested("co_fill", "mixed_side_simultaneous_ticks", COUNT)),
)


def render_whales(
    whales: dict[str, Any],
    *,
    symbol: str,
    simulation: dict[str, Any] | None = None,
    heading: bool = True,
) -> None:
    """Render the whale section from the serialized ``report.whale_activity``.

    ``simulation`` is the payload's run metadata, used only to say *why*
    a run has no whale activity (no whales, no observation, or AMM).

    ``heading`` (Phase 24, Step 5) draws the section's own heading; the
    Simulate workspace passes ``False``, since its tab already names the section.
    """
    if heading:
        st.markdown("**Whales**")
    _coverage(whales)
    if not whales["whales"]:
        st.info(_unavailable_message(simulation))
        return

    _overview(whales, symbol)
    _activity(whales["whales"])
    _outcomes(whales["whales"])
    _behavior(whales)
    _allocation(whales["whales"])
    _cohorts(whales["cohorts"])
    _detail(whales["whales"])


# --- sections --------------------------------------------------------------------------------------------


def _coverage(whales: dict[str, Any]) -> None:
    st.caption(
        f"observation coverage {text(whales['coverage'])} · observed ticks "
        f"{count(whales['observed_ticks'])} of {count(whales['ticks'])}"
    )
    if whales["coverage"] == COVERAGE_PARTIAL:
        st.caption(
            "Partial coverage: some ticks carry no whale observation. The figures below describe "
            "the observed ticks only, and an unobserved tick is not a tick without activity."
        )


def _unavailable_message(simulation: dict[str, Any] | None) -> str:
    """Which of the three ways a run ends up with no whale analytics."""
    if simulation is None:
        return NO_ACTIVITY_MESSAGE
    params = simulation.get("params") or {}
    if simulation.get("pricing_mode") == "amm":
        return AMM_MESSAGE
    if params.get("include_whales") is False:
        return NO_WHALES_MESSAGE
    if params.get("whale_observation") is False:
        return NOT_OBSERVED_MESSAGE
    return NO_ACTIVITY_MESSAGE


def _overview(whales: dict[str, Any], symbol: str) -> None:
    render_metric_row([
        ("Whales listed", count(len(whales["whales"]))),
        ("Whale volume", number(whales["whale_volume"], VOLUME_SPEC)),
        ("Share of market volume", percent(whales["whale_volume_share_of_total"], RATIO_SPEC)),
        ("Share of participant volume", percent(whales["whale_volume_share_of_participants"], RATIO_SPEC)),
    ])
    st.caption(
        f"market volume {number(whales['total_market_volume'], VOLUME_SPEC)} · "
        f"participant volume {number(whales['participant_volume'], VOLUME_SPEC)} {symbol} · "
        f"cohorts {count(len(whales['cohorts']))}"
    )
    st.caption(
        "'Whales listed' counts the rows below; the analytics define no whale-count or "
        "active-whale figure, so none is shown."
    )


def _activity(whales: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Whale activity**")
    _table(ACTIVITY_COLUMNS, whales)
    st.caption(
        "One row per observed whale, in the report's order. A whale's share is of whale volume, "
        "as analyze_whale_activity computes it; an unfunded whale trades against external "
        "liquidity, which is what 'funded' distinguishes."
    )


def _outcomes(whales: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Recorded tick outcomes**")
    _table(OUTCOME_COLUMNS, whales)
    st.caption(
        "Each observed tick is recorded as exactly one outcome: traded, blocked by cooldown, "
        "blocked by interval, held at target, no fill, or inactive. They are the simulator's own "
        "classification — a whale that did not fill is not therefore inactive, and a blocked "
        "whale is not therefore idle."
    )


def _behavior(whales: dict[str, Any]) -> None:
    st.markdown("**Behavior**")
    _table(BEHAVIOR_COLUMNS, whales["behaviors"])
    st.caption(
        "Activity grouped by the behavior the simulator recorded for each tick (never inferred "
        "from the size or side of a trade). Per-whale behavior and cycle-phase ticks are in the "
        "outcomes table above."
    )


def _allocation(whales: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Allocation and targets**")
    _table(ALLOCATION_COLUMNS, whales)
    st.caption(
        "Allocation figures are the analytics' own: the coin fraction path and its target come "
        "from analyze_whales, the gap statistics and target-reaching ticks from "
        "analyze_whale_activity. A whale without a target has no allocation record, so its "
        "columns are n/a."
    )


def _cohorts(cohorts: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Cohorts**")
    if not cohorts:
        st.caption(NO_COHORTS_MESSAGE)
        return
    _table(COHORT_COLUMNS, cohorts)
    st.caption("Cohort figures are the report's own group totals.")
    if any(cohort["co_fill"] is not None for cohort in cohorts):
        _table(CO_FILL_COLUMNS, cohorts)
    else:
        st.caption(NO_CO_FILL_MESSAGE)
    st.caption(COFILL_NOTE)


def _detail(whales: Sequence[dict[str, Any]]) -> None:
    st.markdown("**Whale detail**")
    identifiers = [activity["summary"]["whale_id"] for activity in whales]
    selected = st.selectbox("Whale", (ALL_WHALES, *identifiers), key=WHALE_SELECT_KEY)
    if selected == ALL_WHALES:
        st.caption(SELECT_HINT)
        return
    activity = next(
        (row for row in whales if row["summary"]["whale_id"] == selected), None
    )
    if activity is None:  # the payload changed under a stale selection
        st.caption(SELECT_HINT)
        return
    st.table(pd.DataFrame(_detail_rows(activity)).set_index(DETAIL_COLUMNS[0]))
    st.caption(
        "Every figure the whale analytics record for this whale. Selecting a whale filters the "
        "payload already on screen: it runs no simulation and no analytics."
    )


def _detail_rows(activity: dict[str, Any]) -> list[dict[str, str]]:
    summary = activity["summary"]
    label, value = DETAIL_COLUMNS
    rows: list[tuple[str, str]] = [
        *((name, _FORMATTERS[kind](summary[field])) for name, field, kind in SUMMARY_DETAIL),
        *((name, _FORMATTERS[kind](activity[field])) for name, field, kind in ACTIVITY_DETAIL),
        *_record_rows(summary["allocation"], ALLOCATION_DETAIL),
        *_record_rows(activity["allocation_gap"], GAP_DETAIL),
        *_record_rows(activity["target_reaching"], TARGET_DETAIL),
        ("Behavior ticks", _pairs(summary["behavior_ticks"])),
        ("Cycle phase ticks", _pairs(summary["phase_ticks"])),
        *((f"Ticks {outcome}", count(summary["outcome_ticks"].get(outcome)))
          for outcome in TICK_OUTCOMES),
    ]
    return [{label: name, value: shown} for name, shown in rows]


def _record_rows(
    record: dict[str, Any] | None, fields: Sequence[tuple[str, str, str]]
) -> list[tuple[str, str]]:
    """Rows for a nested record the report may not have for this whale."""
    return [
        (name, UNAVAILABLE if record is None else _FORMATTERS[kind](record[field]))
        for name, field, kind in fields
    ]


def _table(
    columns: Sequence[tuple[str, Callable[[dict[str, Any]], str]]],
    rows: Sequence[dict[str, Any]],
) -> None:
    """One row per record, in the report's order, every cell formatted."""
    frame = pd.DataFrame([{header: render(row) for header, render in columns} for row in rows])
    st.dataframe(frame, hide_index=True, width="stretch")
