import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from app.utils.db import execute
from app.utils.formatting import fmt_currency

st.set_page_config(page_title="Cash Buyers", page_icon="💰", layout="wide")
st.title("💰 Cash Buyer Database")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_list, tab_add, tab_mine, tab_csv, tab_clerk, tab_match, tab_skip = st.tabs([
    "📋 Buyer List", "➕ Add Buyer",
    "🏗️ Mine from HCAD", "📥 CSV Import", "🏛️ County Clerk Deeds",
    "🎯 Match Leads", "📤 Skip Trace",
])

# ─────────────────────────────────────────────────────────────────────────────
with tab_list:
    import urllib.parse

    b_search = st.text_input("🔍 Search buyers", placeholder="Name, ZIP, city…", label_visibility="collapsed")

    buyers = execute("""
        SELECT DISTINCT ON (b.id)
            b.id, b.display_name, b.entity_name, b.entity_type,
            b.phone, b.email, b.is_verified, b.deals_closed,
            b.reliability_pct, b.notes,
            b.mailing_address, b.mailing_city, b.mailing_state, b.mailing_zip,
            bb.min_price, bb.max_price, bb.max_repairs, bb.zip_codes
        FROM cash_buyers b
        LEFT JOIN buyer_buyboxes bb ON bb.buyer_id = b.id
        ORDER BY b.id, bb.id
    """)

    if b_search:
        q = b_search.lower()
        buyers = [b for b in buyers if q in (b["display_name"] or "").lower()
                  or q in (b["mailing_city"] or "").lower()
                  or q in " ".join(b["zip_codes"] or [])]

    if not buyers:
        st.info("No buyers yet — use **🏗️ Mine from HCAD** or **➕ Add Buyer**.")
    else:
        st.caption(f"{len(buyers):,} buyers")
        for b in buyers:
            contacts = execute(
                "SELECT * FROM buyer_contacts WHERE buyer_id=%s ORDER BY is_primary DESC, id",
                (b["id"],)
            )
            primary = next((c for c in contacts if c["is_primary"]), contacts[0] if contacts else None)

            verified  = "✅ " if b["is_verified"] else ""
            pri_tag   = f" · 📞 {primary['full_name']}" if primary else ""
            price_str = ""
            if b["min_price"] or b["max_price"]:
                price_str = f" · {fmt_currency(b['min_price'])}–{fmt_currency(b['max_price'])}"
            label = f"{verified}**{b['display_name']}**{pri_tag}{price_str}"

            with st.expander(label):
                info_col, contact_col, research_col = st.columns([2, 2, 1])

                with info_col:
                    st.markdown("**Company Info**")
                    st.markdown(f"Type: `{b['entity_type'] or '—'}`")
                    st.markdown(f"Mail: {b['mailing_address'] or ''}, {b['mailing_city'] or '—'}, {b['mailing_state'] or ''} {b['mailing_zip'] or ''}")
                    if b["zip_codes"]:
                        st.markdown(f"Buy ZIPs: {', '.join(b['zip_codes'][:10])}")
                    if b["notes"]:
                        st.caption(b["notes"])

                with contact_col:
                    st.markdown("**Contacts**")
                    if contacts:
                        for c in contacts:
                            star = "⭐ " if c["is_primary"] else ""
                            lines = [f"{star}**{c['full_name']}**"]
                            if c["title"]:    lines.append(c["title"])
                            if c["phone"]:    lines.append(f"📞 {c['phone']}")
                            if c["cell_phone"]: lines.append(f"📱 {c['cell_phone']}")
                            if c["email"]:    lines.append(f"✉️ {c['email']}")
                            if c["linkedin_url"]:
                                lines.append(f"[LinkedIn]({c['linkedin_url']})")
                            st.markdown("  \n".join(lines))
                            if st.button("🗑️", key=f"delc_{c['id']}", help="Remove contact"):
                                execute("DELETE FROM buyer_contacts WHERE id=%s", (c["id"],), commit=True)
                                st.rerun()
                            st.divider()
                    else:
                        st.caption("No contacts yet")

                    # Inline add contact form
                    with st.popover("➕ Add Contact"):
                        cn = st.text_input("Full Name *",    key=f"cn_{b['id']}")
                        ct = st.text_input("Title / Role",   key=f"ct_{b['id']}", placeholder="Owner / Asset Manager")
                        cp = st.text_input("Office Phone",   key=f"cp_{b['id']}")
                        cc = st.text_input("Cell / Mobile",  key=f"cc_{b['id']}")
                        ce = st.text_input("Email",          key=f"ce_{b['id']}")
                        cl = st.text_input("LinkedIn URL",   key=f"cl_{b['id']}")
                        cno= st.text_area("Notes",           key=f"cno_{b['id']}", height=60)
                        cpr= st.checkbox("Primary contact",  key=f"cpr_{b['id']}")
                        if st.button("Save Contact", key=f"csave_{b['id']}", type="primary"):
                            if not cn.strip():
                                st.error("Name required")
                            else:
                                if cpr:
                                    execute("UPDATE buyer_contacts SET is_primary=FALSE WHERE buyer_id=%s",
                                            (b["id"],), commit=True)
                                execute("""
                                    INSERT INTO buyer_contacts
                                        (buyer_id, full_name, title, phone, cell_phone, email,
                                         linkedin_url, notes, is_primary, last_updated)
                                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                                """, (b["id"], cn.strip(), ct.strip() or None, cp.strip() or None,
                                      cc.strip() or None, ce.strip() or None,
                                      cl.strip() or None, cno.strip() or None, cpr), commit=True)
                                st.success("Saved!")
                                st.rerun()

                with research_col:
                    st.markdown("**Research**")
                    name_enc = urllib.parse.quote_plus(b["display_name"])
                    addr_enc = urllib.parse.quote_plus(
                        f"{b['mailing_address'] or ''} {b['mailing_city'] or ''} {b['mailing_state'] or ''}"
                    )
                    st.markdown(f"[🔍 Google](https://www.google.com/search?q={name_enc}+Houston+TX+real+estate+investor)")
                    st.markdown(f"[💼 LinkedIn](https://www.linkedin.com/search/results/companies/?keywords={name_enc})")
                    st.markdown(f"[🏛️ TX SOS](https://mycpa.cpa.state.tx.us/coa/Index.do?action=SEARCH&searchToken={name_enc})")
                    if b["mailing_address"]:
                        st.markdown(f"[🏠 WhitePages](https://www.whitepages.com/address/{addr_enc})")
                    st.markdown(f"[📞 BatchLeads](https://app.batchleads.io/)")

                act1, act2 = st.columns(2)
                if act1.button("🗑️ Remove Buyer", key=f"del_{b['id']}"):
                    execute("DELETE FROM cash_buyers WHERE id=%s", (b["id"],), commit=True)
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

        if not all_cands:
            st.warning("No results. Try lowering the min-properties slider or expanding owner types.")
        elif not cands:
            st.success("✅ All candidates from this search are already in your buyer database!")
            st.caption("Try raising the min-properties slider or changing ZIPs to find new investors.")

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
        sale_cols = [h for h in headers if any(k in h for k in ["sale","grant","deed","transfer","price","amount","value"])]
        st.caption(f"Sale-related columns: {', '.join(sale_cols) or 'none detected'}")

        if not headers:
            st.error("Could not parse columns from this file. Make sure it is tab-separated.")
        elif not sale_cols:
            st.warning("No sale/deed columns detected. Map them manually below.")
            sale_cols = headers  # fall through to mapping UI

        if headers:
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

# ── SKIP TRACE EXPORT / IMPORT ────────────────────────────────────────────────
with tab_skip:
    # ── Auto-enrich via Google Maps (free, no API key) ────────────────────
    st.subheader("🗺️ Auto-Enrich from Google Maps (Free)")
    st.caption("Uses a headless browser to search Google Maps for each company and extract real phone numbers and websites. No API key, no billing.")

    enriched_count = execute("SELECT COUNT(DISTINCT buyer_id) AS n FROM buyer_contacts WHERE notes LIKE 'Google Maps%'")[0]["n"]
    total_buyers   = execute("SELECT COUNT(*) AS n FROM cash_buyers")[0]["n"]
    st.metric("Already enriched", f"{enriched_count:,} / {total_buyers:,} buyers")

    ge1, ge2 = st.columns(2)
    enrich_limit    = ge1.slider("Buyers to process per run", 10, 200, 50)
    enrich_start_id = ge2.number_input("Resume from buyer ID greater than", min_value=0, value=0, step=1)

    if st.button("🚀 Start Auto-Enrich", type="primary"):
        st.info(f"Searching Google Maps for {enrich_limit} buyers — takes ~{enrich_limit*25//60} min. Don't close this tab.")
        progress = st.progress(0)
        status   = st.empty()

        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from scripts.enrich_buyers import run as run_enrich, scrape_google_maps, clean_phone, extract_url, log as enrich_log
        from playwright.sync_api import sync_playwright

        buyers_to_enrich = execute("""
            SELECT b.id, b.display_name
            FROM cash_buyers b
            WHERE b.id > %s
              AND NOT EXISTS (SELECT 1 FROM buyer_contacts bc WHERE bc.buyer_id = b.id)
            ORDER BY b.id
            LIMIT %s
        """, (int(enrich_start_id), enrich_limit))

        if not buyers_to_enrich:
            st.warning("All buyers already have contacts — nothing to enrich!")
        else:
            found_n = 0
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    ctx     = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        viewport={"width": 1280, "height": 800},
                    )
                    page = ctx.new_page()
                    total_n = len(buyers_to_enrich)
                    for i, b in enumerate(buyers_to_enrich):
                        status.text(f"[{i+1}/{total_n}] {b['display_name']}")
                        info       = scrape_google_maps(page, b["display_name"])
                        phone      = clean_phone(info.get("phone", ""))
                        website    = extract_url(info.get("website", ""))
                        found_name = info.get("found_name", "").strip()
                        if phone or website:
                            execute("""
                                INSERT INTO buyer_contacts
                                    (buyer_id, full_name, phone, notes, is_primary, last_updated)
                                VALUES (%s,%s,%s,%s,TRUE,NOW())
                            """, (b["id"], found_name or b["display_name"], phone or None,
                                  f"Google Maps auto-enrich · website: {website}" if website else "Google Maps auto-enrich"
                                  ), commit=True)
                            found_n += 1
                        import time as _t; _t.sleep(2)
                        progress.progress((i + 1) / total_n)
                    ctx.close(); browser.close()
            except Exception as _enrich_err:
                st.error(f"Enrichment error: {_enrich_err}")

            st.success(f"Done — {found_n} of {total_n} buyers enriched with phone/website")
            st.rerun()

    st.divider()
    st.subheader("📤 Export for Skip Tracing")
    st.caption(
        "Export your buyer list as CSV, upload to BatchLeads/BatchSkipTracing/TLO, "
        "then re-import the enriched file with phone numbers and emails."
    )
    import pandas as pd, io

    skip_buyers = execute("""
        SELECT b.id, b.display_name, b.entity_type,
               b.mailing_address, b.mailing_city, b.mailing_state, b.mailing_zip,
               COUNT(bc.id) AS contacts_already
        FROM cash_buyers b
        LEFT JOIN buyer_contacts bc ON bc.buyer_id = b.id
        GROUP BY b.id
        ORDER BY b.display_name
    """)

    only_no_contact = st.checkbox("Only buyers with no contacts yet", value=True)
    if only_no_contact:
        skip_buyers = [r for r in skip_buyers if r["contacts_already"] == 0]

    st.markdown(f"**{len(skip_buyers):,} buyers to export**")

    if skip_buyers and st.button("⬇️ Download Skip-Trace CSV"):
        df = pd.DataFrame([{
            "buyer_id":   r["id"],
            "company":    r["display_name"],
            "type":       r["entity_type"],
            "address":    r["mailing_address"] or "",
            "city":       r["mailing_city"] or "",
            "state":      r["mailing_state"] or "",
            "zip":        r["mailing_zip"] or "",
        } for r in skip_buyers])
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        st.download_button("📥 Save CSV", buf.getvalue(), "buyers_skip_trace.csv", "text/csv")

    st.divider()
    st.subheader("📥 Import Skip-Trace Results")
    st.caption("Upload the enriched CSV returned by your skip-trace service. Must include a `buyer_id` or `company` column plus phone/email columns.")

    st_file = st.file_uploader("Upload enriched CSV", type=["csv"], key="st_import")
    if st_file:
        import csv as _csv
        content = st_file.read().decode("utf-8-sig", errors="replace")
        rows    = list(_csv.DictReader(io.StringIO(content)))
        if rows:
            cols = list(rows[0].keys())
            st.caption(f"{len(rows):,} rows · columns: {', '.join(cols)}")
            op  = ["(skip)"] + cols

            def bm(candidates):
                for c in candidates:
                    for col in cols:
                        if c.lower() in col.lower(): return col
                return "(skip)"

            s1, s2, s3 = st.columns(3)
            map_id    = s1.selectbox("Buyer ID col",   op, index=op.index(bm(["buyer_id","id"])))
            map_name  = s2.selectbox("Company Name",   op, index=op.index(bm(["company","name","entity"])))
            map_fname = s3.selectbox("Contact First Name", op, index=op.index(bm(["first","fname"])))
            s4, s5, s6 = st.columns(3)
            map_lname = s4.selectbox("Contact Last Name",  op, index=op.index(bm(["last","lname"])))
            map_phone = s5.selectbox("Phone",   op, index=op.index(bm(["phone","office"])))
            map_cell  = s6.selectbox("Cell",    op, index=op.index(bm(["cell","mobile","wireless"])))
            map_email = st.selectbox("Email",   op, index=op.index(bm(["email","mail"])))

            def gv(row, col):
                return row.get(col, "").strip() if col != "(skip)" else ""

            # Build buyer_id lookup from name if no ID column
            if map_id == "(skip)" and map_name != "(skip)":
                existing = {r["display_name"].upper(): r["id"]
                            for r in execute("SELECT id, display_name FROM cash_buyers")}

            if st.button("⬇️ Import Contacts", type="primary"):
                added = skipped = 0
                for row in rows:
                    bid = None
                    if map_id != "(skip)":
                        try: bid = int(gv(row, map_id))
                        except: pass
                    elif map_name != "(skip)":
                        bid = existing.get(gv(row, map_name).upper())
                    if not bid:
                        skipped += 1; continue

                    first = gv(row, map_fname)
                    last  = gv(row, map_lname)
                    full  = f"{first} {last}".strip() or gv(row, map_name) or "Unknown"
                    phone = gv(row, map_phone)
                    cell  = gv(row, map_cell)
                    email = gv(row, map_email)
                    if not (phone or cell or email):
                        skipped += 1; continue

                    execute("""
                        INSERT INTO buyer_contacts
                            (buyer_id, full_name, phone, cell_phone, email, notes, is_primary, last_updated)
                        VALUES (%s,%s,%s,%s,%s,'skip-trace import',TRUE,NOW())
                        ON CONFLICT DO NOTHING
                    """, (bid, full, phone or None, cell or None, email or None), commit=True)
                    added += 1
                st.success(f"Imported {added:,} contacts · skipped {skipped:,}")
                st.rerun()

# ── MATCH LEADS ──────────────────────────────────────────────────────────────
with tab_match:
    st.subheader("🎯 Match Leads to Buyers")

    match_filter = st.text_input("🔍 Filter buyers", placeholder="Type name to narrow list…", key="match_filter")
    buyers_for_match = execute(
        "SELECT id, display_name FROM cash_buyers WHERE display_name ILIKE %s ORDER BY display_name LIMIT 200"
        if match_filter else
        "SELECT id, display_name FROM cash_buyers ORDER BY display_name LIMIT 200",
        (f"%{match_filter}%",) if match_filter else None,
    )

    if not buyers_for_match:
        st.info("No buyers match your filter — try a different name, or add buyers first.")
    else:
        buyer_lookup = {b["id"]: b["display_name"] for b in buyers_for_match}
        sel_buyer = st.selectbox("Select Buyer",
                                 options=list(buyer_lookup.keys()),
                                 format_func=lambda i: buyer_lookup.get(i, str(i)))

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
