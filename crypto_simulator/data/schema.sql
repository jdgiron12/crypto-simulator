-- Schema for the Crypto Market Simulator's SQLite persistence layer.
-- All data here is synthetic simulation state — no real financial data.

CREATE TABLE IF NOT EXISTS assets (
    symbol         TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    base_currency  TEXT NOT NULL DEFAULT 'USD'
);

CREATE TABLE IF NOT EXISTS accounts (
    id             TEXT PRIMARY KEY,
    cash_balance   REAL NOT NULL,
    base_currency  TEXT NOT NULL DEFAULT 'USD'
);

CREATE TABLE IF NOT EXISTS holdings (
    account_id     TEXT NOT NULL REFERENCES accounts(id),
    symbol         TEXT NOT NULL REFERENCES assets(symbol),
    quantity       REAL NOT NULL DEFAULT 0,
    average_cost   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS orders (
    id             TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES accounts(id),
    symbol         TEXT NOT NULL REFERENCES assets(symbol),
    side           TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type     TEXT NOT NULL CHECK (order_type IN ('market', 'limit')),
    quantity       REAL NOT NULL,
    limit_price    REAL,
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id             TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES orders(id),
    account_id     TEXT NOT NULL REFERENCES accounts(id),
    symbol         TEXT NOT NULL REFERENCES assets(symbol),
    side           TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity       REAL NOT NULL,
    price          REAL NOT NULL,
    executed_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    symbol         TEXT NOT NULL REFERENCES assets(symbol),
    timestamp      TEXT NOT NULL,
    open           REAL NOT NULL,
    high           REAL NOT NULL,
    low            REAL NOT NULL,
    close          REAL NOT NULL,
    volume         REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timestamp)
);
