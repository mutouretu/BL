from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import db


CURRENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    market TEXT NOT NULL DEFAULT 'A股',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    cash_balance REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES paper_projects(id),
    UNIQUE (project_id, name)
);

CREATE TABLE IF NOT EXISTS paper_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    signal_time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    action TEXT NOT NULL CHECK (action IN ('BUY', 'ADD', 'REDUCE', 'SELL', 'WATCH')),
    position_before REAL,
    target_position REAL,
    position_delta REAL,
    allocation_ratio REAL,
    allocation_basis TEXT CHECK (
        allocation_basis IS NULL OR allocation_basis IN ('CASH_POOL', 'STOCK_POSITION')
    ),
    reference_price REAL,
    predicted_high REAL,
    predicted_low REAL,
    signal_type TEXT,
    raw_text TEXT,
    source_ref TEXT,
    fingerprint TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'VALID'
        CHECK (status IN ('DRAFT', 'PENDING_CONFIRM', 'VALID', 'EXECUTED', 'IGNORED', 'INVALID')),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES paper_projects(id)
);

CREATE TABLE IF NOT EXISTS paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    signal_id INTEGER,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type TEXT NOT NULL DEFAULT 'MARKET_SIM',
    order_price REAL,
    order_quantity REAL NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('DRAFT', 'SUBMITTED', 'PARTIALLY_FILLED', 'FILLED', 'CANCELED', 'REJECTED')
    ),
    reject_reason TEXT,
    submitted_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES paper_accounts(id),
    FOREIGN KEY (signal_id) REFERENCES paper_signals(id),
    UNIQUE (account_id, signal_id)
);

CREATE TABLE IF NOT EXISTS paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    signal_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    fill_time TEXT NOT NULL,
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    commission REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0,
    operator TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES paper_orders(id),
    FOREIGN KEY (account_id) REFERENCES paper_accounts(id),
    FOREIGN KEY (signal_id) REFERENCES paper_signals(id)
);

CREATE TABLE IF NOT EXISTS paper_cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    fill_id INTEGER,
    note TEXT,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES paper_accounts(id),
    FOREIGN KEY (fill_id) REFERENCES paper_fills(id)
);

CREATE TABLE IF NOT EXISTS paper_positions (
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 0,
    cost_total REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol),
    FOREIGN KEY (account_id) REFERENCES paper_accounts(id)
);

CREATE TABLE IF NOT EXISTS paper_position_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    source_fill_id INTEGER NOT NULL,
    remaining_quantity REAL NOT NULL,
    available_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES paper_accounts(id),
    FOREIGN KEY (source_fill_id) REFERENCES paper_fills(id)
);

CREATE TABLE IF NOT EXISTS paper_market_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    high REAL,
    low REAL,
    close REAL,
    source TEXT NOT NULL DEFAULT 'STUB',
    updated_at TEXT NOT NULL,
    UNIQUE (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS paper_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    operator TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paper_signals_project_date
    ON paper_signals(project_id, trade_date, signal_time);
CREATE INDEX IF NOT EXISTS idx_paper_fills_account_time
    ON paper_fills(account_id, fill_time);
CREATE INDEX IF NOT EXISTS idx_paper_lots_account_symbol
    ON paper_position_lots(account_id, symbol, available_date);
"""


LEGACY_COPY_SQL = """
INSERT OR IGNORE INTO paper_projects
SELECT id, name, market, created_at FROM shadow_projects;

INSERT OR IGNORE INTO paper_accounts (
    id, project_id, name, initial_cash, cash_balance, currency, is_active, created_at
)
SELECT id, project_id, name, initial_cash, cash_balance, currency, is_active, created_at
FROM shadow_accounts
WHERE book_type = 'PAPER';

INSERT OR IGNORE INTO paper_signals
SELECT * FROM shadow_signals;

INSERT OR IGNORE INTO paper_orders
SELECT o.id, o.account_id, o.signal_id, o.side, o.order_type, o.order_price,
       o.order_quantity, o.status, o.reject_reason, o.submitted_at, o.created_at
FROM shadow_orders o
JOIN shadow_accounts a ON a.id = o.account_id
WHERE a.book_type = 'PAPER';

INSERT OR IGNORE INTO paper_fills
SELECT f.* FROM shadow_fills f
JOIN shadow_accounts a ON a.id = f.account_id
WHERE a.book_type = 'PAPER';

INSERT OR IGNORE INTO paper_cash_ledger
SELECT l.* FROM shadow_cash_ledger l
JOIN shadow_accounts a ON a.id = l.account_id
WHERE a.book_type = 'PAPER';

INSERT OR IGNORE INTO paper_positions
SELECT p.* FROM shadow_positions p
JOIN shadow_accounts a ON a.id = p.account_id
WHERE a.book_type = 'PAPER';

INSERT OR IGNORE INTO paper_position_lots
SELECT l.* FROM shadow_position_lots l
JOIN shadow_accounts a ON a.id = l.account_id
WHERE a.book_type = 'PAPER';

INSERT OR IGNORE INTO paper_market_daily
SELECT * FROM shadow_market_daily;

INSERT OR IGNORE INTO paper_audit_events
SELECT e.* FROM shadow_audit_events e
WHERE e.entity_type = 'ORDER'
  AND EXISTS (SELECT 1 FROM paper_orders o WHERE o.id = e.entity_id);

DROP TABLE shadow_cash_ledger;
DROP TABLE shadow_position_lots;
DROP TABLE shadow_positions;
DROP TABLE shadow_fills;
DROP TABLE shadow_orders;
DROP TABLE shadow_signals;
DROP TABLE shadow_accounts;
DROP TABLE shadow_market_daily;
DROP TABLE shadow_audit_events;
DROP TABLE shadow_projects;
"""

TRACKING_SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    lot_size INTEGER NOT NULL DEFAULT 100,
    t_plus_days INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    instrument_id INTEGER NOT NULL,
    tracking_state TEXT NOT NULL
        CHECK (tracking_state IN ('WATCHING', 'HOLDING', 'CLOSED', 'EXPIRED')),
    recommended_at TEXT NOT NULL,
    watch_expires_at TEXT,
    source_recommendation_id TEXT,
    latest_action TEXT,
    latest_signal_at TEXT,
    target_position REAL,
    pending_cash_ratio REAL CHECK (
        pending_cash_ratio IS NULL OR pending_cash_ratio IN (0.10, 0.40, 0.50)
    ),
    pending_sell_ratio REAL CHECK (
        pending_sell_ratio IS NULL OR pending_sell_ratio IN (0.50, 1.00)
    ),
    reference_price REAL,
    predicted_low REAL,
    predicted_high REAL,
    peak_hint TEXT,
    processing_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (processing_status IN ('PENDING', 'CONFIRMED', 'IGNORED', 'SIGNALLED')),
    raw_text TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES paper_projects(id),
    FOREIGN KEY (instrument_id) REFERENCES instruments(id),
    UNIQUE (project_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    external_event_id TEXT,
    instrument_id INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    signal_type TEXT,
    raw_action TEXT,
    normalized_action TEXT NOT NULL
        CHECK (normalized_action IN ('BUY', 'ADD', 'WATCH', 'REDUCE', 'SELL')),
    target_position REAL,
    reference_price REAL,
    predicted_low REAL,
    predicted_high REAL,
    raw_text TEXT,
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    source_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL UNIQUE,
    processing_status TEXT NOT NULL DEFAULT 'RECORDED'
        CHECK (processing_status IN (
            'RECORDED', 'PENDING_RULE', 'ORDER_CREATED',
            'DUPLICATE_RECORDED', 'IGNORED', 'REJECTED'
        )),
    processing_reason TEXT,
    parser_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES paper_projects(id),
    FOREIGN KEY (instrument_id) REFERENCES instruments(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_events_source_external
    ON signal_events(source_name, external_event_id)
    WHERE external_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tracked_project_state
    ON tracked_instruments(project_id, tracking_state, recommended_at);
CREATE INDEX IF NOT EXISTS idx_signal_events_project_instrument_time
    ON signal_events(project_id, instrument_id, occurred_at);
"""

THEORY_RECORD_SCHEMA = """
CREATE TABLE IF NOT EXISTS theory_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '理论账户',
    initial_cash REAL NOT NULL,
    cash_balance REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES paper_projects(id)
);

CREATE TABLE IF NOT EXISTS theory_trade_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    recorded_at TEXT NOT NULL,
    allocation_ratio REAL NOT NULL,
    allocation_basis TEXT NOT NULL CHECK (
        allocation_basis IN ('CASH_POOL', 'STOCK_POSITION')
    ),
    reference_price REAL NOT NULL,
    price_time TEXT NOT NULL,
    price_source TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    gross_amount REAL NOT NULL,
    cash_change REAL NOT NULL,
    equity_before REAL NOT NULL,
    cash_before REAL NOT NULL,
    position_before INTEGER NOT NULL,
    capital_ratio REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    operator TEXT NOT NULL DEFAULT '手工记录',
    fixture_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES paper_projects(id),
    FOREIGN KEY (account_id) REFERENCES theory_accounts(id)
);

CREATE TABLE IF NOT EXISTS theory_cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    record_id INTEGER,
    event_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    note TEXT,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES theory_accounts(id),
    FOREIGN KEY (record_id) REFERENCES theory_trade_records(id)
);

CREATE TABLE IF NOT EXISTS theory_positions (
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    cost_total REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol),
    FOREIGN KEY (account_id) REFERENCES theory_accounts(id)
);

CREATE TABLE IF NOT EXISTS theory_position_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    source_record_id INTEGER NOT NULL,
    remaining_quantity INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    available_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES theory_accounts(id),
    FOREIGN KEY (source_record_id) REFERENCES theory_trade_records(id)
);

CREATE TABLE IF NOT EXISTS theory_reference_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    price_time TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '本地样本',
    created_at TEXT NOT NULL,
    UNIQUE (symbol, price_time, source)
);

CREATE INDEX IF NOT EXISTS idx_theory_records_project_time
    ON theory_trade_records(project_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_theory_records_account_symbol
    ON theory_trade_records(account_id, symbol, recorded_at);
CREATE INDEX IF NOT EXISTS idx_theory_lots_available
    ON theory_position_lots(account_id, symbol, available_date);
CREATE INDEX IF NOT EXISTS idx_theory_prices_symbol_time
    ON theory_reference_prices(symbol, price_time);
"""


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    result = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return result is not None


def _backup_legacy_database(conn: sqlite3.Connection) -> None:
    database_path = Path(db.DB_PATH)
    if str(database_path) == ":memory:" or not database_path.exists():
        return
    backup_path = Path(f"{database_path}.pre-paper-v2.bak")
    if backup_path.exists():
        return
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)


def _create_current_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(CURRENT_SCHEMA)


def _migrate_legacy_shadow_schema(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "shadow_projects"):
        conn.executescript(LEGACY_COPY_SQL)


def _create_tracking_and_signal_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TRACKING_SCHEMA)


def _add_pending_cash_ratio(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(tracked_instruments)")
    }
    if "pending_cash_ratio" not in columns:
        conn.execute(
            """
            ALTER TABLE tracked_instruments
            ADD COLUMN pending_cash_ratio REAL CHECK (
                pending_cash_ratio IS NULL OR pending_cash_ratio IN (0.10, 0.40, 0.50)
            )
            """
        )


def _add_pending_sell_ratio(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(tracked_instruments)")
    }
    if "pending_sell_ratio" not in columns:
        conn.execute(
            """
            ALTER TABLE tracked_instruments
            ADD COLUMN pending_sell_ratio REAL CHECK (
                pending_sell_ratio IS NULL OR pending_sell_ratio IN (0.50, 1.00)
            )
            """
        )


def _add_signal_allocation_fields(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(paper_signals)")
    }
    if "allocation_ratio" not in columns:
        conn.execute("ALTER TABLE paper_signals ADD COLUMN allocation_ratio REAL")
    if "allocation_basis" not in columns:
        conn.execute(
            """
            ALTER TABLE paper_signals
            ADD COLUMN allocation_basis TEXT CHECK (
                allocation_basis IS NULL OR allocation_basis IN ('CASH_POOL', 'STOCK_POSITION')
            )
            """
        )


def _create_theory_record_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(THEORY_RECORD_SCHEMA)


def _canonicalize_symbol_aliases(conn: sqlite3.Connection) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE instruments
        SET symbol = substr(symbol, 1, length(symbol) - 3) || '.SH',
            exchange = 'SH',
            updated_at = ?
        WHERE symbol LIKE '%.SS'
          AND NOT EXISTS (
              SELECT 1 FROM instruments target
              WHERE target.symbol = substr(instruments.symbol, 1, length(instruments.symbol) - 3) || '.SH'
          )
        """,
        (timestamp,),
    )
    for table in (
        "paper_signals",
        "paper_fills",
        "paper_position_lots",
        "theory_trade_records",
        "theory_position_lots",
    ):
        conn.execute(
            f"""
            UPDATE {table}
            SET symbol = substr(symbol, 1, length(symbol) - 3) || '.SH'
            WHERE symbol LIKE '%.SS'
            """
        )
    for table in ("paper_positions", "theory_positions"):
        conn.execute(
            f"""
            UPDATE {table}
            SET symbol = substr(symbol, 1, length(symbol) - 3) || '.SH'
            WHERE symbol LIKE '%.SS'
              AND NOT EXISTS (
                  SELECT 1 FROM {table} target
                  WHERE target.account_id = {table}.account_id
                    AND target.symbol = substr({table}.symbol, 1, length({table}.symbol) - 3) || '.SH'
              )
            """
        )
    conn.execute(
        """
        UPDATE paper_market_daily
        SET symbol = substr(symbol, 1, length(symbol) - 3) || '.SH'
        WHERE symbol LIKE '%.SS'
          AND NOT EXISTS (
              SELECT 1 FROM paper_market_daily target
              WHERE target.trade_date = paper_market_daily.trade_date
                AND target.symbol = substr(paper_market_daily.symbol, 1, length(paper_market_daily.symbol) - 3) || '.SH'
          )
        """
    )
    conn.execute(
        """
        UPDATE theory_reference_prices
        SET symbol = substr(symbol, 1, length(symbol) - 3) || '.SH'
        WHERE symbol LIKE '%.SS'
          AND NOT EXISTS (
              SELECT 1 FROM theory_reference_prices target
              WHERE target.price_time = theory_reference_prices.price_time
                AND target.source = theory_reference_prices.source
                AND target.symbol = substr(theory_reference_prices.symbol, 1, length(theory_reference_prices.symbol) - 3) || '.SH'
          )
        """
    )


MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
    (1, "create_paper_schema", _create_current_schema),
    (2, "remove_manual_ledger_and_migrate_shadow_tables", _migrate_legacy_shadow_schema),
    (3, "create_tracking_and_signal_event_schema", _create_tracking_and_signal_schema),
    (4, "add_pending_cash_allocation_ratio", _add_pending_cash_ratio),
    (5, "add_pending_sell_ratio", _add_pending_sell_ratio),
    (6, "add_signal_allocation_fields", _add_signal_allocation_fields),
    (7, "create_manual_theory_record_schema", _create_theory_record_schema),
    (8, "canonicalize_symbol_aliases", _canonicalize_symbol_aliases),
)


def migrate() -> None:
    """Bring a fresh or legacy database to the current schema."""
    with db.get_connection() as conn:
        if _table_exists(conn, "shadow_projects"):
            _backup_legacy_database(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            int(item["version"])
            for item in conn.execute("SELECT version FROM schema_migrations")
        }
        for version, name, migration in MIGRATIONS:
            if version in applied:
                continue
            migration(conn)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with db.get_connection() as conn:
        return conn.execute(query, params).fetchall()


def row(query: str, params: tuple = ()) -> sqlite3.Row | None:
    with db.get_connection() as conn:
        return conn.execute(query, params).fetchone()
