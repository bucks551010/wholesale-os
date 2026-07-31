import os
from dotenv import load_dotenv

load_dotenv()

TARGET_ZIPS: list[str] = [
    z.strip() for z in os.getenv("TARGET_ZIPS", "").split(",") if z.strip()
]

HCAD_DATA_DIR: str = os.getenv("HCAD_DATA_DIR", "./data/hcad")
HCAD_YEAR: int = int(os.getenv("HCAD_YEAR", "2026"))

APP_TITLE: str = os.getenv("APP_TITLE", "WholesaleOS")
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

SMTP_FROM: str = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_PASS: str = os.getenv("SMTP_APP_PASSWORD", "")

GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

# Offer formula defaults (all editable per deal)
DEFAULT_CLOSING_COSTS = 3_000
DEFAULT_ASSIGNMENT_FEE = 10_000
DEFAULT_CONTINGENCY_PCT = 12

# Motivated score weights (must sum to 100)
SCORE_WEIGHTS = {
    "tax":        30,
    "violation":  25,
    "foreclosure": 15,
    "vacancy":    15,
    "probate":    10,
    "absentee":    3,
    "portfolio":   2,
}
