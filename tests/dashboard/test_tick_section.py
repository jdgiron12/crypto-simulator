"""The tick-level views section (Phase 20, Step 4), driven through
``streamlit.testing.v1.AppTest`` on real runs' serialized tick series."""

from __future__ import annotations

import json
import math

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.analytics.tick_series import build_tick_series
from crypto_simulator.dashboard.data import (
    TICK_SERIES_UNAVAILABLE_MESSAGE,
    SimulationParams,
    run_dashboard_simulation,
    tick_series_to_dict,
)
from crypto_simulator.dashboard.tick_section import (
    NO_EVENT_STATE_MESSAGE,
    NO_POOL_STATE_MESSAGE,
    NO_TICKS_MESSAGE,
    OHLC_WINDOW_KEY,
    SECTION_HEADING,
)
from crypto_simulator.visualization.tick_charts import SYNTHETIC_OHLC_DISCLOSURE

FORBIDDEN = ("caused", "causes", "predicted", "predicts", "drove", "drives", "triggered", "influenced",
             "influence", "resulted in", "led to", "because of", "due to", "herding", "contagion",
             "propagation", "responsible for", "produced")

RW_EVENTS = SimulationParams(ticks=37, random_seed=5, events=True, random_events=True, psychology=True,
                             scenario="pump_and_dump")
RW_PLAIN = SimulationParams(ticks=23, random_seed=9, include_whales=False)
AMM_EVENTS = SimulationParams(ticks=31, random_seed=4, pricing_mode="amm", include_whales=False, events=True,
                              scenario="wash_trading")


def _section(tick_series=None, symbol="FIC"):
    """The section on its own (AppTest executes this function's source)."""
    from crypto_simulator.dashboard.tick_section import render_tick_views

    render_tick_views(tick_series, symbol=symbol)


def _app(tick_series) -> AppTest:
    return AppTest.from_function(_section, kwargs={"tick_series": tick_series}, default_timeout=60).run()


def _series(params):
    run = run_dashboard_simulation(params)
    return run, tick_series_to_dict(run.tick_series)


@pytest.fixture(scope="module")
def rw():
    return _series(RW_EVENTS)


@pytest.fixture(scope="module")
def amm():
    return _series(AMM_EVENTS)


def _charts(at):
    return [json.loads(chart.proto.spec) for chart in at.get("plotly_chart")]


def _titles(at):
    return [chart["layout"]["title"]["text"] for chart in _charts(at)]


def _shown(at):
    parts = [e.value for e in at.markdown] + [e.value for e in at.caption] + [e.value for e in at.info]
    parts += _titles(at)
    parts += [trace.get("name", "") for chart in _charts(at) for trace in chart["data"]]
    return " ".join(parts).lower()


# --- availability ---------------------------------------------------------------------------------------


def test_no_tick_series_shows_the_frozen_message_and_no_chart():
    at = _app(None)
    assert SECTION_HEADING in [e.value for e in at.markdown]
    assert [e.value for e in at.info] == [TICK_SERIES_UNAVAILABLE_MESSAGE]
    assert TICK_SERIES_UNAVAILABLE_MESSAGE == "Tick-level data was not recorded for this saved run."
    assert at.get("plotly_chart") == []


def test_a_run_with_no_ticks_shows_no_views():
    empty = tick_series_to_dict(build_tick_series([], total_supply=1.0, population={"retail": 1}, whale_count=0))
    at = _app(empty)
    assert [e.value for e in at.info] == [NO_TICKS_MESSAGE]
    assert at.get("plotly_chart") == []


# --- views ----------------------------------------------------------------------------------------------


def test_random_walk_shows_ohlc_volume_and_events_and_says_there_is_no_pool(rw):
    at = _app(rw[1])
    titles = _titles(at)
    assert len(titles) == 3
    assert titles[0].startswith("FIC synthetic OHLC, 10-tick windows")
    assert SYNTHETIC_OHLC_DISCLOSURE in titles[0]
    assert titles[1] == "Recorded volume per tick by component (FIC)"
    assert titles[2] == "Recorded event state per tick"
    assert NO_POOL_STATE_MESSAGE in [e.value for e in at.info]
    assert SYNTHETIC_OHLC_DISCLOSURE in " ".join(e.value for e in at.caption)


def test_amm_shows_the_recorded_pool_state(amm):
    at = _app(amm[1])
    titles = _titles(at)
    assert titles[2:6] == ["Pool reserves after each tick", "Pool invariant after each tick",
                           "Cumulative pool fees", "Cumulative pool swap count"]
    assert NO_POOL_STATE_MESSAGE not in [e.value for e in at.info]
    charts = _charts(at)
    data = amm[1]["data"]
    reserves = {t["name"]: t["y"] for t in charts[2]["data"]}
    assert reserves == {"Coin reserve (FIC)": data["pool_coin_reserve"], "Cash reserve (cash)": data["pool_cash_reserve"]}
    assert charts[3]["data"][0]["y"] == data["pool_invariant"]
    fees = {t["name"]: t["y"] for t in charts[4]["data"]}
    assert fees == {"Fees collected (FIC)": data["pool_fees_collected_coins"],
                    "Fees collected (cash)": data["pool_fees_collected_cash"]}
    assert charts[5]["data"][0]["y"] == data["pool_swap_count"]
    assert all(t["x"] == data["tick"] for chart in charts[2:6] for t in chart["data"])


def test_there_is_no_second_spot_price_or_psychology_chart(rw, amm):
    for _, series in (rw, amm):
        names = " ".join(t.get("name", "") for c in _charts(_app(series)) for t in c["data"]).lower()
        assert "spot" not in names
        for component in ("fear", "fomo", "conviction", "uncertainty"):
            assert component not in names


def _volume_traces(at):
    chart = next(c for c in _charts(at) if c["layout"]["title"]["text"].startswith("Recorded volume"))
    return {t["name"]: t["y"] for t in chart["data"]}, chart


def test_random_walk_volume_has_every_recorded_component_and_reconciles(rw):
    run, series = rw
    traces, chart = _volume_traces(_app(series))
    assert list(traces) == ["Organic", "Manipulator", "Wash", "Whale", "Background"]
    assert chart["layout"]["barmode"] == "relative"
    for i, point in enumerate(run.payload.price_series):
        assert math.isclose(math.fsum(values[i] for values in traces.values()), point.volume,
                            rel_tol=1e-12, abs_tol=1e-9)


def test_amm_volume_has_no_whale_or_background_and_reconciles(amm):
    run, series = amm
    traces, _ = _volume_traces(_app(series))
    assert list(traces) == ["Organic", "Manipulator", "Wash"]
    for i, point in enumerate(run.payload.price_series):
        assert math.isclose(math.fsum(values[i] for values in traces.values()), point.volume,
                            rel_tol=1e-12, abs_tol=1e-9)


def test_the_whale_trace_is_omitted_without_whales():
    traces, _ = _volume_traces(_app(_series(RW_PLAIN)[1]))
    assert list(traces) == ["Organic", "Manipulator", "Wash", "Background"]


def test_event_state_is_the_recorded_columns(rw):
    series = rw[1]
    chart = next(c for c in _charts(_app(series)) if c["layout"]["title"]["text"] == "Recorded event state per tick")
    traces = {t["name"]: t["y"] for t in chart["data"]}
    data = series["data"]
    assert traces["Sentiment"] == data["event_sentiment"]
    assert traces["Volatility multiplier"] == data["event_volatility_multiplier"]
    assert traces["Attention multiplier"] == data["event_attention_multiplier"]
    assert traces["Live events"] == [len(live) for live in data["event_live"]]
    assert any(traces["Live events"]), "the demo events should be live on some tick"


def test_a_run_without_events_says_so_instead_of_charting():
    at = _app(_series(RW_PLAIN)[1])
    assert NO_EVENT_STATE_MESSAGE in [e.value for e in at.info]
    assert "Recorded event state per tick" not in _titles(at)


# --- OHLC window control --------------------------------------------------------------------------------


def test_the_window_control_offers_5_10_20_50_and_defaults_to_10(rw):
    at = _app(rw[1])
    control = at.selectbox(key=OHLC_WINDOW_KEY)
    assert list(control.options) == ["5", "10", "20", "50"]
    assert control.value == 10
    assert _charts(at)[0]["data"][0]["x"] == [1, 11, 21, 31]


def test_changing_the_window_regroups_the_stored_series(rw):
    at = _app(rw[1])
    at.selectbox(key=OHLC_WINDOW_KEY).set_value(5).run()
    candles = _charts(at)[0]["data"][0]
    assert candles["x"] == [1, 6, 11, 16, 21, 26, 31, 36]
    assert candles["text"][-1].startswith("Ticks 36-37 (2 recorded ticks, partial window)")
    assert "The last window is partial." in " ".join(e.value for e in at.caption)


# --- vocabulary -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["rw", "amm", "plain", "none"])
def test_no_causal_or_behavioral_claims_on_screen(which, rw, amm):
    series = {"rw": rw[1], "amm": amm[1], "plain": _series(RW_PLAIN)[1], "none": None}[which]
    shown = _shown(_app(series))
    for word in FORBIDDEN:
        assert word not in shown, word
