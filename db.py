from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path("guanfu_trade_manager.sqlite3")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
