from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import theory_capital  # noqa: E402


def _money(value: float) -> str:
    return f"{value:,.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="按比例放大或缩小已有理论账户、交易记录、持仓和现金流水。"
    )
    parser.add_argument(
        "--db",
        default="guanfu_trade_manager.sqlite3",
        help="SQLite 数据库路径，默认 guanfu_trade_manager.sqlite3。",
    )
    parser.add_argument(
        "--project-id",
        type=int,
        default=1,
        help="paper_projects.id，默认 1。",
    )
    parser.add_argument(
        "--target-cash",
        type=float,
        default=10_000_000.0,
        help="目标理论总资金，默认 10000000。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写入数据库；不加时只预览。",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="写入前不生成数据库备份。默认会备份。",
    )
    args = parser.parse_args()

    result = theory_capital.resize_theory_capital(
        args.project_id,
        args.target_cash,
        apply=args.apply,
        backup=not args.no_backup,
        db_path=args.db,
    )
    mode = "已执行" if result.applied else "预览"
    print(f"[{mode}] project_id={result.project_id}, account_id={result.account_id}")
    print(
        "理论总资金: "
        f"{_money(result.old_initial_cash)} -> {_money(result.target_initial_cash)}"
    )
    print(f"缩放倍数: {result.scale_factor:g}x")
    print(
        "影响记录: "
        f"交易 {result.trade_record_count} 条, "
        f"现金流水 {result.cash_ledger_count} 条, "
        f"持仓 {result.position_count} 条, "
        f"持仓批次 {result.lot_count} 条"
    )
    if result.backup_path:
        print(f"备份文件: {result.backup_path}")
    if not result.applied:
        print("当前未写入数据库；确认无误后加 --apply 执行。")


if __name__ == "__main__":
    main()
