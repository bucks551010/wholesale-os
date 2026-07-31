import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from datetime import datetime

from app.utils.config import APP_TITLE
from app.utils.theme import inject_theme, page_header, kpi_card, section_header, pill, COLORS
from app.utils.db import execute
from app.utils.formatting import fmt_currency

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🏚️",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_theme()

_hour = datetime.now().hour
_greet = "Good morning" if _hour < 12 else ("Good afternoon" if _hour < 18 else "Good evening")
page_header(
    APP_TITLE,
    f"{_greet} — Harris County wholesale command center.",
    icon="🏚️",
)


@st.cache_data(ttl=300)
def get_portfolio_stats():
    def safe(sql: str, default: int = 0):
        try:
            r = execute(sql, commit=False)
            return r[0]["n"] if r else default
        except Exception:
            return default
    return {
        "parcels":        safe("SELECT COUNT(*) AS n FROM parcels"),
        "buildings":      safe("SELECT COUNT(*) AS n FROM buildings"),
        "leads":          safe("SELECT COUNT(*) AS n FROM leads"),
        "active":         safe("SELECT COUNT(*) AS n FROM leads WHERE status NOT IN ('closed','dead')"),
        "deals":          safe("SELECT COUNT(*) AS n FROM active_deals"),
        "under_contract": safe("SELECT COUNT(*) AS n FROM active_deals WHERE stage='under_contract'"),
        "buyers":         safe("SELECT COUNT(*) AS n FROM cash_buyers"),
        "pipeline_val":   safe("SELECT COALESCE(SUM(assignment_fee_target),0) AS n FROM active_deals"),
    }

s = get_portfolio_stats()

section_header("Portfolio")
c1, c2, c3, c4 = st.columns(4)
with c1: kpi_card("Parcels Loaded",  f"{s['parcels']:,}",   f"{s['buildings']:,} buildings")
with c2: kpi_card("Active Leads",    f"{s['active']:,}",    f"of {s['leads']:,} total")
with c3: kpi_card("Deals in Motion", f"{s['deals']:,}",     f"{s['under_contract']:,} under contract", "up" if s['under_contract'] else "")
with c4: kpi_card("Pipeline Value",  fmt_currency(s['pipeline_val']), f"{s['buyers']:,} cash buyers")


section_header("Quick Actions")
q1, q2, q3, q4 = st.columns(4)
if q1.button("🔍  Search a Property", use_container_width=True, key="qa_search"):
    st.switch_page("pages/01_Search.py")
if q2.button("🎯  Find Deals", use_container_width=True, key="qa_finder"):
    st.switch_page("pages/09_Deal_Finder.py")
if q3.button("📊  Analyze a Deal", use_container_width=True, key="qa_analysis"):
    st.switch_page("pages/04_Analysis.py")
if q4.button("💼  My Work", use_container_width=True, type="primary", key="qa_work"):
    st.switch_page("pages/08_My_Work.py")


@st.cache_data(ttl=60)
def get_recent_activity():
    try:
        return execute("""
            SELECT ad.id, ad.stage, ad.purchase_price, ad.assignment_fee_target,
                   ad.created_date, ad.updated_date,
                   l.parcel_id,
                   p.situs_num, p.situs_street, p.situs_zip
            FROM active_deals ad
            LEFT JOIN leads l ON l.id = ad.lead_id
            LEFT JOIN parcels p ON p.parcel_id = l.parcel_id
            ORDER BY ad.updated_date DESC NULLS LAST, ad.created_date DESC
            LIMIT 6
        """, commit=False) or []
    except Exception:
        return []

recent = get_recent_activity()
if recent:
    section_header("Active Deals")
    STAGE_COLORS = {
        "prospect": "info", "contacted": "info", "negotiating": "warning",
        "under_contract": "brand", "assigned": "success", "closed": "success",
        "dead": "danger",
    }
    for d in recent:
        addr = f"{d.get('situs_num','')} {d.get('situs_street','')}".strip() or d.get("parcel_id", "—")
        stage = (d.get("stage") or "prospect").lower()
        stage_kind = STAGE_COLORS.get(stage, "info")

        col_a, col_b, col_c, col_d = st.columns([3, 1.2, 1.2, 1])
        with col_a:
            st.markdown(
                f"**{addr}**  {pill(stage.replace('_',' ').title(), stage_kind)}  "
                f"<span style='color:{COLORS['muted']}; font-size:0.82rem'>ZIP {d.get('situs_zip','—')}</span>",
                unsafe_allow_html=True,
            )
        col_b.markdown(
            f"<div style='font-size:0.72rem;color:{COLORS['muted']};text-transform:uppercase;font-weight:600'>Contract</div>"
            f"<div style='font-family:JetBrains Mono,monospace;font-weight:700'>{fmt_currency(d.get('purchase_price'))}</div>",
            unsafe_allow_html=True,
        )
        col_c.markdown(
            f"<div style='font-size:0.72rem;color:{COLORS['muted']};text-transform:uppercase;font-weight:600'>Assign Fee</div>"
            f"<div style='font-family:JetBrains Mono,monospace;font-weight:700;color:{COLORS['success']}'>{fmt_currency(d.get('assignment_fee_target'))}</div>",
            unsafe_allow_html=True,
        )
        with col_d:
            if st.button("Open →", key=f"open_{d['id']}", use_container_width=True):
                st.session_state["mw_selected_deal_id"] = d["id"]
                st.switch_page("pages/08_My_Work.py")
        st.markdown(
            f"<hr style='margin:8px 0;border-color:{COLORS['border']};opacity:0.5'/>",
            unsafe_allow_html=True,
        )
else:
    section_header("Get Started")
    st.info("👈  Use the sidebar to navigate. Start with **Property Search** or **Deal Finder** to find your first deal.")


section_header("Everything You Can Do")
FEATURES = [
    ("🔍", "Property Search",   "Look up any Harris County address, parcel, or owner",  "pages/01_Search.py"),
    ("📋", "Leads",             "Manage & score your entire lead pipeline",              "pages/02_Leads.py"),
    ("🚚", "Pipeline",          "Kanban board of every deal by stage",                   "pages/03_Pipeline.py"),
    ("📊", "Deal Analysis",     "Comps, ARV, repairs, MAO, all deal types",              "pages/04_Analysis.py"),
    ("👥", "Cash Buyers",       "Buyer book, filters, blast lists",                      "pages/05_Buyers.py"),
    ("📨", "Outreach",          "Skip-tracing & seller contact",                         "pages/06_Outreach.py"),
    ("📝", "Contracts",         "Assignment agreements & closing docs",                  "pages/07_Contracts.py"),
    ("💼", "My Work",           "Live workspace for every active deal",                  "pages/08_My_Work.py"),
    ("🎯", "Deal Finder",       "Filter high-equity, distressed, absentee leads",        "pages/09_Deal_Finder.py"),
    ("📈", "Comp Report",       "Printable comp report for buyers & sellers",            "pages/10_Comp_Report.py"),
]
grid_cols = st.columns(3)
for i, (icon, name, desc, page) in enumerate(FEATURES):
    col = grid_cols[i % 3]
    with col:
        with st.container(border=True):
            st.markdown(
                f"<div style='font-size:1.5rem;line-height:1'>{icon}</div>"
                f"<div style='font-weight:700;font-size:1.05rem;margin-top:6px'>{name}</div>"
                f"<div style='color:{COLORS['muted']};font-size:0.85rem;margin:6px 0 12px 0;min-height:38px'>{desc}</div>",
                unsafe_allow_html=True,
            )
            if st.button("Open", key=f"nav_{name}", use_container_width=True):
                st.switch_page(page)


st.markdown(
    f"<div style='text-align:center;color:{COLORS['muted']};font-size:0.75rem;margin-top:40px;padding:16px'>"
    f"WholesaleOS · Harris County · Data live from Railway PostgreSQL · Updated {datetime.now().strftime('%b %d, %Y %H:%M')}"
    f"</div>",
    unsafe_allow_html=True,
)
