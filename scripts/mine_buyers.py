"""Mine cash buyers from HCAD multi-property LLC/trust owners and load into cash_buyers table."""
import sys, uuid, logging
sys.path.insert(0, r"C:\Users\v-jmoten\wholesale-os")
from app.utils.db import execute, db_cursor
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger()

HOMEBUILDER_KEYWORDS = [
    "DR HORTON","M/I HOMES","M I HOMES","TOLL ","LENNAR","KB HOME","PULTE","MERITAGE",
    "BEAZER","CENTEX","PERRY HOME","DAVID WEEKLEY","HIGHLAND HOME",
    "COVENTRY HOME","NEWMARK HOME","TRENDMAKER","GEHAN HOME",
    "LONG LAKE","WESTIN HOME","VILLAGE BUILDER","CHESMAR","PLANTATION HOME",
    "HISTORY MAKER","BRIGHTLAND","CASTLEROCK","BRIGHTWATER","CLARITY HOME",
    "BETENBOUGH","ANGLIA HOME","NEWLAND","TAYLOR MORRISON",
    # Infrastructure / non-investor entities
    "RAILROAD","RAILWAY","ELECTRIC","GAS CO","PIPELINE","TRANSMISSION LINE",
    "CHURCH","CHAPEL","TEMPLE","MOSQUE","MINISTRY","DIOCESE",
    "SCHOOL DISTRICT","HOUSTON ISD","HISD",
    "COUNTY OF","CITY OF","STATE OF","DEPARTMENT OF",
    "CEMETERY","GOLF CLUB","COUNTRY CLUB",
    "HOUSING AUTHORITY","METRO ","TXDOT",
]

log.info("Querying multi-property LLC/trust/corp owners...")
candidates = execute("""
    SELECT
        o.owner_name,
        o.owner_type,
        o.mail_addr_1,
        o.mail_city,
        o.mail_state,
        o.mail_zip,
        COUNT(o.parcel_id)                                                      AS prop_count,
        array_agg(DISTINCT p.situs_zip) FILTER (WHERE p.situs_zip IS NOT NULL)  AS zips,
        MIN(p.total_appr_val)                                                   AS min_val,
        MAX(p.total_appr_val)                                                   AS max_val,
        ROUND(AVG(p.total_appr_val))                                            AS avg_val
    FROM owners o
    JOIN parcels p ON p.parcel_id = o.parcel_id
    WHERE o.owner_type IN ('llc', 'trust', 'corporation')
    GROUP BY o.owner_name, o.owner_type, o.mail_addr_1, o.mail_city, o.mail_state, o.mail_zip
    HAVING COUNT(o.parcel_id) BETWEEN 3 AND 200
    ORDER BY prop_count DESC
""")
log.info(f"  {len(candidates):,} raw candidates")

filtered = [
    c for c in candidates
    if not any(kw in (c["owner_name"] or "").upper() for kw in HOMEBUILDER_KEYWORDS)
]
log.info(f"  {len(filtered):,} after removing homebuilders")

existing = {r["display_name"].upper() for r in execute("SELECT display_name FROM cash_buyers")}
new_buyers = [c for c in filtered if (c["owner_name"] or "").upper() not in existing]
log.info(f"  {len(new_buyers):,} not yet in buyers table â€” inserting in batch...")

# Build buyer rows
buyer_rows = [(
    str(uuid.uuid4())[:8],
    c["owner_name"], c["owner_name"], c["owner_type"],
    c["mail_addr_1"], c["mail_city"], c["mail_state"], c["mail_zip"],
    f"HCAD-mined: {c['prop_count']} props Â· avg ${int(c['avg_val'] or 0):,}",
) for c in new_buyers]

INS_BUYER = """
    INSERT INTO cash_buyers
        (buyer_key, display_name, entity_name, entity_type,
         mailing_address, mailing_city, mailing_state, mailing_zip,
         is_verified, notes, last_updated)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,%s,NOW())
    ON CONFLICT DO NOTHING
"""

with db_cursor(commit=True) as cur:
    psycopg2.extras.execute_batch(cur, INS_BUYER, buyer_rows, page_size=500)
log.info(f"  Buyers inserted")

# Fetch back the IDs we just created to build buy-box rows
inserted = execute("""
    SELECT id, display_name FROM cash_buyers
    WHERE display_name = ANY(%s)
""", ([c["owner_name"] for c in new_buyers],))

name_to_id = {r["display_name"]: r["id"] for r in inserted}

# Map back candidate data for buy-box
cand_by_name = {c["owner_name"]: c for c in new_buyers}

INS_BOX = """
    INSERT INTO buyer_buyboxes (buyer_id, min_price, max_price, zip_codes, last_updated)
    VALUES (%s,%s,%s,%s::text[],NOW())
    ON CONFLICT DO NOTHING
"""
box_rows = []
for name, bid in name_to_id.items():
    c = cand_by_name.get(name)
    if not c:
        continue
    zips = list(c["zips"])[:20] if c["zips"] else None
    box_rows.append((bid, int(c["min_val"] or 0), int(c["max_val"] or 999_999), zips))

with db_cursor(commit=True) as cur:
    psycopg2.extras.execute_batch(cur, INS_BOX, box_rows, page_size=500)
log.info(f"  Buy-boxes inserted")

total = execute("SELECT COUNT(*) AS n FROM cash_buyers")[0]["n"]
log.info(f"Done â€” {len(buyer_rows):,} buyers added. Total in DB: {total:,}")

