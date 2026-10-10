"""The application shell (Phase 24, Step 3).

``app.py`` is a multipage app: the coin simulator is the landing page and
the dormant multi-asset experiment is a separate, secondary page. The
trading platform's unimplemented Trade, Portfolio and History views are
not pages. The run controls survive a visit to another page.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from crypto_simulator import app as app_module
from crypto_simulator.config import clear_settings_cache
from crypto_simulator.dashboard.view import EMPTY_MESSAGE, PAGE_HEADING, RUN_CONTROL_KEYS

APP = Path(app_module.__file__)


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYPTOSIM_DB_PATH", str(tmp_path / "app.sqlite3"))
    clear_settings_cache()
    yield tmp_path / "app.sqlite3"
    clear_settings_cache()


def _text(at: AppTest) -> str:
    parts = []
    for kind in ("title", "subheader", "markdown", "caption", "info", "warning", "error", "success"):
        parts += [str(element.value) for element in getattr(at, kind)]
    return " ".join(parts)


# --- the page list -------------------------------------------------------------------------------------


def test_the_coin_simulator_is_the_first_and_landing_page():
    section, title, url_path, _ = app_module.PAGES[0]
    assert (section, title, url_path) == ("", "Simulate", "simulate")


def test_the_multi_asset_experiment_is_a_separate_legacy_page():
    legacy = [page for page in app_module.PAGES if page[0] == "Legacy"]
    assert [(title, url_path) for _, title, url_path, _ in legacy] == [("Multi-asset sandbox", "sandbox")]


def test_no_page_offers_unimplemented_trading():
    titles = " ".join(title.lower() for _, title, _, _ in app_module.PAGES)
    for word in ("trade", "portfolio", "history", "order"):
        assert word not in titles


def test_page_paths_are_unique():
    paths = [url_path for _, _, url_path, _ in app_module.PAGES]
    assert len(set(paths)) == len(paths)


# --- the landing page ----------------------------------------------------------------------------------


def test_the_app_lands_on_the_coin_simulator(isolated_db):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception
    # Phase 24, Step 4: the product name moved from a large title into the
    # compact header line, and the page names itself with its own heading.
    assert len(at.title) == 0
    assert any(f"**{app_module.settings.ui.page_title}**" in caption.value for caption in at.caption)
    assert [header.value for header in at.subheader] == [PAGE_HEADING, "Run setup"]
    assert EMPTY_MESSAGE in [info.value for info in at.info]
    assert at.button(key="coin_dashboard_run") is not None
    assert at.button(key="coin_dashboard_run_batch") is not None
    assert at.button(key="coin_dashboard_run_comparison") is not None


def test_every_page_carries_the_disclaimer(isolated_db):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    captions = [caption.value for caption in at.caption]
    assert sum(app_module.DISCLAIMER in caption for caption in captions) == 1


def test_the_landing_page_has_no_placeholder_tabs_or_sandbox(isolated_db):
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    # Phase 24, Step 4 adds the workspace's own tabs; none is a trading placeholder.
    labels = " ".join(tab.label.lower() for tab in at.tabs)
    for word in ("trade", "portfolio", "history"):
        assert word not in labels
    assert "coming soon" not in _text(at).lower()
    assert "Asset" not in [box.label for box in at.selectbox]
    assert "Multi-asset sandbox" not in _text(at)


# --- the sandbox page ----------------------------------------------------------------------------------


def _sandbox(db_path: str):
    """The sandbox page on its own (AppTest executes this function's source).

    The database path is passed in: ``app.settings`` is read once at
    import, so it would point at the real local database."""
    from crypto_simulator.app import _get_market_engine, render_market_sandbox
    from crypto_simulator.data.database import get_connection
    from crypto_simulator.services.market_service import MarketService

    with get_connection(db_path) as conn:
        render_market_sandbox(MarketService(conn, _get_market_engine()))


def _sandbox_app(db_path: Path) -> AppTest:
    return AppTest.from_function(_sandbox, kwargs={"db_path": str(db_path)}, default_timeout=60).run()


def test_the_sandbox_page_explains_itself_and_starts_empty(isolated_db):
    at = _sandbox_app(isolated_db)
    assert not at.exception, at.exception
    assert [header.value for header in at.subheader] == ["Multi-asset sandbox"]
    assert app_module.SANDBOX_CAPTION in [caption.value for caption in at.caption]
    assert [box.label for box in at.selectbox] == ["Asset"]
    assert any("No simulated price history yet" in info.value for info in at.info)


def test_the_sandbox_still_advances_and_charts_its_market(isolated_db):
    at = _sandbox_app(isolated_db)
    at.button[0].click().run()
    assert not at.exception
    assert len(at.metric) == 1
    assert len(at.get("plotly_chart")) == 1
    assert isolated_db.exists()


# --- the run controls survive a visit to another page --------------------------------------------------


def _paged(retain: bool):
    """The dashboard drawn only while ``st.session_state.show`` is true —
    the same thing a page switch does — with or without
    ``retain_control_state`` running first, as the app runs it."""
    import streamlit as st

    from crypto_simulator.dashboard.data import run_simulation
    from crypto_simulator.dashboard.view import render_dashboard, retain_control_state

    if retain:
        retain_control_state()
    if st.session_state.get("show", True):
        render_dashboard(runner=run_simulation)
    else:
        st.write("another page")


CHANGED = {
    "coin_dashboard_ticks": 7,
    "coin_dashboard_whales": False,
    "coin_dashboard_psychology": True,
    "coin_dashboard_batch_runs": 3,
    "coin_dashboard_compare_runs": 4,
}


def _visit_another_page(at: AppTest) -> AppTest:
    at.session_state["show"] = False
    at.run()
    at.run()  # a second run on the other page is when Streamlit drops unkept widget state
    at.session_state["show"] = True
    return at.run()


def _change_controls(at: AppTest) -> None:
    for key, value in CHANGED.items():
        widget = at.checkbox(key=key) if isinstance(value, bool) else at.number_input(key=key)
        widget.set_value(value)
    at.run()


def test_run_controls_survive_a_visit_to_another_page():
    at = AppTest.from_function(_paged, kwargs={"retain": True}, default_timeout=60).run()
    _change_controls(at)
    _visit_another_page(at)
    assert not at.exception
    for key, value in CHANGED.items():
        assert at.session_state[key] == value, key
    assert at.number_input(key="coin_dashboard_ticks").value == 7
    assert at.checkbox(key="coin_dashboard_whales").value is False


def test_without_retaining_streamlit_would_reset_the_controls():
    """The control case: it is ``retain_control_state`` that keeps them."""
    at = AppTest.from_function(_paged, kwargs={"retain": False}, default_timeout=60).run()
    _change_controls(at)
    _visit_another_page(at)
    assert at.number_input(key="coin_dashboard_ticks").value == 20
    assert at.checkbox(key="coin_dashboard_whales").value is True


def test_a_run_after_returning_uses_the_kept_controls():
    at = AppTest.from_function(_paged, kwargs={"retain": True}, default_timeout=60).run()
    _change_controls(at)
    _visit_another_page(at)
    at.button(key="coin_dashboard_run").click().run()
    params = at.session_state["coin_dashboard_payload"]["simulation"]["params"]
    assert params["ticks"] == 7
    assert params["include_whales"] is False
    assert params["psychology"] is True


def test_retaining_before_the_dashboard_is_drawn_invents_nothing():
    state: dict = {}
    from crypto_simulator.dashboard.view import retain_control_state

    retain_control_state(state)
    assert state == {}


def test_every_run_control_widget_is_kept():
    """Every widget key the controls draw is in ``RUN_CONTROL_KEYS``."""
    at = AppTest.from_function(_paged, kwargs={"retain": True}, default_timeout=60).run()
    drawn = {
        widget.key
        for kind in ("number_input", "checkbox", "selectbox", "multiselect")
        for widget in getattr(at, kind)
        if widget.key and widget.key.startswith("coin_dashboard_")
    }
    assert drawn == set(RUN_CONTROL_KEYS)
