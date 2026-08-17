"""Idempotent sample data for the manual theory-record workflow."""

from __future__ import annotations

import db
import theory_services
import tracking_services


TRACKING_FIXTURES = (
    ("300377.SZ", "赢时胜", "2026-08-03 09:30:00"),
    ("300083.SZ", "创世纪", "2026-08-04 09:30:00"),
    ("300142.SZ", "沃森生物", "2026-08-05 09:30:00"),
    ("300760.SZ", "迈瑞医疗", "2026-08-06 09:30:00"),
    ("300300.SZ", "海峡创新", "2026-08-13 09:42:00"),
)


TRADE_FIXTURES = (
    {
        "key": "THEORY-DEMO-001",
        "symbol": "300377.SZ",
        "side": "BUY",
        "ratio": 0.10,
        "price": 13.90,
        "recorded_at": "2026-08-03 09:46:12",
    },
    {
        "key": "THEORY-DEMO-002",
        "symbol": "300083.SZ",
        "side": "BUY",
        "ratio": 0.10,
        "price": 13.20,
        "recorded_at": "2026-08-04 09:52:08",
    },
    {
        "key": "THEORY-DEMO-003",
        "symbol": "300377.SZ",
        "side": "BUY",
        "ratio": 0.40,
        "price": 14.10,
        "recorded_at": "2026-08-05 10:18:35",
    },
    {
        "key": "THEORY-DEMO-004",
        "symbol": "300760.SZ",
        "side": "BUY",
        "ratio": 0.50,
        "price": 225.00,
        "recorded_at": "2026-08-06 10:06:19",
    },
    {
        "key": "THEORY-DEMO-005",
        "symbol": "300142.SZ",
        "side": "BUY",
        "ratio": 0.40,
        "price": 12.50,
        "recorded_at": "2026-08-07 13:36:42",
    },
    {
        "key": "THEORY-DEMO-006",
        "symbol": "300377.SZ",
        "side": "SELL",
        "ratio": 0.50,
        "price": 14.55,
        "recorded_at": "2026-08-10 10:32:27",
    },
    {
        "key": "THEORY-DEMO-007",
        "symbol": "300083.SZ",
        "side": "SELL",
        "ratio": 1.00,
        "price": 14.05,
        "recorded_at": "2026-08-11 14:08:53",
    },
    {
        "key": "THEORY-DEMO-008",
        "symbol": "300142.SZ",
        "side": "SELL",
        "ratio": 0.50,
        "price": 12.10,
        "recorded_at": "2026-08-12 10:45:16",
    },
)


LATEST_PRICES = (
    ("300377.SZ", 14.61, "2026-08-13 15:00:00"),
    ("300083.SZ", 14.02, "2026-08-13 15:00:00"),
    ("300142.SZ", 12.04, "2026-08-13 15:00:00"),
    ("300760.SZ", 227.40, "2026-08-13 15:00:00"),
    ("300300.SZ", 4.86, "2026-08-13 15:00:00"),
)


def seed(project_id: int) -> dict:
    theory_services.ensure_account(project_id)
    for symbol, name, recommended_at in TRACKING_FIXTURES:
        with db.get_connection() as conn:
            existing = conn.execute(
                """
                SELECT 1
                FROM tracked_instruments t
                JOIN instruments i ON i.id = t.instrument_id
                WHERE t.project_id = ? AND i.symbol = ?
                  AND t.tracking_state IN ('WATCHING', 'HOLDING')
                """,
                (project_id, symbol),
            ).fetchone()
        if existing is None:
            tracking_services.add_watching(
                project_id,
                symbol,
                name,
                recommended_at,
            )

    with db.get_connection() as conn:
        before = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM theory_trade_records WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]
        )

    record_ids = []
    for item in TRADE_FIXTURES:
        record_ids.append(
            theory_services.create_record(
                project_id,
                item["symbol"],
                item["side"],
                item["ratio"],
                recorded_at=item["recorded_at"],
                reference_price=item["price"],
                price_source="演示参考价",
                operator="演示数据",
                fixture_key=item["key"],
            )
        )

    for symbol, price, price_time in LATEST_PRICES:
        theory_services.upsert_reference_price(
            symbol,
            price,
            price_time=price_time,
            source="演示收盘价",
        )

    with db.get_connection() as conn:
        after = int(
            conn.execute(
                "SELECT COUNT(*) AS count FROM theory_trade_records WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]
        )
    return {
        "tracking_count": len(TRACKING_FIXTURES),
        "record_count": len(record_ids),
        "new_record_count": after - before,
    }


def seed_if_empty(project_id: int) -> bool:
    with db.get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM theory_trade_records WHERE project_id = ? LIMIT 1",
            (project_id,),
        ).fetchone()
    if exists is not None:
        return False
    seed(project_id)
    return True
