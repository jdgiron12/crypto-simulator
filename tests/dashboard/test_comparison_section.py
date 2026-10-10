"""The scenario-comparison section (Phase 20, Step 7), driven through
``streamlit.testing.v1.AppTest`` on real reduced comparisons.

The section shows each configuration's batch as it is — run counts and
failures, the aggregate's own values for one metric side by side, and the
median of every metric — in selection order, with the comparison
disclosures. It computes nothing, ranks nothing and imports no analytics.
"""

from __future__ import annotations

import ast
import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import crypto_simulator.dashboard.comparison_section as comparison_section
from crypto_simulator.analytics.aggregate import AGGREGATED_METRICS
from crypto_simulator.dashboard.batch_section import ZERO_COUNT_MESSAGE, metric_label
from crypto_simulator.dashboard.comparison_section import (
    AMM_CONDITION_NOTE,
    MARKET_CONDITION_DISCLOSURE,
    METRIC_KEY,
    NO_COMPARISON_MESSAGE,
    PRICING_ARCHITECTURE_DISCLOSURE,
    SHARED_SEED_DISCLOSURE,
)
from crypto_simulator.dashboard.data import (
    SimulationParams,
    comparison_configurations,
    comparison_to_dict,
    plan_comparison,
    plan_to_dict,
    run_dashboard_comparison,
    run_simulation,
)
from crypto_simulator.services.batch import batch_seed
from crypto_simulator.visualization.comparison_charts import COMPARISON_DISCLOSURE, MEAN_TRACE, MEDIAN_TRACE

HELD = SimulationParams(ticks=12, include_whales=False)
SEED = 4242
CONDITIONS = comparison_configurations(["random_walk"], [None], [None, "bull", "bear"])
DISCLOSURES = (COMPARISON_DISCLOSURE, SHARED_SEED_DISCLOSURE, MARKET_CONDITION_DISCLOSURE,
               PRICING_ARCHITECTURE_DISCLOSURE, AMM_CONDITION_NOTE)
FORBIDDEN = ("better", "worse", "best", "worst", "winner", "outperform", "optimal", "expected", "likely",
             "predict", "forecast", "probability", "odds", "recommend", "rank", "score", "caused")


def _section(comparison=None, error=None):
    """The results on their own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.comparison_section import render_comparison

    render_comparison(comparison, error=error)


def _plan_section(plan, base_seed):
    from crypto_simulator.dashboard.comparison_section import render_comparison_plan

    render_comparison_plan(plan, base_seed=base_seed)


def _app(comparison=None, error=None) -> AppTest:
    return AppTest.from_function(_section, kwargs={"comparison": comparison, "error": error},
                                 default_timeout=60).run()


def _plan_app(plan, base_seed=SEED) -> AppTest:
    return AppTest.from_function(_plan_section, kwargs={"plan": plan, "base_seed": base_seed},
                                 default_timeout=60).run()


def _failing(predicate):
    def runner(params):
        if predicate(params):
            raise RuntimeError(f"refused {params.market_condition} seed {params.random_seed}")
        return run_simulation(params)

    return runner


@pytest.fixture(scope="module")
def ok():
    return comparison_to_dict(run_dashboard_comparison(HELD, CONDITIONS, 4, base_seed=SEED))


@pytest.fixture(scope="module")
def mixed():
    runner = _failing(lambda p: p.market_condition == "bear" or (
        p.market_condition == "bull" and p.random_seed == batch_seed(SEED, 2)))
    return comparison_to_dict(run_dashboard_comparison(HELD, CONDITIONS, 4, base_seed=SEED, runner=runner))


@pytest.fixture(scope="module")
def pricing():
    configs = comparison_configurations(["random_walk", "amm"], [None], ["bull"])
    return comparison_to_dict(run_dashboard_comparison(HELD, configs, 3, base_seed=SEED))


def _charts(at):
    return [json.loads(chart.proto.spec) for chart in at.get("plotly_chart")]


def _captions(at):
    return [e.value for e in at.caption]


def _group(comparison, label):
    return next(g for g in comparison["groups"] if g["label"] == label)


def _entry(group, metric):
    return next(m for m in group["batch"]["aggregate"]["metrics"] if m["metric"] == metric)


def _shown(at):
    parts = [e.value for e in at.markdown] + _captions(at) + [e.value for e in at.info]
    parts += [e.value for e in at.success] + [e.value for e in at.warning]
    for chart in _charts(at):
        parts.append(chart["layout"]["title"]["text"])
        parts += [trace.get("name", "") for trace in chart["data"]]
    for frame in [t.value for t in at.table] + [d.value for d in at.dataframe]:
        parts += [str(c) for c in frame.columns] + [str(i) for i in frame.index]
    text = " ".join(parts)
    for disclosure in DISCLOSURES:
        text = text.replace(disclosure, "")
    return text.lower()


# --- plan -----------------------------------------------------------------------------------------------


def test_the_plan_shows_configurations_runs_and_total():
    at = _plan_app(plan_to_dict(plan_comparison(HELD, CONDITIONS, 25)))
    markdown = [e.value for e in at.markdown]
    assert markdown[0] == ("Configurations: **3** · Runs per configuration: **25** · Total simulations: 3 × 25 "
                           "= **75**")
    assert markdown[1].splitlines() == [f"- {c.label}" for c in CONDITIONS]
    caption = _captions(at)[0]
    assert caption.startswith("Compared dimensions: market condition. Held constant: 12 ticks · traders on · "
                              "whales off · news events off")
    assert f"shared base seed {SEED}" in caption
    assert at.warning.len == 0


def test_the_plan_shows_every_problem():
    configs = comparison_configurations(["random_walk", "amm"], [None], list((None, "bull", "bear", "meme")))
    at = _plan_app(plan_to_dict(plan_comparison(replace(HELD, include_whales=True), configs, 60)))
    warnings = [e.value for e in at.warning]
    assert len(warnings) == 2
    assert "8 configurations x 60 runs is 480 simulations" in warnings[0]
    assert "AMM configurations cannot run with whales" in warnings[1]


def test_a_single_configuration_plan_compares_nothing():
    at = _plan_app(plan_to_dict(plan_comparison(HELD, CONDITIONS[:1], 5)))
    assert _captions(at)[0].startswith("Compared dimensions: none (a single configuration).")


# --- empty and error ------------------------------------------------------------------------------------


def test_no_comparison_shows_the_empty_message_and_nothing_else():
    at = _app()
    assert [e.value for e in at.info] == [NO_COMPARISON_MESSAGE]
    assert at.get("plotly_chart") == [] and at.table.len == 0 and at.dataframe.len == 0


def test_a_comparison_that_could_not_run_shows_its_error():
    at = _app(error="ValueError: AMM configurations cannot run with whales")
    assert "Comparison failed. ValueError: AMM configurations cannot run with whales" in at.error[0].value
    assert at.get("plotly_chart") == []


# --- summary and failures -------------------------------------------------------------------------------


def test_the_summary_has_one_row_per_configuration_in_order(ok):
    at = _app(ok)
    frame = at.dataframe[0].value
    assert list(frame.columns) == ["Configuration", "Pricing mode", "Manipulation scenario", "Market condition",
                                   "Base seed", "Requested runs", "Successful runs", "Failed runs"]
    assert list(frame["Configuration"]) == [c.label for c in CONDITIONS]
    assert list(frame["Market condition"]) == ["none (neutral)", "bear", "bull"]
    assert list(frame["Base seed"]) == [SEED] * 3
    assert list(frame["Successful runs"]) == [4, 4, 4]
    assert at.success[0].value == "Every run of every configuration completed."


def test_failures_are_listed_per_configuration(mixed):
    at = _app(mixed)
    summary = at.dataframe[0].value
    assert list(summary["Successful runs"]) == [4, 0, 3]
    assert list(summary["Failed runs"]) == [0, 4, 1]
    warning = at.warning[0].value
    assert "RW | No manipulation | Bear, RW | No manipulation | Bull" in warning
    assert "do not all rest on the same number of runs" in warning
    failures = at.dataframe[1].value
    assert list(failures.columns) == ["Configuration", "Run index", "Seed", "Error"]
    assert list(failures["Configuration"]) == ["RW | No manipulation | Bear"] * 4 + ["RW | No manipulation | Bull"]
    assert list(failures["Run index"]) == [0, 1, 2, 3, 2]
    assert failures["Error"].iloc[-1] == f"RuntimeError: refused bull seed {batch_seed(SEED, 2)}"


def test_a_configuration_with_no_successful_run_is_kept_but_not_charted(mixed):
    at = _app(mixed)
    assert "No successful run, so no aggregate is shown for: RW | No manipulation | Bear." in [
        e.value for e in at.info]
    chart = _charts(at)[0]
    assert list(chart["layout"]["yaxis"]["categoryarray"]) == ["RW | No manipulation | Neutral (no preset)",
                                                              "RW | No manipulation | Bull"]
    table = at.table[0].value
    assert table.loc["RW | No manipulation | Bear", "Median (P50)"] == "n/a"
    assert table.loc["RW | No manipulation | Bear", "Runs with a value"] == "0"
    matrix = at.dataframe[2].value
    assert list(matrix.columns) == ["RW | No manipulation | Neutral (no preset)", "RW | No manipulation | Bull"]


def test_a_comparison_with_no_successful_run_anywhere_shows_only_its_summary():
    comparison = comparison_to_dict(run_dashboard_comparison(
        HELD, CONDITIONS[:2], 2, base_seed=SEED, runner=_failing(lambda p: True)))
    at = _app(comparison)
    assert at.get("plotly_chart") == [] and at.table.len == 0 and at.selectbox.len == 0
    assert at.dataframe.len == 2


# --- one metric -----------------------------------------------------------------------------------------


def test_the_metric_selector_offers_the_aggregated_metrics(ok):
    control = _app(ok).selectbox(key=METRIC_KEY)
    assert list(control.options) == [metric_label(m) for m in AGGREGATED_METRICS]
    assert control.value == "close_price"


def test_the_chart_draws_each_configurations_aggregate(ok):
    at = _app(ok)
    chart = _charts(at)[0]
    assert chart["layout"]["title"]["text"] == "Close price by configuration"
    # The disclosure opens the results as wrapping text (Phase 24, Step 5),
    # rather than as a one-line chart subtitle that is cut off when narrow.
    assert COMPARISON_DISCLOSURE not in chart["layout"]["title"]["text"]
    assert COMPARISON_DISCLOSURE in _captions(at)
    traces = {t["name"]: t for t in chart["data"]}
    groups = [_group(ok, c.label) for c in CONDITIONS]
    assert traces[MEDIAN_TRACE]["x"] == [_entry(g, "close_price")["median"] for g in groups]
    assert traces[MEAN_TRACE]["x"] == [_entry(g, "close_price")["mean"] for g in groups]
    outer = []
    for g in groups:
        p = {q["percent"]: q["value"] for q in _entry(g, "close_price")["percentiles"]}
        outer += [p[5], p[95], None]
    assert traces["P5 to P95"]["x"] == outer


def test_the_table_is_the_aggregates_own_values_one_row_per_configuration(ok):
    table = _app(ok).table[0].value
    assert list(table.index) == [c.label for c in CONDITIONS]
    assert list(table.columns) == ["Runs with a value", "Median (P50)", "Mean", "P5", "P25", "P75", "P95",
                                   "Minimum", "Maximum"]
    for c in CONDITIONS:
        entry = _entry(_group(ok, c.label), "close_price")
        p = {q["percent"]: q["value"] for q in entry["percentiles"]}
        assert table.loc[c.label, "Median (P50)"] == format(entry["median"], ",.6g")
        assert table.loc[c.label, "Mean"] == format(entry["mean"], ",.6g")
        assert table.loc[c.label, "P5"] == format(p[5], ",.6g")
        assert table.loc[c.label, "P95"] == format(p[95], ",.6g")


def test_selecting_a_metric_redraws_from_the_stored_aggregates(ok):
    at = _app(ok)
    at.selectbox(key=METRIC_KEY).set_value("max_drawdown").run()
    chart = _charts(at)[0]
    assert chart["layout"]["title"]["text"] == "Max drawdown by configuration"
    median = {t["name"]: t for t in chart["data"]}[MEDIAN_TRACE]["x"]
    assert median == [_entry(_group(ok, c.label), "max_drawdown")["median"] for c in CONDITIONS]


def test_a_metric_no_run_computed_says_so():
    comparison = comparison_to_dict(run_dashboard_comparison(
        replace(HELD, ticks=1), CONDITIONS[:2], 2, base_seed=SEED))
    at = _app(comparison)
    at.selectbox(key=METRIC_KEY).set_value("volatility").run()
    info = [e.value for e in at.info]
    assert any(v.startswith(ZERO_COUNT_MESSAGE) for v in info)
    assert not any(c["layout"]["title"]["text"].startswith("Volatility") for c in _charts(at))


def test_one_configuration_is_drawn_alone():
    comparison = comparison_to_dict(run_dashboard_comparison(HELD, CONDITIONS[:1], 1, base_seed=SEED))
    at = _app(comparison)
    chart = _charts(at)[0]
    assert chart["layout"]["yaxis"]["categoryarray"] == [CONDITIONS[0].label]
    assert at.table[0].value.loc[CONDITIONS[0].label, "Runs with a value"] == "1"


# --- all metrics ----------------------------------------------------------------------------------------


def test_the_matrix_is_the_median_of_every_metric_with_no_styling(ok):
    at = _app(ok)
    matrix = at.dataframe[1].value
    assert list(matrix.index) == [metric_label(m) for m in AGGREGATED_METRICS]
    assert list(matrix.columns) == [c.label for c in CONDITIONS]
    for c in CONDITIONS:
        group = _group(ok, c.label)
        assert list(matrix[c.label]) == [
            "n/a" if _entry(group, m)["median"] is None else format(_entry(group, m)["median"], ",.6g")
            for m in AGGREGATED_METRICS
        ]
    assert all(dtype == object for dtype in matrix.dtypes)


# --- disclosures and vocabulary -------------------------------------------------------------------------


def test_the_comparison_disclosures_are_shown(ok):
    captions = _captions(_app(ok))
    assert COMPARISON_DISCLOSURE in captions
    assert SHARED_SEED_DISCLOSURE in captions
    assert MARKET_CONDITION_DISCLOSURE in captions
    assert PRICING_ARCHITECTURE_DISCLOSURE not in captions


def test_a_pricing_comparison_says_the_architectures_differ(pricing):
    captions = _captions(_app(pricing))
    assert PRICING_ARCHITECTURE_DISCLOSURE in captions
    assert AMM_CONDITION_NOTE in captions


def test_a_neutral_only_comparison_has_no_market_condition_disclosure():
    configs = comparison_configurations(["random_walk"], [None, "wash_trading"], [None])
    captions = _captions(_app(comparison_to_dict(run_dashboard_comparison(HELD, configs, 2, base_seed=SEED))))
    assert MARKET_CONDITION_DISCLOSURE not in captions
    assert COMPARISON_DISCLOSURE in captions


def test_the_disclosures_are_the_approved_text():
    assert SHARED_SEED_DISCLOSURE == (
        "Corresponding runs use the same derived seed when a shared base seed is selected; different "
        "configurations may still consume random streams differently.")
    assert MARKET_CONDITION_DISCLOSURE == (
        "Market-condition presets are simulator configurations, not forecasts of real market conditions.")


@pytest.mark.parametrize("which", ["ok", "mixed", "pricing", "none"])
def test_no_ranking_or_predictive_wording_on_screen(which, ok, mixed, pricing):
    comparison = {"ok": ok, "mixed": mixed, "pricing": pricing, "none": None}[which]
    shown = _shown(_app(comparison))
    for word in FORBIDDEN:
        assert word not in shown, word


def test_the_section_does_not_reorder_by_value(ok):
    shuffled = copy.deepcopy(ok)
    shuffled["groups"].reverse()
    chart = _charts(_app(shuffled))[0]
    assert chart["layout"]["yaxis"]["categoryarray"] == [c.label for c in reversed(CONDITIONS)]


# --- structure ------------------------------------------------------------------------------------------


def _tree():
    return ast.parse(Path(comparison_section.__file__).read_text())


def test_the_section_imports_no_analytics_core_or_services():
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom):
            for banned in ("crypto_simulator.analytics", "crypto_simulator.core", "crypto_simulator.services"):
                assert not node.module.startswith(banned), node.module


def test_the_section_does_no_arithmetic_and_runs_nothing():
    numeric = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod)
    assert [n for n in ast.walk(_tree()) if isinstance(n, (ast.BinOp, ast.AugAssign))
            and isinstance(n.op, numeric)] == []
    calls = {n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
             for n in ast.walk(_tree()) if isinstance(n, ast.Call)}
    for banned in ("run_batch", "aggregate_batch", "aggregate_values", "run_simulation", "run_dashboard_comparison",
                   "sum", "fsum", "mean", "median", "percentile", "stdev", "sorted", "sort", "min", "max", "len",
                   "background_gradient"):
        assert banned not in calls, banned
