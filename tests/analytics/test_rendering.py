"""Plain-text report rendering (Phase 9, Step 8b).

``render_report`` is presentation only, so these tests pin what it shows
to the values already on the report: a fixed report renders to an exact
string, changed report values change the text in exactly those places,
``None`` renders as unavailable while a defined zero renders as zero,
and the module computes nothing, calls no analytics, and makes no causal
or forecasting statement.
"""

import ast
import copy
import dataclasses
from pathlib import Path

import pytest

import crypto_simulator.analytics.rendering as rendering_module
from crypto_simulator.analytics import build_report, render_report
from crypto_simulator.core.coin_simulator import CoinSimulator
from crypto_simulator.core.whale import Whale
from tests.analytics.test_report import _world
from tests.core.test_coin_simulator_traders import _all_five, _coin

HEADINGS = ("SIMULATION REPORT", "MARKET", "TRADERS", "WHALE ACTIVITY", "EVENT WINDOWS", "PSYCHOLOGY",
            "MANIPULATION", "REGIMES")

EMPTY = (
    "==============================================================================\n"
    "SIMULATION REPORT\n"
    "Descriptive observations of a finished synthetic run. Not a prediction,\n"
    "a recommendation or a trading signal, and no figure states a cause.\n"
    "==============================================================================\n"
    "  ticks analysed           0\n"
    "  tick range               none\n"
    "  pricing mode             n/a\n"
    "\n"
    "MARKET\n"
    "  (recorded prices and volume)\n"
    "------------------------------------------------------------------------------\n"
    "  no ticks were analysed\n"
    "\n"
    "TRADERS\n"
    "  (recorded fills; wash legs reported apart)\n"
    "------------------------------------------------------------------------------\n"
    "  no trader activity recorded\n"
    "\n"
    "WHALE ACTIVITY\n"
    "  (recorded whale observations; descriptive only)\n"
    "------------------------------------------------------------------------------\n"
    "  no whale observations recorded (whale volume is still counted under MARKET)\n"
    "\n"
    "EVENT WINDOWS\n"
    "  (market observed around each event's ground-truth lifecycle; not attributed)\n"
    "------------------------------------------------------------------------------\n"
    "  unavailable: no event timeline was supplied\n"
    "\n"
    "PSYCHOLOGY\n"
    "  (recorded market-wide state alongside the market; co-movement, not cause)\n"
    "------------------------------------------------------------------------------\n"
    "  unavailable: no psychology was recorded\n"
    "\n"
    "MANIPULATION\n"
    "  (fills recorded by registered manipulation strategies; descriptive only)\n"
    "------------------------------------------------------------------------------\n"
    "  no manipulation fills recorded\n"
    "\n"
    "REGIMES\n"
    "  (observed conditions per 20-tick window; describes the past only)\n"
    "------------------------------------------------------------------------------\n"
    "  no windows: no ticks were analysed\n"
)


def _full_report(seed=4, **kwargs):
    sim, ticks, events, random_ids, start, end = _world(seed, **kwargs)
    return build_report(ticks, events=events, random_event_ids=random_ids, initial_price=sim.coin.starting_price,
                        total_supply=sim.coin.initial_supply, start_balances=start, end_balances=end)


# --- fixed output ----------------------------------------------------------------------------------------


def test_an_empty_report_renders_to_a_fixed_string():
    assert render_report(build_report([])) == EMPTY


def test_rendered_values_are_the_reports_own_values():
    report = _full_report()
    market = dataclasses.replace(report.market, open_price=1.2345, close_price=6.789, high_price=9.5, high_tick=77,
                                 cumulative_return=0.1234)
    traders = dataclasses.replace(report.traders, fill_count=4242, pnl=-17.5)
    text = render_report(dataclasses.replace(report, market=market, traders=traders))
    assert "open / close             1.2345 / 6.7890" in text
    assert "high                     9.5000 at tick 77" in text
    assert "return                   +12.34%" in text
    assert "fills                    4242" in text
    assert "combined P&L             -17.50" in text
    original = render_report(report)
    assert f"{report.market.open_price:,.4f} / {report.market.close_price:,.4f}" in original
    assert f"fills                    {report.traders.fill_count}" in original


def test_none_renders_as_unavailable_and_a_defined_zero_as_zero():
    report = _full_report()
    none_drawdown = dataclasses.replace(report.market, max_drawdown=None, drawdown_peak_tick=None, turnover=None)
    zero_drawdown = dataclasses.replace(report.market, max_drawdown=0.0, drawdown_peak_tick=None)
    assert "max drawdown             n/a" in render_report(dataclasses.replace(report, market=none_drawdown))
    assert "turnover                 n/a (no total supply given)" in render_report(
        dataclasses.replace(report, market=none_drawdown))
    assert "max drawdown             0.00%" in render_report(dataclasses.replace(report, market=zero_drawdown))
    no_pnl = dataclasses.replace(report.traders, pnl=None)
    assert "combined P&L             n/a (no wallet balances supplied)" in render_report(
        dataclasses.replace(report, traders=no_pnl))


# --- content on real runs --------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["random_walk", "amm"])
def test_a_full_report_shows_every_section_and_its_entities(mode):
    report = _full_report(mode=mode)
    text = render_report(report)
    positions = [text.index(heading) for heading in HEADINGS]
    assert positions == sorted(positions)
    for event in report.event_windows.events:
        assert f"  {event.event_id} (" in text
    for strategy in report.traders.strategies:
        # Traders known only from wallet balances have no recorded strategy.
        assert f"  {strategy.strategy or '(balances only)'}" in text
    for trader in report.manipulation.pump_and_dump:
        assert f"  {trader.trader_id}: recorded phases" in text
    regime_rows = [line for line in text.splitlines() if line.startswith("  ") and line[2:3].isdigit()
                   and "-" in line.split()[0]]
    assert len(regime_rows) == report.regimes.total_windows
    if mode == "amm":
        assert "n/a (AMM mode)" in text and " cash + " in text
        assert "no whale observations recorded" in text
    else:
        for whale in report.whale_activity.whales:
            assert f"  {whale.whale_id} " in text


def test_a_short_run_renders():
    report = _full_report(ticks=3)
    text = render_report(report)
    assert "ticks analysed           3" in text
    assert "  1-20         3*  " in text and "* incomplete window" in text


def test_a_run_without_traders_renders():
    sim = CoinSimulator(_coin(), seed=2, whales=[Whale("w", 30_000.0, activity_probability=0.5, seed=2)])
    ticks = sim.run(25)
    text = render_report(build_report(ticks, initial_price=sim.coin.starting_price))
    assert "no trader activity recorded" in text and "no manipulation fills recorded" in text


@pytest.mark.parametrize("flag, expected", [
    ("psychology", "unavailable: no psychology was recorded"),
    ("whales", "no whale observations recorded"),
    ("manipulation", "no manipulation fills recorded"),
])
def test_disabled_features_render_as_unavailable_not_as_zeros(flag, expected):
    text = render_report(_full_report(seed=6, **{flag: False}))
    assert expected in text


def test_no_event_timeline_and_an_empty_timeline_render_differently():
    sim, ticks, *_ = _world(7, events=False, ticks=40)
    assert "unavailable: no event timeline was supplied" in render_report(build_report(ticks))
    assert "no events started within the analysed ticks" in render_report(build_report(ticks, events=()))


def test_a_scoped_report_names_the_requested_range():
    sim, ticks, events, *_ = _world(8, ticks=80)
    text = render_report(build_report(ticks, events=events, start_tick=21, end_tick=60))
    assert "ticks analysed           40 (requested ticks 21-60)" in text
    assert "tick range               21-60" in text


# --- determinism, purity, and presentation only ----------------------------------------------------------


def test_rendering_is_deterministic():
    report = _full_report(seed=9)
    assert render_report(report) == render_report(report)
    assert render_report(_full_report(seed=9)) == render_report(report)


def test_rendering_does_not_change_the_report():
    report = _full_report(seed=10)
    snapshot = copy.deepcopy(report)
    render_report(report)
    assert report == snapshot


def test_the_renderer_computes_nothing_and_calls_no_analytics():
    tree = ast.parse(Path(rendering_module.__file__).read_text())
    arithmetic = [n for n in ast.walk(tree)
                  if isinstance(n, ast.BinOp) and not isinstance(n.op, (ast.Add, ast.BitOr))]
    assert not arithmetic
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"sum", "min", "max", "len", "round", "abs", "sorted"}
    assert not {name for name in called if name.startswith(("analyze_", "build_"))}
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported == {"__future__", "typing", "crypto_simulator.analytics.events",
                        "crypto_simulator.analytics.regimes", "crypto_simulator.analytics.report"}


def test_rendered_text_makes_no_causal_or_forecasting_statement():
    text = render_report(_full_report(seed=11)).lower()
    for phrase in ("caused", "drove", "led to", "because", "due to", "bullish", "bearish", "opportunity",
                   "buy signal", "sell signal", " will ", "expect", "should"):
        assert phrase not in text, phrase
