import streamlit as st
from app.utils.config import APP_TITLE

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🏚️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title(f"🏚️ {APP_TITLE}")
st.caption("Harris County / Houston Wholesale Platform")

col1, col2, col3, col4 = st.columns(4)

from app.utils.db import execute

@st.cache_data(ttl=300)
def get_stats():
    try:
        parcels = execute("SELECT COUNT(*) AS n FROM parcels", commit=False)[0]["n"]
        owners  = execute("SELECT COUNT(*) AS n FROM owners",  commit=False)[0]["n"]
        buyers  = execute("SELECT COUNT(*) AS n FROM cash_buyers", commit=False)[0]["n"]
        leads   = execute("SELECT COUNT(*) AS n FROM leads WHERE status NOT IN ('closed','dead')", commit=False)[0]["n"]
        return parcels, owners, buyers, leads
    except Exception:
        return 0, 0, 0, 0

parcels, owners, buyers, leads = get_stats()

col1.metric("Parcels Loaded", f"{parcels:,}")
col2.metric("Owners Found", f"{owners:,}")
col3.metric("Cash Buyers", f"{buyers:,}")
col4.metric("Active Leads", f"{leads:,}")

st.divider()
st.info("👈 Use the sidebar to navigate. Start with **Search** to look up any property.")
