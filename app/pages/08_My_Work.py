import os, sys, datetime
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency
from app.utils.comps import (
    REPAIR_RATES, find_comps, compute_arv, estimate_repairs,
    compute_mao, save_valuation, save_repair_estimate,
    compute_flip_offer, compute_hold, compute_brrr, compute_novation,
)

try:
    from app.utils.geo import geocode, photo_links
    from app.utils.config import GOOGLE_MAPS_API_KEY
    GEO_OK = True
except Exception:
    GEO_OK = False

try:
    import folium
    from streamlit_folium import st_folium
    FOLIUM_OK = True
except Exception:
    FOLIUM_OK = False

st.set_page_config(page_title="My Work", page_icon="📁", layout="wide")

# ── DB Bootstrap ──────────────────────────────────────────────────────────────
_boot = [
    """CREATE TABLE IF NOT EXISTS work_tasks (
        id SERIAL PRIMARY KEY, lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
        task_text TEXT NOT NULL, due_date DATE, priority TEXT DEFAULT 'normal',
        is_done BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT NOW(),
        completed_at TIMESTAMPTZ)""",
    "ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS seller_notes TEXT",
    "ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS assignment_price NUMERIC",
    "ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS motivation_score INTEGER DEFAULT 5",
    "ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS seller_type TEXT",
    "ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS best_call_time TEXT",
    "ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS urgency TEXT DEFAULT 'normal'",
    "ALTER TABLE matched_buyers ADD COLUMN IF NOT EXISTS notes TEXT",
    "ALTER TABLE matched_buyers ADD COLUMN IF NOT EXISTS response_date DATE",
    """CREATE TABLE IF NOT EXISTS seller_facts (
        id SERIAL PRIMARY KEY, deal_id INTEGER REFERENCES active_deals(id) ON DELETE CASCADE,
        fact_text TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())""",
    "CREATE INDEX IF NOT EXISTS idx_seller_facts_deal ON seller_facts(deal_id)",
]
for _s in _boot:
    execute(_s, commit=True)

# ── Constants ─────────────────────────────────────────────────────────────────
STAGE_KEYS   = ["new_lead","contacted","analyzing","negotiating","under_contract","assigned"]
STAGE_LABELS = {
    "new_lead":       "🆕 New Lead",
    "contacted":      "📞 Contacted",
    "analyzing":      "🔍 Analyzing",
    "negotiating":    "🤝 Negotiating",
    "under_contract": "📝 Under Contract",
    "assigned":       "💰 Assigned",
}
STATUS_ICON   = {k: v.split()[0] for k, v in STAGE_LABELS.items()}
URGENCY_COLOR = {"critical": "🔴", "high": "🟠", "normal": "🟡", "low": "🟢"}
METHOD_ICON   = {"Call":"📞","Text":"💬","Email":"✉️","Letter":"📬",
                 "In-person":"🤝","Voicemail":"📱","Door knock":"🚪"}
OUTCOME_DOT   = {
    "Spoke — interested":"🟢","Appointment set":"🟢","Offer accepted":"🟢",
    "Offer made":"🟡","Spoke — not interested":"🔴","Offer rejected":"🔴",
    "No answer":"⚫","Left voicemail":"⚫",
}
PRI_ICON = {"high":"🔴","normal":"🟡","low":"🟢"}
SELLER_TYPES = [
    "Inherited","Divorce","Pre-foreclosure","Behind on Taxes","Absentee Owner",
    "Tired Landlord","Probate","Job Loss/Relocation","Code Violations","Bankruptcy",
    "Death in Family","Medical Bills","Downsizing","Estate Sale","Other",
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def days_until(dt):
    if not dt:
        return None
    if isinstance(dt, datetime.datetime):
        dt = dt.date()
    return (dt - datetime.date.today()).days

def countdown_badge(label, dt, warn_days=7, danger_days=3):
    n = days_until(dt)
    if n is None:
        return
    if n < 0:
        st.error(f"🚨 **{label}** was {abs(n)} days ago! ({dt})")
    elif n <= danger_days:
        st.error(f"🔴 **{label}** in {n} days ({dt})")
    elif n <= warn_days:
        st.warning(f"🟠 **{label}** in {n} days ({dt})")
    else:
        st.info(f"📅 **{label}** in {n} days ({dt})")

# ── Pipeline summary bar ──────────────────────────────────────────────────────
pipeline_rows = execute("""
    SELECT status, COUNT(*) AS n FROM active_deals WHERE status != 'dead' GROUP BY status
""", commit=False)
pipeline_map  = {r["status"]: r["n"] for r in pipeline_rows}
total_active  = sum(pipeline_map.values())

st.title("📁 My Work")
if total_active:
    pcols = st.columns(len(STAGE_KEYS) + 1)
    pcols[0].metric("Total Active", total_active)
    for i, k in enumerate(STAGE_KEYS):
        pcols[i + 1].metric(STAGE_LABELS[k], pipeline_map.get(k, 0))

st.divider()

left_col, right_col = st.columns([1, 3], gap="large")

# ── LEFT PANEL ────────────────────────────────────────────────────────────────
with left_col:
    st.subheader("🏠 My Properties")

    lf1, lf2 = st.columns(2)
    filter_status = lf1.selectbox(
        "Filter stage",
        ["All"] + STAGE_KEYS,
        format_func=lambda k: "All Stages" if k == "All" else STAGE_LABELS[k],
        key="mw_filter_status",
        label_visibility="collapsed",
    )
    sort_by = lf2.selectbox(
        "Sort",
        ["Newest First", "Score ↓", "Stage"],
        key="mw_sort_by",
        label_visibility="collapsed",
    )

    where_clause = "AND ad.status = %s" if filter_status != "All" else ""
    order_clause = {
        "Newest First": "ad.created_at DESC",
        "Score ↓":      "l.motivated_score DESC NULLS LAST",
        "Stage":        "array_position(ARRAY['new_lead','contacted','analyzing','negotiating','under_contract','assigned'], ad.status)",
    }[sort_by]

    q_args = (filter_status,) if filter_status != "All" else ()
    active_deals = execute(f"""
        SELECT ad.id, p.full_address, p.situs_zip, ad.status, ad.urgency,
               l.motivated_score, l.id AS lead_id,
               ad.purchase_price, ad.option_expiry, ad.closing_date,
               (SELECT MAX(contact_date) FROM lead_contact_log WHERE lead_id = l.id) AS last_contact,
               (SELECT COUNT(*) FROM work_tasks WHERE lead_id = l.id AND is_done = FALSE) AS open_tasks
        FROM active_deals ad
        JOIN leads   l ON l.id = ad.lead_id
        JOIN parcels p ON p.parcel_id = l.parcel_id
        WHERE ad.status != 'dead' {where_clause}
        ORDER BY {order_clause}
    """, q_args)

    selected_id = st.session_state.get("mw_deal_id")

    if not active_deals:
        st.info("No properties match the filter.")

    for d in active_deals:
        is_sel      = selected_id == d["id"]
        icon        = STATUS_ICON.get(d["status"], "")
        urg_dot     = URGENCY_COLOR.get(d["urgency"] or "normal", "🟡")
        addr        = d["full_address"][:34]
        overdue_exp = d["option_expiry"] and days_until(d["option_expiry"]) is not None and days_until(d["option_expiry"]) < 0
        exp_warn    = d["option_expiry"] and 0 <= (days_until(d["option_expiry"]) or 999) <= 5

        with st.container(border=is_sel):
            st.markdown(f"{urg_dot} {icon} **{addr}**")
            score_str = f"Score {d['motivated_score'] or '—'}"
            price_str = f" · ${int(d['purchase_price'] or 0):,}" if d["purchase_price"] else ""
            tasks_str = f" · ✅ {d['open_tasks']} tasks" if d["open_tasks"] else ""
            exp_str   = " · 🚨 Expired!" if overdue_exp else (" · ⚠️ Expiring" if exp_warn else "")
            st.caption(f"{score_str}{price_str}{tasks_str}{exp_str}")
            if st.button("Open →", key=f"mw_open_{d['id']}", use_container_width=True,
                         type="primary" if is_sel else "secondary"):
                st.session_state["mw_deal_id"] = d["id"]
                st.rerun()

    st.divider()
    with st.expander("➕ Add a Property"):
        addr_q = st.text_input("Search address, ZIP, or parcel ID", key="mw_addr_q",
                               placeholder="e.g. 4521 Elm or 77051")
        if addr_q and len(addr_q) >= 3:
            hits = execute("""
                SELECT p.parcel_id, p.full_address, p.situs_zip, p.total_mkt_val,
                       l.id AS lead_id, COALESCE(l.motivated_score, 0) AS motivated_score,
                       o.owner_name
                FROM parcels p
                LEFT JOIN leads l ON l.parcel_id = p.parcel_id
                LEFT JOIN owners o ON o.parcel_id = p.parcel_id
                WHERE UPPER(p.full_address) ILIKE %s
                   OR p.parcel_id = %s
                   OR UPPER(o.owner_name) ILIKE %s
                ORDER BY l.motivated_score DESC NULLS LAST
                LIMIT 12
            """, (f"%{addr_q.upper()}%", addr_q.strip(), f"%{addr_q.upper()}%"))
            if not hits:
                st.caption("No properties found.")
            for h in hits:
                already = execute(
                    "SELECT ad.id FROM active_deals ad JOIN leads l ON l.id=ad.lead_id "
                    "WHERE l.parcel_id=%s AND ad.status!='dead' LIMIT 1",
                    (h["parcel_id"],)
                )
                badge = " ✅" if already else ""
                label = f"{h['full_address'][:38]}  |  Score {h['motivated_score']}{badge}"
                if st.button(label, key=f"mw_hit_{h['parcel_id']}", use_container_width=True):
                    if already:
                        st.session_state["mw_deal_id"] = already[0]["id"]
                        st.rerun()
                    else:
                        lead_id = h["lead_id"]
                        if not lead_id:
                            r_lead = execute(
                                "INSERT INTO leads (parcel_id, source, date_added, motivated_score, status, priority) "
                                "VALUES (%s,'manual',NOW(),0,'new_lead','low') RETURNING id",
                                (h["parcel_id"],), commit=True
                            )
                            lead_id = r_lead[0]["id"] if r_lead else None
                        if lead_id:
                            res = execute(
                                "INSERT INTO active_deals (lead_id, status, created_at) "
                                "VALUES (%s,'new_lead',NOW()) RETURNING id",
                                (lead_id,), commit=True
                            )
                            if res:
                                st.session_state["mw_deal_id"] = res[0]["id"]
                                st.rerun()

# ── RIGHT PANEL ───────────────────────────────────────────────────────────────
with right_col:
    deal_id = st.session_state.get("mw_deal_id")

    if not deal_id:
        st.markdown("### 👈 Select or add a property to get started")
        st.markdown("""
**What you can do here:**
- 📊 Deal Dashboard — deadlines, quick actions, risk flags, satellite map
- 💰 Deal Numbers — live MAO calc, ARV, repairs, assignment fee
- 🧑 Seller — contact info, motivation score, call scripts, timestamped facts log
- 📝 Activity Log — every call, text, and meeting with overdue alerts
- ✅ Tasks — prioritized checklist with standard wholesaling workflow
- 🎯 Buyers — auto-match, deal blast generator, response tracking
""")
        st.stop()

    d_rows = execute("""
        SELECT ad.id, ad.lead_id, ad.seller_name, ad.seller_phone, ad.seller_email,
               ad.contract_date, ad.purchase_price, ad.option_period_days, ad.option_expiry,
               ad.closing_date, ad.title_company, ad.title_company_contact,
               ad.earnest_money_amount, ad.em_status, ad.assignment_fee_target,
               ad.status, ad.notes, ad.seller_notes, ad.assignment_price, ad.created_at,
               ad.motivation_score, ad.seller_type, ad.best_call_time, ad.urgency,
               p.full_address, p.situs_zip, p.total_mkt_val, p.total_appr_val,
               p.land_val, p.improvement_val, p.parcel_id,
               l.motivated_score, l.deal_score, l.priority, l.notes AS lead_notes,
               l.status AS lead_status, l.id AS lead_id_q
        FROM active_deals ad
        JOIN leads   l ON l.id = ad.lead_id
        JOIN parcels p ON p.parcel_id = l.parcel_id
        WHERE ad.id = %s
    """, (deal_id,))

    if not d_rows:
        st.error("Deal not found.")
        del st.session_state["mw_deal_id"]
        st.stop()

    d         = d_rows[0]
    parcel_id = d["parcel_id"]
    lead_id   = d["lead_id"]

    # ── Header ────────────────────────────────────────────────────────────
    h1, h2, h3, h4, h5 = st.columns([3, 1, 1, 1, 1])
    h1.header(d["full_address"])
    h1.caption(f"ZIP {d['situs_zip']}  ·  Parcel {parcel_id}")
    days_in_pipe = (datetime.date.today() - d["created_at"].date()).days if d["created_at"] else "—"
    h2.metric("Days In Pipeline",  days_in_pipe)
    h3.metric("Motivated Score",   d["motivated_score"] or "—")
    h4.metric("HCAD Value",        fmt_currency(d["total_mkt_val"]))
    h5.metric("Deal Score",        d["deal_score"] or "—")

    # Stage + urgency controls
    sc1, sc2, sc3 = st.columns([3, 3, 1])
    new_status = sc1.selectbox(
        "Stage",
        STAGE_KEYS,
        format_func=lambda k: STAGE_LABELS[k],
        index=STAGE_KEYS.index(d["status"]) if d["status"] in STAGE_KEYS else 0,
        key="mw_status_select",
        label_visibility="collapsed",
    )
    urg_options = ["critical","high","normal","low"]
    new_urgency = sc2.selectbox(
        "Urgency",
        urg_options,
        format_func=lambda u: f"{URGENCY_COLOR[u]} {u.title()} Urgency",
        index=urg_options.index(d["urgency"] or "normal"),
        key="mw_urgency_select",
        label_visibility="collapsed",
    )
    if new_status != d["status"] or new_urgency != (d["urgency"] or "normal"):
        execute("UPDATE active_deals SET status=%s, urgency=%s WHERE id=%s",
                (new_status, new_urgency, deal_id), commit=True)
        st.rerun()

    # Visual pipeline progress bar
    stage_idx  = STAGE_KEYS.index(d["status"]) if d["status"] in STAGE_KEYS else 0
    prog_parts = []
    for i, k in enumerate(STAGE_KEYS):
        lbl = STAGE_LABELS[k].split(" ", 1)[1]
        if i < stage_idx:
            prog_parts.append(f"<span style='color:#4ade80'>✔ {lbl}</span>")
        elif i == stage_idx:
            prog_parts.append(f"<span style='color:#e85d04;font-weight:700'>▶ {lbl}</span>")
        else:
            prog_parts.append(f"<span style='color:#555'>{lbl}</span>")
    st.markdown(" &nbsp;›&nbsp; ".join(prog_parts), unsafe_allow_html=True)
    st.progress((stage_idx + 1) / len(STAGE_KEYS))

    if sc3.button("🗑️ Archive", key="mw_kill", help="Remove from active work"):
        execute("UPDATE active_deals SET status='dead' WHERE id=%s", (deal_id,), commit=True)
        del st.session_state["mw_deal_id"]
        st.rerun()

    # Deadline countdown banners
    for lbl, dt, w, dg in [("Option Expiry", d["option_expiry"], 5, 2),
                             ("Closing Date",  d["closing_date"],  7, 3)]:
        if dt:
            countdown_badge(lbl, dt, w, dg)

    # Overdue alerts
    overdue_tasks = execute("""
        SELECT COUNT(*) AS n FROM work_tasks
        WHERE lead_id=%s AND is_done=FALSE AND due_date < CURRENT_DATE
    """, (lead_id,))[0]["n"]
    overdue_fu_row = execute("""
        SELECT MIN(next_followup) AS d FROM lead_contact_log
        WHERE lead_id=%s AND next_followup < CURRENT_DATE
    """, (lead_id,))[0]["d"]
    if overdue_tasks:
        st.error(f"🚨 **{overdue_tasks} overdue task{'s' if overdue_tasks > 1 else ''}** — see Tasks tab")
    if overdue_fu_row:
        st.warning(f"⏰ **Follow-up overdue** since {overdue_fu_row} — log an activity!")

    st.divider()

    # ── Tabs ──────────────────────────────────────────────────────────────
    t_dash, t_deal, t_seller, t_act, t_tasks, t_buyers = st.tabs([
        "📊 Dashboard", "💰 Deal Numbers", "🧑 Seller", "📝 Activity Log", "✅ Tasks", "🎯 Buyers"
    ])

    # ──────────────────────────────────────────────────────────────────────
    # DASHBOARD TAB
    # ──────────────────────────────────────────────────────────────────────
    with t_dash:
        st.subheader("⚡ Quick Actions")
        qa1, qa2, qa3, qa4 = st.columns(4)

        if qa1.button("📞 Log a Call", use_container_width=True):
            st.session_state["mw_quick_log"] = not st.session_state.get("mw_quick_log", False)

        if qa2.button("📊 Run Comps", use_container_width=True):
            st.switch_page("pages/04_Analysis.py")

        if qa3.button("📋 Copy Deal Sheet", use_container_width=True):
            st.session_state["mw_show_summary"] = not st.session_state.get("mw_show_summary", False)

        if qa4.button("🎯 Blast Buyers", use_container_width=True):
            st.session_state["mw_show_blast"] = not st.session_state.get("mw_show_blast", False)

        # Quick call log panel
        if st.session_state.get("mw_quick_log"):
            with st.form("mw_quick_call"):
                st.markdown("**Log a Quick Contact**")
                ql1, ql2 = st.columns(2)
                ql_method  = ql1.selectbox("Method",  list(METHOD_ICON.keys()))
                ql_outcome = ql2.selectbox("Outcome", [
                    "No answer","Left voicemail","Spoke — interested",
                    "Spoke — not interested","Appointment set","Offer made","Other",
                ])
                ql_notes = st.text_area("Notes", height=60)
                ql_fu    = st.date_input("Next Follow-up",
                                          value=datetime.date.today() + datetime.timedelta(days=3))
                sb1, sb2 = st.columns(2)
                if sb1.form_submit_button("💾 Log It", type="primary"):
                    execute("""
                        INSERT INTO lead_contact_log
                            (lead_id, contact_date, method, outcome, notes, next_followup)
                        VALUES (%s, CURRENT_DATE, %s, %s, %s, %s)
                    """, (lead_id, ql_method, ql_outcome,
                          ql_notes.strip() or None, ql_fu), commit=True)
                    st.session_state["mw_quick_log"] = False
                    st.rerun()
                if sb2.form_submit_button("Cancel"):
                    st.session_state["mw_quick_log"] = False
                    st.rerun()

        # Deal sheet for copy-paste
        if st.session_state.get("mw_show_summary"):
            arv_qs = execute("SELECT arv_estimate FROM valuations WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1", (parcel_id,))
            arv_s  = fmt_currency(arv_qs[0]["arv_estimate"]) if arv_qs else "TBD"
            bldg_s = execute("SELECT living_area, year_built, bedrooms, full_baths, condition FROM buildings WHERE parcel_id=%s AND building_num=1 LIMIT 1", (parcel_id,))
            bld_s  = bldg_s[0] if bldg_s else {}
            sqft_s = f"{int(bld_s['living_area']):,} sqft" if bld_s.get("living_area") else "—"
            sheet  = (
                f"🏠 {d['full_address']}\n"
                f"ARV: {arv_s}  |  HCAD Value: {fmt_currency(d['total_mkt_val'])}\n"
                f"Bed/Bath: {bld_s.get('bedrooms','?')}/{bld_s.get('full_baths','?')}  |  {sqft_s}  |  Built {bld_s.get('year_built','?')}\n"
                f"Condition: {bld_s.get('condition','?')}\n"
                f"Asking: {fmt_currency(d['purchase_price'])}  |  Fee Target: {fmt_currency(d['assignment_fee_target'])}\n"
                f"ZIP: {d['situs_zip']}"
            )
            st.code(sheet, language=None)
            st.caption("Select all → copy → paste into text/email to buyers.")

        # Buyer blast template
        if st.session_state.get("mw_show_blast"):
            arv_bl = execute("SELECT arv_estimate FROM valuations WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1", (parcel_id,))
            arv_bl_s = fmt_currency(arv_bl[0]["arv_estimate"]) if arv_bl else "TBD"
            rep_bl = execute("SELECT total_low, total_high FROM repair_estimates WHERE parcel_id=%s ORDER BY created_date DESC LIMIT 1", (parcel_id,))
            rep_bl_s = f"{fmt_currency(rep_bl[0]['total_low'])}–{fmt_currency(rep_bl[0]['total_high'])}" if rep_bl else "TBD"
            bldg_bl = execute("SELECT living_area, year_built, bedrooms, full_baths FROM buildings WHERE parcel_id=%s AND building_num=1 LIMIT 1", (parcel_id,))
            bld_bl  = bldg_bl[0] if bldg_bl else {}
            sqft_bl = f"{int(bld_bl['living_area']):,} sqft" if bld_bl.get("living_area") else "—"
            blast   = (
                f"🏠 DEAL ALERT — {d['full_address']}, {d['situs_zip']}\n\n"
                f"🛏 {bld_bl.get('bedrooms','?')} bed / {bld_bl.get('full_baths','?')} bath  |  {sqft_bl}  |  Built {bld_bl.get('year_built','?')}\n"
                f"💰 ARV: {arv_bl_s}  |  Est. Repairs: {rep_bl_s}\n"
                f"🏷 Asking: {fmt_currency(d['purchase_price']) if d['purchase_price'] else 'Make offer'}\n\n"
                f"Reply INTERESTED or call me for deal details!"
            )
            st.code(blast, language=None)
            st.caption("Copy this to blast to your buyers list.")

        st.divider()

        # Property snapshot + satellite map
        snap_left, snap_right = st.columns([1, 1])

        bldg_ov = execute("""
            SELECT living_area, year_built, bedrooms, full_baths, half_baths,
                   condition, stories, pool_flag, building_class
            FROM buildings WHERE parcel_id=%s AND building_num=1 LIMIT 1
        """, (parcel_id,))
        bld_ov = bldg_ov[0] if bldg_ov else {}

        with snap_left:
            st.subheader("🏗️ Property Profile")
            info_rows = [
                ("Living Area",  f"{int(bld_ov['living_area']):,} sqft" if bld_ov.get("living_area") else "—"),
                ("Year Built",   str(bld_ov.get("year_built") or "—")),
                ("Bed / Bath",   f"{bld_ov.get('bedrooms','?')} / {bld_ov.get('full_baths','?')}"),
                ("Stories",      str(bld_ov.get("stories") or "—")),
                ("Condition",    bld_ov.get("condition") or "—"),
                ("Pool",         "✅" if bld_ov.get("pool_flag") else "❌"),
                ("Class",        bld_ov.get("building_class") or "—"),
            ]
            for lbl, val in info_rows:
                st.markdown(f"**{lbl}:** {val}")

            owner = execute("""
                SELECT owner_name, owner_type, mail_addr_1, mail_city, mail_state, mail_zip
                FROM owners WHERE parcel_id=%s LIMIT 1
            """, (parcel_id,))
            st.subheader("👤 Owner of Record")
            if owner:
                ow   = owner[0]
                mail = ", ".join(p for p in [ow["mail_addr_1"], ow["mail_city"],
                                             ow["mail_state"], ow["mail_zip"]] if p)
                st.markdown(f"**{ow['owner_name'] or '—'}** ({ow['owner_type'] or '—'})")
                if mail:
                    st.caption(f"📬 {mail}")
            else:
                st.caption("No owner data.")

        with snap_right:
            if GEO_OK and FOLIUM_OK:
                geo_result = geocode(d["full_address"])
                if geo_result:
                    lat, lon = geo_result
                    m_map = folium.Map(
                        location=[lat, lon], zoom_start=17,
                        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                        attr="Esri",
                    )
                    folium.Marker([lat, lon], popup=d["full_address"],
                                  icon=folium.Icon(color="orange", icon="home")).add_to(m_map)
                    st_folium(m_map, height=260, use_container_width=True)
                    links = photo_links(d["full_address"], lat, lon)
                    if GEO_OK and GOOGLE_MAPS_API_KEY and "Street View" in links:
                        st.image(links["Street View"], use_container_width=True)
                    ph_cols = st.columns(3)
                    skip = {"Street View", "Satellite"}
                    for i, (name, url) in enumerate([(k, v) for k, v in links.items() if k not in skip][:6]):
                        ph_cols[i % 3].link_button(name, url, use_container_width=True)
                else:
                    st.caption("Map unavailable — geocode returned no result.")
            else:
                st.info("Install `streamlit-folium` for satellite map.")

        st.divider()

        # Risk flags
        st.subheader("⚠️ Risk Flags")
        rm1, rm2, rm3, rm4, rm5 = st.columns(5)
        v_row = execute("SELECT arv_estimate, comp_count, confidence FROM valuations WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1", (parcel_id,))
        rm1.metric("ARV",         fmt_currency(v_row[0]["arv_estimate"]) if v_row else "—")
        liens_n  = execute("SELECT COUNT(*) AS n FROM liens        WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        perms_n  = execute("SELECT COUNT(*) AS n FROM permits      WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        viols_n  = execute("SELECT COUNT(*) AS n FROM violations   WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        fore_n   = execute("SELECT COUNT(*) AS n FROM foreclosures WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        rm2.metric("Liens",        liens_n,  delta="⚠️" if liens_n  else None, delta_color="inverse")
        rm3.metric("Permits",      perms_n)
        rm4.metric("Violations",   viols_n,  delta="⚠️" if viols_n  else None, delta_color="inverse")
        rm5.metric("Foreclosures", fore_n,   delta="⚠️" if fore_n   else None, delta_color="inverse")

        st.divider()

        # Last activity + next follow-up + next task summary
        sa1, sa2, sa3 = st.columns(3)
        last_act = execute("""
            SELECT contact_date, method, outcome, next_followup FROM lead_contact_log
            WHERE lead_id=%s ORDER BY contact_date DESC LIMIT 1
        """, (lead_id,))
        next_task = execute("""
            SELECT task_text, due_date, priority FROM work_tasks
            WHERE lead_id=%s AND is_done=FALSE ORDER BY due_date NULLS LAST LIMIT 1
        """, (lead_id,))
        saved_buyers_n = execute("SELECT COUNT(*) AS n FROM matched_buyers WHERE deal_id=%s", (deal_id,))[0]["n"]

        if last_act:
            la = last_act[0]
            icon = METHOD_ICON.get(la["method"], "📌")
            sa1.metric("Last Contact", str(la["contact_date"]))
            sa1.caption(f"{icon} {la['method']} — {la['outcome']}")
            if la["next_followup"]:
                n_fu = days_until(la["next_followup"])
                sa2.metric("Next Follow-up", str(la["next_followup"]),
                           delta=f"In {n_fu} days" if (n_fu is not None and n_fu >= 0)
                                 else f"{abs(n_fu or 0)} days overdue",
                           delta_color="normal" if (n_fu is not None and n_fu >= 0) else "inverse")
            else:
                sa2.metric("Next Follow-up", "Not set")
        else:
            sa1.metric("Last Contact", "Never")
            sa2.metric("Next Follow-up", "—")

        if next_task:
            nt = next_task[0]
            label = (nt["task_text"][:28] + "…") if len(nt["task_text"]) > 28 else nt["task_text"]
            sa3.metric("Next Task", label)
            if nt["due_date"]:
                sa3.caption(f"Due {nt['due_date']}  ·  {nt['priority']}")
        else:
            sa3.metric("Saved Buyers", saved_buyers_n)

    # ──────────────────────────────────────────────────────────────────────
    # DEAL NUMBERS TAB
    # ──────────────────────────────────────────────────────────────────────
    with t_deal:
        # Load building data for defaults
        _bldg_dn = execute("""
            SELECT living_area, year_built, bedrooms, full_baths, condition
            FROM buildings WHERE parcel_id=%s AND building_num=1 LIMIT 1
        """, (parcel_id,))
        _bld_dn   = _bldg_dn[0] if _bldg_dn else {}
        _sqft_dn  = float(_bld_dn.get("living_area") or 0)
        _yr_dn    = int(_bld_dn.get("year_built") or 1990)
        _cond_dn  = _bld_dn.get("condition") or "Average"
        _mktval   = float(d["total_mkt_val"] or 0)

        # Per-deal session key so switching deals resets analysis state
        _akey = f"mw_analysis_{deal_id}"

        # ── Analyze button + property parameter overrides ──────────────
        st.subheader("🧮 Analyze This Deal")
        ab1, ab2 = st.columns([1, 3])
        if ab1.button("▶️ Run Analysis", type="primary", use_container_width=True, key="mw_run_analysis"):
            st.session_state[_akey] = "running"
            st.rerun()

        with st.expander("⚙️ Override Property Parameters", expanded=not st.session_state.get(_akey)):
            pp1, pp2, pp3, pp4 = st.columns(4)
            ov_sqft = pp1.number_input(
                "Living Area (sqft)",
                min_value=0, max_value=50_000,
                value=int(_sqft_dn) if _sqft_dn else 0,
                step=100, key="dn_ov_sqft",
                help="Override if HCAD building data is missing or wrong",
            )
            ov_yr = pp2.number_input(
                "Year Built",
                min_value=1900, max_value=2026,
                value=_yr_dn, step=1, key="dn_ov_yr",
            )
            _cond_opts = ["Excellent","Good","Average","Fair","Low","Poor"]
            _cond_idx  = _cond_opts.index(_cond_dn) if _cond_dn in _cond_opts else 2
            ov_cond = pp3.selectbox("Condition", _cond_opts, index=_cond_idx, key="dn_ov_cond")
            ov_months = pp4.slider("Comp window (months)", 12, 60, 36, 6, key="dn_ov_months")

        # Use overrides (fall back to raw HCAD when 0)
        use_sqft = float(ov_sqft) if ov_sqft > 0 else (_sqft_dn or None)
        use_yr   = ov_yr
        use_cond = ov_cond

        # ── Run analysis ───────────────────────────────────────────────
        if st.session_state.get(_akey):
            with st.spinner("Finding comparable properties…"):
                comps    = find_comps(parcel_id, use_sqft, use_yr,
                                      d["situs_zip"] or "",
                                      n=15, months=ov_months,
                                      subject_value=_mktval if not use_sqft else None)
                arv_data = compute_arv(comps, use_sqft or _mktval / 150)
                repair   = estimate_repairs(use_cond, use_sqft or 1500)

            _arv_raw = arv_data["arv"] or 0

            st.divider()

            # ── Comp table ────────────────────────────────────────────
            st.subheader(f"🏘️ Comparable Properties ({len(comps)} found)")
            if comps:
                ds_label = "✅ Sold" if arv_data.get("data_source") == "sold" else "⚠️ HCAD Est."
                st.caption(
                    f"{arv_data.get('sold_comp_count',0)} sold · "
                    f"{arv_data['comp_count']} used for ARV · "
                    f"confidence: **{arv_data['confidence']}** · source: {ds_label}"
                )
                df_comps = pd.DataFrame([{
                    "Address":    c.get("full_address") or c.get("parcel_id",""),
                    "ZIP":        c.get("situs_zip",""),
                    "Sqft":       f"{int(c['living_area']):,}" if c.get("living_area") else "—",
                    "Year":       str(c.get("year_built") or "—"),
                    "Value":      fmt_currency(c.get("comp_value")),
                    "$/sqft":     fmt_currency(c["comp_value"] / c["living_area"])
                              if c.get("comp_value") and c.get("living_area") else "—",
                    "Source":     "✅ Sold" if c.get("comp_source") == "sold" else "⚠️ HCAD",
                    "Sale Date":  str(c["sale_dt"]) if c.get("sale_dt") else "—",
                } for c in comps[:15]])
                st.dataframe(df_comps, use_container_width=True, hide_index=True, height=280)
            else:
                st.warning("No comps found — try widening the comp window or ZIP radius.")

            st.divider()

            # ── ARV with granular override ─────────────────────────────
            st.subheader("🏡 After-Repair Value (ARV)")
            arv_l, arv_r = st.columns([1, 1])
            arv_l.metric(
                "Comp-Based ARV",
                fmt_currency(_arv_raw),
                delta=f"${arv_data['price_per_sqft']:,.0f}/sqft · {arv_data['comp_count']} comps",
                delta_color="off",
            )
            use_arv = arv_r.number_input(
                "ARV to Use ($)  ← override if needed",
                min_value=0, max_value=50_000_000,
                value=int(_arv_raw), step=5_000, key="dn_use_arv",
            )
            if use_arv != int(_arv_raw):
                arv_r.caption("✏️ Manually overridden")

            st.divider()

            # ── Repairs with granular override ────────────────────────
            st.subheader("🔨 Repair Estimate")
            _rep_lo  = repair["low"]
            _rep_hi  = repair["high"]
            _rep_mid = int((_rep_lo + _rep_hi) / 2)
            _rep_max = max(int(_rep_hi * 2), 500_000)

            rep_l, rep_r = st.columns([1, 1])
            rep_l.markdown(
                f"**Benchmark:** {fmt_currency(_rep_lo)} – {fmt_currency(_rep_hi)}  \n"
                f"Condition: **{use_cond}** · "
                f"{int(use_sqft or 1500):,} sqft · "
                f"${repair['rate_low']}–{repair['rate_high']}/sqft"
            )

            # Repair preset quick-select
            PRESETS = {
                "Light Touch (~$5k)":  5_000,
                "Cosmetic (~$15k)":   15_000,
                "Medium (~$30k)":     30_000,
                "Heavy (~$60k)":      60_000,
                "Full Gut (~$100k)": 100_000,
                "Custom":              None,
            }
            preset_lbl = rep_r.selectbox("Quick Preset", list(PRESETS.keys()),
                                          index=list(PRESETS.keys()).index("Custom"),
                                          key="dn_rep_preset")
            preset_val = PRESETS[preset_lbl]
            default_rep = preset_val if preset_val is not None else _rep_mid

            use_repair = st.slider(
                "Repair Cost ($)",
                min_value=0, max_value=_rep_max,
                value=min(default_rep, _rep_max),
                step=1_000, format="$%d", key="dn_use_repair",
            )
            # Granular repair line items (expandable)
            with st.expander("📋 Itemized Repair Breakdown"):
                ri1, ri2 = st.columns(2)
                r_roof    = ri1.number_input("Roof",             0, 100_000, 0,  1_000, key="dn_r_roof")
                r_hvac    = ri2.number_input("HVAC",             0,  50_000, 0,  1_000, key="dn_r_hvac")
                r_plumb   = ri1.number_input("Plumbing",         0,  50_000, 0,  1_000, key="dn_r_plumb")
                r_elec    = ri2.number_input("Electrical",       0,  50_000, 0,  1_000, key="dn_r_elec")
                r_kitchen = ri1.number_input("Kitchen",          0,  60_000, 0,  1_000, key="dn_r_kitchen")
                r_bath    = ri2.number_input("Bathrooms",        0,  40_000, 0,  1_000, key="dn_r_bath")
                r_floors  = ri1.number_input("Flooring",         0,  30_000, 0,  1_000, key="dn_r_floors")
                r_paint   = ri2.number_input("Paint / Drywall",  0,  30_000, 0,  1_000, key="dn_r_paint")
                r_windows = ri1.number_input("Windows / Doors",  0,  30_000, 0,  1_000, key="dn_r_windows")
                r_demo    = ri2.number_input("Demo / Haul-off",  0,  20_000, 0,  500,   key="dn_r_demo")
                r_other   = ri1.number_input("Other / Misc",     0, 100_000, 0,  1_000, key="dn_r_other")
                r_contin  = ri2.number_input("Contingency (10%)", 0, 100_000,
                                              int(use_repair * 0.10), 500, key="dn_r_contin")
                itemized_total = (r_roof + r_hvac + r_plumb + r_elec + r_kitchen +
                                  r_bath + r_floors + r_paint + r_windows + r_demo +
                                  r_other + r_contin)
                if itemized_total > 0:
                    st.metric("Itemized Total", fmt_currency(itemized_total))
                    if st.button("⬆️ Use Itemized Total as Repair Cost", key="dn_use_itemized"):
                        st.session_state["dn_use_repair"] = min(itemized_total, _rep_max)
                        st.rerun()

            st.divider()

            # ── MAO Table ─────────────────────────────────────────────
            st.subheader("📊 Maximum Allowable Offer (MAO)")
            _mao = compute_mao(use_arv, use_repair) if use_arv else {}
            m_cls = 3_000  # closing costs estimate
            mm1, mm2, mm3, mm4 = st.columns(4)
            mm1.metric("ARV Used",          fmt_currency(use_arv))
            mm2.metric("Repairs",           fmt_currency(use_repair))
            mm3.metric("Conservative 60%",  fmt_currency(_mao.get("conservative", 0)))
            mm4.metric("Standard 65%",      fmt_currency(_mao.get("standard", 0)),
                       delta="Target offer")

            # Gap vs HCAD value
            if _mktval and _mao.get("standard"):
                gap = _mktval - _mao["standard"]
                if gap > 0:
                    st.warning(
                        f"HCAD values this at **{fmt_currency(_mktval)}** — you need to negotiate "
                        f"**{fmt_currency(gap)} below** HCAD to hit your 65% MAO."
                    )
                else:
                    st.success(
                        f"HCAD values this at **{fmt_currency(_mktval)}** — already "
                        f"**{fmt_currency(abs(gap))} below** your 65% MAO. "
                        f"Potential fee spread of {fmt_currency(abs(gap))}."
                    )

            st.divider()

            # ── Deal Type Calculator ───────────────────────────────────
            st.subheader("🏷️ Deal Type Calculator")
            deal_repair = st.slider(
                "Repair cost used in deal math ($)",
                0, _rep_max, use_repair, 1_000, format="$%d", key="dn_deal_repairs",
            )

            dtab_ws, dtab_ff, dtab_bh, dtab_brr, dtab_nov = st.tabs([
                "🏷️ Wholesale", "🔨 Fix & Flip", "🏡 Buy & Hold", "♻️ BRRRR", "🤝 Novation"
            ])

            with dtab_ws:
                st.markdown("**Wholesale — Assign the Contract**")
                dw1, dw2, dw3 = st.columns(3)
                d_arv_pct = dw1.radio("Buyer ARV %", [60, 65, 70], index=1,
                                       horizontal=True, format_func=lambda x: f"{x}%", key="dn_ws_pct")
                d_assign  = dw2.number_input("Your Assignment Fee ($)", 0, 5_000_000,
                                              int(d["assignment_fee_target"] or 10_000),
                                              500, key="dn_ws_fee")
                d_close   = dw3.number_input("Closing Costs ($)", 0, 50_000, 3_000, 500, key="dn_ws_cls")
                d_mao     = max(0.0, use_arv * (d_arv_pct / 100) - deal_repair - d_close)
                d_seller  = max(0.0, d_mao - d_assign)
                with st.container(border=True):
                    dw_a, dw_b, dw_c, dw_d = st.columns(4)
                    dw_a.metric("ARV",                fmt_currency(use_arv))
                    dw_b.metric(f"MAO ({d_arv_pct}%)", fmt_currency(d_mao))
                    dw_c.metric("Max Offer to Seller", fmt_currency(d_seller),
                                delta=f"vs contract {fmt_currency(d['purchase_price'])}"
                                if d["purchase_price"] else None, delta_color="off")
                    dw_d.metric("Your Fee",            fmt_currency(d_assign),
                                delta="✅ Profitable" if d_assign > 0 else None)
                if st.button("💾 Save Wholesale Offer", key="dn_ws_save", type="primary"):
                    execute("""
                        UPDATE active_deals SET assignment_fee_target=%s WHERE id=%s
                    """, (d_assign, deal_id), commit=True)
                    execute("""
                        INSERT INTO offer_options
                            (lead_id, scenario, arv, arv_pct, repair_cost, offer_price, target_fee, feasible, calc_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    """, (lead_id, f"Wholesale {d_arv_pct}%",
                          use_arv, d_arv_pct, deal_repair, d_seller, d_assign, d_seller > 0), commit=True)
                    st.success("Saved!")
                    st.rerun()

            with dtab_ff:
                st.markdown("**Fix & Flip — Rehab & Resell**")
                ff1, ff2, ff3 = st.columns(3)
                ff_profit  = ff1.slider("Profit target %", 10, 30, 15, key="dn_ff_profit") / 100
                ff_months  = ff2.slider("Holding months",  2, 12,  4, key="dn_ff_months")
                ff_closing = ff3.slider("Closing costs %",  1,  8,  4, key="dn_ff_closing") / 100
                ff_rate    = ff1.slider("Monthly holding rate %", 0, 2, 1, key="dn_ff_rate") / 100
                flip = compute_flip_offer(use_arv, deal_repair, ff_profit, ff_months, ff_rate / 12 if ff_rate else 0.005, ff_closing)
                with st.container(border=True):
                    fm1, fm2, fm3, fm4 = st.columns(4)
                    fm1.metric("Sale Price (ARV)", fmt_currency(use_arv))
                    fm2.metric("Repairs",          fmt_currency(deal_repair))
                    fm3.metric("Profit Target",    fmt_currency(flip["profit_target"]))
                    fm4.metric("Max Offer",        fmt_currency(flip["max_offer"]),
                               delta="Buy at or below this")
                st.caption(f"Holding: {fmt_currency(flip['holding_costs'])} · Closing: {fmt_currency(flip['closing_costs'])}")
                if st.button("💾 Save Flip Offer", key="dn_ff_save"):
                    execute("""
                        INSERT INTO offer_options
                            (lead_id, scenario, arv, repair_cost, offer_price, target_fee, feasible, calc_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                    """, (lead_id, f"Fix & Flip {int(ff_profit*100)}% profit",
                          use_arv, deal_repair, flip["max_offer"], 0, flip["max_offer"] > 0), commit=True)
                    st.success("Saved!")

            with dtab_bh:
                st.markdown("**Buy & Hold — Long-Term Rental**")
                bh1, bh2, bh3, bh4 = st.columns(4)
                _bh_def  = min(max(0, int(use_arv * 0.70 - deal_repair)), 20_000_000)
                bh_price = bh1.number_input("Purchase Price ($)", 0, 20_000_000, _bh_def, 1_000, key="dn_bh_price")
                bh_rent  = bh2.number_input("Monthly Rent ($)", 0, 50_000, 1_400, 50, key="dn_bh_rent")
                bh_down  = bh3.slider("Down Payment %", 5, 30, 20, key="dn_bh_down") / 100
                bh_rate  = bh4.slider("Loan Rate %", 3, 12, 7, key="dn_bh_rate") / 100
                hold = compute_hold(use_arv, bh_price, bh_rent * 12, down_pct=bh_down, rate=bh_rate)
                with st.container(border=True):
                    hm1, hm2, hm3, hm4 = st.columns(4)
                    hm1.metric("Monthly Cash Flow", fmt_currency(hold["annual_cash_flow"] / 12),
                               delta_color="normal" if hold["annual_cash_flow"] > 0 else "inverse")
                    hm2.metric("Cap Rate",     f"{hold['cap_rate'] * 100:.2f}%")
                    hm3.metric("Cash-on-Cash", f"{hold['coc_return'] * 100:.2f}%")
                    hm4.metric("GRM",          f"{hold['gross_rent_multiplier']:.1f}x")
                st.caption(
                    f"Down: {fmt_currency(bh_price * bh_down)} · "
                    f"Annual NOI: {fmt_currency(hold['noi'])} · "
                    f"Rate: {bh_rate*100:.1f}%"
                )

            with dtab_brr:
                st.markdown("**BRRRR — Buy · Rehab · Rent · Refinance · Repeat**")
                br1, br2, br3, br4 = st.columns(4)
                _brr_def  = min(max(0, int(use_arv * 0.65 - deal_repair)), 20_000_000)
                brr_price = br1.number_input("Purchase Price ($)", 0, 20_000_000, _brr_def, 1_000, key="dn_brr_price")
                brr_rent  = br2.number_input("Monthly Rent ($)", 0, 50_000, 1_400, 50, key="dn_brr_rent")
                brr_ltv   = br3.slider("Refi LTV %", 60, 80, 75, key="dn_brr_ltv") / 100
                brr_rate  = br4.slider("Refi Rate %", 3, 12, 7, key="dn_brr_rate") / 100
                brr = compute_brrr(use_arv, deal_repair, brr_price,
                                   refi_ltv=brr_ltv, annual_rent=brr_rent * 12,
                                   refi_rate=brr_rate)
                with st.container(border=True):
                    bm1, bm2, bm3, bm4 = st.columns(4)
                    bm1.metric("Total Invested",   fmt_currency(brr["total_invested"]))
                    bm2.metric("Refi Loan",        fmt_currency(brr["refi_loan_amount"]))
                    bm3.metric("Cash Out at Refi", fmt_currency(brr["cash_out"]),
                               delta="✅ Got money back" if brr["cash_out"] >= 0 else "❌ Cash in",
                               delta_color="normal" if brr["cash_out"] >= 0 else "inverse")
                    bm4.metric("Equity Remaining", fmt_currency(brr["equity_remaining"]))
                st.caption(
                    f"All-in cost: {fmt_currency(brr_price + deal_repair)} · "
                    f"Refi at {brr_ltv*100:.0f}% LTV of {fmt_currency(use_arv)}"
                )

            with dtab_nov:
                st.markdown("**Novation — List on the Seller's Behalf**")
                nv1, nv2, nv3 = st.columns(3)
                nov_agent   = nv1.slider("Agent Commission %", 3, 8, 6, key="dn_nov_agent") / 100
                nov_cont    = nv2.number_input("Contingency ($)", 0, 100_000, 5_000, 500, key="dn_nov_cont")
                nov_repairs = nv3.number_input("Repair Credit ($)", 0, 500_000, use_repair, 500, key="dn_nov_rep")
                nov = compute_novation(use_arv, nov_repairs, nov_agent, nov_cont)
                with st.container(border=True):
                    nm1, nm2, nm3, nm4 = st.columns(4)
                    nm1.metric("List Price (ARV)",  fmt_currency(nov["list_price"]))
                    nm2.metric("Agent Fees",        fmt_currency(nov["agent_fees"]))
                    nm3.metric("Net to Seller",     fmt_currency(nov["net_to_seller"]))
                    nm4.metric("Your Spread",       fmt_currency(nov["investor_spread"]),
                               delta="Your earnings")

            st.divider()

            # ── Save full analysis ─────────────────────────────────────
            sa1, sa2 = st.columns(2)
            if sa1.button("💾 Save Analysis to Deal Record", type="primary", use_container_width=True, key="dn_save_analysis"):
                save_valuation(parcel_id, use_arv,
                               arv_data["price_per_sqft"], arv_data["comp_count"],
                               arv_data["confidence"])
                save_repair_estimate(parcel_id, use_cond, repair)
                st.success("Analysis saved — ARV and repair estimate updated in records!")
                st.rerun()
            if sa2.button("🔄 Re-Run Analysis", use_container_width=True, key="dn_rerun"):
                st.session_state[_akey] = "running"
                st.rerun()

        else:
            # ── No analysis run yet: show last saved values ────────────
            latest_val = execute("""
                SELECT arv_estimate, comp_count, confidence, calc_date, price_per_sqft
                FROM valuations WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1
            """, (parcel_id,))
            latest_rep = execute("""
                SELECT condition_tier, total_low, total_high, created_date
                FROM repair_estimates WHERE parcel_id=%s ORDER BY created_date DESC LIMIT 1
            """, (parcel_id,))
            if latest_val or latest_rep:
                pr1, pr2 = st.columns(2)
                if latest_val:
                    v = latest_val[0]
                    pr1.metric("Last Saved ARV",    fmt_currency(v["arv_estimate"]))
                    pr1.caption(f"Comps: {v['comp_count']} · {v['confidence']} confidence · {v['calc_date'] or '—'}")
                if latest_rep:
                    r = latest_rep[0]
                    pr2.metric("Last Saved Repairs",
                               f"{fmt_currency(r['total_low'])} – {fmt_currency(r['total_high'])}")
                    pr2.caption(f"Tier: {r['condition_tier'] or '—'} · {r['created_date'].date() if r['created_date'] else '—'}")
                st.info("👆 Click **▶️ Run Analysis** to refresh with current comps and live calculations.")
            else:
                st.info("No analysis run yet. Click **▶️ Run Analysis** above to find comps and calculate ARV, repairs, and MAO.")

        # ── Saved Offer Scenarios ──────────────────────────────────────
        latest_offers = execute("""
            SELECT scenario, arv, arv_pct, repair_cost, offer_price, target_fee,
                   buyer_profit, feasible, calc_date
            FROM offer_options WHERE lead_id=%s ORDER BY calc_date DESC LIMIT 6
        """, (lead_id,))
        if latest_offers:
            st.divider()
            st.subheader("📋 Saved Offer Scenarios")
            df_off = pd.DataFrame([{
                "Scenario":     o["scenario"] or "—",
                "ARV":          fmt_currency(o["arv"]),
                "% ARV":        f"{o['arv_pct']}%" if o["arv_pct"] else "—",
                "Repairs":      fmt_currency(o["repair_cost"]),
                "Offer Price":  fmt_currency(o["offer_price"]),
                "Target Fee":   fmt_currency(o["target_fee"]),
                "Feasible":     "✅" if o["feasible"] else "❌",
                "Date":         str(o["calc_date"]) if o["calc_date"] else "—",
            } for o in latest_offers])
            st.dataframe(df_off, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("✏️ Record Contract Numbers")
        with st.form("mw_financials"):
            fc1, fc2, fc3 = st.columns(3)
            new_price = fc1.number_input("Purchase Price ($)", min_value=0,
                                          value=int(d["purchase_price"] or 0), step=1000)
            new_fee   = fc2.number_input("Assignment Fee Target ($)", min_value=0,
                                          value=int(d["assignment_fee_target"] or 0), step=500)
            new_em    = fc3.number_input("Earnest Money ($)", min_value=0,
                                          value=int(d["earnest_money_amount"] or 0), step=100)
            fc4, fc5 = st.columns(2)
            em_opts   = ["pending","received","forfeited","returned"]
            em_idx    = em_opts.index(d["em_status"]) if d["em_status"] in em_opts else 0
            new_em_st = fc4.selectbox("EM Status", em_opts, index=em_idx)
            new_opt   = fc5.number_input("Option Period (days)", min_value=0,
                                          value=d["option_period_days"] or 10, step=1)
            new_notes = st.text_area("Deal Notes", value=d["notes"] or "", height=60)
            if st.form_submit_button("💾 Save", type="primary"):
                execute("""
                    UPDATE active_deals SET
                        purchase_price=%s, assignment_fee_target=%s,
                        earnest_money_amount=%s, em_status=%s,
                        option_period_days=%s, notes=%s
                    WHERE id=%s
                """, (new_price or None, new_fee or None, new_em or None,
                      new_em_st, new_opt or None, new_notes.strip() or None, deal_id), commit=True)
                st.success("Saved!")
                st.rerun()

        st.divider()
        st.subheader("🏷️ Assignment Fee Calculator")
        ap1, ap2 = st.columns(2)
        fc_contract = ap1.number_input("Your Contract Price (pay to seller) ($)",
                                        min_value=0, value=int(d["purchase_price"] or 0),
                                        step=1000, key="mw_dn_contract")
        fc_assign   = ap2.number_input("Your Assignment Price (buyer pays you) ($)",
                                        min_value=0, value=int(d.get("assignment_price") or 0),
                                        step=1000, key="mw_dn_assign")
        fc_fee = fc_assign - fc_contract
        mf1, mf2, mf3 = st.columns(3)
        mf1.metric("Contract Price",   fmt_currency(fc_contract))
        mf2.metric("Assignment Price", fmt_currency(fc_assign))
        mf3.metric("🏷️ YOUR FEE",      fmt_currency(fc_fee),
                   delta="✅ Profit" if fc_fee > 0 else ("❌ Negative" if fc_contract > 0 else "Enter prices"),
                   delta_color="normal" if fc_fee > 0 else "inverse")
        if st.button("💾 Save These Numbers", key="mw_dn_save", type="primary"):
            execute("""
                UPDATE active_deals SET
                    purchase_price=%s, assignment_price=%s, assignment_fee_target=%s
                WHERE id=%s
            """, (fc_contract or None, fc_assign or None, max(0, fc_fee) or None, deal_id), commit=True)
            execute("""
                INSERT INTO offer_options
                    (lead_id, scenario, offer_price, target_fee, feasible, calc_date)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (lead_id,
                  f"Contract ${fc_contract:,} → Assign ${fc_assign:,}",
                  fc_contract, max(0, fc_fee), fc_fee > 0), commit=True)
            st.success("Saved!")
            st.rerun()

    # ──────────────────────────────────────────────────────────────────────
    # SELLER TAB
    # ──────────────────────────────────────────────────────────────────────
    with t_seller:
        sel_left, sel_right = st.columns([1, 1])

        with sel_left:
            st.subheader("🧑 Contact Info")
            with st.form("mw_seller"):
                se1, se2 = st.columns(2)
                s_name  = se1.text_input("Seller Full Name",  value=d["seller_name"]  or "")
                s_phone = se2.text_input("Seller Phone",      value=d["seller_phone"] or "")
                s_email = se1.text_input("Seller Email",      value=d["seller_email"] or "")
                s_title = se2.text_input("Title Company",     value=d["title_company"] or "")
                s_tcon  = se1.text_input("Title Co. Contact", value=d["title_company_contact"] or "")
                st.markdown("**Contract Dates**")
                dc1, dc2, dc3 = st.columns(3)
                today      = datetime.date.today()
                s_contract = dc1.date_input("Contract Date", value=d["contract_date"]  or today)
                s_opt_exp  = dc2.date_input("Option Expiry", value=d["option_expiry"]  or today)
                s_closing  = dc3.date_input("Closing Date",  value=d["closing_date"]   or today)
                if st.form_submit_button("💾 Save", type="primary"):
                    execute("""
                        UPDATE active_deals SET
                            seller_name=%s, seller_phone=%s, seller_email=%s,
                            title_company=%s, title_company_contact=%s,
                            contract_date=%s, option_expiry=%s, closing_date=%s
                        WHERE id=%s
                    """, (s_name.strip() or None, s_phone.strip() or None,
                          s_email.strip() or None, s_title.strip() or None,
                          s_tcon.strip() or None,
                          s_contract, s_opt_exp, s_closing, deal_id), commit=True)
                    st.success("Saved!")
                    st.rerun()

        with sel_right:
            st.subheader("🎯 Motivation & Strategy")
            with st.form("mw_motivation"):
                mot_score = st.slider(
                    "Seller Motivation Score (1 = cold, 10 = desperate)",
                    min_value=1, max_value=10,
                    value=d.get("motivation_score") or 5,
                )
                mot_labels = {
                    1:"❄️ Cold — just curious",  2:"❄️ Very low motivation",
                    3:"🟦 Low — open but no urgency", 4:"🟦 Slightly motivated",
                    5:"🟡 Moderate — willing to negotiate", 6:"🟡 Getting motivated",
                    7:"🟠 High — real urgency present", 8:"🟠 Very motivated",
                    9:"🔴 Highly motivated", 10:"🔴 FIRE SALE — needs out NOW",
                }
                st.caption(mot_labels.get(mot_score, ""))

                current_types = [t.strip() for t in (d.get("seller_type") or "").split(",") if t.strip()]
                sel_types = st.multiselect(
                    "Motivation Categories",
                    SELLER_TYPES,
                    default=[t for t in current_types if t in SELLER_TYPES],
                )
                best_call = st.text_input(
                    "Best Time to Call",
                    value=d.get("best_call_time") or "",
                    placeholder="e.g. Weekdays 6–8pm, mornings only",
                )
                if st.form_submit_button("💾 Save Motivation", type="primary"):
                    execute("""
                        UPDATE active_deals SET motivation_score=%s, seller_type=%s, best_call_time=%s
                        WHERE id=%s
                    """, (mot_score, ", ".join(sel_types) or None,
                          best_call.strip() or None, deal_id), commit=True)
                    st.success("Saved!")
                    st.rerun()

            st.markdown("---")
            st.subheader("📞 Call Script Helper")
            script_type = st.selectbox("Script for:", [
                "Opening Call", "Follow-up", "Making an Offer",
                "Objection: Price Too Low", "Closing the Deal",
            ])
            scripts = {
                "Opening Call": (
                    f"Hi, is this the owner of {d['full_address']}? My name is [YOUR NAME] — "
                    "I'm a local real estate investor. I know this might be unexpected, but I was "
                    "wondering if you'd ever considered selling your property? I buy homes as-is "
                    "for cash and can close on your timeline."
                ),
                "Follow-up": (
                    f"Hi [SELLER NAME], this is [YOUR NAME] following up about {d['full_address']}. "
                    "I wanted to check in — have you given any more thought to our conversation? "
                    "Is there anything I can do to make this easier for you?"
                ),
                "Making an Offer": (
                    f"Based on the condition and what similar homes are selling for, the best I can "
                    f"do is ${int(d['purchase_price'] or 0):,}. I know that's not retail, but I'm "
                    "buying as-is, paying all cash, no agent fees, and we can close in as little as "
                    "[X] days — on your schedule. Does that work for you?"
                ),
                "Objection: Price Too Low": (
                    "I completely understand — you want to maximize what you get. The thing is, "
                    "I'm not paying retail because I take on all the risk and repair costs myself. "
                    "A retail buyer needs inspections, financing, and months. My offer is certainty. "
                    "What number would make sense for you?"
                ),
                "Closing the Deal": (
                    "I think we're close. If we can agree on [PRICE] today, I can have a contract "
                    "to you tomorrow and pick a closing date that works for your situation. "
                    "Does [DATE] give you enough time?"
                ),
            }
            st.code(scripts[script_type], language=None)

        st.divider()
        st.subheader("📋 Seller Facts Log")
        st.caption("Each fact is saved separately with its own date stamp — add as many as you want.")

        with st.form("mw_seller_notes"):
            s_fact_new = st.text_area(
                "New Fact / Note",
                height=90,
                placeholder=(
                    "e.g. Behind 3 months on mortgage · going through divorce · "
                    "wants to close in 30 days · inherited the property · won't take less than $X"
                ),
            )
            if st.form_submit_button("💾 Save Fact", type="primary"):
                if s_fact_new.strip():
                    execute("INSERT INTO seller_facts (deal_id, fact_text) VALUES (%s, %s)",
                            (deal_id, s_fact_new.strip()), commit=True)
                    st.success("Fact saved!")
                    st.rerun()

        facts = execute("""
            SELECT id, fact_text, created_at FROM seller_facts
            WHERE deal_id=%s ORDER BY created_at DESC
        """, (deal_id,), commit=False)

        if facts:
            st.markdown(f"**{len(facts)} saved fact{'s' if len(facts)>1 else ''}** (newest first):")
            for f in facts:
                ts = f["created_at"].strftime("%b %d, %Y  %I:%M %p") if f["created_at"] else "—"
                with st.container(border=True):
                    fc_t, fc_d = st.columns([6, 1])
                    fc_t.markdown(f["fact_text"])
                    fc_t.caption(f"🕐 {ts}")
                    if fc_d.button("🗑️", key=f"del_fact_{f['id']}", help="Delete this fact"):
                        execute("DELETE FROM seller_facts WHERE id=%s", (f["id"],), commit=True)
                        st.rerun()
        else:
            st.info("No facts saved yet — add one above.")

    # ──────────────────────────────────────────────────────────────────────
    # ACTIVITY LOG TAB
    # ──────────────────────────────────────────────────────────────────────
    with t_act:
        logs = execute("""
            SELECT id, contact_date, method, outcome, notes, next_followup, script_used
            FROM lead_contact_log WHERE lead_id=%s ORDER BY contact_date DESC
        """, (lead_id,))

        # Overdue / upcoming follow-up alert
        upcoming_fu = [l for l in logs if l["next_followup"]]
        if upcoming_fu:
            soonest_fu = min(upcoming_fu, key=lambda x: x["next_followup"])
            n_fu       = days_until(soonest_fu["next_followup"])
            if n_fu is not None and n_fu <= 0:
                st.error(f"🚨 Follow-up was due **{soonest_fu['next_followup']}** — {soonest_fu['method']} · {soonest_fu['outcome']}")
            elif n_fu is not None and n_fu <= 2:
                st.warning(f"⏰ Follow-up in **{n_fu} days** ({soonest_fu['next_followup']})")

        a1, a2, a3 = st.columns(3)
        a1.metric("Total Contacts", len(logs))
        a2.metric("Last Contact",   str(logs[0]["contact_date"]) if logs else "Never")
        a3.metric("Next Follow-up", str(upcoming_fu[0]["next_followup"]) if upcoming_fu else "None set")

        with st.expander("➕ Log New Activity", expanded=(len(logs) == 0)):
            with st.form("mw_activity"):
                al1, al2 = st.columns(2)
                act_method  = al1.selectbox("Method", list(METHOD_ICON.keys()))
                act_outcome = al2.selectbox("Outcome", [
                    "No answer","Left voicemail","Spoke — not interested",
                    "Spoke — interested","Appointment set","Letter sent",
                    "Offer made","Offer accepted","Offer rejected","Other",
                ])
                act_notes = st.text_area("Notes", height=70,
                                          placeholder="What was said? Motivation details?")
                al3, al4 = st.columns(2)
                act_date     = al3.date_input("Contact Date",  value=datetime.date.today())
                act_followup = al4.date_input("Next Follow-up",
                                              value=datetime.date.today() + datetime.timedelta(days=3))
                act_script = st.text_area("Script / Talking Points Used", height=45)
                if st.form_submit_button("💾 Log Activity", type="primary"):
                    execute("""
                        INSERT INTO lead_contact_log
                            (lead_id, contact_date, method, outcome, notes, next_followup, script_used)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """, (lead_id, act_date, act_method, act_outcome,
                          act_notes.strip() or None, act_followup,
                          act_script.strip() or None), commit=True)
                    st.success("Logged!")
                    st.rerun()

        if not logs:
            st.info("No activity logged yet — click ➕ above to log your first contact.")
        else:
            st.subheader(f"📅 History ({len(logs)} entries)")
            for entry in logs:
                icon         = METHOD_ICON.get(entry["method"], "📌")
                dot          = OUTCOME_DOT.get(entry["outcome"], "🟡")
                overdue_e    = entry["next_followup"] and days_until(entry["next_followup"]) is not None and days_until(entry["next_followup"]) < 0
                with st.container(border=True):
                    la, lb, lc, ld = st.columns([2, 2, 2, 1])
                    la.markdown(f"**{icon} {entry['method']}**")
                    la.caption(str(entry["contact_date"]))
                    lb.markdown(f"{dot} {entry['outcome']}")
                    if entry["next_followup"]:
                        fu_txt = f"🚨 **{entry['next_followup']}**" if overdue_e else f"📅 {entry['next_followup']}"
                        lc.markdown(f"Follow-up: {fu_txt}")
                    if entry["notes"]:
                        st.markdown(f"_{entry['notes']}_")
                    if entry["script_used"]:
                        with st.expander("Talking points"):
                            st.text(entry["script_used"])
                    if ld.button("🗑️", key=f"del_log_{entry['id']}", help="Delete"):
                        execute("DELETE FROM lead_contact_log WHERE id=%s", (entry["id"],), commit=True)
                        st.rerun()

    # ──────────────────────────────────────────────────────────────────────
    # TASKS TAB
    # ──────────────────────────────────────────────────────────────────────
    with t_tasks:
        tasks = execute("""
            SELECT id, task_text, due_date, priority, is_done, created_at, completed_at
            FROM work_tasks WHERE lead_id=%s
            ORDER BY is_done,
                     CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     due_date NULLS LAST
        """, (lead_id,))

        pending = [t for t in tasks if not t["is_done"]]
        done    = [t for t in tasks if t["is_done"]]

        tk_a, tk_b, tk_c = st.columns(3)
        tk_a.metric("Pending", len(pending))
        tk_b.metric("Completed", len(done))
        tk_c.metric("Total", len(tasks))

        with st.form("mw_new_task"):
            tk1, tk2, tk3, tk4 = st.columns([3, 1, 1, 1])
            task_txt = tk1.text_input("New Task", placeholder="Call seller, pull title, schedule walkthrough…")
            task_due = tk2.date_input("Due Date", value=None)
            task_pri = tk3.selectbox("Priority", ["high","normal","low"])
            if tk4.form_submit_button("➕ Add", use_container_width=True, type="primary"):
                if task_txt.strip():
                    execute("INSERT INTO work_tasks (lead_id, task_text, due_date, priority) VALUES (%s,%s,%s,%s)",
                            (lead_id, task_txt.strip(), task_due, task_pri), commit=True)
                    st.rerun()

        st.divider()

        if not pending and not done:
            st.info("No tasks yet — add one above or quick-add from the checklist below.")
        else:
            if pending:
                for t in pending:
                    overdue_t = t["due_date"] and t["due_date"] < datetime.date.today()
                    pri  = PRI_ICON.get(t["priority"], "⚪")
                    due  = f" · Due **{t['due_date']}**" if t["due_date"] else ""
                    line = f"{'🚨 ' if overdue_t else ''}{pri} {t['task_text']}{due}"
                    tc1, tc2, tc3 = st.columns([6, 1, 1])
                    tc1.markdown(line)
                    if tc2.button("✅", key=f"tk_done_{t['id']}", help="Mark complete"):
                        execute("UPDATE work_tasks SET is_done=TRUE, completed_at=NOW() WHERE id=%s",
                                (t["id"],), commit=True)
                        st.rerun()
                    if tc3.button("🗑️", key=f"tk_del_{t['id']}", help="Delete"):
                        execute("DELETE FROM work_tasks WHERE id=%s", (t["id"],), commit=True)
                        st.rerun()
            else:
                st.success("🎉 All tasks complete!")

            if done:
                with st.expander(f"✅ Completed ({len(done)})"):
                    for t in done:
                        done_dt = t["completed_at"].date() if t["completed_at"] else "?"
                        st.markdown(f"~~{t['task_text']}~~ · {done_dt}")

        st.divider()
        st.caption("**Quick-add standard wholesaling tasks:**")
        STANDARD = [
            ("Verify seller motivation & situation", "high"),
            ("Pull comparable sales (comps)", "high"),
            ("Run repair estimate", "high"),
            ("Calculate MAO / max offer price", "high"),
            ("Order title search / check liens & taxes", "high"),
            ("Make verbal offer to seller", "high"),
            ("Send written offer / PSA contract", "high"),
            ("Execute purchase & sale agreement", "high"),
            ("Collect Proof of Funds from buyer", "normal"),
            ("Schedule walkthrough / inspection", "normal"),
            ("Blast deal to buyers list", "normal"),
            ("Upload signed contract to document vault", "normal"),
            ("Confirm title is clear to close", "normal"),
            ("Coordinate closing with title company", "normal"),
            ("Collect assignment fee at closing", "normal"),
            ("Follow up for testimonial / referral", "low"),
        ]
        existing_text = {t["task_text"] for t in tasks}
        sc = st.columns(2)
        for i, (txt, pri) in enumerate(STANDARD):
            if txt not in existing_text:
                if sc[i % 2].button(f"+ {txt}", key=f"std_{i}", use_container_width=True):
                    execute("INSERT INTO work_tasks (lead_id, task_text, priority) VALUES (%s,%s,%s)",
                            (lead_id, txt, pri), commit=True)
                    st.rerun()

    # ──────────────────────────────────────────────────────────────────────
    # BUYERS TAB
    # ──────────────────────────────────────────────────────────────────────
    with t_buyers:
        # Deal blast template expander
        with st.expander("📣 Generate Deal Blast Message"):
            arv_bl  = execute("SELECT arv_estimate FROM valuations WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1", (parcel_id,))
            rep_bl  = execute("SELECT total_low, total_high FROM repair_estimates WHERE parcel_id=%s ORDER BY created_date DESC LIMIT 1", (parcel_id,))
            bldg_bl = execute("SELECT living_area, year_built, bedrooms, full_baths FROM buildings WHERE parcel_id=%s AND building_num=1 LIMIT 1", (parcel_id,))
            bld_bl  = bldg_bl[0] if bldg_bl else {}
            arv_bl_s = fmt_currency(arv_bl[0]["arv_estimate"]) if arv_bl else "TBD"
            rep_bl_s = f"{fmt_currency(rep_bl[0]['total_low'])}–{fmt_currency(rep_bl[0]['total_high'])}" if rep_bl else "TBD"
            sqft_bl  = f"{int(bld_bl['living_area']):,} sqft" if bld_bl.get("living_area") else "—"
            blast = (
                f"🏠 DEAL ALERT — {d['full_address']}, {d['situs_zip']}\n\n"
                f"🛏 {bld_bl.get('bedrooms','?')} bed / {bld_bl.get('full_baths','?')} bath  |  {sqft_bl}  |  Built {bld_bl.get('year_built','?')}\n"
                f"💰 ARV: {arv_bl_s}  |  Est. Repairs: {rep_bl_s}\n"
                f"🏷 Asking: {fmt_currency(d['purchase_price']) if d['purchase_price'] else 'Make offer'}\n\n"
                f"Reply INTERESTED or call me for deal details!"
            )
            st.code(blast, language=None)
            st.caption("Copy → text or email to your buyers list.")

        # Matched buyers summary
        matched = execute("""
            SELECT mb.id, mb.match_score, mb.notified, mb.notified_date, mb.response,
                   mb.notes AS buyer_notes, mb.response_date,
                   cb.id AS buyer_id, cb.display_name, cb.entity_type, cb.deals_closed,
                   bc.full_name AS contact_name, bc.phone, bc.email, bc.cell_phone
            FROM matched_buyers mb
            JOIN cash_buyers cb ON cb.id = mb.buyer_id
            LEFT JOIN buyer_contacts bc ON bc.buyer_id = cb.id AND bc.is_primary = TRUE
            WHERE mb.deal_id = %s
            ORDER BY mb.match_score DESC NULLS LAST, cb.deals_closed DESC NULLS LAST
        """, (deal_id,))

        notified_n   = sum(1 for m in matched if m["notified"])
        interested_n = sum(1 for m in matched if (m["response"] or "").lower() in
                          ("interested","yes","in","interested"))
        mb1, mb2, mb3 = st.columns(3)
        mb1.metric("Saved Buyers", len(matched))
        mb2.metric("Notified",     notified_n)
        mb3.metric("Interested",   interested_n)

        if matched:
            st.subheader(f"📋 Saved Buyers")
            bulk1, bulk2 = st.columns(2)
            if bulk1.button("📨 Mark All as Notified", use_container_width=True):
                execute("""
                    UPDATE matched_buyers SET notified=TRUE, notified_date=NOW()
                    WHERE deal_id=%s AND notified=FALSE
                """, (deal_id,), commit=True)
                st.success("All marked notified!")
                st.rerun()

            resp_filter = bulk2.selectbox(
                "Filter",
                ["All","Not notified","Notified","Interested","Passed"],
                key="mw_buyer_filter",
                label_visibility="collapsed",
            )

            for m in matched:
                if resp_filter == "Not notified" and m["notified"]:
                    continue
                if resp_filter == "Notified" and not m["notified"]:
                    continue
                resp_lower = (m["response"] or "").lower()
                if resp_filter == "Interested" and resp_lower not in ("interested","yes","in"):
                    continue
                if resp_filter == "Passed" and resp_lower not in ("no","pass","passed","not interested"):
                    continue

                phone_str = m["phone"] or m["cell_phone"] or "—"
                with st.container(border=True):
                    mc1, mc2, mc3, mc4 = st.columns([3, 2, 2, 2])
                    score_badge = f" `{m['match_score']}%`" if m["match_score"] else ""
                    mc1.markdown(f"**{m['display_name']}**{score_badge}")
                    if m["contact_name"]:
                        mc1.caption(m["contact_name"])
                    mc2.markdown(f"📞 {phone_str}")
                    mc3.markdown(f"✉️ {m['email'] or '—'}")
                    if mc4.button("📨 Notified" if m["notified"] else "📨 Mark Notified",
                                  key=f"mb_notif_{m['id']}", use_container_width=True):
                        execute("UPDATE matched_buyers SET notified=TRUE, notified_date=NOW() WHERE id=%s",
                                (m["id"],), commit=True)
                        st.rerun()
                    if m["notified"] and m["notified_date"]:
                        mc4.caption(f"Notified {m['notified_date'].date()}")

                    resp_col, note_col, del_col = st.columns([2, 3, 1])
                    resp_opts = ["—","Interested","Need More Info","Passed","No Answer","Under Review"]
                    cur_resp  = m["response"] or "—"
                    cur_idx   = resp_opts.index(cur_resp) if cur_resp in resp_opts else 0
                    new_resp  = resp_col.selectbox("Response", resp_opts, index=cur_idx,
                                                    key=f"mb_resp_{m['id']}", label_visibility="collapsed")
                    new_note  = note_col.text_input("Note", value=m["buyer_notes"] or "",
                                                    placeholder="e.g. Wants to view Saturday, needs 7-day close",
                                                    key=f"mb_note_{m['id']}", label_visibility="collapsed")
                    if resp_col.button("Save", key=f"mb_save_{m['id']}", use_container_width=True):
                        execute("""
                            UPDATE matched_buyers SET response=%s, notes=%s, response_date=CURRENT_DATE
                            WHERE id=%s
                        """, (new_resp if new_resp != "—" else None,
                              new_note.strip() or None, m["id"]), commit=True)
                        st.rerun()
                    if del_col.button("🗑️", key=f"mb_del_{m['id']}", help="Remove"):
                        execute("DELETE FROM matched_buyers WHERE id=%s", (m["id"],), commit=True)
                        st.rerun()
        else:
            st.info("No buyers matched yet — use Auto-Match below.")

        st.divider()
        st.subheader("🔍 Auto-Match Buyers")
        st.caption("Buyers whose buy box (price range + ZIP) fits this property.")

        prop_val = d.get("total_mkt_val") or 0
        prop_zip = (d.get("situs_zip") or "").strip() or None

        auto = execute("""
            SELECT cb.id, cb.display_name, cb.entity_type, cb.deals_closed,
                   bb.min_price, bb.max_price, bb.zip_codes, bb.strategies,
                   bc.full_name AS contact_name, bc.phone, bc.email
            FROM cash_buyers cb
            JOIN buyer_buyboxes bb ON bb.buyer_id = cb.id
            LEFT JOIN buyer_contacts bc ON bc.buyer_id = cb.id AND bc.is_primary = TRUE
            WHERE (bb.min_price IS NULL OR %s = 0 OR bb.min_price <= %s)
              AND (bb.max_price IS NULL OR %s = 0 OR bb.max_price >= %s)
              AND (
                  bb.zip_codes IS NULL
                  OR cardinality(bb.zip_codes) = 0
                  OR %s IS NULL
                  OR %s = ANY(bb.zip_codes)
              )
              AND cb.id NOT IN (
                  SELECT buyer_id FROM matched_buyers WHERE deal_id = %s
              )
            ORDER BY cb.deals_closed DESC NULLS LAST, bc.phone NULLS LAST
            LIMIT 100
        """, (prop_val, prop_val, prop_val, prop_val, prop_zip, prop_zip, deal_id))

        if auto:
            am1, am2 = st.columns([1, 3])
            am1.metric("Potential Matches", len(auto))
            buyer_search = am2.text_input("Filter", key="mw_buyer_search",
                                           placeholder="Name, type…",
                                           label_visibility="collapsed")
            if buyer_search:
                q = buyer_search.lower()
                auto = [b for b in auto if
                        q in (b["display_name"] or "").lower()
                        or q in (b["entity_type"] or "").lower()
                        or q in (b["contact_name"] or "").lower()]

            df_auto = pd.DataFrame([{
                "Buyer":        m["display_name"],
                "Type":         m["entity_type"] or "—",
                "Contact":      m["contact_name"] or "—",
                "Phone":        m["phone"] or "—",
                "Price Range":  f"{fmt_currency(m['min_price'])} – {fmt_currency(m['max_price'])}",
                "Strategies":   ", ".join(m["strategies"] or []) if m["strategies"] else "—",
                "Deals Closed": m["deals_closed"] or 0,
            } for m in auto])
            st.dataframe(df_auto, use_container_width=True, hide_index=True)

            bc1, bc2 = st.columns(2)
            if bc1.button(f"⬇️ Save All {len(auto)} as Matched", type="primary", use_container_width=True):
                added = 0
                for m in auto:
                    r = execute("""
                        INSERT INTO matched_buyers (deal_id, buyer_id, notified, match_score)
                        VALUES (%s, %s, FALSE, 75)
                        ON CONFLICT DO NOTHING RETURNING id
                    """, (deal_id, m["id"]), commit=True)
                    if r:
                        added += 1
                st.success(f"Added {added} buyers!")
                st.rerun()

            if bc2.button("⬇️ Save Top 10 Most Active", use_container_width=True):
                added = 0
                for m in sorted(auto, key=lambda x: x["deals_closed"] or 0, reverse=True)[:10]:
                    r = execute("""
                        INSERT INTO matched_buyers (deal_id, buyer_id, notified, match_score)
                        VALUES (%s, %s, FALSE, 85)
                        ON CONFLICT DO NOTHING RETURNING id
                    """, (deal_id, m["id"]), commit=True)
                    if r:
                        added += 1
                st.success(f"Saved {added} top buyers!")
                st.rerun()
        else:
            st.info("No additional buyers found matching this property's price/ZIP criteria.")
