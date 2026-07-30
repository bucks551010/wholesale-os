import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import date, timedelta
import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency
from app.utils.contracts import generate_purchase_contract, generate_assignment_contract

st.set_page_config(page_title="Contracts", page_icon="📝", layout="wide")
st.title("📝 Contract Generator")
st.caption("⚠️ Templates only — have a licensed Texas real estate attorney review before use.")

tab_purchase, tab_assign = st.tabs(["📋 Purchase Agreement", "🔀 Assignment Agreement"])

# ── Shared: load active deals ─────────────────────────────────────────────────
deals = execute("""
    SELECT ad.id, ad.status, ad.purchase_price, ad.option_period_days,
           ad.closing_date, ad.earnest_money_amount, ad.title_company,
           ad.title_company_contact, ad.seller_name, ad.seller_phone,
           ad.seller_email, ad.assignment_fee_target, ad.notes,
           p.parcel_id, p.full_address, p.situs_zip, p.situs_city,
           p.total_mkt_val,
           o.owner_name, o.mail_addr_1, o.mail_city, o.mail_state, o.mail_zip
    FROM active_deals ad
    JOIN leads   l ON l.id = ad.lead_id
    JOIN parcels p ON p.parcel_id = l.parcel_id
    LEFT JOIN owners o ON o.parcel_id = p.parcel_id
    WHERE ad.status NOT IN ('dead','closed')
    ORDER BY ad.created_at DESC
""")

if not deals:
    st.info("No active deals in pipeline. Go to the Pipeline page and add a deal first.")
    st.stop()

deal_labels = {d["id"]: f"{d['full_address']} — {fmt_currency(d['purchase_price']) if d['purchase_price'] else 'No price set'}" for d in deals}

# ─────────────────────────────────────────────────────────────────────────────
with tab_purchase:
    sel_id = st.selectbox("Select Deal", options=list(deal_labels.keys()),
                          format_func=lambda i: deal_labels[i], key="pur_deal")
    deal = next(d for d in deals if d["id"] == sel_id)

    st.subheader(deal["full_address"] or deal["parcel_id"])
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Seller Info**")
        seller_name  = st.text_input("Seller Name",  value=deal["seller_name"] or deal["owner_name"] or "", key="pur_seller")
        seller_phone = st.text_input("Seller Phone", value=deal["seller_phone"] or "", key="pur_phone")

    with c2:
        st.markdown("**Deal Terms**")
        purchase_price = st.number_input("Purchase Price ($)", min_value=0,
                                         value=int(deal["purchase_price"] or 0), step=1000, key="pur_price")
        earnest_money  = st.number_input("Earnest Money ($)", min_value=0,
                                         value=int(deal["earnest_money_amount"] or 500), step=100, key="pur_em")
        option_days    = st.number_input("Option Period (days)", min_value=1,
                                         value=int(deal["option_period_days"] or 10), key="pur_opt")
        closing_date   = st.date_input("Closing Date",
                                       value=deal["closing_date"] or date.today() + timedelta(days=30),
                                       key="pur_close")
        title_company  = st.text_input("Title Company", value=deal["title_company"] or "", key="pur_title")
        notes          = st.text_area("Special Provisions", value=deal["notes"] or "", height=80, key="pur_notes")

    with st.expander("Buyer / Your Info"):
        buyer_name   = st.text_input("Buyer Name",   value=st.session_state.get("buyer_name", ""), key="pur_bname")
        buyer_entity = st.text_input("Buyer Entity", placeholder="ABC Investments LLC", key="pur_bentity")

    if st.button("📄 Generate Purchase Agreement", type="primary", key="gen_pur"):
        deal_data = {**deal, "purchase_price": purchase_price, "earnest_money_amount": earnest_money,
                     "option_period_days": option_days, "closing_date": closing_date,
                     "title_company": title_company, "seller_name": seller_name, "notes": notes}
        parcel_data = {"parcel_id": deal["parcel_id"], "full_address": deal["full_address"]}
        owner_data  = {"owner_name": seller_name}

        docx_bytes = generate_purchase_contract(
            deal=deal_data, parcel=parcel_data, owner=owner_data,
            buyer_name=buyer_name or "[BUYER NAME]",
            buyer_entity=buyer_entity or "[BUYER ENTITY]",
        )
        # Save updated deal info
        execute("""UPDATE active_deals SET purchase_price=%s, earnest_money_amount=%s,
                   option_period_days=%s, closing_date=%s, title_company=%s,
                   seller_name=%s, notes=%s WHERE id=%s""",
                (purchase_price, earnest_money, option_days, closing_date,
                 title_company or None, seller_name or None, notes or None, sel_id), commit=True)
        execute("""INSERT INTO contracts (deal_id, contract_type, template_version,
                   generated_date, status) VALUES (%s,'purchase','v1',NOW(),'generated')""",
                (sel_id,), commit=True)

        fname = f"purchase_agreement_{deal['parcel_id']}.docx"
        st.download_button("⬇️ Download Purchase Agreement (.docx)",
                           data=docx_bytes, file_name=fname,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        st.success("Generated & saved to contracts log.")

# ─────────────────────────────────────────────────────────────────────────────
with tab_assign:
    sel_id2 = st.selectbox("Select Deal", options=list(deal_labels.keys()),
                           format_func=lambda i: deal_labels[i], key="asgn_deal")
    deal2 = next(d for d in deals if d["id"] == sel_id2)

    st.subheader(deal2["full_address"] or deal2["parcel_id"])
    a1, a2 = st.columns(2)

    with a1:
        assignor = st.text_input("Assignor (you / your entity)",
                                 value=st.session_state.get("buyer_name", ""), key="asgn_or")
        assignee = st.text_input("Assignee (cash buyer)", placeholder="John Smith / JNS Holdings LLC", key="asgn_ee")

    with a2:
        asgn_price = st.number_input("Original Purchase Price ($)",
                                     value=int(deal2["purchase_price"] or 0), step=1000, key="asgn_price")
        asgn_fee   = st.number_input("Assignment Fee ($)",
                                     value=int(deal2["assignment_fee_target"] or 10000), step=500, key="asgn_fee")
        asgn_close = st.date_input("Closing Date",
                                   value=deal2["closing_date"] or date.today() + timedelta(days=14),
                                   key="asgn_close")

    if st.button("📄 Generate Assignment Agreement", type="primary", key="gen_asgn"):
        deal2_data  = {**deal2, "purchase_price": asgn_price, "closing_date": asgn_close}
        parcel2     = {"parcel_id": deal2["parcel_id"], "full_address": deal2["full_address"]}

        docx_bytes2 = generate_assignment_contract(
            deal=deal2_data, parcel=parcel2,
            assignor=assignor or "[ASSIGNOR]",
            assignee=assignee or "[ASSIGNEE]",
            assignment_fee=asgn_fee,
        )
        execute("""UPDATE active_deals SET assignment_fee_target=%s WHERE id=%s""",
                (asgn_fee, sel_id2), commit=True)
        execute("""INSERT INTO contracts (deal_id, contract_type, template_version,
                   generated_date, status) VALUES (%s,'assignment','v1',NOW(),'generated')""",
                (sel_id2,), commit=True)

        fname2 = f"assignment_agreement_{deal2['parcel_id']}.docx"
        st.download_button("⬇️ Download Assignment Agreement (.docx)",
                           data=docx_bytes2, file_name=fname2,
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        st.success("Generated & saved to contracts log.")
