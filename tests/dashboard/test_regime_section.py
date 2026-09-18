"""The market-regimes dashboard section (Phase 10, Step 6).

Every label and figure on screen must be one ``analyze_regimes``
produced, so the checks format the report's own ``RegimeReport`` and
compare strings. The cases that matter here are the ones the analytics
deliberately leave open: an early window with no volatility or volume
class, a window shorter than its grid span, a run with no windows at all,
and the description the report writes itself — none of which may be
filled in, re-joined or re-counted by the dashboard.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics.regimes import (
    COVERAGE_COMPLETE,
    COVERAGE_PARTIAL,
    DIRECTIONS,
    MARKET_STATES,
    MIN_REFERENCE_WINDOWS,
    VOLATILITY_CLASSES,
    VOLUME_CLASSES,
    RegimeContext,
    RegimeObservation,
)
from crypto_simulator.dashboard import regime_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.regime_section import (
    DISTRIBUTIONS,
    NO_WINDOWS_MESSAGE,
    UNAVAILABLE_MESSAGE,
    VOLUME_CHART_TITLE,
)

PRICE = ",.4f"
VOLUME = ",.0f"
SIGNED = "+.4f"
RATIO = ".2%"
RETURN = "+.2%"

#: Wording the section must never use: a regime describes one past
#: window, and none of these would be true of it.
CAUSAL_WORDS = ("caused", "causes", "predicted", "predicts", "drove", "drives", "triggered",
                "influenced", "influence", "resulted in", "led to", "because of", "due to")

#: Table positions, in render order.
WINDOWS, FIGURES, CONTEXT, DISTRIBUTION = 0, 1, 2, 3


def _regime_app(regimes=None, simulation=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.regime_section import render_regimes

    render_regimes(regimes, symbol="FIC", simulation=simulation)


def _render(regimes, simulation=None) -> AppTest:
    return AppTest.from_function(
        _regime_app, kwargs={"regimes": regimes, "simulation": simulation}, default_timeout=120
    ).run()


def _metrics(at: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _captions(at: AppTest) -> str:
    return " ".join(caption.value for caption in at.caption)


def _rows(at: AppTest, index: int) -> list[dict[str, str]]:
    return at.dataframe[index].value.to_dict("records")


def visible_text(at: AppTest) -> str:
    """Everything a reader can see, for the wording checks."""
    parts = [element.value for element in at.caption]
    parts += [element.value for element in at.markdown]
    parts += [element.value for element in at.info]
    parts += [metric.label for metric in at.metric]
    for index in range(at.dataframe.len):
        frame = at.dataframe[index].value
        parts += list(frame.columns)
        parts += [str(cell) for row in frame.to_dict("records") for cell in row.values()]
    return " ".join(parts).lower()


def _section_for(params: SimulationParams):
    payload = run_simulation(params)
    serialized = payload_to_dict(payload)
    return payload.report.regimes, serialized["report"]["regimes"], serialized["simulation"]


@pytest.fixture(scope="module")
def long_run():
    """Long enough for the quartile reference to fill: the later windows
    carry volatility and volume classes, the early ones do not."""
    return _section_for(SimulationParams(ticks=120))


@pytest.fixture(scope="module")
def short_run():
    """One window, shorter than its grid span."""
    return _section_for(SimulationParams(ticks=8))


# --- overview --------------------------------------------------------------------------------------------


def test_the_overview_counts_the_reports_own_windows(long_run):
    report, payload, _ = long_run
    shown = _metrics(_render(payload))
    assert shown["Regime windows"] == format(report.total_windows, ",d")
    assert shown["Complete windows"] == format(report.complete_windows, ",d")
    assert shown["Incomplete windows"] == format(report.incomplete_windows, ",d")
    assert shown["Window size (ticks)"] == format(report.window_size, ",d")


def test_the_overview_names_the_analysed_grid(long_run):
    report, payload, _ = long_run
    captions = _captions(_render(payload))
    first, last = report.observations[0], report.observations[-1]
    assert f"window grid {first.start_tick}-{last.end_tick}" in captions
    assert f"first window {first.start_tick}-{first.end_tick}" in captions
    assert f"last window {last.start_tick}-{last.end_tick}" in captions


def test_coverage_and_window_size_are_the_reports_own(long_run, short_run):
    for fixture, expected in ((long_run, COVERAGE_COMPLETE), (short_run, COVERAGE_PARTIAL)):
        report, payload, _ = fixture
        assert report.coverage == expected
        captions = _captions(_render(payload))
        assert f"window coverage {report.coverage}" in captions
        assert f"window size {report.window_size:,d} ticks" in captions
        assert f"ticks analysed {report.ticks:,d}" in captions
        assert f"pricing mode {report.pricing_mode}" in captions


# --- the window table ------------------------------------------------------------------------------------


def test_one_row_per_window_in_report_order(long_run):
    report, payload, _ = long_run
    rows = _rows(_render(payload), WINDOWS)
    assert [row["Window"] for row in rows] == [
        format(observation.window_index, ",d") for observation in report.observations
    ]


def test_window_labels_are_the_reports_own_labels(long_run):
    report, payload, _ = long_run
    for row, observation in zip(_rows(_render(payload), WINDOWS), report.observations):
        assert row["Ticks"] == f"{observation.start_tick}-{observation.end_tick}"
        assert row["Observed ticks"] == format(observation.tick_count, ",d")
        assert row["Grid span"] == format(observation.expected_tick_count, ",d")
        assert row["Complete"] == ("yes" if observation.complete else "no")
        assert row["Direction"] == (observation.direction or "n/a")
        assert row["Volatility"] == (observation.volatility or "n/a")
        assert row["Volume"] == (observation.volume or "n/a")
        assert row["Market state"] == (observation.market_state or "n/a")


def test_labels_keep_the_analytics_spelling(long_run):
    """No re-casing, no relabelling, and no combined regime label."""
    report, payload, _ = long_run
    rows = _rows(_render(payload), WINDOWS)
    known = {"n/a"}
    assert {row["Direction"] for row in rows} <= known | set(DIRECTIONS)
    assert {row["Volatility"] for row in rows} <= known | set(VOLATILITY_CLASSES)
    assert {row["Volume"] for row in rows} <= known | set(VOLUME_CLASSES)
    assert {row["Market state"] for row in rows} <= known | set(MARKET_STATES)
    assert any(row["Volatility"] in VOLATILITY_CLASSES for row in rows)


def test_the_description_is_the_reports_own(long_run):
    report, payload, _ = long_run
    for row, observation in zip(_rows(_render(payload), WINDOWS), report.observations):
        assert row["Description"] == observation.description


def test_the_description_is_not_rebuilt_from_the_shown_labels(long_run):
    """The report writes ``unavailable`` where the columns show ``n/a``,
    so a description assembled from the table would differ from it."""
    report, payload, _ = long_run
    early = next(o for o in report.observations if o.volatility is None)
    row = next(r for r in _rows(_render(payload), WINDOWS)
               if r["Window"] == format(early.window_index, ",d"))
    assert "unavailable" in row["Description"]
    assert row["Volatility"] == "n/a"


# --- early and incomplete windows ------------------------------------------------------------------------


def test_early_windows_keep_their_unavailable_labels(long_run):
    """A volatility or volume class needs earlier complete windows for its
    quartile reference; until then the analytics assign none."""
    report, payload, _ = long_run
    early = [o for o in report.observations if o.volatility is None]
    assert len(early) == MIN_REFERENCE_WINDOWS
    rows = {row["Window"]: row for row in _rows(_render(payload), WINDOWS)}
    for observation in early:
        row = rows[format(observation.window_index, ",d")]
        assert row["Volatility"] == "n/a" and row["Volume"] == "n/a"


def test_an_unavailable_label_is_never_shown_as_zero_or_normal(long_run):
    _, payload, _ = long_run
    rows = _rows(_render(payload), WINDOWS)
    for row in rows[:MIN_REFERENCE_WINDOWS]:
        assert row["Volatility"] not in {"0", "0.0000", "normal_volatility"}
        assert row["Volume"] not in {"0", "0.0000", "normal_volume"}


def test_an_incomplete_window_is_marked_rather_than_padded(short_run):
    report, payload, _ = short_run
    observation = report.observations[0]
    assert not observation.complete
    row = _rows(_render(payload), WINDOWS)[0]
    assert row["Complete"] == "no"
    assert row["Observed ticks"] == format(observation.tick_count, ",d")
    assert row["Grid span"] == format(observation.expected_tick_count, ",d")
    assert row["Observed ticks"] != row["Grid span"]


def test_the_reference_bounds_are_unavailable_until_the_analytics_have_them(long_run):
    report, payload, _ = long_run
    rows = {row["Window"]: row for row in _rows(_render(payload), FIGURES)}
    for observation in report.observations:
        row = rows[format(observation.window_index, ",d")]
        for column, bounds in (("Volatility reference", observation.volatility_reference),
                               ("Volume reference", observation.volume_reference)):
            if bounds is None:
                assert row[column] == "n/a"
            else:
                assert row[column] == f"{bounds[0]:,.4f} to {bounds[1]:,.4f}"


# --- the figure table ------------------------------------------------------------------------------------


def test_window_figures_are_the_reports_own(long_run):
    report, payload, _ = long_run
    rows = {row["Window"]: row for row in _rows(_render(payload), FIGURES)}
    for observation in report.observations:
        row = rows[format(observation.window_index, ",d")]
        market = observation.market
        assert row["Open"] == format(market.open_price, PRICE)
        assert row["Close"] == format(market.close_price, PRICE)
        assert row["Return"] == format(market.cumulative_return, RETURN)
        assert row["Net log return"] == format(observation.net_log_return, SIGNED)
        assert row["Volatility"] == format(market.volatility, PRICE)
        assert row["Realized volatility"] == format(market.realized_volatility, PRICE)
        assert row["Volume"] == format(market.volume_breakdown.total_volume, VOLUME)
        assert row["Volume per tick"] == format(observation.volume_per_tick, VOLUME)
        assert row["Running peak"] == format(observation.running_peak, PRICE)
        assert row["Drawdown at start"] == format(observation.drawdown_at_start, RATIO)
        assert row["Drawdown at end"] == format(observation.drawdown_at_end, RATIO)


def test_the_net_log_return_is_not_the_markets_cumulative_return(long_run):
    """They are different figures, and the table keeps them apart."""
    report, payload, _ = long_run
    observation = report.observations[0]
    row = _rows(_render(payload), FIGURES)[0]
    assert observation.net_log_return != observation.market.cumulative_return
    assert row["Net log return"] == format(observation.net_log_return, SIGNED)
    assert row["Return"] == format(observation.market.cumulative_return, RETURN)


# --- context ---------------------------------------------------------------------------------------------


def test_the_context_table_is_the_reports_own_record():
    report, payload, _ = _section_for(
        SimulationParams(ticks=40, events=True, psychology=True, whale_observation=True)
    )
    at = _render(payload)
    rows = {row["Window"]: row for row in _rows(at, CONTEXT)}
    for observation in report.observations:
        row = rows[format(observation.window_index, ",d")]
        context = observation.context
        assert row["Event state ticks"] == format(context.event_state_ticks, ",d")
        assert row["Event active ticks"] == format(context.event_active_ticks, ",d")
        assert row["Event live"] == ("yes" if context.event_active else "no")
        assert row["Psychology ticks"] == format(context.psychology_ticks, ",d")
        assert row["Mean fear"] == format(context.mean_fear, PRICE)
        assert row["Whale observed ticks"] == format(context.whale_observed_ticks, ",d")
        assert row["Events"] == (", ".join(context.event_ids) or "none")
        assert row["Categories"] == (", ".join(context.event_categories) or "none")


def test_a_window_with_no_event_state_keeps_event_live_unavailable(long_run):
    """``None`` means no tick recorded an event state at all, which the
    analytics keep apart from a window whose events were not live."""
    report, payload, _ = long_run
    assert report.observations[0].context.event_active is None
    assert _rows(_render(payload), CONTEXT)[0]["Event live"] == "n/a"


def test_psychology_means_are_unavailable_without_psychology(long_run):
    report, payload, _ = long_run
    assert report.observations[0].context.mean_fear is None
    row = _rows(_render(payload), CONTEXT)[0]
    for column in ("Mean fear", "Mean FOMO", "Mean conviction", "Mean uncertainty"):
        assert row[column] == "n/a"


def test_the_context_table_reads_declared_context_fields(long_run):
    _, payload, _ = long_run
    declared = {field.name for field in dataclasses.fields(RegimeContext)}
    assert declared <= set(payload["observations"][0]["context"])


# --- the distribution ------------------------------------------------------------------------------------


def test_the_distribution_is_the_reports_own_tallies(long_run):
    report, payload, _ = long_run
    rows = _rows(_render(payload), DISTRIBUTION)
    expected = [
        (dimension, label or "n/a", format(windows, ",d"))
        for dimension, field in DISTRIBUTIONS
        for label, windows in getattr(report, field)
    ]
    assert [(row["Dimension"], row["Label"], row["Windows"]) for row in rows] == expected


def test_the_distribution_keeps_the_unavailable_tally(long_run):
    report, payload, _ = long_run
    rows = _rows(_render(payload), DISTRIBUTION)
    unavailable = next(row for row in rows
                       if row["Dimension"] == "volatility" and row["Label"] == "n/a")
    expected = dict(report.volatility_counts)[None]
    assert unavailable["Windows"] == format(expected, ",d")
    assert expected == MIN_REFERENCE_WINDOWS


# --- the chart -------------------------------------------------------------------------------------------


def test_the_chart_plots_the_reports_own_volume_per_tick(long_run):
    report, payload, _ = long_run
    at = _render(payload)
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert spec["data"][0]["x"] == [o.start_tick for o in report.observations]
    assert spec["data"][0]["y"] == [o.volume_per_tick for o in report.observations]
    assert spec["layout"]["title"]["text"] == VOLUME_CHART_TITLE


# --- missing regime data ---------------------------------------------------------------------------------


def test_a_report_with_no_windows_says_so(long_run):
    """A report can hold no windows when no tick was analysed; the
    section says that rather than drawing an empty grid."""
    _, payload, _ = long_run
    empty = {**payload, "observations": [], "total_windows": 0, "complete_windows": 0,
             "incomplete_windows": 0, "coverage": "none"}
    at = _render(empty)
    assert NO_WINDOWS_MESSAGE in [info.value for info in at.info]
    assert at.dataframe.len == 0
    assert at.metric.len == 0
    assert "window coverage none" in _captions(at)


def test_a_missing_regime_report_is_not_an_empty_one():
    at = _render(None)
    assert UNAVAILABLE_MESSAGE in [info.value for info in at.info]
    assert at.dataframe.len == 0 and at.metric.len == 0


def test_a_one_tick_run_renders_a_single_incomplete_window():
    report, payload, simulation = _section_for(SimulationParams(ticks=1))
    at = _render(payload, simulation)
    assert not at.exception
    assert report.total_windows == 1
    row = _rows(at, WINDOWS)[0]
    assert row["Complete"] == "no"
    assert row["Direction"] == "n/a"
    assert row["Volatility"] == "n/a"


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=3),
        SimulationParams(ticks=25, pricing_mode="amm", include_whales=False),
        SimulationParams(ticks=45, events=True, random_events=True, psychology=True),
        SimulationParams(ticks=30, scenario="wash_trading"),
        SimulationParams(ticks=110, pricing_mode="amm", include_whales=False),
    ],
    ids=["short", "amm", "events-psychology", "scenario", "amm-long"],
)
def test_the_section_renders_for_varied_runs(params):
    _, payload, simulation = _section_for(params)
    at = _render(payload, simulation)
    assert not at.exception


def test_both_pricing_modes_label_their_windows_the_same_way():
    """The taxonomy is the analytics', so it does not change with the
    pricing mode; only the figures behind it do."""
    random_walk, rw_payload, _ = _section_for(SimulationParams(ticks=110))
    amm, amm_payload, _ = _section_for(
        SimulationParams(ticks=110, pricing_mode="amm", include_whales=False))
    assert random_walk.pricing_mode == "random_walk" and amm.pricing_mode == "amm"
    for report, payload in ((random_walk, rw_payload), (amm, amm_payload)):
        rows = _rows(_render(payload), WINDOWS)
        assert [row["Description"] for row in rows] == [
            observation.description for observation in report.observations
        ]


# --- wording, determinism and structure ------------------------------------------------------------------


def test_the_visible_wording_stays_descriptive(long_run, short_run):
    for fixture in (long_run, short_run):
        _, payload, simulation = fixture
        shown = visible_text(_render(payload, simulation))
        for word in CAUSAL_WORDS:
            assert word not in shown, f"causal wording on screen: {word}"


def test_the_section_makes_no_claim_about_later_ticks(long_run):
    _, payload, _ = long_run
    captions = _captions(_render(payload))
    assert "no label says anything about the ticks after its window" in captions


def test_the_same_payload_renders_the_same_tables(long_run):
    _, payload, _ = long_run
    first, second = _render(payload), _render(payload)
    assert [_rows(first, i) for i in range(first.dataframe.len)] == [
        _rows(second, i) for i in range(second.dataframe.len)
    ]


def test_every_observation_field_is_available_to_the_section(long_run):
    _, payload, _ = long_run
    declared = {field.name for field in dataclasses.fields(RegimeObservation)}
    assert declared <= set(payload["observations"][0])
    assert {"complete", "description"} <= set(payload["observations"][0])


BANNED_CALLS = {"analyze_regimes", "analyze_market", "analyze_psychology", "build_report",
                "fsum", "sum", "round", "abs", "min", "max", "sorted", "count_values"}


def _calls(module) -> set[str]:
    tree = ast.parse(Path(module.__file__).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


def _arithmetic(module) -> list[str]:
    tree = ast.parse(Path(module.__file__).read_text())
    return [
        type(node.op).__name__
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod))
    ]


def test_the_regime_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(regime_section)


def test_the_regime_section_does_no_arithmetic():
    assert _arithmetic(regime_section) == []


def test_the_regime_section_assigns_no_labels():
    """It never names a label to compare or assign: the labels arrive in
    the payload."""
    source = Path(regime_section.__file__).read_text()
    for banned in ("RISING", "FALLING", "FLAT", "HIGH_VOLATILITY", "LOW_VOLATILITY",
                   "NORMAL_VOLUME", "AT_HIGH", "DRAWDOWN", "RECOVERY", "quartile("):
        assert banned not in source


def test_the_regime_section_imports_no_psychology_module():
    """The containment rule holds: psychology means reach the section
    through the serialized report only."""
    source = Path(regime_section.__file__).read_text()
    assert "analytics.psychology" not in source
    assert "core.psychology" not in source
