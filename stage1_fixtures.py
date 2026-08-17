"""Fixed development fixtures for stage 1.

These rows are test stubs for the internal service boundary. They are not an
external protocol and do not generate data over time.
"""

from __future__ import annotations

import tracking_services
import paper_services


TRACKING_FIXTURES = (
    {
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "tracking_state": "WATCHING",
        "recommended_at": "2026-07-30 09:43:00",
        "source_recommendation_id": "REC-STUB-001",
        "latest_action": "BUY",
        "latest_signal_at": "2026-07-30 10:03:25",
        "target_position": 0.375,
        "reference_price": 13.97,
        "predicted_low": 13.72,
        "predicted_high": 14.20,
        "peak_hint": "未出现",
        "processing_status": "SIGNALLED",
        "raw_text": "盘中第三次出现 B 信号，建议目标仓位 37.5%",
    },
    {
        "symbol": "300300.SZ",
        "name": "海峡创新",
        "tracking_state": "WATCHING",
        "recommended_at": "2026-07-30 09:57:00",
        "source_recommendation_id": "REC-STUB-002",
        "latest_action": "WATCH",
        "latest_signal_at": "2026-07-30 09:57:10",
        "target_position": 0.125,
        "reference_price": 4.86,
        "predicted_low": 4.72,
        "predicted_high": 5.08,
        "peak_hint": "未出现",
        "processing_status": "CONFIRMED",
        "raw_text": "信号出现但强度一般，等待二次确认",
    },
    {
        "symbol": "300760.SZ",
        "name": "迈瑞医疗",
        "tracking_state": "WATCHING",
        "recommended_at": "2026-07-29 09:38:00",
        "source_recommendation_id": "REC-STUB-003",
        "latest_action": "BUY",
        "latest_signal_at": "2026-07-29 09:38:15",
        "target_position": 0.09,
        "reference_price": 228.60,
        "predicted_low": 224.20,
        "predicted_high": 235.00,
        "peak_hint": "已出现",
        "processing_status": "IGNORED",
        "raw_text": "新仓两成，对应账户目标仓位 9%",
    },
    {
        "symbol": "300083.SZ",
        "name": "创世纪",
        "tracking_state": "HOLDING",
        "recommended_at": "2026-07-22 10:11:00",
        "source_recommendation_id": "REC-STUB-004",
        "latest_action": "REDUCE",
        "latest_signal_at": "2026-07-30 10:11:03",
        "target_position": 0.25,
        "reference_price": 13.66,
        "predicted_low": 13.20,
        "predicted_high": 14.66,
        "peak_hint": "已出现",
        "processing_status": "SIGNALLED",
        "raw_text": "出现红色信号且未突破，建议减半仓",
    },
    {
        "symbol": "300142.SZ",
        "name": "沃森生物",
        "tracking_state": "HOLDING",
        "recommended_at": "2026-07-22 10:18:00",
        "source_recommendation_id": "REC-STUB-005",
        "latest_action": "ADD",
        "latest_signal_at": "2026-07-30 10:18:51",
        "target_position": 0.25,
        "reference_price": 12.44,
        "predicted_low": 12.18,
        "predicted_high": 12.92,
        "peak_hint": "未出现",
        "processing_status": "SIGNALLED",
        "raw_text": "已有 12.5% 仓位，建议加至 25%",
    },
    {
        "symbol": "300001.SZ",
        "name": "特锐德",
        "tracking_state": "WATCHING",
        "recommended_at": "2026-07-20 09:30:00",
        "source_recommendation_id": "REC-STUB-EXPIRED",
        "latest_action": "WATCH",
        "latest_signal_at": "2026-07-20 09:30:10",
        "target_position": 0.10,
        "reference_price": 24.30,
        "predicted_low": 23.80,
        "predicted_high": 25.10,
        "peak_hint": "未出现",
        "processing_status": "CONFIRMED",
        "raw_text": "用于验证观察超过五天自动过期",
    },
)


SIGNAL_FIXTURES = (
    {
        "external_event_id": "SIG-STUB-001",
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "occurred_at": "2026-07-30 09:43:06",
        "received_at": "2026-07-30 09:43:07",
        "signal_type": "B",
        "raw_action": "买入",
        "normalized_action": "BUY",
        "target_position": 0.25,
        "reference_price": 13.98,
        "predicted_low": 13.72,
        "predicted_high": 14.20,
        "raw_text": "盘中出现 B 信号",
        "processing_status": "ORDER_CREATED",
        "processing_reason": "固定桩：已生成模拟订单",
    },
    {
        "external_event_id": "SIG-STUB-002",
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "occurred_at": "2026-07-30 09:47:18",
        "received_at": "2026-07-30 09:47:19",
        "signal_type": "B",
        "raw_action": "买入",
        "normalized_action": "BUY",
        "target_position": 0.25,
        "reference_price": 13.96,
        "raw_text": "B 信号再次确认",
        "processing_status": "DUPLICATE_RECORDED",
        "processing_reason": "固定桩：重复信号已留痕",
    },
    {
        "external_event_id": "SIG-STUB-003",
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "occurred_at": "2026-07-30 09:51:42",
        "received_at": "2026-07-30 09:51:43",
        "signal_type": "①④",
        "raw_action": "观察",
        "normalized_action": "WATCH",
        "target_position": 0.25,
        "reference_price": 13.99,
        "raw_text": "信号①④，维持目标仓位",
        "processing_status": "RECORDED",
        "processing_reason": "固定桩：仅记录",
    },
    {
        "external_event_id": "SIG-STUB-004",
        "symbol": "300300.SZ",
        "name": "海峡创新",
        "occurred_at": "2026-07-30 09:57:10",
        "received_at": "2026-07-30 09:57:11",
        "signal_type": "①④",
        "raw_action": "观察",
        "normalized_action": "WATCH",
        "target_position": 0.125,
        "reference_price": 4.86,
        "raw_text": "信号出现但强度一般",
        "processing_status": "RECORDED",
        "processing_reason": "固定桩：仅记录",
    },
    {
        "external_event_id": "SIG-STUB-005",
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "occurred_at": "2026-07-30 10:03:25",
        "received_at": "2026-07-30 10:03:26",
        "signal_type": "B",
        "raw_action": "加仓",
        "normalized_action": "ADD",
        "target_position": 0.375,
        "reference_price": 13.97,
        "raw_text": "盘中第三次出现 B 信号",
        "processing_status": "PENDING_RULE",
        "processing_reason": "固定桩：待规则判断",
    },
    {
        "external_event_id": "SIG-STUB-006",
        "symbol": "300083.SZ",
        "name": "创世纪",
        "occurred_at": "2026-07-30 10:11:03",
        "received_at": "2026-07-30 10:11:04",
        "signal_type": "红色信号",
        "raw_action": "减仓",
        "normalized_action": "REDUCE",
        "target_position": 0.25,
        "reference_price": 13.66,
        "raw_text": "出现红色信号且未突破，减半仓",
        "processing_status": "ORDER_CREATED",
        "processing_reason": "固定桩：已生成模拟订单",
    },
    {
        "external_event_id": "SIG-STUB-007",
        "symbol": "300142.SZ",
        "name": "沃森生物",
        "occurred_at": "2026-07-30 10:18:51",
        "received_at": "2026-07-30 10:18:52",
        "signal_type": "B",
        "raw_action": "加仓",
        "normalized_action": "ADD",
        "target_position": 0.25,
        "reference_price": 12.44,
        "raw_text": "已有12.5%仓位，建议加至25%",
        "processing_status": "ORDER_CREATED",
        "processing_reason": "固定桩：已生成模拟订单",
    },
)


TRADE_HISTORY_FIXTURES = (
    {
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "trade_date": "2026-08-03",
        "signal_time": "2026-08-03 09:46:12",
        "action": "BUY",
        "target_position": 0.18,
        "reference_price": 13.90,
        "high": 14.08,
        "low": 13.72,
        "close": 13.96,
        "raw_text": "交易历史样例：首次买入至18%",
        "allocation_ratio": 0.10,
        "allocation_basis": "CASH_POOL",
    },
    {
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "trade_date": "2026-08-05",
        "signal_time": "2026-08-05 10:18:35",
        "action": "ADD",
        "target_position": 0.30,
        "reference_price": 14.10,
        "high": 14.35,
        "low": 13.98,
        "close": 14.28,
        "raw_text": "交易历史样例：确认信号后加仓至30%",
        "allocation_ratio": 0.40,
        "allocation_basis": "CASH_POOL",
    },
    {
        "symbol": "300083.SZ",
        "name": "创世纪",
        "trade_date": "2026-08-04",
        "signal_time": "2026-08-04 09:52:08",
        "action": "BUY",
        "target_position": 0.12,
        "reference_price": 13.20,
        "high": 13.48,
        "low": 13.08,
        "close": 13.36,
        "raw_text": "交易历史样例：首次买入至12%",
        "allocation_ratio": 0.10,
        "allocation_basis": "CASH_POOL",
    },
    {
        "symbol": "300142.SZ",
        "name": "沃森生物",
        "trade_date": "2026-08-05",
        "signal_time": "2026-08-05 13:36:42",
        "action": "BUY",
        "target_position": 0.12,
        "reference_price": 12.50,
        "high": 12.68,
        "low": 12.31,
        "close": 12.46,
        "raw_text": "交易历史样例：首次买入至12%",
        "allocation_ratio": 0.50,
        "allocation_basis": "CASH_POOL",
    },
    {
        "symbol": "300760.SZ",
        "name": "迈瑞医疗",
        "trade_date": "2026-08-06",
        "signal_time": "2026-08-06 10:06:19",
        "action": "BUY",
        "target_position": 0.25,
        "reference_price": 225.00,
        "high": 228.60,
        "low": 223.80,
        "close": 227.40,
        "raw_text": "交易历史样例：首次买入至25%",
        "allocation_ratio": 0.50,
        "allocation_basis": "CASH_POOL",
    },
    {
        "symbol": "300377.SZ",
        "name": "赢时胜",
        "trade_date": "2026-08-10",
        "signal_time": "2026-08-10 10:32:27",
        "action": "REDUCE",
        "target_position": 0.15,
        "reference_price": 14.55,
        "high": 14.82,
        "low": 14.36,
        "close": 14.61,
        "raw_text": "交易历史样例：冲高后减仓至15%",
        "allocation_ratio": 0.50,
        "allocation_basis": "STOCK_POSITION",
    },
    {
        "symbol": "300083.SZ",
        "name": "创世纪",
        "trade_date": "2026-08-11",
        "signal_time": "2026-08-11 14:08:53",
        "action": "SELL",
        "target_position": 0.0,
        "reference_price": 14.05,
        "high": 14.22,
        "low": 13.84,
        "close": 14.02,
        "raw_text": "交易历史样例：止盈清仓",
        "allocation_ratio": 1.00,
        "allocation_basis": "STOCK_POSITION",
    },
    {
        "symbol": "300142.SZ",
        "name": "沃森生物",
        "trade_date": "2026-08-12",
        "signal_time": "2026-08-12 10:45:16",
        "action": "REDUCE",
        "target_position": 0.06,
        "reference_price": 12.10,
        "high": 12.26,
        "low": 11.92,
        "close": 12.04,
        "raw_text": "交易历史样例：回撤后减仓至6%",
        "allocation_ratio": 0.50,
        "allocation_basis": "STOCK_POSITION",
    },
)


def seed(project_id: int) -> dict:
    tracking_ids = [
        tracking_services.upsert_tracking(project_id=project_id, **item)
        for item in TRACKING_FIXTURES
    ]
    signal_ids = [
        tracking_services.record_signal_event(
            project_id=project_id,
            source_name="test-stub",
            raw_payload={"fixture": item["external_event_id"]},
            **item,
        )
        for item in SIGNAL_FIXTURES
    ]
    expired = tracking_services.expire_watching(
        project_id, as_of="2026-07-30 23:59:59"
    )
    return {
        "tracking_count": len(set(tracking_ids)),
        "signal_count": len(set(signal_ids)),
        "newly_expired": expired,
    }


def seed_trade_history(project_id: int, account_id: int) -> dict:
    """Load an idempotent set of completed simulated trades for UI review."""
    before = len(paper_services.fill_rows(account_id))
    symbols: set[str] = set()
    for item in TRADE_HISTORY_FIXTURES:
        symbols.add(item["symbol"])
        tracking_services.upsert_tracking(
            project_id=project_id,
            symbol=item["symbol"],
            name=item["name"],
            tracking_state="HOLDING",
            recommended_at=f"{item['trade_date']} 09:30:00",
            source_recommendation_id=f"TRADE-DEMO-{item['symbol']}",
            latest_action=item["action"],
            latest_signal_at=item["signal_time"],
            target_position=item["target_position"],
            reference_price=item["reference_price"],
            processing_status="SIGNALLED",
            raw_text="操作历史页面模拟数据",
        )
        paper_services.upsert_market_daily(
            item["trade_date"],
            item["symbol"],
            item["high"],
            item["low"],
            item["close"],
        )
        signal_id = paper_services.create_signal(
            project_id=project_id,
            trade_date=item["trade_date"],
            signal_time=item["signal_time"],
            symbol=item["symbol"],
            name=item["name"],
            action=item["action"],
            target_position=item["target_position"],
            reference_price=item["reference_price"],
            raw_text=item["raw_text"],
            signal_type="TRADE_HISTORY_DEMO",
            allocation_ratio=item["allocation_ratio"],
            allocation_basis=item["allocation_basis"],
        )
        paper_services.set_signal_allocation(
            signal_id, item["allocation_ratio"], item["allocation_basis"]
        )
        order_id = paper_services.execute_paper_signal(signal_id, account_id)
        order = next(
            row
            for row in paper_services.order_rows(project_id)
            if int(row["id"]) == order_id
        )
        if order["status"] != "FILLED":
            raise ValueError(
                f"模拟成交生成失败：{item['symbol']} {order['reject_reason']}"
            )
    after = len(paper_services.fill_rows(account_id))
    return {
        "instrument_count": len(symbols),
        "trade_count": len(TRADE_HISTORY_FIXTURES),
        "new_trade_count": after - before,
    }
