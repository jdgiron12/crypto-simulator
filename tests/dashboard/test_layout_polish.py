"""The Simulate workspace's layout polish (Phase 24, Step 5).

Presentation only: these tests check that the polish moved text and
headings without losing any of it, and changed no figure. The headline
figures wrap rather than truncate and show the return once; a tab's
section does not repeat the tab's name as its heading; follow-on notes sit,
word for word, in one collapsed "Notes on these figures" expander; batch
charts keep short titles and show their disclosures as wrapping captions.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator.dashboard.notes import NOTES_LABEL
from crypto_simulator.dashboard.regime_section import INCOMPLETE_NOTE
from crypto_simulator.dashboard.view import PAYLOAD_KEY, RESULT_TABS, RunStatus, STATUS_KEY

TICKS = 60


def _dashboard():
    """The dashboard with its default runners (AppTest executes this source)."""
    from crypto_simulator.dashboard.view import render_dashboard

    render_dashboard()


def _sections(heading: bool):
    """Every detail-tab section drawn on its own, with or without its heading."""
    from crypto_simulator.dashboard.data import SimulationParams, payload_to_dict, run_simulation
    from crypto_simulator.dashboard.event_section import render_events
    from crypto_simulator.dashboard.manipulation_section import render_manipulation
    from crypto_simulator.dashboard.psychology_section import render_psychology
    from crypto_simulator.dashboard.regime_section import render_regimes
    from crypto_simulator.dashboard.tick_section import render_tick_views
    from crypto_simulator.dashboard.trader_section import render_traders
    from crypto_simulator.dashboard.whale_section import render_whales

    payload = payload_to_dict(run_simulation(SimulationParams(ticks=12)))
    report, simulation = payload["report"], payload["simulation"]
    render_traders(report["traders"], symbol="FIC", heading=heading)
    render_whales(report["whale_activity"], symbol="FIC", simulation=simulation, heading=heading)
    render_events(report["event_windows"], symbol="FIC", simulation=simulation, heading=heading)
    render_psychology(report["psychology_market"], symbol="FIC", simulation=simulation, heading=heading)
    render_manipulation(report["manipulation"], symbol="FIC", simulation=simulation, heading=heading)
    render_regimes(report["regimes"], symbol="FIC", simulation=simulation, heading=heading)
    render_tick_views(None, symbol="FIC", heading=heading)


#: Each section's own heading, as drawn when it stands alone.
SECTION_HEADINGS = (
    "**Traders**", "**Whales**", "**Events**", "**Psychology**", "**Manipulation**", "**Market regimes**",
    "**Tick-level views**",
)


@pytest.fixture(scope="module")
def full_run() -> AppTest:
    """One run with every optional recorder on and a manipulation scenario,
    so every detail tab has content and every notes expander is drawn."""
    at = AppTest.from_function(_dashboard, default_timeout=300).run()
    at.number_input(key="coin_dashboard_ticks").set_value(TICKS)
    for key in ("coin_dashboard_events", "coin_dashboard_psychology", "coin_dashboard_whale_observation"):
        at.checkbox(key=key).check()
    at.selectbox(key="coin_dashboard_scenario").set_value("pump_and_dump")
    at.button(key="coin_dashboard_run").click().run()
    assert at.session_state[STATUS_KEY] is RunStatus.SUCCESS
    return at


def _tab(at: AppTest, label: str):
    return next(tab for tab in at.tabs if tab.label == label)


# --- the headline --------------------------------------------------------------------------------------


def test_the_headline_shows_every_figure_and_the_return_once(full_run):
    market = full_run.session_state[PAYLOAD_KEY]["report"]["market"]
    headline = {metric.label: metric for metric in _tab(full_run, "Single run").metric[:4]}
    assert list(headline) == ["Close price", "Return", "Total volume", "Ticks analysed"]
    assert headline["Close price"].value == format(market["close_price"], ",.4f")
    assert headline["Return"].value == format(market["cumulative_return"], "+.2%")
    assert headline["Total volume"].value == format(market["volume_breakdown"]["total_volume"], ",.0f")
    assert headline["Ticks analysed"].value == str(market["ticks"])
    # The close no longer repeats the return as its delta.
    assert not headline["Close price"].delta
    shown = [metric.value for metric in headline.values()] + [metric.delta for metric in headline.values()]
    assert shown.count(format(market["cumulative_return"], "+.2%")) == 1


# --- headings ------------------------------------------------------------------------------------------


def test_no_detail_tab_repeats_its_name_as_a_heading(full_run):
    headings = [element.value for element in full_run.markdown]
    for heading in SECTION_HEADINGS:
        assert heading not in headings, heading
    # The subsections inside the tabs keep their headings.
    for tab, subsection in (("Traders", "**Strategies**"), ("Regimes", "**Regime windows**"),
                            ("Manipulation", "**Pump-and-dump**"), ("Psychology", "**Components**")):
        assert subsection in [element.value for element in _tab(full_run, tab).markdown], tab


def test_a_section_drawn_alone_still_has_its_heading():
    alone = AppTest.from_function(_sections, kwargs={"heading": True}, default_timeout=120).run()
    tabbed = AppTest.from_function(_sections, kwargs={"heading": False}, default_timeout=120).run()
    shown = [element.value for element in alone.markdown]
    for heading in SECTION_HEADINGS:
        assert heading in shown, heading
    # Leaving the heading out changes nothing else.
    assert [m for m in shown if m not in SECTION_HEADINGS] == [element.value for element in tabbed.markdown]
    assert [c.value for c in alone.caption] == [c.value for c in tabbed.caption]
    assert [t.value.to_dict() for t in alone.dataframe] == [t.value.to_dict() for t in tabbed.dataframe]


# --- notes ---------------------------------------------------------------------------------------------


def _notes(container) -> list[str]:
    return [caption.value for expander in container.expander if expander.label == NOTES_LABEL
            for caption in expander.caption]


def test_follow_on_notes_are_kept_in_collapsed_expanders(full_run):
    regimes = _notes(_tab(full_run, "Regimes"))
    assert INCOMPLETE_NOTE in regimes
    assert any(note.startswith("A label shown as n/a is one the analytics report as unavailable") for note in regimes)
    manipulation = _notes(_tab(full_run, "Manipulation"))
    assert any(note.startswith("'Kinds observed' is the analytics' own coverage word") for note in manipulation)
    assert any(note.startswith("Phases are per manipulator") for note in manipulation)
    for expander in full_run.expander:
        if expander.label == NOTES_LABEL:
            assert expander.proto.expanded is False


def test_the_first_caption_of_each_view_stays_visible(full_run):
    regimes = _tab(full_run, "Regimes")
    hidden = set(_notes(regimes))
    visible = [caption.value for caption in regimes.caption if caption.value not in hidden]
    assert any(caption.startswith("One row per window, in the report's order") for caption in visible)


# --- batch charts --------------------------------------------------------------------------------------


def test_batch_disclosures_are_captions_and_titles_fit_a_narrow_plot():
    from crypto_simulator.visualization.batch_charts import (
        HISTOGRAM_DISCLOSURE,
        PRICE_PATH_DISCLOSURE,
        RANGE_DISCLOSURE,
    )

    at = AppTest.from_function(_dashboard, default_timeout=300).run()
    at.number_input(key="coin_dashboard_batch_runs").set_value(4)
    at.button(key="coin_dashboard_run_batch").click().run()
    batch = _tab(at, "Batch analysis")
    titles = [json.loads(chart.proto.spec)["layout"]["title"]["text"] for chart in batch.get("plotly_chart")]
    captions = [caption.value for caption in batch.caption]
    assert len(titles) == 6
    assert all("<br>" not in title and len(title) <= 45 for title in titles), titles
    for disclosure in (RANGE_DISCLOSURE, HISTOGRAM_DISCLOSURE, PRICE_PATH_DISCLOSURE):
        assert any(caption.startswith(disclosure) for caption in captions), disclosure


def test_the_detail_tabs_are_unchanged(full_run):
    single, *_ = (tab.label for tab in full_run.tabs)
    assert single == "Single run"
    assert [tab.label for tab in full_run.tabs][1:1 + len(RESULT_TABS)] == list(RESULT_TABS)
