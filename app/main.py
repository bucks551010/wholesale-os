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


def safe_switch(page_relpath: str) -> None:
    """Robust page switch — resolves the target relative to this script."""
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.normpath(os.path.join(here, page_relpath))
    try:
        st.switch_page(target if os.path.exists(target) else page_relpath)
    except Exception as e:
        st.error(f"Could not open **{os.path.basename(page_relpath)}** — {e}")


_hour = datetime.now().hour
_greet = "Good morning" if _hour < 12 else ("Good afternoon" if _hour < 18 else "Good evening")
page_header(APP_TITLE, f"{_greet} — Harris County wholesale command center.", icon="🏚️")


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

section_header("Portfolio Snapshot")
c1, c2, c3, c4 = st.columns(4, gap="medium")
with c1: kpi_card("Parcels Loaded",  f"{s['parcels']:,}",   f"{s['buildings']:,} buildings")
with c2: kpi_card("Active Leads",    f"{s['active']:,}",    f"of {s['leads']:,} total")
with c3: kpi_card("Deals in Motion", f"{s['deals']:,}",     f"{s['under_contract']:,} under contract", "up" if s['under_contract'] else "")
with c4: kpi_card("Pipeline Value",  fmt_currency(s['pipeline_val']), f"{s['buyers']:,} cash buyers")


section_header("Command Center")
q1, q2, q3, q4 = st.columns(4, gap="medium")
if q1.button("🔍  Search Property", use_container_width=True, key="qa_search"):
    safe_switch("pages/01_Search.py")
if q2.button("🎯  Find Deals", use_container_width=True, key="qa_finder"):
    safe_switch("pages/09_Deal_Finder.py")
if q3.button("📊  Analyze Deal", use_container_width=True, key="qa_analysis"):
    safe_switch("pages/04_Analysis.py")
if q4.button("💼  Open My Work", use_container_width=True, type="primary", key="qa_work"):
    safe_switch("pages/08_My_Work.py")


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
    STAGE_KIND = {
        "prospect": "info", "contacted": "info", "negotiating": "warning",
        "under_contract": "brand", "assigned": "success", "closed": "success",
        "dead": "danger",
    }
    for d in recent:
        addr = f"{d.get('situs_num','')} {d.get('situs_street','')}".strip() or d.get("parcel_id", "—")
        stage = (d.get("stage") or "prospect").lower()
        stage_kind = STAGE_KIND.get(stage, "info")

        with st.container():
            col_a, col_b, col_c, col_d = st.columns([3, 1.2, 1.2, 1], gap="small")
            with col_a:
                st.markdown(
                    f"<div style='padding:6px 0'>"
                    f"<div style='font-weight:700; font-size:1rem; color:{COLORS['text']}'>{addr}</div>"
                    f"<div style='margin-top:4px'>{pill(stage.replace('_',' ').title(), stage_kind)}"
                    f"<span style='color:{COLORS['muted']}; font-size:0.82rem; margin-left:6px'>ZIP {d.get('situs_zip','—')}</span></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            col_b.markdown(
                f"<div style='padding:6px 0'>"
                f"<div style='font-size:0.68rem;color:{COLORS['muted']};text-transform:uppercase;font-weight:700;letter-spacing:0.08em'>Contract</div>"
                f"<div style='font-family:JetBrains Mono,monospace;font-weight:700;font-size:1rem;color:{COLORS['text']};margin-top:2px'>{fmt_currency(d.get('purchase_price'))}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            col_c.markdown(
                f"<div style='padding:6px 0'>"
                f"<div style='font-size:0.68rem;color:{COLORS['muted']};text-transform:uppercase;font-weight:700;letter-spacing:0.08em'>Assign Fee</div>"
                f"<div style='font-family:JetBrains Mono,monospace;font-weight:700;font-size:1rem;color:{COLORS['success']};margin-top:2px'>{fmt_currency(d.get('assignment_fee_target'))}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            with col_d:
                st.write("")
                if st.button("Open →", key=f"open_{d['id']}", use_container_width=True):
                    st.session_state["mw_selected_deal_id"] = d["id"]
                    safe_switch("pages/08_My_Work.py")
        st.markdown(
            f"<hr style='margin:8px 0;border-color:{COLORS['border']};opacity:0.6'/>",
            unsafe_allow_html=True,
        )
else:
    section_header("Get Started")
    st.info("👈  Use the sidebar to navigate. Start with **Property Search** or **Deal Finder** to find your first deal.")


section_header("Everything You Can Do")
FEATURES = [
    ("🔍", "Property Search",   "Look up any Harris County address, parcel, or owner.",  "pages/01_Search.py"),
    ("📋", "Leads",             "Score and manage your entire lead pipeline.",           "pages/02_Leads.py"),
    ("🚚", "Pipeline",          "Kanban board of every deal by stage.",                  "pages/03_Pipeline.py"),
    ("📊", "Deal Analysis",     "Comps, ARV, repairs, MAO, and every deal type.",        "pages/04_Analysis.py"),
    ("👥", "Cash Buyers",       "Buyer book, filters, and blast lists.",                 "pages/05_Buyers.py"),
    ("📨", "Outreach",          "Skip-trace and contact motivated sellers.",             "pages/06_Outreach.py"),
    ("📝", "Contracts",         "Assignment agreements and closing docs.",               "pages/07_Contracts.py"),
    ("💼", "My Work",           "Live workspace for every active deal.",                 "pages/08_My_Work.py"),
    ("🎯", "Deal Finder",       "Filter high-equity, distressed, absentee leads.",       "pages/09_Deal_Finder.py"),
    ("📈", "Comp Report",       "Printable comp reports for buyers and sellers.",        "pages/10_Comp_Report.py"),
]
rows = [FEATURES[i:i + 3] for i in range(0, len(FEATURES), 3)]
for row in rows:
    cols = st.columns(len(row), gap="medium")
    for col, (icon, name, desc, page) in zip(cols, row):
        with col:
            st.markdown(
                f"<div class='ws-card'>"
                f"<div class='ws-card-icon'>{icon}</div>"
                f"<div class='ws-card-title'>{name}</div>"
                f"<div class='ws-card-desc'>{desc}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button(f"Open  →", key=f"nav_{name}", use_container_width=True):
                safe_switch(page)


st.markdown(
    f"<div style='text-align:center; color:{COLORS['muted2']}; font-size:0.75rem; "
    f"margin-top:48px; padding:20px; border-top:1px solid {COLORS['border']}'>"
    f"WholesaleOS  ·  Harris County  ·  Live data from Railway PostgreSQL  ·  "
    f"Updated {datetime.now().strftime('%b %d, %Y  %H:%M')}"
    f"</div>",
    unsafe_allow_html=True,
)
