from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import db
import paper_db
import paper_services


class PaperTradingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "test.sqlite3"
        paper_db.migrate()
        self.project_id, self.paper_id = paper_services.create_demo_project()

    def tearDown(self) -> None:
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def create_signal(
        self,
        action: str = "BUY",
        target: float = 0.25,
        signal_time: str = "2026-07-22 09:43:00",
        raw_text: str = "信号①④，目标25%",
    ) -> int:
        return paper_services.create_signal(
            project_id=self.project_id,
            trade_date=signal_time[:10],
            signal_time=signal_time,
            symbol="300377.SZ",
            name="赢时胜",
            action=action,
            target_position=target,
            reference_price=10,
            raw_text=raw_text,
            signal_type="①④",
        )

    def test_fresh_schema_only_contains_paper_account(self) -> None:
        with db.get_connection() as conn:
            accounts = conn.execute("SELECT * FROM paper_accounts").fetchall()
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(paper_accounts)")
            }
        self.assertEqual(len(accounts), 1)
        self.assertNotIn("book_type", columns)
        self.assertNotIn("paired_account_id", columns)

    def test_duplicate_signal_is_idempotent(self) -> None:
        first = self.create_signal()
        second = self.create_signal()
        self.assertEqual(first, second)
        self.assertEqual(len(paper_services.list_signals(self.project_id)), 1)

    def test_paper_target_position_creates_order_fill_and_cash_ledger(self) -> None:
        signal_id = self.create_signal()
        preview = paper_services.preview_execution(signal_id, self.paper_id)
        self.assertEqual(preview.side, "BUY")
        self.assertEqual(preview.order_quantity, 2400)
        self.assertIsNone(preview.reject_reason)

        order_id = paper_services.execute_paper_signal(signal_id, self.paper_id)
        repeated_order_id = paper_services.execute_paper_signal(
            signal_id, self.paper_id
        )
        orders = paper_services.order_rows(self.project_id)
        fills = paper_services.fill_rows(self.paper_id)
        positions = paper_services.position_rows(self.paper_id)

        self.assertEqual(order_id, repeated_order_id)
        self.assertEqual(order_id, orders[0]["id"])
        self.assertEqual(orders[0]["status"], "FILLED")
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(fills), 1)
        self.assertEqual(positions[0]["持仓数量"], 2400)
        self.assertGreater(paper_services.account_summary(self.paper_id)["cash"], 0)

        instruments = paper_services.trade_history_instruments(self.project_id)
        history = paper_services.trade_history(self.project_id, "300377.SZ")
        self.assertEqual(
            instruments,
            [{"symbol": "300377.SZ", "name": "赢时胜", "has_trade": 1}],
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["side"], "BUY")
        self.assertEqual(history[0]["quantity"], 2400)
        self.assertIsNone(history[0]["allocation_ratio"])
        self.assertGreater(history[0]["capital_ratio"], 0)
        self.assertLess(history[0]["cash_change"], 0)

    def test_same_day_sell_is_rejected_by_t1(self) -> None:
        buy_signal = self.create_signal()
        paper_services.execute_paper_signal(buy_signal, self.paper_id)
        sell_signal = self.create_signal(
            action="SELL",
            target=0,
            signal_time="2026-07-22 14:30:00",
            raw_text="清仓",
        )
        preview = paper_services.preview_execution(sell_signal, self.paper_id)
        self.assertEqual(preview.reject_reason, "T1_AVAILABLE_INSUFFICIENT")

        order_id = paper_services.execute_paper_signal(sell_signal, self.paper_id)
        order = next(
            row for row in paper_services.order_rows() if row["id"] == order_id
        )
        self.assertEqual(order["status"], "REJECTED")
        self.assertEqual(len(paper_services.fill_rows(self.paper_id)), 1)


class LegacyMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "legacy.sqlite3"
        legacy_schema = paper_db.CURRENT_SCHEMA.replace("paper_", "shadow_")
        with db.get_connection() as conn:
            conn.executescript(legacy_schema)
            conn.execute(
                "ALTER TABLE shadow_accounts ADD COLUMN book_type TEXT NOT NULL DEFAULT 'PAPER'"
            )
            conn.execute(
                "ALTER TABLE shadow_accounts ADD COLUMN paired_account_id INTEGER"
            )
            conn.execute(
                """
                INSERT INTO shadow_projects (id, name, market, created_at)
                VALUES (1, '旧版项目', 'A股', '2026-07-01 09:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO shadow_accounts (
                    id, project_id, name, initial_cash, cash_balance, currency,
                    is_active, created_at, book_type, paired_account_id
                ) VALUES
                    (1, 1, '系统模拟账户', 100000, 90000, 'CNY', 1,
                     '2026-07-01 09:00:00', 'PAPER', 2),
                    (2, 1, '人工实盘账户', 100000, 80000, 'CNY', 1,
                     '2026-07-01 09:00:00', 'MANUAL', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO shadow_cash_ledger (
                    id, account_id, event_type, amount, balance_after, note, occurred_at
                ) VALUES
                    (1, 1, 'INITIAL_DEPOSIT', 100000, 100000, 'PAPER', '2026-07-01'),
                    (2, 2, 'INITIAL_DEPOSIT', 100000, 100000, 'MANUAL', '2026-07-01')
                """
            )

    def tearDown(self) -> None:
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_legacy_migration_preserves_paper_and_discards_manual(self) -> None:
        paper_db.migrate()
        paper_db.migrate()
        backup_path = Path(f"{db.DB_PATH}.pre-paper-v2.bak")

        with db.get_connection() as conn:
            accounts = conn.execute(
                "SELECT id, name, cash_balance FROM paper_accounts ORDER BY id"
            ).fetchall()
            ledger = conn.execute(
                "SELECT account_id, note FROM paper_cash_ledger ORDER BY id"
            ).fetchall()
            legacy_tables = conn.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'shadow_%'
                """
            ).fetchall()
            versions = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        with sqlite3.connect(backup_path) as backup:
            backup_account_count = backup.execute(
                "SELECT COUNT(*) FROM shadow_accounts"
            ).fetchone()[0]

        self.assertEqual([dict(row) for row in accounts], [
            {"id": 1, "name": "系统模拟账户", "cash_balance": 90000.0}
        ])
        self.assertEqual([dict(row) for row in ledger], [
            {"account_id": 1, "note": "PAPER"}
        ])
        self.assertEqual(legacy_tables, [])
        self.assertEqual(
            [row["version"] for row in versions],
            [1, 2, 3, 4, 5, 6, 7, 8, 9],
        )
        self.assertEqual(backup_account_count, 2)


if __name__ == "__main__":
    unittest.main()
