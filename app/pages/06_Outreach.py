import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import io
import zipfile
import streamlit as st
from app.utils.db import execute
from app.utils.contracts import render_yellow_letter

st.set_page_config(page_title="Outreach", page_icon="✉️", layout="wide")
st.title("✉️ Owner Outreach")

# ── Sender settings ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Your Info (Sender)")
    buyer_name  = st.text_input("Your Name",  value=st.session_state.get("buyer_name", ""))
    buyer_phone = st.text_input("Your Phone", value=st.session_state.get("buyer_phone", ""))
    buyer_email = st.text_input("Your Email", value=st.session_state.get("buyer_email", ""))
    if st.button("Save"):
        st.session_state["buyer_name"]  = buyer_name
        st.session_state["buyer_phone"] = buyer_phone
        st.session_state["buyer_email"] = buyer_email
        st.success("Saved")
    st.divider()
    st.header("Filters")
    zip_opts = execute("SELECT DISTINCT situs_zip FROM parcels WHERE situs_zip IS NOT NULL ORDER BY situs_zip")
    zip_list = ["All"] + [r["situs_zip"] for r in zip_opts]
    sel_zip  = st.selectbox("ZIP", zip_list)
    min_score = st.slider("Min Score", 0, 20, 5)
    max_leads = st.slider("Max Letters", 10, 500, 50, step=10)

# ── Load leads ────────────────────────────────────────────────────────────────
where = "l.source = 'hcad_auto' AND l.motivated_score >= %(min_score)s AND o.owner_name IS NOT NULL"
params: dict = {"min_score": min_score}
if sel_zip != "All":
    where += " AND p.situs_zip = %(zip)s"
    params["zip"] = sel_zip

leads = execute(f"""
    SELECT l.id AS lead_id, p.full_address, p.situs_zip, p.situs_city,
           o.owner_name, o.is_absentee, l.motivated_score,
           m.id AS mail_id, m.status AS mail_status, m.sent_date
    FROM leads l
    JOIN  parcels p  ON p.parcel_id = l.parcel_id
    LEFT JOIN owners o    ON o.parcel_id = p.parcel_id
    LEFT JOIN mail_queue m ON m.lead_id  = l.id
    WHERE {where}
    ORDER BY l.motivated_score DESC
    LIMIT %(limit)s
""", {**params, "limit": max_leads})

st.caption(f"{len(leads)} leads loaded · {sum(1 for r in leads if r['mail_status'] == 'sent')} already mailed")

if not leads:
    st.info("No leads match the current filters.")
    st.stop()

# ── Select leads to mail ──────────────────────────────────────────────────────
st.subheader("Select Leads to Mail")

not_yet_mailed = [r for r in leads if r["mail_status"] != "sent"]
col_sel, col_all = st.columns([1, 3])
select_all = col_sel.checkbox("Select all", value=True)

selected_ids: list[int] = []
for row in not_yet_mailed:
    default = select_all
    label = (
        f"Score {row['motivated_score']}  ·  "
        f"{'👤 Absentee ' if row['is_absentee'] else ''}"
        f"{row['owner_name']}  —  {row['full_address']}"
    )
    if st.checkbox(label, value=default, key=f"chk_{row['lead_id']}"):
        selected_ids.append(row["lead_id"])

st.caption(f"{len(selected_ids)} selected")

# ── Preview one letter ────────────────────────────────────────────────────────
if selected_ids and leads:
    sample = next((r for r in leads if r["lead_id"] == selected_ids[0]), leads[0])
    with st.expander("📄 Preview Letter (first selected)"):
        preview = render_yellow_letter(
            owner_name=sample["owner_name"] or "",
            address=sample["full_address"] or "",
            city=sample["situs_city"] or "HOUSTON",
            zip_code=sample["situs_zip"] or "",
            buyer_name=buyer_name or "[YOUR NAME]",
            buyer_phone=buyer_phone or "[YOUR PHONE]",
            buyer_email=buyer_email or "[YOUR EMAIL]",
        )
        st.text(preview)

# ── Generate & Download ───────────────────────────────────────────────────────
st.divider()
dl_col, mark_col = st.columns(2)

if dl_col.button("📦 Generate Letters ZIP", type="primary",
                 disabled=not selected_ids or not buyer_name):
    lead_map = {r["lead_id"]: r for r in leads}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for lid in selected_ids:
            row = lead_map[lid]
            text = render_yellow_letter(
                owner_name=row["owner_name"] or "",
                address=row["full_address"] or "",
                city=row["situs_city"] or "HOUSTON",
                zip_code=row["situs_zip"] or "",
                buyer_name=buyer_name,
                buyer_phone=buyer_phone,
                buyer_email=buyer_email,
            )
            fname = f"letter_{lid}_{(row['full_address'] or str(lid)).replace(' ','_')[:40]}.txt"
            zf.writestr(fname, text)
    buf.seek(0)
    dl_col.download_button("⬇️ Download ZIP", data=buf,
                           file_name=f"outreach_letters_{len(selected_ids)}.zip",
                           mime="application/zip")

if mark_col.button("✅ Mark Selected as Sent", disabled=not selected_ids):
    from datetime import date
    for lid in selected_ids:
        existing = execute("SELECT id FROM mail_queue WHERE lead_id = %s", (lid,))
        if existing:
            execute("UPDATE mail_queue SET status='sent', sent_date=%s WHERE lead_id=%s",
                    (date.today(), lid), commit=True)
        else:
            execute("""INSERT INTO mail_queue (lead_id, piece_type, status, sent_date)
                       VALUES (%s,'yellow_letter','sent',%s)""",
                    (lid, date.today()), commit=True)
        execute("""INSERT INTO outreach_log (lead_id, outreach_date, channel, template_used)
                   VALUES (%s, NOW(), 'direct_mail', 'yellow_letter')""",
                (lid,), commit=True)
    st.success(f"Marked {len(selected_ids)} letters as sent.")
    st.rerun()

# ── Already mailed ────────────────────────────────────────────────────────────
mailed = [r for r in leads if r["mail_status"] == "sent"]
if mailed:
    with st.expander(f"📬 Already Mailed ({len(mailed)})"):
        for r in mailed:
            st.write(f"✉ {r['full_address']}  —  {r['owner_name']}  —  sent {r['sent_date']}")
