import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.theme import inject_theme, page_header
from app.utils.db import execute
from app.utils.formatting import fmt_currency

st.set_page_config(page_title="Pipeline", page_icon="📋", layout="wide")
inject_theme()
page_header("Deal Pipeline", "Kanban view of every deal by stage.", icon="📋")
STAGES = [
    ("new_lead",       "🆕 New Lead"),
    ("contacted",      "📞 Contacted"),
    ("analyzing",      "🔍 Analyzing"),
    ("negotiating",    "🤝 Negotiating"),
    ("under_contract", "📝 Under Contract"),
    ("assigned",       "💰 Assigned"),
]
STAGE_KEYS   = [s[0] for s in STAGES]
STAGE_LABELS = {s[0]: s[1] for s in STAGES}

# ── Load all active deals ─────────────────────────────────────────────────────
deals = execute("""
    SELECT
        ad.id, ad.status, ad.purchase_price, ad.assignment_fee_target,
        ad.option_expiry, ad.contract_date, ad.seller_name, ad.notes,
        ad.created_at,
        p.full_address, p.situs_zip,
        l.motivated_score,
        l.id AS lead_id
    FROM active_deals ad
    JOIN leads   l ON l.id = ad.lead_id
    JOIN parcels p ON p.parcel_id = l.parcel_id
    ORDER BY ad.created_at DESC
""")

by_stage: dict = {k: [] for k in STAGE_KEYS}
for d in deals:
    key = d["status"] if d["status"] in by_stage else "new_lead"
    by_stage[key].append(d)

total = len(deals)

# ── Top bar ───────────────────────────────────────────────────────────────────
cols_top = st.columns(len(STAGES))
for i, (key, label) in enumerate(STAGES):
    cols_top[i].metric(label, len(by_stage[key]))

st.divider()

if total == 0:
    st.info("No deals in pipeline yet. Go to the **Leads** page and click ➕ Add to Pipeline.")
    st.stop()

# ── Kanban columns ────────────────────────────────────────────────────────────
kanban_cols = st.columns(len(STAGES))

for col_widget, (stage_key, stage_label) in zip(kanban_cols, STAGES):
    with col_widget:
        st.markdown(f"### {stage_label}")
        stage_deals = by_stage[stage_key]
        if not stage_deals:
            st.caption("— empty —")
        for deal in stage_deals:
            addr = deal["full_address"] or f"Parcel {deal['lead_id']}"
            price_str = fmt_currency(deal["purchase_price"]) if deal["purchase_price"] else "—"
            fee_str   = fmt_currency(deal["assignment_fee_target"]) if deal["assignment_fee_target"] else "—"
            with st.container(border=True):
                st.markdown(f"**{addr[:40]}**")
                st.caption(f"ZIP {deal['situs_zip']} · Score {deal['motivated_score']}")
                if deal["purchase_price"]:
                    st.caption(f"Buy {price_str} → Fee {fee_str}")
                if deal["option_expiry"]:
                    st.caption(f"Option expires: {deal['option_expiry']}")
                if deal["seller_name"]:
                    st.caption(f"Seller: {deal['seller_name']}")

                # Move forward button
                cur_idx = STAGE_KEYS.index(stage_key)
                if cur_idx < len(STAGE_KEYS) - 1:
                    next_key   = STAGE_KEYS[cur_idx + 1]
                    next_label = STAGE_LABELS[next_key]
                    if st.button(f"→ {next_label}", key=f"adv_{deal['id']}"):
                        execute(
                            "UPDATE active_deals SET status=%s WHERE id=%s",
                            (next_key, deal["id"]), commit=True,
                        )
                        st.rerun()

                # Kill deal button
                if st.button("✖ Dead Deal", key=f"dead_{deal['id']}"):
                    execute(
                        "UPDATE active_deals SET status='dead' WHERE id=%s",
                        (deal["id"],), commit=True,
                    )
                    st.rerun()

# ── Dead deals (collapsed) ────────────────────────────────────────────────────
dead = execute("""
    SELECT ad.id, p.full_address, ad.notes
    FROM active_deals ad
    JOIN leads   l ON l.id = ad.lead_id
    JOIN parcels p ON p.parcel_id = l.parcel_id
    WHERE ad.status = 'dead'
    ORDER BY ad.created_at DESC
""")
if dead:
    with st.expander(f"💀 Dead Deals ({len(dead)})"):
        for d in dead:
            rc, rn = st.columns([3, 1])
            rc.write(d["full_address"])
            if rn.button("Revive", key=f"rev_{d['id']}"):
                execute("UPDATE active_deals SET status='new_lead' WHERE id=%s", (d["id"],), commit=True)
                st.rerun()
