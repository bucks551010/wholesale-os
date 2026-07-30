import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency
from app.utils.comps import (
    find_comps, compute_arv, estimate_repairs, compute_mao,
    save_valuation, save_repair_estimate, STANDARD_MULTIPLIERS,
)

st.set_page_config(page_title="Deal Analysis", page_icon="💡", layout="wide")
st.title("💡 Deal Analysis")

# ── Property lookup ───────────────────────────────────────────────────────────
default_pid = st.session_state.get("analysis_parcel_id", "")
query = st.text_input("Parcel ID or Address", value=default_pid,
                      placeholder="e.g. 0651040050025  or  907 COMMERCE ST")

if not query:
    st.info("Enter a parcel ID or street address above to run a deal analysis.")
    st.stop()

# ── Find the parcel ───────────────────────────────────────────────────────────
rows = execute("""
    SELECT p.*, o.owner_name, o.owner_type, o.is_absentee,
           b.living_area, b.year_built, b.condition, b.building_class,
           l.id AS lead_id, l.motivated_score
    FROM parcels p
    LEFT JOIN owners o    ON o.parcel_id = p.parcel_id
    LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
    LEFT JOIN leads l     ON l.parcel_id = p.parcel_id AND l.source = 'hcad_auto'
    WHERE p.parcel_id ILIKE %(q)s
       OR p.full_address ILIKE %(like)s
    LIMIT 5
""", {"q": query.strip(), "like": f"%{query.strip()}%"})

if not rows:
    st.warning("No property found. Try a parcel ID (e.g. `0651040050025`) or address fragment.")
    st.stop()

if len(rows) > 1:
    opts = {r["full_address"] or r["parcel_id"]: r for r in rows}
    sel  = st.selectbox("Multiple matches — pick one:", list(opts.keys()))
    prop = opts[sel]
else:
    prop = rows[0]

# ── Property card ─────────────────────────────────────────────────────────────
st.subheader(prop["full_address"] or prop["parcel_id"])
pc1, pc2, pc3 = st.columns(3)
pc1.markdown(f"**Parcel:** `{prop['parcel_id']}`")
pc1.markdown(f"**ZIP:** {prop['situs_zip']}")
pc1.markdown(f"**Acct type:** {prop['acct_type'] or '—'}")
pc2.markdown(f"**Owner:** {prop['owner_name'] or '—'}")
pc2.markdown(f"**Owner type:** {prop['owner_type'] or '—'}")
pc2.markdown(f"**Absentee:** {'Yes ⚠️' if prop['is_absentee'] else 'No'}")
pc3.markdown(f"**Living area:** {int(prop['living_area']):,} sqft" if prop['living_area'] else "**Living area:** —")
pc3.markdown(f"**Year built:** {prop['year_built'] or '—'}")
pc3.markdown(f"**Condition:** {prop['condition'] or '—'}")

st.divider()

# ── Comp search ───────────────────────────────────────────────────────────────
sqft     = float(prop["living_area"] or 1200)
yr       = int(prop["year_built"] or 1990)
zip_code = prop["situs_zip"] or ""
cond     = prop["condition"] or "Average"

with st.spinner("Finding comparable properties…"):
    comps = find_comps(prop["parcel_id"], sqft, yr, zip_code)
    arv_data = compute_arv(comps, sqft)
    repair   = estimate_repairs(cond, sqft)

arv = arv_data["arv"]

# ── ARV & Repairs ─────────────────────────────────────────────────────────────
col_arv, col_rep = st.columns(2)
with col_arv:
    st.markdown("### 🏡 ARV Estimate")
    if arv:
        st.metric("ARV", fmt_currency(arv),
                  help=f"Trimmed mean of {arv_data['comp_count']} comps · confidence: {arv_data['confidence']}")
        if arv_data["price_per_sqft"]:
            st.caption(f"${arv_data['price_per_sqft']:,.0f}/sqft · {arv_data['comp_count']} comps · {arv_data['confidence']} confidence")
    else:
        st.warning("Not enough comps in this ZIP to estimate ARV.")

with col_rep:
    st.markdown("### 🔨 Repair Estimate")
    st.metric("Repair Range",
              f"{fmt_currency(repair['low'])} – {fmt_currency(repair['high'])}",
              help=f"{repair['rate_low']}–{repair['rate_high']} $/sqft × {repair['sqft']:,.0f} sqft")
    st.caption(f"Condition: **{cond}** · {repair['sqft']:,.0f} sqft")

st.divider()

# ── MAO table ─────────────────────────────────────────────────────────────────
st.markdown("### 📊 Maximum Allowable Offer (MAO)")
if arv:
    repairs_mid = (repair["low"] + repair["high"]) / 2
    mao = compute_mao(arv, repairs_mid)

    cols = st.columns(len(STANDARD_MULTIPLIERS) + 1)
    cols[0].metric("As-Is Value (HCAD)", fmt_currency(prop["total_mkt_val"]))
    for i, (label, pct) in enumerate(STANDARD_MULTIPLIERS.items()):
        spread = mao[label] - (float(prop["total_mkt_val"] or 0))
        cols[i + 1].metric(
            f"{label.title()} ({int(pct*100)}%)",
            fmt_currency(mao[label]),
            delta=f"Spread {fmt_currency(abs(spread))}" if spread > 0 else "Below current value",
        )

    st.caption(f"Formula: ARV × multiplier − avg repairs ({fmt_currency(repairs_mid)})")

    # Save analysis
    if st.button("💾 Save Analysis to DB"):
        save_valuation(prop["parcel_id"], arv, arv_data["price_per_sqft"],
                       arv_data["comp_count"], arv_data["confidence"])
        save_repair_estimate(prop["parcel_id"], cond, repair)
        st.success("Analysis saved.")
else:
    st.info("ARV needed to compute MAO. Try widening to a neighboring ZIP.")

st.divider()

# ── Comps table ───────────────────────────────────────────────────────────────
if comps:
    st.markdown(f"### 🏘️ Comparable Properties ({len(comps)})")
    import pandas as pd
    df = pd.DataFrame([{
        "Address":      c["full_address"] or c["parcel_id"],
        "Mkt Value":    fmt_currency(c["total_mkt_val"]),
        "Sqft":         f"{int(c['living_area']):,}" if c["living_area"] else "—",
        "Year Built":   c["year_built"] or "—",
        "Condition":    c["condition"] or "—",
    } for c in comps])
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No comps found. No non-distressed properties with similar size in this ZIP.")

st.divider()

# ── Add to pipeline ───────────────────────────────────────────────────────────
st.markdown("### ➕ Add to Pipeline")
if prop.get("lead_id"):
    existing = execute("SELECT id FROM active_deals WHERE lead_id = %s", (prop["lead_id"],))
    if existing:
        st.success("Already in pipeline.")
    else:
        if st.button("Add to Pipeline as New Lead"):
            execute("INSERT INTO active_deals (lead_id, status, created_at) VALUES (%s,'new_lead',NOW())",
                    (prop["lead_id"],), commit=True)
            st.success("Added to pipeline!")
else:
    st.caption("Property not yet in leads. Go to the Leads page to score it first.")
