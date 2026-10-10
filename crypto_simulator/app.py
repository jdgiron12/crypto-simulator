"""Streamlit entrypoint for the Crypto Market Simulator.

Presentation only: this module renders UI and delegates all logic to
``services``. It must never contain simulation math, SQL, or (needless to
say) real exchange connectivity.
"""

from __future__ import annotations

import streamlit as st

from crypto_simulator.config import get_settings
from crypto_simulator.core.clock import SimulationClock
from crypto_simulator.core.market_engine import MarketEngine
from crypto_simulator.dashboard.view import render_dashboard, retain_control_state
from crypto_simulator.data.database import get_connection
from crypto_simulator.services.market_service import MarketService
from crypto_simulator.utils.logger import configure_logging, get_logger
from crypto_simulator.visualization.charts import candlestick_chart

settings = get_settings()
configure_logging(settings.logging)
logger = get_logger(__name__)


def _get_market_engine() -> MarketEngine:
    """Return the session's ``MarketEngine``, creating it on first use.

    Cached in ``st.session_state`` (rather than rebuilt every rerun) so its
    RNG state and current prices persist across Streamlit reruns instead of
    resetting on every widget interaction.
    """
    if "market_engine" not in st.session_state:
        clock = SimulationClock(tick_interval=settings.simulation.tick_interval_seconds)
        st.session_state.market_engine = MarketEngine(
            settings.market.assets,
            clock,
            seed=settings.simulation.random_seed,
            initial_prices=settings.market.initial_prices,
            volatility=settings.market.volatility,
        )
    return st.session_state.market_engine


#: The app's pages, in navigation order: (section, title, url path, icon).
#: The working coin simulator is the landing page. The dormant multi-asset
#: experiment sits apart under "Legacy". The trading platform's Trade,
#: Portfolio and History views are not implemented, so they are not pages
#: (see docs/ROADMAP.md); nothing here offers order entry.
PAGES: tuple[tuple[str, str, str, str], ...] = (
    ("", "Simulate", "simulate", ":material/monitoring:"),
    ("Legacy", "Multi-asset sandbox", "sandbox", ":material/science:"),
)

DISCLAIMER = (
    "**Fictional simulator — educational use only.** No real exchange "
    "connections, no real trades, no real money."
)

SANDBOX_CAPTION = (
    "An early experiment kept for reference: its own synthetic price process for "
    f"{', '.join(settings.market.assets)}, separate from the coin simulator. "
    "It generates prices only — there is no trading here."
)


def render_market_sandbox(market_service: MarketService) -> None:
    """The dormant trading-platform track's price view (formerly the
    Dashboard tab): advance the multi-asset engine and chart one asset."""
    st.subheader("Multi-asset sandbox")
    st.caption(SANDBOX_CAPTION)
    symbol = st.selectbox("Asset", settings.market.assets)
    if st.button("⏭️ Advance market by 1 tick"):
        market_service.step()

    history = market_service.price_history_df(symbol, limit=200)
    if history.empty:
        st.info(
            "No simulated price history yet — click "
            "'Advance market by 1 tick' to generate some."
        )
    else:
        st.metric(f"{symbol} price", f"{market_service.current_prices()[symbol]:,.2f}")
        st.plotly_chart(
            candlestick_chart(history, title=f"{symbol} (simulated)"),
            width="stretch", theme=None,
        )


def main() -> None:
    st.set_page_config(
        page_title=settings.ui.page_title,
        page_icon=settings.ui.page_icon,
        layout=settings.ui.layout,
    )

    # Initialize (or connect to) the SQLite database on every run so every
    # page can rely on the schema already existing.
    with get_connection(settings.database.path, echo=settings.database.echo) as conn:
        logger.info("Database ready at %s", settings.database.path)

        market_service = MarketService(conn, _get_market_engine())

        def simulate() -> None:
            # The coin-economy track (core.coin_simulator): a read-only view
            # of a finished run's analytics report. It uses neither the
            # database nor the multi-asset market engine.
            render_dashboard()

        def sandbox() -> None:
            render_market_sandbox(market_service)

        render = {"simulate": simulate, "sandbox": sandbox}
        sections: dict[str, list] = {}
        for section, title, url_path, icon in PAGES:
            sections.setdefault(section, []).append(
                st.Page(render[url_path], title=title, url_path=url_path, icon=icon,
                        default=url_path == PAGES[0][2])
            )
        page = st.navigation(sections, position="top")

        # One compact line on every page: the product and the disclaimer.
        # Each page draws its own heading below it.
        st.caption(f"**{settings.ui.page_title}** · {DISCLAIMER}")
        # Keep the run controls through a visit to another page.
        retain_control_state()
        page.run()


if __name__ == "__main__":
    main()
