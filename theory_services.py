from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import db
import paper_db


DEFAULT_INITIAL_CASH = 100_000.0
BUY_RATIOS = {0.10, 0.40, 0.50}
SELL_RATIOS = {0.50, 1.00}


@dataclass(frozen=True)
class TheoryRecordPreview:
    project_id: int
    account_id: int
    symbol: str
    side: str
    allocation_ratio: float
    allocation_basis: str
    reference_price: float
    price_time: str
    price_source: str
    quantity: int
    gross_amount: float
    cash_change: float
    cash_before: float
    position_before: int
    equity_before: float
    capital_ratio: float
    realized_pnl: float


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _normalize_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if not value:
        raise ValueError("股票代码不能为空。")
    if value.isdigit() and len(value) == 6:
        if value.startswith(("4", "8")):
            return f"{value}.BJ"
        if value.startswith(("5", "6")):
            return f"{value}.SH"
        return f"{value}.SZ"
    if "." in value:
        code, exchange = value.rsplit(".", 1)
        if exchange == "SS":
            return f"{code}.SH"
    return value


def ensure_account(
    project_id: int,
    *,
    initial_cash: float = DEFAULT_INITIAL_CASH,
) -> int:
    paper_db.migrate()
    if initial_cash <= 0:
        raise ValueError("理论账户期初资金必须大于 0。")
    with db.get_connection() as conn:
        account = conn.execute(
            "SELECT id FROM theory_accounts WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if account is not None:
            return int(account["id"])
        created_at = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO theory_accounts (
                project_id, name, initial_cash, cash_balance, currency,
                created_at, updated_at
            ) VALUES (?, '理论收益账户', ?, ?, 'CNY', ?, ?)
            """,
            (project_id, initial_cash, initial_cash, created_at, created_at),
        )
        account_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO theory_cash_ledger (
                account_id, event_type, amount, balance_after, note, occurred_at
            ) VALUES (?, 'INITIAL_DEPOSIT', ?, ?, '理论账户期初资金', ?)
            """,
            (account_id, initial_cash, initial_cash, created_at),
        )
        return account_id


def upsert_reference_price(
    symbol: str,
    price: float,
    *,
    price_time: str | None = None,
    source: str = "本地样本",
) -> None:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_price = float(price)
    if normalized_price <= 0:
        raise ValueError("参考价格必须大于 0。")
    timestamp = price_time or now_iso()
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
            (normalized_symbol, normalized_price, timestamp, source, now_iso()),
        )
        conn.execute(
            """
            UPDATE tracked_instruments
            SET reference_price = ?, updated_at = ?
            WHERE instrument_id = (
                SELECT id FROM instruments WHERE symbol = ?
            )
            """,
            (normalized_price, now_iso(), normalized_symbol),
        )


def _latest_price(conn, symbol: str, fallback: float = 0.0) -> dict:
    row = conn.execute(
        """
        SELECT price, price_time, source
        FROM theory_reference_prices
        WHERE symbol = ?
        ORDER BY price_time DESC, id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is not None:
        return dict(row)
    row = conn.execute(
        """
        SELECT close AS price, trade_date || ' 15:00:00' AS price_time,
               '本地日行情' AS source
        FROM paper_market_daily
        WHERE symbol = ? AND close IS NOT NULL
        ORDER BY trade_date DESC, id DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is not None:
        return dict(row)
    row = conn.execute(
        """
        SELECT t.reference_price AS price, t.updated_at AS price_time,
               '当前跟踪参考价' AS source
        FROM tracked_instruments t
        JOIN instruments i ON i.id = t.instrument_id
        WHERE i.symbol = ? AND t.reference_price IS NOT NULL
        ORDER BY t.updated_at DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    if row is not None:
        return dict(row)
    if fallback > 0:
        return {"price": fallback, "price_time": now_iso(), "source": "持仓成本"}
    raise ValueError(f"{symbol} 暂无有效参考价格，请先刷新或录入参考行情。")


def _account_summary(conn, account_id: int) -> dict:
    account = conn.execute(
        "SELECT * FROM theory_accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if account is None:
        raise ValueError("理论账户不存在。")
    positions = conn.execute(
        """
        SELECT symbol, quantity, cost_total, realized_pnl
        FROM theory_positions
        WHERE account_id = ?
        """,
        (account_id,),
    ).fetchall()
    market_value = 0.0
    unrealized = 0.0
    realized = 0.0
    for position in positions:
        quantity = int(position["quantity"])
        cost_total = float(position["cost_total"])
        realized += float(position["realized_pnl"])
        if quantity <= 0:
            continue
        mark = float(_latest_price(conn, position["symbol"], cost_total / quantity)["price"])
        market_value += quantity * mark
        unrealized += quantity * mark - cost_total
    cash = float(account["cash_balance"])
    equity = cash + market_value
    return {
        "account_id": account_id,
        "initial_cash": float(account["initial_cash"]),
        "cash": cash,
        "market_value": market_value,
        "equity": equity,
        "position_pct": market_value / equity if equity > 0 else 0.0,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": equity - float(account["initial_cash"]),
    }


def account_summary(project_id: int) -> dict:
    account_id = ensure_account(project_id)
    with db.get_connection() as conn:
        return _account_summary(conn, account_id)


def _preview_with_connection(
    conn,
    project_id: int,
    symbol: str,
    side: str,
    allocation_ratio: float,
    *,
    recorded_at: str,
    reference_price: float | None = None,
    price_source: str | None = None,
) -> TheoryRecordPreview:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_side = side.strip().upper()
    ratio = float(allocation_ratio)
    if normalized_side == "BUY" and ratio not in BUY_RATIOS:
        raise ValueError("理论买入比例仅支持剩余现金的 10%、40% 或 50%。")
    if normalized_side == "SELL" and ratio not in SELL_RATIOS:
        raise ValueError("理论卖出比例仅支持当前持仓的 50% 或 100%。")
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("操作只能是买入或卖出。")

    tracked = conn.execute(
        """
        SELECT i.lot_size
        FROM tracked_instruments t
        JOIN instruments i ON i.id = t.instrument_id
        WHERE t.project_id = ? AND i.symbol = ?
          AND t.tracking_state IN ('WATCHING', 'HOLDING')
        """,
        (project_id, normalized_symbol),
    ).fetchone()
    if tracked is None:
        raise ValueError("未找到对应的当前跟踪股票。")
    account = conn.execute(
        "SELECT id, cash_balance FROM theory_accounts WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    if account is None:
        raise ValueError("理论账户不存在。")
    account_id = int(account["id"])
    summary = _account_summary(conn, account_id)
    position = conn.execute(
        """
        SELECT quantity, cost_total FROM theory_positions
        WHERE account_id = ? AND symbol = ?
        """,
        (account_id, normalized_symbol),
    ).fetchone()
    current_quantity = int(position["quantity"]) if position else 0
    current_cost = float(position["cost_total"]) if position else 0.0
    if reference_price is None:
        price_row = _latest_price(conn, normalized_symbol)
        price = float(price_row["price"])
        price_time = str(price_row["price_time"])
        source = str(price_row["source"])
    else:
        price = float(reference_price)
        if price <= 0:
            raise ValueError("参考价格必须大于 0。")
        price_time = recorded_at
        source = price_source or "手工样本"
    lot_size = int(tracked["lot_size"] or 100)

    if normalized_side == "BUY":
        planned_amount = summary["cash"] * ratio
        quantity = math.floor(planned_amount / price / lot_size) * lot_size
        if quantity <= 0:
            raise ValueError("剩余理论现金不足以买入一个交易单位。")
        gross_amount = price * quantity
        if gross_amount > summary["cash"] + 1e-8:
            raise ValueError("理论账户剩余现金不足。")
        cash_change = -gross_amount
        realized_pnl = 0.0
        basis = "CASH_POOL"
    else:
        if current_quantity <= 0:
            raise ValueError("该股票当前没有理论持仓。")
        if ratio == 1.0:
            quantity = current_quantity
        else:
            quantity = math.floor(current_quantity * ratio / lot_size) * lot_size
        if quantity <= 0:
            raise ValueError("按所选比例计算后不足一个可卖交易单位。")
        gross_amount = price * quantity
        cash_change = gross_amount
        average_cost = current_cost / current_quantity
        realized_pnl = gross_amount - average_cost * quantity
        basis = "STOCK_POSITION"

    capital_ratio = (
        gross_amount / summary["equity"] if summary["equity"] > 0 else 0.0
    )
    return TheoryRecordPreview(
        project_id=project_id,
        account_id=account_id,
        symbol=normalized_symbol,
        side=normalized_side,
        allocation_ratio=ratio,
        allocation_basis=basis,
        reference_price=price,
        price_time=price_time,
        price_source=source,
        quantity=int(quantity),
        gross_amount=gross_amount,
        cash_change=cash_change,
        cash_before=summary["cash"],
        position_before=current_quantity,
        equity_before=summary["equity"],
        capital_ratio=capital_ratio,
        realized_pnl=realized_pnl,
    )


def preview_record(
    project_id: int,
    symbol: str,
    side: str,
    allocation_ratio: float,
    *,
    reference_price: float | None = None,
    price_source: str | None = None,
) -> TheoryRecordPreview:
    ensure_account(project_id)
    with db.get_connection() as conn:
        return _preview_with_connection(
            conn,
            project_id,
            symbol,
            side,
            allocation_ratio,
            recorded_at=now_iso(),
            reference_price=reference_price,
            price_source=price_source,
        )


def _consume_lots(
    conn,
    account_id: int,
    symbol: str,
    quantity: int,
) -> None:
    remaining = quantity
    lots = conn.execute(
        """
        SELECT id, remaining_quantity
        FROM theory_position_lots
        WHERE account_id = ? AND symbol = ?
          AND remaining_quantity > 0
        ORDER BY available_date, id
        """,
        (account_id, symbol),
    ).fetchall()
    for lot in lots:
        consumed = min(remaining, int(lot["remaining_quantity"]))
        conn.execute(
            """
            UPDATE theory_position_lots
            SET remaining_quantity = remaining_quantity - ?
            WHERE id = ?
            """,
            (consumed, lot["id"]),
        )
        remaining -= consumed
        if remaining == 0:
            return
    raise ValueError("理论可卖批次数量不足。")


def create_record(
    project_id: int,
    symbol: str,
    side: str,
    allocation_ratio: float,
    *,
    recorded_at: str | None = None,
    reference_price: float | None = None,
    price_source: str | None = None,
    operator: str = "手工记录",
    fixture_key: str | None = None,
) -> int:
    ensure_account(project_id)
    timestamp = recorded_at or now_iso()
    with db.get_connection() as conn:
        if fixture_key:
            existing = conn.execute(
                "SELECT id FROM theory_trade_records WHERE fixture_key = ?",
                (fixture_key,),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        preview = _preview_with_connection(
            conn,
            project_id,
            symbol,
            side,
            allocation_ratio,
            recorded_at=timestamp,
            reference_price=reference_price,
            price_source=price_source,
        )
        created_at = now_iso()
        cursor = conn.execute(
            """
            INSERT INTO theory_trade_records (
                project_id, account_id, symbol, side, recorded_at,
                allocation_ratio, allocation_basis, reference_price,
                price_time, price_source, quantity, gross_amount, cash_change,
                equity_before, cash_before, position_before, capital_ratio,
                realized_pnl, operator, fixture_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                preview.account_id,
                preview.symbol,
                preview.side,
                timestamp,
                preview.allocation_ratio,
                preview.allocation_basis,
                preview.reference_price,
                preview.price_time,
                preview.price_source,
                preview.quantity,
                preview.gross_amount,
                preview.cash_change,
                preview.equity_before,
                preview.cash_before,
                preview.position_before,
                preview.capital_ratio,
                preview.realized_pnl,
                operator,
                fixture_key,
                created_at,
            ),
        )
        record_id = int(cursor.lastrowid)
        position = conn.execute(
            """
            SELECT quantity, cost_total, realized_pnl
            FROM theory_positions
            WHERE account_id = ? AND symbol = ?
            """,
            (preview.account_id, preview.symbol),
        ).fetchone()
        current_quantity = int(position["quantity"]) if position else 0
        current_cost = float(position["cost_total"]) if position else 0.0
        cumulative_realized = float(position["realized_pnl"]) if position else 0.0
        if preview.side == "BUY":
            next_quantity = current_quantity + preview.quantity
            next_cost = current_cost + preview.gross_amount
            conn.execute(
                """
                INSERT INTO theory_position_lots (
                    account_id, symbol, source_record_id, remaining_quantity,
                    unit_cost, available_date, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preview.account_id,
                    preview.symbol,
                    record_id,
                    preview.quantity,
                    preview.reference_price,
                    timestamp[:10],
                    created_at,
                ),
            )
        else:
            average_cost = current_cost / current_quantity
            next_quantity = current_quantity - preview.quantity
            next_cost = max(0.0, current_cost - average_cost * preview.quantity)
            cumulative_realized += preview.realized_pnl
            _consume_lots(
                conn,
                preview.account_id,
                preview.symbol,
                preview.quantity,
            )
        conn.execute(
            """
            INSERT INTO theory_positions (
                account_id, symbol, quantity, cost_total, realized_pnl, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, symbol) DO UPDATE SET
                quantity = excluded.quantity,
                cost_total = excluded.cost_total,
                realized_pnl = excluded.realized_pnl,
                updated_at = excluded.updated_at
            """,
            (
                preview.account_id,
                preview.symbol,
                next_quantity,
                next_cost,
                cumulative_realized,
                timestamp,
            ),
        )
        next_cash = preview.cash_before + preview.cash_change
        conn.execute(
            """
            UPDATE theory_accounts
            SET cash_balance = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_cash, timestamp, preview.account_id),
        )
        conn.execute(
            """
            INSERT INTO theory_cash_ledger (
                account_id, record_id, event_type, amount, balance_after,
                note, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preview.account_id,
                record_id,
                "THEORY_BUY" if preview.side == "BUY" else "THEORY_SELL",
                preview.cash_change,
                next_cash,
                f"{preview.symbol} 理论{'买入' if preview.side == 'BUY' else '卖出'}",
                timestamp,
            ),
        )
        tracking_state = "HOLDING" if next_quantity > 0 else "WATCHING"
        conn.execute(
            """
            UPDATE tracked_instruments
            SET tracking_state = ?, latest_action = ?,
                pending_cash_ratio = NULL, pending_sell_ratio = NULL,
                target_position = NULL, reference_price = ?,
                watch_expires_at = CASE WHEN ? = 'WATCHING'
                    THEN datetime(?, '+5 days') ELSE NULL END,
                processing_status = 'CONFIRMED', updated_at = ?
            WHERE project_id = ? AND instrument_id = (
                SELECT id FROM instruments WHERE symbol = ?
            )
            """,
            (
                tracking_state,
                preview.side,
                preview.reference_price,
                tracking_state,
                timestamp,
                timestamp,
                project_id,
                preview.symbol,
            ),
        )
        return record_id


def position_rows(project_id: int) -> list[dict]:
    account_id = ensure_account(project_id)
    summary = account_summary(project_id)
    with db.get_connection() as conn:
        positions = conn.execute(
            """
            SELECT p.symbol, i.name, p.quantity, p.cost_total, p.realized_pnl
            FROM theory_positions p
            LEFT JOIN instruments i ON i.symbol = p.symbol
            WHERE p.account_id = ?
            ORDER BY p.symbol
            """,
            (account_id,),
        ).fetchall()
        result = []
        for position in positions:
            quantity = int(position["quantity"])
            cost_total = float(position["cost_total"])
            price_row = _latest_price(
                conn,
                position["symbol"],
                cost_total / quantity if quantity else 0,
            )
            mark = float(price_row["price"])
            market_value = quantity * mark
            result.append(
                {
                    "symbol": position["symbol"],
                    "name": position["name"] or position["symbol"],
                    "quantity": quantity,
                    "available_quantity": quantity,
                    "average_cost": cost_total / quantity if quantity else None,
                    "reference_price": mark,
                    "market_value": market_value,
                    "position_pct": market_value / summary["equity"] if summary["equity"] else 0,
                    "unrealized_pnl": market_value - cost_total,
                    "realized_pnl": float(position["realized_pnl"]),
                    "pnl_ratio": (market_value - cost_total) / cost_total if cost_total else None,
                }
            )
        return result


def tracking_position_map(project_id: int) -> dict[str, dict]:
    return {row["symbol"]: row for row in position_rows(project_id)}


def history_instruments(project_id: int) -> list[dict]:
    rows = paper_db.rows(
        """
        SELECT symbol, MAX(name) AS name, MAX(has_record) AS has_record
        FROM (
            SELECT i.symbol, i.name, 0 AS has_record
            FROM tracked_instruments t
            JOIN instruments i ON i.id = t.instrument_id
            WHERE t.project_id = ?
              AND t.tracking_state IN ('WATCHING', 'HOLDING')

            UNION ALL

            SELECT r.symbol, COALESCE(i.name, r.symbol), 1 AS has_record
            FROM theory_trade_records r
            LEFT JOIN instruments i ON i.symbol = r.symbol
            WHERE r.project_id = ?

            UNION ALL

            SELECT i.symbol, i.name, 1 AS has_record
            FROM tracking_operation_records o
            JOIN instruments i ON i.id = o.instrument_id
            WHERE o.project_id = ?
        ) items
        GROUP BY symbol
        ORDER BY has_record DESC, symbol
        """,
        (project_id, project_id, project_id),
    )
    return [dict(row) for row in rows]


def trade_history(project_id: int, symbol: str) -> list[dict]:
    normalized_symbol = _normalize_symbol(symbol)
    return [
        dict(row)
        for row in paper_db.rows(
            """
            SELECT r.*, COALESCE(i.name, r.symbol) AS name
            FROM theory_trade_records r
            LEFT JOIN instruments i ON i.symbol = r.symbol
            WHERE r.project_id = ? AND r.symbol = ?
            ORDER BY r.recorded_at DESC, r.id DESC
            """,
            (project_id, normalized_symbol),
        )
    ]


def all_trade_history(project_id: int) -> list[dict]:
    return [
        dict(row)
        for row in paper_db.rows(
            """
            SELECT r.*, COALESCE(i.name, r.symbol) AS name
            FROM theory_trade_records r
            LEFT JOIN instruments i ON i.symbol = r.symbol
            WHERE r.project_id = ?
            ORDER BY r.recorded_at DESC, r.id DESC
            """,
            (project_id,),
        )
    ]


def _operation_history(project_id: int, symbol: str | None = None) -> list[dict]:
    normalized_symbol = _normalize_symbol(symbol) if symbol is not None else None
    trade_symbol_filter = "AND r.symbol = ?" if normalized_symbol else ""
    watch_symbol_filter = "AND i.symbol = ?" if normalized_symbol else ""
    params: tuple = (project_id,)
    if normalized_symbol:
        params += (normalized_symbol,)
    params += (project_id,)
    if normalized_symbol:
        params += (normalized_symbol,)
    return [
        dict(row)
        for row in paper_db.rows(
            f"""
            SELECT *
            FROM (
                SELECT
                    'TRADE' AS record_kind,
                    r.id AS source_id,
                    r.symbol,
                    COALESCE(i.name, r.symbol) AS name,
                    r.side,
                    r.recorded_at,
                    r.allocation_ratio,
                    r.capital_ratio,
                    r.reference_price,
                    r.quantity,
                    r.gross_amount,
                    r.cash_change
                FROM theory_trade_records r
                LEFT JOIN instruments i ON i.symbol = r.symbol
                WHERE r.project_id = ? {trade_symbol_filter}

                UNION ALL

                SELECT
                    'TRACKING' AS record_kind,
                    o.id AS source_id,
                    i.symbol,
                    i.name,
                    o.action AS side,
                    o.occurred_at AS recorded_at,
                    NULL AS allocation_ratio,
                    NULL AS capital_ratio,
                    NULL AS reference_price,
                    NULL AS quantity,
                    NULL AS gross_amount,
                    NULL AS cash_change
                FROM tracking_operation_records o
                JOIN instruments i ON i.id = o.instrument_id
                WHERE o.project_id = ? {watch_symbol_filter}
            ) operations
            ORDER BY recorded_at DESC,
                     CASE record_kind WHEN 'TRADE' THEN 1 ELSE 0 END DESC,
                     source_id DESC
            """,
            params,
        )
    ]


def operation_history(project_id: int, symbol: str) -> list[dict]:
    return _operation_history(project_id, symbol)


def all_operation_history(project_id: int) -> list[dict]:
    return _operation_history(project_id)


def paged_operation_history(
    project_id: int,
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Search and page the combined watch and trade operation history."""
    paper_db.migrate()
    if page < 1:
        raise ValueError("页码必须大于等于 1。")
    if page_size < 1:
        raise ValueError("每页条数必须大于等于 1。")

    search_text = query.strip()
    if search_text.isdigit() and len(search_text) == 6:
        search_text = _normalize_symbol(search_text)
    elif search_text.upper().endswith(".SS"):
        search_text = f"{search_text[:-3]}.SH"
    escaped = (
        search_text.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    pattern = f"%{escaped}%"
    operation_cte = """
        WITH operations AS (
            SELECT
                'TRADE' AS record_kind,
                r.id AS source_id,
                r.symbol,
                COALESCE(i.name, r.symbol) AS name,
                r.side,
                r.recorded_at,
                r.allocation_ratio,
                r.capital_ratio,
                r.reference_price,
                r.quantity,
                r.gross_amount,
                r.cash_change
            FROM theory_trade_records r
            LEFT JOIN instruments i ON i.symbol = r.symbol
            WHERE r.project_id = ?

            UNION ALL

            SELECT
                'TRACKING' AS record_kind,
                o.id AS source_id,
                i.symbol,
                i.name,
                o.action AS side,
                o.occurred_at AS recorded_at,
                NULL AS allocation_ratio,
                NULL AS capital_ratio,
                NULL AS reference_price,
                NULL AS quantity,
                NULL AS gross_amount,
                NULL AS cash_change
            FROM tracking_operation_records o
            JOIN instruments i ON i.id = o.instrument_id
            WHERE o.project_id = ?
        ),
        filtered AS (
            SELECT *
            FROM operations
            WHERE ? = ''
               OR UPPER(symbol) LIKE UPPER(?) ESCAPE '\\'
               OR name LIKE ? ESCAPE '\\'
        )
    """
    base_params = (project_id, project_id, search_text, pattern, pattern)
    with db.get_connection() as conn:
        summary = conn.execute(
            operation_cte
            + """
            SELECT
                COUNT(*) AS total_count,
                COUNT(DISTINCT symbol) AS symbol_count,
                MIN(symbol) AS matched_symbol,
                MIN(name) AS matched_name
            FROM filtered
            """,
            base_params,
        ).fetchone()
        total_count = int(summary["total_count"])
        page_count = math.ceil(total_count / page_size) if total_count else 0
        current_page = min(page, page_count) if page_count else 1
        offset = (current_page - 1) * page_size
        rows = conn.execute(
            operation_cte
            + """
            SELECT *
            FROM filtered
            ORDER BY recorded_at DESC,
                     CASE record_kind WHEN 'TRADE' THEN 1 ELSE 0 END DESC,
                     source_id DESC
            LIMIT ? OFFSET ?
            """,
            base_params + (page_size, offset),
        ).fetchall()
    return {
        "rows": [dict(row) for row in rows],
        "query": search_text,
        "page": current_page,
        "page_size": page_size,
        "page_count": page_count,
        "total_count": total_count,
        "symbol_count": int(summary["symbol_count"]),
        "matched_symbol": summary["matched_symbol"],
        "matched_name": summary["matched_name"],
    }


def available_months(project_id: int) -> list[str]:
    rows = paper_db.rows(
        """
        SELECT DISTINCT substr(recorded_at, 1, 7) AS month
        FROM theory_trade_records
        WHERE project_id = ?
        ORDER BY month DESC
        """,
        (project_id,),
    )
    return [str(row["month"]) for row in rows]


def monthly_statistics(project_id: int, month: str) -> dict:
    if len(month) != 7 or month[4] != "-":
        raise ValueError("统计月份格式应为 YYYY-MM。")
    account = account_summary(project_id)
    positions = tracking_position_map(project_id)
    rows = paper_db.rows(
        """
        SELECT
            r.symbol,
            COALESCE(i.name, r.symbol) AS name,
            SUM(CASE WHEN r.side = 'BUY' THEN 1 ELSE 0 END) AS buy_count,
            SUM(CASE WHEN r.side = 'BUY' THEN r.quantity ELSE 0 END) AS buy_quantity,
            SUM(CASE WHEN r.side = 'BUY' THEN r.gross_amount ELSE 0 END) AS invested,
            SUM(CASE WHEN r.side = 'SELL' THEN 1 ELSE 0 END) AS sell_count,
            SUM(CASE WHEN r.side = 'SELL' THEN r.quantity ELSE 0 END) AS sell_quantity,
            SUM(CASE WHEN r.side = 'SELL' THEN r.gross_amount ELSE 0 END) AS sold_amount,
            SUM(r.realized_pnl) AS realized_pnl
        FROM theory_trade_records r
        LEFT JOIN instruments i ON i.symbol = r.symbol
        WHERE r.project_id = ? AND substr(r.recorded_at, 1, 7) = ?
        GROUP BY r.symbol
        ORDER BY r.symbol
        """,
        (project_id, month),
    )
    details = []
    for row in rows:
        position = positions.get(row["symbol"])
        current_quantity = int(position["quantity"]) if position else 0
        unrealized = float(position["unrealized_pnl"]) if position else 0.0
        realized = float(row["realized_pnl"] or 0)
        invested = float(row["invested"] or 0)
        total_pnl = realized + unrealized
        details.append(
            {
                "股票代码": row["symbol"],
                "股票名称": row["name"],
                "买入次数": int(row["buy_count"] or 0),
                "买入股数": int(row["buy_quantity"] or 0),
                "累计投入": invested,
                "当前仓位": float(position["position_pct"]) if position else 0.0,
                "卖出次数": int(row["sell_count"] or 0),
                "卖出股数": int(row["sell_quantity"] or 0),
                "卖出金额": float(row["sold_amount"] or 0),
                "已实现盈亏": realized,
                "未实现盈亏": unrealized,
                "总盈亏": total_pnl,
                "收益率": total_pnl / invested if invested else None,
                "当前状态": "持仓中" if current_quantity > 0 else "已清仓",
            }
        )
    total_invested = sum(row["累计投入"] for row in details)
    total_pnl = sum(row["总盈亏"] for row in details)
    return {
        "month": month,
        "details": details,
        "stock_count": len(details),
        "buy_count": sum(row["买入次数"] for row in details),
        "sell_count": sum(row["卖出次数"] for row in details),
        "invested": total_invested,
        "pnl": total_pnl,
        "return_rate": total_pnl / total_invested if total_invested else None,
        "account": account,
    }
