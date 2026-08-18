from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import sqlite3

import db
import paper_db


@dataclass(frozen=True)
class CapitalResizeResult:
    project_id: int
    account_id: int
    old_initial_cash: float
    target_initial_cash: float
    scale_factor: float
    applied: bool
    backup_path: str | None
    trade_record_count: int
    cash_ledger_count: int
    position_count: int
    lot_count: int


def _count(conn: sqlite3.Connection, query: str, params: tuple) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0] if row is not None else 0)


def _backup_database(conn: sqlite3.Connection, database_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = database_path.with_name(
        f"{database_path.name}.pre-capital-resize-{timestamp}.bak"
    )
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)
    return backup_path


def resize_theory_capital(
    project_id: int,
    target_initial_cash: float,
    *,
    apply: bool = False,
    backup: bool = True,
    db_path: str | Path | None = None,
) -> CapitalResizeResult:
    """Scale an existing theory account to a new total capital base.

    Prices, allocation ratios, and capital ratios remain unchanged. Historical
    cash, amounts, quantities, positions, lots, and realized PnL are scaled by
    the same factor so existing statistics keep their proportions.
    """

    if target_initial_cash <= 0:
        raise ValueError("目标理论总资金必须大于 0。")
    original_db_path = db.DB_PATH
    if db_path is not None:
        db.DB_PATH = Path(db_path)
    try:
        paper_db.migrate()
        with db.get_connection() as conn:
            account = conn.execute(
                """
                SELECT id, initial_cash
                FROM theory_accounts
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            if account is None:
                raise ValueError(f"未找到 project_id={project_id} 的理论账户。")
            account_id = int(account["id"])
            old_initial = float(account["initial_cash"])
            if old_initial <= 0:
                raise ValueError("当前理论账户期初资金异常，不能按比例放大。")

            scale_factor = float(target_initial_cash) / old_initial
            integer_factor = round(scale_factor)
            if not math.isclose(scale_factor, integer_factor, rel_tol=0, abs_tol=1e-9):
                raise ValueError(
                    "目标资金不是当前期初资金的整数倍，直接缩放会破坏股数整数。"
                )

            counts = {
                "trade_record_count": _count(
                    conn,
                    "SELECT COUNT(*) FROM theory_trade_records WHERE account_id = ?",
                    (account_id,),
                ),
                "cash_ledger_count": _count(
                    conn,
                    "SELECT COUNT(*) FROM theory_cash_ledger WHERE account_id = ?",
                    (account_id,),
                ),
                "position_count": _count(
                    conn,
                    "SELECT COUNT(*) FROM theory_positions WHERE account_id = ?",
                    (account_id,),
                ),
                "lot_count": _count(
                    conn,
                    "SELECT COUNT(*) FROM theory_position_lots WHERE account_id = ?",
                    (account_id,),
                ),
            }
            if not apply:
                return CapitalResizeResult(
                    project_id=project_id,
                    account_id=account_id,
                    old_initial_cash=old_initial,
                    target_initial_cash=float(target_initial_cash),
                    scale_factor=scale_factor,
                    applied=False,
                    backup_path=None,
                    **counts,
                )

            database_path = Path(db.DB_PATH)
            backup_path = None
            if backup and str(database_path) != ":memory:":
                backup_path = _backup_database(conn, database_path)

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("BEGIN")
            conn.execute(
                """
                UPDATE theory_accounts
                SET initial_cash = ?,
                    cash_balance = cash_balance * ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (float(target_initial_cash), scale_factor, now, account_id),
            )
            conn.execute(
                """
                UPDATE theory_trade_records
                SET quantity = quantity * ?,
                    gross_amount = gross_amount * ?,
                    cash_change = cash_change * ?,
                    equity_before = equity_before * ?,
                    cash_before = cash_before * ?,
                    position_before = position_before * ?,
                    realized_pnl = realized_pnl * ?
                WHERE account_id = ?
                """,
                (
                    integer_factor,
                    scale_factor,
                    scale_factor,
                    scale_factor,
                    scale_factor,
                    integer_factor,
                    scale_factor,
                    account_id,
                ),
            )
            conn.execute(
                """
                UPDATE theory_cash_ledger
                SET amount = amount * ?,
                    balance_after = balance_after * ?
                WHERE account_id = ?
                """,
                (scale_factor, scale_factor, account_id),
            )
            conn.execute(
                """
                UPDATE theory_positions
                SET quantity = quantity * ?,
                    cost_total = cost_total * ?,
                    realized_pnl = realized_pnl * ?,
                    updated_at = ?
                WHERE account_id = ?
                """,
                (integer_factor, scale_factor, scale_factor, now, account_id),
            )
            conn.execute(
                """
                UPDATE theory_position_lots
                SET remaining_quantity = remaining_quantity * ?
                WHERE account_id = ?
                """,
                (integer_factor, account_id),
            )
            conn.commit()

            return CapitalResizeResult(
                project_id=project_id,
                account_id=account_id,
                old_initial_cash=old_initial,
                target_initial_cash=float(target_initial_cash),
                scale_factor=scale_factor,
                applied=True,
                backup_path=str(backup_path) if backup_path is not None else None,
                **counts,
            )
    finally:
        db.DB_PATH = original_db_path
