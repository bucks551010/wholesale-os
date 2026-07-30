def fmt_currency(value, default="—") -> str:
    if value is None:
        return default
    return f"${value:,.0f}"


def fmt_address(num, street, city="Houston", state="TX", zip_code="") -> str:
    parts = [p for p in [num, street] if p]
    line1 = " ".join(parts).strip()
    line2 = ", ".join(p for p in [city, state] if p)
    if zip_code:
        line2 += f" {zip_code}"
    return f"{line1}, {line2}" if line1 else line2


def owner_type_label(raw: str) -> str:
    raw = (raw or "").upper()
    if any(k in raw for k in ["LLC", "L.L.C", "LTD", "INC", "CORP", "COMPANY", "CO."]):
        return "LLC / Entity"
    if any(k in raw for k in ["TRUST", "TR "]):
        return "Trust"
    if any(k in raw for k in ["ESTATE", "HEIR", "EXECUTOR"]):
        return "Estate / Probate"
    if any(k in raw for k in ["BANK", "MORTGAGE", "FINANCIAL", "FANNIE", "FREDDIE"]):
        return "Bank / Lender"
    return "Individual"


def score_color(score: int) -> str:
    if score >= 70:
        return "🔴"
    if score >= 40:
        return "🟡"
    return "🟢"


def feasibility_badge(feasible: bool | None) -> str:
    if feasible is True:
        return "✅ Feasible"
    if feasible is False:
        return "❌ Won't work"
    return "⚠️ Unknown"
