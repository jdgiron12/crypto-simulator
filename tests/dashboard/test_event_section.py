"""The events dashboard section (Phase 10, Step 5).

Every figure on screen must be one ``analyze_event_windows`` produced, so
the checks format the report's own ``EventWindowReport`` and compare
strings. The cases that matter here are the ones the analytics keep apart:
no timeline versus no events in range, recorded provenance versus unknown
provenance, a complete window versus a truncated one, and overlapping
events, which are listed rather than blamed.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics.events import EventGroundTruth
from crypto_simulator.dashboard import event_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.event_section import (
    ALL_EVENTS,
    DETAIL_COLUMNS,
    EVENT_SELECT_KEY,
    GROUND_TRUTH_DETAIL,
    NO_EVENTS_IN_RANGE_MESSAGE,
    NO_TIMELINE_MESSAGE,
    WINDOW_NAMES,
)

PRICE = ",.4f"
VOLUME = ",.0f"
SIGNED = "+.4f"
RETURN = "+.2%"

#: Wording the section must never use: these would turn a description of
#: what happened during a window into a claim about why.
CAUSAL_WORDS = ("caused", "causes", "predicted", "predicts", "drove", "drives", "triggered",
                "influenced", "influence", "resulted in", "led to", "because of", "due to")


def _event_app(events=None, simulation=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.event_section import render_events

    render_events(events, symbol="FIC", simulation=simulation)


def _render(events, simulation=None) -> AppTest:
    return AppTest.from_function(
        _event_app, kwargs={"events": events, "simulation": simulation}, default_timeout=90
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
    return payload.report.event_windows, serialized["report"]["event_windows"], serialized["simulation"]


@pytest.fixture(scope="module")
def scheduled():
    """The demo news schedule: two events with known ground truth."""
    return _section_for(SimulationParams(ticks=60, events=True, psychology=True))


@pytest.fixture(scope="module")
def random_events():
    return _section_for(SimulationParams(ticks=50, random_events=True))


# --- overview --------------------------------------------------------------------------------------------


def test_the_overview_counts_what_the_report_lists(scheduled):
    report, payload, _ = scheduled
    shown = _metrics(_render(payload))
    assert shown["Events observed"] == format(len(report.events), ",d")
    assert shown["Categories"] == format(len(report.categories), ",d")
    assert shown["Ticks analysed"] == format(report.ticks, ",d")


# --- the event table -------------------------------------------------------------------------------------


def test_the_event_table_has_one_row_per_event_in_report_order(scheduled):
    report, payload, _ = scheduled
    rows = _rows(_render(payload), 0)
    assert [row["Event"] for row in rows] == [event.event_id for event in report.events]


def test_event_ground_truth_is_the_reports_own(scheduled):
    report, payload, _ = scheduled
    for row, event in zip(_rows(_render(payload), 0), report.events):
        truth = event.ground_truth
        assert row["Category"] == truth.category
        assert row["Severity"] == format(truth.severity, PRICE)
        assert row["Sentiment"] == format(truth.sentiment, SIGNED)
        assert row["Volatility boost"] == format(truth.volatility_boost, PRICE)
        assert row["Attention"] == format(truth.attention, PRICE)
        assert row["Start"] == str(truth.start_tick)
        assert row["Last active"] == str(truth.last_active_tick)
        assert row["Duration"] == format(truth.duration, ",d")
        assert row["Decay ticks"] == format(truth.decay_ticks, ",d")
        assert row["Expires at"] == str(truth.expires_at)


def test_provenance_is_the_recorded_flag(scheduled, random_events):
    for fixture, expected in ((scheduled, "scheduled"), (random_events, "random")):
        report, payload, _ = fixture
        rows = _rows(_render(payload), 0)
        for row, event in zip(rows, report.events):
            assert event.ground_truth.randomly_generated is (expected == "random")
            assert row["Provenance"] == expected


def test_unknown_provenance_is_shown_as_unknown(scheduled):
    """Without a provenance flag the analytics report ``None``, which the
    section shows rather than guessing from the event id."""
    _, payload, _ = scheduled
    stripped = {
        **payload,
        "events": [
            {**event, "ground_truth": {**event["ground_truth"], "randomly_generated": None}}
            for event in payload["events"]
        ],
    }
    rows = _rows(_render(stripped), 0)
    assert {row["Provenance"] for row in rows} == {"n/a (not recorded)"}


def test_overlap_information_is_the_reports_own(scheduled):
    report, payload, _ = scheduled
    for row, event in zip(_rows(_render(payload), 0), report.events):
        assert row["Overlapping"] == ("yes" if event.overlapping else "no")
        assert row["Overlap count"] == format(event.overlap_count, ",d")
        assert row["Overlapping events"] == (", ".join(event.overlapping_event_ids) or "none")


# --- the window table ------------------------------------------------------------------------------------


def test_every_recorded_window_gets_a_row(scheduled):
    report, payload, _ = scheduled
    rows = _rows(_render(payload), 1)
    expected = [
        (event.event_id, name)
        for event in report.events
        for name in WINDOW_NAMES
        if getattr(event, name) is not None
    ]
    assert [(row["Event"], row["Window"]) for row in rows] == expected


def test_window_figures_are_the_reports_own(scheduled):
    report, payload, _ = scheduled
    rows = {(row["Event"], row["Window"]): row for row in _rows(_render(payload), 1)}
    for event in report.events:
        for name in WINDOW_NAMES:
            window = getattr(event, name)
            if window is None:
                continue
            row = rows[(event.event_id, name)]
            assert row["Requested ticks"] == format(window.ticks_requested, ",d")
            assert row["Observed ticks"] == format(window.ticks_observed, ",d")
            assert row["Complete"] == ("yes" if window.complete else "no")
            assert row["Tick range"] == f"{window.requested_start}-{window.requested_end}"
            assert row["Open"] == format(window.market.open_price, PRICE)
            assert row["Close"] == format(window.market.close_price, PRICE)
            assert row["Return"] == format(window.market.cumulative_return, RETURN)
            assert row["Volume"] == format(window.market.volume_breakdown.total_volume, VOLUME)
            assert row["Volume per tick"] == format(window.volume_per_tick, VOLUME)


def test_returns_are_not_recomputed_from_prices(scheduled):
    """The shown return is the window's own ``cumulative_return``, which
    is not simply close over open (the path includes the pre-run point)."""
    report, payload, _ = scheduled
    window = report.events[0].active
    row = next(r for r in _rows(_render(payload), 1) if r["Window"] == "active")
    assert row["Return"] == format(window.market.cumulative_return, RETURN)
    assert row["Open"] == format(window.market.open_price, PRICE)


def test_an_incomplete_window_is_marked_rather_than_padded():
    """An event near the end of a run cannot observe its whole post
    window; the analytics say so and the section repeats it."""
    report, payload, _ = _section_for(SimulationParams(ticks=16, events=True))
    truncated = [
        (event.event_id, name)
        for event in report.events
        for name in WINDOW_NAMES
        if getattr(event, name) is not None and not getattr(event, name).complete
    ]
    assert truncated, "a 16-tick run should truncate at least one window"
    rows = {(row["Event"], row["Window"]): row for row in _rows(_render(payload), 1)}
    for key in truncated:
        assert rows[key]["Complete"] == "no"
        assert rows[key]["Observed ticks"] != rows[key]["Requested ticks"]


# --- categories ------------------------------------------------------------------------------------------


def test_category_activity_is_the_reports_own(scheduled):
    report, payload, _ = scheduled
    rows = _rows(_render(payload), 2)
    assert [row["Category"] for row in rows] == [c.category for c in report.categories]
    for row, category in zip(rows, report.categories):
        assert row["Events"] == format(category.event_count, ",d")
        assert row["Observed ticks"] == format(category.observed_ticks, ",d")
        assert row["Mean severity"] == format(category.mean_severity, PRICE)
        assert row["Mean sentiment"] == format(category.mean_sentiment, SIGNED)
        assert row["Active return"] == format(category.active_return, RETURN)
        assert row["Post-event return"] == format(category.post_event_return, RETURN)
        assert row["Volume"] == format(category.volume, VOLUME)


# --- detail and selection --------------------------------------------------------------------------------


def test_the_selector_lists_every_event(scheduled):
    report, payload, _ = scheduled
    at = _render(payload)
    assert list(at.selectbox[0].options) == [ALL_EVENTS, *[e.event_id for e in report.events]]
    assert at.table.len == 0


def test_selecting_an_event_shows_its_ground_truth_and_windows(scheduled):
    report, payload, _ = scheduled
    event = report.events[0]
    at = _render(payload)
    at.selectbox(key=EVENT_SELECT_KEY).set_value(event.event_id).run()

    frame = at.table[0].value
    detail = dict(zip(frame.index, frame[DETAIL_COLUMNS[1]]))
    assert detail["Event"] == event.event_id
    assert detail["Headline"] == event.ground_truth.headline
    assert detail["Severity"] == format(event.ground_truth.severity, PRICE)
    assert detail["Randomly generated"] == ("yes" if event.ground_truth.randomly_generated else "no")
    windows = _rows(at, at.dataframe.len - 1)
    assert {row["Event"] for row in windows} == {event.event_id}


def test_the_detail_view_covers_every_ground_truth_field():
    shown = {field for _, field, _ in GROUND_TRUTH_DETAIL}
    assert shown == {field.name for field in dataclasses.fields(EventGroundTruth)}


def test_a_stale_selection_falls_back_to_the_overview(scheduled):
    _, payload, _ = scheduled
    at = AppTest.from_function(
        _event_app, kwargs={"events": payload, "simulation": None}, default_timeout=90
    )
    at.session_state[EVENT_SELECT_KEY] = "whatever-happened"
    at.run()
    assert not at.exception
    assert at.table.len == 0
    assert at.selectbox[0].value == ALL_EVENTS


def test_selecting_an_event_runs_no_simulation():
    def dashboard(runner=None):
        from crypto_simulator.dashboard.view import render_dashboard

        render_dashboard(runner=runner)

    runs = []

    def counting_runner(params):
        runs.append(params)
        return run_simulation(params)

    at = AppTest.from_function(dashboard, kwargs={"runner": counting_runner}, default_timeout=120).run()
    at.number_input(key="coin_dashboard_ticks").set_value(20)
    at.checkbox(key="coin_dashboard_events").set_value(True)
    at.button(key="coin_dashboard_run").click().run()
    assert len(runs) == 1
    before = at.session_state["coin_dashboard_payload"]

    at.selectbox(key=EVENT_SELECT_KEY).set_value("demo-listing").run()
    assert len(runs) == 1
    assert at.session_state["coin_dashboard_payload"] == before
    assert at.table.len > 0


# --- missing data ----------------------------------------------------------------------------------------


def test_a_run_without_a_timeline_says_so():
    report, payload, simulation = _section_for(SimulationParams(ticks=10))
    assert report is None and payload is None
    at = _render(payload, simulation)
    assert NO_TIMELINE_MESSAGE in [info.value for info in at.info]
    assert at.metric.len == 0 and at.dataframe.len == 0


def test_a_timeline_with_no_events_in_range_is_kept_distinct(scheduled):
    """``None`` means no timeline; an empty list means a timeline whose
    events all start outside the analysed ticks."""
    _, payload, _ = scheduled
    empty = {**payload, "events": [], "categories": []}
    at = _render(empty)
    assert NO_EVENTS_IN_RANGE_MESSAGE in [info.value for info in at.info]
    assert NO_TIMELINE_MESSAGE not in [info.value for info in at.info]
    assert f"ticks analysed {payload['ticks']:,d}" in _captions(at)


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=8, events=True),
        SimulationParams(ticks=8, events=True, pricing_mode="amm", include_whales=False),
        SimulationParams(ticks=20, random_events=True, psychology=True),
        SimulationParams(ticks=12, events=True, scenario="wash_trading"),
    ],
    ids=["short", "amm", "random-psychology", "scenario"],
)
def test_the_section_renders_for_varied_runs(params):
    _, payload, simulation = _section_for(params)
    at = _render(payload, simulation)
    assert not at.exception


# --- wording, determinism and structure ------------------------------------------------------------------


def test_the_visible_wording_stays_descriptive(scheduled):
    _, payload, _ = scheduled
    shown = visible_text(_render(payload))
    for word in CAUSAL_WORDS:
        assert word not in shown, f"causal wording on screen: {word}"


def test_the_same_payload_renders_the_same_tables(scheduled):
    _, payload, _ = scheduled
    first, second = _render(payload), _render(payload)
    assert [_rows(first, i) for i in range(first.dataframe.len)] == [
        _rows(second, i) for i in range(second.dataframe.len)
    ]


BANNED_CALLS = {"analyze_event_windows", "analyze_events", "analyze_market", "build_report",
                "fsum", "sum", "round", "abs", "min", "max", "sorted"}


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


def test_the_event_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(event_section)


def test_the_event_section_does_no_arithmetic():
    assert _arithmetic(event_section) == []
