"""Scenario-comparison chart builder (Phase 20, Step 7): every configuration's
given values are drawn in the given order, nothing is sorted or ranked, bad
input is refused, and the figure is deterministic and descriptive."""

import json
import math

import pytest

from crypto_simulator.visualization.comparison_charts import (
    COMPARISON_DISCLOSURE,
    FULL_RANGE_TRACE,
    INNER_SPREAD_TRACE,
    MEAN_TRACE,
    MEDIAN_TRACE,
    OUTER_SPREAD_TRACE,
    ComparisonRange,
    comparison_range_chart,
)

FORBIDDEN = ("better", "worse", "best", "worst", "winner", "outperform", "optimal", "expected", "likely",
             "predict", "forecast", "probability", "odds", "recommend", "rank", "score")


def _range(label, low=0.8, count=10, shift=0.0):
    return ComparisonRange(label=label, count=count, minimum=low + shift, p5=0.85 + shift, p25=0.95 + shift,
                           median=1.0 + shift, p75=1.05 + shift, p95=1.2 + shift, maximum=1.3 + shift,
                           mean=1.02 + shift)


# Deliberately not in value order: the chart must keep this order.
RANGES = (_range("RW | No manipulation | Bull", shift=0.5), _range("RW | No manipulation | Neutral (no preset)"),
          _range("RW | No manipulation | Bear", shift=-0.3))


def _traces(fig):
    return {trace.name: trace for trace in fig.data}


def _chart(ranges=RANGES):
    return comparison_range_chart(ranges, metric_label="Close price", title="Close price across successful runs")


def test_each_band_holds_every_configurations_segment_in_order():
    traces = _traces(_chart())
    assert list(traces) == [FULL_RANGE_TRACE, OUTER_SPREAD_TRACE, INNER_SPREAD_TRACE, MEDIAN_TRACE, MEAN_TRACE]
    for name, low, high in ((FULL_RANGE_TRACE, "minimum", "maximum"), (OUTER_SPREAD_TRACE, "p5", "p95"),
                            (INNER_SPREAD_TRACE, "p25", "p75")):
        expected_x, expected_y = [], []
        for r in RANGES:
            expected_x += [getattr(r, low), getattr(r, high), None]
            expected_y += [r.label, r.label, None]
        assert list(traces[name].x) == expected_x, name
        assert list(traces[name].y) == expected_y, name


def test_median_and_mean_markers_are_the_given_values():
    traces = _traces(_chart())
    assert list(traces[MEDIAN_TRACE].x) == [r.median for r in RANGES]
    assert list(traces[MEAN_TRACE].x) == [r.mean for r in RANGES]
    assert list(traces[MEDIAN_TRACE].y) == [r.label for r in RANGES]


def test_configurations_keep_the_given_order_and_are_not_sorted_by_value():
    fig = _chart()
    assert list(fig.layout.yaxis.categoryarray) == [r.label for r in RANGES]
    assert fig.layout.yaxis.categoryorder == "array"
    assert [r.median for r in RANGES] != sorted(r.median for r in RANGES)


def test_one_configuration_is_drawn():
    fig = _chart((RANGES[0],))
    assert list(_traces(fig)[MEDIAN_TRACE].x) == [RANGES[0].median]


def test_the_title_carries_the_disclosure_and_the_axis_the_metric():
    fig = _chart()
    assert fig.layout.title.text.startswith("Close price across successful runs")
    assert COMPARISON_DISCLOSURE in fig.layout.title.text
    assert fig.layout.xaxis.title.text == "Close price"
    assert fig.layout.yaxis.title.text == "Configuration"


def test_an_empty_or_ambiguous_comparison_is_refused():
    with pytest.raises(ValueError, match="no configuration"):
        _chart(())
    with pytest.raises(ValueError, match="unique"):
        _chart((RANGES[0], RANGES[0]))


@pytest.mark.parametrize("field", ["minimum", "p5", "p25", "median", "p75", "p95", "maximum", "mean"])
@pytest.mark.parametrize("bad", [None, math.nan, -math.inf, True])
def test_a_range_refuses_missing_or_non_finite_values(field, bad):
    values = {**_range("x").__dict__, field: bad}
    with pytest.raises(ValueError, match=field):
        ComparisonRange(**values)


@pytest.mark.parametrize("bad", [0, -2, True, 1.0])
def test_a_range_refuses_a_non_positive_count(bad):
    with pytest.raises(ValueError, match="count"):
        ComparisonRange(**{**_range("x").__dict__, "count": bad})


def test_the_same_input_gives_the_same_figure():
    assert json.loads(_chart().to_json()) == json.loads(_chart().to_json())


def test_no_ranking_or_predictive_wording():
    fig = _chart()
    shown = fig.layout.title.text.replace(COMPARISON_DISCLOSURE, "")
    shown += " ".join(trace.name for trace in fig.data) + fig.layout.xaxis.title.text + fig.layout.yaxis.title.text
    for word in FORBIDDEN:
        assert word not in shown.lower(), word


def test_the_disclosure_is_the_approved_text():
    assert COMPARISON_DISCLOSURE == (
        "These charts compare descriptive statistics from separate batches of synthetic simulations. They "
        "do not establish causal effects, forecasts, or real-market probabilities."
    )
