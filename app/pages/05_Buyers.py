import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency

st.set_page_config(page_title="Cash Buyers", page_icon="💰", layout="wide")
st.title("💰 Cash Buyer Database")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_list, tab_add, tab_mine, tab_csv, tab_clerk, tab_match = st.tabs([
    "📋 Buyer List", "➕ Add Buyer",
    "🏗️ Mine from HCAD", "📥 CSV Import", "🏛️ County Clerk Deeds",
    "🎯 Match Leads",
])

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

# ── MINE FROM HCAD ────────────────────────────────────────────────────────────
HOMEBUILDER_KEYWORDS = [
    "DR HORTON","M/I HOMES","M I HOMES","TOLL ","LENNAR","KB HOME","PULTE","MERITAGE",
    "BEAZER","CENTEX","PERRY HOME","DAVID WEEKLEY","HIGHLAND HOME",
    "COVENTRY HOME","NEWMARK HOME","TRENDMAKER","GEHAN HOME",
]

with tab_mine:
    st.subheader("🏗️ Mine Cash Buyers from HCAD Data")
    st.caption(
        "These are LLCs, trusts, and corporations that own multiple Harris County "
        "properties — highly likely to be active cash investors."
    )

    mc1, mc2, mc3 = st.columns(3)
    mine_min_props  = mc1.slider("Min properties owned", 3, 50, 5)
    mine_max_props  = mc2.slider("Max properties (exclude large builders)", 5, 500, 100)
    mine_excl_build = mc3.checkbox("Exclude known homebuilders", value=True)
    mine_types      = st.multiselect("Owner types", ["llc","trust","corporation","estate"],
                                     default=["llc","trust","corporation"])

    if st.button("🔍 Find Buyer Candidates", type="primary"):
        candidates = execute("""
            SELECT
                o.owner_name,
                o.owner_type,
                o.mail_addr_1,
                o.mail_city,
                o.mail_state,
                o.mail_zip,
                COUNT(o.parcel_id) AS prop_count,
                array_agg(DISTINCT p.situs_zip) FILTER (WHERE p.situs_zip IS NOT NULL) AS zips,
                MIN(p.total_appr_val) AS min_val,
                MAX(p.total_appr_val) AS max_val
            FROM owners o
            JOIN parcels p ON p.parcel_id = o.parcel_id
            WHERE o.owner_type = ANY(%(types)s)
            GROUP BY o.owner_name, o.owner_type, o.mail_addr_1, o.mail_city, o.mail_state, o.mail_zip
            HAVING COUNT(o.parcel_id) BETWEEN %(mn)s AND %(mx)s
            ORDER BY prop_count DESC
            LIMIT 500
        """, {"types": mine_types, "mn": mine_min_props, "mx": mine_max_props})

        if mine_excl_build:
            candidates = [
                c for c in candidates
                if not any(kw in (c["owner_name"] or "").upper() for kw in HOMEBUILDER_KEYWORDS)
            ]

        # Filter out already-imported names
        existing = {r["display_name"].upper() for r in execute("SELECT display_name FROM cash_buyers")}
        new_cands = [c for c in candidates if (c["owner_name"] or "").upper() not in existing]

        st.session_state["mine_candidates"] = new_cands
        st.session_state["mine_all_cands"]  = candidates
        st.rerun()

    if "mine_candidates" in st.session_state:
        cands     = st.session_state["mine_candidates"]
        all_cands = st.session_state["mine_all_cands"]
        st.markdown(
            f"**{len(all_cands):,} candidates found** · "
            f"**{len(cands):,} not yet imported**"
        )

        if cands:
            import pandas as pd
            df = pd.DataFrame([{
                "Name":        c["owner_name"],
                "Type":        c["owner_type"],
                "Props":       c["prop_count"],
                "ZIPs":        ", ".join((c["zips"] or [])[:5]),
                "Value Range": f"{fmt_currency(c['min_val'])} – {fmt_currency(c['max_val'])}",
                "Mail City":   f"{c['mail_city'] or '—'}, {c['mail_state'] or ''}",
            } for c in cands])
            st.dataframe(df, use_container_width=True, hide_index=True)

            if st.button(f"⬇️ Import All {len(cands):,} as Cash Buyers", type="primary"):
                import uuid
                added = 0
                for c in cands:
                    r = execute("""
                        INSERT INTO cash_buyers
                            (buyer_key, display_name, entity_name, entity_type,
                             mailing_address, mailing_city, mailing_state, mailing_zip,
                             is_verified, notes, last_updated)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s,NOW())
                        ON CONFLICT DO NOTHING RETURNING id
                    """, (
                        str(uuid.uuid4())[:8],
                        c["owner_name"], c["owner_name"], c["owner_type"],
                        c["mail_addr_1"], c["mail_city"], c["mail_state"], c["mail_zip"],
                        f"HCAD-mined: {c['prop_count']} properties in Harris County",
                    ), commit=True)
                    if r:
                        zips = c["zips"] if c["zips"] else None
                        execute("""
                            INSERT INTO buyer_buyboxes (buyer_id, min_price, max_price, zip_codes, last_updated)
                            VALUES (%s,%s,%s,%s::text[],NOW())
                        """, (r[0]["id"], c["min_val"] or 0, c["max_val"] or 999999, zips), commit=True)
                        added += 1
                st.success(f"Imported {added:,} buyers!")
                del st.session_state["mine_candidates"]
                del st.session_state["mine_all_cands"]
                st.rerun()

# ── CSV IMPORT ────────────────────────────────────────────────────────────────
with tab_csv:
    st.subheader("📥 Import Buyers from CSV")
    st.caption("Accepts exports from PropStream, BatchLeads, ListSource, REIPro, or any custom CSV.")

    uploaded = st.file_uploader("Upload buyer list CSV", type=["csv"])
    if uploaded:
        import csv as _csv, io, pandas as pd

        content = uploaded.read().decode("utf-8-sig", errors="replace")
        reader  = _csv.DictReader(io.StringIO(content))
        raw     = list(reader)
        if not raw:
            st.error("CSV is empty.")
        else:
            st.caption(f"{len(raw):,} rows · columns: {', '.join(raw[0].keys())}")

            col_names = list(raw[0].keys())
            def best_match(candidates, cols):
                for c in candidates:
                    for col in cols:
                        if c.lower() in col.lower():
                            return col
                return None

            st.markdown("**Map your columns** (auto-detected where possible):")
            f1, f2 = st.columns(2)
            opt = ["(skip)"] + col_names
            map_name    = f1.selectbox("Full Name / Company *", opt,
                index=opt.index(best_match(["name","company","entity","owner"], col_names) or "(skip)"))
            map_phone   = f1.selectbox("Phone", opt,
                index=opt.index(best_match(["phone","cell","mobile"], col_names) or "(skip)"))
            map_email   = f1.selectbox("Email", opt,
                index=opt.index(best_match(["email","mail"], col_names) or "(skip)"))
            map_city    = f2.selectbox("City", opt,
                index=opt.index(best_match(["city"], col_names) or "(skip)"))
            map_state   = f2.selectbox("State", opt,
                index=opt.index(best_match(["state"], col_names) or "(skip)"))
            map_zip     = f2.selectbox("ZIP", opt,
                index=opt.index(best_match(["zip","postal"], col_names) or "(skip)"))
            map_min     = f1.selectbox("Min Price", opt,
                index=opt.index(best_match(["min","low","floor"], col_names) or "(skip)"))
            map_max     = f2.selectbox("Max Price", opt,
                index=opt.index(best_match(["max","high","ceil","top"], col_names) or "(skip)"))

            def gv(row, col):
                return row.get(col, "").strip() if col != "(skip)" else ""

            def to_int(v):
                try: return int("".join(c for c in v if c.isdigit() or c == ".").split(".")[0])
                except: return None

            if map_name == "(skip)":
                st.warning("Name/Company column is required.")
            else:
                preview = pd.DataFrame([{
                    "Name":  gv(r, map_name),
                    "Phone": gv(r, map_phone),
                    "Email": gv(r, map_email),
                    "City":  gv(r, map_city),
                    "ZIP":   gv(r, map_zip),
                    "Min $": gv(r, map_min),
                    "Max $": gv(r, map_max),
                } for r in raw[:10]])
                st.markdown("**Preview (first 10 rows):**")
                st.dataframe(preview, use_container_width=True, hide_index=True)

                if st.button(f"⬇️ Import {len(raw):,} Buyers", type="primary"):
                    import uuid
                    added = skipped = 0
                    existing = {r["display_name"].upper()
                                for r in execute("SELECT display_name FROM cash_buyers")}
                    for row in raw:
                        name = gv(row, map_name)
                        if not name or name.upper() in existing:
                            skipped += 1
                            continue
                        r = execute("""
                            INSERT INTO cash_buyers
                                (buyer_key, display_name, entity_name, entity_type,
                                 phone, email, mailing_city, mailing_state, mailing_zip,
                                 is_verified, notes, last_updated)
                            VALUES (%s,%s,%s,'individual',%s,%s,%s,%s,%s,FALSE,'CSV import',NOW())
                            ON CONFLICT DO NOTHING RETURNING id
                        """, (
                            str(uuid.uuid4())[:8],
                            name, name,
                            gv(row, map_phone) or None,
                            gv(row, map_email) or None,
                            gv(row, map_city)  or None,
                            gv(row, map_state) or None,
                            gv(row, map_zip)   or None,
                        ), commit=True)
                        if r:
                            min_p = to_int(gv(row, map_min))
                            max_p = to_int(gv(row, map_max))
                            zip_v = gv(row, map_zip)
                            execute("""
                                INSERT INTO buyer_buyboxes
                                    (buyer_id, min_price, max_price, zip_codes, last_updated)
                                VALUES (%s,%s,%s,%s::text[],NOW())
                            """, (r[0]["id"], min_p, max_p,
                                  [zip_v] if zip_v else None), commit=True)
                            added += 1
                        else:
                            skipped += 1
                    st.success(f"Imported {added:,} buyers · skipped {skipped:,} duplicates")
                    st.rerun()

# ── HARRIS COUNTY CLERK DEEDS ─────────────────────────────────────────────────
with tab_clerk:
    st.subheader("🏛️ Harris County Clerk — Cash Deed Buyers")
    st.markdown("""
Harris County Clerk publishes all recorded deeds at **[hcdistrictclerk.com](https://www.hcdistrictclerk.com)**.
Cash buyers show up as **Warranty Deed** or **Special Warranty Deed** transactions with *no corresponding Deed of Trust*
(which is the mortgage) recorded within 30 days.

#### How to get the data (free):

**Option A — HCAD bulk download** *(easiest)*
1. Go to [download.hcad.org](https://download.hcad.org/data/CAMA/2026/)
2. Download `real_acct.txt` — this contains `last_sale_dt`, `last_sale_price`, and grantee info for every property
3. Drop the file here to parse and identify recent buyers:
""")

    deed_file = st.file_uploader("Upload real_acct.txt from HCAD", type=["txt","csv"], key="deed_upload")
    if deed_file:
        import csv as _csv, io, pandas as pd

        st.info("Parsing real_acct.txt for recent sales (2023–2026)…")
        content = deed_file.read().decode("cp1252", errors="replace")
        reader  = _csv.DictReader(io.StringIO(content), delimiter="\t")
        raw     = list(reader)
        headers = [h.strip().lower() for h in raw[0].keys()] if raw else []
        st.caption(f"Columns detected: {', '.join(headers[:20])}")

        # Look for sale-related columns
        sale_cols = [h for h in headers if any(k in h for k in ["sale","grant","deed","transfer"])]
        st.caption(f"Sale-related columns: {', '.join(sale_cols) or 'none detected'}")

        if sale_cols:
            st.markdown("**Column mapping for deed buyer extraction:**")
            col_opts = ["(skip)"] + headers
            s1, s2, s3 = st.columns(3)
            map_grantee  = s1.selectbox("Buyer (Grantee) Name",  col_opts)
            map_sale_dt  = s2.selectbox("Sale Date",             col_opts)
            map_sale_pr  = s3.selectbox("Sale Price",            col_opts)

            if map_grantee != "(skip)" and st.button("🔍 Extract Cash Buyer Candidates from Deeds"):
                from collections import defaultdict
                buyers_found = defaultdict(lambda: {"count": 0, "total": 0, "dates": []})
                for row in raw:
                    name  = (row.get(map_grantee) or "").strip()
                    price = row.get(map_sale_pr, "")
                    date  = row.get(map_sale_dt, "")
                    if not name or len(name) < 3: continue
                    try: amt = int("".join(c for c in price if c.isdigit()))
                    except: amt = 0
                    if amt < 10_000: continue
                    buyers_found[name]["count"]  += 1
                    buyers_found[name]["total"]  += amt
                    buyers_found[name]["dates"].append(date)

                # Rank by purchase frequency
                ranked = sorted(
                    [(k, v) for k, v in buyers_found.items() if v["count"] >= 2],
                    key=lambda x: x[1]["count"], reverse=True
                )[:500]

                if ranked:
                    df = pd.DataFrame([{
                        "Buyer Name":     name,
                        "Purchases":      v["count"],
                        "Total Spent":    fmt_currency(v["total"]),
                        "Avg Price":      fmt_currency(v["total"] // v["count"]),
                    } for name, v in ranked])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    st.session_state["deed_buyers"] = ranked
                else:
                    st.warning("No repeat buyers found. Check column mapping.")

        if "deed_buyers" in st.session_state and st.button("⬇️ Import Deed Buyers to Database"):
            import uuid
            existing = {r["display_name"].upper() for r in execute("SELECT display_name FROM cash_buyers")}
            added = 0
            for name, v in st.session_state["deed_buyers"]:
                if name.upper() in existing: continue
                r = execute("""
                    INSERT INTO cash_buyers
                        (buyer_key, display_name, entity_name, entity_type,
                         is_verified, notes, last_updated)
                    VALUES (%s,%s,%s,'individual',FALSE,%s,NOW())
                    ON CONFLICT DO NOTHING RETURNING id
                """, (
                    str(uuid.uuid4())[:8], name, name,
                    f"County Clerk deed records: {v['count']} purchases, {fmt_currency(v['total'])} total",
                ), commit=True)
                if r: added += 1
            st.success(f"Imported {added:,} deed buyers!")
            del st.session_state["deed_buyers"]
            st.rerun()

    st.markdown("""
---
**Option B — Direct County Clerk search**
1. Visit [hcdistrictclerk.com/Applications/WebSearch/RP.aspx](https://www.hcdistrictclerk.com/Applications/WebSearch/RP.aspx)
2. Search by date range for "Warranty Deed" instrument type
3. Export results to CSV and use the **📥 CSV Import** tab above

**Option C — PropStream / BatchLeads** *(fastest)*
- Filter: Harris County · Sold in last 12 months · Cash transaction · Entity type = LLC/Trust
- Export CSV → use **📥 CSV Import** tab above
""")

# ─────────────────────────────────────────────────────────────────────────────

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
