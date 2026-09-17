"""The market dashboard section (Phase 10, Step 2).

Every figure on screen must be a value the report holds, so the checks
format the report's own ``MarketSummary`` and compare strings — never a
number the test computed for itself. The rest covers the chart's data,
both pricing modes, and runs whose analytics legitimately have nothing to
report (no ticks, one tick, no supply, no whales, no events), which must
render as ``n/a`` rather than zero and must not crash.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics import build_report
from crypto_simulator.config import get_settings
from crypto_simulator.dashboard import market_section
from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
from crypto_simulator.dashboard.market_section import NO_TICKS_MESSAGE, STATISTICS_COLUMNS
from crypto_simulator.dashboard.serialization import report_to_dict
from crypto_simulator.services.coin_simulation import build_coin_simulator

PRICE = ",.4f"
VOLUME = ",.0f"
RETURN = "+.2%"
RATIO = ".2%"


def _market_app(payload=None):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.market_section import render_market

    render_market(
        payload["report"]["market"],
        symbol=payload["simulation"]["coin_symbol"],
        price_series=payload["price_series"],
        scope=(payload["report"]["start_tick"], payload["report"]["end_tick"]),
    )


def _render(payload_dict) -> AppTest:
    return AppTest.from_function(
        _market_app, kwargs={"payload": payload_dict}, default_timeout=60
    ).run()


def _payload_dict_for(report, *, price_series=(), symbol="FIC") -> dict:
    """A payload-shaped dict for a report built directly, so a run the
    dashboard controls cannot produce (no total supply, no ticks) can
    still be rendered. The report goes through the real serializer."""
    return {
        "simulation": {"coin_symbol": symbol},
        "report": report_to_dict(report),
        "price_series": [dict(point) for point in price_series],
    }


def _metrics(at: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in at.metric}


def _captions(at: AppTest) -> str:
    return " ".join(caption.value for caption in at.caption)


def _table(at: AppTest, index: int) -> dict[str, str]:
    """A rendered label/value table, as a mapping."""
    frame = at.table[index].value
    return dict(zip(frame.index, frame[STATISTICS_COLUMNS[1]]))


def _statistics(at: AppTest) -> dict[str, str]:
    return _table(at, -1)


def _volume_table(at: AppTest) -> dict[str, str]:
    return _table(at, 0)


@pytest.fixture(scope="module")
def random_walk():
    payload = run_simulation(SimulationParams(ticks=30, events=True, whale_observation=True))
    return payload, payload_to_dict(payload)


@pytest.fixture(scope="module")
def amm():
    payload = run_simulation(
        SimulationParams(ticks=30, pricing_mode="amm", include_whales=False, scenario="wash_trading")
    )
    return payload, payload_to_dict(payload)


# --- price overview --------------------------------------------------------------------------------------


def test_price_figures_are_the_reports_own(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    shown = _metrics(_render(payload_dict))
    assert shown["Close price"] == format(market.close_price, PRICE)
    assert shown["Open price"] == format(market.open_price, PRICE)
    assert shown["High"] == format(market.high_price, PRICE)
    assert shown["Low"] == format(market.low_price, PRICE)
    assert shown["Mean price"] == format(market.mean_price, PRICE)
    assert shown["Return"] == format(market.cumulative_return, RETURN)


def test_the_high_and_low_ticks_come_from_the_report(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    captions = _captions(_render(payload_dict))
    assert f"high at tick {market.high_tick}" in captions
    assert f"low at tick {market.low_tick}" in captions


def test_the_tick_range_is_the_reports_range(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    statistics = _statistics(_render(payload_dict))
    assert statistics["Tick range"] == f"{market.first_tick}-{market.last_tick}"
    assert statistics["Ticks analysed"] == format(market.ticks, ",d")


def test_a_scoped_report_shows_the_requested_range(random_walk):
    """``SimulationReport`` carries the requested scope, so a windowed run
    is not reported as a full one."""
    payload, _ = random_walk
    settings = get_settings()
    sim = build_coin_simulator(settings)
    ticks = sim.run(20)
    report = build_report(ticks, initial_price=settings.coin.starting_price,
                          total_supply=settings.coin.initial_supply, start_tick=5, end_tick=15)
    statistics = _statistics(_render(_payload_dict_for(report)))
    assert statistics["Requested range"] == "5-15"
    assert statistics["Tick range"] == f"{report.market.first_tick}-{report.market.last_tick}"


# --- volume ----------------------------------------------------------------------------------------------


def test_volume_figures_are_the_reports_own(random_walk):
    payload, payload_dict = random_walk
    volume = payload.report.market.volume_breakdown
    at = _render(payload_dict)
    table = _volume_table(at)
    assert _metrics(at)["Total volume"] == format(volume.total_volume, VOLUME)
    assert table["Total volume"] == format(volume.total_volume, VOLUME)
    assert table["Background (synthetic)"] == format(volume.background_volume, VOLUME)
    assert table["Whale"] == format(volume.whale_volume, VOLUME)
    assert table["Organic traders"] == format(volume.organic_volume, VOLUME)
    assert table["Manipulators"] == format(volume.manipulator_volume, VOLUME)
    assert table["Wash legs"] == format(volume.wash_volume, VOLUME)


def test_participant_volume_is_the_analytics_property_not_a_frontend_sum(random_walk):
    payload, payload_dict = random_walk
    volume = payload.report.market.volume_breakdown
    table = _volume_table(_render(payload_dict))
    assert table["Participants (whale + organic + manipulator)"] == format(
        volume.participant_volume, VOLUME
    )
    assert table["Fills in total"] == format(volume.fills, ",d")


def test_fill_counts_are_the_reports_own(random_walk):
    payload, payload_dict = random_walk
    volume = payload.report.market.volume_breakdown
    table = _volume_table(_render(payload_dict))
    assert table["Whale fills"] == format(volume.whale_fills, ",d")
    assert table["Organic fills"] == format(volume.organic_fills, ",d")
    assert table["Manipulator fills"] == format(volume.manipulator_fills, ",d")
    assert table["Wash legs recorded"] == format(volume.wash_legs, ",d")
    assert table["Zero-quantity whale trades"] == format(volume.zero_quantity_whale_trades, ",d")


# --- volatility, drawdown, valuation ---------------------------------------------------------------------


def test_volatility_figures_are_the_reports_own(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    at = _render(payload_dict)
    shown = _metrics(at)
    assert shown["Volatility (per tick)"] == format(market.volatility, PRICE)
    assert shown["Realized volatility"] == format(market.realized_volatility, PRICE)
    assert f"{market.return_count:,d} log returns" in _captions(at)


def test_drawdown_figures_are_the_reports_own(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    at = _render(payload_dict)
    shown = _metrics(at)
    captions = _captions(at)
    assert shown["Max drawdown"] == format(market.max_drawdown, RATIO)
    assert shown["Drawdown at close"] == format(market.end_drawdown, RATIO)
    assert f"drawdown peak tick {market.drawdown_peak_tick}" in captions
    assert f"trough tick {market.drawdown_trough_tick}" in captions
    expected = "not recovered" if market.recovery_tick is None else f"recovered at tick {market.recovery_tick}"
    assert expected in captions


def test_market_cap_and_turnover_are_the_reports_own(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    at = _render(payload_dict)
    shown = _metrics(at)
    assert shown["Market cap (open)"] == format(market.market_cap_start, VOLUME)
    assert shown["Market cap (close)"] == format(market.market_cap_end, VOLUME)
    assert shown["Turnover"] == format(market.turnover, RATIO)
    assert shown["Participant turnover"] == format(market.participant_turnover, RATIO)
    assert f"average trade size {format(market.average_trade_size, VOLUME)}" in _captions(at)
    assert f"trader VWAP {format(market.trader_vwap, PRICE)}" in _captions(at)


def test_the_statistics_table_matches_the_report(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    statistics = _statistics(_render(payload_dict))
    assert statistics["Open"] == format(market.open_price, PRICE)
    assert statistics["Close"] == format(market.close_price, PRICE)
    assert statistics["Return"] == format(market.cumulative_return, RETURN)
    assert statistics["Log return"] == format(market.log_return, "+.4f")
    assert statistics["High"] == f"{format(market.high_price, PRICE)} at tick {market.high_tick}"
    assert statistics["Low"] == f"{format(market.low_price, PRICE)} at tick {market.low_tick}"
    assert statistics["Mean return"] == format(market.mean_return, "+.4f")
    assert statistics["Trader VWAP"] == format(market.trader_vwap, PRICE)
    assert statistics["Pricing mode"] == market.pricing_mode
    assert statistics["Missing ticks"] == format(market.missing_tick_count, ",d")


# --- the chart -------------------------------------------------------------------------------------------


def test_the_chart_plots_the_recorded_price_path(random_walk):
    payload, payload_dict = random_walk
    spec = json.loads(_render(payload_dict).get("plotly_chart")[0].proto.spec)
    price = spec["data"][0]
    assert price["x"] == [point.tick for point in payload.price_series]
    assert price["y"] == [point.price for point in payload.price_series]
    assert price["x"] == sorted(price["x"])


def test_the_chart_hover_shows_tick_price_and_volume(random_walk):
    _, payload_dict = random_walk
    price = json.loads(_render(payload_dict).get("plotly_chart")[0].proto.spec)["data"][0]
    assert "Tick %{x}" in price["hovertemplate"]
    assert "Price %{y:,.4f}" in price["hovertemplate"]
    assert "Volume %{customdata:,.0f}" in price["hovertemplate"]


def test_the_chart_axes_are_labelled(random_walk):
    _, payload_dict = random_walk
    layout = json.loads(_render(payload_dict).get("plotly_chart")[0].proto.spec)["layout"]
    assert layout["xaxis"]["title"]["text"] == "Tick"
    assert layout["yaxis"]["title"]["text"] == "Price"


def test_the_chart_markers_are_the_reports_high_and_low(random_walk):
    payload, payload_dict = random_walk
    market = payload.report.market
    spec = json.loads(_render(payload_dict).get("plotly_chart")[0].proto.spec)
    markers = spec["data"][1]
    assert markers["text"] == ["High", "Low"]
    assert markers["y"] == [market.high_price, market.low_price]
    assert markers["x"] == [market.high_tick, market.low_tick]


def test_a_pre_run_extreme_is_not_plotted_on_a_tick_it_did_not_happen_at():
    """``analyze_market`` puts the pre-run price at tick 0, which is not a
    recorded tick. A pre-run high therefore gets no marker, while the low
    (a real tick) still does — rather than the high being moved onto a
    tick it did not happen at."""
    settings = get_settings()
    sim = build_coin_simulator(settings, include_traders=False, include_whales=False)
    ticks = sim.run(12)
    # A pre-run price above every recorded price makes tick 0 the high.
    report = build_report(ticks, initial_price=10.0)
    series = [{"tick": t.tick, "price": t.price, "market_cap": t.market_cap, "volume": t.volume}
              for t in ticks]
    market = report.market
    assert market.high_tick == 0 and market.low_tick != 0
    spec = json.loads(
        _render(_payload_dict_for(report, price_series=series)).get("plotly_chart")[0].proto.spec
    )
    markers = spec["data"][1]
    assert markers["text"] == ["Low"]
    assert markers["x"] == [market.low_tick]


def test_the_chart_is_deterministic(random_walk):
    _, payload_dict = random_walk
    first = json.loads(_render(payload_dict).get("plotly_chart")[0].proto.spec)
    second = json.loads(_render(payload_dict).get("plotly_chart")[0].proto.spec)
    assert first["data"] == second["data"]


# --- both pricing modes ----------------------------------------------------------------------------------


def test_amm_pool_activity_is_displayed(amm):
    payload, payload_dict = amm
    pool = payload.report.market.pool_activity
    shown = _metrics(_render(payload_dict))
    assert shown["Swaps"] == format(pool.swap_count, ",d")
    assert shown["Fees (cash)"] == format(float(pool.fees_cash), PRICE)
    assert shown["Fees (coins)"] == format(float(pool.fees_coins), PRICE)
    assert shown["Largest price impact"] == format(float(pool.max_abs_price_impact), RATIO)


def test_amm_background_volume_keeps_its_meaning(amm):
    payload, payload_dict = amm
    assert payload.report.market.volume_breakdown.background_volume is None
    assert _volume_table(_render(payload_dict))["Background (synthetic)"] == "n/a (AMM mode)"


def test_amm_market_figures_are_the_reports_own(amm):
    payload, payload_dict = amm
    market = payload.report.market
    shown = _metrics(_render(payload_dict))
    assert shown["Close price"] == format(market.close_price, PRICE)
    assert shown["Return"] == format(market.cumulative_return, RETURN)
    assert shown["Total volume"] == format(market.volume_breakdown.total_volume, VOLUME)


def test_random_walk_says_why_there_is_no_pool(random_walk):
    payload, payload_dict = random_walk
    assert payload.report.market.pool_activity is None
    at = _render(payload_dict)
    assert market_section.NO_POOL_MESSAGE in _captions(at)
    assert "Swaps" not in _metrics(at)


# --- missing data ----------------------------------------------------------------------------------------


def test_a_report_with_no_ticks_renders_a_message_and_no_figures():
    at = _render(_payload_dict_for(build_report([])))
    assert not at.exception
    assert NO_TICKS_MESSAGE in [info.value for info in at.info]
    assert at.metric.len == 0
    assert at.table.len == 0


def test_a_single_tick_run_renders_with_volatility_unavailable():
    settings = get_settings()
    sim = build_coin_simulator(settings)
    ticks = sim.run(1)
    report = build_report(ticks, initial_price=settings.coin.starting_price,
                          total_supply=settings.coin.initial_supply)
    at = _render(_payload_dict_for(
        report,
        price_series=[{"tick": t.tick, "price": t.price, "market_cap": t.market_cap, "volume": t.volume}
                      for t in ticks],
    ))
    assert not at.exception
    shown = _metrics(at)
    assert shown["Close price"] == format(report.market.close_price, PRICE)
    assert report.market.volatility is None
    assert shown["Volatility (per tick)"] == "n/a"


def test_without_a_total_supply_market_cap_and_turnover_stay_unavailable():
    settings = get_settings()
    sim = build_coin_simulator(settings)
    ticks = sim.run(10)
    report = build_report(ticks, initial_price=settings.coin.starting_price)
    at = _render(_payload_dict_for(report))
    shown = _metrics(at)
    assert report.market.turnover is None and report.market.market_cap_end is None
    assert shown["Turnover"] == "n/a"
    assert shown["Participant turnover"] == "n/a"
    assert shown["Market cap (open)"] == "n/a"
    assert shown["Market cap (close)"] == "n/a"
    assert _statistics(at)["Turnover"] == "n/a"


def test_missing_values_are_never_shown_as_zero():
    settings = get_settings()
    sim = build_coin_simulator(settings, include_traders=False, include_whales=False)
    ticks = sim.run(4)
    report = build_report(ticks, initial_price=settings.coin.starting_price)
    statistics = _statistics(_render(_payload_dict_for(report)))
    assert report.market.trader_vwap is None
    assert statistics["Trader VWAP"] == "n/a"
    assert statistics["Average trade size"] == "n/a"
    for label in ("Turnover", "Participant turnover", "Market cap (open)"):
        assert statistics[label] == "n/a"


@pytest.mark.parametrize(
    "params",
    [
        SimulationParams(ticks=6, include_whales=False),
        SimulationParams(ticks=6, include_traders=False),
        SimulationParams(ticks=6, include_traders=False, include_whales=False),
        SimulationParams(ticks=6, events=True, psychology=True),
        SimulationParams(ticks=6, pricing_mode="amm", include_whales=False),
    ],
    ids=["no-whales", "no-traders", "neither", "events-psychology", "amm"],
)
def test_the_section_renders_for_sparse_runs(params):
    payload = run_simulation(params)
    at = _render(payload_to_dict(payload))
    assert not at.exception
    assert _metrics(at)["Close price"] == format(payload.report.market.close_price, PRICE)


# --- the section computes nothing ------------------------------------------------------------------------


BANNED_CALLS = {"analyze_market", "analyze_traders", "build_report", "fsum", "sum", "round", "abs",
                "min", "max", "sorted"}


def _calls(module) -> set[str]:
    """Every function name called in a module (structural, so a docstring
    mentioning a function does not count as calling it)."""
    tree = ast.parse(Path(module.__file__).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


def _arithmetic(module) -> list[str]:
    """Arithmetic operators used anywhere in a module's code."""
    tree = ast.parse(Path(module.__file__).read_text())
    return [
        type(node.op).__name__
        for node in ast.walk(tree)
        if isinstance(node, (ast.BinOp, ast.AugAssign))
        and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod))
    ]


def test_the_market_section_calls_no_analytics():
    assert not BANNED_CALLS & _calls(market_section)


def test_the_market_section_does_no_arithmetic():
    """Its only literals are labels, payload keys and format specs; every
    figure arrives already computed by the analytics."""
    assert _arithmetic(market_section) == []


def test_the_formatting_helpers_do_no_arithmetic():
    from crypto_simulator.dashboard import formatting

    assert _arithmetic(formatting) == []
    assert not BANNED_CALLS & _calls(formatting)
