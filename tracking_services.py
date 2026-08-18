from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any

import db
import market_data
import paper_db


TRACKING_STATES = {"WATCHING", "HOLDING", "CLOSED", "EXPIRED"}
SIGNAL_ACTIONS = {"BUY", "ADD", "WATCH", "REDUCE", "SELL"}
TRACKING_STATUSES = {"PENDING", "CONFIRMED", "IGNORED", "SIGNALLED"}
SIGNAL_STATUSES = {
    "RECORDED",
    "PENDING_RULE",
    "ORDER_CREATED",
    "DUPLICATE_RECORDED",
    "IGNORED",
    "REJECTED",
}


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    try:
        return datetime.fromisoformat(str(value).replace("T", " ")).replace(
            microsecond=0
        )
    except ValueError as exc:
        raise ValueError(f"无法识别的日期时间：{value}") from exc


def _iso(value: str | datetime) -> str:
    return _parse_datetime(value).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("股票代码不能为空。")
    if normalized.isdigit() and len(normalized) == 6:
        if normalized.startswith(("4", "8")):
            return f"{normalized}.BJ"
        if normalized.startswith(("5", "6")):
            return f"{normalized}.SH"
        return f"{normalized}.SZ"
    if "." in normalized:
        code, exchange = normalized.rsplit(".", 1)
        if exchange == "SS":
            return f"{code}.SH"
    return normalized


def _exchange(symbol: str) -> str:
    if "." in symbol:
        exchange = symbol.rsplit(".", 1)[1]
        return "SH" if exchange == "SS" else exchange
    if symbol.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _validate_position(value: float | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if not 0 <= normalized <= 1:
        raise ValueError("目标仓位必须在 0% 到 100% 之间。")
    return normalized


def _validate_price(value: float | None, label: str) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if normalized <= 0:
        raise ValueError(f"{label}必须大于 0。")
    return normalized


def _upsert_instrument(
    conn, symbol: str, name: str, occurred_at: str
) -> int:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("股票名称不能为空。")
    existing = conn.execute(
        "SELECT id FROM instruments WHERE symbol = ?", (normalized_symbol,)
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE instruments
            SET name = ?, exchange = ?, is_active = 1, updated_at = ?
            WHERE id = ?
            """,
            (
                normalized_name,
                _exchange(normalized_symbol),
                occurred_at,
                existing["id"],
            ),
        )
        return int(existing["id"])
    cursor = conn.execute(
        """
        INSERT INTO instruments (
            symbol, name, exchange, lot_size, t_plus_days,
            is_active, created_at, updated_at
        ) VALUES (?, ?, ?, 100, 1, 1, ?, ?)
        """,
        (
            normalized_symbol,
            normalized_name,
            _exchange(normalized_symbol),
            occurred_at,
            occurred_at,
        ),
    )
    return int(cursor.lastrowid)


def upsert_tracking(
    project_id: int,
    symbol: str,
    name: str,
    tracking_state: str,
    recommended_at: str | datetime,
    *,
    source_recommendation_id: str | None = None,
    latest_action: str | None = None,
    latest_signal_at: str | datetime | None = None,
    target_position: float | None = None,
    reference_price: float | None = None,
    predicted_low: float | None = None,
    predicted_high: float | None = None,
    peak_hint: str = "",
    processing_status: str = "PENDING",
    raw_text: str = "",
    watch_days: int = 5,
) -> int:
    paper_db.migrate()
    state = tracking_state.strip().upper()
    if state not in TRACKING_STATES:
        raise ValueError("不支持的跟踪状态。")
    status = processing_status.strip().upper()
    if status not in TRACKING_STATUSES:
        raise ValueError("不支持的处理状态。")
    if watch_days < 0:
        raise ValueError("观察天数不能小于 0。")
    recommended = _parse_datetime(recommended_at)
    recommended_text = _iso(recommended)
    expires_at = None
    if state == "WATCHING":
        expires_at = _iso(recommended + timedelta(days=watch_days))
    action = latest_action.strip().upper() if latest_action else None
    if action is not None and action not in SIGNAL_ACTIONS:
        raise ValueError("不支持的操作建议。")

    with db.get_connection() as conn:
        instrument_id = _upsert_instrument(
            conn, symbol, name, recommended_text
        )
        existing = conn.execute(
            """
            SELECT id, tracking_state FROM tracked_instruments
            WHERE project_id = ? AND instrument_id = ?
            """,
            (project_id, instrument_id),
        ).fetchone()
        changed_at = now_iso()
        values = (
            state,
            recommended_text,
            expires_at,
            source_recommendation_id,
            action,
            _iso(latest_signal_at) if latest_signal_at else None,
            _validate_position(target_position),
            _validate_price(reference_price, "参考价"),
            _validate_price(predicted_low, "预测最低"),
            _validate_price(predicted_high, "预测最高"),
            peak_hint.strip(),
            status,
            raw_text.strip(),
            changed_at,
        )
        should_record_watch = state == "WATCHING" and (
            existing is None
            or existing["tracking_state"] not in {"WATCHING", "HOLDING"}
        )
        if existing is not None:
            conn.execute(
                """
                UPDATE tracked_instruments SET
                    tracking_state = ?, recommended_at = ?, watch_expires_at = ?,
                    source_recommendation_id = ?, latest_action = ?,
                    latest_signal_at = ?, target_position = ?, reference_price = ?,
                    predicted_low = ?, predicted_high = ?, peak_hint = ?,
                    processing_status = ?, raw_text = ?, updated_at = ?
                WHERE id = ?
                """,
                values + (existing["id"],),
            )
            tracking_id = int(existing["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO tracked_instruments (
                    project_id, instrument_id, tracking_state, recommended_at,
                    watch_expires_at, source_recommendation_id, latest_action,
                    latest_signal_at, target_position, reference_price,
                    predicted_low, predicted_high, peak_hint, processing_status,
                    raw_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, instrument_id)
                + values[:-1]
                + (values[-1], values[-1]),
            )
            tracking_id = int(cursor.lastrowid)
        if should_record_watch:
            source_part = source_recommendation_id or (
                f"TRACKING-{tracking_id}-{recommended_text}"
            )
            operator = (
                "手工加入"
                if source_recommendation_id
                and source_recommendation_id.startswith("UI-")
                else "系统记录"
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO tracking_operation_records (
                    project_id, instrument_id, action, occurred_at,
                    operator, source_key, created_at
                ) VALUES (?, ?, 'WATCH', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    instrument_id,
                    recommended_text,
                    operator,
                    f"{project_id}:{source_part}",
                    changed_at,
                ),
            )
        return tracking_id


def add_watching(
    project_id: int,
    symbol: str,
    name: str,
    recommended_at: str | datetime,
    *,
    latest_action: str = "WATCH",
    target_position: float | None = None,
    reference_price: float | None = None,
    predicted_low: float | None = None,
    predicted_high: float | None = None,
    peak_hint: str = "未出现",
    raw_text: str = "",
) -> int:
    """Add a user-entered observation without demoting an active holding."""
    paper_db.migrate()
    normalized_symbol = _normalize_symbol(symbol)
    existing = paper_db.row(
        """
        SELECT t.tracking_state
        FROM tracked_instruments t
        JOIN instruments i ON i.id = t.instrument_id
        WHERE t.project_id = ? AND i.symbol = ?
        """,
        (project_id, normalized_symbol),
    )
    if existing is not None and existing["tracking_state"] in {"WATCHING", "HOLDING"}:
        state_text = "观察中" if existing["tracking_state"] == "WATCHING" else "持仓中"
        raise ValueError(f"{normalized_symbol} 已在{state_text}列表中。")
    if (
        predicted_low is not None
        and predicted_high is not None
        and float(predicted_low) > float(predicted_high)
    ):
        raise ValueError("预测最低不能高于预测最高。")
    return upsert_tracking(
        project_id=project_id,
        symbol=normalized_symbol,
        name=name,
        tracking_state="WATCHING",
        recommended_at=recommended_at,
        source_recommendation_id=f"UI-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        latest_action=latest_action,
        target_position=target_position,
        reference_price=reference_price,
        predicted_low=predicted_low,
        predicted_high=predicted_high,
        peak_hint=peak_hint,
        processing_status="PENDING",
        raw_text=raw_text,
    )


def expire_watching(
    project_id: int, as_of: str | datetime | date | None = None
) -> int:
    paper_db.migrate()
    if as_of is None:
        as_of_text = now_iso()
    elif isinstance(as_of, date) and not isinstance(as_of, datetime):
        as_of_text = f"{as_of.isoformat()} 00:00:00"
    else:
        as_of_text = _iso(as_of)
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE tracked_instruments
            SET tracking_state = 'EXPIRED', updated_at = ?
            WHERE project_id = ?
              AND tracking_state = 'WATCHING'
              AND watch_expires_at IS NOT NULL
              AND date(watch_expires_at) < date(?)
            """,
            (now_iso(), project_id, as_of_text),
        )
        return int(cursor.rowcount)


def set_tracking_state(
    project_id: int, symbol: str, tracking_state: str
) -> None:
    state = tracking_state.strip().upper()
    if state not in TRACKING_STATES:
        raise ValueError("不支持的跟踪状态。")
    normalized_symbol = _normalize_symbol(symbol)
    with db.get_connection() as conn:
        result = conn.execute(
            """
            UPDATE tracked_instruments
            SET tracking_state = ?,
                watch_expires_at = CASE WHEN ? = 'WATCHING'
                    THEN datetime('now', 'localtime', '+5 days')
                    ELSE NULL END,
                updated_at = ?
            WHERE project_id = ?
              AND instrument_id = (
                  SELECT id FROM instruments WHERE symbol = ?
              )
            """,
            (state, state, now_iso(), project_id, normalized_symbol),
        )
        if result.rowcount == 0:
            raise ValueError("未找到对应的跟踪股票。")


def portfolio_position_scenarios(project_id: int) -> dict:
    """Calculate current and post-allocation position ratios from account cash."""
    paper_db.migrate()
    with db.get_connection() as conn:
        account = conn.execute(
            """
            SELECT id, cash_balance FROM paper_accounts
            WHERE project_id = ? AND is_active = 1
            ORDER BY id LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if account is None:
            raise ValueError("模拟账户不存在。")
        cash = float(account["cash_balance"])
        positions = conn.execute(
            """
            SELECT
                p.symbol,
                p.quantity,
                COALESCE(
                    (
                        SELECT m.close FROM paper_market_daily m
                        WHERE m.symbol = p.symbol AND m.close IS NOT NULL
                        ORDER BY m.trade_date DESC, m.id DESC LIMIT 1
                    ),
                    (
                        SELECT f.price FROM paper_fills f
                        WHERE f.symbol = p.symbol
                        ORDER BY f.fill_time DESC, f.id DESC LIMIT 1
                    ),
                    CASE WHEN p.quantity > 0 THEN p.cost_total / p.quantity ELSE 0 END
                ) AS mark_price
            FROM paper_positions p
            WHERE p.account_id = ? AND p.quantity > 0
            """,
            (account["id"],),
        ).fetchall()
    market_values = {
        row["symbol"]: float(row["quantity"]) * float(row["mark_price"] or 0)
        for row in positions
    }
    equity = cash + sum(market_values.values())
    rates = (0.10, 0.40, 0.50)
    by_symbol = {}
    symbols = {
        row["symbol"]
        for row in paper_db.rows(
            """
            SELECT i.symbol
            FROM tracked_instruments t
            JOIN instruments i ON i.id = t.instrument_id
            WHERE t.project_id = ? AND t.tracking_state IN ('WATCHING', 'HOLDING')
            """,
            (project_id,),
        )
    } | set(market_values)
    for symbol in symbols:
        current_value = market_values.get(symbol, 0.0)
        by_symbol[symbol] = {
            "market_value": current_value,
            "current_position_pct": current_value / equity if equity > 0 else 0.0,
            "projected_position_pct": {
                rate: (current_value + cash * rate) / equity if equity > 0 else 0.0
                for rate in rates
            },
        }
    return {"cash": cash, "equity": equity, "by_symbol": by_symbol}


def set_tracking_cash_allocation(
    project_id: int, symbol: str, cash_allocation_ratio: float
) -> dict:
    """Set a pending buy action as a percentage of the remaining account cash."""
    normalized_symbol = _normalize_symbol(symbol)
    allocation = _validate_position(cash_allocation_ratio)
    if allocation not in {0.10, 0.40, 0.50}:
        raise ValueError("买入比例仅支持剩余资金的 10%、40% 或 50%。")
    scenarios = portfolio_position_scenarios(project_id)
    if scenarios["cash"] <= 0:
        raise ValueError("模拟账户没有可用现金。")
    symbol_scenarios = scenarios["by_symbol"].get(normalized_symbol)
    if symbol_scenarios is None:
        raise ValueError("未找到对应的当前跟踪股票。")
    target = symbol_scenarios["projected_position_pct"][allocation]
    with db.get_connection() as conn:
        result = conn.execute(
            """
            UPDATE tracked_instruments
            SET latest_action = 'BUY', pending_cash_ratio = ?,
                pending_sell_ratio = NULL, target_position = ?,
                processing_status = 'PENDING', updated_at = ?
            WHERE project_id = ?
              AND tracking_state IN ('WATCHING', 'HOLDING')
              AND instrument_id = (
                  SELECT id FROM instruments WHERE symbol = ?
              )
            """,
            (allocation, target, now_iso(), project_id, normalized_symbol),
        )
        if result.rowcount == 0:
            raise ValueError("未找到对应的当前跟踪股票。")
    return {
        "symbol": normalized_symbol,
        "cash_allocation_ratio": allocation,
        "cash_available": scenarios["cash"],
        "account_equity": scenarios["equity"],
        "target_position": target,
    }


def set_pending_buy(
    project_id: int, symbol: str, cash_allocation_ratio: float
) -> dict:
    """Record a pending buy sized from the remaining simulated cash."""
    return set_tracking_cash_allocation(project_id, symbol, cash_allocation_ratio)


def set_pending_sell(
    project_id: int, symbol: str, position_sell_ratio: float
) -> dict:
    """Record a pending sell sized from the symbol's current simulated holding."""
    normalized_symbol = _normalize_symbol(symbol)
    sell_ratio = _validate_position(position_sell_ratio)
    if sell_ratio not in {0.50, 1.00}:
        raise ValueError("卖出比例仅支持当前持仓的 50% 或 100%。")
    portfolio = portfolio_position_scenarios(project_id)
    symbol_position = portfolio["by_symbol"].get(normalized_symbol)
    if symbol_position is None:
        raise ValueError("未找到对应的当前跟踪股票。")
    market_value = symbol_position["market_value"]
    if market_value <= 0:
        raise ValueError("该股票当前没有可卖持仓。")
    target = symbol_position["current_position_pct"] * (1 - sell_ratio)
    with db.get_connection() as conn:
        result = conn.execute(
            """
            UPDATE tracked_instruments
            SET latest_action = 'SELL', pending_cash_ratio = NULL,
                pending_sell_ratio = ?, target_position = ?,
                processing_status = 'PENDING', updated_at = ?
            WHERE project_id = ?
              AND tracking_state IN ('WATCHING', 'HOLDING')
              AND instrument_id = (
                  SELECT id FROM instruments WHERE symbol = ?
              )
            """,
            (sell_ratio, target, now_iso(), project_id, normalized_symbol),
        )
        if result.rowcount == 0:
            raise ValueError("未找到对应的当前跟踪股票。")
    return {
        "symbol": normalized_symbol,
        "position_sell_ratio": sell_ratio,
        "market_value": market_value,
        "account_equity": portfolio["equity"],
        "target_position": target,
    }


def set_pending_trade_action(project_id: int, symbol: str, action: str) -> None:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_action = action.strip().upper()
    if normalized_action not in {"BUY", "SELL"}:
        raise ValueError("操作只能是买入或卖出。")
    portfolio = portfolio_position_scenarios(project_id)
    symbol_position = portfolio["by_symbol"].get(normalized_symbol)
    if symbol_position is None:
        raise ValueError("未找到对应的当前跟踪股票。")
    if normalized_action == "BUY" and portfolio["cash"] <= 0:
        raise ValueError("模拟账户没有可用现金。")
    if normalized_action == "SELL" and symbol_position["market_value"] <= 0:
        raise ValueError("该股票当前没有可卖持仓。")
    with db.get_connection() as conn:
        result = conn.execute(
            """
            UPDATE tracked_instruments
            SET latest_action = ?, pending_cash_ratio = NULL,
                pending_sell_ratio = NULL,
                target_position = CASE WHEN ? = 'SELL' THEN 0 ELSE NULL END,
                processing_status = 'PENDING', updated_at = ?
            WHERE project_id = ?
              AND tracking_state IN ('WATCHING', 'HOLDING')
              AND instrument_id = (
                  SELECT id FROM instruments WHERE symbol = ?
              )
            """,
            (
                normalized_action,
                normalized_action,
                now_iso(),
                project_id,
                normalized_symbol,
            ),
        )
        if result.rowcount == 0:
            raise ValueError("未找到对应的当前跟踪股票。")


def update_tracking_instrument(
    project_id: int,
    current_symbol: str,
    new_symbol: str,
    new_name: str,
) -> dict:
    current = _normalize_symbol(current_symbol)
    updated_symbol = _normalize_symbol(new_symbol)
    updated_name = new_name.strip()
    if not updated_name:
        raise ValueError("股票名称不能为空。")
    with db.get_connection() as conn:
        tracked = conn.execute(
            """
            SELECT t.id AS tracking_id, i.id AS instrument_id
            FROM tracked_instruments t
            JOIN instruments i ON i.id = t.instrument_id
            WHERE t.project_id = ? AND i.symbol = ?
              AND t.tracking_state IN ('WATCHING', 'HOLDING')
            """,
            (project_id, current),
        ).fetchone()
        if tracked is None:
            raise ValueError("未找到对应的当前跟踪股票。")
        duplicate = conn.execute(
            "SELECT id FROM instruments WHERE symbol = ? AND id != ?",
            (updated_symbol, tracked["instrument_id"]),
        ).fetchone()
        if duplicate is not None:
            raise ValueError(f"{updated_symbol} 已存在，不能重复使用。")
        if updated_symbol != current:
            traded = conn.execute(
                """
                SELECT 1
                FROM theory_trade_records r
                WHERE r.project_id = ? AND r.symbol = ?
                LIMIT 1
                """,
                (project_id, current),
            ).fetchone()
            if traded is not None:
                raise ValueError("已有交易记录的股票不能修改代码，只能修改名称。")
        conn.execute(
            """
            UPDATE instruments
            SET symbol = ?, name = ?, exchange = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated_symbol,
                updated_name,
                _exchange(updated_symbol),
                now_iso(),
                tracked["instrument_id"],
            ),
        )
    return {"symbol": updated_symbol, "name": updated_name}


def remove_tracking(project_id: int, symbol: str) -> None:
    normalized_symbol = _normalize_symbol(symbol)
    with db.get_connection() as conn:
        position = conn.execute(
            """
            SELECT p.quantity
            FROM theory_positions p
            JOIN theory_accounts a ON a.id = p.account_id
            WHERE a.project_id = ? AND p.symbol = ? AND p.quantity > 0
            """,
            (project_id, normalized_symbol),
        ).fetchone()
        if position is not None:
            raise ValueError("该股票仍有理论持仓，不能从当前跟踪中删除。")
        result = conn.execute(
            """
            UPDATE tracked_instruments
            SET tracking_state = 'CLOSED', pending_cash_ratio = NULL,
                pending_sell_ratio = NULL,
                target_position = NULL, processing_status = 'IGNORED', updated_at = ?
            WHERE project_id = ?
              AND tracking_state IN ('WATCHING', 'HOLDING')
              AND instrument_id = (
                  SELECT id FROM instruments WHERE symbol = ?
              )
            """,
            (now_iso(), project_id, normalized_symbol),
        )
        if result.rowcount == 0:
            raise ValueError("未找到对应的当前跟踪股票。")


def archive_tracking(project_id: int, symbol: str) -> None:
    normalized_symbol = _normalize_symbol(symbol)
    with db.get_connection() as conn:
        theory_position = conn.execute(
            """
            SELECT p.quantity
            FROM theory_positions p
            JOIN theory_accounts a ON a.id = p.account_id
            WHERE a.project_id = ? AND p.symbol = ? AND p.quantity > 0
            """,
            (project_id, normalized_symbol),
        ).fetchone()
        if theory_position is not None:
            raise ValueError("该股票仍有理论持仓，请全部卖出后再归档。")
        result = conn.execute(
            """
            UPDATE tracked_instruments
            SET tracking_state = 'CLOSED', pending_cash_ratio = NULL,
                pending_sell_ratio = NULL, target_position = NULL,
                watch_expires_at = NULL, processing_status = 'CONFIRMED',
                updated_at = ?
            WHERE project_id = ?
              AND tracking_state IN ('WATCHING', 'HOLDING')
              AND instrument_id = (
                  SELECT id FROM instruments WHERE symbol = ?
              )
            """,
            (now_iso(), project_id, normalized_symbol),
        )
        if result.rowcount == 0:
            raise ValueError("未找到对应的当前跟踪股票。")


def refresh_tracking_price(project_id: int, symbol: str) -> dict:
    normalized_symbol = _normalize_symbol(symbol)
    with db.get_connection() as conn:
        tracked = conn.execute(
            """
            SELECT t.id
            FROM tracked_instruments t
            JOIN instruments i ON i.id = t.instrument_id
            WHERE t.project_id = ? AND i.symbol = ?
              AND t.tracking_state IN ('WATCHING', 'HOLDING')
            """,
            (project_id, normalized_symbol),
        ).fetchone()
        if tracked is None:
            raise ValueError("未找到对应的当前跟踪股票。")

    quote = market_data.fetch_realtime_quote(normalized_symbol)
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO theory_reference_prices (
                symbol, price, price_time, source, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol, price_time, source) DO UPDATE SET
                price = excluded.price,
                created_at = excluded.created_at
            """,
            (
                quote.symbol,
                quote.price,
                quote.price_time,
                quote.source,
                now_iso(),
            ),
        )
        conn.execute(
            """
            UPDATE tracked_instruments
            SET reference_price = ?, updated_at = ?
            WHERE id = ?
            """,
            (quote.price, now_iso(), tracked["id"]),
        )
    return {
        "symbol": normalized_symbol,
        "price": quote.price,
        "price_time": quote.price_time,
        "source": quote.source,
    }


def refresh_all_tracking_prices(project_id: int) -> dict:
    tracked_rows = paper_db.rows(
        """
        SELECT i.symbol
        FROM tracked_instruments t
        JOIN instruments i ON i.id = t.instrument_id
        WHERE t.project_id = ?
          AND t.tracking_state IN ('WATCHING', 'HOLDING')
        ORDER BY t.recommended_at DESC, i.symbol
        """,
        (project_id,),
    )
    if not tracked_rows:
        raise ValueError("当前没有需要刷新价格的股票。")

    symbols = [str(row["symbol"]) for row in tracked_rows]
    quotes, quote_failures = market_data.fetch_realtime_quotes(symbols)
    updated = []
    failed = [
        {"symbol": symbol, "message": quote_failures[symbol]}
        for symbol in symbols
        if symbol in quote_failures
    ]

    with db.get_connection() as conn:
        for symbol in symbols:
            quote = quotes.get(symbol)
            if quote is None:
                continue
            conn.execute(
                """
                INSERT INTO theory_reference_prices (
                    symbol, price, price_time, source, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol, price_time, source) DO UPDATE SET
                    price = excluded.price,
                    created_at = excluded.created_at
                """,
                (
                    quote.symbol,
                    quote.price,
                    quote.price_time,
                    quote.source,
                    now_iso(),
                ),
            )
            conn.execute(
                """
                UPDATE tracked_instruments
                SET reference_price = ?, updated_at = ?
                WHERE project_id = ? AND instrument_id = (
                    SELECT id FROM instruments WHERE symbol = ?
                )
                  AND tracking_state IN ('WATCHING', 'HOLDING')
                """,
                (quote.price, now_iso(), project_id, symbol),
            )
            updated.append(
                {
                    "symbol": symbol,
                    "price": quote.price,
                    "price_time": quote.price_time,
                    "source": quote.source,
                }
            )

    if not updated:
        detail = failed[0]["message"] if failed else "行情服务暂无可用数据。"
        raise ValueError(f"全部实时行情刷新失败：{detail}")
    return {
        "updated": updated,
        "failed": failed,
        "updated_count": len(updated),
        "failed_count": len(failed),
    }


def list_tracking(
    project_id: int,
    *,
    states: tuple[str, ...] = ("WATCHING", "HOLDING"),
    keyword: str = "",
    as_of: str | datetime | date | None = None,
) -> list[dict]:
    expire_watching(project_id, as_of)
    normalized_states = tuple(state.upper() for state in states)
    if not normalized_states:
        return []
    if any(state not in TRACKING_STATES for state in normalized_states):
        raise ValueError("不支持的跟踪状态。")
    placeholders = ",".join("?" for _ in normalized_states)
    query = f"""
        SELECT
            t.id, i.symbol, i.name, t.tracking_state, t.recommended_at,
            t.watch_expires_at, t.source_recommendation_id, t.latest_action,
            t.latest_signal_at, t.target_position, t.pending_cash_ratio,
            t.pending_sell_ratio,
            t.reference_price,
            t.predicted_low, t.predicted_high, t.peak_hint,
            t.processing_status, t.raw_text,
            (
                SELECT e.signal_type
                FROM signal_events e
                WHERE e.project_id = t.project_id
                  AND e.instrument_id = t.instrument_id
                ORDER BY e.occurred_at DESC, e.id DESC
                LIMIT 1
            ) AS signal_type
        FROM tracked_instruments t
        JOIN instruments i ON i.id = t.instrument_id
        WHERE t.project_id = ?
          AND t.tracking_state IN ({placeholders})
    """
    params: list[Any] = [project_id, *normalized_states]
    normalized_keyword = keyword.strip()
    if normalized_keyword:
        query += " AND (i.symbol LIKE ? OR i.name LIKE ?)"
        term = f"%{normalized_keyword}%"
        params.extend([term.upper(), term])
    query += " ORDER BY t.recommended_at DESC, i.symbol"
    return [dict(row) for row in paper_db.rows(query, tuple(params))]


def tracking_summary(
    project_id: int, as_of: str | datetime | date | None = None
) -> dict:
    expire_watching(project_id, as_of)
    if as_of is None:
        day = date.today().isoformat()
    elif isinstance(as_of, (datetime, date)):
        day = as_of.date().isoformat() if isinstance(as_of, datetime) else as_of.isoformat()
    else:
        day = _parse_datetime(as_of).date().isoformat()
    with db.get_connection() as conn:
        counts = {
            row["tracking_state"]: int(row["count"])
            for row in conn.execute(
                """
                SELECT tracking_state, COUNT(*) AS count
                FROM tracked_instruments
                WHERE project_id = ?
                GROUP BY tracking_state
                """,
                (project_id,),
            )
        }
        today_added = conn.execute(
            """
            SELECT COUNT(*) AS count FROM tracked_instruments
            WHERE project_id = ? AND date(recommended_at) = date(?)
            """,
            (project_id, day),
        ).fetchone()
    return {
        "watching": counts.get("WATCHING", 0),
        "holding": counts.get("HOLDING", 0),
        "expired": counts.get("EXPIRED", 0),
        "closed": counts.get("CLOSED", 0),
        "today_added": int(today_added["count"]),
    }


def _signal_fingerprint(
    project_id: int,
    symbol: str,
    occurred_at: str,
    normalized_action: str,
    signal_type: str,
    raw_text: str,
    source_name: str,
    external_event_id: str | None,
) -> str:
    payload = "|".join(
        (
            str(project_id),
            symbol,
            occurred_at,
            normalized_action,
            signal_type.strip(),
            raw_text.strip(),
            source_name.strip(),
            external_event_id or "",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_signal_event(
    project_id: int,
    symbol: str,
    name: str,
    occurred_at: str | datetime,
    normalized_action: str,
    *,
    signal_type: str = "",
    raw_action: str = "",
    target_position: float | None = None,
    reference_price: float | None = None,
    predicted_low: float | None = None,
    predicted_high: float | None = None,
    raw_text: str = "",
    raw_payload: dict | None = None,
    source_name: str = "test-stub",
    external_event_id: str | None = None,
    received_at: str | datetime | None = None,
    processing_status: str = "RECORDED",
    processing_reason: str = "",
    parser_version: int = 1,
) -> int:
    paper_db.migrate()
    action = normalized_action.strip().upper()
    if action not in SIGNAL_ACTIONS:
        raise ValueError("不支持的信号动作。")
    status = processing_status.strip().upper()
    if status not in SIGNAL_STATUSES:
        raise ValueError("不支持的信号处理状态。")
    if parser_version < 1:
        raise ValueError("解析版本必须大于 0。")
    normalized_symbol = _normalize_symbol(symbol)
    occurred_text = _iso(occurred_at)
    received_text = _iso(received_at) if received_at else now_iso()
    source = source_name.strip()
    if not source:
        raise ValueError("信号来源不能为空。")
    external_id = external_event_id.strip() if external_event_id else None
    fingerprint = _signal_fingerprint(
        project_id,
        normalized_symbol,
        occurred_text,
        action,
        signal_type,
        raw_text,
        source,
        external_id,
    )
    target = _validate_position(target_position)
    reference = _validate_price(reference_price, "信号价格")
    low = _validate_price(predicted_low, "预测最低")
    high = _validate_price(predicted_high, "预测最高")
    payload_json = json.dumps(
        raw_payload or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )

    with db.get_connection() as conn:
        if external_id:
            existing = conn.execute(
                """
                SELECT id FROM signal_events
                WHERE source_name = ? AND external_event_id = ?
                """,
                (source, external_id),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        existing = conn.execute(
            "SELECT id FROM signal_events WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if existing is not None:
            return int(existing["id"])
        instrument_id = _upsert_instrument(
            conn, normalized_symbol, name, occurred_text
        )
        cursor = conn.execute(
            """
            INSERT INTO signal_events (
                project_id, external_event_id, instrument_id, occurred_at,
                received_at, signal_type, raw_action, normalized_action,
                target_position, reference_price, predicted_low, predicted_high,
                raw_text, raw_payload_json, source_name, fingerprint,
                processing_status, processing_reason, parser_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                external_id,
                instrument_id,
                occurred_text,
                received_text,
                signal_type.strip(),
                raw_action.strip() or action,
                action,
                target,
                reference,
                low,
                high,
                raw_text.strip(),
                payload_json,
                source,
                fingerprint,
                status,
                processing_reason.strip(),
                parser_version,
                now_iso(),
            ),
        )
        event_id = int(cursor.lastrowid)
        tracked = conn.execute(
            """
            SELECT id FROM tracked_instruments
            WHERE project_id = ? AND instrument_id = ?
            """,
            (project_id, instrument_id),
        ).fetchone()
        tracking_status = (
            "IGNORED" if status == "IGNORED"
            else "SIGNALLED" if status in {"PENDING_RULE", "ORDER_CREATED"}
            else "CONFIRMED"
        )
        if tracked is None:
            tracking_state = "HOLDING" if action in {"REDUCE", "SELL"} else "WATCHING"
            expires_at = (
                None
                if tracking_state == "HOLDING"
                else _iso(_parse_datetime(occurred_text) + timedelta(days=5))
            )
            conn.execute(
                """
                INSERT INTO tracked_instruments (
                    project_id, instrument_id, tracking_state, recommended_at,
                    watch_expires_at, source_recommendation_id, latest_action,
                    latest_signal_at, target_position, reference_price,
                    predicted_low, predicted_high, peak_hint, processing_status,
                    raw_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
                """,
                (
                    project_id,
                    instrument_id,
                    tracking_state,
                    occurred_text,
                    expires_at,
                    external_id,
                    action,
                    occurred_text,
                    target,
                    reference,
                    low,
                    high,
                    tracking_status,
                    raw_text.strip(),
                    now_iso(),
                    now_iso(),
                ),
            )
        else:
            conn.execute(
                """
                UPDATE tracked_instruments SET
                    latest_action = ?, latest_signal_at = ?,
                    target_position = COALESCE(?, target_position),
                    reference_price = COALESCE(?, reference_price),
                    predicted_low = COALESCE(?, predicted_low),
                    predicted_high = COALESCE(?, predicted_high),
                    processing_status = ?, raw_text = ?, updated_at = ?
                WHERE id = ?
                  AND (latest_signal_at IS NULL OR latest_signal_at <= ?)
                """,
                (
                    action,
                    occurred_text,
                    target,
                    reference,
                    low,
                    high,
                    tracking_status,
                    raw_text.strip(),
                    now_iso(),
                    tracked["id"],
                    occurred_text,
                ),
            )
        return event_id


def signal_instruments(project_id: int) -> list[dict]:
    return [
        dict(row)
        for row in paper_db.rows(
            """
            SELECT i.symbol, i.name
            FROM instruments i
            WHERE EXISTS (
                SELECT 1 FROM tracked_instruments t
                WHERE t.instrument_id = i.id AND t.project_id = ?
            ) OR EXISTS (
                SELECT 1 FROM signal_events e
                WHERE e.instrument_id = i.id AND e.project_id = ?
            )
            ORDER BY i.symbol
            """,
            (project_id, project_id),
        )
    ]


def list_signal_events(
    project_id: int,
    *,
    symbol: str | None = None,
    signal_date: str | None = None,
    signal_types: tuple[str, ...] = (),
) -> list[dict]:
    query = """
        SELECT
            e.id, e.external_event_id, i.symbol, i.name, e.occurred_at,
            e.received_at, e.signal_type, e.raw_action, e.normalized_action,
            e.target_position, e.reference_price, e.predicted_low,
            e.predicted_high, e.raw_text, e.raw_payload_json, e.source_name,
            e.fingerprint, e.processing_status, e.processing_reason,
            e.parser_version
        FROM signal_events e
        JOIN instruments i ON i.id = e.instrument_id
        WHERE e.project_id = ?
    """
    params: list[Any] = [project_id]
    if symbol:
        query += " AND i.symbol = ?"
        params.append(_normalize_symbol(symbol))
    if signal_date:
        query += " AND date(e.occurred_at) = date(?)"
        params.append(signal_date)
    if signal_types:
        placeholders = ",".join("?" for _ in signal_types)
        query += f" AND e.signal_type IN ({placeholders})"
        params.extend(signal_types)
    query += " ORDER BY e.occurred_at DESC, e.id DESC"
    return [dict(row) for row in paper_db.rows(query, tuple(params))]
