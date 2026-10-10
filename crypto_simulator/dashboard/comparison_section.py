"""The scenario-comparison views of the dashboard (Phase 20, Step 7).

Display only. The section receives the serialized comparison plan
(``dashboard.data.plan_to_dict``) and the serialized comparison
(``dashboard.data.comparison_to_dict``) and draws them; it runs no
simulation, reads no analytics module and computes no figure. Every count,
mean, median, percentile, minimum and maximum shown is the value
``aggregate_batch`` computed for one configuration's batch.

**Layout:**

    plan          before running: the configurations, how many simulations
                  they make, what is compared and what is held constant, and
                  anything that stops the comparison from running
    summary       per configuration: requested, successful and failed runs,
                  and every failure with its seed and message
    one metric    each configuration's range (minimum to maximum, P5 to P95,
                  P25 to P75, median and mean) side by side, and a table of
                  the same values
    all metrics   the median of every aggregated metric, configuration by
                  configuration, as plain text with no colour scale

**Descriptive only.** Configurations are shown in the order they were
selected, never sorted by a value, ranked or scored. Separate synthetic
batches differ; the section says how they differed and nothing about why,
and nothing about real markets.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.batch_section import DEFAULT_METRIC, ZERO_COUNT_MESSAGE, metric_label
from crypto_simulator.dashboard.formatting import count, number, text
from crypto_simulator.visualization.comparison_charts import (
    COMPARISON_DISCLOSURE,
    ComparisonRange,
    comparison_range_chart,
)

__all__ = [
    "AMM_CONDITION_NOTE",
    "MARKET_CONDITION_DISCLOSURE",
    "METRIC_KEY",
    "NO_COMPARISON_MESSAGE",
    "PRICING_ARCHITECTURE_DISCLOSURE",
    "SECTION_HEADING",
    "SHARED_SEED_DISCLOSURE",
    "render_comparison",
    "render_comparison_plan",
]

SECTION_HEADING = "**Scenario comparison**"
METRIC_KEY = "coin_dashboard_comparison_metric"

NO_COMPARISON_MESSAGE = (
    "No comparison has been run yet. Select the configurations to compare and press 'Run comparison'."
)
SHARED_SEED_DISCLOSURE = (
    "Corresponding runs use the same derived seed when a shared base seed is selected; different "
    "configurations may still consume random streams differently."
)
MARKET_CONDITION_DISCLOSURE = (
    "Market-condition presets are simulator configurations, not forecasts of real market conditions."
)
PRICING_ARCHITECTURE_DISCLOSURE = (
    "RW and AMM are different pricing architectures — a random walk and a constant-product pool — so a "
    "comparison across pricing modes changes the whole price mechanism, not one variable."
)
AMM_CONDITION_NOTE = (
    "In AMM runs a market-condition preset changes only which news arrives and how often; its sentiment "
    "drift applies to the random walk alone, as Phase 17 defines it."
)

_VALUE_SPEC = ",.6g"


def _on_off(value: bool) -> str:
    return "on" if value else "off"


def _held_constant(params: dict[str, Any]) -> str:
    return (
        f"{params['ticks']} ticks · traders {_on_off(params['include_traders'])} · "
        f"whales {_on_off(params['include_whales'])} · news events {_on_off(params['events'])} · "
        f"random news events {_on_off(params['random_events'])} · "
        f"psychology {_on_off(params['psychology'])} · "
        f"whale observation {_on_off(params['whale_observation'])}"
    )


# --- plan ----------------------------------------------------------------------------------------------


def render_comparison_plan(plan: dict[str, Any], *, base_seed: int) -> None:
    """What the selected comparison would run, before it runs."""
    st.markdown(
        f"Configurations: **{plan['configuration_count']}** · Runs per configuration: "
        f"**{text(plan['runs_per_configuration'])}** · Total simulations: {plan['configuration_count']} × "
        f"{text(plan['runs_per_configuration'])} = **{plan['total_runs']}**"
    )
    compared = plan["compared_dimensions"]
    st.caption(
        f"Compared dimensions: {', '.join(compared) if compared else 'none (a single configuration)'}. "
        f"Held constant: {_held_constant(plan['held_constant'])} · shared base seed {base_seed}."
    )
    if plan["labels"]:
        st.markdown("\n".join(f"- {label}" for label in plan["labels"]))
    for problem in plan["problems"]:
        st.warning(problem)


# --- results -------------------------------------------------------------------------------------------


def render_comparison(comparison: dict[str, Any] | None, *, error: str | None = None) -> None:
    """Render a finished comparison, its error, or the empty state."""
    if error is not None:
        st.error(f"Comparison failed. {error}")
        st.caption("No comparison results are shown for a failed comparison.")
        return
    if comparison is None:
        st.info(NO_COMPARISON_MESSAGE)
        return
    groups = comparison["groups"]
    _disclosures(comparison)
    _summary(comparison)
    empty = [group["label"] for group in groups if not group["batch"]["successful_runs"]]
    if empty:
        st.info(f"No successful run, so no aggregate is shown for: {'; '.join(empty)}.")
    successful = [group for group in groups if group["batch"]["successful_runs"]]
    if not successful:
        return
    _one_metric(groups)
    _all_metrics(successful)


def _disclosures(comparison: dict[str, Any]) -> None:
    groups = comparison["groups"]
    notes = [COMPARISON_DISCLOSURE, SHARED_SEED_DISCLOSURE]
    if any(group["market_condition"] is not None for group in groups):
        notes.append(MARKET_CONDITION_DISCLOSURE)
    if "pricing mode" in comparison["compared_dimensions"]:
        notes.append(PRICING_ARCHITECTURE_DISCLOSURE)
    if any(group["pricing_mode"] == "amm" and group["market_condition"] is not None for group in groups):
        notes.append(AMM_CONDITION_NOTE)
    for note in notes:
        st.caption(note)


def _summary(comparison: dict[str, Any]) -> None:
    groups = comparison["groups"]
    compared = comparison["compared_dimensions"]
    st.markdown("*Comparison summary*")
    st.caption(
        f"Compared dimensions: {', '.join(compared) if compared else 'none (a single configuration)'}. "
        f"Held constant: {_held_constant(comparison['held_constant'])} · shared base seed "
        f"{comparison['base_seed']} · {comparison['runs_per_configuration']} runs per configuration."
    )
    st.dataframe(
        pd.DataFrame({
            "Configuration": [group["label"] for group in groups],
            "Pricing mode": [group["pricing_mode"] for group in groups],
            "Manipulation scenario": [text(group["scenario"] or "none") for group in groups],
            "Market condition": [text(group["market_condition"] or "none (neutral)") for group in groups],
            "Base seed": [group["batch"]["base_seed"] for group in groups],
            "Requested runs": [group["batch"]["requested_runs"] for group in groups],
            "Successful runs": [group["batch"]["successful_runs"] for group in groups],
            "Failed runs": [group["batch"]["failed_runs"] for group in groups],
        }),
        hide_index=True,
        key="coin_dashboard_comparison_summary",
    )
    failures = [
        (group["label"], failure) for group in groups for failure in group["batch"]["failures"]
    ]
    if not failures:
        st.success("Every run of every configuration completed.")
        return
    affected = [group["label"] for group in groups if group["batch"]["failed_runs"]]
    st.warning(
        f"Runs failed in {', '.join(affected)}. Failed runs are listed here and contribute no value to "
        "that configuration's aggregate; the configurations do not all rest on the same number of runs."
    )
    st.dataframe(
        pd.DataFrame({
            "Configuration": [label for label, _ in failures],
            "Run index": [failure["index"] for _, failure in failures],
            "Seed": [failure["seed"] for _, failure in failures],
            "Error": [failure["error"] for _, failure in failures],
        }),
        hide_index=True,
        key="coin_dashboard_comparison_failures",
    )


def _entry(group: dict[str, Any], metric: str) -> dict[str, Any]:
    return next(entry for entry in group["batch"]["aggregate"]["metrics"] if entry["metric"] == metric)


def _percentiles(entry: dict[str, Any]) -> dict[int, float | None]:
    return {item["percent"]: item["value"] for item in entry["percentiles"]}


def _one_metric(groups: list[dict[str, Any]]) -> None:
    st.markdown("*One metric across configurations*")
    names = [entry["metric"] for entry in groups[0]["batch"]["aggregate"]["metrics"]]
    chosen = st.selectbox(
        "Aggregated metric",
        names,
        index=names.index(DEFAULT_METRIC),
        format_func=metric_label,
        key=METRIC_KEY,
    )
    label = metric_label(chosen)
    entries = [(group, _entry(group, chosen)) for group in groups]
    drawn = [(group, entry) for group, entry in entries if entry["count"]]
    missing = [group["label"] for group, entry in entries if group["batch"]["successful_runs"] and not entry["count"]]
    if missing:
        st.info(f"{ZERO_COUNT_MESSAGE} Configurations: {'; '.join(missing)}.")
    if drawn:
        ranges = []
        for group, entry in drawn:
            percentiles = _percentiles(entry)
            ranges.append(ComparisonRange(
                label=group["label"], count=entry["count"], minimum=entry["minimum"], p5=percentiles[5],
                p25=percentiles[25], median=entry["median"], p75=percentiles[75], p95=percentiles[95],
                maximum=entry["maximum"], mean=entry["mean"],
            ))
        st.plotly_chart(
            comparison_range_chart(ranges, metric_label=label, title=f"{label} across successful runs, by configuration"),
            width="stretch", theme=None,
        )
    rows = []
    for group, entry in entries:
        percentiles = _percentiles(entry)
        rows.append({
            "Configuration": group["label"],
            "Runs with a value": count(entry["count"]),
            "Median (P50)": number(entry["median"], _VALUE_SPEC),
            "Mean": number(entry["mean"], _VALUE_SPEC),
            "P5": number(percentiles[5], _VALUE_SPEC),
            "P25": number(percentiles[25], _VALUE_SPEC),
            "P75": number(percentiles[75], _VALUE_SPEC),
            "P95": number(percentiles[95], _VALUE_SPEC),
            "Minimum": number(entry["minimum"], _VALUE_SPEC),
            "Maximum": number(entry["maximum"], _VALUE_SPEC),
        })
    st.table(pd.DataFrame(rows).set_index("Configuration"))
    st.caption(
        f"{label} across the successful simulated runs of each configuration, in the order the "
        "configurations were selected. Mean and median (P50) are marked; P5–P95 and P25–P75 are the "
        "observed spread of each batch's runs. A configuration with no value shows n/a."
    )


def _all_metrics(groups: list[dict[str, Any]]) -> None:
    st.markdown("*Median of every aggregated metric*")
    names = [entry["metric"] for entry in groups[0]["batch"]["aggregate"]["metrics"]]
    matrix = pd.DataFrame(
        {group["label"]: [number(_entry(group, name)["median"], _VALUE_SPEC) for name in names] for group in groups},
        index=[metric_label(name) for name in names],
    )
    st.dataframe(matrix, key="coin_dashboard_comparison_matrix")
    st.caption(
        "Median (P50) across each configuration's successful simulated runs, one column per "
        "configuration with at least one successful run. Plain values: no colour scale, no ordering "
        "by value."
    )
