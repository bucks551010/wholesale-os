"""
Master Search — type any address, parcel ID, or owner name.
Returns the full property profile instantly.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import streamlit as st
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.utils.db import execute
from app.utils.formatting import fmt_currency, fmt_address, owner_type_label
from app.utils.geo import geocode, street_view_url, photo_links
from app.utils.config import GOOGLE_MAPS_API_KEY

st.set_page_config(page_title="Search | WholesaleOS", layout="wide")
st.title("🔍 Property Search")
st.caption("Type an address, parcel ID, or owner name to pull the full property profile.")


# ── Data helpers (defined before use) ────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner="Searching…")
def search_properties(q: str) -> list[dict]:
    like = f"%{q.upper()}%"
    sql = """
        SELECT
            p.parcel_id,
            p.situs_num,
            p.situs_street,
            p.situs_city,
            p.situs_zip,
            p.full_address,
            p.acct_type,
            p.total_appr_val,
            p.total_mkt_val,
            o.owner_name,
            o.owner_type,
            o.mail_city,
            o.mail_state,
            o.mail_zip,
            o.is_absentee,
            b.living_area,
            b.year_built,
            b.bedrooms,
            b.full_baths,
            b.half_baths
        FROM parcels p
        LEFT JOIN owners   o ON o.parcel_id = p.parcel_id
        LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        WHERE
            UPPER(p.full_address)  ILIKE %s
            OR p.parcel_id         = %s
            OR UPPER(o.owner_name) ILIKE %s
        LIMIT 40
    """
    return execute(sql, (like, q, like), commit=False)


@st.cache_data(ttl=120)
def get_distress_signals(parcel_id: str) -> list[str]:
    signals = []
    tax = execute(
        "SELECT SUM(amount_due - COALESCE(amount_paid,0)) AS owed, COUNT(*) AS yrs "
        "FROM tax_status WHERE parcel_id=%s AND is_delinquent=TRUE",
        (parcel_id,), commit=False
    )
    if tax and tax[0]["owed"]:
        signals.append(f"🔴 Tax delinquent: {fmt_currency(tax[0]['owed'])} ({tax[0]['yrs']} yr{'s' if tax[0]['yrs']!=1 else ''})")
    viol = execute(
        "SELECT COUNT(*) AS n FROM violations WHERE parcel_id=%s AND status NOT IN ('closed','resolved')",
        (parcel_id,), commit=False
    )
    if viol and viol[0]["n"]:
        signals.append(f"🔴 Open code violations: {viol[0]['n']}")
    fc = execute(
        "SELECT filing_date, status FROM foreclosures "
        "WHERE parcel_id=%s AND status NOT IN ('cancelled','sold') ORDER BY filing_date DESC LIMIT 1",
        (parcel_id,), commit=False
    )
    if fc:
        signals.append(f"🔴 Foreclosure filed: {fc[0]['filing_date']} ({fc[0]['status']})")
    comp = execute(
        "SELECT COUNT(*) AS n FROM complaints_311 "
        "WHERE parcel_id=%s AND complaint_date > NOW()-INTERVAL '2 years'",
        (parcel_id,), commit=False
    )
    if comp and comp[0]["n"]:
        signals.append(f"🟡 311 complaints (2 yr): {comp[0]['n']}")
    return signals


def _save_parcel_to_my_work(parcel_id: str):
    """Look up or create a lead, then open it in the My Work workspace."""
    lead = execute("SELECT id FROM leads WHERE parcel_id=%s LIMIT 1", (parcel_id,))
    if lead:
        lead_id = lead[0]["id"]
    else:
        # Create a manual lead for parcels not in the scored set
        r = execute(
            "INSERT INTO leads (parcel_id, source, date_added, motivated_score, status, priority) "
            "VALUES (%s,'manual',NOW(),0,'new_lead','low') RETURNING id",
            (parcel_id,), commit=True
        )
        lead_id = r[0]["id"] if r else None
    if not lead_id:
        st.error("Could not save this property.")
        return
    existing = execute(
        "SELECT id FROM active_deals WHERE lead_id=%s AND status!='dead' LIMIT 1", (lead_id,)
    )
    if existing:
        st.session_state["mw_deal_id"] = existing[0]["id"]
    else:
        r2 = execute(
            "INSERT INTO active_deals (lead_id, status, created_at) VALUES (%s,'new_lead',NOW()) RETURNING id",
            (lead_id,), commit=True
        )
        if r2:
            st.session_state["mw_deal_id"] = r2[0]["id"]
    st.switch_page("pages/08_My_Work.py")


def show_property_card(row: dict):
    addr = fmt_address(row["situs_num"], row["situs_street"],
                       row["situs_city"] or "Houston", "TX", row["situs_zip"] or "")

    # ── Photo / map row ───────────────────────────────────────────────────────
    @st.cache_data(ttl=3600, show_spinner=False)
    def _coords(a: str, city: str):
        return geocode(a, city=city, state="TX")

    coords = _coords(addr, row.get("situs_city") or "Houston")

    map_col, info_col, owner_col = st.columns([1, 1, 1], gap="medium")

    with map_col:
        if coords:
            import folium
            from streamlit_folium import st_folium
            lat, lon = coords
            if GOOGLE_MAPS_API_KEY:
                sv_url = street_view_url(lat, lon, GOOGLE_MAPS_API_KEY)
                st.image(sv_url, use_container_width=True, caption="📷 Street View")
            else:
                m = folium.Map(
                    location=[lat, lon],
                    zoom_start=18,
                    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                    attr="Esri",
                )
                folium.Marker(
                    [lat, lon],
                    tooltip=addr,
                    icon=folium.Icon(color="orange", icon="home", prefix="fa"),
                ).add_to(m)
                st_folium(m, width=320, height=240, returned_objects=[])
        else:
            st.markdown(
                f'<div style="background:#1a1a1a;border-radius:10px;padding:20px;'
                f'text-align:center;height:240px;display:flex;align-items:center;'
                f'justify-content:center;flex-direction:column;">'
                f'<div style="font-size:2.5rem;">🏠</div>'
                f'<div style="font-size:0.8rem;color:#888;margin-top:8px;">Map unavailable</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        # Photo links
        plinks = photo_links(addr, *coords) if coords else photo_links(addr)
        st.markdown(" | ".join(f"[{n}]({u})" for n, u in plinks.items()), unsafe_allow_html=True)

    with info_col:
        st.subheader("Property")
        st.markdown(f"**Address:** {addr}")
        st.markdown(f"**Parcel ID:** `{row['parcel_id']}`")
        st.markdown(f"**Type:** {row['acct_type'] or '—'}")
        beds  = row["bedrooms"]  or "?"
        baths = row["full_baths"] or "?"
        hb    = f" + {row['half_baths']}h" if row["half_baths"] else ""
        sqft  = f"{row['living_area']:,.0f} sqft" if row["living_area"] else "?"
        st.markdown(f"**Size:** {sqft}  •  {beds} bed / {baths}{hb} bath")
        st.markdown(f"**Year Built:** {row['year_built'] or '—'}")
        st.markdown("---")
        st.markdown(f"**HCAD Appraised:** {fmt_currency(row['total_appr_val'])}")
        st.markdown(f"**HCAD Market:**    {fmt_currency(row['total_mkt_val'])}")

    with owner_col:
        st.subheader("Owner")
        st.markdown(f"**Name:** {row['owner_name'] or '—'}")
        st.markdown(f"**Type:** {owner_type_label(row['owner_name'])}")
        mailing = ", ".join(filter(None, [row["mail_city"], row["mail_state"], row["mail_zip"]]))
        absentee_flag = "⚠️ **Absentee**" if row["is_absentee"] else "✅ Local owner"
        st.markdown(f"**Mailing:** {mailing or '—'}  {absentee_flag}")
        st.markdown("---")
        st.markdown("**Find contact info (free):**")
        name_enc = (row["owner_name"] or "").replace(" ", "+")
        city_enc = (row["mail_city"] or "Houston").replace(" ", "+")
        state    = row.get("mail_state") or "TX"
        pid      = row["parcel_id"]
        st.markdown(
            f"[TruePeopleSearch ↗](https://www.truepeoplesearch.com/results?name={name_enc}&citystatezip={city_enc}%2C+{state})  |  "
            f"[FastPeopleSearch ↗](https://www.fastpeoplesearch.com/name/{name_enc})  |  "
            f"[HCAD Portal ↗](https://hcad.org/property-search/real-property/strap-search/?strap={pid})"
        )
        if owner_type_label(row["owner_name"]) == "LLC / Entity":
            st.markdown(
                f"[TX SOS Entity ↗](https://mycpa.cpa.state.tx.us/coa/searchEntities.do?name={name_enc})"
            )

    signals = get_distress_signals(row["parcel_id"])
    if signals:
        st.subheader("⚠️ Distress Signals")
        for s in signals:
            st.markdown(s)
    else:
        st.markdown("✅ No distress signals found yet — run ingestion jobs to populate.")

    st.divider()
    a1, a2, a3, a4, a5 = st.columns(5)
    a1.button("➕ Add as Lead",       key=f"lead_{row['parcel_id']}")
    if a2.button("💰 Run Deal Analysis", key=f"deal_{row['parcel_id']}"):
        st.session_state["analysis_parcel_id"] = row["parcel_id"]
        st.switch_page("pages/04_Analysis.py")
    if a3.button("📊 Comp Report", key=f"comp_{row['parcel_id']}"):
        st.session_state["cr_query"] = row["full_address"] or row["parcel_id"]
        st.switch_page("pages/10_Comp_Report.py")
    a4.button("📋 View Full History", key=f"hist_{row['parcel_id']}")
    if a5.button("📁 Save to My Work", key=f"work_{row['parcel_id']}", type="primary"):
        _save_parcel_to_my_work(row["parcel_id"])


# ── Search input (below all function definitions) ─────────────────────────────
_prefill = st.session_state.pop("search_query", "")
query = st.text_input(
    label="Search",
    placeholder='e.g.  "4521 Oak St"   or   "1234567890"   or   "James Williams"',
    label_visibility="collapsed",
    value=_prefill,
)

if not query or len(query.strip()) < 3:
    st.info("Enter at least 3 characters to search.")
    st.stop()

results = search_properties(query.strip())

if not results:
    st.warning("No properties found. Try a partial street name, parcel ID, or owner name.")
    st.stop()

st.success(f"{len(results)} result{'s' if len(results) != 1 else ''} found")

for row in results:
    addr  = fmt_address(row["situs_num"], row["situs_street"],
                        row["situs_city"] or "Houston", "TX", row["situs_zip"] or "")
    owner = row["owner_name"] or "Unknown Owner"
    val   = fmt_currency(row["total_appr_val"])
    with st.expander(f"**{addr}** — {owner} — HCAD: {val}", expanded=len(results) == 1):
        show_property_card(row)
