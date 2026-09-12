from crypto_simulator.data.repositories import AccountRepository, AssetRepository
from crypto_simulator.models.account import Account, Holding
from crypto_simulator.models.asset import Asset


def test_asset_repository_add_and_get(db_conn):
    repo = AssetRepository(db_conn)
    repo.add(Asset(symbol="BTC", name="Bitcoin (Simulated)"))

    fetched = repo.get("BTC")
    assert fetched is not None
    assert fetched.name == "Bitcoin (Simulated)"
    assert repo.get("DOES_NOT_EXIST") is None


def test_asset_repository_list_all(db_conn):
    repo = AssetRepository(db_conn)
    repo.add(Asset(symbol="ETH", name="Ethereum (Simulated)"))
    repo.add(Asset(symbol="BTC", name="Bitcoin (Simulated)"))

    symbols = [asset.symbol for asset in repo.list_all()]
    assert symbols == sorted(symbols)
    assert set(symbols) == {"BTC", "ETH"}


def test_account_repository_round_trip_with_holdings(db_conn):
    AssetRepository(db_conn).add(Asset(symbol="BTC", name="Bitcoin (Simulated)"))
    accounts = AccountRepository(db_conn)
    account = Account(cash_balance=100_000.0)
    accounts.add(account)
    accounts.upsert_holding(account.id, Holding(symbol="BTC", quantity=1.5, average_cost=60000.0))

    fetched = accounts.get(account.id)
    assert fetched is not None
    assert fetched.cash_balance == 100_000.0
    assert fetched.holdings["BTC"].quantity == 1.5
