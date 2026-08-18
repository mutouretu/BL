from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import db
import market_data
import paper_db
import paper_services
import stage1_fixtures
import tracking_services


class TrackingServicesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.original_db_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "tracking.sqlite3"
        paper_db.migrate()
        self.project_id, self.paper_id = paper_services.create_demo_project()

    def tearDown(self) -> None:
        db.DB_PATH = self.original_db_path
        self.tmp.cleanup()

    def test_stage1_schema_is_versioned(self) -> None:
        with db.get_connection() as conn:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            versions = [
                row["version"]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        self.assertTrue(
            {"instruments", "tracked_instruments", "signal_events"} <= tables
        )
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

    def test_symbol_alias_migration_normalizes_ss_to_sh(self) -> None:
        with db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO instruments (
                    symbol, name, exchange, created_at, updated_at
                ) VALUES (
                    '600619.SS', '海立股份', 'SS',
                    '2026-08-17 09:30:00', '2026-08-17 09:30:00'
                )
                """
            )
            conn.execute("DELETE FROM schema_migrations WHERE version = 8")

        paper_db.migrate()

        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT symbol, exchange FROM instruments WHERE name = '海立股份'"
            ).fetchone()

        self.assertEqual(dict(row), {"symbol": "600619.SH", "exchange": "SH"})

    def test_watching_expires_after_five_full_calendar_days(self) -> None:
        tracking_services.upsert_tracking(
            self.project_id,
            "300001.SZ",
            "特锐德",
            "WATCHING",
            "2026-07-20 09:30:00",
        )
        tracking_services.upsert_tracking(
            self.project_id,
            "300083.SZ",
            "创世纪",
            "HOLDING",
            "2026-07-01 09:30:00",
        )

        on_day_five = tracking_services.list_tracking(
            self.project_id,
            states=("WATCHING", "HOLDING"),
            as_of="2026-07-25 23:59:59",
        )
        self.assertEqual(
            {row["symbol"] for row in on_day_five},
            {"300001.SZ", "300083.SZ"},
        )

        after_day_five = tracking_services.list_tracking(
            self.project_id,
            states=("WATCHING", "HOLDING"),
            as_of="2026-07-26 00:00:00",
        )
        self.assertEqual(
            {row["symbol"] for row in after_day_five}, {"300083.SZ"}
        )
        summary = tracking_services.tracking_summary(
            self.project_id, as_of="2026-07-26 00:00:00"
        )
        self.assertEqual(summary["expired"], 1)
        self.assertEqual(summary["holding"], 1)

    def test_add_watching_normalizes_symbol_and_rejects_active_duplicate(self) -> None:
        tracking_id = tracking_services.add_watching(
            self.project_id,
            "600000.SS",
            "浦发银行",
            "2026-08-06 09:30:00",
            latest_action="BUY",
            target_position=0.1,
            reference_price=10.25,
            predicted_low=9.90,
            predicted_high=10.80,
            raw_text="页面手工新增",
        )
        rows = tracking_services.list_tracking(
            self.project_id, as_of="2026-08-06 12:00:00"
        )
        self.assertGreater(tracking_id, 0)
        self.assertEqual(rows[0]["symbol"], "600000.SH")
        self.assertEqual(rows[0]["latest_action"], "BUY")
        with db.get_connection() as conn:
            operation = conn.execute(
                """
                SELECT o.action, o.occurred_at, o.operator
                FROM tracking_operation_records o
                JOIN instruments i ON i.id = o.instrument_id
                WHERE o.project_id = ? AND i.symbol = ?
                """,
                (self.project_id, "600000.SH"),
            ).fetchone()
        self.assertEqual(
            dict(operation),
            {
                "action": "WATCH",
                "occurred_at": "2026-08-06 09:30:00",
                "operator": "手工加入",
            },
        )

        with self.assertRaisesRegex(ValueError, "已在观察中"):
            tracking_services.add_watching(
                self.project_id,
                "600000.SH",
                "浦发银行",
                "2026-08-06 10:00:00",
            )

    def test_cash_allocation_presets_are_based_on_remaining_cash(self) -> None:
        tracking_services.add_watching(
            self.project_id,
            "000001",
            "平安银行",
            "2026-08-06 09:30:00",
        )
        initial = tracking_services.portfolio_position_scenarios(self.project_id)
        self.assertEqual(initial["by_symbol"]["000001.SZ"]["current_position_pct"], 0)
        self.assertEqual(
            initial["by_symbol"]["000001.SZ"]["projected_position_pct"][0.40],
            0.40,
        )

        result = tracking_services.set_pending_buy(
            self.project_id, "000001.SZ", 0.40
        )
        row = tracking_services.list_tracking(
            self.project_id, as_of="2026-08-06 12:00:00"
        )[0]
        self.assertEqual(row["latest_action"], "BUY")
        self.assertEqual(row["target_position"], 0.40)
        self.assertEqual(row["pending_cash_ratio"], 0.40)
        self.assertEqual(row["processing_status"], "PENDING")
        self.assertEqual(result["cash_allocation_ratio"], 0.40)
        self.assertEqual(result["target_position"], 0.40)

        full_result = tracking_services.set_pending_buy(
            self.project_id, "000001.SZ", 1.00
        )
        full_row = tracking_services.list_tracking(
            self.project_id, as_of="2026-08-06 12:00:00"
        )[0]
        self.assertEqual(full_row["pending_cash_ratio"], 1.00)
        self.assertEqual(full_result["cash_allocation_ratio"], 1.00)
        self.assertEqual(full_result["target_position"], 1.00)

        with self.assertRaisesRegex(ValueError, "仅支持"):
            tracking_services.set_tracking_cash_allocation(
                self.project_id, "000001.SZ", 0.25
            )

    def test_sell_presets_are_based_on_current_symbol_holding(self) -> None:
        tracking_services.add_watching(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-08-06 09:30:00",
        )
        signal_id = paper_services.create_signal(
            project_id=self.project_id,
            trade_date="2026-08-06",
            signal_time="2026-08-06 10:00:00",
            symbol="300377.SZ",
            name="赢时胜",
            action="BUY",
            target_position=0.25,
            reference_price=10,
        )
        paper_services.execute_paper_signal(signal_id, self.paper_id)
        before = tracking_services.portfolio_position_scenarios(self.project_id)
        current = before["by_symbol"]["300377.SZ"]["current_position_pct"]

        result = tracking_services.set_pending_sell(
            self.project_id, "300377.SZ", 0.50
        )
        row = tracking_services.list_tracking(
            self.project_id, as_of="2026-08-06 12:00:00"
        )[0]
        self.assertEqual(row["latest_action"], "SELL")
        self.assertEqual(row["pending_sell_ratio"], 0.50)
        self.assertIsNone(row["pending_cash_ratio"])
        self.assertAlmostEqual(row["target_position"], current * 0.50)
        self.assertAlmostEqual(result["target_position"], current * 0.50)

        full_sell = tracking_services.set_pending_sell(
            self.project_id, "300377.SZ", 1.00
        )
        self.assertEqual(full_sell["target_position"], 0)
        with self.assertRaisesRegex(ValueError, "仅支持"):
            tracking_services.set_pending_sell(
                self.project_id, "300377.SZ", 0.25
            )

    def test_position_scenarios_include_existing_market_value(self) -> None:
        tracking_services.add_watching(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-08-06 09:30:00",
        )
        signal_id = paper_services.create_signal(
            project_id=self.project_id,
            trade_date="2026-08-06",
            signal_time="2026-08-06 10:00:00",
            symbol="300377.SZ",
            name="赢时胜",
            action="BUY",
            target_position=0.25,
            reference_price=10,
        )
        paper_services.execute_paper_signal(signal_id, self.paper_id)

        scenarios = tracking_services.portfolio_position_scenarios(self.project_id)
        item = scenarios["by_symbol"]["300377.SZ"]
        expected = (
            item["market_value"] + scenarios["cash"] * 0.40
        ) / scenarios["equity"]
        self.assertGreater(item["current_position_pct"], 0)
        self.assertAlmostEqual(item["projected_position_pct"][0.40], expected)
        self.assertGreater(
            item["projected_position_pct"][0.40], item["current_position_pct"]
        )
        tracking_services.remove_tracking(self.project_id, "300377.SZ")
        self.assertEqual(
            tracking_services.list_tracking(
                self.project_id, as_of="2026-08-06 12:00:00"
            ),
            [],
        )

    def test_tracking_operation_actions(self) -> None:
        tracking_services.add_watching(
            self.project_id,
            "000001",
            "平安银行",
            "2026-08-06 09:30:00",
        )
        tracking_services.set_pending_trade_action(
            self.project_id, "000001.SZ", "BUY"
        )
        row = tracking_services.list_tracking(
            self.project_id, as_of="2026-08-06 12:00:00"
        )[0]
        self.assertEqual(row["latest_action"], "BUY")

        with self.assertRaisesRegex(ValueError, "没有可卖持仓"):
            tracking_services.set_pending_trade_action(
                self.project_id, "000001.SZ", "SELL"
            )

        updated = tracking_services.update_tracking_instrument(
            self.project_id,
            "000001.SZ",
            "000002",
            "万科A",
        )
        self.assertEqual(updated, {"symbol": "000002.SZ", "name": "万科A"})
        quote = market_data.RealtimeQuote(
            symbol="000002.SZ",
            name="万科A",
            price=7.08,
            price_time="2026-08-06 11:20:00",
        )
        with patch(
            "tracking_services.market_data.fetch_realtime_quote",
            return_value=quote,
        ):
            refreshed = tracking_services.refresh_tracking_price(
                self.project_id, "000002.SZ"
            )
        self.assertEqual(refreshed["price"], 7.08)
        self.assertEqual(refreshed["source"], "东方财富实时行情")
        with db.get_connection() as conn:
            stored_price = conn.execute(
                """
                SELECT price, price_time, source
                FROM theory_reference_prices
                WHERE symbol = ?
                """,
                ("000002.SZ",),
            ).fetchone()
        self.assertEqual(stored_price["price"], 7.08)
        self.assertEqual(stored_price["price_time"], "2026-08-06 11:20:00")

        newer_quote = market_data.RealtimeQuote(
            symbol="000002.SZ",
            name="万科A",
            price=7.12,
            price_time="2026-08-06 11:21:00",
        )
        with patch(
            "tracking_services.market_data.fetch_realtime_quotes",
            return_value=({"000002.SZ": newer_quote}, {}),
        ):
            refreshed_all = tracking_services.refresh_all_tracking_prices(
                self.project_id
            )
        self.assertEqual(refreshed_all["updated_count"], 1)
        self.assertEqual(refreshed_all["failed_count"], 0)
        self.assertEqual(refreshed_all["updated"][0]["symbol"], "000002.SZ")
        self.assertEqual(refreshed_all["updated"][0]["price"], 7.12)

        tracking_services.remove_tracking(self.project_id, "000002.SZ")
        self.assertEqual(
            tracking_services.list_tracking(
                self.project_id, as_of="2026-08-06 12:00:00"
            ),
            [],
        )

    def test_archive_hides_tracking_and_preserves_record(self) -> None:
        tracking_services.add_watching(
            self.project_id,
            "000001",
            "平安银行",
            "2026-08-06 09:30:00",
        )
        tracking_services.archive_tracking(self.project_id, "000001.SZ")

        self.assertEqual(
            tracking_services.list_tracking(
                self.project_id, as_of="2026-08-06 12:00:00"
            ),
            [],
        )
        with db.get_connection() as conn:
            archived = conn.execute(
                """
                SELECT t.tracking_state, t.processing_status
                FROM tracked_instruments t
                JOIN instruments i ON i.id = t.instrument_id
                WHERE t.project_id = ? AND i.symbol = ?
                """,
                (self.project_id, "000001.SZ"),
            ).fetchone()
        self.assertEqual(archived["tracking_state"], "CLOSED")
        self.assertEqual(archived["processing_status"], "CONFIRMED")

    def test_legacy_paper_position_does_not_block_theory_archive(self) -> None:
        tracking_services.add_watching(
            self.project_id,
            "300142.SZ",
            "沃森生物",
            "2026-08-06 09:30:00",
        )
        signal_id = paper_services.create_signal(
            project_id=self.project_id,
            trade_date="2026-08-06",
            signal_time="2026-08-06 10:00:00",
            symbol="300142.SZ",
            name="沃森生物",
            action="BUY",
            target_position=0.10,
            reference_price=12.50,
        )
        paper_services.execute_paper_signal(signal_id, self.paper_id)

        tracking_services.archive_tracking(self.project_id, "300142.SZ")
        self.assertEqual(
            tracking_services.list_tracking(
                self.project_id, as_of="2026-08-06 12:00:00"
            ),
            [],
        )

    def test_signal_event_idempotency_prefers_external_id(self) -> None:
        values = {
            "project_id": self.project_id,
            "symbol": "300377.SZ",
            "name": "赢时胜",
            "occurred_at": "2026-07-30 09:43:06",
            "normalized_action": "BUY",
            "signal_type": "B",
            "target_position": 0.25,
            "reference_price": 13.98,
            "raw_text": "盘中出现 B 信号",
            "source_name": "test-stub",
            "raw_payload": {"signal": "B"},
        }
        first = tracking_services.record_signal_event(
            external_event_id="SIG-001", **values
        )
        repeated = tracking_services.record_signal_event(
            external_event_id="SIG-001", **values
        )
        distinct = tracking_services.record_signal_event(
            external_event_id="SIG-002", **values
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, distinct)
        events = tracking_services.list_signal_events(
            self.project_id, symbol="300377.SZ"
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(json.loads(events[0]["raw_payload_json"]), {"signal": "B"})

    def test_signal_updates_tracking_without_overwriting_event_history(self) -> None:
        tracking_services.upsert_tracking(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "WATCHING",
            "2026-07-30 09:30:00",
            latest_action="WATCH",
            target_position=0.10,
        )
        first = tracking_services.record_signal_event(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-07-30 09:43:06",
            "BUY",
            external_event_id="SIG-101",
            signal_type="B",
            target_position=0.25,
            reference_price=13.98,
            raw_text="首次 B 信号",
        )
        second = tracking_services.record_signal_event(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-07-30 10:03:25",
            "ADD",
            external_event_id="SIG-102",
            signal_type="B",
            target_position=0.375,
            reference_price=13.97,
            raw_text="再次 B 信号",
        )

        rows = tracking_services.list_tracking(
            self.project_id, as_of="2026-07-30 23:59:59"
        )
        events = tracking_services.list_signal_events(
            self.project_id, symbol="300377.SZ"
        )
        self.assertNotEqual(first, second)
        self.assertEqual(len(events), 2)
        self.assertEqual(rows[0]["latest_action"], "ADD")
        self.assertEqual(rows[0]["target_position"], 0.375)

    def test_older_backfilled_event_does_not_replace_latest_tracking_signal(self) -> None:
        tracking_services.record_signal_event(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-07-30 10:03:25",
            "ADD",
            external_event_id="SIG-LATEST",
            target_position=0.375,
            reference_price=13.97,
            raw_text="最新信号",
        )
        tracking_services.record_signal_event(
            self.project_id,
            "300377.SZ",
            "赢时胜",
            "2026-07-30 09:43:06",
            "BUY",
            external_event_id="SIG-BACKFILL",
            target_position=0.25,
            reference_price=13.98,
            raw_text="补录的较早信号",
        )

        tracking = tracking_services.list_tracking(
            self.project_id, as_of="2026-07-30 23:59:59"
        )[0]
        events = tracking_services.list_signal_events(
            self.project_id, symbol="300377.SZ"
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(tracking["latest_action"], "ADD")
        self.assertEqual(tracking["target_position"], 0.375)
        self.assertEqual(tracking["latest_signal_at"], "2026-07-30 10:03:25")

    def test_fixed_stage1_fixtures_are_idempotent(self) -> None:
        first = stage1_fixtures.seed(self.project_id)
        second = stage1_fixtures.seed(self.project_id)
        summary = tracking_services.tracking_summary(
            self.project_id, as_of="2026-07-30 23:59:59"
        )
        events = tracking_services.list_signal_events(self.project_id)

        self.assertEqual(first["tracking_count"], 6)
        self.assertEqual(first["signal_count"], 7)
        self.assertEqual(second["signal_count"], 7)
        self.assertEqual(len(events), 7)
        self.assertEqual(summary["watching"], 3)
        self.assertEqual(summary["holding"], 2)
        self.assertEqual(summary["expired"], 1)

    def test_trade_history_fixtures_are_idempotent(self) -> None:
        first = stage1_fixtures.seed_trade_history(self.project_id, self.paper_id)
        second = stage1_fixtures.seed_trade_history(self.project_id, self.paper_id)
        fills = paper_services.fill_rows(self.paper_id)
        instruments = paper_services.trade_history_instruments(self.project_id)

        self.assertEqual(first["instrument_count"], 4)
        self.assertEqual(first["trade_count"], 8)
        self.assertEqual(first["new_trade_count"], 8)
        self.assertEqual(second["new_trade_count"], 0)
        self.assertEqual(len(fills), 8)
        self.assertEqual(len(instruments), 4)
        self.assertEqual(
            len(paper_services.trade_history(self.project_id, "300377.SZ")), 3
        )
        history = paper_services.trade_history(self.project_id, "300377.SZ")
        self.assertEqual(history[0]["allocation_ratio"], 0.50)
        self.assertEqual(history[0]["allocation_basis"], "STOCK_POSITION")
        self.assertGreater(history[0]["capital_ratio"], 0)


if __name__ == "__main__":
    unittest.main()
