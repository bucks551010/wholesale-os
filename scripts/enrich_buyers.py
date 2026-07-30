"""
Enrich cash buyers with real contact info from Google Maps (no API key, no billing).
Uses Playwright headless browser to render JavaScript-heavy pages.
Run:  python scripts/enrich_buyers.py [--limit N] [--start-id N]
"""
import sys, re, time, argparse, logging
sys.path.insert(0, r"C:\Users\v-jmoten\wholesale-os")
from app.utils.db import execute
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger()

PHONE_RE = re.compile(r"\(?\b(\d{3})\)?[-.\s](\d{3})[-.\s](\d{4})\b")

def clean_phone(raw):
    """Strip non-digit prefix characters from Maps phone strings."""
    m = PHONE_RE.search(raw or "")
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}" if m else ""

def extract_url(href):
    """Parse actual URL out of Google's /url?q= redirect."""
    if not href: return ""
    m = re.search(r'/url\?q=([^&]+)', href)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    return href if href.startswith('http') else ""

def scrape_google_maps(page, company_name):
    """Search Google Maps for a business, extract phone, website, address."""
    query = f"{company_name} Houston TX real estate"
    url   = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        # Accept cookies if prompted
        try:
            page.click("button:has-text('Accept all')", timeout=3000)
        except PWTimeout:
            pass

        # Wait for results panel
        try:
            page.wait_for_selector("[aria-label='Results for']", timeout=8000)
        except PWTimeout:
            pass

        # Click first result
        first = page.query_selector("a[href*='/maps/place/']")
        if first:
            first.click()
            try:
                page.wait_for_selector("[data-item-id='phone:tel:']", timeout=8000)
            except PWTimeout:
                time.sleep(2)

        content = page.content()
        phones  = PHONE_RE.findall(content)

        # Extract phone from Maps-specific element
        phone_el  = page.query_selector("[data-item-id*='phone:tel:']")
        website_el = page.query_selector("a[data-item-id='authority']")
        addr_el   = page.query_selector("[data-item-id='address']")
        title_el  = page.query_selector("h1.DUwDvf, h1[jstcache]")

        return {
            "found_name": title_el.inner_text().strip()   if title_el  else "",
            "phone":      phone_el.inner_text().strip()   if phone_el  else (f"({phones[0][0]}) {phones[0][1]}-{phones[0][2]}" if phones else ""),
            "website":    website_el.get_attribute("href") if website_el else "",
            "address":    addr_el.inner_text().strip()    if addr_el   else "",
        }
    except Exception as e:
        log.warning(f"    Error: {e}")
        return {}


def run(limit=50, start_id=0, dry_run=False):
    buyers = execute("""
        SELECT b.id, b.display_name, b.mailing_city
        FROM cash_buyers b
        WHERE b.id > %s
          AND NOT EXISTS (
              SELECT 1 FROM buyer_contacts bc WHERE bc.buyer_id = b.id
          )
        ORDER BY b.id
        LIMIT %s
    """, (start_id, limit))

    log.info(f"Enriching {len(buyers)} buyers via Google Maps…")
    found = skipped = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        for i, b in enumerate(buyers):
            name = b["display_name"]
            log.info(f"  [{i+1}/{len(buyers)}] {name}")

            info = scrape_google_maps(page, name)

            phone      = clean_phone(info.get("phone",   ""))
            website    = extract_url(info.get("website", ""))
            found_name = info.get("found_name", "").strip()

            if not phone and not website:
                log.info(f"    → no data found")
                skipped += 1
            else:
                log.info(f"    → phone={phone!r}  website={website!r}  name={found_name!r}")
                if not dry_run:
                    execute("""
                        INSERT INTO buyer_contacts
                            (buyer_id, full_name, phone, notes, is_primary, last_updated)
                        VALUES (%s, %s, %s, %s, TRUE, NOW())
                    """, (
                        b["id"],
                        found_name or name,
                        phone or None,
                        f"Google Maps auto-enrich · website: {website}" if website else "Google Maps auto-enrich",
                    ), commit=True)
                    # Also update website on buyer record if blank
                    if website:
                        execute("UPDATE cash_buyers SET notes = COALESCE(notes,'') || %s WHERE id=%s",
                                (f" | web:{website}", b["id"]), commit=True)
                found += 1

            # Polite delay to avoid rate limits
            time.sleep(2)

        context.close()
        browser.close()

    log.info(f"Done — {found} enriched, {skipped} no data found")
    return found, skipped


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit",    type=int, default=50,  help="Max buyers to process")
    ap.add_argument("--start-id", type=int, default=0,   help="Resume from buyer ID > N")
    ap.add_argument("--dry-run",  action="store_true",   help="Don't write to DB")
    args = ap.parse_args()
    run(limit=args.limit, start_id=args.start_id, dry_run=args.dry_run)
