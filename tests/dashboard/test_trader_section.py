"""The trader dashboard section (Phase 10, Step 3).

Every figure on screen must be one ``analyze_traders`` produced, so the
checks format the report's own ``TraderReport``/``TraderSummary``/
``StrategySummary`` values and compare strings — never a number the test
worked out for itself. P&L and VWAP get their own checks because they are
the easiest things to accidentally recompute. The rest covers both pricing
modes, the strategy grouping, the selector (which must filter and nothing
more), and the runs whose analytics legitimately have nothing to report.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics import build_report
from crypto_simulator.analytics.traders import StrategySummary, TraderSummary
from crypto_simulator.config import get_settings
from crypto_simulator.dashboard import trader_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.serialization import DERIVED_FIELDS, report_to_dict
from crypto_simulator.dashboard.trader_section import (
    ALL_TRADERS,
    DETAIL_COLUMNS,
    DETAIL_ROWS,
    NO_FEES_MESSAGE,
    NO_PNL_MESSAGE,
    NO_TRADERS_MESSAGE,
    TRADER_SELECT_KEY,
    UNLABELLED_STRATEGY,
)
from crypto_simulator.services.coin_simulation import build_coin_simulator

PRICE = ",.4f"
VOLUME = ",.0f"
NOTIONAL = ",.2f"
SIGNED_VOLUME = "+,.0f"
SIGNED_NOTIONAL = "+,.2f"
RETURN = "+.2%"
RATIO = ".2%"


def _trader_app(traders=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.trader_section import render_traders

    render_traders(traders, symbol="FIC")


def _render(traders: dict) -> AppTest:
    return AppTest.from_function(
        _trader_app, kwargs={"traders": traders}, default_timeout=60
    ).run()


def _metrics(at: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _captions(at: AppTest) -> str:
    return " ".join(caption.value for caption in at.caption)


def _rows(at: AppTest, index: int) -> list[dict[str, str]]:
    return at.dataframe[index].value.to_dict("records")


def _strategy_rows(at: AppTest) -> list[dict[str, str]]:
    return _rows(at, 0)


def _activity_rows(at: AppTest) -> list[dict[str, str]]:
    return _rows(at, 1)


def _performance_rows(at: AppTest) -> list[dict[str, str]]:
    return _rows(at, 2)


@pytest.fixture(scope="module")
def random_walk():
    """A run with every strategy, a manipulator and four traders who never
    fill — so labelled, unlabelled, active and inactive all appear."""
    payload = run_simulation(SimulationParams(ticks=30, scenario="pump_and_dump"))
    return payload.report.traders, payload_to_dict(payload)["report"]["traders"]


@pytest.fixture(scope="module")
def amm():
    payload = run_simulation(
        SimulationParams(ticks=30, pricing_mode="amm", include_whales=False, scenario="wash_trading")
    )
    return payload.report.traders, payload_to_dict(payload)["report"]["traders"]


def _report_without_balances(ticks: int = 10):
    """A report built the way a caller who kept no wallet snapshots would
    get it: every balance-based figure is None."""
    settings = get_settings()
    sim = build_coin_simulator(settings)
    recorded = sim.run(ticks)
    report = build_report(recorded, initial_price=settings.coin.starting_price)
    return report.traders, report_to_dict(report)["traders"]


# --- overview --------------------------------------------------------------------------------------------


def test_overview_totals_are_the_reports_own(random_walk):
    report, payload = random_walk
    shown = _metrics(_render(payload))
    assert shown["Traders active"] == f"{report.active_traders} of {report.population}"
    assert shown["Participation"] == format(report.participation_rate, ".0%")
    assert shown["Trader fills"] == format(report.fill_count, ",d")
    assert shown["Trader volume"] == format(report.total_volume, VOLUME)
    assert shown["Trader notional"] == format(report.total_notional, NOTIONAL)
    assert shown["VWAP (all fills)"] == format(report.vwap, PRICE)


def test_overview_flows_and_performance_are_the_reports_own(random_walk):
    report, payload = random_walk
    shown = _metrics(_render(payload))
    assert shown["Net coin flow"] == format(report.net_coin_flow, SIGNED_VOLUME)
    assert shown["Net cash flow"] == format(report.net_cash_flow, SIGNED_NOTIONAL)
    assert shown["Combined P&L"] == format(report.pnl, SIGNED_NOTIONAL)
    assert shown["Combined return"] == format(report.equity_return, RETURN)
    assert shown["Start equity"] == format(report.start_equity, NOTIONAL)
    assert shown["End equity"] == format(report.end_equity, NOTIONAL)


def test_overview_captions_carry_the_remaining_totals(random_walk):
    report, payload = random_walk
    captions = _captions(_render(payload))
    assert (f"buy / sell / wash volume {format(report.buy_volume, VOLUME)} / "
            f"{format(report.sell_volume, VOLUME)} / {format(report.wash_volume, VOLUME)}") in captions
    assert (f"filled {format(report.filled_volume, VOLUME)} of requested "
            f"{format(report.requested_volume, VOLUME)}") in captions
    assert f"(ratio {format(report.fill_ratio, RATIO)})" in captions
    assert f"final price {format(report.final_price, PRICE)}" in captions
    assert f"ticks {format(report.ticks, ',d')}" in captions
    assert f"pricing mode {report.pricing_mode}" in captions


def test_random_walk_says_why_there_are_no_fees(random_walk):
    report, payload = random_walk
    assert report.fees_paid_cash is None and report.fees_paid_coins is None
    assert NO_FEES_MESSAGE in _captions(_render(payload))


def test_amm_fees_are_the_reports_own(amm):
    report, payload = amm
    captions = _captions(_render(payload))
    assert f"{format(float(report.fees_paid_cash), NOTIONAL)} cash" in captions
    assert f"{format(float(report.fees_paid_coins), PRICE)} coins" in captions


# --- strategies ------------------------------------------------------------------------------------------


def test_the_strategy_table_is_the_reports_own_grouping(random_walk):
    report, payload = random_walk
    rows = _strategy_rows(_render(payload))
    assert len(rows) == len(report.strategies)
    for row, strategy in zip(rows, report.strategies):
        expected = strategy.strategy or UNLABELLED_STRATEGY
        assert row["Strategy"].removesuffix(" *") == expected
        assert row["Traders active"] == f"{strategy.active_trader_count} of {strategy.trader_count}"
        assert row["Fills"] == format(strategy.fill_count, ",d")
        assert row["Volume"] == format(strategy.total_volume, VOLUME)
        assert row["Notional"] == format(strategy.total_notional, NOTIONAL)
        assert row["Participation"] == format(strategy.participation, RATIO)


def test_strategy_performance_columns_are_the_reports_own(random_walk):
    report, payload = random_walk
    rows = _strategy_rows(_render(payload))
    for row, strategy in zip(rows, report.strategies):
        assert row["P&L"] == (
            "n/a" if strategy.pnl is None else format(strategy.pnl, SIGNED_NOTIONAL)
        )
        assert row["VWAP"] == ("n/a" if strategy.vwap is None else format(strategy.vwap, PRICE))
        assert row["Net coins"] == format(strategy.net_coin_flow, SIGNED_VOLUME)
        assert row["Buy volume"] == format(strategy.buy_volume, VOLUME)
        assert row["Sell volume"] == format(strategy.sell_volume, VOLUME)
        assert row["Wash volume"] == format(strategy.wash_volume, VOLUME)


def test_a_manipulation_strategy_is_marked_by_its_recorded_label(random_walk):
    report, payload = random_walk
    rows = _strategy_rows(_render(payload))
    marked = {row["Strategy"] for row in rows if row["Strategy"].endswith(" *")}
    expected = {f"{s.strategy} *" for s in report.strategies if s.is_manipulation_strategy}
    assert marked == expected and expected


def test_traders_known_only_from_balances_are_labelled_as_such(random_walk):
    report, payload = random_walk
    assert any(strategy.strategy is None for strategy in report.strategies)
    assert UNLABELLED_STRATEGY in {row["Strategy"] for row in _strategy_rows(_render(payload))}


def test_the_missing_strategy_return_is_explained(random_walk):
    """``StrategySummary`` has no return field, so none is shown."""
    _, payload = random_walk
    assert "equity_return" not in {f.name for f in dataclasses.fields(StrategySummary)}
    assert "define no strategy-level return" in _captions(_render(payload))


# --- per-trader tables -----------------------------------------------------------------------------------


def test_the_activity_table_has_one_row_per_trader_in_report_order(random_walk):
    report, payload = random_walk
    rows = _activity_rows(_render(payload))
    assert [row["Trader"] for row in rows] == [t.trader_id for t in report.traders]


def test_activity_figures_are_the_reports_own(random_walk):
    report, payload = random_walk
    for row, trader in zip(_activity_rows(_render(payload)), report.traders):
        assert row["Fills"] == format(trader.fill_count, ",d")
        assert row["Buy qty"] == format(trader.buy_volume, VOLUME)
        assert row["Sell qty"] == format(trader.sell_volume, VOLUME)
        assert row["Wash qty"] == format(trader.wash_volume, VOLUME)
        assert row["Volume"] == format(trader.total_volume, VOLUME)
        assert row["Active ticks"] == format(trader.active_ticks, ",d")
        assert row["Active"] == ("yes" if trader.active else "no")
        assert row["Fill ratio"] == (
            "n/a" if trader.fill_ratio is None else format(trader.fill_ratio, RATIO)
        )


def test_the_fill_span_is_the_reports_first_and_last_fill_ticks(random_walk):
    report, payload = random_walk
    for row, trader in zip(_activity_rows(_render(payload)), report.traders):
        if trader.first_fill_tick is None:
            assert row["Fill ticks"] == "n/a"
        else:
            assert row["Fill ticks"] == f"{trader.first_fill_tick}-{trader.last_fill_tick}"


def test_performance_figures_are_the_reports_own(random_walk):
    report, payload = random_walk
    for row, trader in zip(_performance_rows(_render(payload)), report.traders):
        assert row["Trader"] == trader.trader_id
        assert row["Notional"] == format(trader.total_notional, NOTIONAL)
        assert row["Net coins"] == format(trader.net_coin_flow, SIGNED_VOLUME)
        assert row["Net cash"] == format(trader.net_cash_flow, SIGNED_NOTIONAL)
        assert row["End cash"] == format(trader.end_cash, NOTIONAL)
        assert row["End coins"] == format(trader.end_coins, VOLUME)
        assert row["End equity"] == format(trader.end_equity, NOTIONAL)


def test_pnl_and_return_are_the_analytics_values_not_recomputed(random_walk):
    """The dashboard shows ``analyze_traders``' P&L exactly; it does not
    subtract equities or value wallets itself."""
    report, payload = random_walk
    for row, trader in zip(_performance_rows(_render(payload)), report.traders):
        assert row["P&L"] == format(trader.pnl, SIGNED_NOTIONAL)
        assert row["Return"] == (
            "n/a" if trader.equity_return is None else format(trader.equity_return, RETURN)
        )


def test_vwap_is_the_analytics_value_and_missing_without_fills(random_walk):
    report, payload = random_walk
    rows = _performance_rows(_render(payload))
    assert any(trader.vwap is None for trader in report.traders)
    for row, trader in zip(rows, report.traders):
        assert row["VWAP"] == ("n/a" if trader.vwap is None else format(trader.vwap, PRICE))


def test_wash_share_is_the_recorded_classification(amm):
    report, payload = amm
    rows = _performance_rows(_render(payload))
    assert any(trader.wash_volume for trader in report.traders)
    for row, trader in zip(rows, report.traders):
        assert row["Wash share"] == (
            "n/a" if trader.wash_share is None else format(trader.wash_share, RATIO)
        )


def test_amm_fee_columns_carry_the_per_trader_fees(amm):
    report, payload = amm
    for row, trader in zip(_performance_rows(_render(payload)), report.traders):
        assert row["Fees (cash)"] == format(float(trader.fees_paid_cash), NOTIONAL)
        assert row["Fees (coins)"] == format(float(trader.fees_paid_coins), PRICE)


def test_random_walk_has_no_per_trader_fees(random_walk):
    report, payload = random_walk
    assert all(trader.fees_paid_cash is None for trader in report.traders)
    assert {row["Fees (cash)"] for row in _performance_rows(_render(payload))} == {"n/a"}


# --- detail and selection --------------------------------------------------------------------------------


def test_the_selector_lists_every_trader(random_walk):
    report, payload = random_walk
    at = _render(payload)
    assert list(at.selectbox[0].options) == [ALL_TRADERS, *[t.trader_id for t in report.traders]]
    assert at.table.len == 0  # nothing selected yet


def test_selecting_a_trader_shows_that_traders_recorded_figures(random_walk):
    report, payload = random_walk
    trader = next(t for t in report.traders if t.fill_count)
    at = _render(payload)
    at.selectbox(key=TRADER_SELECT_KEY).set_value(trader.trader_id).run()

    frame = at.table[0].value
    detail = dict(zip(frame.index, frame[DETAIL_COLUMNS[1]]))
    assert detail["Trader"] == trader.trader_id
    assert detail["Strategy"] == trader.strategy
    assert detail["Fills"] == format(trader.fill_count, ",d")
    assert detail["Total volume"] == format(trader.total_volume, VOLUME)
    assert detail["VWAP"] == format(trader.vwap, PRICE)
    assert detail["P&L"] == format(trader.pnl, SIGNED_NOTIONAL)
    assert detail["Return"] == format(trader.equity_return, RETURN)
    assert detail["Start cash"] == format(trader.start_cash, NOTIONAL)
    assert detail["Start coins"] == format(trader.start_coins, VOLUME)
    assert detail["Start equity"] == format(trader.start_equity, NOTIONAL)
    assert detail["Requested volume"] == format(trader.requested_volume, VOLUME)


def test_the_detail_view_covers_every_recorded_field():
    """If the analytics gain a trader field, the detail view must show
    it rather than silently dropping it."""
    shown = {field for _, field, _ in DETAIL_ROWS}
    declared = {field.name for field in dataclasses.fields(TraderSummary)}
    assert declared <= shown
    assert set(DERIVED_FIELDS[TraderSummary]) <= shown
    assert shown == declared | set(DERIVED_FIELDS[TraderSummary])


def test_an_inactive_traders_detail_keeps_its_gaps(random_walk):
    report, payload = random_walk
    trader = next(t for t in report.traders if not t.fill_count)
    at = _render(payload)
    at.selectbox(key=TRADER_SELECT_KEY).set_value(trader.trader_id).run()
    frame = at.table[0].value
    detail = dict(zip(frame.index, frame[DETAIL_COLUMNS[1]]))
    assert detail["Active"] == "no"
    assert detail["VWAP"] == "n/a"
    assert detail["First fill tick"] == "n/a"
    assert detail["Average fill size"] == "n/a"
    assert detail["Fills"] == "0"


def test_a_stale_selection_falls_back_to_the_overview(random_walk):
    """A trader from another run's population is no longer an option."""
    _, payload = random_walk
    at = AppTest.from_function(_trader_app, kwargs={"traders": payload}, default_timeout=60)
    at.session_state[TRADER_SELECT_KEY] = "whoever-1"
    at.run()
    assert not at.exception
    assert at.table.len == 0
    assert at.selectbox[0].value == ALL_TRADERS


def test_selecting_a_trader_runs_no_simulation():
    """The selector filters the payload already on screen."""

    def dashboard(runner=None):
        from crypto_simulator.dashboard.view import render_dashboard

        render_dashboard(runner=runner)

    runs = []

    def counting_runner(params):
        runs.append(params)
        return run_simulation(params)

    at = AppTest.from_function(dashboard, kwargs={"runner": counting_runner}, default_timeout=90).run()
    at.number_input(key="coin_dashboard_ticks").set_value(8)
    at.button(key="coin_dashboard_run").click().run()
    assert len(runs) == 1
    before = at.session_state["coin_dashboard_payload"]

    at.selectbox(key=TRADER_SELECT_KEY).set_value("retail-1").run()
    assert len(runs) == 1
    assert at.session_state["coin_dashboard_payload"] == before
    assert at.table.len > 0


# --- missing data ----------------------------------------------------------------------------------------


def test_a_run_without_traders_says_so():
    payload = run_simulation(SimulationParams(ticks=6, include_traders=False))
    traders = payload_to_dict(payload)["report"]["traders"]
    at = _render(traders)
    assert not at.exception
    assert payload.report.traders.population == 0
    assert NO_TRADERS_MESSAGE in [info.value for info in at.info]
    assert at.metric.len == 0
    assert at.dataframe.len == 0


def test_without_balances_equity_and_pnl_stay_unavailable():
    report, payload = _report_without_balances()
    at = _render(payload)
    shown = _metrics(at)
    assert report.pnl is None and report.start_equity is None
    assert shown["Combined P&L"] == "n/a"
    assert shown["Combined return"] == "n/a"
    assert shown["Start equity"] == "n/a"
    assert shown["End equity"] == "n/a"
    assert NO_PNL_MESSAGE in _captions(at)
    assert {row["P&L"] for row in _performance_rows(at)} == {"n/a"}
    assert {row["End equity"] for row in _performance_rows(at)} == {"n/a"}


def test_missing_values_are_never_shown_as_zero():
    report, payload = _report_without_balances()
    rows = _performance_rows(_render(payload))
    assert all(row["End cash"] == "n/a" for row in rows)
    assert all(trader.end_cash is None for trader in report.traders)


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=1),
        SimulationParams(ticks=3, include_whales=False),
        SimulationParams(ticks=3, pricing_mode="amm", include_whales=False),
        SimulationParams(ticks=6, events=True, psychology=True),
        SimulationParams(ticks=12, scenario="wash_trading"),
    ],
    ids=["one-tick", "no-whales", "amm", "events-psychology", "wash"],
)
def test_the_section_renders_for_sparse_runs(params):
    payload = run_simulation(params)
    at = _render(payload_to_dict(payload)["report"]["traders"])
    assert not at.exception
    report = payload.report.traders
    assert _metrics(at)["Traders active"] == f"{report.active_traders} of {report.population}"


# --- determinism and structure ---------------------------------------------------------------------------


def test_the_same_payload_renders_the_same_tables(random_walk):
    _, payload = random_walk
    first, second = _render(payload), _render(payload)
    assert _activity_rows(first) == _activity_rows(second)
    assert _performance_rows(first) == _performance_rows(second)
    assert _strategy_rows(first) == _strategy_rows(second)
    assert _metrics(first) == _metrics(second)


BANNED_CALLS = {"analyze_traders", "analyze_market", "build_report", "fsum", "sum", "round", "abs",
                "min", "max", "sorted"}


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


def test_the_trader_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(trader_section)


def test_the_trader_section_does_no_arithmetic():
    """Every trader figure arrives computed; the section only formats."""
    assert _arithmetic(trader_section) == []
