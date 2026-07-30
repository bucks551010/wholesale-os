import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency
from app.utils.comps import REPAIR_RATES

st.set_page_config(page_title="My Work", page_icon="📁", layout="wide")

# Ensure work_tasks table exists
execute("""
    CREATE TABLE IF NOT EXISTS work_tasks (
        id SERIAL PRIMARY KEY,
        lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
        task_text TEXT NOT NULL,
        due_date DATE,
        priority TEXT DEFAULT 'normal',
        is_done BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        completed_at TIMESTAMPTZ
    )
""", commit=True)
execute("ALTER TABLE active_deals ADD COLUMN IF NOT EXISTS seller_notes TEXT", commit=True)

st.title("📁 My Work")
st.caption("Save properties, track every deal detail, log contacts, and manage tasks — all in one workspace.")

left_col, right_col = st.columns([1, 3], gap="large")

# ── LEFT PANEL: property list + add ───────────────────────────────────────────
with left_col:
    st.subheader("🏠 My Properties")

    active_deals = execute("""
        SELECT ad.id, p.full_address, p.situs_zip, ad.status,
               ad.seller_name, l.motivated_score, l.id AS lead_id,
               ad.purchase_price, ad.assignment_fee_target
        FROM active_deals ad
        JOIN leads   l ON l.id = ad.lead_id
        JOIN parcels p ON p.parcel_id = l.parcel_id
        WHERE ad.status != 'dead'
        ORDER BY ad.created_at DESC
    """)

    STATUS_ICON = {
        "new_lead":       "🆕",
        "contacted":      "📞",
        "analyzing":      "🔍",
        "negotiating":    "🤝",
        "under_contract": "📝",
        "assigned":       "💰",
    }
    selected_id = st.session_state.get("mw_deal_id")

    if not active_deals:
        st.info("No active properties yet. Search below to add one.")

    for d in active_deals:
        is_sel = selected_id == d["id"]
        icon   = STATUS_ICON.get(d["status"], "")
        addr   = d["full_address"][:34]
        with st.container(border=is_sel):
            st.markdown(f"{icon} **{addr}**")
            score_str = f"Score {d['motivated_score']}"
            price_str = f" · Buy {fmt_currency(d['purchase_price'])}" if d["purchase_price"] else ""
            st.caption(f"{score_str}{price_str}")
            if st.button("Open →", key=f"mw_open_{d['id']}", use_container_width=True,
                         type="primary" if is_sel else "secondary"):
                st.session_state["mw_deal_id"] = d["id"]
                st.rerun()

    st.divider()

    with st.expander("➕ Add a Property to Work On"):
        addr_q = st.text_input("Search by address or ZIP", key="mw_addr_q", placeholder="e.g. 4521 Elm or 77051")
        if addr_q and len(addr_q) >= 3:
            # Search all parcels (same as Search page), not just pre-scored leads
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
                LIMIT 15
            """, (f"%{addr_q.upper()}%", addr_q.strip(), f"%{addr_q.upper()}%"))
            if not hits:
                st.caption("No properties found. Try a partial street name, parcel ID, or owner name.")
            for h in hits:
                already = execute(
                    "SELECT ad.id FROM active_deals ad JOIN leads l ON l.id=ad.lead_id "
                    "WHERE l.parcel_id=%s AND ad.status!='dead' LIMIT 1",
                    (h["parcel_id"],)
                )
                badge = " ✅ already saved" if already else ""
                label = f"{h['full_address'][:42]}  |  {h['owner_name'] or ''}  |  Score {h['motivated_score']}{badge}"
                if st.button(label, key=f"mw_hit_{h['parcel_id']}", use_container_width=True):
                    if already:
                        st.session_state["mw_deal_id"] = already[0]["id"]
                        st.rerun()
                    else:
                        # Create lead if not scored yet
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
                                "INSERT INTO active_deals (lead_id, status, created_at) VALUES (%s,'new_lead',NOW()) RETURNING id",
                                (lead_id,), commit=True
                            )
                            if res:
                                st.session_state["mw_deal_id"] = res[0]["id"]
                                st.rerun()


# ── RIGHT PANEL: workspace ────────────────────────────────────────────────────
with right_col:
    deal_id = st.session_state.get("mw_deal_id")

    if not deal_id:
        st.markdown("### 👈 Select or add a property to get started")
        st.markdown("""
**What you can do here:**
- 🏠 View full property details — HCAD value, building, owner, liens, permits, violations
- 💰 Track deal numbers — ARV, repair estimate, offer price, assignment fee
- 🧑 Save seller contact info and contract dates
- 📝 Log every call, text, and meeting with timestamps
- ✅ Create and check off tasks with due dates and priority levels
- 🎯 Find and notify matching cash buyers for this deal
""")
        st.stop()

    # Load full deal record
    deal_rows = execute("""
        SELECT ad.id, ad.lead_id, ad.seller_name, ad.seller_phone, ad.seller_email,
               ad.contract_date, ad.purchase_price, ad.option_period_days, ad.option_expiry,
               ad.closing_date, ad.title_company, ad.title_company_contact,
               ad.earnest_money_amount, ad.em_status, ad.assignment_fee_target,
               ad.status, ad.notes, ad.seller_notes, ad.created_at,
               p.full_address, p.situs_zip, p.total_mkt_val, p.total_appr_val,
               p.land_val, p.improvement_val, p.parcel_id,
               l.motivated_score, l.deal_score, l.priority, l.notes AS lead_notes,
               l.status AS lead_status
        FROM active_deals ad
        JOIN leads   l ON l.id = ad.lead_id
        JOIN parcels p ON p.parcel_id = l.parcel_id
        WHERE ad.id = %s
    """, (deal_id,))

    if not deal_rows:
        st.error("Deal not found.")
        del st.session_state["mw_deal_id"]
        st.stop()

    d = deal_rows[0]
    parcel_id = d["parcel_id"]
    lead_id   = d["lead_id"]

    # ── Header bar ─────────────────────────────────────────────────────────
    h1, h2, h3, h4 = st.columns([3, 1, 1, 1])
    h1.header(d["full_address"])
    h1.caption(f"ZIP {d['situs_zip']} · Parcel {parcel_id}")
    h2.metric("Motivated Score",  d["motivated_score"])
    h3.metric("HCAD Value",       fmt_currency(d["total_mkt_val"]))
    h4.metric("Deal Score",       d["deal_score"] or "—")

    STAGE_KEYS = ["new_lead","contacted","analyzing","negotiating","under_contract","assigned"]
    STAGE_LABELS = {"new_lead":"🆕 New Lead","contacted":"📞 Contacted","analyzing":"🔍 Analyzing",
                    "negotiating":"🤝 Negotiating","under_contract":"📝 Under Contract","assigned":"💰 Assigned"}

    sc1, sc2 = st.columns([1, 5])
    new_status = sc1.selectbox(
        "Status",
        options=STAGE_KEYS,
        format_func=lambda k: STAGE_LABELS[k],
        index=STAGE_KEYS.index(d["status"]) if d["status"] in STAGE_KEYS else 0,
        key="mw_status_select",
    )
    if new_status != d["status"]:
        execute("UPDATE active_deals SET status=%s WHERE id=%s", (new_status, deal_id), commit=True)
        st.rerun()

    if sc2.button("🗑️ Remove from My Work", key="mw_kill"):
        execute("UPDATE active_deals SET status='dead' WHERE id=%s", (deal_id,), commit=True)
        del st.session_state["mw_deal_id"]
        st.rerun()

    st.divider()

    # ── 6 workspace tabs ───────────────────────────────────────────────────
    t_ov, t_deal, t_seller, t_act, t_tasks, t_buyers = st.tabs([
        "🏠 Overview", "💰 Deal Numbers", "🧑 Seller", "📝 Activity Log", "✅ Tasks", "🎯 Buyers"
    ])

    # ── OVERVIEW ─────────────────────────────────────────────────────────
    with t_ov:
        ov1, ov2, ov3 = st.columns(3)
        ov1.metric("Land Value",        fmt_currency(d["land_val"]))
        ov2.metric("Improvement Value", fmt_currency(d["improvement_val"]))
        ov3.metric("Appraised Value",   fmt_currency(d["total_appr_val"]))

        b_col, o_col = st.columns(2)

        # Building info
        bldg = execute("""
            SELECT living_area, year_built, bedrooms, full_baths, half_baths,
                   condition, stories, pool_flag, building_class
            FROM buildings WHERE parcel_id=%s AND building_num=1 LIMIT 1
        """, (parcel_id,))

        with b_col:
            st.subheader("🏗️ Building")
            if bldg:
                bld = bldg[0]
                rows = [
                    ("Living Area", f"{int(bld['living_area']):,} sqft" if bld["living_area"] else "—"),
                    ("Year Built",  str(bld["year_built"]) if bld["year_built"] else "—"),
                    ("Bedrooms",    str(bld["bedrooms"]) if bld["bedrooms"] else "—"),
                    ("Full Baths",  str(bld["full_baths"]) if bld["full_baths"] else "—"),
                    ("Half Baths",  str(bld["half_baths"]) if bld["half_baths"] else "—"),
                    ("Stories",     str(bld["stories"]) if bld["stories"] else "—"),
                    ("Condition",   bld["condition"] or "—"),
                    ("Pool",        "✅ Yes" if bld["pool_flag"] else "❌ No"),
                    ("Class",       bld["building_class"] or "—"),
                ]
                for label, val in rows:
                    st.markdown(f"**{label}:** {val}")
            else:
                st.caption("No building data on file.")

        # Owner info
        owner = execute("""
            SELECT owner_name, owner_type, mail_addr_1, mail_city, mail_state, mail_zip
            FROM owners WHERE parcel_id=%s LIMIT 1
        """, (parcel_id,))

        with o_col:
            st.subheader("👤 Owner of Record")
            if owner:
                ow = owner[0]
                st.markdown(f"**Name:** {ow['owner_name'] or '—'}")
                st.markdown(f"**Type:** {ow['owner_type'] or '—'}")
                mail = ", ".join(p for p in [ow["mail_addr_1"], ow["mail_city"],
                                             ow["mail_state"], ow["mail_zip"]] if p)
                st.markdown(f"**Mailing:** {mail or '—'}")
            else:
                st.caption("No owner data on file.")

        # Risk metrics row
        st.subheader("⚠️ Risk Factors")
        rm1, rm2, rm3, rm4, rm5 = st.columns(5)

        val_row = execute("""
            SELECT arv_estimate, comp_count, confidence FROM valuations
            WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1
        """, (parcel_id,))
        rm1.metric("ARV", fmt_currency(val_row[0]["arv_estimate"]) if val_row else "—")

        liens_n  = execute("SELECT COUNT(*) AS n FROM liens     WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        perms_n  = execute("SELECT COUNT(*) AS n FROM permits   WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        viols_n  = execute("SELECT COUNT(*) AS n FROM violations WHERE parcel_id=%s", (parcel_id,))[0]["n"]
        fore_n   = execute("SELECT COUNT(*) AS n FROM foreclosures WHERE parcel_id=%s", (parcel_id,))[0]["n"]

        rm2.metric("Liens",       liens_n,  delta=None if liens_n == 0 else "⚠️", delta_color="inverse")
        rm3.metric("Permits",     perms_n)
        rm4.metric("Violations",  viols_n,  delta=None if viols_n == 0 else "⚠️", delta_color="inverse")
        rm5.metric("Foreclosures",fore_n,   delta=None if fore_n == 0 else "⚠️", delta_color="inverse")

        if d["lead_notes"]:
            st.subheader("📋 Lead Notes")
            st.info(d["lead_notes"])

    # ── DEAL NUMBERS ─────────────────────────────────────────────────────
    with t_deal:
        latest_val = execute("""
            SELECT arv_estimate, comp_count, confidence, calc_date, price_per_sqft,
                   est_monthly_rent, cap_rate_arv
            FROM valuations WHERE parcel_id=%s ORDER BY calc_date DESC LIMIT 1
        """, (parcel_id,))

        latest_rep = execute("""
            SELECT condition_tier, total_low, total_high, contingency_pct, created_date, notes
            FROM repair_estimates WHERE parcel_id=%s ORDER BY created_date DESC LIMIT 1
        """, (parcel_id,))

        latest_offers = execute("""
            SELECT scenario, arv, arv_pct, repair_cost, offer_price, target_fee,
                   buyer_profit, feasible, calc_date
            FROM offer_options WHERE lead_id=%s ORDER BY calc_date DESC LIMIT 5
        """, (lead_id,))

        dn_a, dn_b = st.columns(2)

        with dn_a:
            st.subheader("📊 ARV / Valuation")
            if latest_val:
                v = latest_val[0]
                st.metric("ARV Estimate", fmt_currency(v["arv_estimate"]))
                va1, va2, va3 = st.columns(3)
                va1.metric("Comps",      v["comp_count"] or "—")
                va2.metric("Confidence", v["confidence"] or "—")
                va3.metric("$/sqft",     fmt_currency(v["price_per_sqft"]))
                if v["est_monthly_rent"]:
                    st.metric("Est. Monthly Rent", fmt_currency(v["est_monthly_rent"]))
                st.caption(f"As of {v['calc_date'] or '—'}")
            else:
                st.info("No ARV calculated yet. Use the **Deal Analysis** page to run comps.")

        with dn_b:
            st.subheader("🔨 Repair Estimate")
            if latest_rep:
                r = latest_rep[0]
                st.metric("Repair Range",
                          f"{fmt_currency(r['total_low'])} – {fmt_currency(r['total_high'])}")
                st.caption(f"Condition: **{r['condition_tier'] or '—'}** · {r['created_date'].date() if r['created_date'] else '—'}")
                if r["notes"]:
                    st.caption(r["notes"])
            else:
                st.info("No repair estimate yet. Use the **Deal Analysis** page.")

        # Offer options table
        st.subheader("📋 Offer Scenarios")
        if latest_offers:
            import pandas as pd
            df_off = pd.DataFrame([{
                "Scenario":     o["scenario"] or "—",
                "ARV":          fmt_currency(o["arv"]),
                "% ARV":        f"{o['arv_pct']}%" if o["arv_pct"] else "—",
                "Repairs":      fmt_currency(o["repair_cost"]),
                "Offer Price":  fmt_currency(o["offer_price"]),
                "Target Fee":   fmt_currency(o["target_fee"]),
                "Buyer Profit": fmt_currency(o["buyer_profit"]),
                "Feasible":     "✅" if o["feasible"] else ("❌" if o["feasible"] is False else "?"),
                "Date":         str(o["calc_date"]) if o["calc_date"] else "—",
            } for o in latest_offers])
            st.dataframe(df_off, use_container_width=True, hide_index=True)
        else:
            st.info("No offer scenarios yet. Use the **Deal Analysis** page to calculate MAO.")

        # Inline editable financials
        st.subheader("✏️ Record Current Numbers")
        with st.form("mw_financials"):
            fc1, fc2, fc3 = st.columns(3)
            new_price  = fc1.number_input("Purchase Price ($)", min_value=0,
                                          value=int(d["purchase_price"] or 0), step=1000)
            new_fee    = fc2.number_input("Assignment Fee Target ($)", min_value=0,
                                          value=int(d["assignment_fee_target"] or 0), step=500)
            new_em     = fc3.number_input("Earnest Money ($)", min_value=0,
                                          value=int(d["earnest_money_amount"] or 0), step=100)
            fc4, fc5 = st.columns(2)
            em_options    = ["pending","received","forfeited","returned"]
            em_idx        = em_options.index(d["em_status"]) if d["em_status"] in em_options else 0
            new_em_status = fc4.selectbox("EM Status", em_options, index=em_idx)
            new_opt_days  = fc5.number_input("Option Period (days)", min_value=0,
                                             value=d["option_period_days"] or 10, step=1)
            new_notes     = st.text_area("Deal Notes", value=d["notes"] or "", height=80)
            if st.form_submit_button("💾 Save Financials", type="primary"):
                execute("""
                    UPDATE active_deals SET
                        purchase_price=%s, assignment_fee_target=%s,
                        earnest_money_amount=%s, em_status=%s,
                        option_period_days=%s, notes=%s
                    WHERE id=%s
                """, (new_price or None, new_fee or None, new_em or None,
                      new_em_status, new_opt_days or None,
                      new_notes.strip() or None, deal_id), commit=True)
                st.success("Financials saved!")
                st.rerun()

        # ── Live Assignment Fee Calculator ─────────────────────────────────
        st.divider()
        st.subheader("🏷️ Your Assignment Fee Calculator")

        _bldg_fc = execute("""
            SELECT living_area, condition FROM buildings
            WHERE parcel_id=%s AND building_num=1 LIMIT 1
        """, (parcel_id,))
        _sqft_fc = float((_bldg_fc[0]["living_area"] or 1200) if _bldg_fc else 1200)
        _cond_fc = ((_bldg_fc[0]["condition"] or "Low") if _bldg_fc else "Low")
        _lo_fc, _hi_fc = REPAIR_RATES.get(_cond_fc, (28, 40))
        _def_arv_fc = int(float(latest_val[0]["arv_estimate"]) if latest_val and latest_val[0]["arv_estimate"]
                          else float(d["total_mkt_val"] or 0) * 1.15)
        _def_rep_fc = int((_lo_fc + _hi_fc) / 2 * _sqft_fc)
        _def_off_fc = int(d["purchase_price"] or 0)

        cal1, cal2 = st.columns(2)
        fc_arv     = cal1.number_input("ARV ($)", min_value=0, value=_def_arv_fc, step=5000, key="mw_dn_arv")
        fc_repairs = cal2.number_input("Your Repair Estimate ($)", min_value=0, value=_def_rep_fc, step=1000,
                                        key="mw_dn_rep",
                                        help=f"Condition '{_cond_fc}' benchmark: ~${_def_rep_fc:,}")
        cal3, cal4 = st.columns(2)
        fc_closing  = cal3.number_input("Closing Costs ($)", min_value=0, value=3000, step=500, key="mw_dn_cls")
        fc_pct_lbl  = cal4.radio("Buyer's %", ["60%", "65%", "70%"], index=1, horizontal=True, key="mw_dn_pct")
        fc_pct      = int(fc_pct_lbl[:-1]) / 100
        fc_offer    = st.number_input("Your Contract Price (what you pay seller) ($)",
                                       min_value=0, value=_def_off_fc, step=1000, key="mw_dn_offer")

        fc_mao = fc_arv * fc_pct - fc_repairs - fc_closing
        fc_fee = fc_mao - fc_offer

        cm1, cm2, cm3, cm4 = st.columns(4)
        cm1.metric("ARV",            fmt_currency(fc_arv))
        cm2.metric("Buyer's MAO",    fmt_currency(max(0, fc_mao)))
        cm3.metric("Contract Price", fmt_currency(fc_offer))
        cm4.metric("🏷️ YOUR FEE",   fmt_currency(fc_fee),
                   delta="✅ Feasible" if fc_fee > 0 else "❌ Underwater",
                   delta_color="normal" if fc_fee > 0 else "inverse")

        with st.expander("📊 All 3 scenarios at your numbers"):
            import pandas as pd
            _sc_data = []
            for _lbl, _pct in [("Conservative (60%)", 0.60), ("Standard (65%)", 0.65), ("Aggressive (70%)", 0.70)]:
                _sc_mao = fc_arv * _pct - fc_repairs - fc_closing
                _sc_data.append({
                    "Scenario":  _lbl,
                    "Buyer MAO": fmt_currency(max(0, _sc_mao)),
                    "Your Fee":  fmt_currency(_sc_mao - fc_offer),
                    "Feasible":  "✅" if _sc_mao > fc_offer else "❌",
                })
            st.dataframe(pd.DataFrame(_sc_data), use_container_width=True, hide_index=True)

        if st.button("💾 Save Scenario", key="mw_dn_save", type="primary"):
            execute("""
                INSERT INTO offer_options
                    (lead_id, scenario, arv, arv_pct, repair_cost, closing_costs,
                     target_fee, offer_price, feasible, calc_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            """, (lead_id,
                  f"My Work {fc_pct_lbl}",
                  fc_arv, int(fc_pct * 100), fc_repairs, fc_closing,
                  max(0, int(fc_fee)), fc_offer, fc_fee > 0), commit=True)
            st.success("Scenario saved to Offer Scenarios!")
            st.rerun()

    # ── SELLER ────────────────────────────────────────────────────────────
    with t_seller:
        st.subheader("🧑 Seller & Contract Details")
        with st.form("mw_seller"):
            se1, se2 = st.columns(2)
            s_name   = se1.text_input("Seller Full Name",  value=d["seller_name"]  or "")
            s_phone  = se2.text_input("Seller Phone",      value=d["seller_phone"] or "")
            s_email  = se1.text_input("Seller Email",      value=d["seller_email"] or "")
            s_title  = se2.text_input("Title Company",     value=d["title_company"] or "")
            s_tcon   = se1.text_input("Title Co. Contact", value=d["title_company_contact"] or "")

            st.markdown("**Contract Dates**")
            dc1, dc2, dc3 = st.columns(3)
            today = datetime.date.today()
            # Use today as fallback for date_input (can't be None)
            s_contract = dc1.date_input("Contract Date",  value=d["contract_date"]   or today)
            s_opt_exp  = dc2.date_input("Option Expiry",  value=d["option_expiry"]   or today)
            s_closing  = dc3.date_input("Closing Date",   value=d["closing_date"]    or today)

            if st.form_submit_button("💾 Save Seller Info", type="primary"):
                execute("""
                    UPDATE active_deals SET
                        seller_name=%s, seller_phone=%s, seller_email=%s,
                        title_company=%s, title_company_contact=%s,
                        contract_date=%s, option_expiry=%s, closing_date=%s
                    WHERE id=%s
                """, (s_name.strip() or None, s_phone.strip() or None,
                      s_email.strip() or None, s_title.strip() or None,
                      s_tcon.strip() or None,
                      s_contract, s_opt_exp, s_closing,
                      deal_id), commit=True)
                st.success("Seller info saved!")
                st.rerun()

        st.divider()
        st.subheader("📋 Owner / Seller Facts")
        st.caption("Record motivation, circumstances, timeline — anything useful for your pitch.")
        with st.form("mw_seller_notes"):
            s_facts = st.text_area(
                "Facts & Notes",
                value=d.get("seller_notes") or "",
                height=200,
                placeholder=(
                    "e.g. Behind 3 months on mortgage, going through divorce, "
                    "wants to close in 30 days, absentee landlord in Dallas, "
                    "inherited the property, doesn't want to deal with repairs..."
                ),
            )
            if st.form_submit_button("💾 Save Facts", type="primary"):
                execute(
                    "UPDATE active_deals SET seller_notes=%s WHERE id=%s",
                    (s_facts.strip() or None, deal_id), commit=True,
                )
                st.success("Facts saved!")
                st.rerun()

    # ── ACTIVITY LOG ──────────────────────────────────────────────────────
    with t_act:
        st.subheader("📝 Activity Log")

        logs = execute("""
            SELECT id, contact_date, method, outcome, notes, next_followup, script_used
            FROM lead_contact_log WHERE lead_id=%s ORDER BY contact_date DESC
        """, (lead_id,))

        # Add new entry
        with st.expander("➕ Log New Activity", expanded=(len(logs) == 0)):
            with st.form("mw_activity"):
                al1, al2 = st.columns(2)
                act_method  = al1.selectbox("Method", ["Call","Text","Email","Letter",
                                                         "In-person","Voicemail","Door knock"])
                act_outcome = al2.selectbox("Outcome", [
                    "No answer","Left voicemail","Spoke — not interested",
                    "Spoke — interested","Appointment set","Letter sent",
                    "Offer made","Offer accepted","Offer rejected","Other",
                ])
                act_notes   = st.text_area("Notes", height=80,
                                           placeholder="What was said? Any key motivation details?")
                al3, al4 = st.columns(2)
                act_date     = al3.date_input("Contact Date",   value=datetime.date.today())
                act_followup = al4.date_input("Next Follow-up",
                                              value=datetime.date.today() + datetime.timedelta(days=3))
                act_script   = st.text_area("Script / Talking Points Used", height=50)
                if st.form_submit_button("💾 Log Activity", type="primary"):
                    execute("""
                        INSERT INTO lead_contact_log
                            (lead_id, contact_date, method, outcome, notes, next_followup, script_used)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """, (lead_id, act_date, act_method, act_outcome,
                          act_notes.strip() or None, act_followup,
                          act_script.strip() or None), commit=True)
                    st.success("Activity logged!")
                    st.rerun()

        if not logs:
            st.info("No activity logged yet — start by clicking ➕ above.")
        else:
            METHOD_ICON  = {"Call":"📞","Text":"💬","Email":"✉️","Letter":"📬",
                            "In-person":"🤝","Voicemail":"📱","Door knock":"🚪"}
            OUTCOME_DOT  = {"Spoke — interested":"🟢","Appointment set":"🟢",
                            "Offer accepted":"🟢","Offer made":"🟡",
                            "Spoke — not interested":"🔴","Offer rejected":"🔴",
                            "No answer":"⚫","Left voicemail":"⚫"}
            for entry in logs:
                icon = METHOD_ICON.get(entry["method"], "📌")
                dot  = OUTCOME_DOT.get(entry["outcome"], "🟡")
                with st.container(border=True):
                    la, lb, lc = st.columns([2, 2, 1])
                    la.markdown(f"**{icon} {entry['method']}** · {entry['contact_date']}")
                    lb.markdown(f"{dot} {entry['outcome']}")
                    if entry["next_followup"]:
                        lc.caption(f"Follow-up {entry['next_followup']}")
                    if entry["notes"]:
                        st.markdown(entry["notes"])
                    if entry["script_used"]:
                        with st.expander("Talking points"):
                            st.text(entry["script_used"])
                    if st.button("🗑️ Delete", key=f"del_log_{entry['id']}", type="secondary"):
                        execute("DELETE FROM lead_contact_log WHERE id=%s",
                                (entry["id"],), commit=True)
                        st.rerun()

    # ── TASKS ─────────────────────────────────────────────────────────────
    with t_tasks:
        st.subheader("✅ Tasks & Checklist")

        tasks = execute("""
            SELECT id, task_text, due_date, priority, is_done, created_at, completed_at
            FROM work_tasks WHERE lead_id=%s
            ORDER BY is_done, CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                     due_date NULLS LAST
        """, (lead_id,))

        # Add custom task
        with st.form("mw_new_task"):
            tk1, tk2, tk3 = st.columns([3, 1, 1])
            task_txt  = tk1.text_input("New Task", placeholder="e.g. Call seller back, Pull title search")
            task_due  = tk2.date_input("Due Date", value=None)
            task_pri  = tk3.selectbox("Priority", ["high","normal","low"])
            if st.form_submit_button("➕ Add Task", type="primary"):
                if task_txt.strip():
                    execute("INSERT INTO work_tasks (lead_id, task_text, due_date, priority) VALUES (%s,%s,%s,%s)",
                            (lead_id, task_txt.strip(), task_due, task_pri), commit=True)
                    st.rerun()

        pending = [t for t in tasks if not t["is_done"]]
        done    = [t for t in tasks if t["is_done"]]
        PRI_ICON = {"high":"🔴","normal":"🟡","low":"🟢"}

        if not pending and not done:
            st.info("No tasks yet. Add one above, or quick-add from the standard checklist below.")
        elif not pending:
            st.success("🎉 All tasks complete!")
        else:
            st.markdown(f"**{len(pending)} pending task{'s' if len(pending)>1 else ''}**")
            for t in pending:
                tc1, tc2, tc3 = st.columns([5, 1, 1])
                pri  = PRI_ICON.get(t["priority"], "⚪")
                due  = f" · Due **{t['due_date']}**" if t["due_date"] else ""
                overdue = t["due_date"] and t["due_date"] < datetime.date.today()
                prefix = "🚨 " if overdue else ""
                tc1.markdown(f"{prefix}{pri} {t['task_text']}{due}")
                if tc2.button("✅", key=f"tk_done_{t['id']}", help="Mark complete"):
                    execute("UPDATE work_tasks SET is_done=TRUE, completed_at=NOW() WHERE id=%s",
                            (t["id"],), commit=True)
                    st.rerun()
                if tc3.button("🗑️", key=f"tk_del_{t['id']}", help="Delete task"):
                    execute("DELETE FROM work_tasks WHERE id=%s", (t["id"],), commit=True)
                    st.rerun()

        if done:
            with st.expander(f"✅ Done ({len(done)})"):
                for t in done:
                    done_dt = t["completed_at"].date() if t["completed_at"] else "?"
                    st.markdown(f"~~{t['task_text']}~~ · completed {done_dt}")

        # Standard checklist quick-add
        st.divider()
        st.caption("**Standard wholesaling checklist — click to add:**")
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
        cols_std = st.columns(2)
        for i, (txt, pri) in enumerate(STANDARD):
            if txt not in existing_text:
                if cols_std[i % 2].button(f"+ {txt}", key=f"std_{i}", use_container_width=True):
                    execute("INSERT INTO work_tasks (lead_id, task_text, priority) VALUES (%s,%s,%s)",
                            (lead_id, txt, pri), commit=True)
                    st.rerun()

    # ── BUYERS ────────────────────────────────────────────────────────────
    with t_buyers:
        st.subheader("🎯 Matched Cash Buyers")

        matched = execute("""
            SELECT mb.id, mb.match_score, mb.notified, mb.notified_date, mb.response,
                   cb.id AS buyer_id, cb.display_name, cb.entity_type,
                   bc.full_name AS contact_name, bc.phone, bc.email, bc.cell_phone
            FROM matched_buyers mb
            JOIN cash_buyers cb ON cb.id = mb.buyer_id
            LEFT JOIN buyer_contacts bc ON bc.buyer_id = cb.id AND bc.is_primary = TRUE
            WHERE mb.deal_id = %s
            ORDER BY mb.match_score DESC NULLS LAST
        """, (deal_id,))

        if matched:
            st.markdown(f"**{len(matched)} buyer{'s' if len(matched)>1 else ''} saved for this deal**")
            for m in matched:
                mc1, mc2, mc3, mc4 = st.columns([3, 2, 2, 1])
                mc1.markdown(f"**{m['display_name']}** `{m['entity_type'] or ''}`")
                if m["contact_name"]:
                    mc1.caption(m["contact_name"])
                phone_str = m["phone"] or m["cell_phone"] or "—"
                mc2.markdown(f"📞 {phone_str}")
                mc3.markdown(f"✉️ {m['email'] or '—'}")
                notif_lbl = "📨 Re-notify" if m["notified"] else "📨 Mark Notified"
                if mc4.button(notif_lbl, key=f"mb_notif_{m['id']}"):
                    execute("UPDATE matched_buyers SET notified=TRUE, notified_date=NOW() WHERE id=%s",
                            (m["id"],), commit=True)
                    st.rerun()
                if m["notified"]:
                    mc3.caption(f"Notified {m['notified_date'].date() if m['notified_date'] else '?'}")
                if m["response"]:
                    st.caption(f"Response: {m['response']}")
                st.divider()
        else:
            st.info("No buyers matched yet. Use the auto-match below.")

        st.subheader("🔍 Auto-Match from Buyer Database")
        st.caption("Finds buyers whose buy box (price range + ZIP) matches this property.")

        auto = execute("""
            SELECT cb.id, cb.display_name, cb.entity_type, cb.deals_closed,
                   bb.min_price, bb.max_price, bb.zip_codes,
                   bc.full_name AS contact_name, bc.phone, bc.email
            FROM cash_buyers cb
            JOIN buyer_buyboxes bb ON bb.buyer_id = cb.id
            LEFT JOIN buyer_contacts bc ON bc.buyer_id = cb.id AND bc.is_primary = TRUE
            WHERE (bb.min_price IS NULL OR bb.min_price <= %s)
              AND (bb.max_price IS NULL OR bb.max_price >= %s)
              AND (bb.zip_codes IS NULL OR %s = ANY(bb.zip_codes))
              AND cb.id NOT IN (
                  SELECT buyer_id FROM matched_buyers WHERE deal_id = %s
              )
            ORDER BY cb.deals_closed DESC NULLS LAST, bc.phone NULLS LAST
            LIMIT 100
        """, (d["total_mkt_val"] or 999999, d["total_mkt_val"] or 0,
              d["situs_zip"] or "00000", deal_id))

        st.metric("Potential matches", len(auto))

        if auto:
            import pandas as pd
            df_auto = pd.DataFrame([{
                "Buyer":         m["display_name"],
                "Type":          m["entity_type"] or "—",
                "Contact":       m["contact_name"] or "—",
                "Phone":         m["phone"] or "—",
                "Email":         m["email"] or "—",
                "Price Range":   f"{fmt_currency(m['min_price'])} – {fmt_currency(m['max_price'])}",
                "Deals Closed":  m["deals_closed"] or 0,
            } for m in auto])
            st.dataframe(df_auto, use_container_width=True, hide_index=True)

            if st.button(f"⬇️ Save All {len(auto)} as Matched Buyers", type="primary"):
                added = 0
                for m in auto:
                    r = execute("""
                        INSERT INTO matched_buyers (deal_id, buyer_id, notified, match_score)
                        VALUES (%s,%s,FALSE,75)
                        ON CONFLICT DO NOTHING RETURNING id
                    """, (deal_id, m["id"]), commit=True)
                    if r: added += 1
                st.success(f"Added {added} buyers to this deal!")
                st.rerun()
        else:
            st.info("No additional buyers found matching this property's value/ZIP criteria.")
