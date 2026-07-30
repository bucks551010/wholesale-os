"""
HCAD Property Data Ingestion
Downloads and imports HCAD bulk data files into PostgreSQL.

Data source: https://pdata.hcad.org/download/
Files used:
  - real_acct.txt   — parcel + value data
  - building_res.txt — residential building details
  - owner.txt        — owner name + mailing address

Usage:
    python ingestion/ingest_hcad.py              # download + import
    python ingestion/ingest_hcad.py --local      # import from existing HCAD_DATA_DIR
"""

import argparse
import csv
import io
import logging
import os
import sys
import time
import zipfile
from pathlib import Path

import requests
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.utils.config import HCAD_DATA_DIR, HCAD_YEAR, TARGET_ZIPS
from app.utils.db import db_cursor, execute

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# HCAD data download base URL
HCAD_BASE_URL = "https://pdata.hcad.org/download"

# Files we need and their download paths
HCAD_FILES = {
    "real_acct":    f"{HCAD_BASE_URL}/{HCAD_YEAR}/Real_acct_owner.zip",
    "building_res": f"{HCAD_BASE_URL}/{HCAD_YEAR}/building_res.zip",
}

# Column mappings — HCAD uses fixed column order (no headers in some files)
# real_acct.txt columns (pipe-delimited)
REAL_ACCT_COLS = [
    "acct", "yr", "hcad_num", "situs_num", "situs_street_pfx",
    "situs_street", "situs_street_sfx", "situs_unit",
    "situs_city", "situs_state", "situs_zip",
    "acct_type", "ag_exempt_flag", "multiple_acct_flag",
    "land_val", "improvement_val", "extra_features_val",
    "ag_val", "total_appr_val", "total_mkt_val", "assessed_val",
    "soil_code", "tot_blk_val", "assessed_val_chg", "tot_appr_val_chg",
    "new_construction_val", "tot_rkt_val", "notice_date", "hcad_link",
]

OWNER_COLS = [
    "acct", "yr", "owner_name", "owner_name_2",
    "mail_addr_1", "mail_addr_2", "mail_city", "mail_state",
    "mail_zip", "mail_country",
]

BUILDING_RES_COLS = [
    "acct", "yr", "bld_num", "bld_class",
    "net_rentable_area", "bld_desc", "impr_desc",
    "living_area", "bed_rms", "full_baths", "half_baths",
    "yr_impr", "eff_yr", "pool", "condition_code",
    "stories", "bld_ar", "rmf_ar",
]


# ──────────────────────────────────────────────────────────
# Download helpers
# ──────────────────────────────────────────────────────────

def download_file(url: str, dest_path: Path) -> bool:
    log.info(f"Downloading {url}...")
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True, desc=dest_path.name
            ) as bar:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    bar.update(len(chunk))
        log.info(f"Saved to {dest_path}")
        return True
    except Exception as e:
        log.error(f"Download failed: {e}")
        return False


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    log.info(f"Extracting {zip_path.name}...")
    extracted = []
    with zipfile.ZipFile(zip_path, "r") as z:
        for name in z.namelist():
            z.extract(name, dest_dir)
            extracted.append(dest_dir / name)
    return extracted


# ──────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────

def safe_numeric(val: str):
    try:
        return float(val.replace(",", "").strip()) if val and val.strip() else None
    except ValueError:
        return None


def safe_int(val: str):
    try:
        v = int(val.strip()) if val and val.strip() else None
        return v
    except ValueError:
        return None


def parse_txt_file(file_path: Path, col_names: list[str], delimiter="|") -> list[dict]:
    """Parse a HCAD pipe-delimited file, auto-detecting header vs fixed-column."""
    rows = []
    encodings = ["cp1252", "utf-8", "latin-1"]

    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc, errors="replace") as f:
                first_line = f.readline()
                # Detect if first line is a header (contains non-numeric first field)
                first_field = first_line.split(delimiter)[0].strip()
                has_header = not first_field.isdigit()
                f.seek(0)

                reader = csv.reader(f, delimiter=delimiter)
                if has_header:
                    headers = [h.strip().lower() for h in next(reader)]
                    col_names = headers  # use actual headers when present

                for line in reader:
                    if len(line) < 2:
                        continue
                    row = {}
                    for i, col in enumerate(col_names):
                        row[col] = line[i].strip() if i < len(line) else ""
                    rows.append(row)
            break
        except UnicodeDecodeError:
            continue

    log.info(f"  Parsed {len(rows):,} rows from {file_path.name}")
    return rows


# ──────────────────────────────────────────────────────────
# Import functions
# ──────────────────────────────────────────────────────────

def import_real_acct(rows: list[dict], target_zips: set[str]) -> tuple[int, int]:
    """Upsert parcels from real_acct data, filtered to target ZIPs."""
    filtered = [r for r in rows if r.get("situs_zip", "")[:5] in target_zips]
    log.info(f"  Filtered to {len(filtered):,} parcels in target ZIPs (from {len(rows):,} total)")

    inserted = updated = 0
    batch = []

    for r in filtered:
        situs_street = " ".join(filter(None, [
            r.get("situs_street_pfx", ""),
            r.get("situs_street", ""),
            r.get("situs_street_sfx", ""),
        ])).strip()

        batch.append({
            "parcel_id":       r.get("acct", "").strip(),
            "situs_num":       r.get("situs_num", "").strip() or None,
            "situs_street":    situs_street or None,
            "situs_city":      r.get("situs_city", "").strip() or "HOUSTON",
            "situs_state":     r.get("situs_state", "TX").strip() or "TX",
            "situs_zip":       r.get("situs_zip", "")[:5].strip() or None,
            "acct_type":       r.get("acct_type", "").strip() or None,
            "land_val":        safe_numeric(r.get("land_val", "")),
            "improvement_val": safe_numeric(r.get("improvement_val", "")),
            "total_appr_val":  safe_numeric(r.get("total_appr_val", "")),
            "total_mkt_val":   safe_numeric(r.get("total_mkt_val", "")),
            "assessed_val":    safe_numeric(r.get("assessed_val", "")),
            "hcad_year":       safe_int(r.get("yr", str(HCAD_YEAR))),
        })

        if len(batch) >= 500:
            i, u = _upsert_parcels(batch)
            inserted += i; updated += u; batch = []

    if batch:
        i, u = _upsert_parcels(batch)
        inserted += i; updated += u

    return inserted, updated


def _upsert_parcels(batch: list[dict]) -> tuple[int, int]:
    sql = """
        INSERT INTO parcels (
            parcel_id, situs_num, situs_street, situs_city,
            situs_state, situs_zip, acct_type,
            land_val, improvement_val, total_appr_val,
            total_mkt_val, assessed_val, hcad_year, last_updated
        ) VALUES (
            %(parcel_id)s, %(situs_num)s, %(situs_street)s, %(situs_city)s,
            %(situs_state)s, %(situs_zip)s, %(acct_type)s,
            %(land_val)s, %(improvement_val)s, %(total_appr_val)s,
            %(total_mkt_val)s, %(assessed_val)s, %(hcad_year)s, NOW()
        )
        ON CONFLICT (parcel_id) DO UPDATE SET
            situs_num        = EXCLUDED.situs_num,
            situs_street     = EXCLUDED.situs_street,
            situs_city       = EXCLUDED.situs_city,
            situs_state      = EXCLUDED.situs_state,
            situs_zip        = EXCLUDED.situs_zip,
            acct_type        = EXCLUDED.acct_type,
            land_val         = EXCLUDED.land_val,
            improvement_val  = EXCLUDED.improvement_val,
            total_appr_val   = EXCLUDED.total_appr_val,
            total_mkt_val    = EXCLUDED.total_mkt_val,
            assessed_val     = EXCLUDED.assessed_val,
            hcad_year        = EXCLUDED.hcad_year,
            last_updated     = NOW()
    """
    with db_cursor(commit=True) as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(cur, sql, batch, page_size=500)
        return len(batch), 0


def import_owners(rows: list[dict], target_parcel_ids: set[str]) -> int:
    """Upsert owner records for parcels we already imported."""
    filtered = [r for r in rows if r.get("acct", "").strip() in target_parcel_ids]
    log.info(f"  Owner records for our parcels: {len(filtered):,}")

    batch = []
    for r in filtered:
        name = r.get("owner_name", "").strip()
        batch.append({
            "parcel_id":    r.get("acct", "").strip(),
            "owner_name":   name or None,
            "owner_name_2": r.get("owner_name_2", "").strip() or None,
            "owner_type":   _classify_owner(name),
            "mail_addr_1":  r.get("mail_addr_1", "").strip() or None,
            "mail_addr_2":  r.get("mail_addr_2", "").strip() or None,
            "mail_city":    r.get("mail_city", "").strip() or None,
            "mail_state":   r.get("mail_state", "").strip() or None,
            "mail_zip":     r.get("mail_zip", "")[:5].strip() or None,
            "mail_country": r.get("mail_country", "US").strip() or "US",
        })

        if len(batch) >= 500:
            _upsert_owners(batch)
            batch = []

    if batch:
        _upsert_owners(batch)

    return len(filtered)


def _classify_owner(name: str) -> str:
    n = (name or "").upper()
    if any(k in n for k in ["LLC", "L.L.C", "LTD", "INC", "CORP", "CO.", "COMPANY", "PARTNERSHIP", "LP "]):
        return "llc"
    if any(k in n for k in ["TRUST", " TR ", " TR,"]):
        return "trust"
    if any(k in n for k in ["ESTATE", "HEIR", "EXECUTOR", "EXECUTRIX"]):
        return "estate"
    if any(k in n for k in ["BANK", "MORTGAGE", "FINANCIAL", "FANNIE", "FREDDIE", "SERVICER"]):
        return "bank"
    return "individual"


def _upsert_owners(batch: list[dict]):
    sql = """
        INSERT INTO owners (
            parcel_id, owner_name, owner_name_2, owner_type,
            mail_addr_1, mail_addr_2, mail_city, mail_state,
            mail_zip, mail_country, situs_zip_cache, last_updated
        )
        SELECT
            %(parcel_id)s, %(owner_name)s, %(owner_name_2)s, %(owner_type)s,
            %(mail_addr_1)s, %(mail_addr_2)s, %(mail_city)s, %(mail_state)s,
            %(mail_zip)s, %(mail_country)s,
            p.situs_zip, NOW()
        FROM parcels p WHERE p.parcel_id = %(parcel_id)s
        ON CONFLICT (parcel_id) DO UPDATE SET
            owner_name   = EXCLUDED.owner_name,
            owner_name_2 = EXCLUDED.owner_name_2,
            owner_type   = EXCLUDED.owner_type,
            mail_addr_1  = EXCLUDED.mail_addr_1,
            mail_addr_2  = EXCLUDED.mail_addr_2,
            mail_city    = EXCLUDED.mail_city,
            mail_state   = EXCLUDED.mail_state,
            mail_zip     = EXCLUDED.mail_zip,
            mail_country = EXCLUDED.mail_country,
            last_updated = NOW()
    """
    with db_cursor(commit=True) as cur:
        import psycopg2.extras
        psycopg2.extras.execute_batch(cur, sql, batch, page_size=500)


def import_buildings(rows: list[dict], target_parcel_ids: set[str]) -> int:
    """Upsert building records for our parcels."""
    filtered = [r for r in rows if r.get("acct", "").strip() in target_parcel_ids]
    log.info(f"  Building records for our parcels: {len(filtered):,}")

    sql = """
        INSERT INTO buildings (
            parcel_id, building_num, living_area, year_built,
            bedrooms, full_baths, half_baths, building_class,
            condition, stories, pool_flag, last_updated
        ) VALUES (
            %(parcel_id)s, %(building_num)s, %(living_area)s, %(year_built)s,
            %(bedrooms)s, %(full_baths)s, %(half_baths)s, %(building_class)s,
            %(condition)s, %(stories)s, %(pool_flag)s, NOW()
        )
        ON CONFLICT DO NOTHING
    """
    batch = []
    for r in filtered:
        batch.append({
            "parcel_id":     r.get("acct", "").strip(),
            "building_num":  safe_int(r.get("bld_num", "1")) or 1,
            "living_area":   safe_numeric(r.get("living_area", "") or r.get("bld_ar", "")),
            "year_built":    safe_int(r.get("yr_impr", "")),
            "bedrooms":      safe_int(r.get("bed_rms", "")),
            "full_baths":    safe_int(r.get("full_baths", "")),
            "half_baths":    safe_int(r.get("half_baths", "")),
            "building_class": r.get("bld_class", "").strip() or None,
            "condition":     r.get("condition_code", "").strip() or None,
            "stories":       safe_numeric(r.get("stories", "")),
            "pool_flag":     r.get("pool", "").strip().upper() in ("Y", "YES", "1"),
        })

        if len(batch) >= 500:
            with db_cursor(commit=True) as cur:
                import psycopg2.extras
                psycopg2.extras.execute_batch(cur, sql, batch, page_size=500)
            batch = []

    if batch:
        with db_cursor(commit=True) as cur:
            import psycopg2.extras
            psycopg2.extras.execute_batch(cur, sql, batch, page_size=500)

    return len(filtered)


# ──────────────────────────────────────────────────────────
# Ingestion log helpers
# ──────────────────────────────────────────────────────────

def log_start(job_name: str) -> int:
    rows = execute(
        "INSERT INTO ingestion_log (job_name, started_at, status) VALUES (%s, NOW(), 'running') RETURNING id",
        (job_name,), commit=True
    )
    return rows[0]["id"] if rows else -1


def log_finish(log_id: int, status: str, processed: int, inserted: int, updated: int, error: str = None):
    execute(
        """UPDATE ingestion_log SET
               finished_at=NOW(), status=%s,
               records_processed=%s, records_inserted=%s,
               records_updated=%s, error_message=%s
           WHERE id=%s""",
        (status, processed, inserted, updated, error, log_id),
        commit=True
    )


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

def run(local_only: bool = False):
    if not TARGET_ZIPS:
        log.error("TARGET_ZIPS is empty. Set it in .env before running.")
        sys.exit(1)

    zip_set = set(z[:5] for z in TARGET_ZIPS)
    log.info(f"Target ZIPs: {sorted(zip_set)}")

    data_dir = Path(HCAD_DATA_DIR)
    data_dir.mkdir(parents=True, exist_ok=True)

    log_id = log_start("ingest_hcad")
    total_parcels = total_owners = total_buildings = 0

    try:
        # ── Step 1: Get / locate data files ──────────────────
        real_acct_path = _resolve_file(data_dir, "real_acct.txt", HCAD_FILES["real_acct"], local_only)
        owner_path     = _resolve_file(data_dir, "owner.txt", HCAD_FILES["real_acct"], local_only)
        bldg_path      = _resolve_file(data_dir, "building_res.txt", HCAD_FILES["building_res"], local_only)

        # ── Step 2: Import parcels ────────────────────────────
        log.info("Parsing real_acct.txt...")
        acct_rows = parse_txt_file(real_acct_path, REAL_ACCT_COLS)
        ins, upd = import_real_acct(acct_rows, zip_set)
        total_parcels = ins + upd
        log.info(f"  Parcels: {total_parcels:,} processed")

        # Get parcel IDs we actually imported for filtering subsequent files
        result = execute("SELECT parcel_id FROM parcels", commit=False)
        imported_ids = {r["parcel_id"] for r in result}
        log.info(f"  Total parcels in DB for our ZIPs: {len(imported_ids):,}")

        # ── Step 3: Import owners ─────────────────────────────
        if owner_path and owner_path.exists():
            log.info("Parsing owner.txt...")
            owner_rows = parse_txt_file(owner_path, OWNER_COLS)
            total_owners = import_owners(owner_rows, imported_ids)
        else:
            log.warning("owner.txt not found — skipping owner import")

        # ── Step 4: Import buildings ──────────────────────────
        if bldg_path and bldg_path.exists():
            log.info("Parsing building_res.txt...")
            bldg_rows = parse_txt_file(bldg_path, BUILDING_RES_COLS)
            total_buildings = import_buildings(bldg_rows, imported_ids)
        else:
            log.warning("building_res.txt not found — skipping building import")

        log_finish(log_id, "success", total_parcels + total_owners + total_buildings,
                   total_parcels, 0)
        log.info(f"✅ HCAD ingestion complete — {total_parcels:,} parcels, "
                 f"{total_owners:,} owners, {total_buildings:,} buildings")

    except Exception as e:
        log.exception("Ingestion failed")
        log_finish(log_id, "error", 0, 0, 0, str(e))
        sys.exit(1)


def _resolve_file(data_dir: Path, filename: str, download_url: str, local_only: bool) -> Path | None:
    """Find a file locally or download and extract it."""
    # Check if already extracted
    existing = list(data_dir.glob(f"**/{filename}"))
    if existing:
        log.info(f"Found {filename} at {existing[0]}")
        return existing[0]

    if local_only:
        log.warning(f"{filename} not found locally and --local mode is on. Skipping.")
        return None

    # Download and extract
    zip_name = download_url.split("/")[-1]
    zip_path = data_dir / zip_name
    if not zip_path.exists():
        ok = download_file(download_url, zip_path)
        if not ok:
            return None

    extracted = extract_zip(zip_path, data_dir)
    found = [p for p in extracted if p.name.lower() == filename.lower()]
    return found[0] if found else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest HCAD data into PostgreSQL")
    parser.add_argument("--local", action="store_true",
                        help="Use only locally cached files, do not download")
    args = parser.parse_args()
    run(local_only=args.local)
