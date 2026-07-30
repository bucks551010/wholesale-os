import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import statistics
from app.utils.db import execute

# Repair cost $/sqft by condition tier
REPAIR_RATES = {
    "Very Low": (45, 65),
    "Low":      (28, 40),
    "Average":  (12, 20),
    "Good":     (3,  8),
    "Excellent": (0, 3),
}

STANDARD_MULTIPLIERS = {
    "conservative": 0.60,
    "standard":     0.65,
    "aggressive":   0.70,
}


def find_comps(parcel_id: str, sqft: float, year_built: int, zip_code: str,
               n: int = 15) -> list[dict]:
    """Return up to n comps: same ZIP, similar sqft/age, non-distressed condition."""
    sqft   = sqft or 1200
    yr     = year_built or 1990
    rows = execute("""
        SELECT
            p.parcel_id, p.full_address,
            p.total_mkt_val, p.total_appr_val,
            b.living_area, b.year_built, b.condition
        FROM parcels  p
        JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        WHERE p.situs_zip = %(zip)s
          AND b.living_area BETWEEN %(min_sqft)s AND %(max_sqft)s
          AND p.total_mkt_val > 10000
          AND b.condition IN ('Average','Good','Excellent','Superior')
          AND p.parcel_id != %(pid)s
        ORDER BY ABS(b.living_area - %(sqft)s)
               + ABS(COALESCE(b.year_built, %(yr)s) - %(yr)s) * 50
        LIMIT %(n)s
    """, {"zip": zip_code, "sqft": sqft, "yr": yr,
          "min_sqft": sqft * 0.65, "max_sqft": sqft * 1.35,
          "pid": parcel_id, "n": n})
    return rows


def compute_arv(comps: list[dict], living_area: float) -> dict:
    """Trimmed-mean ARV from comps. Returns arv, confidence, price_per_sqft."""
    values = sorted(float(c["total_mkt_val"]) for c in comps if c["total_mkt_val"])
    if not values:
        return {"arv": None, "confidence": "none", "comp_count": 0, "price_per_sqft": None}

    n = len(values)
    trim = max(1, n // 5)
    trimmed = values[trim: n - trim] if n > 4 else values
    arv = statistics.mean(trimmed)
    ppsf = arv / living_area if living_area else None
    confidence = "high" if n >= 8 else "medium" if n >= 4 else "low"
    return {"arv": arv, "confidence": confidence, "comp_count": n, "price_per_sqft": ppsf}


def estimate_repairs(condition: str, living_area: float) -> dict:
    """Return low/high repair cost and per-sqft rate."""
    sqft  = living_area or 1200
    lo, hi = REPAIR_RATES.get(condition, (25, 38))
    return {"low": lo * sqft, "high": hi * sqft, "sqft": sqft,
            "rate_low": lo, "rate_high": hi}


def compute_mao(arv: float, repairs_mid: float) -> dict:
    """Return MAO at each standard multiplier."""
    return {
        k: max(0, arv * pct - repairs_mid)
        for k, pct in STANDARD_MULTIPLIERS.items()
    }


def save_valuation(parcel_id: str, arv: float, ppsf: float,
                   comp_count: int, confidence: str):
    execute("""
        INSERT INTO valuations
            (parcel_id, arv_estimate, price_per_sqft, comp_count, confidence,
             method, calc_date)
        VALUES (%s, %s, %s, %s, %s, 'hcad_mkt_val', CURRENT_DATE)
        ON CONFLICT DO NOTHING
    """, (parcel_id, arv, ppsf, comp_count, confidence), commit=True)


def save_repair_estimate(parcel_id: str, condition: str, est: dict):
    execute("""
        INSERT INTO repair_estimates
            (parcel_id, condition_tier, total_low, total_high,
             contingency_pct, created_date)
        VALUES (%s, %s, %s, %s, 10, CURRENT_DATE)
        ON CONFLICT DO NOTHING
    """, (parcel_id, condition, est["low"], est["high"]), commit=True)
