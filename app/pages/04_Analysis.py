import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.theme import inject_theme, page_header
from app.utils.db import execute
from app.utils.formatting import fmt_currency
from app.utils.comps import (
    find_comps, compute_arv, estimate_repairs, compute_mao,
    save_valuation, save_repair_estimate, STANDARD_MULTIPLIERS,
    compute_flip_offer, compute_hold, compute_brrr, compute_novation,
)

st.set_page_config(page_title="Deal Analysis", page_icon="💡", layout="wide")
inject_theme()
page_header("Deal Analysis", "Comps, ARV, repairs, MAO, and every deal type in one place.", icon="💡")
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
           b.bedrooms, b.full_baths, b.half_baths,
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
_hb = f" + {prop['half_baths']}h" if prop.get("half_baths") else ""
pc3.markdown(f"**Beds / Baths:** {prop.get('bedrooms') or '?'} bed / {prop.get('full_baths') or '?'}{_hb} bath")
pc3.markdown(f"**Living area:** {int(prop['living_area']):,} sqft" if prop['living_area'] else "**Living area:** —")
pc3.markdown(f"**Year built:** {prop['year_built'] or '—'}")
pc3.markdown(f"**Condition:** {prop['condition'] or '—'}")

st.divider()

# ── Comp search ───────────────────────────────────────────────────────────────
sqft_raw = prop["living_area"]
sqft     = float(sqft_raw) if sqft_raw else None
yr       = int(prop["year_built"] or 1990)
zip_code = prop["situs_zip"] or ""
cond     = prop["condition"] or "Average"
mkt_val  = float(prop["total_mkt_val"] or 0)

if not sqft_raw:
    st.warning(
        f"⚠️ **No building data in HCAD** for this parcel (sqft, year, condition are unknown). "
        f"Comps will match by value range (±40% of HCAD value {fmt_currency(mkt_val)}). "
        f"Enter actual sqft for size-matched comps:"
    )
    an1, an2 = st.columns(2)
    manual_sqft = an1.number_input("Living Area (sqft)", 0, 30_000, 0, 100, key="an_sqft",
                                    help="From Zillow, county records, or the listing")
    manual_yr   = an2.number_input("Year Built", 1900, 2026, 2000, 1, key="an_yr")
    if manual_sqft > 0:
        sqft = float(manual_sqft)
    yr   = manual_yr
    cond = "Average"

with st.spinner("Finding comparable properties…"):
    comps    = find_comps(prop["parcel_id"], sqft, yr, zip_code,
                          subject_value=mkt_val if not sqft else None)
    arv_data = compute_arv(comps, sqft or mkt_val / 200)  # rough $/sqft fallback
    repair   = estimate_repairs(cond, sqft or 2000)

arv = arv_data["arv"]

# ── ARV & Repairs ─────────────────────────────────────────────────────────────
col_arv, col_rep = st.columns(2)
with col_arv:
    st.markdown("### 🏡 ARV Estimate")
    if arv:
        ds = arv_data.get("data_source", "hcad_estimate")
        sold_n = arv_data.get("sold_comp_count", 0)
        st.metric("ARV", fmt_currency(arv),
                  help=f"Trimmed mean of {arv_data['comp_count']} comps · confidence: {arv_data['confidence']}")
        src_label = f"✅ {sold_n} sold comps" if ds == "sold" else "⚠️ HCAD assessed values"
        st.caption(
            f"${arv_data['price_per_sqft']:,.0f}/sqft · {arv_data['comp_count']} comps · "
            f"{arv_data['confidence']} confidence · {src_label}"
        )
        if ds == "hcad_estimate":
            st.warning("ARV based on HCAD assessed values — ingest sales history for real sold comps.")
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
# ── Deal-Type Calculator Tabs (ChatARV-style) ────────────────────────────
if arv:
    st.markdown("### 🏷️ Deal Type Calculator")
    repairs_mid = (repair["low"] + repair["high"]) / 2
    deal_repair = st.slider(
        "Repair cost ($)", 0, max(int(repair["high"] * 1.5), 100_000),
        int(repairs_mid), 1_000, format="$%d", key="deal_repairs",
        help=f"Benchmark: {fmt_currency(repair['low'])}–{fmt_currency(repair['high'])} for {cond} condition"
    )

    dtab_ws, dtab_ff, dtab_bh, dtab_brr, dtab_nov = st.tabs(
        ["🏷️ Wholesale", "🔨 Fix & Flip", "🏡 Buy & Hold", "♻️ BRRRR", "🤝 Novation"]
    )

    with dtab_ws:
        st.markdown("**Wholesale — Assign the Contract**")
        dw1, dw2 = st.columns(2)
        d_arv_pct  = dw1.radio("ARV %", [60, 65, 70], index=1, horizontal=True,
                                format_func=lambda x: f"{x}%", key="da_ws_pct")
        d_assign   = dw2.number_input("Your Assignment Fee ($)", 0, 500_000,
                                       10_000, 500, key="da_ws_fee")
        d_mao       = max(0.0, arv * (d_arv_pct / 100) - deal_repair)
        d_seller    = max(0.0, d_mao - d_assign)
        with st.container(border=True):
            dm1, dm2, dm3, dm4 = st.columns(4)
            dm1.metric("ARV",              fmt_currency(arv))
            dm2.metric(f"MAO ({d_arv_pct}%)", fmt_currency(d_mao))
            dm3.metric("Max Offer to Seller", fmt_currency(d_seller))
            dm4.metric("Your Fee",         fmt_currency(d_assign),
                       delta="Your profit" if d_assign > 0 else None)

    with dtab_ff:
        st.markdown("**Fix & Flip — Rehab & Resell**")
        ff1, ff2, ff3 = st.columns(3)
        ff_profit  = ff1.slider("Profit target %", 10, 30, 15, key="da_ff_profit") / 100
        ff_months  = ff2.slider("Holding months",  2, 12,  4, key="da_ff_months")
        ff_closing = ff3.slider("Closing costs %",  1,  8,  4, key="da_ff_closing") / 100
        flip = compute_flip_offer(arv, deal_repair, ff_profit, ff_months, 0.005, ff_closing)
        with st.container(border=True):
            fm1, fm2, fm3, fm4 = st.columns(4)
            fm1.metric("Sale Price (ARV)", fmt_currency(arv))
            fm2.metric("Repairs",          fmt_currency(deal_repair))
            fm3.metric("Profit Target",    fmt_currency(flip["profit_target"]))
            fm4.metric("Max Offer",        fmt_currency(flip["max_offer"]),
                       delta="Buy at or below")
        st.caption(
            f"Holding costs: {fmt_currency(flip['holding_costs'])} · "
            f"Closing costs: {fmt_currency(flip['closing_costs'])}"
        )

    with dtab_bh:
        st.markdown("**Buy & Hold — Long-Term Rental**")
        bh1, bh2, bh3 = st.columns(3)
        _bh_default = max(0, int(arv * 0.70 - deal_repair))
        bh_price = bh1.number_input("Purchase Price ($)", 0, 20_000_000,
                                     min(_bh_default, 20_000_000), 1_000, key="da_bh_price")
        bh_rent  = bh2.number_input("Monthly Rent ($)", 0, 20_000, 1_400, 50, key="da_bh_rent")
        bh_down  = bh3.slider("Down Payment %", 5, 30, 20, key="da_bh_down") / 100
        hold = compute_hold(arv, bh_price, bh_rent * 12, down_pct=bh_down)
        with st.container(border=True):
            hm1, hm2, hm3, hm4 = st.columns(4)
            hm1.metric("Monthly Cash Flow",
                       fmt_currency(hold["annual_cash_flow"] / 12),
                       delta_color="normal" if hold["annual_cash_flow"] > 0 else "inverse")
            hm2.metric("Cap Rate",     f"{hold['cap_rate'] * 100:.1f}%")
            hm3.metric("Cash-on-Cash", f"{hold['coc_return'] * 100:.1f}%")
            hm4.metric("GRM",          f"{hold['gross_rent_multiplier']:.1f}x")

    with dtab_brr:
        st.markdown("**BRRRR — Buy · Rehab · Rent · Refinance · Repeat**")
        br1, br2, br3 = st.columns(3)
        _brr_default = max(0, int(arv * 0.65 - deal_repair))
        brr_price = br1.number_input("Purchase Price ($)", 0, 20_000_000,
                                      min(_brr_default, 20_000_000), 1_000, key="da_brr_price")
        brr_rent  = br2.number_input("Monthly Rent ($)", 0, 20_000, 1_400, 50, key="da_brr_rent")
        brr_ltv   = br3.slider("Refi LTV %", 60, 80, 75, key="da_brr_ltv") / 100
        brr = compute_brrr(arv, deal_repair, brr_price, refi_ltv=brr_ltv,
                            annual_rent=brr_rent * 12)
        with st.container(border=True):
            bm1, bm2, bm3, bm4 = st.columns(4)
            bm1.metric("Total Invested",   fmt_currency(brr["total_invested"]))
            bm2.metric("Refi Loan",        fmt_currency(brr["refi_loan_amount"]))
            bm3.metric("Cash Out at Refi", fmt_currency(brr["cash_out"]),
                       delta_color="normal" if brr["cash_out"] >= 0 else "inverse")
            bm4.metric("Equity Remaining", fmt_currency(brr["equity_remaining"]))

    with dtab_nov:
        st.markdown("**Novation — List on the Seller's Behalf**")
        nv1, nv2, nv3 = st.columns(3)
        nov_agent   = nv1.slider("Agent Commission %", 3, 8, 6, key="da_nov_agent") / 100
        nov_cont    = nv2.number_input("Contingency ($)", 0, 50_000, 5_000, 500, key="da_nov_cont")
        nov_repairs = nv3.number_input("Repair Credit ($)", 0, 200_000,
                                        int(deal_repair), 500, key="da_nov_rep")
        nov = compute_novation(arv, nov_repairs, nov_agent, nov_cont)
        with st.container(border=True):
            nm1, nm2, nm3 = st.columns(3)
            nm1.metric("List Price (ARV)", fmt_currency(nov["list_price"]))
            nm2.metric("Net to Seller",    fmt_currency(nov["net_to_seller"]))
            nm3.metric("Your Spread",      fmt_currency(nov["investor_spread"]),
                       delta="Your earnings")

    st.divider()

st.divider()
# ── Your Fee Calculator ───────────────────────────────────────────────────────
st.markdown("### 🏷️ Your Assignment Fee Calculator")
st.caption("Your fee = what your buyer pays you − what you pay the seller.")

ap1, ap2 = st.columns(2)
fee_contract = ap1.number_input(
    "Your Contract Price (what you pay seller) ($)",
    min_value=0, value=0, step=1000, key="fee_contract",
)
fee_assign = ap2.number_input(
    "Your Assignment Price (what buyer pays you) ($)",
    min_value=0, value=0, step=1000, key="fee_assign",
)

_fee = fee_assign - fee_contract

with st.container(border=True):
    rr1, rr2, rr3 = st.columns(3)
    rr1.metric("Your Contract Price",    fmt_currency(fee_contract))
    rr2.metric("Your Assignment Price",  fmt_currency(fee_assign))
    rr3.metric("🏷️ YOUR ASSIGNMENT FEE", fmt_currency(_fee),
               delta="✅ You profit" if _fee > 0 else ("❌ Negative" if fee_contract > 0 else "Enter your prices"),
               delta_color="normal" if _fee > 0 else "inverse")

if prop.get("lead_id") and st.button("💾 Save this Scenario", key="save_fee_scenario"):
    execute("""
        INSERT INTO offer_options
            (lead_id, scenario, offer_price, target_fee, feasible, calc_date)
        VALUES (%s,%s,%s,%s,%s,CURRENT_DATE)
    """, (prop["lead_id"],
          f"Analysis: Contract ${fee_contract:,} → Assign ${fee_assign:,}",
          fee_contract, max(0, _fee), _fee > 0), commit=True)
    st.success("Scenario saved!")

with st.expander("🔍 Validate: Is your assignment price within the buyer's MAO?"):
    st.caption("Cash buyers using the 65% rule won't pay more than ARV × % − repairs − closing.")
    _repairs_mid = (repair["low"] + repair["high"]) / 2 if arv else 0
    _default_arv  = int(arv or prop["total_mkt_val"] or 0)
    _default_rep  = int(_repairs_mid)

    fc1, fc2, fc3 = st.columns(3)
    fc_arv     = fc1.number_input("ARV ($)",             min_value=0, value=_default_arv, step=1000, key="fee_arv")
    fc_repairs = fc2.number_input("Repair Estimate ($)", min_value=0, value=_default_rep, step=500,  key="fee_rep",
                                   help=f"Benchmark: {fmt_currency(repair['low'])}–{fmt_currency(repair['high'])} for {cond} condition")
    fc_closing = fc3.number_input("Closing Costs ($)",   min_value=0, value=3_000, step=250, key="fee_cls")
    fc_buyer_pct = st.radio("Buyer's ARV %", [60, 65, 70], index=1, horizontal=True,
                              format_func=lambda x: f"{x}%", key="fee_pct")

    _buyer_mao   = max(0, fc_arv * (fc_buyer_pct / 100) - fc_repairs - fc_closing)
    buyer_margin = _buyer_mao - fee_assign

    vm1, vm2, vm3 = st.columns(3)
    vm1.metric("Buyer's MAO",           fmt_currency(_buyer_mao))
    vm2.metric("Your Assignment Price", fmt_currency(fee_assign))
    vm3.metric("Buyer's Margin",        fmt_currency(buyer_margin),
               delta="✅ Buyer makes money" if buyer_margin >= 0 else "❌ Over buyer's MAO",
               delta_color="normal" if buyer_margin >= 0 else "inverse")

st.divider()

# ── Comps table ───────────────────────────────────────────────────────────────
if comps:
    st.markdown(f"### 🏘️ Comparable Properties ({len(comps)})")
    _sold_n = sum(1 for c in comps if c.get("comp_source") == "sold")
    if _sold_n == 0:
        st.warning(
            "⚠️ **HCAD assessed values only** — no actual sold prices in this ZIP. "
            "Run `python ingestion/ingest_hcad.py` to load real sale data."
        )
    elif _sold_n < len(comps):
        st.info(f"📊 {_sold_n} of {len(comps)} comps have actual sale prices; rest use HCAD estimates.")
    import pandas as pd
    df = pd.DataFrame([{
        "Address":    c["full_address"] or c["parcel_id"],
        "Value":      fmt_currency(c.get("comp_value") or c["total_mkt_val"]),
        "Source":     "✅ Sold" if c.get("comp_source") == "sold" else "⚠️ HCAD Est.",
        "Sale Date":  str(c["sale_dt"]) if c.get("sale_dt") else "—",
        "Sqft":       f"{int(c['living_area']):,}" if c["living_area"] else "—",
        "Year Built": c["year_built"] or "—",
        "Condition":  c["condition"] or "—",
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
