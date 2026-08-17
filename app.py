from __future__ import annotations

import importlib

import streamlit as st

import paper_db
import paper_services
import tracking_services
import trade_ui


paper_db = importlib.reload(paper_db)
paper_services = importlib.reload(paper_services)
tracking_services = importlib.reload(tracking_services)
trade_ui = importlib.reload(trade_ui)


st.set_page_config(
    page_title="观复交易管理系统",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --beili-navy: #F1F3F7;
            --beili-navy-soft: #C5CBD6;
            --beili-violet: #A78BFA;
            --beili-violet-soft: #2C2544;
            --beili-teal: #38BDF8;
            --beili-teal-soft: #132F3D;
            --beili-amber: #F6C453;
            --beili-amber-soft: #3B3019;
            --beili-canvas: #111318;
            --beili-card: #181C23;
            --beili-input: #20252E;
            --beili-line: #303744;
            --beili-text: #E7E9EE;
            --beili-muted: #929BAA;
        }
        .stApp { background: var(--beili-canvas); }
        header[data-testid="stHeader"] { background: transparent; }
        div[data-testid="stDecoration"] { display: none; }
        .block-container {
            max-width: 92rem;
            padding: 2rem 2rem 3rem;
        }
        section[data-testid="stSidebar"] {
            min-width: 14rem;
            background:
                radial-gradient(circle at 10% 0%, rgba(167, 139, 250, 0.22), transparent 30%),
                linear-gradient(180deg, #0D0F14 0%, #080A0E 100%);
            border-right: 0;
        }
        section[data-testid="stSidebar"] * {
            color: #F7FAFC;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label {
            border-radius: 0.65rem;
            padding: 0.35rem 0.55rem;
            transition: background 120ms ease;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {
            background: rgba(255, 255, 255, 0.08);
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
            background: rgba(167, 139, 250, 0.18);
            box-shadow: inset 3px 0 0 var(--beili-violet);
        }
        .beili-brand {
            margin: 0.2rem 0 1.5rem;
            padding-bottom: 1.2rem;
            border-bottom: 1px solid rgba(255,255,255,0.12);
        }
        .beili-brand-mark {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2.4rem;
            height: 2.4rem;
            margin-bottom: 0.65rem;
            border-radius: 0.75rem;
            background: linear-gradient(135deg, var(--beili-violet), #7C3AED);
            color: white;
            font-weight: 800;
            letter-spacing: 0.04em;
            box-shadow: 0 8px 20px rgba(124,58,237,0.25);
        }
        .beili-brand-title {
            color: white;
            font-size: 1.08rem;
            font-weight: 750;
            line-height: 1.3;
        }
        .beili-brand-subtitle {
            margin-top: 0.55rem;
            color: #D8D2C4;
            font-family: "Kaiti SC", "STKaiti", "KaiTi", "FZKai-Z03", serif;
            font-size: 1rem;
            font-weight: 500;
            letter-spacing: 0.12em;
            line-height: 1.6;
        }
        .beili-page-header {
            margin-bottom: 1.35rem;
        }
        .beili-page-eyebrow {
            color: var(--beili-violet);
            font-size: 0.72rem;
            font-weight: 750;
            letter-spacing: 0.12em;
        }
        .beili-page-title {
            margin-top: 0.2rem;
            color: var(--beili-navy);
            font-size: 2rem;
            font-weight: 780;
            line-height: 1.18;
        }
        div[data-testid="stMetric"] {
            min-height: 7rem;
            padding: 1rem 1.05rem;
            background: var(--beili-card);
            border: 1px solid var(--beili-line);
            border-radius: 0.9rem;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.16);
        }
        div[data-testid="stMetric"] label {
            color: var(--beili-muted);
        }
        div[data-testid="stMetricValue"] {
            color: var(--beili-navy);
        }
        div[data-testid="stDataFrame"],
        div[data-testid="stForm"],
        details[data-testid="stExpander"] {
            overflow: hidden;
            background: var(--beili-card);
            border: 1px solid var(--beili-line);
            border-radius: 0.9rem;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
        }
        div.stButton > button[kind="primary"],
        div.stFormSubmitButton > button[kind="primary"] {
            border: 0;
            background: linear-gradient(135deg, #8B5CF6, var(--beili-violet));
            color: white;
            box-shadow: 0 6px 16px rgba(139,92,246,0.24);
        }
        div.stButton > button[kind="secondary"],
        div.stDownloadButton > button {
            border-color: #465063;
            background: var(--beili-card);
            color: var(--beili-navy);
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        textarea {
            border-color: #3A4352 !important;
            background: var(--beili-input) !important;
        }
        h1, h2, h3, h4 {
            color: var(--beili-navy);
        }
        .beili-book-heading {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            margin: 1.45rem 0 0.7rem;
            color: var(--beili-navy);
            font-size: 1.05rem;
            font-weight: 750;
        }
        .beili-book-badge {
            padding: 0.24rem 0.55rem;
            border-radius: 999px;
            font-size: 0.7rem;
            font-weight: 800;
            letter-spacing: 0.06em;
        }
        .beili-book-badge.paper {
            color: var(--beili-teal);
            background: var(--beili-teal-soft);
        }
        .beili-book-badge.holding {
            color: var(--beili-amber);
            background: var(--beili-amber-soft);
        }
        .beili-note {
            padding: 0.78rem 0.95rem;
            border-left: 3px solid var(--beili-violet);
            border-radius: 0.25rem 0.65rem 0.65rem 0.25rem;
            background: #1B2029;
            color: #AEB6C3;
            font-size: 0.88rem;
        }
        .beili-table-wrap {
            overflow-x: auto;
            border: 1px solid var(--beili-line);
            border-radius: 0.9rem;
            background: var(--beili-card);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.14);
        }
        .beili-table {
            width: 100%;
            min-width: 1180px;
            border-collapse: collapse;
            font-size: 0.82rem;
        }
        .beili-table th {
            padding: 0.78rem 0.72rem;
            border-bottom: 1px solid var(--beili-line);
            color: var(--beili-muted);
            background: #151920;
            text-align: left;
            white-space: nowrap;
            font-weight: 700;
        }
        .beili-table td {
            padding: 0.72rem;
            border-bottom: 1px solid #252B35;
            color: var(--beili-text);
            vertical-align: middle;
            white-space: nowrap;
        }
        .beili-table tr:last-child td { border-bottom: 0; }
        .beili-table tbody tr:hover td { background: #1E242D; }
        .beili-stock-link {
            color: var(--beili-teal) !important;
            text-decoration: none;
            font-weight: 750;
        }
        .beili-stock-link:hover { text-decoration: underline; }
        .beili-action {
            display: inline-block;
            min-width: 3.5rem;
            padding: 0.23rem 0.48rem;
            border-radius: 0.38rem;
            text-align: center;
            font-weight: 750;
        }
        .beili-action.buy {
            color: #7DD3FC;
            background: rgba(56, 189, 248, 0.22);
        }
        .beili-action.sell {
            color: #FCD34D;
            background: rgba(246, 196, 83, 0.22);
        }
        .beili-action.watch {
            color: #B6BEC9;
            background: rgba(146, 155, 170, 0.12);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    paper_db.migrate()
    apply_styles()
    st.sidebar.markdown(
        """
        <div class="beili-brand">
          <div class="beili-brand-mark">观</div>
          <div class="beili-brand-title">观复交易复盘</div>
          <div class="beili-brand-subtitle">万物并作，吾以观复</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    pages = ["当前跟踪", "操作历史", "交易统计", "导入与样例"]
    requested_page = st.query_params.get("page")
    requested_symbol = st.query_params.get("symbol")
    if requested_page == "信号历史":
        requested_page = "操作历史"
    query_navigation = (requested_page, requested_symbol)
    if (
        requested_page in pages
        and st.session_state.get("_applied_query_navigation") != query_navigation
    ):
        st.session_state["navigation_page"] = requested_page
        if requested_symbol:
            st.session_state["operation_history_symbol"] = requested_symbol
        st.session_state["_applied_query_navigation"] = query_navigation

    page = st.sidebar.radio(
        "功能导航",
        pages,
        key="navigation_page",
    )
    st.markdown(
        f"""
        <div class="beili-page-header">
          <div class="beili-page-eyebrow">观复 · 理论收益复盘</div>
          <div class="beili-page-title">{page}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if page == "当前跟踪":
        trade_ui.daily_recommendations_page()
    elif page == "操作历史":
        trade_ui.operation_history_page()
    elif page == "交易统计":
        trade_ui.monthly_trade_statistics_page()
    else:
        trade_ui.import_page()


if __name__ == "__main__":
    main()
