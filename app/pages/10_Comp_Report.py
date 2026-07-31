"""
Comp Report — ChatARV-style workflow:
  1. Search any property by address / parcel ID
  2. View property profile + Street View photo
  3. Review top 6 AI-selected comps as visual cards (deselect bad ones)
  4. Adjust repair cost with presets
  5. Choose deal type → get your offer numbers
  6. View & share a report summary
"""
import os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.theme import inject_theme, page_header
from app.utils.db import execute
from app.utils.formatting import fmt_currency, fmt_address
from app.utils.comps import (
    find_comps, compute_arv, estimate_repairs, compute_mao,
    compute_flip_offer, compute_hold, compute_brrr, compute_novation,
)
import folium
from streamlit_folium import st_folium
from app.utils.geo import geocode, street_view_url, photo_links
from app.utils.config import GOOGLE_MAPS_API_KEY

st.set_page_config(page_title="Comp Report", page_icon="📊", layout="wide")
inject_theme()

# ── Dark-theme card styles ────────────────────────────────────────────────────
st.markdown("""
<style>
.comp-card {
    border: 2px solid #2a2a2a;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 2px;
    background: #1a1a1a;
    transition: border-color 0.2s;
}
.comp-card.selected { border-color: #e85d04; background: #1f1208; }
.comp-price { font-size: 1.25rem; font-weight: 700; color: #e85d04; }
.comp-ppsf  { font-size: 0.8rem; color: #aaa; }
.comp-addr  { font-size: 0.88rem; font-weight: 600; margin-bottom: 6px;
               white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.comp-meta  { font-size: 0.78rem; color: #888; margin-top: 4px; }
.arv-hero   { font-size: 2.8rem; font-weight: 800; color: #e85d04; line-height: 1; }
.step-label { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.1em;
               color: #e85d04; text-transform: uppercase; margin-bottom: 2px; }
.prop-photo-placeholder {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 32px 20px;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)

page_header("Comp Report", "Search any property · review comps · get your numbers in 60 seconds.", icon="📊")

# ── Step 1: Property Search ───────────────────────────────────────────────────
st.markdown('<div class="step-label">Step 1 — Find Property</div>', unsafe_allow_html=True)
query = st.text_input(
    "address_search",
    placeholder='Enter address or parcel ID — e.g. "4521 Oak St" or "0651040050025"',
    label_visibility="collapsed",
    key="cr_query",
)

if not query or len(query.strip()) < 3:
    st.info("Enter a property address or parcel ID above to get started.")
    st.stop()


@st.cache_data(ttl=60, show_spinner="Searching…")
def _search(q: str) -> list[dict]:
    like = f"%{q.upper()}%"
    return execute(
        """
        SELECT p.parcel_id, p.full_address, p.situs_num, p.situs_street,
               p.situs_city, p.situs_zip, p.total_mkt_val, p.total_appr_val,
               o.owner_name, o.is_absentee, o.mail_city, o.mail_state,
               b.living_area, b.year_built, b.condition,
               b.bedrooms, b.full_baths, b.half_baths
        FROM parcels p
        LEFT JOIN owners   o ON o.parcel_id = p.parcel_id
        LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        WHERE UPPER(p.full_address) ILIKE %s OR p.parcel_id = %s
        LIMIT 10
        """,
        (like, q.strip()),
    )


rows = _search(query.strip())
if not rows:
    st.warning("No properties found. Try a partial street name or parcel ID.")
    st.stop()

if len(rows) > 1:
    opts = {(r["full_address"] or r["parcel_id"]): r for r in rows}
    sel  = st.selectbox("Multiple matches — pick one:", list(opts.keys()))
    prop = opts[sel]
else:
    prop = rows[0]

# ── Step 2: Property Profile ──────────────────────────────────────────────────
st.divider()
st.markdown('<div class="step-label">Step 2 — Property Profile</div>', unsafe_allow_html=True)

address_str = prop["full_address"] or fmt_address(
    prop.get("situs_num", ""), prop.get("situs_street", ""),
    prop.get("situs_city", "Houston"), "TX", prop.get("situs_zip", ""),
)

photo_col, info_col = st.columns([1, 2], gap="large")

with photo_col:
    # Geocode once per address (cached)
    @st.cache_data(ttl=3600, show_spinner=False)
    def _geocode(addr: str):
        return geocode(addr, city=prop.get("situs_city") or "Houston", state="TX")

    coords = _geocode(address_str)

    if GOOGLE_MAPS_API_KEY and coords:
        lat, lon = coords
        img_url = street_view_url(lat, lon, GOOGLE_MAPS_API_KEY)
        st.image(img_url, use_container_width=True, caption="📷 Street View")
    elif coords:
        # Free satellite map via folium + Esri WorldImagery tiles
        lat, lon = coords
        m = folium.Map(
            location=[lat, lon],
            zoom_start=18,
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
        )
        folium.Marker(
            [lat, lon],
            tooltip=address_str,
            icon=folium.Icon(color="orange", icon="home", prefix="fa"),
        ).add_to(m)
        st_folium(m, width=420, height=300, returned_objects=[])
        st.caption("🛰️ Satellite view — add `GOOGLE_MAPS_API_KEY` to .env for Street View")
    else:
        st.markdown(
            f'<div class="prop-photo-placeholder">'
            f'<div style="font-size:3rem;">🏠</div>'
            f'<div style="font-weight:600;margin:8px 0;font-size:0.9rem;">{address_str}</div>'
            f'<div style="font-size:0.75rem;color:#888;">Could not geocode address</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Photo links — always show
    st.markdown("**📸 View Property Photos:**")
    plinks = photo_links(address_str, *coords) if coords else photo_links(address_str)
    link_parts = [f"[{name}]({url})" for name, url in plinks.items()]
    st.markdown(" &nbsp;|&nbsp; ".join(link_parts), unsafe_allow_html=True)

with info_col:
    beds  = prop["bedrooms"]   or "?"
    baths = prop["full_baths"] or "?"
    hb    = f"+{prop['half_baths']}h" if prop.get("half_baths") else ""
    sqft_disp = f"{int(prop['living_area']):,}" if prop["living_area"] else "—"
    yr    = prop["year_built"] or "—"
    cond  = prop["condition"] or "Average"

    st.markdown(f"### {address_str}")
    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Beds", beds)
    mc2.metric("Baths", f"{baths} {hb}".strip())
    mc3.metric("Sqft", sqft_disp)
    mc4.metric("Year Built", yr)

    vc1, vc2 = st.columns(2)
    vc1.metric("HCAD Appraised", fmt_currency(prop["total_appr_val"]))
    vc2.metric("HCAD Market", fmt_currency(prop["total_mkt_val"]))

    absentee_flag = "⚠️ Absentee owner" if prop.get("is_absentee") else "✅ Local owner"
    st.markdown(f"**Condition:** {cond} &nbsp;·&nbsp; **Owner:** {prop['owner_name'] or '—'}")
    st.caption(f"{absentee_flag} &nbsp;·&nbsp; Parcel: `{prop['parcel_id']}`")

    btn1, btn2 = st.columns(2)
    if btn1.button("💡 Full Analysis", key="cr_goto_analysis"):
        st.session_state["analysis_parcel_id"] = prop["parcel_id"]
        st.switch_page("pages/04_Analysis.py")
    if btn2.button("📁 Save to My Work", key="cr_goto_work"):
        st.session_state["search_query"] = prop["full_address"]
        st.switch_page("pages/01_Search.py")

# ── Step 3: Comparable Properties ────────────────────────────────────────────
st.divider()
st.markdown('<div class="step-label">Step 3 — Comparable Properties (AI-selected)</div>',
            unsafe_allow_html=True)
st.caption("Top matches by size, age, and location. Uncheck any comp that doesn't fit.")

sqft_raw = prop["living_area"]
yr_val   = int(prop["year_built"] or 1_990)
zip_val  = prop["situs_zip"] or ""
mkt_val  = float(prop["total_mkt_val"] or 0)

# ── Missing building data — let user fill in manually ────────────────────────
if not sqft_raw:
    st.warning(
        f"⚠️ **No building data** in HCAD for this parcel. "
        f"HCAD value is **{fmt_currency(mkt_val)}** — comps will match by value range (±40%). "
        f"Enter the actual sqft below for more accurate size-matched comps."
    )
    manual_col1, manual_col2 = st.columns(2)
    manual_sqft = manual_col1.number_input(
        "Living Area (sqft)", min_value=0, max_value=30_000, value=0, step=100,
        key="cr_manual_sqft",
        help="Enter from county records, Zillow, or the listing"
    )
    manual_yr = manual_col2.number_input(
        "Year Built", min_value=1900, max_value=2026, value=2000, step=1,
        key="cr_manual_yr"
    )
    sqft_val = float(manual_sqft) if manual_sqft > 0 else None
    yr_val   = manual_yr
else:
    sqft_val = float(sqft_raw)


@st.cache_data(ttl=120, show_spinner="Finding comps…")
def _comps(parcel_id: str, sqft: float | None, yr: int, zip_code: str,
           subject_value: float) -> list[dict]:
    return find_comps(parcel_id, sqft, yr, zip_code, n=9,
                      subject_value=subject_value if subject_value > 0 else None)


all_comps = _comps(prop["parcel_id"], sqft_val, yr_val, zip_val, mkt_val)
display_comps = all_comps[:6]

if not display_comps:
    st.warning("Not enough comps found in this ZIP. Try lowering filters on the Analysis page.")
    st.stop()

# Data quality banner
_sold_n = sum(1 for c in display_comps if c.get("comp_source") == "sold")
if _sold_n == 0:
    st.warning(
        "⚠️ **HCAD assessed values only** — no recent sale prices in this ZIP. "
        "Run `python ingestion/ingest_hcad.py` to load actual sold prices. "
        "ARV may differ from true market value."
    )
elif _sold_n < len(display_comps):
    st.info(f"📊 {_sold_n} of {len(display_comps)} comps have actual sale prices; rest use HCAD estimates.")
else:
    st.success(f"✅ All {_sold_n} comps based on verified recent sale prices.")

selected_comps: list[dict] = []
for row_start in range(0, len(display_comps), 3):
    row_comps = display_comps[row_start : row_start + 3]
    cols = st.columns(3)
    for col, comp in zip(cols, row_comps):
        with col:
            key = f"comp_sel_{comp['parcel_id']}"
            is_sel = st.checkbox("Include", value=True, key=key,
                                  label_visibility="collapsed")

            comp_val  = comp.get("comp_value") or comp.get("total_mkt_val")
            ppsf = (
                float(comp_val) / float(comp["living_area"])
                if comp_val and comp["living_area"]
                else None
            )
            card_class = "comp-card selected" if is_sel else "comp-card"
            ppsf_str  = f"${ppsf:,.0f}/sqft" if ppsf else "—"
            sqft_str  = f"{int(comp['living_area']):,} sqft" if comp["living_area"] else "?"
            yr_str    = str(comp["year_built"] or "?")
            cond_str  = comp["condition"] or "?"
            addr_s    = (comp["full_address"] or comp["parcel_id"])
            source    = comp.get("comp_source", "hcad_estimate")
            sale_dt   = comp.get("sale_dt")
            src_badge = (
                f'✅ Sold {sale_dt.strftime("%b %Y") if sale_dt else ""}'
                if source == "sold" else "⚠️ HCAD Est."
            )

            st.markdown(
                f"""
                <div class="{card_class}">
                    <div class="comp-addr" title="{addr_s}">{addr_s}</div>
                    <div class="comp-price">{fmt_currency(comp_val)}</div>
                    <div class="comp-ppsf">{ppsf_str}</div>
                    <div class="comp-meta">{sqft_str} &nbsp;·&nbsp; {yr_str} &nbsp;·&nbsp; {cond_str}</div>
                    <div class="comp-meta" style="margin-top:4px;">{src_badge}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.checkbox("✓ Include in ARV", value=is_sel, key=f"{key}_label",
                        disabled=True, label_visibility="visible")

            if is_sel:
                selected_comps.append(comp)

if not selected_comps:
    st.warning("Select at least one comp to calculate ARV.")
    st.stop()

# ── Step 4: ARV + Repair Estimate ────────────────────────────────────────────
st.divider()
st.markdown('<div class="step-label">Step 4 — ARV & Repair Estimate</div>', unsafe_allow_html=True)

arv_data = compute_arv(selected_comps, sqft_val)
arv = arv_data["arv"]

arv_col, rep_col = st.columns([1, 2], gap="large")

with arv_col:
    if arv:
        ds = arv_data.get("data_source", "hcad_estimate")
        sold_n = arv_data.get("sold_comp_count", 0)
        ds_label = (
            f"✅ {sold_n} sold" if ds == "sold"
            else "⚠️ HCAD estimates"
        )
        st.markdown(
            f'<div class="arv-hero">{fmt_currency(arv)}</div>'
            f'<div style="color:#aaa;font-size:0.85rem;margin-top:4px;">'
            f'ARV &nbsp;·&nbsp; {arv_data["comp_count"]} comps &nbsp;·&nbsp; '
            f'<strong>{arv_data["confidence"]}</strong> confidence &nbsp;·&nbsp; {ds_label}</div>',
            unsafe_allow_html=True,
        )
        if arv_data["price_per_sqft"]:
            st.caption(f"${arv_data['price_per_sqft']:,.0f} / sqft")
        if ds == "hcad_estimate":
            st.caption("⚠️ Based on HCAD assessed values — ingest sales history for actual sold comps.")
    else:
        st.warning("Not enough comps selected to calculate ARV.")

with rep_col:
    preset_map = {
        "Light Touch": "Excellent",
        "Cosmetic":    "Good",
        "Medium":      "Average",
        "Heavy":       "Low",
        "Full Gut":    "Very Low",
    }
    repair_preset = st.radio(
        "Repair preset",
        list(preset_map.keys()),
        index=2,
        horizontal=True,
        key="cr_repair_preset",
    )
    repair_cond = preset_map[repair_preset]
    repair_est  = estimate_repairs(repair_cond, sqft_val)
    repair_mid  = int((repair_est["low"] + repair_est["high"]) / 2)

    repairs = st.slider(
        "Repair cost ($)",
        min_value=0,
        max_value=max(int(repair_est["high"] * 1.5), 100_000),
        value=repair_mid,
        step=1_000,
        format="$%d",
        key="cr_repairs",
    )
    st.caption(
        f"Benchmark for **{repair_preset}**: "
        f"{fmt_currency(repair_est['low'])} – {fmt_currency(repair_est['high'])} "
        f"(${repair_est['rate_low']}–${repair_est['rate_high']}/sqft)"
    )

# ── Step 5: Deal Type Calculator ─────────────────────────────────────────────
st.divider()
st.markdown('<div class="step-label">Step 5 — Deal Type & Offer</div>', unsafe_allow_html=True)

if not arv:
    st.info("Select comps above to unlock the offer calculator.")
    st.stop()

tab_ws, tab_ff, tab_bh, tab_brr, tab_nov = st.tabs(
    ["🏷️ Wholesale", "🔨 Fix & Flip", "🏡 Buy & Hold", "♻️ BRRRR", "🤝 Novation"]
)

# ─── Wholesale ────────────────────────────────────────────────────────────────
with tab_ws:
    st.markdown("#### Wholesale — Assign the Contract")
    wc1, wc2 = st.columns(2)
    arv_pct    = wc1.radio("ARV %", [60, 65, 70], index=1, horizontal=True,
                             format_func=lambda x: f"{x}%", key="ws_pct")
    assign_fee = wc2.number_input("Your Assignment Fee ($)", 0, 500_000,
                                   10_000, 500, key="ws_fee")

    mao          = max(0.0, arv * (arv_pct / 100) - repairs)
    seller_price = max(0.0, mao - assign_fee)

    with st.container(border=True):
        wm1, wm2, wm3, wm4 = st.columns(4)
        wm1.metric("ARV", fmt_currency(arv))
        wm2.metric(f"MAO ({arv_pct}%)", fmt_currency(mao))
        wm3.metric("Max Offer to Seller", fmt_currency(seller_price),
                   help="Contract at this price or below")
        wm4.metric("Your Assignment Fee", fmt_currency(assign_fee),
                   delta="Your profit" if assign_fee > 0 else None)

    if seller_price > 0:
        st.success(
            f"Offer seller **{fmt_currency(seller_price)}** or less · "
            f"assign to buyer at **{fmt_currency(mao)}** · "
            f"pocket **{fmt_currency(assign_fee)}**."
        )
    else:
        st.warning("Repairs and/or fee leave no room at this ARV%. Try 70% or reduce the fee.")

# ─── Fix & Flip ───────────────────────────────────────────────────────────────
with tab_ff:
    st.markdown("#### Fix & Flip — Rehab & Resell")
    fc1, fc2, fc3 = st.columns(3)
    profit_pct   = fc1.slider("Profit target %", 10, 30, 15, key="ff_profit") / 100
    holding_mo   = fc2.slider("Holding months",  2, 12, 4,  key="ff_months")
    closing_pct  = fc3.slider("Closing costs %", 1,  8, 4,  key="ff_closing") / 100

    flip = compute_flip_offer(arv, repairs, profit_pct, holding_mo, 0.005, closing_pct)

    with st.container(border=True):
        fm1, fm2, fm3, fm4 = st.columns(4)
        fm1.metric("Sale Price (ARV)", fmt_currency(arv))
        fm2.metric("Repairs",          fmt_currency(repairs))
        fm3.metric("Profit Target",    fmt_currency(flip["profit_target"]))
        fm4.metric("Max Offer",        fmt_currency(flip["max_offer"]),
                   delta="Buy at or below")

    st.caption(
        f"Holding costs: {fmt_currency(flip['holding_costs'])} &nbsp;·&nbsp; "
        f"Closing costs: {fmt_currency(flip['closing_costs'])}"
    )

# ─── Buy & Hold ───────────────────────────────────────────────────────────────
with tab_bh:
    st.markdown("#### Buy & Hold — Long-Term Rental")
    bh1, bh2, bh3 = st.columns(3)
    default_price = max(0, int(arv * 0.70 - repairs))
    bh_price = bh1.number_input("Purchase Price ($)", 0, 2_000_000,
                                  default_price, 1_000, key="bh_price")
    bh_rent  = bh2.number_input("Monthly Rent ($)", 0, 20_000, 1_400, 50, key="bh_rent")
    bh_down  = bh3.slider("Down Payment %", 5, 30, 20, key="bh_down") / 100

    hold = compute_hold(arv, bh_price, bh_rent * 12, down_pct=bh_down)

    with st.container(border=True):
        hm1, hm2, hm3, hm4 = st.columns(4)
        hm1.metric("Monthly Cash Flow",
                   fmt_currency(hold["annual_cash_flow"] / 12),
                   delta="positive" if hold["annual_cash_flow"] > 0 else "negative",
                   delta_color="normal" if hold["annual_cash_flow"] > 0 else "inverse")
        hm2.metric("Cap Rate",     f"{hold['cap_rate'] * 100:.1f}%")
        hm3.metric("Cash-on-Cash", f"{hold['coc_return'] * 100:.1f}%")
        hm4.metric("GRM",          f"{hold['gross_rent_multiplier']:.1f}x")

    st.caption(
        f"Down: {fmt_currency(hold['down_payment'])} &nbsp;·&nbsp; "
        f"Monthly P&I: {fmt_currency(hold['monthly_payment'])} &nbsp;·&nbsp; "
        f"Annual NOI: {fmt_currency(hold['noi'])}"
    )

# ─── BRRRR ────────────────────────────────────────────────────────────────────
with tab_brr:
    st.markdown("#### BRRRR — Buy · Rehab · Rent · Refinance · Repeat")
    br1, br2, br3 = st.columns(3)
    default_brr = max(0, int(arv * 0.65 - repairs))
    brr_price   = br1.number_input("Purchase Price ($)", 0, 2_000_000,
                                    default_brr, 1_000, key="brr_price")
    brr_rent    = br2.number_input("Monthly Rent ($)", 0, 20_000,
                                    1_400, 50, key="brr_rent")
    refi_ltv    = br3.slider("Refi LTV %", 60, 80, 75, key="brr_ltv") / 100

    brr = compute_brrr(arv, repairs, brr_price, refi_ltv=refi_ltv,
                        annual_rent=brr_rent * 12)

    with st.container(border=True):
        bm1, bm2, bm3, bm4 = st.columns(4)
        bm1.metric("Total Invested",   fmt_currency(brr["total_invested"]))
        bm2.metric("Refi Loan",        fmt_currency(brr["refi_loan_amount"]))
        cash_out_val = brr["cash_out"]
        bm3.metric(
            "Cash Out at Refi",
            fmt_currency(cash_out_val),
            delta="✅ All-in recovered" if cash_out_val >= 0 else f"${abs(cash_out_val):,.0f} left in",
            delta_color="normal" if cash_out_val >= 0 else "inverse",
        )
        bm4.metric("Equity Remaining", fmt_currency(brr["equity_remaining"]))

    if "annual_cash_flow" in brr:
        st.caption(
            f"Annual cash flow: {fmt_currency(brr['annual_cash_flow'])} &nbsp;·&nbsp; "
            f"Cap rate: {brr['cap_rate'] * 100:.1f}%"
        )

# ─── Novation ─────────────────────────────────────────────────────────────────
with tab_nov:
    st.markdown("#### Novation — List on the Seller's Behalf")
    nc1, nc2, nc3 = st.columns(3)
    nov_agent   = nc1.slider("Agent Commission %", 3, 8, 6, key="nov_agent") / 100
    nov_cont    = nc2.number_input("Buffer / Contingency ($)", 0, 50_000,
                                    5_000, 500, key="nov_cont")
    nov_repairs = nc3.number_input("Repair Credit to Buyer ($)", 0, 200_000,
                                    int(repairs), 500, key="nov_rep")

    nov = compute_novation(arv, nov_repairs, nov_agent, nov_cont)

    with st.container(border=True):
        nm1, nm2, nm3 = st.columns(3)
        nm1.metric("List Price (ARV)",  fmt_currency(nov["list_price"]))
        nm2.metric("Net to Seller",     fmt_currency(nov["net_to_seller"]))
        nm3.metric("Your Spread",       fmt_currency(nov["investor_spread"]),
                   delta="Your earnings")

    st.caption(
        f"Agent commission: {fmt_currency(nov['agent_commission'])} &nbsp;·&nbsp; "
        f"Repair allowance: {fmt_currency(nov['repair_allowance'])} &nbsp;·&nbsp; "
        f"Contingency: {fmt_currency(nov['contingency'])}"
    )

# ── Step 6: Report Summary ────────────────────────────────────────────────────
st.divider()
st.markdown('<div class="step-label">Step 6 — Report Summary</div>', unsafe_allow_html=True)

with st.expander("📋 View & Share Report", expanded=False):
    flip_summary = compute_flip_offer(arv, repairs)
    lines = [
        f"**Property:** {address_str}",
        f"**Parcel ID:** {prop['parcel_id']}",
        (
            f"**Size:** {sqft_val:,.0f} sqft &nbsp;·&nbsp; "
            f"{prop['bedrooms'] or '?'} bed / {prop['full_baths'] or '?'} bath &nbsp;·&nbsp; "
            f"Built {prop['year_built'] or '?'}"
        ),
        f"**Condition:** {cond}",
        f"**HCAD Market Value:** {fmt_currency(prop['total_mkt_val'])}",
        "",
        f"**ARV Estimate:** {fmt_currency(arv)} "
        f"({arv_data['comp_count']} comps &nbsp;·&nbsp; {arv_data['confidence']} confidence)",
        f"**Repair Estimate:** {fmt_currency(repairs)} — {repair_preset}",
        "",
        f"**Wholesale MAO (65%):** {fmt_currency(max(0.0, arv * 0.65 - repairs))}",
        f"**Fix & Flip Max Offer:** {fmt_currency(flip_summary['max_offer'])}",
        "",
        f"**Comps Used ({len(selected_comps)}):**",
    ]
    for c in selected_comps:
        comp_val_c = c.get("comp_value") or c.get("total_mkt_val") or 0
        ppsf_c = (
            float(comp_val_c) / float(c["living_area"])
            if comp_val_c and c["living_area"] else 0.0
        )
        sqft_c = f"{int(c['living_area']):,} sqft" if c["living_area"] else "?"
        src_c  = "✅ Sold" if c.get("comp_source") == "sold" else "⚠️ HCAD Est."
        lines.append(
            f"&nbsp;&nbsp;• {c['full_address'] or c['parcel_id']} — "
            f"{fmt_currency(comp_val_c)} · ${ppsf_c:,.0f}/sqft · {sqft_c} · {src_c}"
        )

    st.markdown("\n\n".join(lines), unsafe_allow_html=True)
    st.caption("Use Ctrl+P / Cmd+P to print or save as PDF.")
