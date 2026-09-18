"""The manipulation dashboard section (Phase 10, Step 6).

Every figure on screen must be one ``analyze_manipulation`` produced, so
the checks format the report's own ``ManipulationReport`` and compare
strings. The cases that matter here are the ones the analytics keep apart:
pump-and-dump versus wash trading, a phase with recorded fills versus one
with none, a strategy the report summarises versus one it has no summary
for, and a run with no manipulation fills at all — none of which may turn
into a fabricated total or a stand-in zero.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics.manipulation import (
    COVERAGE_NONE,
    COVERAGE_PARTIAL,
    ActivityComparison,
    ManipulationReport,
    PumpAndDumpSummary,
    WashSummary,
)
from crypto_simulator.analytics.traders import StrategySummary
from crypto_simulator.dashboard import manipulation_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.manipulation_section import (
    COMPARISON_ROWS,
    NO_MANIPULATION_MESSAGE,
    NO_PUMP_AND_DUMP_MESSAGE,
    NO_SCENARIO_MESSAGE,
    NO_WASH_MESSAGE,
    PHASE_FIELDS,
    SCENARIO_KINDS,
    UNAVAILABLE_MESSAGE,
    WASH_ROWS,
)

PRICE = ",.4f"
VOLUME = ",.0f"
NOTIONAL = ",.2f"
SIGNED_VOLUME = "+,.0f"
SIGNED_NOTIONAL = "+,.2f"
RATIO = ".2%"
RETURN = "+.2%"

#: Wording the section must never use: these would turn a description of
#: what was recorded during a scenario's ticks into a claim about why.
CAUSAL_WORDS = ("caused", "causes", "predicted", "predicts", "drove", "drives", "triggered",
                "influenced", "influence", "resulted in", "led to", "because of", "due to")

#: Table positions, in render order.
SCENARIOS, PHASES, SPANS = 0, 1, 2


def _manipulation_app(manipulation=None, simulation=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.manipulation_section import render_manipulation

    render_manipulation(manipulation, symbol="FIC", simulation=simulation)


def _render(manipulation, simulation=None) -> AppTest:
    return AppTest.from_function(
        _manipulation_app,
        kwargs={"manipulation": manipulation, "simulation": simulation},
        default_timeout=90,
    ).run()


def _metrics(at: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _captions(at: AppTest) -> str:
    return " ".join(caption.value for caption in at.caption)


def _rows(at: AppTest, index: int) -> list[dict[str, str]]:
    return at.dataframe[index].value.to_dict("records")


def _named_table(at: AppTest, column: str) -> list[dict[str, str]]:
    """The first table carrying ``column``, so a test names the table it
    means rather than counting the ones before it."""
    for index in range(at.dataframe.len):
        if column in at.dataframe[index].value.columns:
            return _rows(at, index)
    raise AssertionError(f"no table with a {column!r} column on screen")


def _wash_pairs(at: AppTest) -> dict[str, str]:
    """The wash table (metric and value), as a lookup."""
    return {row["Metric"]: row["Value"] for row in _named_table(at, "Metric")}


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
    return payload.report.manipulation, serialized["report"]["manipulation"], serialized["simulation"]


@pytest.fixture(scope="module")
def pump_and_dump():
    """The pump-and-dump preset: one manipulator running every phase."""
    return _section_for(SimulationParams(ticks=30, scenario="pump_and_dump"))


@pytest.fixture(scope="module")
def wash_trading():
    return _section_for(SimulationParams(ticks=30, scenario="wash_trading"))


@pytest.fixture(scope="module")
def no_manipulation():
    return _section_for(SimulationParams(ticks=20))


# --- overview --------------------------------------------------------------------------------------------


def test_the_overview_shows_the_reports_own_volume_and_shares(pump_and_dump):
    report, payload, _ = pump_and_dump
    shown = _metrics(_render(payload))
    assert shown["Manipulation volume"] == format(report.manipulation_volume, VOLUME)
    assert shown["Manipulation share of total volume"] == format(
        report.manipulation_share_of_total, RATIO)
    assert shown["Manipulation share of participant volume"] == format(
        report.manipulation_share_of_participants, RATIO)
    assert shown["Manipulation active ticks"] == format(report.active_ticks, ",d")


def test_the_overview_captions_carry_the_reports_volume_split(pump_and_dump):
    report, payload, _ = pump_and_dump
    captions = _captions(_render(payload))
    assert f"pump-and-dump volume {report.pump_and_dump_volume:,.0f}" in captions
    assert f"wash volume {report.wash_volume:,.0f}" in captions
    assert f"market volume {report.total_market_volume:,.0f}" in captions
    assert f"participant volume {report.participant_volume:,.0f}" in captions
    assert f"manipulation fills {report.fill_count:,d}" in captions
    assert f"manipulation notional {report.notional:,.2f}" in captions


def test_coverage_is_the_reports_own_word(pump_and_dump, wash_trading):
    for fixture in (pump_and_dump, wash_trading):
        report, payload, _ = fixture
        assert report.coverage == COVERAGE_PARTIAL
        captions = _captions(_render(payload))
        assert f"kinds observed {report.coverage}" in captions
        assert f"active ticks {report.active_ticks:,d}" in captions
        assert f"recorded ticks {report.first_tick}-{report.last_tick}" in captions


# --- the scenario table ----------------------------------------------------------------------------------


def test_the_scenario_table_keeps_the_two_kinds_apart(pump_and_dump):
    _, payload, _ = pump_and_dump
    rows = _rows(_render(payload), SCENARIOS)
    assert [row["Kind"] for row in rows] == [kind for kind, _ in SCENARIO_KINDS]


def test_a_recorded_kind_shows_its_own_strategy_summary(pump_and_dump):
    report, payload, _ = pump_and_dump
    summary = report.pump_and_dump_strategy
    row = _rows(_render(payload), SCENARIOS)[0]
    assert row["Recorded"] == "yes"
    assert row["Strategy"] == summary.strategy
    assert row["Registered manipulation strategy"] == "yes"
    assert row["Traders"] == format(summary.trader_count, ",d")
    assert row["Active traders"] == format(summary.active_trader_count, ",d")
    assert row["Fills"] == format(summary.fill_count, ",d")
    assert row["Buy volume"] == format(summary.buy_volume, VOLUME)
    assert row["Sell volume"] == format(summary.sell_volume, VOLUME)
    assert row["Wash volume"] == format(summary.wash_volume, VOLUME)
    assert row["Total volume"] == format(summary.total_volume, VOLUME)
    assert row["Notional"] == format(summary.total_notional, NOTIONAL)
    assert row["VWAP"] == format(summary.vwap, PRICE)
    assert row["Net coins"] == format(summary.net_coin_flow, SIGNED_VOLUME)
    assert row["Net cash"] == format(summary.net_cash_flow, SIGNED_NOTIONAL)
    assert row["Average fill"] == format(summary.average_fill_size, VOLUME)


def test_a_kind_with_no_summary_is_unavailable_rather_than_zero(pump_and_dump):
    """The analytics report no ``StrategySummary`` for a strategy with no
    recorded fills, which is not the same as a strategy that traded
    nothing."""
    report, payload, _ = pump_and_dump
    assert report.wash_strategy is None
    row = _rows(_render(payload), SCENARIOS)[1]
    assert row["Recorded"] == "no"
    for column in ("Strategy", "Traders", "Fills", "Total volume", "Notional", "VWAP", "P&L"):
        assert row[column] == "n/a", column


def test_the_strategy_pnl_stays_unavailable(pump_and_dump):
    """``analyze_manipulation`` is built from ticks alone, so it carries
    no balances and reports no P&L — never a zero."""
    report, payload, _ = pump_and_dump
    assert report.pump_and_dump_strategy.pnl is None
    assert _rows(_render(payload), SCENARIOS)[0]["P&L"] == "n/a"


def test_the_wash_kind_reads_its_own_summary(wash_trading):
    report, payload, _ = wash_trading
    rows = _rows(_render(payload), SCENARIOS)
    assert rows[0]["Recorded"] == "no"  # no pump-and-dump fills in this run
    assert rows[1]["Recorded"] == "yes"
    assert rows[1]["Strategy"] == report.wash_strategy.strategy
    assert rows[1]["Wash volume"] == format(report.wash_strategy.wash_volume, VOLUME)
    assert rows[1]["Fills"] == format(report.wash_strategy.fill_count, ",d")


# --- pump-and-dump ---------------------------------------------------------------------------------------


def test_every_manipulator_gets_a_row_per_recorded_phase(pump_and_dump):
    report, payload, _ = pump_and_dump
    rows = _rows(_render(payload), PHASES)
    expected = [
        (summary.trader_id, phase)
        for summary in report.pump_and_dump
        for phase, *_ in PHASE_FIELDS
    ]
    assert [(row["Manipulator"], row["Phase"]) for row in rows] == expected


def test_phase_figures_are_the_reports_own(pump_and_dump):
    report, payload, _ = pump_and_dump
    rows = {(row["Manipulator"], row["Phase"]): row for row in _rows(_render(payload), PHASES)}
    for summary in report.pump_and_dump:
        for phase, fills, volume, first, last in PHASE_FIELDS:
            row = rows[(summary.trader_id, phase)]
            assert row["Fills"] == format(getattr(summary, fills), ",d")
            assert row["Volume"] == format(getattr(summary, volume), VOLUME)
            assert row["First tick"] == str(getattr(summary, first))
            assert row["Last tick"] == str(getattr(summary, last))


def test_the_phase_fields_are_the_summarys_own_fields():
    """The table reads declared fields of ``PumpAndDumpSummary``; it never
    works a phase out for itself."""
    declared = {field.name for field in dataclasses.fields(PumpAndDumpSummary)}
    for _, fills, volume, first, last in PHASE_FIELDS:
        assert {fills, volume, first, last} <= declared


def test_a_phase_with_no_recorded_fills_keeps_its_ticks_unavailable(pump_and_dump):
    """A phase the report counted no fills for has no first or last tick —
    which may mean it never ran, or that it lies outside the analysed
    range. The section shows n/a rather than deciding."""
    _, payload, _ = pump_and_dump
    stripped = {
        **payload,
        "pump_and_dump": [
            {**summary, "dump_fills": 0, "dump_volume": 0.0,
             "dump_start_tick": None, "dump_end_tick": None}
            for summary in payload["pump_and_dump"]
        ],
    }
    dump = next(row for row in _rows(_render(stripped), PHASES) if row["Phase"] == "dump")
    assert dump["Fills"] == "0"
    assert dump["First tick"] == "n/a" and dump["Last tick"] == "n/a"


def test_the_span_table_shows_the_recorded_window_and_its_market_summary(pump_and_dump):
    report, payload, _ = pump_and_dump
    rows = _rows(_render(payload), SPANS)
    assert [row["Manipulator"] for row in rows] == [s.trader_id for s in report.pump_and_dump]
    for row, summary in zip(rows, report.pump_and_dump):
        market = summary.market
        assert row["Observed ticks"] == f"{summary.first_tick}-{summary.last_tick}"
        assert row["Duration"] == format(summary.duration, ",d")
        assert row["Total fills"] == format(summary.total_fills, ",d")
        assert row["Total volume"] == format(summary.total_volume, VOLUME)
        assert row["Price at accumulation start"] == format(
            summary.price_at_accumulation_start, PRICE)
        assert row["Price at dump start"] == format(summary.price_at_dump_start, PRICE)
        assert row["Open"] == format(market.open_price, PRICE)
        assert row["Close"] == format(market.close_price, PRICE)
        assert row["Return over span"] == format(market.cumulative_return, RETURN)
        assert row["High"] == format(market.high_price, PRICE)
        assert row["High tick"] == str(market.high_tick)
        assert row["Low"] == format(market.low_price, PRICE)
        assert row["Max drawdown"] == format(market.max_drawdown, RATIO)
        assert row["Ticks in span"] == format(market.ticks, ",d")


def test_the_span_return_is_not_recomputed_from_the_shown_prices(pump_and_dump):
    """``cumulative_return`` is ``analyze_market``'s own figure over the
    span, which is not simply close over open."""
    report, payload, _ = pump_and_dump
    summary = report.pump_and_dump[0]
    row = _rows(_render(payload), SPANS)[0]
    assert row["Return over span"] == format(summary.market.cumulative_return, RETURN)


def test_a_run_with_no_pump_and_dump_fills_says_so(wash_trading):
    report, payload, _ = wash_trading
    assert report.pump_and_dump == ()
    at = _render(payload)
    assert NO_PUMP_AND_DUMP_MESSAGE in [info.value for info in at.info]


# --- wash trading ----------------------------------------------------------------------------------------


def test_the_wash_table_is_the_reports_own_record(wash_trading):
    report, payload, _ = wash_trading
    shown = _wash_pairs(_render(payload))
    wash = report.wash
    assert shown["Wash legs"] == format(wash.fill_count, ",d")
    assert shown["Wash volume"] == format(wash.volume, VOLUME)
    assert shown["Wash buy volume"] == format(wash.buy_volume, VOLUME)
    assert shown["Wash sell volume"] == format(wash.sell_volume, VOLUME)
    assert shown["Wash notional"] == format(wash.notional, NOTIONAL)
    assert shown["Active ticks"] == format(wash.active_ticks, ",d")
    assert shown["First tick"] == str(wash.first_tick)
    assert shown["Last tick"] == str(wash.last_tick)
    assert shown["Average volume per active tick"] == format(
        wash.average_volume_per_active_tick, VOLUME)


def test_the_wash_table_covers_every_field_of_the_wash_summary():
    shown = {field for _, field, _ in WASH_ROWS}
    assert shown == {field.name for field in dataclasses.fields(WashSummary)}


def test_a_run_with_no_wash_legs_keeps_its_recorded_zeros(pump_and_dump):
    """Trader fills are always fully recorded, so no wash legs is an
    observation: the counts stay zero and the timing stays n/a."""
    report, payload, _ = pump_and_dump
    assert report.wash.fill_count == 0
    at = _render(payload)
    assert NO_WASH_MESSAGE in [info.value for info in at.info]
    shown = _wash_pairs(at)
    assert shown["Wash legs"] == "0"
    assert shown["Wash volume"] == "0"
    assert shown["First tick"] == "n/a"
    assert shown["Last tick"] == "n/a"
    assert shown["Average volume per active tick"] == "n/a"


# --- the comparison --------------------------------------------------------------------------------------


def test_the_comparison_is_the_reports_own_pairing(wash_trading):
    report, payload, _ = wash_trading
    comparison = report.activity_comparison
    rows = {row["Figure"]: row for row in _named_table(_render(payload), "Figure")}
    assert rows["Volume"]["Manipulation"] == format(comparison.manipulation_volume, VOLUME)
    assert rows["Volume"]["Organic"] == format(comparison.organic_volume, VOLUME)
    assert rows["Buy volume"]["Manipulation"] == format(comparison.manipulation_buy_volume, VOLUME)
    assert rows["Sell volume"]["Organic"] == format(comparison.organic_sell_volume, VOLUME)
    assert rows["Notional"]["Manipulation"] == format(comparison.manipulation_notional, NOTIONAL)
    assert rows["Active ticks"]["Organic"] == format(comparison.organic_active_ticks, ",d")
    assert rows["Average fill size"]["Manipulation"] == format(
        comparison.manipulation_average_fill_size, VOLUME)
    assert f"manipulation share of the two {comparison.manipulation_volume_share:.2%}" in _captions(
        _render(payload))


def test_the_comparison_reads_only_fields_the_analytics_declare():
    declared = {field.name for field in dataclasses.fields(ActivityComparison)}
    for _, left, right, _kind in COMPARISON_ROWS:
        assert left in declared and right in declared


# --- missing manipulation data ---------------------------------------------------------------------------


def test_a_run_without_a_scenario_reports_no_manipulation(no_manipulation):
    report, payload, simulation = no_manipulation
    assert report.coverage == COVERAGE_NONE
    at = _render(payload, simulation)
    assert NO_SCENARIO_MESSAGE in [info.value for info in at.info]
    assert at.dataframe.len == 0
    assert at.metric.len == 0
    assert f"kinds observed {COVERAGE_NONE}" in _captions(at)


def test_no_manipulation_without_the_runs_parameters_says_so_plainly(no_manipulation):
    _, payload, _ = no_manipulation
    at = _render(payload, {"params": {"scenario": "pump_and_dump"}})
    assert NO_MANIPULATION_MESSAGE in [info.value for info in at.info]


def test_a_missing_manipulation_report_is_not_an_empty_one():
    at = _render(None)
    assert UNAVAILABLE_MESSAGE in [info.value for info in at.info]
    assert at.dataframe.len == 0 and at.metric.len == 0


def test_unavailable_shares_stay_unavailable(pump_and_dump):
    """A share the analytics could not compute (a zero denominator) is
    n/a, never zero."""
    _, payload, _ = pump_and_dump
    stripped = {**payload, "manipulation_share_of_total": None,
                "manipulation_share_of_participants": None}
    shown = _metrics(_render(stripped))
    assert shown["Manipulation share of total volume"] == "n/a"
    assert shown["Manipulation share of participant volume"] == "n/a"


def test_a_short_run_renders_without_manipulation_analytics():
    _, payload, simulation = _section_for(SimulationParams(ticks=1))
    at = _render(payload, simulation)
    assert not at.exception
    assert NO_SCENARIO_MESSAGE in [info.value for info in at.info]


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=8, scenario="pump_and_dump"),
        SimulationParams(ticks=25, scenario="wash_trading"),
        SimulationParams(ticks=25, pricing_mode="amm", include_whales=False,
                         scenario="pump_and_dump"),
        SimulationParams(ticks=25, pricing_mode="amm", include_whales=False,
                         scenario="wash_trading"),
        SimulationParams(ticks=20, scenario="pump_and_dump", events=True, psychology=True),
    ],
    ids=["short", "wash", "amm-pump", "amm-wash", "events"],
)
def test_the_section_renders_for_varied_runs(params):
    _, payload, simulation = _section_for(params)
    at = _render(payload, simulation)
    assert not at.exception


def test_an_incomplete_scenario_window_is_not_completed_here():
    """A run that stops inside the scheme records only the phases it
    reached; the section shows exactly those."""
    report, payload, _ = _section_for(SimulationParams(ticks=8, scenario="pump_and_dump"))
    summary = report.pump_and_dump[0]
    assert summary.dump_fills == 0 and summary.dump_start_tick is None
    rows = {row["Phase"]: row for row in _rows(_render(payload), PHASES)}
    assert rows["accumulate"]["Fills"] == format(summary.accumulation_fills, ",d")
    assert rows["dump"]["Fills"] == "0"
    assert rows["dump"]["First tick"] == "n/a"


# --- wording, determinism and structure ------------------------------------------------------------------


def test_the_visible_wording_stays_descriptive(pump_and_dump, wash_trading, no_manipulation):
    for fixture in (pump_and_dump, wash_trading, no_manipulation):
        _, payload, simulation = fixture
        shown = visible_text(_render(payload, simulation))
        for word in CAUSAL_WORDS:
            assert word not in shown, f"causal wording on screen: {word}"


def test_the_section_claims_no_scenario_completeness(pump_and_dump):
    """Coverage names the kinds observed; the section says so rather than
    presenting it as a finished scenario."""
    _, payload, _ = pump_and_dump
    captions = _captions(_render(payload))
    assert "kinds" in captions.lower()
    assert "cannot tell a phase that never ran" in captions


def test_the_same_payload_renders_the_same_tables(pump_and_dump):
    _, payload, _ = pump_and_dump
    first, second = _render(payload), _render(payload)
    assert [_rows(first, i) for i in range(first.dataframe.len)] == [
        _rows(second, i) for i in range(second.dataframe.len)
    ]


def test_the_partial_coverage_literal_is_the_analytics_constant():
    assert COVERAGE_PARTIAL == "partial" and COVERAGE_NONE == "none"


def test_every_manipulation_report_field_is_available_to_the_section(pump_and_dump):
    """A guard against the payload and the section drifting apart."""
    _, payload, _ = pump_and_dump
    assert set(payload) >= {field.name for field in dataclasses.fields(ManipulationReport)}
    assert {"total_volume", "total_fills"} <= set(payload["pump_and_dump"][0])
    assert {field.name for field in dataclasses.fields(StrategySummary)} <= set(
        payload["pump_and_dump_strategy"])


BANNED_CALLS = {"analyze_manipulation", "analyze_market", "analyze_traders", "build_report",
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


def test_the_manipulation_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(manipulation_section)


def test_the_manipulation_section_does_no_arithmetic():
    assert _arithmetic(manipulation_section) == []


def test_the_manipulation_section_reaggregates_no_trades():
    """It reads the report only: nothing reaches for a tick's own fills."""
    source = Path(manipulation_section.__file__).read_text()
    for banned in ("trader_trades", "price_series", "SimulationTick", "TradeAction",
                   "MANIPULATION_STRATEGIES", "run_simulation"):
        assert banned not in source
