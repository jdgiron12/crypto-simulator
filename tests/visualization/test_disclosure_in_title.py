"""``disclosure_in_title`` on the batch and comparison chart builders
(Phase 24, Step 5).

The default keeps every figure exactly as before, disclosure subtitle
included. ``False`` leaves the title as given and changes nothing else:
the traces, shapes and every other layout value are the same figure's.
"""

from __future__ import annotations

import pytest

from crypto_simulator.visualization.batch_charts import (
    HISTOGRAM_DISCLOSURE,
    PRICE_PATH_DISCLOSURE,
    RANGE_DISCLOSURE,
    aggregate_range_chart,
    price_path_band_chart,
    run_histogram_chart,
)
from crypto_simulator.visualization.comparison_charts import (
    COMPARISON_DISCLOSURE,
    ComparisonRange,
    comparison_range_chart,
)

RANGE = {"label": "Close price", "minimum": 0.8, "p5": 0.85, "p25": 0.95, "median": 1.0, "p75": 1.05,
         "p95": 1.15, "maximum": 1.2, "mean": 1.01, "count": 12, "title": "Close price across runs"}
BANDS = {"runs": 3, "minimum": [1.0, 0.9], "p5": [1.0, 0.92], "p25": [1.0, 0.95], "median": [1.0, 1.0],
         "p75": [1.0, 1.05], "p95": [1.0, 1.08], "maximum": [1.0, 1.1]}
RANGES = [ComparisonRange(label=label, count=4, minimum=0.8, p5=0.85, p25=0.9, median=1.0, p75=1.1, p95=1.15,
                          maximum=1.2, mean=1.0) for label in ("A", "B")]

CASES = {
    "range": (lambda **kw: aggregate_range_chart(**RANGE, **kw), RANGE_DISCLOSURE, RANGE["title"]),
    "histogram": (lambda **kw: run_histogram_chart([1.0, 2.0, 2.5], label="x", mean=1.8, median=2.0,
                                                   title="x: one value per run", **kw),
                  HISTOGRAM_DISCLOSURE, "x: one value per run"),
    "price paths": (lambda **kw: price_path_band_chart([1, 2], BANDS, title="FIC price per tick", **kw),
                    PRICE_PATH_DISCLOSURE, "FIC price per tick"),
    "comparison": (lambda **kw: comparison_range_chart(RANGES, metric_label="Close price",
                                                       title="Close price by configuration", **kw),
                   COMPARISON_DISCLOSURE, "Close price by configuration"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_default_keeps_the_disclosure_in_the_title(name):
    build, disclosure, title = CASES[name]
    shown = build().layout.title.text
    assert shown.startswith(f"{title}<br><sup>{disclosure}")
    assert build(disclosure_in_title=True).to_plotly_json() == build().to_plotly_json()


@pytest.mark.parametrize("name", list(CASES))
def test_leaving_the_disclosure_out_changes_only_the_title(name):
    build, disclosure, title = CASES[name]
    default, plain = build().to_plotly_json(), build(disclosure_in_title=False).to_plotly_json()
    assert plain["layout"]["title"]["text"] == title
    assert disclosure not in plain["layout"]["title"]["text"]
    assert plain["data"] == default["data"]
    default["layout"]["title"].pop("text")
    plain["layout"]["title"].pop("text")
    assert plain["layout"] == default["layout"]
