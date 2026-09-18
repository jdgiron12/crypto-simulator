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

-- ---------------------------------------------------------------------------
-- Coin economy track (Phase 12).
--
-- The tables above belong to the multi-asset trading platform (assets,
-- accounts, orders). These two belong to the standalone coin-economy
-- simulation, which was ephemeral before Phase 12: a finished run is stored
-- here so later phases can reload it. They share this file and this database
-- because they share one connection layer (database.py); they are otherwise
-- independent and never join against each other.
--
-- A run is stored as it already exists in memory: the run's metadata and its
-- ordered per-tick series as columns (Phase 15 aggregates over these), and
-- the request and the analytics report as JSON text (read whole, never
-- queried field by field). This stores a *completed* run; it is not a
-- checkpoint of a live simulator and cannot resume one.

CREATE TABLE IF NOT EXISTS coin_runs (
    -- Surrogate key: simulation_id is derived from the request and seed, so
    -- saving the same request twice is legal and gives two rows.
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id   TEXT NOT NULL,
    saved_at        TEXT NOT NULL,
    random_seed     INTEGER NOT NULL,
    pricing_mode    TEXT NOT NULL,
    coin_symbol     TEXT NOT NULL,
    coin_name       TEXT NOT NULL,
    initial_supply  REAL NOT NULL,
    starting_price  REAL NOT NULL,
    requested_ticks INTEGER NOT NULL,
    completed_ticks INTEGER NOT NULL CHECK (completed_ticks >= 0),
    params_json     TEXT NOT NULL,
    report_json     TEXT NOT NULL
);

-- Runs of one request are looked up together (a batch in Phase 14 shares a
-- request and varies the seed); run_id lookups already use the primary key.
CREATE INDEX IF NOT EXISTS idx_coin_runs_simulation_id ON coin_runs (simulation_id);

CREATE TABLE IF NOT EXISTS coin_run_ticks (
    run_id      INTEGER NOT NULL REFERENCES coin_runs (run_id) ON DELETE CASCADE,
    tick        INTEGER NOT NULL,
    price       REAL NOT NULL,
    market_cap  REAL NOT NULL,
    volume      REAL NOT NULL,
    -- One row per tick per run, and the index that reads a run's series in
    -- tick order.
    PRIMARY KEY (run_id, tick)
);

-- Saved scenarios (Phase 13).
--
-- A *scenario* here is a named, reusable set of simulation INPUTS — one
-- SimulationParams under a name the user chooses — not a completed run and
-- not a paused simulator. coin_runs above stores what a simulation produced;
-- this stores what to ask for. Loading one rebuilds the request and runs it
-- again from the start; it does not resume anything.
--
-- Note the word is overloaded: params_json's own "scenario" field names a
-- manipulation preset (pump_and_dump, wash_trading) and is one field of the
-- request stored here, not the request itself.

CREATE TABLE IF NOT EXISTS coin_scenarios (
    scenario_id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- The identity a user refers to. UNIQUE so saving under an existing
    -- name updates that scenario instead of quietly creating a second one
    -- with the same name, and it indexes the lookup by name for free.
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    params_json TEXT NOT NULL
);
