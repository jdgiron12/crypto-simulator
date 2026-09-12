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


def main() -> None:
    st.set_page_config(
        page_title=settings.ui.page_title,
        page_icon=settings.ui.page_icon,
        layout=settings.ui.layout,
    )

    st.title(f"{settings.ui.page_icon} {settings.ui.page_title}")
    st.warning(
        "**Fictional simulator — educational use only.** No real exchange "
        "connections, no real trades, no real money.",
        icon="⚠️",
    )

    # Initialize (or connect to) the SQLite database on startup so every
    # page can rely on the schema already existing.
    with get_connection(settings.database.path, echo=settings.database.echo) as conn:
        logger.info("Database ready at %s", settings.database.path)

        market_service = MarketService(conn, _get_market_engine())

        tab_dashboard, tab_trade, tab_portfolio, tab_history = st.tabs(
            ["📊 Dashboard", "💱 Trade", "💼 Portfolio", "🧾 History"]
        )

        with tab_dashboard:
            st.caption(f"Simulated assets: {', '.join(settings.market.assets)}")
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
                    use_container_width=True,
                )

        with tab_trade:
            st.info("Order entry — coming soon. See docs/ROADMAP.md.")

        with tab_portfolio:
            st.info("Portfolio & P&L view — coming soon. See docs/ROADMAP.md.")
            st.caption(f"Starting balance: {settings.simulation.starting_balance:,.2f} {settings.simulation.base_currency}")

        with tab_history:
            st.info("Order & trade history — coming soon. See docs/ROADMAP.md.")


if __name__ == "__main__":
    main()
