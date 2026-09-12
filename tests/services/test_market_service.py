from crypto_simulator.core.clock import SimulationClock
from crypto_simulator.core.market_engine import MarketEngine
from crypto_simulator.services.market_service import MarketService


def _make_service(db_conn, *, symbols=("BTC", "ETH")):
    engine = MarketEngine(list(symbols), SimulationClock(), seed=1)
    return MarketService(db_conn, engine)


def test_construction_seeds_assets_for_engine_symbols(db_conn):
    service = _make_service(db_conn)
    symbols = {asset.symbol for asset in service.list_assets()}
    assert symbols == {"BTC", "ETH"}


def test_step_persists_a_bar_per_symbol(db_conn):
    service = _make_service(db_conn)
    service.step()

    btc_history = service.price_history_df("BTC")
    eth_history = service.price_history_df("ETH")
    assert len(btc_history) == 1
    assert len(eth_history) == 1


def test_step_returns_current_prices(db_conn):
    service = _make_service(db_conn)
    new_prices = service.step()
    assert new_prices == service.current_prices()


def test_price_history_accumulates_across_steps(db_conn):
    service = _make_service(db_conn)
    for _ in range(5):
        service.step()

    history = service.price_history_df("BTC")
    assert len(history) == 5
    assert list(history.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert history["timestamp"].is_monotonic_increasing


def test_price_history_respects_limit(db_conn):
    service = _make_service(db_conn)
    for _ in range(5):
        service.step()

    history = service.price_history_df("BTC", limit=2)
    assert len(history) == 2


def test_price_history_empty_before_any_step(db_conn):
    service = _make_service(db_conn)
    history = service.price_history_df("BTC")
    assert history.empty
