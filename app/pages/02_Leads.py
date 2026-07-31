import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.theme import inject_theme, page_header
from app.utils.db import execute
from app.utils.formatting import fmt_currency


@st.dialog("📋 Property Log & Skip Trace")
def contact_log_dialog(lead_id: int, parcel_id: str, address: str,
                       owner_name: str, mail_city: str, mail_state: str):
    st.subheader(address)

    # Skip-trace links
    name_enc = (owner_name or "").replace(" ", "+")
    city_enc = (mail_city or "Houston").replace(" ", "+")
    state    = mail_state or "TX"
    st.markdown("**Free skip-trace links:**")
    st.markdown(
        f"[TruePeopleSearch ↗](https://www.truepeoplesearch.com/results?name={name_enc}&citystatezip={city_enc}%2C+{state})  ·  "
        f"[FastPeopleSearch ↗](https://www.fastpeoplesearch.com/name/{name_enc})  ·  "
        f"[WhitePages ↗](https://www.whitepages.com/name/{name_enc}/{city_enc})  ·  "
        f"[HCAD Portal ↗](https://hcad.org/property-search/real-property/strap-search/?strap={parcel_id})"
    )
    st.divider()

    # Existing contact log
    history = execute(
        "SELECT contact_date, method, outcome, notes, next_followup "
        "FROM lead_contact_log WHERE lead_id=%s ORDER BY contact_date DESC",
        (lead_id,)
    )
    if history:
        st.markdown("**Previous contacts:**")
        for h in history:
            st.markdown(f"- {h['contact_date'].strftime('%Y-%m-%d')} · {h['method']} · {h['outcome'] or '—'}")
            if h['notes']: st.caption(f"  {h['notes']}")
        st.divider()

    # Log new contact attempt
    st.markdown("**Log a contact attempt:**")
    with st.form("contact_form"):
        r1, r2 = st.columns(2)
        method   = r1.selectbox("Method", ["cold_call","text","email","door_knock","driving","letter_response","other"])
        outcome  = r2.selectbox("Outcome", ["no_answer","left_voicemail","spoke_not_interested","spoke_interested","callback_requested","wrong_number","other"])
        phone_found = st.text_input("Phone number found (add to notes)")
        notes    = st.text_area("Notes", placeholder="What did you find out? Price they want? Motivation?")
        followup = st.date_input("Follow-up date", value=None)
        if st.form_submit_button("Save Contact Log", type="primary"):
            full_notes = ((f"Phone: {phone_found}  " if phone_found else "") + (notes or "")).strip()
            execute(
                "INSERT INTO lead_contact_log "
                "(lead_id, contact_date, method, outcome, notes, next_followup) "
                "VALUES (%s, NOW(), %s, %s, %s, %s)",
                (lead_id, method, outcome, full_notes or None, followup or None),
                commit=True
            )
            st.success("Logged!")
            st.rerun()

st.set_page_config(page_title="Leads", page_icon="🎯", layout="wide")
inject_theme()
page_header("Leads", "Score and manage your entire lead pipeline.", icon="🎯")
def _save_to_my_work(lead_id: int):
    existing = execute(
        "SELECT id FROM active_deals WHERE lead_id=%s AND status!='dead' LIMIT 1", (lead_id,)
    )
    if existing:
        st.session_state["mw_deal_id"] = existing[0]["id"]
    else:
        r = execute(
            "INSERT INTO active_deals (lead_id, status, created_at) VALUES (%s,'new_lead',NOW()) RETURNING id",
            (lead_id,), commit=True
        )
        if r:
            st.session_state["mw_deal_id"] = r[0]["id"]
    st.switch_page("pages/08_My_Work.py")

# ── Value ranges (loaded once for slider bounds) ──────────────────────────────
@st.cache_data(ttl=3600)
def get_filter_bounds():
    r = execute("""
        SELECT
            MIN(b.year_built) FILTER (WHERE b.year_built > 1800) AS yr_min,
            MAX(b.year_built)                                      AS yr_max,
            MIN(b.living_area) FILTER (WHERE b.living_area > 0)   AS sqft_min,
            MAX(b.living_area) FILTER (WHERE b.living_area < 20000) AS sqft_max,
            MIN(p.total_appr_val) FILTER (WHERE p.total_appr_val > 0) AS val_min,
            MAX(p.total_appr_val) FILTER (WHERE p.total_appr_val < 5000000) AS val_max
        FROM leads l
        JOIN parcels p  ON p.parcel_id = l.parcel_id
        LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        WHERE l.source = 'hcad_auto'
    """)
    return r[0] if r else {}

bounds = get_filter_bounds()

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("🔎 Filters")

    # ZIP — multi-select
    zip_options = execute(
        "SELECT DISTINCT situs_zip, COUNT(*) AS n "
        "FROM leads l JOIN parcels p ON p.parcel_id=l.parcel_id "
        "WHERE l.source='hcad_auto' AND situs_zip IS NOT NULL "
        "GROUP BY situs_zip ORDER BY situs_zip"
    )
    zip_labels = {r["situs_zip"]: f"{r['situs_zip']} ({r['n']:,})" for r in zip_options}
    sel_zips = st.multiselect("ZIP Codes", options=list(zip_labels.keys()),
                              format_func=lambda z: zip_labels[z],
                              placeholder="All ZIPs")

    st.divider()

    # Score
    sel_min_score, sel_max_score = st.slider(
        "Distress Score Range", 0, 20, (5, 20)
    )

    # Priority
    sel_priority = st.multiselect("Priority", ["high", "medium", "low"],
                                  default=["high", "medium"])

    # Condition
    st.markdown("**Building Condition**")
    cond_very_low = st.checkbox("💀 Very Low", value=True)
    cond_low      = st.checkbox("⚠️ Low",      value=True)
    cond_average  = st.checkbox("➖ Average",   value=False)
    cond_vacant   = st.checkbox("🏚️ Vacant Lot (no building)", value=False)
    cond_good     = st.checkbox("✅ Good/Excellent", value=False)

    st.divider()

    # Owner filters
    st.markdown("**Owner**")
    sel_absentee_only = st.checkbox("Absentee owners only", value=False)
    sel_owner_types = st.multiselect(
        "Owner Type",
        ["individual", "llc", "trust", "estate", "bank"],
        placeholder="All types",
    )
    sel_not_pipeline = st.checkbox("Exclude leads already in pipeline", value=False)
    sel_not_contacted = st.checkbox("Not yet contacted", value=False)

    st.divider()

    # Year built range
    yr_min = int(bounds.get("yr_min") or 1900)
    yr_max = int(bounds.get("yr_max") or 2024)
    sel_yr = st.slider("Year Built", yr_min, yr_max, (yr_min, yr_max))

    # Living area (sqft)
    sq_min = int(bounds.get("sqft_min") or 0)
    sq_max = int(min(bounds.get("sqft_max") or 10000, 10000))
    sel_sqft = st.slider("Living Area (sqft)", sq_min, sq_max, (sq_min, sq_max))

    # Value range
    v_min = int(bounds.get("val_min") or 0)
    v_max = int(min(bounds.get("val_max") or 1_000_000, 1_000_000))
    sel_val = st.slider("Appraised Value ($)", v_min, v_max, (v_min, v_max),
                        format="$%d")

    st.divider()

    # Sort
    sort_by = st.selectbox("Sort By", [
        "Score (highest first)",
        "Appraised Value (lowest first)",
        "Appraised Value (highest first)",
        "Year Built (oldest first)",
        "Year Built (newest first)",
        "Address A→Z",
    ])

    st.divider()
    max_rows = st.number_input("Max results to load", min_value=100, max_value=10000,
                               value=1000, step=100,
                               help="Raise this to see more properties. Table view handles large numbers well; Card view slows above ~500.")

    run_score = st.button("🔄 Re-score All Leads", type="secondary",
                          help="~2 min — recomputes from HCAD data")

SORT_MAP = {
    "Score (highest first)":         "l.motivated_score DESC, l.id",
    "Appraised Value (lowest first)": "p.total_appr_val ASC NULLS LAST",
    "Appraised Value (highest first)":"p.total_appr_val DESC NULLS LAST",
    "Year Built (oldest first)":      "b.year_built ASC NULLS LAST",
    "Year Built (newest first)":      "b.year_built DESC NULLS LAST",
    "Address A→Z":                    "p.full_address ASC",
}

# ── Re-score trigger ──────────────────────────────────────────────────────────
if run_score:
    with st.spinner("Scoring all parcels… this takes about 2 minutes"):
        from app.utils.scoring import run_batch_score
        counts = run_batch_score()
    st.success(
        f"Scored {counts['total_leads']:,} leads — "
        f"{counts['high']:,} high · {counts['medium']:,} medium · {counts['low_score']:,} low"
    )
    st.cache_data.clear()
    st.rerun()

# ── Check if leads exist ──────────────────────────────────────────────────────
lead_count = execute("SELECT COUNT(*) AS n FROM leads WHERE source = 'hcad_auto'")[0]["n"]
if lead_count == 0:
    st.warning("No leads scored yet. Click **Re-score All Leads** in the sidebar.")
    st.stop()

# ── Build WHERE clause ────────────────────────────────────────────────────────
conditions = [
    "l.source = 'hcad_auto'",
    "l.motivated_score >= %(min_score)s",
    "l.motivated_score <= %(max_score)s",
    "p.total_appr_val BETWEEN %(val_min)s AND %(val_max)s",
]
params: dict = {
    "min_score": sel_min_score,
    "max_score": sel_max_score,
    "val_min": sel_val[0],
    "val_max": sel_val[1],
}

if sel_zips:
    conditions.append("p.situs_zip = ANY(%(zips)s)")
    params["zips"] = sel_zips

if sel_priority:
    conditions.append("l.priority = ANY(%(priority)s)")
    params["priority"] = sel_priority

if sel_absentee_only:
    conditions.append("o.is_absentee = TRUE")

if sel_owner_types:
    conditions.append("o.owner_type = ANY(%(owner_types)s)")
    params["owner_types"] = sel_owner_types

if sel_not_pipeline:
    conditions.append("""
        NOT EXISTS (SELECT 1 FROM active_deals ad WHERE ad.lead_id = l.id
                    AND ad.status NOT IN ('dead'))
    """)

if sel_not_contacted:
    conditions.append("""
        NOT EXISTS (SELECT 1 FROM lead_contact_log cl WHERE cl.lead_id = l.id)
    """)

# Year built range (only apply if building exists)
conditions.append(
    "(b.year_built IS NULL OR b.year_built BETWEEN %(yr_min)s AND %(yr_max)s)"
)
params["yr_min"] = sel_yr[0]
params["yr_max"] = sel_yr[1]

# Sqft range
conditions.append(
    "(b.living_area IS NULL OR b.living_area BETWEEN %(sqft_min)s AND %(sqft_max)s)"
)
params["sqft_min"] = sel_sqft[0]
params["sqft_max"] = sel_sqft[1]

# Condition checkboxes
cond_clauses = []
if cond_very_low: cond_clauses.append("b.condition = 'Very Low'")
if cond_low:      cond_clauses.append("b.condition = 'Low'")
if cond_average:  cond_clauses.append("b.condition = 'Average'")
if cond_good:     cond_clauses.append("b.condition IN ('Good','Excellent','Superior')")
if cond_vacant:   cond_clauses.append("(b.id IS NULL AND COALESCE(p.improvement_val,0) < 5000)")
if cond_clauses:
    conditions.append("(" + " OR ".join(cond_clauses) + ")")

order = SORT_MAP.get(sort_by, "l.motivated_score DESC, l.id")
where = " AND ".join(conditions)

rows = execute(f"""
    SELECT
        l.id            AS lead_id,
        p.parcel_id,
        p.full_address,
        p.situs_zip,
        p.improvement_val,
        p.total_appr_val,
        p.land_val,
        p.situs_city,
        o.owner_name,
        o.owner_type,
        o.is_absentee,
        o.mail_city,
        o.mail_state,
        b.condition,
        b.year_built,
        b.living_area,
        b.building_class,
        l.motivated_score AS score,
        l.priority,
        COALESCE(ds.absentee_score,  0) AS absentee_pts,
        COALESCE(ds.vacancy_score,   0) AS vacancy_pts,
        COALESCE(ds.portfolio_score, 0) AS portfolio_pts,
        EXISTS(SELECT 1 FROM lead_contact_log cl WHERE cl.lead_id = l.id) AS contacted,
        EXISTS(SELECT 1 FROM active_deals ad WHERE ad.lead_id = l.id
               AND ad.status NOT IN ('dead')) AS in_pipeline
    FROM leads l
    JOIN  parcels p  ON p.parcel_id = l.parcel_id
    LEFT JOIN owners o    ON o.parcel_id = p.parcel_id
    LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
    LEFT JOIN deal_scores ds ON ds.lead_id = l.id
    WHERE {where}
    ORDER BY {order}
    LIMIT {int(max_rows)}
""", params)

# ── Stats header ──────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Matching Leads", f"{len(rows):,}")
c2.metric("High Priority 🔴", sum(1 for r in rows if r["priority"] == "high"))
c3.metric("Absentee 👤",      sum(1 for r in rows if r["is_absentee"]))
c4.metric("Not Contacted 📭", sum(1 for r in rows if not r["contacted"]))
c5.metric("Not in Pipeline",  sum(1 for r in rows if not r["in_pipeline"]))

if not rows:
    st.info("No leads match the current filters. Try relaxing the criteria.")
    st.stop()

st.divider()

# ── View toggle ───────────────────────────────────────────────────────────────
view = st.radio("View", ["📋 Table", "🃏 Cards"], horizontal=True, label_visibility="collapsed")
more_indicator = f" (showing first {int(max_rows):,} — increase 'Max results' in sidebar for more)" if len(rows) == int(max_rows) else ""
st.caption(f"Showing {len(rows):,} matching leads{more_indicator}")

PRIORITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
CONDITION_ICON = {"Very Low": "💀", "Low": "⚠️", "Average": "➖", "Good": "✅", "Excellent": "✅", "Superior": "✅"}

# ── TABLE VIEW ────────────────────────────────────────────────────────────────
if view == "📋 Table":
    import pandas as pd
    df_rows = []
    for r in rows:
        sigs = []
        if r["is_absentee"]:        sigs.append("👤")
        if r["vacancy_pts"] >= 15:  sigs.append("💀")
        elif r["vacancy_pts"] >= 10: sigs.append("⚠️")
        if r["portfolio_pts"]:      sigs.append("📦")
        if r["contacted"]:          sigs.append("📞")
        if r["in_pipeline"]:        sigs.append("📋")
        df_rows.append({
            "Score":     r["score"],
            "Pri":       PRIORITY_ICON.get(r["priority"], ""),
            "Address":   r["full_address"] or r["parcel_id"],
            "ZIP":       r["situs_zip"] or "",
            "Owner":     (r["owner_name"] or "—")[:30],
            "Type":      r["owner_type"] or "—",
            "Condition": r["condition"] or "—",
            "Sqft":      int(r["living_area"]) if r["living_area"] else None,
            "Yr Built":  r["year_built"],
            "Value ($)": int(r["total_appr_val"]) if r["total_appr_val"] else None,
            "Signals":   " ".join(sigs),
            "_lead_id":  r["lead_id"],
        })
    df = pd.DataFrame(df_rows)

    st.dataframe(
        df.drop(columns=["_lead_id"]),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Score":     st.column_config.NumberColumn(width="small"),
            "Pri":       st.column_config.TextColumn("!", width="small"),
            "Sqft":      st.column_config.NumberColumn(format="%d"),
            "Value ($)": st.column_config.NumberColumn(format="$%d"),
        },
    )

    st.caption("Click a row in the table above then use the actions below:")
    sel_addr = st.selectbox("Select property for actions",
                            options=[r["full_address"] or r["parcel_id"] for r in rows],
                            label_visibility="collapsed")
    sel_row  = next((r for r in rows if (r["full_address"] or r["parcel_id"]) == sel_addr), rows[0])

    act1, act2, act3, act4 = st.columns(4)
    if act1.button("🔍 Full Profile"):
        st.session_state["search_query"] = sel_row["parcel_id"]
        st.switch_page("pages/01_Search.py")
    if act2.button("💡 Deal Analysis"):
        st.session_state["analysis_parcel_id"] = sel_row["parcel_id"]
        st.switch_page("pages/04_Analysis.py")
    if act3.button("📋 Log / Skip-Trace"):
        contact_log_dialog(
            lead_id=sel_row["lead_id"], parcel_id=sel_row["parcel_id"],
            address=sel_row["full_address"] or sel_row["parcel_id"],
            owner_name=sel_row["owner_name"] or "",
            mail_city=sel_row.get("mail_city") or sel_row.get("situs_city") or "",
            mail_state=sel_row.get("mail_state") or "TX",
        )
    if act4.button("📁 My Work"):
        _save_to_my_work(sel_row["lead_id"])

# ── CARD VIEW ─────────────────────────────────────────────────────────────────
else:
    for row in rows:
        signals = []
        if row["is_absentee"]:        signals.append("👤 Absentee")
        if row["vacancy_pts"] >= 15:  signals.append("💀 Very Low Condition")
        elif row["vacancy_pts"] >= 10: signals.append("⚠️ Low Condition")
        if row["portfolio_pts"]:      signals.append("📦 Portfolio Owner")
        if row["contacted"]:          signals.append("📞 Contacted")
        if row["in_pipeline"]:        signals.append("📋 In Pipeline")

        icon = PRIORITY_ICON.get(row["priority"], "")
        sqft_str = f"{int(row['living_area']):,} sqft" if row["living_area"] else "—"
        label = (
            f"{icon} **{row['full_address'] or row['parcel_id']}**  "
            f"· Score **{row['score']}**  "
            f"· {row['owner_name'] or '—'}  "
            f"· {fmt_currency(row['total_appr_val'])}  "
            f"· {sqft_str}  "
            f"· {row['year_built'] or '—'}  "
            + (f"· {' · '.join(signals)}" if signals else "")
        )
        with st.expander(label):
            a, b_, c_ = st.columns(3)
            a.markdown(f"**Parcel:** `{row['parcel_id']}`")
            a.markdown(f"**ZIP:** {row['situs_zip']}")
            a.markdown(f"**Appraised:** {fmt_currency(row['total_appr_val'])}")
            a.markdown(f"**Improvement:** {fmt_currency(row['improvement_val'])}")
            a.markdown(f"**Land Value:** {fmt_currency(row['land_val'])}")
            b_.markdown(f"**Owner:** {row['owner_name'] or '—'}")
            b_.markdown(f"**Type:** {row['owner_type'] or '—'}")
            b_.markdown(f"**Absentee:** {'Yes ⚠️' if row['is_absentee'] else 'No'}")
            b_.markdown(f"**Mailing:** {row['mail_city'] or '—'}, {row['mail_state'] or ''}")
            c_.markdown(f"**Condition:** {CONDITION_ICON.get(row['condition'],'')} {row['condition'] or '—'}")
            c_.markdown(f"**Year Built:** {row['year_built'] or '—'}")
            c_.markdown(f"**Living Area:** {sqft_str}")
            c_.markdown(f"**Class:** {row['building_class'] or '—'}")

            col_v, col_a, col_p, col_c, col_w = st.columns(5)
            if col_v.button("🔍 Profile", key=f"prof_{row['lead_id']}"):
                st.session_state["search_query"] = row["parcel_id"]
                st.switch_page("pages/01_Search.py")
            if col_a.button("💡 Analysis", key=f"anal_{row['lead_id']}"):
                st.session_state["analysis_parcel_id"] = row["parcel_id"]
                st.switch_page("pages/04_Analysis.py")
            if col_c.button("📋 Log", key=f"log_{row['lead_id']}"):
                contact_log_dialog(
                    lead_id=row["lead_id"], parcel_id=row["parcel_id"],
                    address=row["full_address"] or row["parcel_id"],
                    owner_name=row["owner_name"] or "",
                    mail_city=row.get("mail_city") or row.get("situs_city") or "",
                    mail_state=row.get("mail_state") or "TX",
                )
            if col_p.button("➕ Pipeline", key=f"pipe_{row['lead_id']}"):
                if row["in_pipeline"]:
                    st.info("Already in pipeline")
                else:
                    execute(
                        "INSERT INTO active_deals (lead_id, status, created_at) VALUES (%s,'new_lead',NOW())",
                        (row["lead_id"],), commit=True,
                    )
                    st.success("Added!")
                    st.rerun()
            if col_w.button("📁 My Work", key=f"work_{row['lead_id']}"):
                _save_to_my_work(row["lead_id"])

