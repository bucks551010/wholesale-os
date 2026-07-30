import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency
from app.utils.comps import REPAIR_RATES

st.set_page_config(page_title="Deal Finder", page_icon="🔥", layout="wide")
st.title("🔥 Deal Finder")
st.caption("Top opportunities ranked by distress score. Click any deal to run your numbers and see your assignment fee instantly.")

# ── Sidebar filters for the deal list ─────────────────────────────────────────
with st.sidebar:
    st.header("🔎 Filter Deals")
    min_score = st.slider("Min distress score", 0, 20, 6)
    max_val   = st.number_input("Max HCAD value ($)", min_value=0, value=300_000, step=10_000)
    min_val   = st.number_input("Min HCAD value ($)", min_value=0, value=20_000, step=5_000)
    conditions = st.multiselect("Condition", ["Very Low","Low","Average","Good","Excellent","Superior"],
                                default=["Very Low","Low","Average"])
    excl_pipeline = st.checkbox("Exclude already in My Work / Pipeline", value=False)
    zip_filter = st.text_input("ZIP (leave blank for all)", placeholder="77051")
    show_n = st.slider("# of deals to show", 10, 200, 50)

# ── Load ranked deal list ──────────────────────────────────────────────────────
cond_clause = ""
params: dict = {
    "min_score": min_score, "max_val": max_val, "min_val": min_val, "limit": show_n,
}
if conditions:
    cond_clause = "AND b.condition = ANY(%(conds)s)"
    params["conds"] = conditions
zip_clause = ""
if zip_filter.strip():
    zip_clause = "AND p.situs_zip = %(zip)s"
    params["zip"] = zip_filter.strip()
pipeline_clause = ""
if excl_pipeline:
    pipeline_clause = "AND NOT EXISTS (SELECT 1 FROM active_deals ad WHERE ad.lead_id=l.id AND ad.status!='dead')"

deals = execute(f"""
    SELECT
        l.id            AS lead_id,
        p.parcel_id,
        p.full_address,
        p.situs_zip,
        p.total_mkt_val,
        l.motivated_score,
        l.priority,
        b.living_area,
        b.year_built,
        b.condition,
        b.bedrooms,
        b.full_baths,
        o.owner_name,
        o.is_absentee,
        v.arv_estimate,
        EXISTS(SELECT 1 FROM active_deals ad WHERE ad.lead_id=l.id AND ad.status!='dead') AS in_work
    FROM leads l
    JOIN parcels p ON p.parcel_id = l.parcel_id
    LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
    LEFT JOIN owners o ON o.parcel_id = p.parcel_id
    LEFT JOIN LATERAL (
        SELECT arv_estimate FROM valuations
        WHERE parcel_id = p.parcel_id
        ORDER BY calc_date DESC LIMIT 1
    ) v ON TRUE
    WHERE l.source IN ('hcad_auto','manual')
      AND l.motivated_score >= %(min_score)s
      AND p.total_mkt_val BETWEEN %(min_val)s AND %(max_val)s
      {cond_clause} {zip_clause} {pipeline_clause}
    ORDER BY l.motivated_score DESC, p.total_mkt_val ASC
    LIMIT %(limit)s
""", params)

# ── Two-column layout ──────────────────────────────────────────────────────────
list_col, calc_col = st.columns([1, 2], gap="large")

PRI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
COND_ICON = {"Very Low": "💀", "Low": "⚠️", "Average": "➖", "Good": "✅", "Excellent": "✅"}

# ── LEFT: ranked deal list ────────────────────────────────────────────────────
with list_col:
    st.subheader(f"🏠 {len(deals)} Best Deals")
    if not deals:
        st.info("No deals match — try lowering the min score or expanding condition filters.")

    sel_id = st.session_state.get("df_selected_lead")

    for d in deals:
        is_sel   = sel_id == d["lead_id"]
        icon     = PRI.get(d["priority"], "")
        cicon    = COND_ICON.get(d["condition"], "")
        work_tag = " ✅" if d["in_work"] else ""
        sqft_s   = f"{int(d['living_area']):,} sf" if d["living_area"] else "?"
        arv_s    = f" · ARV {fmt_currency(d['arv_estimate'])}" if d["arv_estimate"] else ""

        with st.container(border=is_sel):
            st.markdown(
                f"{icon}{cicon} **{(d['full_address'] or d['parcel_id'])[:38]}{work_tag}**"
            )
            st.caption(
                f"Score **{d['motivated_score']}** · {fmt_currency(d['total_mkt_val'])} HCAD"
                f" · {sqft_s} · {d['year_built'] or '?'}{arv_s}"
            )
            if st.button("Run Numbers →", key=f"df_sel_{d['lead_id']}",
                         type="primary" if is_sel else "secondary",
                         use_container_width=True):
                st.session_state["df_selected_lead"] = d["lead_id"]
                # Pre-fill calculator from this deal
                sqft = float(d["living_area"] or 1200)
                cond = d["condition"] or "Low"
                lo, hi = REPAIR_RATES.get(cond, (28, 40))
                _mkt = float(d["total_mkt_val"] or 0)
                _arv = float(d["arv_estimate"] or _mkt * 1.15)
                st.session_state["df_arv"]      = int(_arv)
                st.session_state["df_repairs"]  = int((lo + hi) / 2 * sqft)
                st.session_state["df_contract"] = int(d["purchase_price"] or 0)
                st.session_state["df_assign"]   = int(d.get("assignment_price") or 0)
                st.rerun()

# ── RIGHT: deal calculator ────────────────────────────────────────────────────
with calc_col:
    sel_lead_id = st.session_state.get("df_selected_lead")

    if not sel_lead_id:
        st.markdown("### 👈 Click any deal on the left to run your numbers")
        st.markdown("""
**How your assignment fee works:**
```
  Your contract price with seller      $950,000
  Your assignment price to buyer     $1,050,000
  ═════════════════════════════════════════
  🏷️ YOUR ASSIGNMENT FEE               $100,000
```
Use the **Validate** expander below your calculator to
check whether your assignment price is within the buyer's MAO.
""")
        st.stop()

    # Load full deal data
    prop_rows = execute("""
        SELECT p.parcel_id, p.full_address, p.situs_zip, p.total_mkt_val,
               b.living_area, b.year_built, b.condition, b.bedrooms, b.full_baths,
               o.owner_name, o.is_absentee,
               l.motivated_score, l.id AS lead_id,
               ad.id AS deal_id, ad.purchase_price, ad.assignment_fee_target, ad.assignment_price
        FROM leads l
        JOIN parcels p ON p.parcel_id = l.parcel_id
        LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        LEFT JOIN owners o ON o.parcel_id = p.parcel_id
        LEFT JOIN active_deals ad ON ad.lead_id = l.id AND ad.status != 'dead'
        WHERE l.id = %s
        LIMIT 1
    """, (sel_lead_id,))

    if not prop_rows:
        st.error("Deal not found.")
        st.stop()

    p = prop_rows[0]
    sqft = float(p["living_area"] or 1200)
    cond = p["condition"] or "Low"
    lo, hi = REPAIR_RATES.get(cond, (28, 40))

    # Default pre-fills (from session_state set when they clicked)
    def_arv      = st.session_state.get("df_arv",      int(float(p["total_mkt_val"]) * 1.15 if p["total_mkt_val"] else 100_000))
    def_repairs  = st.session_state.get("df_repairs",  int((lo + hi) / 2 * sqft))
    def_contract = st.session_state.get("df_contract", int(p["purchase_price"] or 0))
    def_assign   = st.session_state.get("df_assign",   int(p.get("assignment_price") or 0))

    # ── Property header ───────────────────────────────────────────────────
    st.subheader(p["full_address"] or p["parcel_id"])
    ph1, ph2, ph3, ph4 = st.columns(4)
    ph1.metric("HCAD Value",   fmt_currency(p["total_mkt_val"]))
    ph2.metric("Score",        p["motivated_score"])
    sqft_label = f"{int(sqft):,} sqft" if p["living_area"] else "—"
    ph3.metric("Size",         sqft_label)
    ph4.metric("Condition",    f"{COND_ICON.get(cond, '')} {cond}")
    st.caption(f"ZIP {p['situs_zip']} · {p['bedrooms'] or '?'} bed / {p['full_baths'] or '?'} bath · Built {p['year_built'] or '?'} · Owner: {p['owner_name'] or '—'}")

    st.divider()
    st.subheader("🧮 Your Deal Calculator")
    st.caption("Adjust any input — your fee updates instantly.")

    # ── Calculator inputs ─────────────────────────────────────────────────
    ci1, ci2, ci3 = st.columns(3)
    calc_arv = ci1.number_input(
        "ARV — After Repair Value ($)",
        min_value=0, max_value=2_000_000,
        value=def_arv, step=1000,
        help="What will the property sell for after full renovation? Pull from comps or your own estimate.",
    )
    calc_repairs = ci2.number_input(
        "Your Repair Estimate ($)",
        min_value=0, max_value=500_000,
        value=def_repairs, step=500,
        help=f"Pre-filled at ${(lo+hi)//2}/sqft × {int(sqft):,} sqft ({cond} condition). Override with your own number.",
    )
    calc_closing = ci3.number_input(
        "Closing Costs ($)",
        min_value=0, max_value=50_000,
        value=3_000, step=250,
        help="Title, escrow, transfer taxes. ~$3,000 typical in Harris County.",
    )

    ci4, ci5 = st.columns(2)
    buyer_pct_choice = ci4.radio(
        "Buyer's ARV %",
        options=[60, 65, 70],
        index=1,
        horizontal=True,
        help="60% = conservative, 65% = standard, 70% = you already have a buyer lined up.",
        format_func=lambda x: f"{x}%",
    )
    calc_offer = ci5.number_input(
        "Your Contract Price (offer to seller) ($)",
        min_value=0, max_value=2_000_000,
        value=max(0, def_offer), step=500,
        help="What YOU agree to pay the seller. Your fee = Buyer's offer − this number.",
    )

    # ── Live calculation ──────────────────────────────────────────────────
    buyer_pct    = buyer_pct_choice / 100.0
    buyer_mao    = calc_arv * buyer_pct - calc_repairs - calc_closing
    buyer_mao    = max(0.0, buyer_mao)
    assign_fee   = buyer_mao - calc_offer
    buyer_profit = calc_arv - calc_repairs - calc_closing - buyer_mao  # = 0 at exact MAO
    feasible     = assign_fee > 0 and calc_offer > 0

    st.divider()

    # ── Fee display ───────────────────────────────────────────────────────
    res1, res2, res3, res4 = st.columns(4)
    res1.metric("ARV",              fmt_currency(calc_arv))
    res2.metric(f"Buyer's MAO ({buyer_pct_choice}%)", fmt_currency(buyer_mao))
    res3.metric("Your Contract Price", fmt_currency(calc_offer))

    fee_color = "normal" if assign_fee >= 0 else "inverse"
    res4.metric(
        "🏷️ YOUR ASSIGNMENT FEE",
        fmt_currency(assign_fee),
        delta="✅ Feasible" if feasible else ("❌ Underwater" if calc_offer > 0 else "Enter your offer"),
        delta_color="normal" if feasible else "inverse",
    )

    # Waterfall breakdown
    breakdown = {
        "ARV":                      calc_arv,
        f"× {buyer_pct_choice}% buyer rule":  - (calc_arv - calc_arv * buyer_pct),
        "− Repairs":                -calc_repairs,
        "− Closing Costs":          -calc_closing,
        "= Buyer pays you":         buyer_mao,
        "− Your contract price":    -calc_offer,
        "🏷️ Your Assignment Fee":   assign_fee,
    }

    with st.container(border=True):
        for label, val in breakdown.items():
            lc, vc = st.columns([3, 1])
            if label.startswith("🏷️"):
                lc.markdown(f"**{label}**")
                vc.markdown(
                    f"**{'✅ ' if assign_fee > 0 else '❌ '}{fmt_currency(assign_fee)}**"
                )
            elif label.startswith("="):
                lc.markdown(f"**{label}**")
                vc.markdown(f"**{fmt_currency(val)}**")
            else:
                lc.write(label)
                vc.write(fmt_currency(val) if val >= 0 else f"({fmt_currency(-val)})")

    # ── 3 Scenarios ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("📊 All 3 Scenarios at Your Numbers")
    sc_data = []
    for lbl, pct in [("Conservative (60%)", 0.60), ("Standard (65%)", 0.65), ("Aggressive (70%)", 0.70)]:
        mao = max(0, calc_arv * pct - calc_repairs - calc_closing)
        fee = mao - calc_offer
        sc_data.append({
            "Scenario":     lbl,
            "Buyer's MAO":  fmt_currency(mao),
            "Your Offer":   fmt_currency(calc_offer),
            "Your Fee":     fmt_currency(fee),
            "Feasible":     "✅" if fee > 0 and calc_offer > 0 else "❌",
        })
    import pandas as pd
    st.dataframe(pd.DataFrame(sc_data), use_container_width=True, hide_index=True)

    # ── Repair hint ───────────────────────────────────────────────────────
    if p["living_area"]:
        st.caption(
            f"💡 Repair benchmark for **{cond}** condition: "
            f"${lo}–${hi}/sqft × {int(sqft):,} sqft = "
            f"**{fmt_currency(lo*sqft)} – {fmt_currency(hi*sqft)}**. "
            f"You entered **{fmt_currency(calc_repairs)}**."
        )

    # ── Action buttons ────────────────────────────────────────────────────
    st.divider()
    ab1, ab2, ab3 = st.columns(3)

    if ab1.button("📁 Save to My Work", type="primary"):
        existing = execute("SELECT id FROM active_deals WHERE lead_id=%s AND status!='dead' LIMIT 1",
                           (sel_lead_id,))
        if existing:
            deal_id = existing[0]["id"]
        else:
            r = execute("INSERT INTO active_deals (lead_id, status, created_at) VALUES (%s,'new_lead',NOW()) RETURNING id",
                        (sel_lead_id,), commit=True)
            deal_id = r[0]["id"] if r else None
        if deal_id:
            execute("""
                UPDATE active_deals
                SET purchase_price=%s, assignment_fee_target=%s
                WHERE id=%s
            """, (calc_offer or None, max(0, assign_fee) or None, deal_id), commit=True)
            st.session_state["mw_deal_id"] = deal_id
            st.switch_page("pages/08_My_Work.py")

    if ab2.button("💾 Save Offer Scenario"):
        if not sel_lead_id:
            st.warning("No lead selected.")
        else:
            execute("""
                INSERT INTO offer_options
                    (lead_id, scenario, arv, arv_pct, repair_cost, closing_costs,
                     target_fee, offer_price, buyer_profit, feasible, calc_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
            """, (
                sel_lead_id,
                f"{buyer_pct_choice}% scenario",
                calc_arv, buyer_pct_choice, calc_repairs, calc_closing,
                max(0, assign_fee), calc_offer,
                calc_arv - calc_repairs - calc_closing - calc_offer,
                feasible,
            ), commit=True)
            st.success("Scenario saved to deal history!")

    if ab3.button("💡 Full Comp Analysis"):
        st.session_state["analysis_parcel_id"] = p["parcel_id"]
        st.switch_page("pages/04_Analysis.py")
