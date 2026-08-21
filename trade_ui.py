from __future__ import annotations

import html
from datetime import date, datetime
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

import paper_services
import tracking_services
import theory_fixtures
import theory_services


ACTION_LABELS = {
    "买入": "BUY",
    "加仓": "ADD",
    "减仓": "REDUCE",
    "卖出/清仓": "SELL",
    "观察": "WATCH",
}

ACTION_TEXT = {
    "BUY": "买入",
    "ADD": "加仓",
    "WATCH": "观察",
    "REDUCE": "减仓",
    "SELL": "卖出/清仓",
}

TRACKING_STATUS_TEXT = {
    "PENDING": "待确认",
    "CONFIRMED": "已确认",
    "IGNORED": "已忽略",
    "SIGNALLED": "已转信号",
}

MARKET_UP_COLOR = "#FCA5A5"
MARKET_DOWN_COLOR = "#86EFAC"
MARKET_FLAT_COLOR = "#B6BEC9"

SIGNAL_STATUS_TEXT = {
    "RECORDED": "仅记录",
    "PENDING_RULE": "待规则判断",
    "ORDER_CREATED": "已生成模拟订单",
    "DUPLICATE_RECORDED": "重复信号已留痕",
    "IGNORED": "已忽略",
    "REJECTED": "处理失败",
}


def recommendation_action_style(value: object) -> str:
    action = str(value)
    if action in {"买入", "加仓"}:
        return (
            "background-color: rgba(56, 189, 248, 0.22); "
            "color: #7DD3FC; font-weight: 750;"
        )
    if action in {"减仓", "卖出", "卖出/清仓"}:
        return (
            "background-color: rgba(246, 196, 83, 0.22); "
            "color: #FCD34D; font-weight: 750;"
        )
    return (
        "background-color: rgba(146, 155, 170, 0.12); "
        "color: #B6BEC9; font-weight: 650;"
    )


def recommendation_action_class(action: object) -> str:
    if str(action) in {"买入", "加仓"}:
        return "buy"
    if str(action) in {"减仓", "卖出", "卖出/清仓"}:
        return "sell"
    return "watch"


def _number_text(value: object, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}"


def _position_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.1%}"


def _pnl_ratio_text(value: object) -> str:
    if value is None or pd.isna(value):
        return "-"
    ratio = float(value)
    if ratio > 0:
        color = MARKET_UP_COLOR
    elif ratio < 0:
        color = MARKET_DOWN_COLOR
    else:
        color = MARKET_FLAT_COLOR
    return f'<span style="color:{color};font-weight:700;">{ratio:+.1%}</span>'


def _reset_operation_history_page() -> None:
    st.session_state["operation_history_page_number"] = 1


def _set_operation_history_page(page: int) -> None:
    st.session_state["operation_history_page_number"] = page


def render_recommendation_table(frame: pd.DataFrame) -> None:
    headers = [
        "股票代码",
        "股票名称",
        "荐股日期",
        "荐股时间",
        "信号标签",
        "操作建议",
        "建议仓位",
        "参考价",
        "预测最低",
        "预测最高",
        "最高点提示",
        "处理状态",
        "原始说明",
    ]
    rows = []
    for _, row in frame.iterrows():
        query = urlencode({"page": "操作历史", "symbol": row["股票代码"]})
        cells = [
            (
                f'<a class="beili-stock-link" href="?{query}" target="_self">'
                f'{html.escape(str(row["股票代码"]))}</a>'
            ),
            html.escape(str(row["股票名称"])),
            html.escape(str(row["荐股日期"])),
            html.escape(str(row["荐股时间"])),
            html.escape(str(row["信号标签"])),
            (
                f'<span class="beili-action {recommendation_action_class(row["操作建议"])}">'
                f'{html.escape(str(row["操作建议"]))}</span>'
            ),
            _position_text(row["建议仓位"]),
            _number_text(row["参考价"]),
            _number_text(row["预测最低"]),
            _number_text(row["预测最高"]),
            html.escape(str(row["最高点提示"])),
            html.escape(str(row["处理状态"])),
            html.escape(str(row["原始说明"])),
        ]
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    if not rows:
        rows.append(
            '<tr><td colspan="13" style="text-align:center;color:var(--beili-muted);">'
            "暂无符合条件的股票</td></tr>"
        )
    markup = (
        '<div class="beili-table-wrap"><table class="beili-table"><thead><tr>'
        + "".join(f"<th>{header}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )
    st.markdown(markup, unsafe_allow_html=True)


def _run_tracking_action(action, success_message) -> None:
    try:
        result = action()
        st.session_state["tracking_save_notice"] = (
            success_message(result) if callable(success_message) else success_message
        )
    except ValueError as exc:
        st.session_state["tracking_action_error"] = str(exc)
    st.rerun()


def _trade_price_hint(current_price: object) -> str:
    current_price_text = _number_text(current_price)
    if current_price_text == "-":
        return "请输入成交价格"
    return f"请输入成交价格，如 {current_price_text}"


@st.dialog("买入", icon=":material/add_shopping_cart:")
def render_buy_dialog(
    project_id: int,
    symbol: str,
    name: str,
    current_price: object,
) -> None:
    st.caption(f"{symbol} · {name} · 按账户剩余现金计算")
    buy_ratio = st.segmented_control(
        "买入比例",
        options=(0.10, 0.40, 0.50, 1.00),
        default=None,
        format_func=lambda value: f"{value:.0%}",
        key=f"tracking_buy_ratio_{symbol}",
        width="stretch",
    )
    buy_price = st.number_input(
        "买入价格",
        min_value=0.01,
        value=None,
        step=0.01,
        format="%.2f",
        placeholder=_trade_price_hint(current_price),
        icon=":material/payments:",
        key=f"tracking_buy_price_{symbol}",
    )
    buy_preview = None
    if buy_ratio is not None and buy_price is not None:
        try:
            buy_preview = theory_services.preview_record(
                project_id,
                symbol,
                "BUY",
                buy_ratio,
                reference_price=buy_price,
                price_source="手工录入",
            )
            st.caption(
                f"成交价 {buy_preview.reference_price:.2f} · "
                f"买入 {buy_preview.quantity:,} 股 · "
                f"金额 {money(buy_preview.gross_amount)} · "
                f"总仓占比 {buy_preview.capital_ratio:.1%}"
            )
        except ValueError as exc:
            st.warning(str(exc))
    if st.button(
        "买入",
        type="primary",
        icon=":material/check:",
        disabled=buy_preview is None,
        key=f"tracking_buy_confirm_{symbol}",
        width="stretch",
    ):
        _run_tracking_action(
            lambda: theory_services.create_record(
                project_id,
                symbol,
                "BUY",
                buy_ratio,
                reference_price=buy_price,
                price_source="手工录入",
            ),
            f"{name} 买入记录已保存。",
        )


@st.dialog("卖出", icon=":material/sell:")
def render_sell_dialog(
    project_id: int,
    symbol: str,
    name: str,
    current_price: object,
) -> None:
    st.caption(f"{symbol} · {name} · 按该股票当前持仓计算")
    sell_ratio = st.segmented_control(
        "卖出比例",
        options=(0.50, 1.00),
        default=None,
        format_func=lambda value: f"{value:.0%}",
        key=f"tracking_sell_ratio_{symbol}",
        width="stretch",
    )
    sell_price = st.number_input(
        "卖出价格",
        min_value=0.01,
        value=None,
        step=0.01,
        format="%.2f",
        placeholder=_trade_price_hint(current_price),
        icon=":material/payments:",
        key=f"tracking_sell_price_{symbol}",
    )
    sell_preview = None
    if sell_ratio is not None and sell_price is not None:
        try:
            sell_preview = theory_services.preview_record(
                project_id,
                symbol,
                "SELL",
                sell_ratio,
                reference_price=sell_price,
                price_source="手工录入",
            )
            st.caption(
                f"成交价 {sell_preview.reference_price:.2f} · "
                f"卖出 {sell_preview.quantity:,} 股 · "
                f"金额 {money(sell_preview.gross_amount)} · "
                f"总仓占比 {sell_preview.capital_ratio:.1%}"
            )
        except ValueError as exc:
            st.warning(str(exc))
    if st.button(
        "卖出",
        type="primary",
        icon=":material/check:",
        disabled=sell_preview is None,
        key=f"tracking_sell_confirm_{symbol}",
        width="stretch",
    ):
        _run_tracking_action(
            lambda: theory_services.create_record(
                project_id,
                symbol,
                "SELL",
                sell_ratio,
                reference_price=sell_price,
                price_source="手工录入",
            ),
            f"{name} 卖出记录已保存。",
        )


def render_tracking_table(frame: pd.DataFrame, project_id: int) -> None:
    ratios = [1.42, 1.20, 0.76, 0.78, 0.82, 0.82, 2.15]
    header = st.columns(ratios, vertical_alignment="center")
    for column, label in zip(
        header[:6],
        [
            "股票",
            "荐股时间",
            "当前仓位",
            "当前价格",
            "买入均价",
            "盈亏比例",
        ],
    ):
        column.markdown(f"**{label}**")
    action_header = header[6].columns([1, 0.34], vertical_alignment="center")
    action_header[0].markdown("**操作**")
    if action_header[1].button(
        ":material/refresh:",
        key="refresh_all_tracking_prices",
        help="刷新全部股票价格",
        width="stretch",
    ):
        _run_tracking_action(
            lambda: tracking_services.refresh_all_tracking_prices(project_id),
            lambda result: (
                f"已刷新 {result['updated_count']} 只股票价格。"
                + (
                    f"另有 {result['failed_count']} 只股票实时行情获取失败。"
                    if result["failed_count"]
                    else ""
                )
            ),
        )
    st.markdown(
        '<div style="height:1px;background:var(--beili-line);margin:-0.35rem 0 0.15rem;"></div>',
        unsafe_allow_html=True,
    )

    if frame.empty:
        st.markdown(
            '<div style="padding:1.4rem;text-align:center;color:var(--beili-muted);">'
            "暂无符合条件的股票</div>",
            unsafe_allow_html=True,
        )
        return

    for _, row in frame.iterrows():
        columns = st.columns(ratios, vertical_alignment="center")
        query = urlencode({"page": "操作历史", "symbol": row["股票代码"]})
        columns[0].markdown(
            f'<a class="beili-stock-link" href="?{query}" target="_self">'
            f'{html.escape(str(row["股票代码"]))}</a><br/>'
            f'<span style="color:var(--beili-text);">{html.escape(str(row["股票名称"]))}</span>',
            unsafe_allow_html=True,
        )
        columns[1].markdown(
            f"{html.escape(str(row['荐股日期']))}<br/>"
            f"<span style=\"color:var(--beili-muted);\">{html.escape(str(row['荐股时间']))}</span>",
            unsafe_allow_html=True,
        )
        columns[2].markdown(f"**{row['当前仓位']:.1%}**")
        columns[3].markdown(_number_text(row["当前价格"]))
        columns[4].markdown(_number_text(row["买入均价"]))
        columns[5].markdown(_pnl_ratio_text(row["盈亏比例"]), unsafe_allow_html=True)
        action_columns = columns[6].columns(5)
        if action_columns[0].button(
            ":material/add_shopping_cart:",
            help="买入",
            key=f"tracking_buy_{row['股票代码']}",
            width="stretch",
        ):
            render_buy_dialog(
                project_id,
                row["股票代码"],
                row["股票名称"],
                row["当前价格"],
            )

        has_position = float(row["当前仓位"]) > 0
        if action_columns[1].button(
            ":material/sell:",
            help="卖出" if has_position else "当前没有可卖持仓",
            disabled=not has_position,
            key=f"tracking_sell_{row['股票代码']}",
            width="stretch",
        ):
            render_sell_dialog(
                project_id,
                row["股票代码"],
                row["股票名称"],
                row["当前价格"],
            )

        with action_columns[3].popover(
            "✏️", help="编辑", key=f"tracking_edit_{row['股票代码']}"
        ):
            st.caption("编辑股票信息")
            with st.form(f"tracking_edit_form_{row['股票代码']}"):
                edited_symbol = st.text_input(
                    "股票代码", value=row["股票代码"], key=f"edit_symbol_{row['股票代码']}"
                )
                edited_name = st.text_input(
                    "股票名称", value=row["股票名称"], key=f"edit_name_{row['股票代码']}"
                )
                edit_submitted = st.form_submit_button("保存", type="primary")
            if edit_submitted:
                _run_tracking_action(
                    lambda: tracking_services.update_tracking_instrument(
                        project_id,
                        row["股票代码"],
                        edited_symbol,
                        edited_name,
                    ),
                    lambda result: f"{result['symbol']} · {result['name']} 已更新。",
                )

        with action_columns[4].popover(
            "🗑️", help="删除", key=f"tracking_delete_{row['股票代码']}"
        ):
            st.caption(f"确认从当前跟踪中删除 {row['股票代码']} · {row['股票名称']}？")
            if st.button(
                "确认删除",
                type="primary",
                key=f"confirm_delete_{row['股票代码']}",
                width="stretch",
            ):
                _run_tracking_action(
                    lambda: tracking_services.remove_tracking(
                        project_id, row["股票代码"]
                    ),
                    f"{row['股票名称']} 已从当前跟踪中删除。",
                )

        if action_columns[2].button(
            ":material/archive:",
            help="归档（保留操作历史）",
            key=f"tracking_archive_{row['股票代码']}",
            width="stretch",
        ):
            _run_tracking_action(
                lambda: tracking_services.archive_tracking(
                    project_id, row["股票代码"]
                ),
                f"{row['股票名称']} 已归档，操作历史继续保留。",
            )
        st.markdown(
            '<div style="height:1px;background:rgba(48,55,68,0.65);margin:0.05rem 0;"></div>',
            unsafe_allow_html=True,
        )


def ensure_demo() -> tuple[int, int]:
    return paper_services.create_demo_project()


def money(value: float) -> str:
    return f"¥{value:,.2f}"


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2%}"


def render_add_watching_form(project_id: int) -> None:
    st.caption("保存后进入观察中列表，荐股日期和时间自动使用当前系统时间。")
    with st.form("add_watching_form", clear_on_submit=False):
        identity = st.columns(2)
        symbol = identity[0].text_input(
            "股票代码 *", placeholder="例如：300377 或 300377.SZ"
        )
        name = identity[1].text_input("股票名称 *", placeholder="例如：赢时胜")
        submitted = st.form_submit_button("保存到观察中", type="primary")

    if submitted:
        try:
            if not symbol.strip() or not name.strip():
                raise ValueError("股票代码和股票名称不能为空。")
            tracking_services.add_watching(
                project_id=project_id,
                symbol=symbol,
                name=name,
                recommended_at=datetime.now(),
                latest_action="WATCH",
            )
            st.session_state["tracking_save_notice"] = f"{name.strip()} 已加入观察中。"
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


@st.dialog("添加观察股", icon=":material/add:")
def render_add_watching_dialog(project_id: int) -> None:
    render_add_watching_form(project_id)


def daily_recommendations_page() -> None:
    project_id, _ = ensure_demo()
    theory_services.ensure_account(project_id)
    notice = st.session_state.pop("tracking_save_notice", None)
    if notice:
        st.success(notice)
    action_error = st.session_state.pop("tracking_action_error", None)
    if action_error:
        st.error(action_error)
    st.markdown(
        '<div class="beili-note">当前跟踪用于手工记录理论买入与卖出。'
        "观察中股票保留5个自然日，已有理论持仓的股票持续保留。</div>",
        unsafe_allow_html=True,
    )

    keyword = st.text_input(
        "搜索股票",
        placeholder="输入股票代码或名称",
        key="daily_recommendation_search",
    )
    rows = tracking_services.list_tracking(
        project_id,
        states=("WATCHING", "HOLDING"),
        keyword=keyword,
    )
    summary = tracking_services.tracking_summary(project_id)
    account = theory_services.account_summary(project_id)
    position_details = theory_services.tracking_position_map(project_id)
    missing_price_symbols = [
        symbol
        for symbol, position in position_details.items()
        if position.get("price_missing")
    ]
    if missing_price_symbols:
        st.warning(
            "以下持仓缺少有效参考行情，当前暂未计入持仓市值："
            + "、".join(missing_price_symbols)
            + "。请点击表格右上方的刷新价格按钮。",
            icon=":material/warning:",
        )

    display_rows = []
    for row in rows:
        recommended = datetime.fromisoformat(row["recommended_at"])
        holding = position_details.get(row["symbol"])
        buy_average = holding["average_cost"] if holding is not None else None
        pnl_ratio = holding["pnl_ratio"] if holding is not None else None
        current_price = (
            holding["reference_price"]
            if holding is not None
            else row["reference_price"]
        )
        display_rows.append(
            {
                "荐股日期": recommended.strftime("%Y-%m-%d"),
                "荐股时间": recommended.strftime("%H:%M"),
                "股票代码": row["symbol"],
                "股票名称": row["name"],
                "操作建议": ACTION_TEXT.get(row["latest_action"], "观察"),
                "建议仓位": row["target_position"],
                "参考价": row["reference_price"],
                "预测最低": row["predicted_low"],
                "预测最高": row["predicted_high"],
                "最高点提示": row["peak_hint"] or "-",
                "处理状态": TRACKING_STATUS_TEXT.get(
                    row["processing_status"], row["processing_status"]
                ),
                "原始说明": row["raw_text"] or "",
                "管理分组": row["tracking_state"],
                "内部动作": row["latest_action"],
                "内部目标仓位": row["target_position"],
                "内部资金比例": row["pending_cash_ratio"],
                "内部卖出比例": row["pending_sell_ratio"],
                "当前仓位": holding["position_pct"] if holding is not None else 0.0,
                "当前价格": current_price,
                "买入均价": buy_average,
                "盈亏比例": pnl_ratio,
            }
        )
    source = pd.DataFrame(display_rows)
    traded_count = sum(1 for item in display_rows if item["当前仓位"] > 0)

    summary_cols = st.columns(4)
    summary_cols[0].metric("当前跟踪", summary["watching"] + summary["holding"])
    summary_cols[1].metric("理论持仓", traded_count)
    summary_cols[2].metric("今日新增", summary["today_added"])
    summary_cols[3].metric(
        "已自动清理",
        summary["expired"],
        help="观察超过5个完整自然日后由后端标记为过期",
    )

    st.markdown(
        '<div class="beili-book-heading"><span class="beili-book-badge paper">'
        "当前跟踪</span><span>观察与持仓股票</span></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"理论账户总权益 {money(account['equity'])}；当前仓位以理论总权益为分母，"
        "未记录理论买入的股票显示为 0%。"
    )
    render_tracking_table(source, project_id)
    if st.button(
        "添加观察股",
        type="primary",
        icon=":material/add:",
        key="add_watching_button",
    ):
        render_add_watching_dialog(project_id)
    st.caption(
        f"当前显示 {len(source)} 条 · 已清理 {summary['expired']} 条过期观察记录"
    )


def operation_history_page() -> None:
    project_id, _ = ensure_demo()
    st.markdown(
        '<div class="beili-note">通过股票代码或名称搜索加入观察、理论买入和卖出记录，'
        "用于复核每只股票从观察到交易的完整操作过程。</div>",
        unsafe_allow_html=True,
    )
    requested_symbol = st.session_state.pop("operation_history_symbol", None)
    legacy_symbol = st.session_state.pop("signal_history_symbol", None)
    navigation_query = requested_symbol or legacy_symbol
    if navigation_query:
        st.session_state["operation_history_query"] = navigation_query
        st.session_state["operation_history_page_number"] = 1
    st.session_state.setdefault("operation_history_query", "")
    st.session_state.setdefault("operation_history_page_number", 1)

    search_query = st.text_input(
        "搜索股票",
        placeholder="输入股票代码或名称，留空显示全部",
        icon=":material/search:",
        key="operation_history_query",
        on_change=_reset_operation_history_page,
        persist_state="session",
        width=480,
    )
    page_size = 50
    result = theory_services.paged_operation_history(
        project_id,
        query=search_query or "",
        page=st.session_state["operation_history_page_number"],
        page_size=page_size,
    )
    st.session_state["operation_history_page_number"] = result["page"]
    operations = result["rows"]
    query_is_empty = not (search_query or "").strip()
    show_stock_columns = query_is_empty or result["symbol_count"] != 1

    if query_is_empty:
        stock_name = "完整操作记录"
        heading_label = "全部股票"
    elif result["symbol_count"] == 1:
        stock_name = result["matched_name"]
        heading_label = result["matched_symbol"]
    else:
        stock_name = f'共匹配 {result["symbol_count"]} 只股票'
        heading_label = "搜索结果"
    st.markdown(
        '<div class="beili-book-heading">'
        f'<span class="beili-book-badge paper">{html.escape(str(heading_label))}</span>'
        f"<span>{html.escape(str(stock_name))}</span></div>",
        unsafe_allow_html=True,
    )

    rows = []
    action_text = {"WATCH": "观察", "BUY": "买入", "SELL": "卖出"}
    for row in operations:
        item = {
            "记录时间": row["recorded_at"],
            "操作": action_text.get(row["side"], row["side"]),
            "买卖比例": (
                row["allocation_ratio"] * 100
                if row["allocation_ratio"] is not None
                else None
            ),
            "总仓占比": (
                row["capital_ratio"] * 100
                if row["capital_ratio"] is not None
                else None
            ),
            "成交价格": row["reference_price"],
            "理论数量": row["quantity"],
            "理论金额": row["gross_amount"],
            "资金变动": row["cash_change"],
        }
        if show_stock_columns:
            item = {
                "股票代码": row["symbol"],
                "股票名称": row["name"],
                **item,
            }
        rows.append(item)
    if not rows:
        if query_is_empty:
            st.info("当前暂无操作记录，请先在“当前跟踪”中添加观察股。")
        else:
            st.info(f'没有找到与“{search_query.strip()}”匹配的操作记录。')
        return

    frame = pd.DataFrame(rows)
    styled = frame.style.map(recommendation_action_style, subset=["操作"])
    column_config = {
        "记录时间": st.column_config.TextColumn(width="medium"),
        "操作": st.column_config.TextColumn(width="small"),
        "买卖比例": st.column_config.NumberColumn(format="%.1f%%", width="small"),
        "总仓占比": st.column_config.NumberColumn(format="%.1f%%", width="small"),
        "成交价格": st.column_config.NumberColumn(format="%.2f", width="small"),
        "理论数量": st.column_config.NumberColumn(format="%.0f", width="small"),
        "理论金额": st.column_config.NumberColumn(format="¥ %.2f", width="medium"),
        "资金变动": st.column_config.NumberColumn(format="¥ %.2f", width="medium"),
    }
    if show_stock_columns:
        column_config = {
            "股票代码": st.column_config.TextColumn(width="medium", pinned=True),
            "股票名称": st.column_config.TextColumn(width="small"),
            **column_config,
        }
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        column_config=column_config,
    )
    first_record = (result["page"] - 1) * page_size + 1
    last_record = first_record + len(frame) - 1
    st.caption(
        f"当前显示第 {first_record}–{last_record} 条 · 共 {result['total_count']} 条"
        " · 按记录时间倒序排列 · 每页 50 条"
    )
    if result["page_count"] > 1:
        page_columns = st.columns([1, 1, 2, 1, 1], vertical_alignment="center")
        page_columns[0].button(
            "首页",
            icon=":material/first_page:",
            disabled=result["page"] == 1,
            key="operation_history_first_page",
            on_click=_set_operation_history_page,
            args=(1,),
            width="stretch",
        )
        page_columns[1].button(
            "上一页",
            icon=":material/chevron_left:",
            disabled=result["page"] == 1,
            key="operation_history_previous_page",
            on_click=_set_operation_history_page,
            args=(result["page"] - 1,),
            width="stretch",
        )
        page_columns[2].markdown(
            f"**第 {result['page']} / {result['page_count']} 页**"
        )
        page_columns[3].button(
            "下一页",
            icon=":material/chevron_right:",
            icon_position="right",
            disabled=result["page"] == result["page_count"],
            key="operation_history_next_page",
            on_click=_set_operation_history_page,
            args=(result["page"] + 1,),
            width="stretch",
        )
        page_columns[4].button(
            "末页",
            icon=":material/last_page:",
            icon_position="right",
            disabled=result["page"] == result["page_count"],
            key="operation_history_last_page",
            on_click=_set_operation_history_page,
            args=(result["page_count"],),
            width="stretch",
        )


def signal_history_page() -> None:
    """Compatibility alias for bookmarks created before the page rename."""
    operation_history_page()


def signal_center_page() -> None:
    project_id, paper_id = ensure_demo()
    st.caption("原始信号与标准化字段并列保存；相同指纹重复提交不会重复建账。")

    with st.expander("新增信号", expanded=True):
        with st.form("paper_signal_form", clear_on_submit=True):
            cols = st.columns(4)
            trade_day = cols[0].date_input("交易日", value=date.today())
            signal_clock = cols[1].time_input(
                "信号时间", value=datetime.now().time().replace(second=0, microsecond=0)
            )
            symbol = cols[2].text_input("股票代码", placeholder="300377.SZ")
            name = cols[3].text_input("股票名称", placeholder="赢时胜")
            action_label = st.selectbox("建议动作", list(ACTION_LABELS))
            cols = st.columns(4)
            target_pct = cols[0].number_input(
                "目标仓位（%）", min_value=0.0, max_value=100.0, value=25.0, step=0.5
            )
            reference_price = cols[1].number_input(
                "参考价", min_value=0.0, value=0.0, step=0.01
            )
            predicted_high = cols[2].number_input(
                "预测最高", min_value=0.0, value=0.0, step=0.01
            )
            predicted_low = cols[3].number_input(
                "预测最低", min_value=0.0, value=0.0, step=0.01
            )
            signal_type = st.text_input("信号标签", placeholder="①④ / B / 红色信号")
            raw_text = st.text_area("原始信号", placeholder="信号①④，加仓至25%")
            submitted = st.form_submit_button("保存为有效信号", type="primary")
        if submitted:
            try:
                timestamp = f"{trade_day.isoformat()} {signal_clock.strftime('%H:%M:%S')}"
                signal_id = paper_services.create_signal(
                    project_id=project_id,
                    trade_date=trade_day.isoformat(),
                    signal_time=timestamp,
                    symbol=symbol,
                    name=name,
                    action=ACTION_LABELS[action_label],
                    target_position=target_pct / 100,
                    reference_price=reference_price or None,
                    raw_text=raw_text,
                    signal_type=signal_type,
                    predicted_high=predicted_high or None,
                    predicted_low=predicted_low or None,
                )
                st.success(f"信号 #{signal_id} 已保存。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    signals = paper_services.list_signals(project_id)
    if not signals:
        st.info("暂无信号。可先录入一条，或到“导入与样例”批量导入。")
        return
    frame = pd.DataFrame([dict(row) for row in signals])
    display = frame[
        [
            "id",
            "signal_time",
            "symbol",
            "name",
            "action",
            "target_position",
            "reference_price",
            "signal_type",
            "raw_text",
            "status",
        ]
    ].rename(
        columns={
            "id": "ID",
            "signal_time": "信号时间",
            "symbol": "标的",
            "name": "名称",
            "action": "动作",
            "target_position": "目标仓位",
            "reference_price": "参考价",
            "signal_type": "标签",
            "raw_text": "原始信号",
            "status": "状态",
        }
    )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        column_config={"目标仓位": st.column_config.NumberColumn(format="%.2%%")},
    )

    st.markdown("#### 模拟执行")
    valid = [row for row in signals if row["status"] == "VALID"]
    if not valid:
        st.info("暂无待执行信号。")
        return
    selected_id = st.selectbox(
        "选择待执行信号",
        [int(row["id"]) for row in valid],
        format_func=lambda value: next(
            f"#{row['id']} · {row['symbol']} · {row['action']} · {row['target_position']:.1%}"
            for row in valid
            if int(row["id"]) == value
        ),
    )
    slippage = st.number_input("模拟滑点（bps）", min_value=0.0, value=5.0, step=1.0)
    preview = paper_services.preview_execution(selected_id, paper_id, slippage)
    st.json(
        {
            "执行前权益": round(preview.equity_before, 2),
            "当前数量": preview.current_quantity,
            "目标数量": preview.target_quantity,
            "订单方向": preview.side,
            "订单数量": preview.order_quantity,
            "模拟价格": round(preview.simulated_price, 4),
            "预计费用": round(preview.estimated_fees, 2),
            "成交后现金": round(preview.cash_after, 2),
            "拒绝原因": preview.reject_reason,
        }
    )
    if st.button("确认生成模拟订单", type="primary"):
        order_id = paper_services.execute_paper_signal(
            selected_id, paper_id, slippage
        )
        st.success(f"模拟订单 #{order_id} 已生成。")
        st.rerun()


def simulation_ledger_page() -> None:
    project_id, paper_id = ensure_demo()
    summary = paper_services.account_summary(paper_id)
    st.markdown(
        '<div class="beili-note">模拟账本由系统信号自动驱动，集中记录 PAPER '
        "账户的订单、成交、现金、持仓和盈亏，不涉及真实券商资金。</div>",
        unsafe_allow_html=True,
    )

    cols = st.columns(6)
    cols[0].metric("账户现金", money(summary["cash"]))
    cols[1].metric("持仓市值", money(summary["market_value"]))
    cols[2].metric("账户总权益", money(summary["equity"]))
    cols[3].metric("当前仓位", pct(summary["position_pct"]))
    cols[4].metric("已实现盈亏", money(summary["realized_pnl"]))
    cols[5].metric("模拟总盈亏", money(summary["total_pnl"]))

    position_tab, order_tab, fill_tab = st.tabs(["当前持仓", "模拟订单", "模拟成交"])
    with position_tab:
        positions = pd.DataFrame(paper_services.position_rows(paper_id))
        if positions.empty:
            st.info("暂无模拟持仓。买入信号执行后将在这里形成持仓记录。")
        else:
            st.dataframe(positions, width="stretch", hide_index=True)
    with order_tab:
        orders = pd.DataFrame(
            [dict(row) for row in paper_services.order_rows(project_id)]
        )
        if orders.empty:
            st.info("暂无模拟订单。")
        else:
            st.dataframe(orders, width="stretch", hide_index=True)
    with fill_tab:
        fills = pd.DataFrame(
            [dict(row) for row in paper_services.fill_rows(paper_id)]
        )
        if fills.empty:
            st.info("暂无模拟成交。")
        else:
            st.dataframe(fills, width="stretch", hide_index=True)


def trade_profit_style(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric > 0:
        return f"color: {MARKET_UP_COLOR}; font-weight: 720;"
    if numeric < 0:
        return f"color: {MARKET_DOWN_COLOR}; font-weight: 720;"
    return f"color: {MARKET_FLAT_COLOR};"


def monthly_trade_statistics_page() -> None:
    project_id, _ = ensure_demo()
    st.markdown(
        '<div class="beili-note">按月汇总理论操作和持仓市值，资金池按月滚动：'
        "本月期末总资金将作为下月期初资金。</div>",
        unsafe_allow_html=True,
    )
    months = theory_services.available_months(project_id)
    if not months:
        st.info("当前还没有理论操作记录，请先在“当前跟踪”中记录买入或载入演示数据。")
        return
    selected_month = st.selectbox("统计月份", months, key="trade_statistics_month")
    statistics = theory_services.monthly_statistics(project_id, selected_month)
    monthly = pd.DataFrame(statistics["details"])

    first_row = st.columns(3)
    first_row[0].metric("交易股数", f"{statistics['stock_count']} 只")
    first_row[1].metric("买入次数", f"{statistics['buy_count']} 次")
    first_row[2].metric("卖出次数", f"{statistics['sell_count']} 次")
    second_row = st.columns(4)
    second_row[0].metric("期初资金池", money(statistics["opening_capital"]))
    second_row[1].metric("本月盈亏", money(statistics["pnl"]))
    second_row[2].metric("期末总资金", money(statistics["closing_capital"]))
    second_row[3].metric("本月收益率", pct(statistics["return_rate"]))

    st.markdown(
        '<div class="beili-book-heading"><span class="beili-book-badge paper">'
        f"{selected_month}</span><span>理论交易股票明细</span></div>",
        unsafe_allow_html=True,
    )
    visible_columns = [
        "股票代码",
        "股票名称",
        "买入次数",
        "月末仓位",
        "卖出次数",
        "卖出金额",
        "已实现盈亏",
        "未实现盈亏变动",
        "本月盈亏",
        "收益率",
        "月末状态",
    ]
    styled = (
        monthly[visible_columns]
        .style.map(
            trade_profit_style,
            subset=["已实现盈亏", "未实现盈亏变动", "本月盈亏", "收益率"],
        )
    )
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        column_config={
            "股票代码": st.column_config.TextColumn(width="medium"),
            "股票名称": st.column_config.TextColumn(width="small"),
            "买入次数": st.column_config.NumberColumn(format="%d", width="small"),
            "月末仓位": st.column_config.NumberColumn(format="percent", width="small"),
            "卖出次数": st.column_config.NumberColumn(format="%d", width="small"),
            "卖出金额": st.column_config.NumberColumn(format="¥%.2f", width="medium"),
            "已实现盈亏": st.column_config.NumberColumn(format="¥%.2f", width="medium"),
            "未实现盈亏变动": st.column_config.NumberColumn(format="¥%.2f", width="medium"),
            "本月盈亏": st.column_config.NumberColumn(format="¥%.2f", width="medium"),
            "收益率": st.column_config.NumberColumn(format="percent", width="small"),
            "月末状态": st.column_config.TextColumn(width="small"),
        },
    )
    st.caption(
        f"{selected_month} 共 {len(monthly)} 只股票产生理论操作记录 · "
        "本月收益率 = 本月盈亏 ÷ 期初资金池 · 期末总资金自动滚入下月"
    )


def import_page() -> None:
    project_id, _ = ensure_demo()
    st.markdown(
        '<div class="beili-note">这里提供可重复载入的理论交易演示数据，'
        "用于查看当前跟踪、操作历史和月度统计的完整效果。</div>",
        unsafe_allow_html=True,
    )
    actions = st.container(horizontal=True)
    if actions.button(
        "载入理论交易演示数据",
        type="primary",
        icon=":material/history:",
    ):
        result = theory_fixtures.seed(project_id)
        st.session_state["fixture_notice"] = (
            f"演示数据已载入：{result['tracking_count']} 只股票、"
            f"{result['record_count']} 笔理论操作；本次新增 "
            f"{result['new_record_count']} 笔。重复载入不会重复记录。"
        )
        st.rerun()
    if notice := st.session_state.pop("fixture_notice", None):
        st.success(notice)

    summary = tracking_services.tracking_summary(project_id)
    account = theory_services.account_summary(project_id)
    months = theory_services.available_months(project_id)
    record_count = sum(
        theory_services.monthly_statistics(project_id, month)["buy_count"]
        + theory_services.monthly_statistics(project_id, month)["sell_count"]
        for month in months
    )
    cols = st.columns(4)
    cols[0].metric("观察中", summary["watching"])
    cols[1].metric("理论持仓", summary["holding"])
    cols[2].metric("理论操作", record_count)
    cols[3].metric("理论总权益", money(account["equity"]))

    with st.expander("查看演示数据内容"):
        st.caption("股票样本")
        st.dataframe(
            pd.DataFrame(
                theory_fixtures.TRACKING_FIXTURES,
                columns=["股票代码", "股票名称", "荐股时间"],
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption("理论操作样本")
        st.dataframe(
            pd.DataFrame(theory_fixtures.TRADE_FIXTURES),
            width="stretch",
            hide_index=True,
        )
