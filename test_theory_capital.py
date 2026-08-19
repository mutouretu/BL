from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import db
import paper_db
import paper_services
import theory_capital
import theory_services
import tracking_services


class TheoryCapitalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "capital.sqlite3"
        paper_db.migrate()
        self.project_id, _ = paper_services.create_demo_project()
        theory_services.ensure_account(self.project_id, initial_cash=100_000)
        tracking_services.add_watching(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-08-03 09:30:00",
        )
        theory_services.upsert_reference_price(
            "300377.SZ", 10.0, price_time="2026-08-03 09:40:00"
        )
        theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "BUY",
            0.10,
            recorded_at="2026-08-03 10:00:00",
        )
        theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "SELL",
            0.50,
            recorded_at="2026-08-04 10:00:00",
            reference_price=11.0,
        )

    def tearDown(self) -> None:
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_resize_preview_does_not_write_database(self) -> None:
        result = theory_capital.resize_theory_capital(
            self.project_id,
            10_000_000,
        )
        summary = theory_services.account_summary(self.project_id)

        self.assertFalse(result.applied)
        self.assertEqual(result.scale_factor, 100)
        self.assertEqual(summary["initial_cash"], 100_000)
        self.assertEqual(summary["cash"], 95_500)

    def test_resize_scales_existing_theory_records(self) -> None:
        result = theory_capital.resize_theory_capital(
            self.project_id,
            10_000_000,
            apply=True,
            backup=False,
        )

        summary = theory_services.account_summary(self.project_id)
        positions = theory_services.position_rows(self.project_id)
        history = theory_services.trade_history(self.project_id, "300377.SZ")
        sell_record = history[0]
        buy_record = history[1]
        with db.get_connection() as conn:
            ledger = conn.execute(
                """
                SELECT event_type, amount, balance_after
                FROM theory_cash_ledger
                WHERE account_id = ?
                ORDER BY id
                """,
                (result.account_id,),
            ).fetchall()
            lot = conn.execute(
                """
                SELECT remaining_quantity, unit_cost
                FROM theory_position_lots
                WHERE account_id = ?
                """,
                (result.account_id,),
            ).fetchone()

        self.assertTrue(result.applied)
        self.assertEqual(summary["initial_cash"], 10_000_000)
        self.assertEqual(summary["cash"], 9_550_000)
        self.assertEqual(positions[0]["quantity"], 50_000)
        self.assertEqual(positions[0]["average_cost"], 10.0)
        self.assertEqual(positions[0]["realized_pnl"], 50_000)
        self.assertEqual(buy_record["quantity"], 100_000)
        self.assertEqual(buy_record["gross_amount"], 1_000_000)
        self.assertEqual(buy_record["capital_ratio"], 0.10)
        self.assertEqual(sell_record["quantity"], 50_000)
        self.assertEqual(sell_record["gross_amount"], 550_000)
        self.assertEqual(sell_record["realized_pnl"], 50_000)
        self.assertEqual(ledger[0]["amount"], 10_000_000)
        self.assertEqual(ledger[-1]["balance_after"], 9_550_000)
        self.assertEqual(lot["remaining_quantity"], 50_000)
        self.assertEqual(lot["unit_cost"], 10.0)


if __name__ == "__main__":
    unittest.main()
