import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency

st.set_page_config(page_title="Cash Buyers", page_icon="💰", layout="wide")
st.title("💰 Cash Buyer Database")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_list, tab_add, tab_match = st.tabs(["📋 Buyer List", "➕ Add Buyer", "🎯 Match Leads"])

# ─────────────────────────────────────────────────────────────────────────────
with tab_list:
    buyers = execute("""
        SELECT DISTINCT ON (b.id)
            b.id, b.display_name, b.entity_name, b.entity_type,
            b.phone, b.email, b.is_verified, b.deals_closed,
            b.reliability_pct, b.notes,
            b.mailing_city, b.mailing_state,
            bb.min_price, bb.max_price, bb.max_repairs, bb.zip_codes
        FROM cash_buyers b
        LEFT JOIN buyer_buyboxes bb ON bb.buyer_id = b.id
        ORDER BY b.id, bb.id
    """)

    if not buyers:
        st.info("No buyers yet. Use **Add Buyer** to add your first cash buyer.")
    else:
        st.caption(f"{len(buyers)} buyers in database")
        for b in buyers:
            verified = "✅ " if b["is_verified"] else ""
            label = f"{verified}**{b['display_name']}**"
            if b["entity_name"]: label += f"  ·  {b['entity_name']}"
            with st.expander(label):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Phone:** {b['phone'] or '—'}")
                c1.markdown(f"**Email:** {b['email'] or '—'}")
                c1.markdown(f"**Deals closed:** {b['deals_closed'] or 0}")
                c1.markdown(f"**Reliability:** {b['reliability_pct'] or '—'}%")
                c2.markdown(f"**Entity:** {b['entity_name'] or '—'} ({b['entity_type'] or '—'})")
                c2.markdown(f"**City:** {b['mailing_city'] or '—'}, {b['mailing_state'] or ''}")
                price_range = ""
                if b["min_price"] or b["max_price"]:
                    price_range = f"{fmt_currency(b['min_price'])} – {fmt_currency(b['max_price'])}"
                c3.markdown(f"**Price range:** {price_range or '—'}")
                if b["notes"]:
                    st.caption(f"Notes: {b['notes']}")

                if st.button("🗑️ Remove", key=f"del_{b['id']}"):
                    execute("DELETE FROM cash_buyers WHERE id = %s", (b["id"],), commit=True)
                    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
with tab_add:
    st.subheader("Add Cash Buyer")
    with st.form("add_buyer"):
        a1, a2 = st.columns(2)
        display_name  = a1.text_input("Display Name *", placeholder="John Smith")
        entity_name   = a2.text_input("Entity / Company", placeholder="Smith Investments LLC")
        phone         = a1.text_input("Phone", placeholder="713-555-0100")
        email         = a2.text_input("Email", placeholder="john@example.com")
        entity_type   = a1.selectbox("Entity Type", ["individual", "llc", "trust", "corporation", "other"])
        is_verified   = a2.checkbox("Verified (POF confirmed)")
        notes         = st.text_area("Notes", placeholder="Focuses on 3/2 SFR, quick closes")

        st.markdown("**Buy Box**")
        b1, b2, b3 = st.columns(3)
        min_price   = b1.number_input("Min Price ($)", min_value=0, value=50_000, step=5_000)
        max_price   = b2.number_input("Max Price ($)", min_value=0, value=300_000, step=5_000)
        max_repairs = b3.number_input("Max Repairs ($)", min_value=0, value=50_000, step=5_000)

        zip_input = st.text_input("Target ZIPs (comma-separated)", placeholder="77051, 77033, 77004")

        submitted = st.form_submit_button("Add Buyer", type="primary")

    if submitted:
        if not display_name.strip():
            st.error("Display name is required.")
        else:
            import uuid
            buyer_key = str(uuid.uuid4())[:8]
            result = execute("""
                INSERT INTO cash_buyers
                    (buyer_key, display_name, entity_name, entity_type,
                     phone, email, is_verified, notes, last_updated)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                RETURNING id
            """, (buyer_key, display_name.strip(), entity_name.strip() or None,
                  entity_type, phone.strip() or None, email.strip() or None,
                  is_verified, notes.strip() or None), commit=True)

            if result:
                buyer_id = result[0]["id"]
                zips = [z.strip() for z in zip_input.split(",") if z.strip()]
                import psycopg2.extras
                execute("""
                    INSERT INTO buyer_buyboxes
                        (buyer_id, min_price, max_price, max_repairs, zip_codes, last_updated)
                    VALUES (%s,%s,%s,%s,%s::text[],NOW())
                """, (buyer_id, min_price, max_price, max_repairs,
                      zips if zips else None), commit=True)
                st.success(f"Added {display_name}!")
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
with tab_match:
    st.subheader("Match Leads to Buyers")
    buyers_for_match = execute("SELECT id, display_name FROM cash_buyers ORDER BY display_name")

    if not buyers_for_match:
        st.info("Add buyers first.")
    else:
        sel_buyer = st.selectbox("Select Buyer",
                                 options=[b["id"] for b in buyers_for_match],
                                 format_func=lambda i: next(b["display_name"] for b in buyers_for_match if b["id"] == i))

        buybox = execute("""
            SELECT min_price, max_price, max_repairs, zip_codes
            FROM buyer_buyboxes WHERE buyer_id = %s LIMIT 1
        """, (sel_buyer,))

        if not buybox:
            st.warning("This buyer has no buy box configured. Edit them in the Buyer List tab.")
        else:
            bb = buybox[0]
            st.caption(f"Buy box: {fmt_currency(bb['min_price'])} – {fmt_currency(bb['max_price'])} "
                       f"· max repairs {fmt_currency(bb['max_repairs'])} "
                       f"· ZIPs: {', '.join(bb['zip_codes'] or []) or 'any'}")

            zip_filter = ""
            if bb["zip_codes"]:
                zip_filter = "AND p.situs_zip = ANY(%(zips)s)"

            matches = execute(f"""
                SELECT p.full_address, p.situs_zip, p.total_mkt_val,
                       b.condition, b.living_area, b.year_built,
                       l.motivated_score, l.id AS lead_id
                FROM leads l
                JOIN parcels p  ON p.parcel_id = l.parcel_id
                LEFT JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
                WHERE l.source = 'hcad_auto'
                  AND p.total_mkt_val BETWEEN %(min_p)s AND %(max_p)s
                  {zip_filter}
                ORDER BY l.motivated_score DESC
                LIMIT 100
            """, {"min_p": bb["min_price"] or 0, "max_p": bb["max_price"] or 9_999_999,
                  "zips": bb["zip_codes"]})

            st.markdown(f"**{len(matches)} matching leads**")
            if matches:
                import pandas as pd
                df = pd.DataFrame([{
                    "Address":   m["full_address"],
                    "ZIP":       m["situs_zip"],
                    "HCAD Value": fmt_currency(m["total_mkt_val"]),
                    "Condition": m["condition"] or "—",
                    "Sqft":      f"{int(m['living_area']):,}" if m["living_area"] else "—",
                    "Score":     m["motivated_score"],
                } for m in matches])
                st.dataframe(df, use_container_width=True, hide_index=True)
