"""The batch views of the dashboard (Phase 20, Step 6).

Display only. The section receives the serialized reduced batch
(``dashboard.data.batch_to_dict``) and draws it; it runs no simulation, reads
no analytics module and computes no figure. Every count, mean, median,
percentile, minimum and maximum shown is ``aggregate_batch``'s own value, and
the histograms are drawn over the per-run values ``reduce_batch`` kept.

**Layout** (one reduced batch):

    summary        what was run; requested, successful and failed runs;
                   the base seed; every failure with its seed and message
    aggregate      one aggregated metric at a time: the aggregate's values
                   and a range chart (minimum to maximum, P5 to P95, P25 to
                   P75, median and mean)
    price paths    the recorded price at each tick across the successful
                   runs (Step 8): P5 to P95 and P25 to P75 bands and the
                   median line, with the minimum and maximum on request
    distributions  per-run histograms of close price, cumulative return,
                   maximum drawdown and total volume

**One configuration.** A batch is one request run under seeds derived from
one base seed, so the section describes how those simulated runs were spread.
It compares nothing with anything and says nothing about real markets.

**Missing stays missing.** A failed run is listed and contributes nothing
else; a metric no successful run computed says so rather than showing zeros;
a batch with no successful run shows its summary and failures only.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from crypto_simulator.dashboard.data import BATCH_HISTOGRAM_METRICS
from crypto_simulator.dashboard.formatting import count, number, text
from crypto_simulator.dashboard.metric_row import render_metric_row
from crypto_simulator.dashboard.notes import render_notes
from crypto_simulator.visualization.batch_charts import (
    HISTOGRAM_DISCLOSURE,
    PRICE_PATH_DISCLOSURE,
    RANGE_DISCLOSURE,
    aggregate_range_chart,
    price_path_band_chart,
    run_histogram_chart,
)

__all__ = [
    "ALL_FAILED_MESSAGE",
    "DEFAULT_METRIC",
    "METRIC_KEY",
    "NO_BATCH_MESSAGE",
    "NO_PRICE_PATHS_MESSAGE",
    "ONE_RUN_PATH_MESSAGE",
    "PRICE_PATH_CAPTION",
    "PRICE_PATH_EXTREMES_CAPTION",
    "PRICE_PATH_EXTREMES_KEY",
    "PRICE_PATH_HEADING",
    "SECTION_HEADING",
    "ZERO_COUNT_MESSAGE",
    "metric_label",
    "render_batch",
]

SECTION_HEADING = "**Batch runs**"
METRIC_KEY = "coin_dashboard_batch_metric"
DEFAULT_METRIC = "close_price"

NO_BATCH_MESSAGE = (
    "No batch has been run yet. Choose a number of runs and press 'Run batch' to run the "
    "run setup from the sidebar under derived seeds."
)
ALL_FAILED_MESSAGE = (
    "Every run in this batch failed, so there are no aggregate values or distributions to show."
)
ZERO_COUNT_MESSAGE = "This metric was not computed by any successful run."

PRICE_PATH_HEADING = "*Price paths across runs*"
PRICE_PATH_EXTREMES_KEY = "coin_dashboard_batch_path_extremes"
PRICE_PATH_CAPTION = (
    "At each tick, the line is the median of the recorded prices of the {n} successful runs of this "
    "configuration, the darker band spans their P25 to P75 and the lighter band their P5 to P95. Each tick "
    "is summarized on its own: the median line and the band edges are not the path of any single run. "
    "These are synthetic simulation outputs describing how this configuration's runs varied, not a "
    "prediction, a confidence interval or a statement about real prices."
)
PRICE_PATH_EXTREMES_CAPTION = (
    "Dotted lines are the lowest and highest recorded price at each tick across the successful runs."
)
ONE_RUN_PATH_MESSAGE = "One successful run: the bands coincide with its recorded path."
NO_PRICE_PATHS_MESSAGE = "No price-path bands were recorded for this batch."

#: Values of different metrics range from fractions to millions; one
#: general spec shows each to six significant figures without scaling it.
_VALUE_SPEC = ",.6g"


def metric_label(metric: str) -> str:
    """An aggregated metric's name, for display: ``close_price`` is
    ``Close price``."""
    return metric.replace("_", " ").capitalize()


def render_batch(batch: dict[str, Any] | None, *, error: str | None = None) -> None:
    """Render a reduced batch, the batch's error, or the empty state."""
    if error is not None:
        st.error(f"Batch failed. {error}")
        st.caption("No batch results are shown for a failed batch.")
        return
    if batch is None:
        st.info(NO_BATCH_MESSAGE)
        return
    _summary(batch)
    if not batch["successful_runs"]:
        st.info(ALL_FAILED_MESSAGE)
        return
    metrics = {entry["metric"]: entry for entry in batch["aggregate"]["metrics"]}
    _aggregate(metrics)
    _price_paths(batch)
    _distributions(batch["runs"], metrics)


def _summary(batch: dict[str, Any]) -> None:
    params = batch["params"]
    st.markdown("*Batch summary*")
    configuration = (
        f"{params['ticks']} ticks · pricing mode {params['pricing_mode']} · "
        f"manipulation scenario {text(params['scenario'] or 'none')}"
    )
    if params["market_condition"] is not None:
        configuration = f"{configuration} · market condition {params['market_condition']}"
    st.caption(
        f"One configuration ({configuration}) run under seeds derived from the base seed, "
        "one seed per run."
    )
    render_metric_row([
        ("Requested runs", count(batch["requested_runs"])),
        ("Successful runs", count(batch["successful_runs"])),
        ("Failed runs", count(batch["failed_runs"])),
        ("Base seed", text(batch["base_seed"])),
    ])
    failures = batch["failures"]
    if not failures:
        st.success(f"All {batch['requested_runs']} requested runs completed.")
        return
    st.warning(
        f"{batch['failed_runs']} of {batch['requested_runs']} requested runs failed. They are listed "
        "here and contribute no value to the aggregate or the distributions."
    )
    st.dataframe(
        pd.DataFrame({
            "Run index": [failure["index"] for failure in failures],
            "Seed": [failure["seed"] for failure in failures],
            "Error": [failure["error"] for failure in failures],
        }),
        hide_index=True,
    )


def _aggregate(metrics: dict[str, dict[str, Any]]) -> None:
    st.markdown("*Aggregate across successful runs*")
    names = list(metrics)
    chosen = st.selectbox(
        "Aggregated metric",
        names,
        index=names.index(DEFAULT_METRIC),
        format_func=metric_label,
        key=METRIC_KEY,
    )
    entry = metrics[chosen]
    if not entry["count"]:
        st.info(ZERO_COUNT_MESSAGE)
        return
    percentiles = {item["percent"]: item["value"] for item in entry["percentiles"]}
    rows = (
        ("Successful runs with a value", count(entry["count"])),
        ("Mean", number(entry["mean"], _VALUE_SPEC)),
        ("Median (P50)", number(entry["median"], _VALUE_SPEC)),
        ("Standard deviation (sample)", number(entry["standard_deviation"], _VALUE_SPEC)),
        ("Minimum", number(entry["minimum"], _VALUE_SPEC)),
        ("P5", number(percentiles[5], _VALUE_SPEC)),
        ("P25", number(percentiles[25], _VALUE_SPEC)),
        ("P75", number(percentiles[75], _VALUE_SPEC)),
        ("P95", number(percentiles[95], _VALUE_SPEC)),
        ("Maximum", number(entry["maximum"], _VALUE_SPEC)),
    )
    st.table(pd.DataFrame(rows, columns=["Aggregate", "Value"]).set_index("Aggregate"))
    label = metric_label(chosen)
    st.plotly_chart(
        aggregate_range_chart(
            label=label,
            minimum=entry["minimum"],
            p5=percentiles[5],
            p25=percentiles[25],
            median=entry["median"],
            p75=percentiles[75],
            p95=percentiles[95],
            maximum=entry["maximum"],
            mean=entry["mean"],
            count=entry["count"],
            title=f"{label} across successful runs",
            disclosure_in_title=False,
        ),
        width="stretch", theme=None,
    )
    undefined = (
        " The standard deviation is undefined with fewer than two values, so it is shown as n/a."
        if entry["standard_deviation"] is None
        else ""
    )
    runs = "run" if entry["count"] == 1 else "runs"
    st.caption(f"{RANGE_DISCLOSURE} {entry['count']} successful {runs}.")
    render_notes(
        "Mean and median (P50) are marked on the chart; the P5–P95 spread is the observed spread "
        "across successful simulated runs, with P25–P75 inside it. Percentiles use linear "
        f"interpolation between the sorted run values.{undefined}"
    )


def _price_paths(batch: dict[str, Any]) -> None:
    """The stored per-tick bands; the extremes checkbox only redraws them."""
    st.markdown(PRICE_PATH_HEADING)
    bands = batch["price_paths"]
    if bands is None:
        st.info(NO_PRICE_PATHS_MESSAGE)
        return
    show_extremes = st.checkbox(
        "Show minimum and maximum across runs", value=False, key=PRICE_PATH_EXTREMES_KEY
    )
    symbol = batch["coin_symbol"]
    st.plotly_chart(
        price_path_band_chart(
            bands["ticks"],
            bands,
            title=f"Recorded {symbol} price per tick, across runs",
            show_extremes=show_extremes,
            disclosure_in_title=False,
        ),
        width="stretch", theme=None,
    )
    st.caption(PRICE_PATH_DISCLOSURE)
    if batch["failed_runs"]:
        st.caption(
            f"The bands use {batch['successful_runs']} of {batch['requested_runs']} requested runs; the "
            "failed runs are listed in the summary and contribute nothing here."
        )
    if bands["runs"] == 1:
        st.info(ONE_RUN_PATH_MESSAGE)
    if show_extremes:
        st.caption(PRICE_PATH_EXTREMES_CAPTION)
    render_notes(PRICE_PATH_CAPTION.format(n=bands["runs"]))


def _distributions(runs: list[dict[str, Any]], metrics: dict[str, dict[str, Any]]) -> None:
    st.markdown("*Per-run distributions*")
    st.caption(
        f"{HISTOGRAM_DISCLOSURE} Each bar counts the successful runs whose value falls in its bin; the "
        "lines mark the aggregate mean and median (P50)."
    )
    for metric in BATCH_HISTOGRAM_METRICS:
        entry = metrics[metric]
        label = metric_label(metric)
        if not entry["count"]:
            st.info(f"No successful run recorded a value for {label.lower()}, so there is no histogram.")
            continue
        st.plotly_chart(
            run_histogram_chart(
                [run["metrics"][metric] for run in runs],
                label=label,
                mean=entry["mean"],
                median=entry["median"],
                title=f"{label}: one value per run",
                disclosure_in_title=False,
            ),
            width="stretch", theme=None,
        )
