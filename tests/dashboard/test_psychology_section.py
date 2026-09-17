"""The psychology dashboard section (Phase 10, Step 5).

Every figure on screen must be one ``analyze_psychology_market`` (or the
``analyze_psychology`` summaries it embeds) produced, so the checks format
the report's own values and compare strings. The cases that matter are the
ones the analytics keep apart: a correlation that could not be computed
versus a zero, coverage versus activity, and the four components kept on
their own scale rather than combined into a score. The wording checks
matter as much as the numbers: a correlation is an association, never a
cause.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics import build_report
from crypto_simulator.analytics.psychology import COMPONENTS, ComponentSummary
from crypto_simulator.analytics.psychology_market import (
    COVERAGE_COMPLETE,
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    PsychologyMarketObservation,
)
from crypto_simulator.config import get_settings
from crypto_simulator.dashboard import psychology_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.psychology_section import (
    COMPONENT_CHART_TITLE,
    PARTIAL_COVERAGE,
    observation_fields,
    NO_EVENT_PERIODS_MESSAGE,
    NO_PSYCHOLOGY_MESSAGE,
    PSYCHOLOGY_OFF_MESSAGE,
)
from crypto_simulator.services.coin_simulation import build_coin_simulator

VALUE = ",.4f"
SIGNED = "+.4f"
VOLUME = ",.0f"
RATIO = ".2%"

#: Wording the section must never use: an association is not a cause.
CAUSAL_WORDS = ("caused", "causes", "predicted", "predicts", "drove", "drives", "triggered",
                "influenced", "influence", "resulted in", "led to", "because of", "due to")


def _psychology_app(psychology=None, simulation=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.psychology_section import render_psychology

    render_psychology(psychology, symbol="FIC", simulation=simulation)


def _render(psychology, simulation=None) -> AppTest:
    return AppTest.from_function(
        _psychology_app,
        kwargs={"psychology": psychology, "simulation": simulation},
        default_timeout=90,
    ).run()


def _captions(at: AppTest) -> str:
    return " ".join(caption.value for caption in at.caption)


def _rows(at: AppTest, index: int) -> list[dict[str, str]]:
    return at.dataframe[index].value.to_dict("records")


def _visible_text(at: AppTest) -> str:
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
    return (payload.report.psychology_market,
            serialized["report"]["psychology_market"],
            serialized["simulation"])


# Table order inside the section.
COMPONENTS_TABLE, OCCUPANCY_TABLE, PERSISTENCE_TABLE = 0, 1, 2
CORRELATIONS_TABLE, GROUPS_TABLE, EVENT_PERIODS_TABLE, OBSERVATIONS_TABLE = 3, 4, 5, 6


@pytest.fixture(scope="module")
def with_events():
    """Psychology recorded alongside a news schedule, so the event-period
    comparison exists too."""
    return _section_for(SimulationParams(ticks=60, events=True, psychology=True))


@pytest.fixture(scope="module")
def without_events():
    return _section_for(SimulationParams(ticks=30, psychology=True))


# --- coverage --------------------------------------------------------------------------------------------


def test_coverage_is_the_reports_own(with_events):
    report, payload, _ = with_events
    captions = _captions(_render(payload))
    assert report.coverage == COVERAGE_COMPLETE
    assert f"psychology coverage {report.coverage}" in captions
    assert (f"ticks with psychology {report.ticks_with_psychology:,d} of {report.ticks:,d}"
            in captions)
    assert (f"recorded ticks {report.first_psychology_tick}-{report.last_psychology_tick}"
            in captions)
    assert f"pricing mode {report.pricing_mode}" in captions


def test_partial_coverage_is_reported_and_explained():
    """Real ticks, with psychology recorded on only some of them."""
    settings = get_settings()
    sim = build_coin_simulator(settings, psychology=True)
    recorded = sim.run(20)
    mixed = [
        tick if tick.tick % 2 else dataclasses.replace(tick, psychology=None)
        for tick in recorded
    ]
    report = build_report(mixed, initial_price=settings.coin.starting_price)
    from crypto_simulator.dashboard.serialization import report_to_dict

    payload = report_to_dict(report)["psychology_market"]
    assert report.psychology_market.coverage == COVERAGE_PARTIAL
    at = _render(payload)
    captions = _captions(at)
    assert f"psychology coverage {COVERAGE_PARTIAL}" in captions
    assert "some analysed ticks carry no psychology" in captions
    assert at.dataframe.len > 0


# --- components ------------------------------------------------------------------------------------------


def test_component_summaries_are_the_reports_own(with_events):
    report, payload, _ = with_events
    rows = _rows(_render(payload), COMPONENTS_TABLE)
    assert [row["Component"] for row in rows] == [c.component for c in report.components]
    assert [row["Component"] for row in rows] == list(COMPONENTS)
    for row, component in zip(rows, report.components):
        assert row["Ticks"] == format(component.count, ",d")
        assert row["Mean"] == format(component.mean, VALUE)
        assert row["Median"] == format(component.median, VALUE)
        assert row["Minimum"] == format(component.minimum, VALUE)
        assert row["Maximum"] == format(component.maximum, VALUE)
        assert row["P90"] == format(component.p90, VALUE)
        assert row["P95"] == format(component.p95, VALUE)


def test_the_components_are_not_combined_into_a_score(with_events):
    _, payload, _ = with_events
    shown = _visible_text(_render(payload))
    for invented in ("sentiment score", "psychology score", "mood index", "composite"):
        assert invented not in shown


def test_the_component_chart_plots_the_recorded_values(with_events):
    report, payload, _ = with_events
    at = _render(payload)
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert spec["layout"]["title"]["text"] == COMPONENT_CHART_TITLE
    assert [series["name"] for series in spec["data"]] == list(COMPONENTS)
    for series in spec["data"]:
        assert series["x"] == [o.tick for o in report.observations]
        assert series["y"] == [getattr(o, series["name"]) for o in report.observations]


# --- occupancy and persistence ---------------------------------------------------------------------------


def test_threshold_occupancy_is_the_reports_own(with_events):
    report, payload, _ = with_events
    rows = _rows(_render(payload), OCCUPANCY_TABLE)
    expected = [(c.component, o) for c in report.components for o in c.occupancy]
    assert len(rows) == len(expected)
    for row, (component, occupancy) in zip(rows, expected):
        assert row["Component"] == component
        assert row["Threshold"] == format(occupancy.threshold, VALUE)
        assert row["Ticks at or above"] == format(occupancy.ticks, ",d")
        assert row["Share of ticks"] == format(occupancy.share, RATIO)


def test_persistence_is_the_reports_own(with_events):
    report, payload, _ = with_events
    rows = _rows(_render(payload), PERSISTENCE_TABLE)
    for row, component in zip(rows, report.components):
        persistence = component.persistence
        assert row["Threshold"] == format(persistence.threshold, VALUE)
        assert row["Longest run"] == format(persistence.longest_run, ",d")
        assert row["Runs"] == format(persistence.runs, ",d")
        assert row["Longest run starts"] == (
            "n/a" if persistence.longest_run_start is None else str(persistence.longest_run_start)
        )


def test_a_component_that_never_reached_the_threshold_has_no_start():
    """Zero is the analytics' own zero; the missing start tick stays
    missing."""
    report, payload, _ = _section_for(SimulationParams(ticks=6, psychology=True))
    rows = {row["Component"]: row for row in _rows(_render(payload), PERSISTENCE_TABLE)}
    for component in report.components:
        if component.persistence.longest_run == 0:
            assert rows[component.component]["Longest run"] == "0"
            assert rows[component.component]["Longest run starts"] == "n/a"
            break
    else:
        pytest.skip("this run reached the persistence threshold on every component")


# --- associations ----------------------------------------------------------------------------------------


def test_correlations_are_the_reports_own(with_events):
    report, payload, _ = with_events
    rows = _rows(_render(payload), CORRELATIONS_TABLE)
    assert len(rows) == len(report.correlations)
    for row, correlation in zip(rows, report.correlations):
        assert row["Series"] == correlation.x
        assert row["Compared with"] == correlation.y
        assert row["Direction"] == correlation.direction
        assert row["Lag"] == format(correlation.lag, ",d")
        assert row["Pairs"] == format(correlation.pairs, ",d")
        assert row["Correlation"] == (
            "n/a" if correlation.value is None else format(correlation.value, SIGNED)
        )


def test_an_uncomputable_correlation_keeps_its_reason():
    """Too few pairs is the analytics' own explanation, not a zero."""
    report, payload, _ = _section_for(SimulationParams(ticks=2, psychology=True))
    unavailable = [c for c in report.correlations if c.value is None]
    assert unavailable, "a two-tick run cannot compute every correlation"
    rows = {(row["Series"], row["Compared with"], row["Lag"]): row
            for row in _rows(_render(payload), CORRELATIONS_TABLE)}
    for correlation in unavailable:
        row = rows[(correlation.x, correlation.y, format(correlation.lag, ",d"))]
        assert row["Correlation"] == "n/a"
        assert row["Unavailable because"] == correlation.unavailable_reason


def test_lagged_associations_are_labelled_by_their_direction(with_events):
    report, payload, _ = with_events
    lagged = [c for c in report.correlations if c.lag]
    assert lagged, "the report should include lagged associations"
    rows = _rows(_render(payload), CORRELATIONS_TABLE)
    for correlation in lagged:
        assert any(row["Direction"] == correlation.direction and row["Lag"] == str(correlation.lag)
                   for row in rows)


def test_group_averages_are_the_reports_own(with_events):
    report, payload, _ = with_events
    rows = _rows(_render(payload), GROUPS_TABLE)
    assert [row["Component"] for row in rows] == [g.component for g in report.groups]
    for row, group in zip(rows, report.groups):
        assert row["Threshold"] == format(group.threshold, VALUE)
        assert row["Low ticks"] == format(group.low.ticks, ",d")
        assert row["High ticks"] == format(group.high.ticks, ",d")
        assert row["Low mean log return"] == format(group.low.mean_log_return, SIGNED)
        assert row["High mean log return"] == format(group.high.mean_log_return, SIGNED)
        assert row["Low mean volume"] == format(group.low.mean_volume, VOLUME)
        assert row["High mean volume"] == format(group.high.mean_volume, VOLUME)


# --- event periods ---------------------------------------------------------------------------------------


def test_event_period_means_are_the_reports_own(with_events):
    report, payload, _ = with_events
    periods = report.event_periods
    assert periods is not None
    at = _render(payload)
    captions = _captions(at)
    assert f"source {periods.source}" in captions
    assert f"event ticks {periods.event_period_ticks:,d}" in captions
    assert f"other ticks {periods.other_period_ticks:,d}" in captions
    rows = _rows(at, EVENT_PERIODS_TABLE)
    for row, component in zip(rows, periods.components):
        assert row["Component"] == component.component
        assert row["Mean during event ticks"] == format(component.event_period_mean, VALUE)
        assert row["Mean during other ticks"] == format(component.other_period_mean, VALUE)
        assert row["Difference"] == format(component.difference, SIGNED)


def test_a_run_without_events_has_no_event_period_comparison(without_events):
    report, payload, _ = without_events
    assert report.event_periods is None
    assert NO_EVENT_PERIODS_MESSAGE in _captions(_render(payload))


# --- observations ----------------------------------------------------------------------------------------


def test_the_observations_table_is_the_per_tick_record(with_events):
    report, payload, _ = with_events
    at = _render(payload)
    rows = _rows(at, OBSERVATIONS_TABLE)
    assert len(rows) == len(report.observations)
    for row, observation in zip(rows, report.observations):
        assert row["Tick"] == str(observation.tick)
        assert row["Price"] == format(observation.price, VALUE)
        assert row["Dominant"] == observation.dominant
        for component in COMPONENTS:
            assert row[component.capitalize()] == format(getattr(observation, component), VALUE)


def test_the_dominant_component_is_per_tick_and_not_aggregated(with_events):
    """``PsychologyMarketReport`` carries no dominant-component totals, so
    the section shows the per-tick label and says why there are no
    totals."""
    _, payload, _ = with_events
    at = _render(payload)
    assert "carries" in _captions(at) and "no dominant-component totals" in _captions(at)
    assert "dominant" not in {metric.label.lower() for metric in at.metric}


def test_the_observations_table_covers_every_recorded_field():
    """A new field on ``PsychologyMarketObservation`` must surface rather
    than be dropped."""
    shown = {field for _, field, _ in observation_fields(COMPONENTS)}
    declared = {field.name for field in dataclasses.fields(PsychologyMarketObservation)}
    assert shown == declared


def test_the_observation_columns_follow_the_reports_own_components(with_events):
    """The component columns are named by the report, not by a list the
    dashboard keeps (the dashboard does not import the psychology
    package)."""
    report, payload, _ = with_events
    at = _render(payload)
    headers = list(at.dataframe[OBSERVATIONS_TABLE].value.columns)
    for component in report.components:
        assert component.component.capitalize() in headers


def test_the_partial_coverage_literal_matches_the_analytics():
    """``psychology_section`` repeats the coverage string rather than
    importing the psychology analytics, so it is pinned here."""
    from crypto_simulator.analytics.psychology_market import COVERAGE_PARTIAL

    assert PARTIAL_COVERAGE == COVERAGE_PARTIAL


def test_the_dashboard_does_not_import_the_psychology_analytics():
    """The containment rule in tests/core/psychology applies to the
    dashboard too: it reads the serialized report instead."""
    import ast

    for module in (psychology_section, __import__(
        "crypto_simulator.dashboard.serialization", fromlist=["x"]
    )):
        tree = ast.parse(Path(module.__file__).read_text())
        imported = {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(
            name.startswith("crypto_simulator.core.psychology")
            or name.startswith("crypto_simulator.analytics.psychology")
            for name in imported
        )


# --- missing psychology ----------------------------------------------------------------------------------


def test_a_run_without_psychology_says_so():
    report, payload, simulation = _section_for(SimulationParams(ticks=10))
    assert report.coverage == COVERAGE_NONE and report.components == ()
    at = _render(payload, simulation)
    assert PSYCHOLOGY_OFF_MESSAGE in [info.value for info in at.info]
    assert at.dataframe.len == 0
    assert f"psychology coverage {COVERAGE_NONE}" in _captions(at)


def test_without_run_metadata_the_message_stays_neutral():
    _, payload, _ = _section_for(SimulationParams(ticks=10))
    at = _render(payload, None)
    assert NO_PSYCHOLOGY_MESSAGE in [info.value for info in at.info]


def test_missing_psychology_is_not_replaced_with_neutral_values():
    """No components at all, rather than four components sitting at a
    neutral value."""
    report, payload, simulation = _section_for(SimulationParams(ticks=10))
    at = _render(payload, simulation)
    shown = _visible_text(at)
    assert report.components == () and report.correlations == ()
    assert at.dataframe.len == 0
    for fabricated in ("0.5000", "0.0000", "neutral", "fear", "fomo"):
        assert fabricated not in shown


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=1, psychology=True),
        SimulationParams(ticks=4, psychology=True),
        SimulationParams(ticks=12, psychology=True, pricing_mode="amm", include_whales=False),
        SimulationParams(ticks=15, psychology=True, random_events=True),
        SimulationParams(ticks=12, psychology=True, scenario="pump_and_dump"),
    ],
    ids=["one-tick", "short", "amm", "random-events", "scenario"],
)
def test_the_section_renders_for_varied_runs(params):
    report, payload, simulation = _section_for(params)
    at = _render(payload, simulation)
    assert not at.exception
    assert f"psychology coverage {report.coverage}" in _captions(at)


# --- wording, determinism and structure ------------------------------------------------------------------


def test_the_visible_wording_stays_descriptive(with_events):
    _, payload, _ = with_events
    shown = _visible_text(_render(payload))
    for word in CAUSAL_WORDS:
        assert word not in shown, f"causal wording on screen: {word}"


def test_associations_are_labelled_as_associations(with_events):
    _, payload, _ = with_events
    shown = _visible_text(_render(payload))
    assert "association" in shown
    assert "correlation" in shown


def test_the_same_payload_renders_the_same_tables(with_events):
    _, payload, _ = with_events
    first, second = _render(payload), _render(payload)
    assert [_rows(first, i) for i in range(first.dataframe.len)] == [
        _rows(second, i) for i in range(second.dataframe.len)
    ]


BANNED_CALLS = {"analyze_psychology", "analyze_psychology_market", "analyze_market", "build_report",
                "fsum", "sum", "round", "abs", "min", "max", "sorted", "mean", "median"}


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


def test_the_psychology_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(psychology_section)


def test_the_psychology_section_does_no_arithmetic():
    assert _arithmetic(psychology_section) == []


def test_the_component_summary_fields_are_all_displayed():
    """A new component figure must surface rather than be dropped."""
    from crypto_simulator.dashboard.psychology_section import COMPONENT_COLUMNS

    scalar_fields = {f.name for f in dataclasses.fields(ComponentSummary)} - {"occupancy", "persistence"}
    headers = {header.lower() for header, _ in COMPONENT_COLUMNS}
    for field in scalar_fields:
        assert field.lower() in headers or field == "count"
