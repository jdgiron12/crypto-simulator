from crypto_simulator.data.database import connect, init_db


def test_init_db_creates_expected_tables():
    conn = connect(":memory:")
    init_db(conn)
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    expected = {"assets", "accounts", "holdings", "orders", "trades", "price_history"}
    assert expected <= tables
    conn.close()
