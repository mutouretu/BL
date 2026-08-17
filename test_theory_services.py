from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import db
import paper_db
import paper_services
import theory_fixtures
import theory_services
import tracking_services


class TheoryServicesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "theory.sqlite3"
        paper_db.migrate()
        self.project_id, _ = paper_services.create_demo_project()
        theory_services.ensure_account(self.project_id)
        tracking_services.add_watching(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-08-03 09:30:00",
        )
        theory_services.upsert_reference_price(
            "300377.SZ", 10.0, price_time="2026-08-03 09:40:00"
        )

    def tearDown(self) -> None:
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_buy_uses_remaining_theory_cash_and_updates_position(self) -> None:
        preview = theory_services.preview_record(
            self.project_id, "300377.SZ", "BUY", 0.10
        )
        self.assertEqual(preview.quantity, 1000)
        self.assertEqual(preview.gross_amount, 10_000)
        self.assertEqual(preview.capital_ratio, 0.10)

        record_id = theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "BUY",
            0.10,
            recorded_at="2026-08-03 10:00:00",
        )
        summary = theory_services.account_summary(self.project_id)
        positions = theory_services.position_rows(self.project_id)
        history = theory_services.trade_history(self.project_id, "300377.SZ")

        self.assertGreater(record_id, 0)
        self.assertEqual(summary["cash"], 90_000)
        self.assertEqual(positions[0]["quantity"], 1000)
        self.assertEqual(history[0]["allocation_ratio"], 0.10)
        with self.assertRaisesRegex(ValueError, "仍有理论持仓"):
            tracking_services.archive_tracking(self.project_id, "300377.SZ")

    def test_manual_price_is_used_for_preview_and_record(self) -> None:
        preview = theory_services.preview_record(
            self.project_id,
            "300377.SZ",
            "BUY",
            0.10,
            reference_price=12.34,
            price_source="手工录入",
        )
        self.assertEqual(preview.reference_price, 12.34)
        self.assertEqual(preview.quantity, 800)
        self.assertEqual(preview.gross_amount, 9_872)

        theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "BUY",
            0.10,
            recorded_at="2026-08-03 10:00:00",
            reference_price=12.34,
            price_source="手工录入",
        )
        history = theory_services.trade_history(self.project_id, "300377.SZ")
        self.assertEqual(history[0]["reference_price"], 12.34)
        self.assertEqual(history[0]["price_source"], "手工录入")

    def test_sell_uses_position_ratio_and_realizes_profit(self) -> None:
        theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "BUY",
            0.10,
            recorded_at="2026-08-03 10:00:00",
        )
        record_id = theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "SELL",
            0.50,
            recorded_at="2026-08-04 10:00:00",
            reference_price=11.0,
        )
        history = theory_services.trade_history(self.project_id, "300377.SZ")
        positions = theory_services.position_rows(self.project_id)

        self.assertGreater(record_id, 0)
        self.assertEqual(history[0]["quantity"], 500)
        self.assertEqual(history[0]["realized_pnl"], 500)
        self.assertEqual(positions[0]["quantity"], 500)

    def test_zero_position_can_be_deleted_with_trade_history_preserved(self) -> None:
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
            1.00,
            recorded_at="2026-08-04 10:00:00",
            reference_price=11.0,
        )

        tracking_services.remove_tracking(self.project_id, "300377.SZ")
        self.assertEqual(
            tracking_services.list_tracking(
                self.project_id, as_of="2026-08-04 12:00:00"
            ),
            [],
        )
        self.assertEqual(
            len(theory_services.trade_history(self.project_id, "300377.SZ")),
            2,
        )

    def test_same_day_sell_is_allowed_without_t1_validation(self) -> None:
        theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "BUY",
            0.10,
            recorded_at="2026-08-03 10:00:00",
        )
        record_id = theory_services.create_record(
            self.project_id,
            "300377.SZ",
            "SELL",
            0.50,
            recorded_at="2026-08-03 14:00:00",
            reference_price=11.0,
        )
        positions = theory_services.position_rows(self.project_id)

        self.assertGreater(record_id, 0)
        self.assertEqual(positions[0]["quantity"], 500)
        self.assertEqual(positions[0]["available_quantity"], 500)

    def test_monthly_statistics_are_generated_from_records(self) -> None:
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
        result = theory_services.monthly_statistics(self.project_id, "2026-08")

        self.assertEqual(result["stock_count"], 1)
        self.assertEqual(result["buy_count"], 1)
        self.assertEqual(result["sell_count"], 1)
        self.assertEqual(result["details"][0]["买入股数"], 1000)
        self.assertEqual(result["details"][0]["卖出股数"], 500)

    def test_demo_fixture_is_idempotent(self) -> None:
        other_tmp = tempfile.TemporaryDirectory()
        try:
            db.DB_PATH = Path(other_tmp.name) / "fixture.sqlite3"
            paper_db.migrate()
            project_id, _ = paper_services.create_demo_project()
            first = theory_fixtures.seed(project_id)
            second = theory_fixtures.seed(project_id)
            self.assertEqual(first["new_record_count"], 8)
            self.assertEqual(second["new_record_count"], 0)
            all_history = theory_services.all_trade_history(project_id)
            self.assertEqual(len(all_history), 8)
            self.assertGreaterEqual(
                all_history[0]["recorded_at"], all_history[-1]["recorded_at"]
            )
            self.assertEqual(len(theory_services.available_months(project_id)), 1)
            self.assertEqual(
                theory_services.monthly_statistics(project_id, "2026-08")["stock_count"],
                4,
            )
        finally:
            other_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
