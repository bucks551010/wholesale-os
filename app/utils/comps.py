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


def find_comps(parcel_id: str, sqft: float | None, year_built: int | None, zip_code: str,
               n: int = 15, months: int = 36,
               subject_value: float | None = None) -> list[dict]:
    """Return up to n comps, preferring recent actual sale prices over HCAD estimates.

    When sqft is unknown, falls back to value-range matching (±40% of subject_value).
    Each row includes comp_value, comp_source ('sold'|'hcad_estimate'), and sale_dt.
    """
    sqft_known = sqft is not None and sqft > 0
    yr         = year_built or 1990
    sqft       = sqft or 0  # keep 0 so we know it was missing

    # ── Build sqft or value filter ────────────────────────────────────────────
    if sqft_known:
        size_filter = "AND b.living_area BETWEEN %(min_sqft)s AND %(max_sqft)s"
        sort_expr   = "ABS(b.living_area - %(sqft)s) + ABS(COALESCE(b.year_built, %(yr)s) - %(yr)s) * 50"
    elif subject_value:
        # No sqft data — match by value range instead
        size_filter = "AND p.total_mkt_val BETWEEN %(min_val)s AND %(max_val)s"
        sort_expr   = "ABS(p.total_mkt_val - %(subject_value)s)"
    else:
        size_filter = ""
        sort_expr   = "p.total_mkt_val DESC"

    params = {
        "zip": zip_code, "sqft": sqft, "yr": yr, "pid": parcel_id, "n": n,
        "months": months,
        "min_sqft": (sqft * 0.65) if sqft_known else 0,
        "max_sqft": (sqft * 1.35) if sqft_known else 9_999_999,
        "subject_value": subject_value or 0,
        "min_val": (subject_value * 0.60) if subject_value else 0,
        "max_val": (subject_value * 1.40) if subject_value else 9_999_999,
    }

    # Try actual sold prices first
    rows = execute(f"""
        SELECT
            p.parcel_id, p.full_address,
            p.total_mkt_val, p.total_appr_val,
            b.living_area, b.year_built, b.condition,
            s.sale_price   AS comp_value,
            s.sale_dt,
            'sold'         AS comp_source
        FROM parcels   p
        JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        JOIN LATERAL (
            SELECT sale_price, sale_dt
            FROM sale_history
            WHERE parcel_id = p.parcel_id
              AND sale_price > 10000
              AND sale_dt    > NOW() - (%(months)s || ' months')::INTERVAL
            ORDER BY sale_dt DESC
            LIMIT 1
        ) s ON TRUE
        WHERE p.situs_zip = %(zip)s
          {size_filter}
          AND b.condition IN ('Average','Good','Excellent','Superior')
          AND p.parcel_id != %(pid)s
        ORDER BY {sort_expr}
        LIMIT %(n)s
    """, params)

    if len(rows) >= 3:
        return rows

    # Fall back to HCAD assessed values
    fallback = execute(f"""
        SELECT
            p.parcel_id, p.full_address,
            p.total_mkt_val, p.total_appr_val,
            b.living_area, b.year_built, b.condition,
            p.total_mkt_val  AS comp_value,
            NULL::DATE       AS sale_dt,
            'hcad_estimate'  AS comp_source
        FROM parcels  p
        JOIN buildings b ON b.parcel_id = p.parcel_id AND b.building_num = 1
        WHERE p.situs_zip = %(zip)s
          {size_filter}
          AND p.total_mkt_val > 10000
          AND b.condition IN ('Average','Good','Excellent','Superior')
          AND p.parcel_id != %(pid)s
        ORDER BY {sort_expr}
        LIMIT %(n)s
    """, params)

    # Merge: keep sold comps first, fill remaining slots with estimates
    seen = {r["parcel_id"] for r in rows}
    for r in fallback:
        if r["parcel_id"] not in seen:
            rows.append(r)
            seen.add(r["parcel_id"])
        if len(rows) >= n:
            break

    return rows


def compute_arv(comps: list[dict], living_area: float) -> dict:
    """Trimmed-mean ARV from comps using comp_value (sale price or HCAD estimate)."""
    values = sorted(float(c["comp_value"]) for c in comps if c.get("comp_value"))
    if not values:
        return {"arv": None, "confidence": "none", "comp_count": 0,
                "price_per_sqft": None, "data_source": "none"}

    n = len(values)
    trim = max(1, n // 5)
    trimmed = values[trim: n - trim] if n > 4 else values
    arv = statistics.mean(trimmed)
    ppsf = arv / living_area if living_area else None
    confidence = "high" if n >= 8 else "medium" if n >= 4 else "low"

    sources = [c.get("comp_source", "hcad_estimate") for c in comps if c.get("comp_value")]
    sold_count = sum(1 for s in sources if s == "sold")
    data_source = "sold" if sold_count >= len(sources) / 2 else "hcad_estimate"

    return {"arv": arv, "confidence": confidence, "comp_count": n,
            "price_per_sqft": ppsf, "data_source": data_source,
            "sold_comp_count": sold_count}


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


# ── Deal-type calculators (ChatARV-style) ─────────────────────────────────────

def compute_flip_offer(
    arv: float, repairs: float,
    profit_pct: float = 0.15,
    holding_months: int = 4,
    monthly_holding_rate: float = 0.005,
    closing_pct: float = 0.04,
) -> dict:
    """Maximum offer for a fix-and-flip deal."""
    profit = arv * profit_pct
    holding_costs = arv * monthly_holding_rate * holding_months
    closing_costs = arv * closing_pct
    max_offer = arv - repairs - profit - holding_costs - closing_costs
    return {
        "max_offer": max(0.0, max_offer),
        "profit_target": profit,
        "holding_costs": holding_costs,
        "closing_costs": closing_costs,
    }


def compute_hold(
    arv: float, purchase_price: float, annual_rent: float,
    expenses_pct: float = 0.45,
    down_pct: float = 0.20,
    rate: float = 0.065,
) -> dict:
    """Buy-and-hold rental metrics."""
    down = purchase_price * down_pct
    loan = purchase_price - down
    monthly_rate = rate / 12
    n = 360
    if loan > 0 and monthly_rate > 0:
        monthly_pi = loan * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    else:
        monthly_pi = 0.0
    annual_pi = monthly_pi * 12
    noi = annual_rent * (1 - expenses_pct)
    cash_flow = noi - annual_pi
    cap_rate = noi / purchase_price if purchase_price else 0.0
    coc = cash_flow / down if down else 0.0
    grm = purchase_price / annual_rent if annual_rent else 0.0
    return {
        "down_payment": down,
        "loan_amount": loan,
        "monthly_payment": monthly_pi,
        "noi": noi,
        "annual_cash_flow": cash_flow,
        "cap_rate": cap_rate,
        "coc_return": coc,
        "gross_rent_multiplier": grm,
    }


def compute_brrr(
    arv: float, repairs: float, purchase_price: float,
    refi_ltv: float = 0.75,
    annual_rent: float = 0.0,
    expenses_pct: float = 0.45,
    refi_rate: float = 0.065,
) -> dict:
    """BRRRR strategy: refinance equity pull + rental cash flow."""
    total_invested = purchase_price + repairs
    refi_loan = arv * refi_ltv
    cash_out = refi_loan - total_invested
    equity = arv - refi_loan
    cash_left_in = max(0.0, total_invested - refi_loan)
    result: dict = {
        "total_invested": total_invested,
        "refi_loan_amount": refi_loan,
        "cash_out": cash_out,
        "equity_remaining": equity,
        "cash_left_in": cash_left_in,
    }
    if annual_rent:
        monthly_rate = refi_rate / 12
        n = 360
        monthly_pi = (
            refi_loan * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
            if refi_loan > 0 and monthly_rate > 0 else 0.0
        )
        noi = annual_rent * (1 - expenses_pct)
        cap_rate = noi / arv if arv else 0.0
        annual_cash_flow = noi - monthly_pi * 12
        result.update({
            "noi": noi,
            "cap_rate": cap_rate,
            "annual_cash_flow": annual_cash_flow,
            "monthly_pi": monthly_pi,
        })
    return result


def compute_novation(
    arv: float, repairs: float,
    agent_pct: float = 0.06,
    contingency: float = 5_000.0,
) -> dict:
    """Novation: investor lists on seller's behalf and earns spread."""
    agent_commission = arv * agent_pct
    net_to_seller = arv - repairs - agent_commission - contingency
    return {
        "list_price": arv,
        "net_to_seller": max(0.0, net_to_seller),
        "investor_spread": arv - max(0.0, net_to_seller),
        "agent_commission": agent_commission,
        "repair_allowance": repairs,
        "contingency": contingency,
    }
