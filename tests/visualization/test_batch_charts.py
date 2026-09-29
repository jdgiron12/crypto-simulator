"""Batch chart builders (Phase 20, Steps 6 and 8): every value drawn is the
one handed in, the reference markers are the aggregate's, the price-path
bands are the per-tick values given, empty and non-finite inputs are refused,
and the figures are deterministic and descriptive."""

import copy
import json
import math

import pytest

from crypto_simulator.analytics.price_paths import PricePathBands
from crypto_simulator.visualization.batch_charts import (
    FULL_RANGE_TRACE,
    HISTOGRAM_DISCLOSURE,
    INNER_SPREAD_TRACE,
    MAXIMUM_TRACE,
    MEAN_TRACE,
    MEDIAN_TRACE,
    MINIMUM_TRACE,
    OUTER_SPREAD_TRACE,
    PRICE_PATH_DISCLOSURE,
    RANGE_DISCLOSURE,
    RUNS_TRACE,
    aggregate_range_chart,
    price_path_band_chart,
    run_histogram_chart,
)

RANGE = dict(label="Close price", minimum=0.8, p5=0.85, p25=0.95, median=1.0, p75=1.05, p95=1.2,
             maximum=1.3, mean=1.02, count=12, title="Selected metric across successful batch runs: Close price")
VALUES = [1.0, 0.9, None, 1.2, 1.1, 0.95]

FORBIDDEN = ("expected", "likely", "predict", "guarantee", "odds", "outperform", "better", "optimal",
             "best", "worse", "winning", "confidence")


def _spec(fig):
    return json.loads(fig.to_json())


def _traces(fig):
    return {trace.name: trace for trace in fig.data}


# --- range chart ----------------------------------------------------------------------------------------


def test_the_range_chart_draws_every_given_value_in_its_own_trace():
    traces = _traces(aggregate_range_chart(**RANGE))
    assert list(traces) == [FULL_RANGE_TRACE, OUTER_SPREAD_TRACE, INNER_SPREAD_TRACE, MEDIAN_TRACE, MEAN_TRACE]
    assert list(traces[FULL_RANGE_TRACE].x) == [0.8, 1.3]
    assert list(traces[OUTER_SPREAD_TRACE].x) == [0.85, 1.2]
    assert list(traces[INNER_SPREAD_TRACE].x) == [0.95, 1.05]
    assert list(traces[MEDIAN_TRACE].x) == [1.0]
    assert list(traces[MEAN_TRACE].x) == [1.02]
    assert all(set(trace.y) == {"Close price"} for trace in traces.values())


def test_the_range_chart_title_carries_the_disclosure_and_the_run_count():
    fig = aggregate_range_chart(**RANGE)
    assert fig.layout.title.text.startswith(RANGE["title"])
    assert RANGE_DISCLOSURE in fig.layout.title.text
    assert "12 successful runs." in fig.layout.title.text
    assert fig.layout.xaxis.title.text == "Close price"
    one = aggregate_range_chart(**{**RANGE, "count": 1})
    assert "1 successful run." in one.layout.title.text


def test_one_run_collapses_every_range_to_its_value():
    single = dict(RANGE, minimum=2.0, p5=2.0, p25=2.0, median=2.0, p75=2.0, p95=2.0, maximum=2.0, mean=2.0,
                  count=1)
    for trace in aggregate_range_chart(**single).data:
        assert set(trace.x) == {2.0}


@pytest.mark.parametrize("name", ["minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"])
@pytest.mark.parametrize("bad", [None, math.nan, math.inf, True])
def test_the_range_chart_refuses_missing_or_non_finite_values(name, bad):
    with pytest.raises(ValueError, match=name):
        aggregate_range_chart(**{**RANGE, name: bad})


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_the_range_chart_refuses_a_non_positive_count(bad):
    with pytest.raises(ValueError, match="count"):
        aggregate_range_chart(**{**RANGE, "count": bad})


# --- histogram ------------------------------------------------------------------------------------------


def test_the_histogram_draws_one_value_per_run_and_leaves_out_missing_ones():
    fig = run_histogram_chart(VALUES, label="Close price", mean=1.03, median=1.0, title="Close price")
    assert len(fig.data) == 1
    assert fig.data[0].type == "histogram"
    assert fig.data[0].name == RUNS_TRACE
    assert list(fig.data[0].x) == [1.0, 0.9, 1.2, 1.1, 0.95]


def test_the_histogram_marks_the_given_mean_and_median():
    fig = run_histogram_chart(VALUES, label="Close price", mean=1.03, median=1.0, title="Close price")
    lines = {shape.name: shape for shape in fig.layout.shapes}
    assert set(lines) == {MEAN_TRACE, MEDIAN_TRACE}
    assert lines[MEAN_TRACE].x0 == lines[MEAN_TRACE].x1 == 1.03
    assert lines[MEDIAN_TRACE].x0 == lines[MEDIAN_TRACE].x1 == 1.0
    assert {a.text for a in fig.layout.annotations} == {MEAN_TRACE, MEDIAN_TRACE}


def test_the_histogram_labels_its_axes_and_carries_the_disclosure():
    fig = run_histogram_chart(VALUES, label="Total volume", mean=1.0, median=1.0, title="Total volume")
    assert fig.layout.xaxis.title.text == "Total volume"
    assert fig.layout.yaxis.title.text == "Successful simulated runs"
    assert HISTOGRAM_DISCLOSURE in fig.layout.title.text


def test_a_histogram_of_one_run_is_drawn():
    fig = run_histogram_chart([0.5], label="Max drawdown", mean=0.5, median=0.5, title="t")
    assert list(fig.data[0].x) == [0.5]


@pytest.mark.parametrize("values", [[], [None, None]])
def test_a_histogram_with_no_value_is_refused(values):
    with pytest.raises(ValueError, match="no run recorded"):
        run_histogram_chart(values, label="Close price", mean=1.0, median=1.0, title="t")


@pytest.mark.parametrize("kwargs", [
    {"values": [1.0, math.nan]},
    {"values": [1.0, "1.0"]},
    {"mean": None},
    {"median": math.inf},
])
def test_the_histogram_refuses_non_finite_input(kwargs):
    arguments = {"values": [1.0, 2.0], "label": "x", "mean": 1.5, "median": 1.5, "title": "t", **kwargs}
    values = arguments.pop("values")
    with pytest.raises(ValueError):
        run_histogram_chart(values, **arguments)


# --- determinism, purity, vocabulary --------------------------------------------------------------------


def test_the_same_input_gives_the_same_figure_and_is_not_mutated():
    values = list(VALUES)
    before = copy.deepcopy(values)
    first = _spec(run_histogram_chart(values, label="x", mean=1.0, median=1.0, title="t"))
    second = _spec(run_histogram_chart(values, label="x", mean=1.0, median=1.0, title="t"))
    assert first == second
    assert values == before
    assert _spec(aggregate_range_chart(**RANGE)) == _spec(aggregate_range_chart(**RANGE))


def test_no_predictive_wording_in_either_figure():
    figures = [aggregate_range_chart(**RANGE), run_histogram_chart(VALUES, label="x", mean=1, median=1, title="t")]
    for fig in figures:
        shown = fig.layout.title.text.replace(RANGE_DISCLOSURE, "").replace(HISTOGRAM_DISCLOSURE, "")
        shown += " ".join(trace.name or "" for trace in fig.data)
        shown += " ".join(a.text for a in fig.layout.annotations)
        for word in FORBIDDEN + ("forecast", "probability"):
            assert word not in shown.lower(), word


def test_the_disclosures_say_what_the_figures_are_not():
    assert RANGE_DISCLOSURE == (
        "Descriptive spread of successful simulated runs; not a forecast or real-market probability."
    )
    assert "not a real-market probability distribution" in HISTOGRAM_DISCLOSURE
    for disclosure in (RANGE_DISCLOSURE, HISTOGRAM_DISCLOSURE):
        for word in FORBIDDEN:
            assert word not in disclosure.lower(), word


# --- price-path bands (Phase 20, Step 8) ----------------------------------------------------------------

BANDS = {
    "runs": 7,
    "ticks": [1, 2, 3],
    "minimum": [0.80, 0.70, 0.60],
    "p5": [0.85, 0.75, 0.70],
    "p25": [0.95, 0.90, 0.88],
    "median": [1.00, 1.01, 1.02],
    "p75": [1.05, 1.10, 1.15],
    "p95": [1.15, 1.25, 1.35],
    "maximum": [1.20, 1.40, 1.60],
    "mean": [1.00, 1.02, 1.05],
}


def _path_chart(bands=BANDS, **kwargs):
    return price_path_band_chart(bands["ticks"], bands, title="Recorded price across successful runs, per tick",
                                 **kwargs)


def _by_name(fig):
    return {trace.name: trace for trace in fig.data}


def test_the_outer_band_is_filled_between_p5_and_p95():
    traces = _by_name(_path_chart())
    lower, upper = traces[f"{OUTER_SPREAD_TRACE} (lower edge)"], traces[OUTER_SPREAD_TRACE]
    assert list(lower.y) == BANDS["p5"] and list(upper.y) == BANDS["p95"]
    assert upper.fill == "tonexty" and lower.fill is None
    names = [trace.name for trace in _path_chart().data]
    assert names.index(OUTER_SPREAD_TRACE) == names.index(f"{OUTER_SPREAD_TRACE} (lower edge)") + 1


def test_the_inner_band_is_filled_between_p25_and_p75():
    traces = _by_name(_path_chart())
    assert list(traces[f"{INNER_SPREAD_TRACE} (lower edge)"].y) == BANDS["p25"]
    assert list(traces[INNER_SPREAD_TRACE].y) == BANDS["p75"]
    assert traces[INNER_SPREAD_TRACE].fill == "tonexty"


def test_the_median_line_is_the_median_and_every_trace_is_on_the_ticks():
    fig = _path_chart()
    median = _by_name(fig)[MEDIAN_TRACE]
    assert list(median.y) == BANDS["median"]
    assert median.mode == "lines"
    assert all(list(trace.x) == BANDS["ticks"] for trace in fig.data)
    assert fig.layout.xaxis.title.text == "Simulation tick"
    assert fig.layout.yaxis.title.text == "Recorded price"


def test_extremes_are_hidden_by_default_and_the_mean_is_never_drawn():
    fig = _path_chart()
    names = [trace.name for trace in fig.data]
    assert MINIMUM_TRACE not in names and MAXIMUM_TRACE not in names
    assert len(fig.data) == 5
    drawn = [list(trace.y) for trace in fig.data]
    assert BANDS["mean"] not in drawn
    assert all("mean" not in (trace.name or "").lower() for trace in fig.data)


def test_extremes_are_dotted_lines_when_requested():
    fig = _path_chart(show_extremes=True)
    traces = _by_name(fig)
    assert list(traces[MINIMUM_TRACE].y) == BANDS["minimum"]
    assert list(traces[MAXIMUM_TRACE].y) == BANDS["maximum"]
    assert traces[MINIMUM_TRACE].line.dash == traces[MAXIMUM_TRACE].line.dash == "dot"
    assert len(fig.data) == 7


def test_the_median_hover_carries_every_band_value_and_the_run_count():
    median = _by_name(_path_chart())[MEDIAN_TRACE]
    assert [list(row) for row in median.customdata] == [
        [BANDS["p5"][i], BANDS["p25"][i], BANDS["median"][i], BANDS["p75"][i], BANDS["p95"][i]] for i in range(3)]
    for label in ("Tick", "P5", "P25", "Median (P50)", "P75", "P95", "7 successful runs"):
        assert label in median.hovertemplate
    assert "Minimum" not in median.hovertemplate
    extended = _by_name(_path_chart(show_extremes=True))[MEDIAN_TRACE]
    assert "Minimum" in extended.hovertemplate and "Maximum" in extended.hovertemplate
    assert [list(row)[5:] for row in extended.customdata] == [
        [BANDS["minimum"][i], BANDS["maximum"][i]] for i in range(3)]


def test_a_one_run_chart_says_run():
    one = {**BANDS, "runs": 1}
    assert "1 successful run<" in _by_name(_path_chart(one))[MEDIAN_TRACE].hovertemplate


def test_the_title_carries_the_disclosure():
    fig = _path_chart()
    assert fig.layout.title.text.startswith("Recorded price across successful runs, per tick")
    assert PRICE_PATH_DISCLOSURE in fig.layout.title.text
    assert PRICE_PATH_DISCLOSURE == (
        "Per-tick spread of recorded prices across successful simulated runs of one configuration; not a "
        "forecast or real-market probability.")


def test_a_price_path_bands_object_draws_the_same_figure():
    bands = PricePathBands(**{k: (tuple(v) if isinstance(v, list) else v) for k, v in BANDS.items()})
    assert _spec(price_path_band_chart(bands.ticks, bands, title="t")) == _spec(
        price_path_band_chart(BANDS["ticks"], BANDS, title="t"))


@pytest.mark.parametrize("column", ["minimum", "p5", "p25", "median", "p75", "p95", "maximum"])
def test_mismatched_lengths_are_refused(column):
    with pytest.raises(ValueError, match=f"{column} has 2 values for 3 ticks"):
        _path_chart({**BANDS, column: BANDS[column][:2]})


@pytest.mark.parametrize("bad", [math.nan, math.inf, None])
def test_non_finite_band_values_are_refused(bad):
    with pytest.raises(ValueError, match=r"p25\[1\]"):
        _path_chart({**BANDS, "p25": [0.95, bad, 0.88]})


@pytest.mark.parametrize("runs", [0, -1, True, 2.0, None])
def test_the_run_count_must_be_positive(runs):
    with pytest.raises(ValueError, match="runs"):
        _path_chart({**BANDS, "runs": runs})


def test_empty_ticks_or_missing_columns_are_refused():
    with pytest.raises(ValueError, match="no ticks"):
        price_path_band_chart([], BANDS, title="t")
    with pytest.raises(ValueError, match="bands has no 'p95'"):
        _path_chart({k: v for k, v in BANDS.items() if k != "p95"})


def test_the_band_chart_is_deterministic_and_does_not_mutate_its_input():
    bands = copy.deepcopy(BANDS)
    first = _spec(_path_chart(bands, show_extremes=True))
    assert _spec(_path_chart(bands, show_extremes=True)) == first
    assert bands == BANDS


def test_no_predictive_or_ranking_wording_in_the_band_chart():
    fig = _path_chart(show_extremes=True)
    shown = fig.layout.title.text.replace(PRICE_PATH_DISCLOSURE, "")
    shown += " ".join(trace.name or "" for trace in fig.data)
    shown += " ".join(trace.hovertemplate or "" for trace in fig.data)
    for word in FORBIDDEN + ("forecast", "probability", "future", "rank", "winner"):
        assert word not in shown.lower(), word
