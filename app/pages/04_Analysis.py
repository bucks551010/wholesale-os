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
st.caption(
    "MAO = ARV × multiplier − avg repairs. "
    "**Offer the seller at or below the 65% MAO.** "
    "The gap between your contract price and a buyer's MAO is your assignment fee."
)
if arv:
    repairs_mid = (repair["low"] + repair["high"]) / 2
    mao = compute_mao(arv, repairs_mid)

    c_arv, c_rep, c_con, c_std, c_agg = st.columns(5)
    c_arv.metric("ARV (comps)", fmt_currency(arv),
                 help=f"Trimmed mean of {arv_data['comp_count']} non-distressed comps in same ZIP")
    c_rep.metric("Repairs (mid-est)", fmt_currency(repairs_mid),
                 help=f"${repair['rate_low']}–{repair['rate_high']}/sqft × {repair['sqft']:,.0f} sqft ({cond})")
    c_con.metric("Conservative 60%", fmt_currency(mao["conservative"]),
                 help="Use if repairs may run high or market is soft")
    c_std.metric("Standard 65%", fmt_currency(mao["standard"]),
                 help="Your target offer price — typical wholesale formula")
    c_agg.metric("Aggressive 70%", fmt_currency(mao["aggressive"]),
                 help="Only if you have a confirmed end buyer already")

    hcad_val = float(prop["total_mkt_val"] or 0)
    gap = hcad_val - mao["standard"]
    if gap > 0:
        st.warning(
            f"HCAD values this property at **{fmt_currency(hcad_val)}** — "
            f"you need to negotiate **{fmt_currency(gap)} below** HCAD value "
            f"to hit your standard MAO of {fmt_currency(mao['standard'])}."
        )
    else:
        st.success(
            f"HCAD values this property at **{fmt_currency(hcad_val)}** — "
            f"**{fmt_currency(abs(gap))} below** your MAO. "
            f"Potential assignment fee up to {fmt_currency(abs(gap))} at that price."
        )

    if st.button("💾 Save Analysis to DB"):
        save_valuation(prop["parcel_id"], arv, arv_data["price_per_sqft"],
                       arv_data["comp_count"], arv_data["confidence"])
        save_repair_estimate(prop["parcel_id"], cond, repair)
        st.success("Analysis saved.")
else:
    st.info("ARV needed to compute MAO. Try widening to a neighboring ZIP.")

st.divider()

# ── Your Fee Calculator ───────────────────────────────────────────────────────
st.markdown("### 🏷️ Your Assignment Fee Calculator")
st.caption("Plug in your own numbers — override any field. Your fee updates instantly.")

_repairs_mid = (repair["low"] + repair["high"]) / 2 if arv else 0
_default_arv  = int(arv or prop["total_mkt_val"] or 0)
_default_rep  = int(_repairs_mid)

fc1, fc2, fc3 = st.columns(3)
fc_arv     = fc1.number_input("ARV ($)",             min_value=0, value=_default_arv, step=1000, key="fee_arv")
fc_repairs = fc2.number_input("Your Repair Est. ($)", min_value=0, value=_default_rep, step=500,  key="fee_rep",
                               help=f"Benchmark: {fmt_currency(repair['low'])}–{fmt_currency(repair['high'])} for {cond} condition")
fc_closing = fc3.number_input("Closing Costs ($)",    min_value=0, value=3_000,        step=250,  key="fee_cls")

fc4, fc5 = st.columns(2)
fc_buyer_pct = fc4.radio("Buyer's ARV %", [60, 65, 70], index=1, horizontal=True,
                          format_func=lambda x: f"{x}%", key="fee_pct")
fc_offer = fc5.number_input("Your Contract Price (offer to seller) ($)",
                             min_value=0, value=max(0, int(_default_arv * 0.65 - _default_rep - 3000 - 10000)),
                             step=500, key="fee_offer")

_buyer_mao  = max(0, fc_arv * (fc_buyer_pct / 100) - fc_repairs - fc_closing)
_fee        = _buyer_mao - fc_offer
_feasible   = _fee > 0 and fc_offer > 0

with st.container(border=True):
    rr1, rr2, rr3, rr4 = st.columns(4)
    rr1.metric("ARV",                        fmt_currency(fc_arv))
    rr2.metric(f"Buyer's MAO ({fc_buyer_pct}%)", fmt_currency(_buyer_mao))
    rr3.metric("Your Contract Price",        fmt_currency(fc_offer))
    rr4.metric("🏷️ YOUR ASSIGNMENT FEE",     fmt_currency(_fee),
               delta="✅ Feasible" if _feasible else ("❌ Underwater" if fc_offer > 0 else "Enter your offer"),
               delta_color="normal" if _feasible else "inverse")

if prop.get("lead_id") and st.button("💾 Save this Scenario", key="save_fee_scenario"):
    execute("""
        INSERT INTO offer_options
            (lead_id, scenario, arv, arv_pct, repair_cost, closing_costs,
             target_fee, offer_price, buyer_profit, feasible, calc_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE)
    """, (prop["lead_id"], f"{fc_buyer_pct}% custom scenario",
          fc_arv, fc_buyer_pct, fc_repairs, fc_closing,
          max(0, _fee), fc_offer,
          fc_arv - fc_repairs - fc_closing - fc_offer, _feasible), commit=True)
    st.success("Scenario saved!")

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
