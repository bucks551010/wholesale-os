"""
Free geocoding and property-photo helpers.
Uses Nominatim (OpenStreetMap) — no API key required.
"""
import time
import urllib.parse
import requests

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_LAST_CALL: float = 0.0  # rate-limit to 1 req/sec per Nominatim ToS


def geocode(address: str, city: str = "Houston", state: str = "TX") -> tuple[float, float] | None:
    """Return (lat, lon) for an address, or None on failure."""
    global _LAST_CALL
    query = f"{address}, {city}, {state}, USA"
    elapsed = time.time() - _LAST_CALL
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    try:
        resp = requests.get(
            _NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": "WholesaleOS/1.0 (real-estate-wholesaling-app)"},
            timeout=5,
        )
        _LAST_CALL = time.time()
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


def street_view_url(lat: float, lon: float, api_key: str = "") -> str:
    """Google Street View Static API URL (requires key) or empty string."""
    if not api_key:
        return ""
    return (
        f"https://maps.googleapis.com/maps/api/streetview"
        f"?size=640x480&location={lat},{lon}&key={api_key}&fov=90&pitch=0"
    )


def photo_links(address: str, lat: float | None = None, lon: float | None = None) -> dict[str, str]:
    """Return a dict of free photo / map deep-links for a property."""
    enc = urllib.parse.quote(address)
    links: dict[str, str] = {
        "Zillow":         f"https://www.zillow.com/homes/{enc}_rb/",
        "Redfin":         f"https://www.redfin.com/search#location={enc}",
        "Realtor.com":    f"https://www.realtor.com/realestateandhomes-search/{enc}",
        "Google Maps":    f"https://www.google.com/maps/search/?api=1&query={enc}",
    }
    if lat and lon:
        links["Street View"] = (
            f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"
        )
        links["Satellite"] = (
            f"https://www.google.com/maps/@{lat},{lon},17z/data=!3m1!1e3"
        )
    return links
