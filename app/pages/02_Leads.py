import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency

st.set_page_config(page_title="Leads", page_icon="🎯", layout="wide")
st.title("🎯 Distressed Property Leads")

# ── Sidebar filters ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")

    zip_options = execute("SELECT DISTINCT situs_zip FROM parcels WHERE situs_zip IS NOT NULL ORDER BY situs_zip")
    zip_list = ["All"] + [r["situs_zip"] for r in zip_options]
    sel_zip = st.selectbox("ZIP Code", zip_list)

    sel_min_score = st.slider("Min Distress Score", 0, 20, 5)

    sel_priority = st.multiselect("Priority", ["high", "medium", "low"], default=["high", "medium"])

    distress_type = st.multiselect(
        "Distress Signals",
        ["Absentee Owner", "Low Condition", "Very Low Condition", "Vacant Lot"],
        default=["Very Low Condition", "Low Condition"],
    )
    run_score = st.button("🔄 Re-score All Leads", type="secondary",
                          help="Recomputes scores from HCAD data (~2 min)")

# ── Re-score trigger ─────────────────────────────────────────────────────────
if run_score:
    with st.spinner("Scoring all parcels… this takes about 2 minutes"):
        from app.utils.scoring import run_batch_score
        counts = run_batch_score()
    st.success(
        f"Scored {counts['total_leads']:,} leads — "
        f"{counts['high']:,} high · {counts['medium']:,} medium · {counts['low_score']:,} low"
    )
    st.rerun()

# ── Check if leads exist ──────────────────────────────────────────────────────
lead_count = execute("SELECT COUNT(*) AS n FROM leads WHERE source = 'hcad_auto'")[0]["n"]
if lead_count == 0:
    st.warning("No leads scored yet.")
    st.info("Click **Re-score All Leads** in the sidebar to run the scoring engine against HCAD data (~2 min).")
    st.stop()

# ── Stats header ─────────────────────────────────────────────────────────────
stats = execute("""
    SELECT
        COUNT(*)                                     AS total,
        COUNT(*) FILTER (WHERE priority = 'high')   AS high_ct,
        COUNT(*) FILTER (WHERE priority = 'medium') AS med_ct,
        AVG(motivated_score)::numeric(5,1)           AS avg_score
    FROM leads WHERE source = 'hcad_auto' AND motivated_score >= %s
""", (sel_min_score,))[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Leads", f"{stats['total']:,}")
c2.metric("High Priority", f"{stats['high_ct']:,}")
c3.metric("Medium Priority", f"{stats['med_ct']:,}")
c4.metric("Avg Score", str(stats["avg_score"] or 0))

st.divider()

# ── Build WHERE clause from filters ──────────────────────────────────────────
conditions = ["l.source = 'hcad_auto'", "l.motivated_score >= %(min_score)s"]
params: dict = {"min_score": sel_min_score}

if sel_zip != "All":
    conditions.append("p.situs_zip = %(zip)s")
    params["zip"] = sel_zip

if sel_priority:
    conditions.append("l.priority = ANY(%(priority)s)")
    params["priority"] = sel_priority

type_clauses = []
if "Absentee Owner" in distress_type:
    type_clauses.append("o.is_absentee = TRUE")
if "Low Condition" in distress_type:
    type_clauses.append("b.condition = 'Low'")
if "Very Low Condition" in distress_type:
    type_clauses.append("b.condition = 'Very Low'")
if "Vacant Lot" in distress_type:
    type_clauses.append("(b.id IS NULL AND COALESCE(p.improvement_val,0) < 5000)")
if type_clauses:
    conditions.append("(" + " OR ".join(type_clauses) + ")")

where = " AND ".join(conditions)

rows = execute(f"""
    SELECT
        l.id            AS lead_id,
        p.parcel_id,
        p.full_address,
        p.situs_zip,
        p.improvement_val,
        p.total_appr_val,
        o.owner_name,
        o.owner_type,
        o.is_absentee,
        b.condition,
        b.year_built,
        b.living_area,
        l.motivated_score AS score,
        l.priority,
        COALESCE(ds.absentee_score,  0) AS absentee_pts,
        COALESCE(ds.vacancy_score,   0) AS vacancy_pts,
        COALESCE(ds.portfolio_score, 0) AS portfolio_pts
    FROM leads l
    JOIN  parcels p  ON p.parcel_id = l.parcel_id
    LEFT JOIN owners o    ON o.parcel_id = p.parcel_id
    LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
    LEFT JOIN deal_scores ds ON ds.lead_id = l.id
    WHERE {where}
    ORDER BY l.motivated_score DESC, l.id
    LIMIT 1000
""", params)

if not rows:
    st.info("No leads match the current filters.")
    st.stop()

st.caption(f"Showing up to 1,000 of matching leads — adjust filters to narrow down")

# ── Render table ──────────────────────────────────────────────────────────────
PRIORITY_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}
CONDITION_ICON = {"Very Low": "💀", "Low": "⚠️", "Average": "➖", "Good": "✅"}

for row in rows:
    signals = []
    if row["is_absentee"]:   signals.append("👤 Absentee")
    if row["vacancy_pts"] >= 10: signals.append(f"{CONDITION_ICON.get(row['condition'],'⚠️')} {row['condition']} Condition")
    if row["portfolio_pts"]:  signals.append("📦 Portfolio")

    icon = PRIORITY_ICON.get(row["priority"], "")
    label = (
        f"{icon} **{row['full_address'] or row['parcel_id']}**  "
        f"· Score {row['score']}  "
        f"· {row['owner_name'] or 'Unknown Owner'}  "
        f"· {fmt_currency(row['total_appr_val'])}  "
        f"· {' · '.join(signals) if signals else ''}"
    )
    with st.expander(label):
        a, b_, c_ = st.columns(3)
        a.markdown(f"**Parcel ID:** `{row['parcel_id']}`")
        a.markdown(f"**ZIP:** {row['situs_zip']}")
        a.markdown(f"**Appraised:** {fmt_currency(row['total_appr_val'])}")
        a.markdown(f"**Improvement:** {fmt_currency(row['improvement_val'])}")
        b_.markdown(f"**Owner:** {row['owner_name'] or '—'}")
        b_.markdown(f"**Owner Type:** {row['owner_type'] or '—'}")
        b_.markdown(f"**Absentee:** {'Yes' if row['is_absentee'] else 'No'}")
        c_.markdown(f"**Condition:** {row['condition'] or '—'}")
        c_.markdown(f"**Year Built:** {row['year_built'] or '—'}")
        c_.markdown(f"**Living Area:** {int(row['living_area']):,} sqft" if row['living_area'] else "**Living Area:** —")

        col_v, col_p = st.columns(2)
        col_v.page_link("pages/01_Search.py", label="🔍 Full Property Profile",
                        help=f"Search for {row['full_address']}")
        if col_p.button("➕ Add to Pipeline", key=f"pipe_{row['lead_id']}"):
            existing = execute("SELECT id FROM active_deals WHERE lead_id = %s", (row["lead_id"],))
            if existing:
                st.warning("Already in pipeline")
            else:
                execute("""
                    INSERT INTO active_deals (lead_id, status, created_at)
                    VALUES (%s, 'new_lead', NOW())
                """, (row["lead_id"],), commit=True)
                st.success("Added to pipeline!")
