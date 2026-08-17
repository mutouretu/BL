from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import db
import paper_db


DEFAULT_INITIAL_CASH = 100_000.0


@dataclass(frozen=True)
class ExecutionPreview:
    signal_id: int
    account_id: int
    side: str
    equity_before: float
    current_quantity: float
    target_quantity: float
    order_quantity: float
    simulated_price: float
    estimated_fees: float
    cash_after: float
    reject_reason: str | None = None


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def next_trade_date(value: str) -> str:
    current = date.fromisoformat(value)
    current += timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current.isoformat()


def signal_fingerprint(
    project_id: int, symbol: str, signal_time: str, action: str, raw_text: str = ""
) -> str:
    payload = f"{project_id}|{symbol.upper()}|{signal_time}|{action.upper()}|{raw_text.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_demo_project(name: str = "观复模拟交易 Demo") -> tuple[int, int]:
    paper_db.migrate()
    with db.get_connection() as conn:
        project = conn.execute(
            "SELECT id FROM paper_projects WHERE name = ?", (name,)
        ).fetchone()
        if project is None:
            cursor = conn.execute(
                "INSERT INTO paper_projects (name, market, created_at) VALUES (?, 'A股', ?)",
                (name, now_iso()),
            )
            project_id = int(cursor.lastrowid)
        else:
            project_id = int(project["id"])

        account = conn.execute(
            "SELECT id FROM paper_accounts WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if account is None:
            account_id = _create_account(conn, project_id, "系统模拟账户")
        else:
            account_id = int(account["id"])
    return project_id, account_id


def seed_paper_demo_if_empty() -> bool:
    project_id, _ = create_demo_project()
    if list_signals(project_id):
        return False
    create_signal(
        project_id=project_id,
        trade_date="2026-07-22",
        signal_time="2026-07-22 09:43:00",
        symbol="300377.SZ",
        name="赢时胜",
        action="BUY",
        target_position=0.25,
        reference_price=13.98,
        predicted_high=14.20,
        predicted_low=13.72,
        signal_type="B / ①④",
        raw_text="盘中出现 B 信号，建议目标仓位 25%",
    )
    upsert_market_daily("2026-07-22", "300377.SZ", 14.20, 13.72, 13.93)
    return True


def _create_account(
    conn, project_id: int, name: str, initial_cash: float = DEFAULT_INITIAL_CASH
) -> int:
    created_at = now_iso()
    cursor = conn.execute(
        """
        INSERT INTO paper_accounts (
            project_id, name, initial_cash, cash_balance, currency, created_at
        ) VALUES (?, ?, ?, ?, 'CNY', ?)
        """,
        (project_id, name, initial_cash, initial_cash, created_at),
    )
    account_id = int(cursor.lastrowid)
    conn.execute(
        """
        INSERT INTO paper_cash_ledger (
            account_id, event_type, amount, balance_after, note, occurred_at
        ) VALUES (?, 'INITIAL_DEPOSIT', ?, ?, 'Demo 期初资金', ?)
        """,
        (account_id, initial_cash, initial_cash, created_at),
    )
    return account_id


def create_signal(
    project_id: int,
    trade_date: str,
    signal_time: str,
    symbol: str,
    name: str,
    action: str,
    target_position: float | None,
    reference_price: float | None,
    raw_text: str = "",
    signal_type: str = "",
    predicted_high: float | None = None,
    predicted_low: float | None = None,
    allocation_ratio: float | None = None,
    allocation_basis: str | None = None,
) -> int:
    normalized_action = action.strip().upper()
    if normalized_action not in {"BUY", "ADD", "REDUCE", "SELL", "WATCH"}:
        raise ValueError("不支持的信号动作。")
    if target_position is not None and not 0 <= float(target_position) <= 1:
        raise ValueError("目标仓位必须在 0% 到 100% 之间。")
    if normalized_action != "WATCH" and (reference_price is None or reference_price <= 0):
        raise ValueError("交易信号必须提供有效参考价。")
    if allocation_ratio is not None and not 0 < float(allocation_ratio) <= 1:
        raise ValueError("操作比例必须在 0% 到 100% 之间。")
    normalized_basis = allocation_basis.strip().upper() if allocation_basis else None
    if normalized_basis not in {None, "CASH_POOL", "STOCK_POSITION"}:
        raise ValueError("不支持的操作比例基准。")
    normalized_symbol = symbol.strip().upper()
    fingerprint = signal_fingerprint(
        project_id, normalized_symbol, signal_time, normalized_action, raw_text
    )
    created_at = now_iso()
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM paper_signals WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if existing is not None:
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO paper_signals (
                project_id, trade_date, signal_time, symbol, name, action,
                target_position, allocation_ratio, allocation_basis, reference_price,
                predicted_high, predicted_low,
                signal_type, raw_text, fingerprint, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'VALID', ?)
            """,
            (
                project_id,
                trade_date,
                signal_time,
                normalized_symbol,
                name.strip(),
                normalized_action,
                target_position,
                allocation_ratio,
                normalized_basis,
                reference_price,
                predicted_high,
                predicted_low,
                signal_type.strip(),
                raw_text.strip(),
                fingerprint,
                created_at,
            ),
        )
        return int(cursor.lastrowid)


def set_signal_allocation(
    signal_id: int, allocation_ratio: float, allocation_basis: str
) -> None:
    """Attach the user's requested sizing rule to a simulated signal."""
    if not 0 < float(allocation_ratio) <= 1:
        raise ValueError("操作比例必须在 0% 到 100% 之间。")
    basis = allocation_basis.strip().upper()
    if basis not in {"CASH_POOL", "STOCK_POSITION"}:
        raise ValueError("不支持的操作比例基准。")
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE paper_signals
            SET allocation_ratio = ?, allocation_basis = ?
            WHERE id = ?
            """,
            (float(allocation_ratio), basis, signal_id),
        )


def list_projects():
    return paper_db.rows("SELECT * FROM paper_projects ORDER BY id")


def list_signals(project_id: int | None = None):
    query = "SELECT * FROM paper_signals"
    params: tuple = ()
    if project_id is not None:
        query += " WHERE project_id = ?"
        params = (project_id,)
    return paper_db.rows(query + " ORDER BY signal_time DESC, id DESC", params)


def latest_price(conn, symbol: str, fallback: float = 0) -> float:
    market = conn.execute(
        "SELECT close FROM paper_market_daily WHERE symbol = ? AND close IS NOT NULL ORDER BY trade_date DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    if market is not None:
        return float(market["close"])
    fill = conn.execute(
        "SELECT price FROM paper_fills WHERE symbol = ? ORDER BY fill_time DESC, id DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    return float(fill["price"]) if fill is not None else float(fallback)


def account_summary(account_id: int) -> dict:
    with db.get_connection() as conn:
        account = conn.execute(
            "SELECT * FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if account is None:
            raise ValueError("账户不存在。")
        positions = conn.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? AND quantity > 0",
            (account_id,),
        ).fetchall()
        market_value = 0.0
        unrealized = 0.0
        realized = 0.0
        for position in positions:
            mark = latest_price(conn, position["symbol"], position["cost_total"] / position["quantity"])
            market_value += mark * float(position["quantity"])
            unrealized += mark * float(position["quantity"]) - float(position["cost_total"])
            realized += float(position["realized_pnl"])
        extra_realized = conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) AS value FROM paper_positions WHERE account_id = ? AND quantity = 0",
            (account_id,),
        ).fetchone()
        realized += float(extra_realized["value"])
        equity = float(account["cash_balance"]) + market_value
        return {
            "account_id": account_id,
            "name": account["name"],
            "cash": float(account["cash_balance"]),
            "market_value": market_value,
            "equity": equity,
            "position_pct": market_value / equity if equity > 0 else 0,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": equity - float(account["initial_cash"]),
        }


def position_rows(account_id: int) -> list[dict]:
    with db.get_connection() as conn:
        positions = conn.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? ORDER BY symbol",
            (account_id,),
        ).fetchall()
        result = []
        for position in positions:
            quantity = float(position["quantity"])
            cost_total = float(position["cost_total"])
            mark = latest_price(conn, position["symbol"], cost_total / quantity if quantity else 0)
            available = conn.execute(
                """
                SELECT COALESCE(SUM(remaining_quantity), 0) AS value
                FROM paper_position_lots
                WHERE account_id = ? AND symbol = ? AND available_date <= date('now', 'localtime')
                """,
                (account_id, position["symbol"]),
            ).fetchone()
            result.append(
                {
                    "标的": position["symbol"],
                    "持仓数量": quantity,
                    "可卖数量": float(available["value"]),
                    "平均成本": cost_total / quantity if quantity else 0,
                    "最新价": mark,
                    "市值": quantity * mark,
                    "未实现盈亏": quantity * mark - cost_total,
                    "已实现盈亏": float(position["realized_pnl"]),
                }
            )
        return result


def preview_execution(signal_id: int, account_id: int, slippage_bps: float = 5) -> ExecutionPreview:
    with db.get_connection() as conn:
        signal = conn.execute(
            "SELECT * FROM paper_signals WHERE id = ?", (signal_id,)
        ).fetchone()
        account = conn.execute(
            "SELECT * FROM paper_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if signal is None or account is None:
            raise ValueError("信号或账户不存在。")
        position = conn.execute(
            "SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?",
            (account_id, signal["symbol"]),
        ).fetchone()
        current_qty = float(position["quantity"]) if position else 0.0
        summary = account_summary(account_id)
        side = "BUY" if signal["action"] in {"BUY", "ADD"} else "SELL"
        reference = float(signal["reference_price"])
        simulated_price = reference * (
            1 + slippage_bps / 10_000 if side == "BUY" else 1 - slippage_bps / 10_000
        )
        target_position = signal["target_position"]
        if signal["action"] == "SELL":
            target_position = 0.0
        if target_position is None:
            return ExecutionPreview(
                signal_id, account_id, side, summary["equity"], current_qty, current_qty,
                0, simulated_price, 0, summary["cash"], "MISSING_TARGET_POSITION"
            )
        target_value = summary["equity"] * float(target_position)
        target_qty = math.floor(target_value / simulated_price / 100) * 100
        delta = target_qty - current_qty
        calculated_side = "BUY" if delta > 0 else "SELL"
        quantity = abs(delta)
        if quantity <= 0:
            return ExecutionPreview(
                signal_id, account_id, calculated_side, summary["equity"], current_qty,
                target_qty, 0, simulated_price, 0, summary["cash"], "NO_POSITION_CHANGE"
            )
        if calculated_side != side and signal["action"] != "SELL":
            return ExecutionPreview(
                signal_id, account_id, calculated_side, summary["equity"], current_qty,
                target_qty, quantity, simulated_price, 0, summary["cash"], "ACTION_CONFLICT"
            )
        commission = max(5.0, quantity * simulated_price * 0.0003)
        tax = quantity * simulated_price * 0.0005 if calculated_side == "SELL" else 0
        fees = commission + tax
        cash_after = summary["cash"] - quantity * simulated_price - fees
        if calculated_side == "SELL":
            cash_after = summary["cash"] + quantity * simulated_price - fees
            available = _available_quantity(conn, account_id, signal["symbol"], signal["trade_date"])
            if quantity > available + 1e-8:
                return ExecutionPreview(
                    signal_id, account_id, calculated_side, summary["equity"], current_qty,
                    target_qty, quantity, simulated_price, fees, cash_after, "T1_AVAILABLE_INSUFFICIENT"
                )
        if calculated_side == "BUY" and cash_after < -1e-8:
            return ExecutionPreview(
                signal_id, account_id, calculated_side, summary["equity"], current_qty,
                target_qty, quantity, simulated_price, fees, cash_after, "INSUFFICIENT_CASH"
            )
        return ExecutionPreview(
            signal_id, account_id, calculated_side, summary["equity"], current_qty,
            target_qty, quantity, simulated_price, fees, cash_after
        )


def execute_paper_signal(signal_id: int, account_id: int, slippage_bps: float = 5) -> int:
    preview = preview_execution(signal_id, account_id, slippage_bps)
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM paper_orders WHERE account_id = ? AND signal_id = ?",
            (account_id, signal_id),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])
        created_at = now_iso()
        status = "REJECTED" if preview.reject_reason else "SUBMITTED"
        cursor = conn.execute(
            """
            INSERT INTO paper_orders (
                account_id, signal_id, side, order_type, order_price, order_quantity,
                status, reject_reason, submitted_at, created_at
            ) VALUES (?, ?, ?, 'MARKET_SIM', ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                signal_id,
                preview.side,
                preview.simulated_price,
                preview.order_quantity,
                status,
                preview.reject_reason,
                created_at,
                created_at,
            ),
        )
        order_id = int(cursor.lastrowid)
        if preview.reject_reason:
            _audit(conn, "ORDER", order_id, "REJECT", preview.reject_reason, "SYSTEM")
            return order_id
        signal = conn.execute(
            "SELECT * FROM paper_signals WHERE id = ?", (signal_id,)
        ).fetchone()
        _post_fill(
            conn,
            order_id=order_id,
            account_id=account_id,
            signal_id=signal_id,
            symbol=signal["symbol"],
            side=preview.side,
            fill_time=signal["signal_time"],
            price=preview.simulated_price,
            quantity=preview.order_quantity,
            commission=max(
                5.0, preview.order_quantity * preview.simulated_price * 0.0003
            ),
            tax=(
                preview.order_quantity * preview.simulated_price * 0.0005
                if preview.side == "SELL"
                else 0
            ),
            operator="SYSTEM",
        )
        conn.execute("UPDATE paper_orders SET status = 'FILLED' WHERE id = ?", (order_id,))
        conn.execute("UPDATE paper_signals SET status = 'EXECUTED' WHERE id = ?", (signal_id,))
        _audit(conn, "ORDER", order_id, "FILL", json.dumps(preview.__dict__, ensure_ascii=False), "SYSTEM")
        return order_id


def _available_quantity(conn, account_id: int, symbol: str, trade_date: str) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(remaining_quantity), 0) AS quantity
        FROM paper_position_lots
        WHERE account_id = ? AND symbol = ? AND available_date <= ?
        """,
        (account_id, symbol, trade_date),
    ).fetchone()
    return float(row["quantity"])


def _post_fill(
    conn,
    order_id: int,
    account_id: int,
    signal_id: int | None,
    symbol: str,
    side: str,
    fill_time: str,
    price: float,
    quantity: float,
    commission: float,
    tax: float,
    operator: str,
) -> int:
    created_at = now_iso()
    position = conn.execute(
        "SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?",
        (account_id, symbol),
    ).fetchone()
    current_qty = float(position["quantity"]) if position else 0
    cost_total = float(position["cost_total"]) if position else 0
    realized = float(position["realized_pnl"]) if position else 0
    account = conn.execute(
        "SELECT cash_balance FROM paper_accounts WHERE id = ?", (account_id,)
    ).fetchone()
    cash = float(account["cash_balance"])

    if side == "BUY":
        cash_delta = -(price * quantity + commission + tax)
        next_qty = current_qty + quantity
        next_cost = cost_total + price * quantity + commission
    else:
        if quantity > current_qty + 1e-8:
            raise ValueError("卖出数量超过持仓。")
        if quantity > _available_quantity(conn, account_id, symbol, fill_time[:10]) + 1e-8:
            raise ValueError("卖出数量超过可卖数量。")
        average_cost = cost_total / current_qty if current_qty else 0
        net_proceeds = price * quantity - commission - tax
        cash_delta = net_proceeds
        next_qty = current_qty - quantity
        next_cost = max(0.0, cost_total - average_cost * quantity)
        realized += net_proceeds - average_cost * quantity
        _consume_available_lots(conn, account_id, symbol, fill_time[:10], quantity)

    next_cash = cash + cash_delta
    if next_cash < -1e-8:
        raise ValueError("成交后现金不能为负。")
    fill = conn.execute(
        """
        INSERT INTO paper_fills (
            order_id, account_id, signal_id, symbol, side, fill_time, price,
            quantity, commission, tax, operator, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            account_id,
            signal_id,
            symbol,
            side,
            fill_time,
            price,
            quantity,
            commission,
            tax,
            operator,
            created_at,
        ),
    )
    fill_id = int(fill.lastrowid)
    if side == "BUY":
        conn.execute(
            """
            INSERT INTO paper_position_lots (
                account_id, symbol, source_fill_id, remaining_quantity, available_date, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                symbol,
                fill_id,
                quantity,
                next_trade_date(fill_time[:10]),
                created_at,
            ),
        )
    conn.execute(
        """
        INSERT INTO paper_positions (
            account_id, symbol, quantity, cost_total, realized_pnl, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, symbol) DO UPDATE SET
            quantity = excluded.quantity,
            cost_total = excluded.cost_total,
            realized_pnl = excluded.realized_pnl,
            updated_at = excluded.updated_at
        """,
        (account_id, symbol, next_qty, next_cost, realized, created_at),
    )
    conn.execute(
        "UPDATE paper_accounts SET cash_balance = ? WHERE id = ?", (next_cash, account_id)
    )
    conn.execute(
        """
        INSERT INTO paper_cash_ledger (
            account_id, event_type, amount, balance_after, fill_id, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            "BUY_SETTLEMENT" if side == "BUY" else "SELL_SETTLEMENT",
            cash_delta,
            next_cash,
            fill_id,
            fill_time,
        ),
    )
    return fill_id


def _consume_available_lots(
    conn, account_id: int, symbol: str, trade_date: str, quantity: float
) -> None:
    remaining = quantity
    lots = conn.execute(
        """
        SELECT * FROM paper_position_lots
        WHERE account_id = ? AND symbol = ? AND available_date <= ? AND remaining_quantity > 0
        ORDER BY available_date, id
        """,
        (account_id, symbol, trade_date),
    ).fetchall()
    for lot in lots:
        consumed = min(remaining, float(lot["remaining_quantity"]))
        conn.execute(
            "UPDATE paper_position_lots SET remaining_quantity = remaining_quantity - ? WHERE id = ?",
            (consumed, lot["id"]),
        )
        remaining -= consumed
        if remaining <= 1e-8:
            break
    if remaining > 1e-8:
        raise ValueError("可卖批次数量不足。")


def upsert_market_daily(
    trade_date: str, symbol: str, high: float | None, low: float | None, close: float | None
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO paper_market_daily (
                trade_date, symbol, high, low, close, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'STUB', ?)
            ON CONFLICT(trade_date, symbol) DO UPDATE SET
                high = excluded.high, low = excluded.low, close = excluded.close,
                source = excluded.source, updated_at = excluded.updated_at
            """,
            (trade_date, symbol.upper(), high, low, close, now_iso()),
        )


def order_rows(project_id: int | None = None):
    query = """
        SELECT o.*, s.symbol, s.signal_time
        FROM paper_orders o
        JOIN paper_accounts a ON a.id = o.account_id
        LEFT JOIN paper_signals s ON s.id = o.signal_id
    """
    params: tuple = ()
    if project_id is not None:
        query += " WHERE a.project_id = ?"
        params = (project_id,)
    return paper_db.rows(query + " ORDER BY o.id DESC", params)


def fill_rows(account_id: int | None = None):
    if account_id is None:
        return paper_db.rows("SELECT * FROM paper_fills ORDER BY fill_time DESC, id DESC")
    return paper_db.rows(
        "SELECT * FROM paper_fills WHERE account_id = ? ORDER BY fill_time DESC, id DESC",
        (account_id,),
    )


def trade_history_instruments(project_id: int) -> list[dict]:
    """List stocks available on the per-instrument operation history page."""
    rows = paper_db.rows(
        """
        SELECT symbol, MAX(name) AS name, MAX(has_trade) AS has_trade
        FROM (
            SELECT i.symbol, i.name, 0 AS has_trade
            FROM tracked_instruments t
            JOIN instruments i ON i.id = t.instrument_id
            WHERE t.project_id = ?

            UNION ALL

            SELECT f.symbol, COALESCE(s.name, i.name, f.symbol) AS name, 1 AS has_trade
            FROM paper_fills f
            JOIN paper_accounts a ON a.id = f.account_id
            LEFT JOIN paper_signals s ON s.id = f.signal_id
            LEFT JOIN instruments i ON i.symbol = f.symbol
            WHERE a.project_id = ?
        ) stocks
        GROUP BY symbol
        ORDER BY has_trade DESC, symbol
        """,
        (project_id, project_id),
    )
    return [dict(row) for row in rows]


def trade_history(project_id: int, symbol: str) -> list[dict]:
    """Return completed simulated trades for one stock in reverse time order."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("股票代码不能为空。")
    rows = paper_db.rows(
        """
        SELECT
            f.id AS fill_id,
            o.id AS order_id,
            f.fill_time,
            f.symbol,
            COALESCE(s.name, i.name, f.symbol) AS name,
            f.side,
            s.allocation_ratio,
            s.allocation_basis,
            f.price,
            f.quantity,
            f.price * f.quantity AS gross_amount,
            f.commission,
            f.tax,
            f.commission + f.tax AS total_fees,
            CASE
                WHEN f.side = 'BUY'
                    THEN -(f.price * f.quantity + f.commission + f.tax)
                ELSE f.price * f.quantity - f.commission - f.tax
            END AS cash_change,
            f.operator,
            o.status AS order_status
        FROM paper_fills f
        JOIN paper_accounts a ON a.id = f.account_id
        JOIN paper_orders o ON o.id = f.order_id
        LEFT JOIN paper_signals s ON s.id = f.signal_id
        LEFT JOIN instruments i ON i.symbol = f.symbol
        WHERE a.project_id = ?
        ORDER BY f.fill_time, f.id
        """,
        (project_id,),
    )
    cash_row = paper_db.row(
        """
        SELECT initial_cash FROM paper_accounts
        WHERE project_id = ? AND is_active = 1
        ORDER BY id LIMIT 1
        """,
        (project_id,),
    )
    cash = float(cash_row["initial_cash"]) if cash_row is not None else 0.0
    quantities: dict[str, float] = {}
    marks: dict[str, float] = {}
    history: list[dict] = []
    for row in rows:
        item = dict(row)
        equity_before = cash + sum(
            quantity * marks.get(item_symbol, 0.0)
            for item_symbol, quantity in quantities.items()
        )
        gross_amount = float(item["gross_amount"])
        item["capital_ratio"] = gross_amount / equity_before if equity_before > 0 else 0.0
        price = float(item["price"])
        quantity = float(item["quantity"])
        symbol_key = item["symbol"]
        marks[symbol_key] = price
        if item["side"] == "BUY":
            cash -= gross_amount + float(item["commission"]) + float(item["tax"])
            quantities[symbol_key] = quantities.get(symbol_key, 0.0) + quantity
        else:
            cash += gross_amount - float(item["commission"]) - float(item["tax"])
            quantities[symbol_key] = quantities.get(symbol_key, 0.0) - quantity
        if symbol_key == normalized_symbol:
            history.append(item)
    return list(reversed(history))


def _audit(conn, entity_type: str, entity_id: int, action: str, detail: str, operator: str):
    conn.execute(
        """
        INSERT INTO paper_audit_events (
            entity_type, entity_id, action, detail, operator, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (entity_type, entity_id, action, detail, operator, now_iso()),
    )
