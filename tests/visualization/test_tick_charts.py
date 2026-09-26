"""Tick-level chart builders (Phase 20, Step 4): the synthetic OHLC
aggregation worked out by hand, and the figures' axes, titles, hover text
and determinism."""

import copy
import json
import math

import pytest

from crypto_simulator.visualization.tick_charts import (
    SYNTHETIC_OHLC_DISCLOSURE,
    OhlcWindow,
    synthetic_ohlc,
    synthetic_ohlc_chart,
    volume_composition_chart,
)

TICKS = list(range(1, 13))
PRICES = [1.0, 1.5, 0.8, 1.2, 1.1, 2.0, 1.9, 0.5, 0.7, 1.0, 1.3, 0.9]


# --- synthetic_ohlc -----------------------------------------------------------------------------------


def test_windows_are_open_first_high_max_low_min_close_last():
    windows = synthetic_ohlc(TICKS, PRICES, 5)
    assert windows[0] == OhlcWindow(1, 5, 5, open=1.0, high=1.5, low=0.8, close=1.1, partial=False)
    assert windows[1] == OhlcWindow(6, 10, 5, open=2.0, high=2.0, low=0.5, close=1.0, partial=False)


def test_a_final_partial_window_is_marked():
    windows = synthetic_ohlc(TICKS, PRICES, 5)
    assert windows[-1] == OhlcWindow(11, 12, 2, open=1.3, high=1.3, low=0.9, close=0.9, partial=True)
    assert [w.partial for w in synthetic_ohlc(TICKS, PRICES, 4)] == [False, False, False]


@pytest.mark.parametrize("window", [5, 10, 20, 50])
def test_every_row_is_in_exactly_one_window_in_order(window):
    ticks = list(range(3, 3 + 137))
    prices = [1.0 + math.sin(i) / 3 for i in range(137)]
    windows = synthetic_ohlc(ticks, prices, window)
    assert sum(w.rows for w in windows) == len(ticks)
    assert windows[0].first_tick == ticks[0] and windows[-1].last_tick == ticks[-1]
    for before, after in zip(windows, windows[1:]):
        assert after.first_tick == before.last_tick + 1
    assert all(w.rows == window for w in windows[:-1])
    assert windows[-1].partial == (len(ticks) % window != 0)
    for w in windows:
        chunk = prices[ticks.index(w.first_tick):ticks.index(w.last_tick) + 1]
        assert (w.open, w.high, w.low, w.close) == (chunk[0], max(chunk), min(chunk), chunk[-1])


def test_window_boundaries_follow_recorded_rows_not_tick_numbers():
    windows = synthetic_ohlc([1, 2, 5, 6], [1.0, 2.0, 3.0, 4.0], 2)
    assert [(w.first_tick, w.last_tick) for w in windows] == [(1, 2), (5, 6)]


def test_a_single_tick_is_one_flat_partial_window():
    assert synthetic_ohlc([7], [2.5], 10) == (OhlcWindow(7, 7, 1, 2.5, 2.5, 2.5, 2.5, partial=True),)


def test_a_one_row_window_repeats_the_price():
    windows = synthetic_ohlc([1, 2], [1.0, 2.0], 1)
    assert [(w.open, w.high, w.low, w.close) for w in windows] == [(1.0,) * 4, (2.0,) * 4]


def test_empty_input_gives_no_windows():
    assert synthetic_ohlc([], [], 10) == ()


@pytest.mark.parametrize("window", [0, -1, 2.0, True, None])
def test_an_invalid_window_is_rejected(window):
    with pytest.raises(ValueError):
        synthetic_ohlc(TICKS, PRICES, window)


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        synthetic_ohlc([1, 2], [1.0], 5)


def test_the_inputs_are_not_mutated_and_output_is_deterministic():
    ticks, prices = list(TICKS), list(PRICES)
    first = synthetic_ohlc(ticks, prices, 5)
    assert (ticks, prices) == (TICKS, PRICES)
    assert synthetic_ohlc(ticks, prices, 5) == first


# --- synthetic_ohlc_chart -----------------------------------------------------------------------------


def _spec(fig):
    return json.loads(fig.to_json())


def test_the_chart_uses_ticks_and_discloses_its_synthetic_aggregation():
    windows = synthetic_ohlc(TICKS, PRICES, 5)
    spec = _spec(synthetic_ohlc_chart(windows, title="FIC synthetic OHLC"))
    trace = spec["data"][0]
    assert trace["type"] == "candlestick"
    assert trace["x"] == [1, 6, 11]
    assert (trace["open"], trace["close"]) == ([1.0, 2.0, 1.3], [1.1, 1.0, 0.9])
    assert SYNTHETIC_OHLC_DISCLOSURE in spec["layout"]["title"]["text"]
    assert spec["layout"]["title"]["text"].startswith("FIC synthetic OHLC")
    assert spec["layout"]["xaxis"]["title"]["text"] == "Simulation tick (window start)"
    assert spec["layout"]["yaxis"]["title"]["text"] == "Price"
    assert "timestamp" not in json.dumps(spec).lower()


def test_hover_gives_each_windows_tick_range_and_partial_status():
    spec = _spec(synthetic_ohlc_chart(synthetic_ohlc(TICKS, PRICES, 5), title="t"))
    hover = spec["data"][0]["text"]
    assert hover[0].startswith("Ticks 1-5 (5 recorded ticks)")
    assert hover[2].startswith("Ticks 11-12 (2 recorded ticks, partial window)")


def test_the_same_windows_give_the_same_figure():
    windows = synthetic_ohlc(TICKS, PRICES, 5)
    assert synthetic_ohlc_chart(windows, title="t").to_json() == synthetic_ohlc_chart(windows, title="t").to_json()


def test_an_empty_window_list_gives_an_empty_candle_trace():
    spec = _spec(synthetic_ohlc_chart((), title="t"))
    assert spec["data"][0]["x"] == []


# --- volume_composition_chart -------------------------------------------------------------------------


def test_volume_bars_stack_in_the_given_order_on_the_tick_axis():
    components = [("Organic", [1.0, 2.0]), ("Wash", [0.0, 4.0]), ("Background", [3.0, -1e-12])]
    before = copy.deepcopy(components)
    spec = _spec(volume_composition_chart([1, 2], components, title="Recorded volume", unit="FIC"))
    assert components == before
    assert [t["name"] for t in spec["data"]] == ["Organic", "Wash", "Background"]
    assert all(t["type"] == "bar" and t["x"] == [1, 2] for t in spec["data"])
    assert spec["layout"]["barmode"] == "relative"
    assert spec["layout"]["xaxis"]["title"]["text"] == "Simulation tick"
    assert spec["layout"]["yaxis"]["title"]["text"] == "Volume (FIC)"
    assert spec["layout"]["title"]["text"] == "Recorded volume"


def test_a_component_of_the_wrong_length_is_rejected():
    with pytest.raises(ValueError):
        volume_composition_chart([1, 2], [("Organic", [1.0])], title="t", unit="FIC")
