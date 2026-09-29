"""The batch views section (Phase 20, Step 6), driven through
``streamlit.testing.v1.AppTest`` on real reduced batches.

The section shows the reduced batch as it is: the summary and every failure,
the aggregate's own values for one selected metric with its range chart, and
per-run histograms marked with the aggregate's mean and median. It computes
nothing and imports no analytics.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import crypto_simulator.dashboard.batch_section as batch_section
from crypto_simulator.analytics.aggregate import AGGREGATED_METRICS
from crypto_simulator.dashboard.batch_section import (
    ALL_FAILED_MESSAGE,
    DEFAULT_METRIC,
    METRIC_KEY,
    NO_BATCH_MESSAGE,
    NO_PRICE_PATHS_MESSAGE,
    ONE_RUN_PATH_MESSAGE,
    PRICE_PATH_CAPTION,
    PRICE_PATH_EXTREMES_CAPTION,
    PRICE_PATH_EXTREMES_KEY,
    PRICE_PATH_HEADING,
    ZERO_COUNT_MESSAGE,
    metric_label,
)
from crypto_simulator.dashboard.data import SimulationParams, batch_to_dict, run_dashboard_batch, run_simulation
from crypto_simulator.services.batch import batch_seed
from crypto_simulator.visualization.batch_charts import (
    HISTOGRAM_DISCLOSURE,
    MEAN_TRACE,
    MEDIAN_TRACE,
    PRICE_PATH_DISCLOSURE,
    RANGE_DISCLOSURE,
)

PARAMS = SimulationParams(ticks=15, random_seed=48291)
HISTOGRAM_LABELS = ("Close price", "Cumulative return", "Max drawdown", "Total volume")

FORBIDDEN = ("expected", "likely", "predict", "forecast", "probability", "guarantee", "odds", "outperform",
             "better", "optimal", "best", "worse", "winning", "confidence interval", "caused", "drove")


def _section(batch=None, error=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.batch_section import render_batch

    render_batch(batch, error=error)


def _app(batch=None, error=None) -> AppTest:
    return AppTest.from_function(_section, kwargs={"batch": batch, "error": error}, default_timeout=60).run()


def _failing_on(indices):
    seeds = {batch_seed(PARAMS.random_seed, index) for index in indices}

    def runner(params):
        if params.random_seed in seeds:
            raise RuntimeError(f"seed {params.random_seed} refused")
        return run_simulation(params)

    return runner


@pytest.fixture(scope="module")
def ok():
    return batch_to_dict(run_dashboard_batch(PARAMS, 6))


@pytest.fixture(scope="module")
def mixed():
    return batch_to_dict(run_dashboard_batch(PARAMS, 5, runner=_failing_on({1, 3})))


@pytest.fixture(scope="module")
def all_failed():
    return batch_to_dict(run_dashboard_batch(PARAMS, 3, runner=_failing_on({0, 1, 2})))


def _charts(at):
    return [json.loads(chart.proto.spec) for chart in at.get("plotly_chart")]


def _titles(at):
    return [chart["layout"]["title"]["text"] for chart in _charts(at)]


def _metrics(at):
    return {metric.label: metric.value for metric in at.metric}


def _aggregate_table(at):
    frame = at.table[0].value
    return dict(zip(frame.index, frame["Value"]))


def _entry(batch, metric):
    return next(m for m in batch["aggregate"]["metrics"] if m["metric"] == metric)


def _shown(at):
    parts = [e.value for e in at.markdown] + [e.value for e in at.caption] + [e.value for e in at.info]
    parts += [e.value for e in at.success] + [e.value for e in at.warning]
    parts += _titles(at)
    parts += [trace.get("name", "") for chart in _charts(at) for trace in chart["data"]]
    parts += [a.get("text", "") for chart in _charts(at) for a in chart["layout"].get("annotations", [])]
    text = " ".join(parts)
    # The approved disclosures say what the figures are not, so they name the
    # words the rest of the screen must not use; everything else is scanned.
    approved = (RANGE_DISCLOSURE, HISTOGRAM_DISCLOSURE, PRICE_PATH_DISCLOSURE, PRICE_PATH_EXTREMES_CAPTION)
    captions = [PRICE_PATH_CAPTION.format(n=n) for n in range(1, 11)]
    for disclosure in (*approved, *captions):
        text = text.replace(disclosure, "")
    return text.lower()


# --- empty, error and failure states --------------------------------------------------------------------


def test_no_batch_shows_the_empty_message_and_nothing_else():
    at = _app()
    assert [e.value for e in at.info] == [NO_BATCH_MESSAGE]
    assert at.get("plotly_chart") == [] and at.metric.len == 0 and at.table.len == 0


def test_a_batch_that_could_not_run_shows_its_error_and_no_results():
    at = _app(error="ValueError: runs must be between 1 and 200")
    assert "Batch failed. ValueError: runs must be between 1 and 200" in at.error[0].value
    assert at.get("plotly_chart") == [] and at.metric.len == 0


def test_the_summary_shows_the_run_counts_and_base_seed(ok):
    at = _app(ok)
    assert _metrics(at) == {"Requested runs": "6", "Successful runs": "6", "Failed runs": "0",
                            "Base seed": str(PARAMS.random_seed)}
    assert at.success[0].value == "All 6 requested runs completed."
    assert at.warning.len == 0 and at.dataframe.len == 0
    captions = " ".join(e.value for e in at.caption)
    assert "15 ticks · pricing mode random_walk · manipulation scenario none" in captions
    assert "market condition" not in captions


def test_failures_are_listed_with_index_seed_and_error(mixed):
    at = _app(mixed)
    assert _metrics(at)["Successful runs"] == "3" and _metrics(at)["Failed runs"] == "2"
    assert "2 of 5 requested runs failed" in at.warning[0].value
    assert at.success.len == 0
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["Run index", "Seed", "Error"]
    assert list(frame["Run index"]) == [1, 3]
    assert list(frame["Seed"]) == [batch_seed(PARAMS.random_seed, i) for i in (1, 3)]
    assert list(frame["Error"]) == [f"RuntimeError: seed {batch_seed(PARAMS.random_seed, i)} refused" for i in (1, 3)]


def test_a_mixed_batch_still_draws_its_successful_runs(mixed):
    at = _app(mixed)
    charts = _charts(at)
    assert len(charts) == 6  # range chart, price-path bands (Step 8), four histograms
    histogram = charts[2]["data"][0]
    assert len(histogram["x"]) == 3


def test_an_all_failed_batch_shows_the_summary_and_failures_but_no_aggregate(all_failed):
    at = _app(all_failed)
    assert _metrics(at) == {"Requested runs": "3", "Successful runs": "0", "Failed runs": "3",
                            "Base seed": str(PARAMS.random_seed)}
    assert list(at.dataframe[0].value["Run index"]) == [0, 1, 2]
    assert ALL_FAILED_MESSAGE in [e.value for e in at.info]
    assert at.get("plotly_chart") == [] and at.table.len == 0
    assert at.selectbox.len == 0


# --- aggregate ------------------------------------------------------------------------------------------


def test_the_metric_selector_offers_the_aggregated_metrics(ok):
    at = _app(ok)
    control = at.selectbox(key=METRIC_KEY)
    assert list(control.options) == [metric_label(m) for m in AGGREGATED_METRICS]
    assert control.value == DEFAULT_METRIC == "close_price"


def test_the_aggregate_table_is_the_aggregates_own_values(ok):
    entry = _entry(ok, "close_price")
    percentiles = {p["percent"]: p["value"] for p in entry["percentiles"]}
    table = _aggregate_table(_app(ok))
    spec = ",.6g"
    assert table == {
        "Successful runs with a value": "6",
        "Mean": format(entry["mean"], spec),
        "Median (P50)": format(entry["median"], spec),
        "Standard deviation (sample)": format(entry["standard_deviation"], spec),
        "Minimum": format(entry["minimum"], spec),
        "P5": format(percentiles[5], spec),
        "P25": format(percentiles[25], spec),
        "P75": format(percentiles[75], spec),
        "P95": format(percentiles[95], spec),
        "Maximum": format(entry["maximum"], spec),
    }
    assert percentiles[50] == entry["median"]


def test_the_range_chart_draws_the_aggregates_values(ok):
    entry = _entry(ok, "close_price")
    percentiles = {p["percent"]: p["value"] for p in entry["percentiles"]}
    chart = _charts(_app(ok))[0]
    traces = {t["name"]: t["x"] for t in chart["data"]}
    assert traces == {
        "Minimum to maximum": [entry["minimum"], entry["maximum"]],
        "P5 to P95": [percentiles[5], percentiles[95]],
        "P25 to P75": [percentiles[25], percentiles[75]],
        MEDIAN_TRACE: [entry["median"]],
        MEAN_TRACE: [entry["mean"]],
    }
    assert chart["layout"]["title"]["text"].startswith("Selected metric across successful batch runs: Close price")
    assert RANGE_DISCLOSURE in chart["layout"]["title"]["text"]


def test_selecting_a_metric_redraws_from_the_stored_aggregate(ok):
    at = _app(ok)
    at.selectbox(key=METRIC_KEY).set_value("total_volume").run()
    entry = _entry(ok, "total_volume")
    assert _aggregate_table(at)["Mean"] == format(entry["mean"], ",.6g")
    assert _titles(at)[0].startswith("Selected metric across successful batch runs: Total volume")


def test_the_aggregate_is_described_as_an_observed_spread(ok):
    captions = " ".join(e.value for e in _app(ok).caption)
    assert RANGE_DISCLOSURE in captions
    assert "observed spread across successful simulated runs" in captions
    assert "Mean and median (P50)" in captions


def test_a_metric_no_run_computed_says_so_and_draws_no_range():
    batch = batch_to_dict(run_dashboard_batch(SimulationParams(ticks=1, random_seed=7), 3))
    at = _app(batch)
    at.selectbox(key=METRIC_KEY).set_value("volatility").run()
    assert ZERO_COUNT_MESSAGE in [e.value for e in at.info]
    assert ZERO_COUNT_MESSAGE == "This metric was not computed by any successful run."
    assert not any(t.startswith("Selected metric") for t in _titles(at))


def test_one_run_shows_no_standard_deviation_and_no_spread():
    batch = batch_to_dict(run_dashboard_batch(PARAMS, 1))
    at = _app(batch)
    table = _aggregate_table(at)
    assert table["Standard deviation (sample)"] == "n/a"
    value = batch["runs"][0]["metrics"]["close_price"]
    for row in ("Mean", "Median (P50)", "Minimum", "P5", "P25", "P75", "P95", "Maximum"):
        assert table[row] == format(value, ",.6g")
    assert "standard deviation is undefined" in " ".join(e.value for e in at.caption)


# --- histograms -----------------------------------------------------------------------------------------


def test_the_four_histograms_are_the_runs_own_values_with_aggregate_markers(ok):
    charts = _charts(_app(ok))[2:]  # after the range chart and the price-path bands (Step 8)
    assert len(charts) == 4
    for chart, metric, label in zip(charts, ("close_price", "cumulative_return", "max_drawdown", "total_volume"),
                                    HISTOGRAM_LABELS):
        assert chart["layout"]["title"]["text"].startswith(f"{label}: one value per successful simulated run")
        assert HISTOGRAM_DISCLOSURE in chart["layout"]["title"]["text"]
        assert chart["data"][0]["type"] == "histogram"
        assert chart["data"][0]["x"] == [run["metrics"][metric] for run in ok["runs"]]
        lines = {shape["name"]: shape["x0"] for shape in chart["layout"]["shapes"]}
        entry = _entry(ok, metric)
        assert lines == {MEAN_TRACE: entry["mean"], MEDIAN_TRACE: entry["median"]}


def test_a_histogram_metric_with_no_values_shows_an_empty_state(ok):
    batch = copy.deepcopy(ok)
    for run in batch["runs"]:
        run["metrics"]["max_drawdown"] = None
    entry = _entry(batch, "max_drawdown")
    entry.update(count=0, mean=None, median=None, minimum=None, maximum=None, standard_deviation=None)
    at = _app(batch)
    assert "No successful run recorded a value for max drawdown, so there is no histogram." in [
        e.value for e in at.info]
    assert not any(t.startswith("Max drawdown") for t in _titles(at))
    assert len(_charts(at)) == 5  # range chart, price-path bands, three histograms


def test_the_histograms_are_described_as_simulated_runs(ok):
    captions = " ".join(e.value for e in _app(ok).caption)
    assert HISTOGRAM_DISCLOSURE in captions
    assert "aggregate mean and median (P50)" in captions


# --- vocabulary and structure ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["ok", "mixed", "all_failed", "none"])
def test_no_predictive_or_comparative_wording_on_screen(which, ok, mixed, all_failed):
    batch = {"ok": ok, "mixed": mixed, "all_failed": all_failed, "none": None}[which]
    shown = _shown(_app(batch))
    for word in FORBIDDEN:
        assert word not in shown, word


def _tree():
    return ast.parse(Path(batch_section.__file__).read_text())


def test_the_section_imports_no_analytics_core_or_services():
    imported = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    for module in imported:
        for banned in ("crypto_simulator.analytics", "crypto_simulator.core", "crypto_simulator.services"):
            assert not module.startswith(banned), module


def test_the_section_does_no_arithmetic_and_runs_nothing():
    numeric = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod)
    arithmetic = [
        node for node in ast.walk(_tree())
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, numeric)
    ]
    assert arithmetic == []
    calls = {
        node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        for node in ast.walk(_tree()) if isinstance(node, ast.Call)
    }
    for banned in ("run_batch", "aggregate_batch", "aggregate_values", "run_simulation", "run_dashboard_batch",
                   "sum", "fsum", "mean", "median", "percentile", "stdev", "sorted", "min", "max", "len"):
        assert banned not in calls, banned


# --- price-path bands (Phase 20, Step 8) ----------------------------------------------------------------


def _path_chart(at):
    return next(c for c in _charts(at) if c["layout"]["title"]["text"].startswith("Recorded price across"))


def _path_traces(at):
    return {t["name"]: t for t in _path_chart(at)["data"]}


def test_the_price_path_chart_is_drawn_from_the_stored_bands(ok):
    at = _app(ok)
    bands = ok["price_paths"]
    traces = _path_traces(at)
    assert traces["Median (P50)"]["y"] == bands["median"]
    assert traces["P5 to P95 (lower edge)"]["y"] == bands["p5"]
    assert traces["P5 to P95"]["y"] == bands["p95"]
    assert traces["P25 to P75 (lower edge)"]["y"] == bands["p25"]
    assert traces["P25 to P75"]["y"] == bands["p75"]
    assert all(t["x"] == bands["ticks"] == list(range(1, 16)) for t in traces.values())
    chart = _path_chart(at)
    assert chart["layout"]["title"]["text"].startswith("Recorded price across successful runs, per tick (FIC)")
    assert PRICE_PATH_DISCLOSURE in chart["layout"]["title"]["text"]


def test_the_price_path_chart_sits_between_the_range_chart_and_the_histograms(ok):
    titles = _titles(_app(ok))
    assert titles[0].startswith("Selected metric across successful batch runs")
    assert titles[1].startswith("Recorded price across successful runs, per tick")
    assert titles[2].startswith("Close price: one value per successful simulated run")
    headings = [e.value for e in _app(ok).markdown]
    assert headings.index("*Aggregate across successful runs*") < headings.index(PRICE_PATH_HEADING) < \
        headings.index("*Per-run distributions*")


def test_the_caption_is_the_approved_text_with_the_run_count(ok):
    captions = [e.value for e in _app(ok).caption]
    assert PRICE_PATH_CAPTION.format(n=6) in captions
    assert PRICE_PATH_CAPTION.format(n=6).startswith(
        "At each tick, the line is the median of the recorded prices of the 6 successful runs of this "
        "configuration, the darker band spans their P25 to P75 and the lighter band their P5 to P95.")
    assert not any("requested runs; the failed runs" in c for c in captions)


def test_a_batch_with_failures_says_how_many_runs_the_bands_use(mixed):
    captions = [e.value for e in _app(mixed).caption]
    assert PRICE_PATH_CAPTION.format(n=3) in captions
    assert ("The bands use 3 of 5 requested runs; the failed runs are listed in the summary and contribute "
            "nothing here.") in captions
    assert "3 successful runs" in _path_traces(_app(mixed))["Median (P50)"]["hovertemplate"]


def test_extremes_are_off_until_the_checkbox_is_ticked_and_only_redraw(ok):
    at = _app(ok)
    assert at.checkbox(key=PRICE_PATH_EXTREMES_KEY).value is False
    assert "Minimum across runs" not in _path_traces(at)
    assert PRICE_PATH_EXTREMES_CAPTION not in [e.value for e in at.caption]
    at.checkbox(key=PRICE_PATH_EXTREMES_KEY).check().run()
    traces = _path_traces(at)
    assert traces["Minimum across runs"]["y"] == ok["price_paths"]["minimum"]
    assert traces["Maximum across runs"]["y"] == ok["price_paths"]["maximum"]
    assert PRICE_PATH_EXTREMES_CAPTION in [e.value for e in at.caption]


def test_the_mean_is_stored_but_not_drawn(ok):
    at = _app(ok)
    at.checkbox(key=PRICE_PATH_EXTREMES_KEY).check().run()
    drawn = [t["y"] for t in _path_chart(at)["data"]]
    assert ok["price_paths"]["mean"] not in drawn


def test_one_successful_run_says_the_bands_are_its_path():
    batch = batch_to_dict(run_dashboard_batch(PARAMS, 1))
    at = _app(batch)
    assert ONE_RUN_PATH_MESSAGE in [e.value for e in at.info]
    assert ONE_RUN_PATH_MESSAGE == "One successful run: the bands coincide with its recorded path."
    traces = _path_traces(at)
    assert traces["P5 to P95"]["y"] == traces["Median (P50)"]["y"] == traces["P25 to P75 (lower edge)"]["y"]


def test_no_one_run_message_with_more_runs(ok):
    assert ONE_RUN_PATH_MESSAGE not in [e.value for e in _app(ok).info]


def test_an_all_failed_batch_has_no_price_path_view(all_failed):
    at = _app(all_failed)
    assert PRICE_PATH_HEADING not in [e.value for e in at.markdown]
    assert at.checkbox.len == 0


def test_a_batch_without_bands_says_so(ok):
    batch = copy.deepcopy(ok)
    batch["price_paths"] = None
    at = _app(batch)
    assert NO_PRICE_PATHS_MESSAGE in [e.value for e in at.info]
    assert not any(t.startswith("Recorded price across") for t in _titles(at))


def test_the_section_builds_no_price_path_statistics():
    calls = {node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
             for node in ast.walk(_tree()) if isinstance(node, ast.Call)}
    assert "aggregate_price_paths" not in calls
    assert "crypto_simulator.analytics" not in Path(batch_section.__file__).read_text()
