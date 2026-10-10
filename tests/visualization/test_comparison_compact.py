"""``compact`` on the comparison chart builder (Phase 24, Step 6).

The default leaves the figure as before. ``compact`` lays it out for a
narrow page — a bottom legend, one compared dimension per tick line and
room for the legend — and changes nothing else: every trace, value and
configuration, and the category order, are the same figure's.
"""

from __future__ import annotations

import pytest

from crypto_simulator.visualization.comparison_charts import (
    BOTTOM_LEGEND,
    LABEL_SEPARATOR,
    LEGEND_ALLOWANCE,
    ComparisonRange,
    comparison_range_chart,
    stacked_label,
)

LABELS = ("RW | Pump & dump | Neutral (no preset)", "AMM | No manipulation | Bull", "AMM | Wash trading | Meme")
RANGES = [ComparisonRange(label=label, count=4, minimum=0.8 + i, p5=0.85 + i, p25=0.9 + i, median=1.0 + i,
                          p75=1.1 + i, p95=1.15 + i, maximum=1.2 + i, mean=1.01 + i)
          for i, label in enumerate(LABELS)]


def _chart(**kwargs):
    return comparison_range_chart(RANGES, metric_label="Close price", title="Close price by configuration",
                                  **kwargs)


def test_the_default_is_not_compact():
    default = _chart()
    assert _chart(compact=False).to_plotly_json() == default.to_plotly_json()
    assert default.layout.yaxis.ticktext is None and default.layout.yaxis.tickvals is None
    assert default.layout.legend.orientation is None
    assert default.layout.height == 90 * len(RANGES) + 160


@pytest.mark.parametrize("disclosure_in_title", [True, False])
def test_compact_changes_only_the_legend_ticks_and_height(disclosure_in_title):
    plain = _chart(disclosure_in_title=disclosure_in_title).to_plotly_json()
    compact = _chart(disclosure_in_title=disclosure_in_title, compact=True).to_plotly_json()
    assert compact["data"] == plain["data"]
    assert compact["layout"]["height"] == plain["layout"]["height"] + LEGEND_ALLOWANCE
    for key in ("tickmode", "tickvals", "ticktext"):
        compact["layout"]["yaxis"].pop(key)
    for layout in (compact["layout"], plain["layout"]):
        layout.pop("height")
        layout.pop("legend", None)
    assert compact["layout"] == plain["layout"]


def test_compact_keeps_every_configuration_in_order():
    yaxis = _chart(compact=True).layout.yaxis
    assert list(yaxis.categoryarray) == list(LABELS)
    assert list(yaxis.tickvals) == list(LABELS)
    assert list(yaxis.ticktext) == [stacked_label(label) for label in LABELS]
    assert yaxis.autorange == "reversed"


def test_compact_names_every_series_in_a_bottom_left_legend():
    fig = _chart(compact=True)
    assert [trace.name for trace in fig.data] == [trace.name for trace in _chart().data]
    assert all(trace.showlegend is not False for trace in fig.data)
    legend = fig.layout.legend
    assert {key: legend[key] for key in BOTTOM_LEGEND} == BOTTOM_LEGEND
    assert legend.orientation == "h" and legend.xanchor == "left" and legend.x == 0


def test_hover_still_names_the_full_configuration():
    for trace in _chart(compact=True).data:
        assert trace.hovertemplate.startswith("%{y}<br>")
        assert {y for y in trace.y if y is not None} == set(LABELS)


@pytest.mark.parametrize("label", LABELS)
def test_a_stacked_label_keeps_every_word(label):
    stacked = stacked_label(label)
    assert stacked.split("<br>") == label.split(LABEL_SEPARATOR)
    assert stacked.replace("<br>", LABEL_SEPARATOR) == label


def test_a_label_without_separators_is_unchanged():
    assert stacked_label("RW") == "RW"
