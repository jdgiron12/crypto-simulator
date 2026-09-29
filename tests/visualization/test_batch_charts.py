"""Batch chart builders (Phase 20, Step 6): every value drawn is the one
handed in, the reference markers are the aggregate's, empty and non-finite
inputs are refused, and the figures are deterministic and descriptive."""

import copy
import json
import math

import pytest

from crypto_simulator.visualization.batch_charts import (
    FULL_RANGE_TRACE,
    HISTOGRAM_DISCLOSURE,
    INNER_SPREAD_TRACE,
    MEAN_TRACE,
    MEDIAN_TRACE,
    OUTER_SPREAD_TRACE,
    RANGE_DISCLOSURE,
    RUNS_TRACE,
    aggregate_range_chart,
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
