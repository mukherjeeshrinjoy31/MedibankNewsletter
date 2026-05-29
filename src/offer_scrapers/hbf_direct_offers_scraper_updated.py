"""
HBF direct offers scraper.

Uses Playwright (headless Chromium) because HBF blocks plain HTTP requests
(returns 403 from datacenter IPs).

HBF currently runs three sign-up offers:
  - Homepage (combined hospital + extras): up to 14 weeks FREE plus no waits
    on eligible extras, offer ends 30 July 2026
  - Hospital cover: 6 weeks FREE, offer ends 30 June 2026
  - Extras cover: 6 weeks FREE plus no waits on eligible extras,
    offer ends 30 June 2026

The waive-detection regex has been broadened to catch HBF's "no waits on
eligible extras" phrasing in addition to the "2 & 6 month wait" wording
used by other brands.

To install Playwright:
    pip install playwright
    python -m playwright install chromium
"""
import json
import logging
import sys
import os
import re
import io
import openpyxl
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# BRAND CONFIG â€” the only per-brand block
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
SOURCE          = 'hbf'
BRAND           = 'HBF'           # must match Brand column in Excel
TIER            = 'medibank_specific'
DATASET         = 'direct_offers'
BUCKET          = 'p000268ds-comp-offers'
LAST_OFFER_FILE = f'{SOURCE}_last_offer.txt'
EXCEL_FILE      = 'comp_offer.xlsx'
AWS_REGION      = os.getenv('AWS_REGION', 'ap-southeast-2')
S3_EXCEL_KEY    = os.getenv('S3_EXCEL_KEY', f'raw/excel/{EXCEL_FILE}')
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')
LOG_FILE        = f'{SOURCE}_direct_offers.log'
ROOT_URL        = 'https://www.hbf.com.au'
TERMS_URL       = 'https://www.hbf.com.au/terms-and-conditions/new-member-promotion'

# Pages to scrape. Homepage banner is the combined hospital + extras hero;
# hospital and extras cover pages each carry their own dedicated offer.
PAGES = [
    {"url": "https://www.hbf.com.au",                            "cover_hint": "hospital + extras"},
    {"url": "https://www.hbf.com.au/health-insurance/hospital-cover", "cover_hint": "hospital only"},
    {"url": "https://www.hbf.com.au/health-insurance/extras-cover",   "cover_hint": "extras only"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Excel column mapping (scraper field -> Excel header)
EXCEL_COL_MAP = {
    "weeks_free":       "Offer : Weeks Free",
    "waiting_waive":    "Offer : Waiting period waive",
    "other":            "Offer : Other",
    "end_date":         "Offer : End date",
    "terms_conditions": ("Offer : T&C", "Offer : T&C's", "Offer : T&Cs", "Offer : T&Cs apply"),
}

COVER_TYPES = ["hospital + extras", "hospital only", "extras only"]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def detect_cover_type(text):
    """Determine which cover type the text refers to."""
    t = text.lower()
    has_hospital = "hospital" in t
    has_extras   = "extras"   in t
    if has_hospital and has_extras:
        return "hospital + extras"
    if has_extras and not has_hospital:
        return "extras only"
    if has_hospital and not has_extras:
        return "hospital only"
    return None


# â”€â”€ Helper: extract offer details from a section of text â”€â”€â”€â”€â”€â”€â”€â”€
def fix_mojibake(text):
    """Repair common UTF-8 text that was accidentally decoded as Windows-1252."""
    if not isinstance(text, str):
        return text
    replacements = {
        "\u00e2\u0080\u0099": "'",
        "\u00e2\u0080\u0098": "'",
        "\u00e2\u0080\u009c": '"',
        "\u00e2\u0080\u009d": '"',
        "\u00e2\u0080\u0093": "-",
        "\u00e2\u0080\u0094": "-",
        "\u00e2\u0080\u00a8": " ",
        "\u00c2\u00a0": " ",
        "\u00c2": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    if not any(marker in text for marker in ("Ã‚", "Ã¢")):
        return text
    try:
        return text.encode("windows-1252").decode("utf-8")
    except UnicodeError:
        return text


def _clean_text(text):
    text = fix_mojibake(text)
    return re.sub(r'\s+', ' ', text).strip()


def extract_hbf_terms_by_cover(html):
    """Extract the current HBF new-member promotion T&C section by cover type."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = _clean_text(soup.get_text(" ", strip=True))
    sections = {
        "hospital + extras": (
            r"Promotional offer:\s*Up to 14 Weeks Free.*?",
            r"(?:HBF\s*[-\u2013\u2014]\s*New Joiners Competition|Promotional offer:\s*6 Weeks Free\s*\(Hospital Only\))",
        ),
        "hospital only": (
            r"Promotional offer:\s*6 Weeks Free\s*\(Hospital Only\)",
            r"Promotional offer:\s*6 weeks free\s*\(extras only\)",
        ),
        "extras only": (
            r"Promotional offer:\s*6 weeks free\s*\(extras only\).*?Waived Waits",
            r"Past promotional offers",
        ),
    }

    terms_by_cover = {}
    for cover_type, (start_pattern, stop_pattern) in sections.items():
        start = re.search(start_pattern, page_text, re.IGNORECASE)
        if not start:
            continue
        chunk = page_text[start.start():]
        stop = re.search(stop_pattern, chunk[start.end() - start.start():], re.IGNORECASE)
        if stop:
            chunk = chunk[:start.end() - start.start() + stop.start()]
        terms_by_cover[cover_type] = _clean_text(chunk)

    return terms_by_cover


def extract_offer(text):
    """Return {weeks_free, waiting_waive, other, end_date} for an offer block.
    Any field with no match returns the literal string 'none'."""
    text_lower = text.lower()

    # Weeks free
    weeks_free = "none"
    m = re.search(r'(?:up to\s+)?(\d+)\s*weeks?\s*free', text_lower)
    if m:
        weeks_free = f"up to {m.group(1)} weeks free"

    # Waiting period waive â€” must be explicitly tied to the offer.
    # Catches multiple phrasings:
    #   "2 & 6 month wait on extras"          (nib)
    #   "2 & 6 month waiting periods waived"  (Medibank/AHM)
    #   "2&6 month waits waived"              (Medibank short form)
    #   "no waits on eligible extras"         (HBF)
    #   "serve no waits on eligible extras"   (HBF combined banner)
    waiting_waive = "none"
    m = re.search(
        r'(?:skip the\s+)?2\s*&?\s*6\s*month\s*'
        r'(?:waiting\s*periods?|waits?|wait)\s*'
        r'(?:on\s+(?:eligible\s+)?extras|waived?)',
        text_lower
    )
    if m:
        waiting_waive = m.group(0).strip()
    else:
        # HBF-style phrasing: "(serve) no waits on (eligible) extras"
        m = re.search(
            r'(?:serve\s+)?no\s+waits?\s+on\s+(?:eligible\s+)?extras',
            text_lower
        )
        if m:
            waiting_waive = m.group(0).strip()

    # Other offers (gift cards, points). No promo codes.
    other = []
    m = re.search(r'\$[\d,]+\s*(?:in\s*)?gift cards?', text_lower)
    if m:
        other.append(m.group(0))
    m = re.search(r'[\d,]+\s*(?:live better\s*)?(?:rewards?\s*)?points', text_lower)
    if m:
        other.append(m.group(0))

    # End date â€” handles multiple phrasings, dates with or without year
    end_date = "none"
    m = re.search(
        r'(?:offer ends?|online by|join by|available until|valid until|expires?)'
        r'[\s,]*'
        r'(\d{1,2}\s+'
        r'(?:january|february|march|april|may|june|july|august|september|october|november|december|'
        r'jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)'
        r'(?:\s+\d{4})?)',
        text_lower
    )
    if m:
        end_date = m.group(1).strip()

    return {
        "weeks_free":       weeks_free,
        "waiting_waive":    waiting_waive,
        "other":            ", ".join(other) if other else "none",
        "end_date":         end_date,
        "terms_conditions": "none",
    }


# â”€â”€ Helper: fetch rendered HTML via Playwright â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _fetch_rendered_html(url, page):
    """Use a shared Playwright page to fetch JS-rendered HTML for a URL.
    Waits for offer-related text to appear; falls back to a brief sleep if it
    doesn't show up so we still get whatever content has loaded."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log.warning(f"page.goto timed out for {url}: {e} â€” continuing")

    # Try to wait for actual offer-related text to render (covers most pages)
    try:
        page.wait_for_selector("text=/weeks free/i", timeout=10000)
    except Exception:
        # Some pages may have no offer at all â€” that's fine, just continue
        pass

    # Brief extra wait so animations / late-loading text settle
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    return page.content()


# â”€â”€ Helper: find offers on a page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def find_offers_on_page(url, cover_hint=None, page=None, terms_by_cover=None):
    """Find offer blocks on a single page. cover_hint forces classification.
    `page` is a Playwright Page object â€” required, since nib renders offer
    text via JavaScript and plain HTTP requests miss it."""
    try:
        log.info(f"Scraping: {url}")
        if page is None:
            raise RuntimeError("nib scraper requires a Playwright page; call via scrape()")
        html = _fetch_rendered_html(url, page)
        soup = BeautifulSoup(html, "html.parser")

        offers_found = []

        # Look at all headings + short paragraphs/divs for offer-trigger phrases
        for tag in soup.find_all(["h1", "h2", "h3", "p", "div"]):
            heading_text = tag.get_text(strip=True).lower()

            # Must mention an offer trigger
            if "weeks free" not in heading_text and "gift card" not in heading_text:
                continue
            # Skip very long blocks (likely whole-page containers)
            if len(heading_text) > 500:
                continue

            section = tag.find_parent()
            if not section:
                continue

            # Walk up to a wider ancestor so adjacent text (like the end-date
            # paragraph that sits in a sibling block) is included. We pick the
            # nearest ancestor whose text fits within a reasonable size â€” large
            # enough to include the full offer block but small enough to avoid
            # capturing the whole page.
            best = section
            cursor = section
            for _ in range(4):
                parent = cursor.find_parent()
                if not parent:
                    break
                ptext = parent.get_text(separator=" ", strip=True)
                if len(ptext) > 2000:
                    break
                cursor = parent
                best = parent

            section_text = best.get_text(separator=" ", strip=True)

            # Classify the offer's cover type
            cover_type = cover_hint or detect_cover_type(heading_text)
            if not cover_type:
                cover_type = detect_cover_type(section_text[:300])
            if not cover_type:
                continue

            offer = extract_offer(section_text)
            if terms_by_cover:
                offer["terms_conditions"] = terms_by_cover.get(cover_type, "none")
            offer["cover_type"]  = cover_type
            offer["source_page"] = url
            offer["heading"]     = tag.get_text(strip=True)

            # Avoid duplicates on same page (same cover type)
            if any(o["cover_type"] == cover_type and o["source_page"] == url
                   for o in offers_found):
                continue

            offers_found.append(offer)
            log.info(f"  Found offer: {cover_type} â€” {tag.get_text(strip=True)[:60]}")

        return offers_found

    except Exception as e:
        log.error(f"Failed to scrape {url}: {e}")
        return []


# â”€â”€ Aggregate offers by cover type â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def aggregate_offers(all_offers):
    """Deduplicate by cover type. Keep the entry with the most populated fields."""
    by_cover = {}
    for offer in all_offers:
        cover = offer["cover_type"]
        if cover not in by_cover:
            by_cover[cover] = offer
            continue
        existing = by_cover[cover]
        existing_filled = sum(1 for k in ["weeks_free", "waiting_waive", "other", "end_date", "terms_conditions"]
                              if existing[k] != "none")
        new_filled = sum(1 for k in ["weeks_free", "waiting_waive", "other", "end_date", "terms_conditions"]
                         if offer[k] != "none")
        if new_filled > existing_filled:
            by_cover[cover] = offer

    final = []
    for cover_type in COVER_TYPES:
        if cover_type in by_cover:
            offer = by_cover[cover_type]
            # Only flag as a real promotion if at least one offer field has data.
            # Otherwise the page may just mention "weeks free" in unrelated
            # content (FAQs, awards, etc.) with no actual offer to scrape.
            has_data = any(
                offer.get(k, "none") != "none"
                for k in ["weeks_free", "waiting_waive", "other", "end_date", "terms_conditions"]
            )
            offer["offer_detection"] = (
                "PROMOTION DETECTED" if has_data else "NO CURRENT PROMOTION FOUND"
            )
        else:
            offer = {
                "cover_type":      cover_type,
                "offer_detection": "NO CURRENT PROMOTION FOUND",
                "weeks_free":      "none",
                "waiting_waive":   "none",
                "other":           "none",
                "end_date":        "none",
                "terms_conditions": "none",
            }
        offer["channel"] = "direct"
        final.append(offer)

    return final


# â”€â”€ Load/save last offer (for week-on-week change detection) â”€â”€â”€â”€
def load_last_offer():
    try:
        if os.path.exists(LAST_OFFER_FILE):
            with open(LAST_OFFER_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        log.warning(f"Could not load last offer: {e}")
    return None


def save_current_offer(text):
    try:
        with open(LAST_OFFER_FILE, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        log.warning(f"Could not save current offer: {e}")


# â”€â”€ Main scrape â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def scrape():
    """Scrape all pages, aggregate by cover type, and return (text, results)."""
    all_offers = []

    # Launch a single headless Chromium and re-use one page across all URLs.
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        browser_page = context.new_page()
        terms_by_cover = {}
        try:
            terms_html = _fetch_rendered_html(TERMS_URL, browser_page)
            terms_by_cover = extract_hbf_terms_by_cover(terms_html)
            log.info(f"Loaded HBF T&C sections: {', '.join(terms_by_cover) or 'none'}")
        except Exception as e:
            log.warning(f"Could not load HBF T&C page: {e}")

        for cfg in PAGES:
            offers = find_offers_on_page(
                cfg["url"], cfg.get("cover_hint"), page=browser_page, terms_by_cover=terms_by_cover
            )
            all_offers.extend(offers)

        browser.close()

    results = aggregate_offers(all_offers)

    current_text = json.dumps(results, ensure_ascii=False)
    last_offer   = load_last_offer()
    if last_offer and last_offer == current_text:
        offer_status = "OFFER STATUS: UNCHANGED from last week"
    else:
        offer_status = "OFFER STATUS: NEW or CHANGED this week"
    save_current_offer(current_text)
    log.info(offer_status)

    run_date = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Source: {SOURCE} | Dataset: {DATASET} | Run Date: {run_date}",
        f"{offer_status}",
        "",
        f"{BRAND} Direct Offers (aggregated from {len(PAGES)} pages):",
        ""
    ]
    for i, r in enumerate(results):
        lines.append(f"{i+1}. Cover Type:    {r['cover_type']}")
        lines.append(f"   Channel:        {r['channel']}")
        lines.append(f"   Status:         {r['offer_detection']}")
        lines.append(f"   Weeks Free:     {r['weeks_free']}")
        lines.append(f"   Waiting Waive:  {r['waiting_waive']}")
        lines.append(f"   Other:          {r['other']}")
        lines.append(f"   End Date:       {r['end_date']}")
        lines.append(f"   T&C:            {r['terms_conditions']}")
        lines.append("")

    return "\n".join(lines), results


# â”€â”€ Build payload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def build_payload(content):
    return {
        'source':     SOURCE,
        'tier':       TIER,
        'dataset':    DATASET,
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'url':        ROOT_URL,
        'content':    content,
    }


# â”€â”€ Save locally â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def save_locally(payload):
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    filename = f"{SOURCE}_{DATASET}_{date}.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"Saved: {filename}")
    except Exception as e:
        log.error(f"Failed to save file: {e}")


# â”€â”€ Excel: locate column indices from header row â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _header_index(ws):
    for row in ws.iter_rows(max_row=50):
        mapping = {}
        for cell in row:
            if cell.value is None:
                continue
            val = str(cell.value).strip()
            if val.startswith("Offer") or val in ("Brand", "Cover Type", "Channel"):
                mapping[val] = cell.column - 1
        if mapping:
            return mapping
    return {}


# â”€â”€ Excel: fill Direct rows for this brand â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _normalise_header(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _find_column_index(col_idx, wanted):
    wanted_names = wanted if isinstance(wanted, (tuple, list, set)) else (wanted,)
    normalised = {
        _normalise_header(header): idx
        for header, idx in col_idx.items()
    }
    for name in wanted_names:
        idx = normalised.get(_normalise_header(name))
        if idx is not None:
            return idx
    return None


def _write_results_to_workbook(wb, results):
    ws = wb["table"]
    col_idx = _header_index(ws)

    direct_offers = {
        o["cover_type"].strip().lower(): o
        for o in results
        if o.get("channel", "").strip().lower() == "direct"
    }

    rows_updated = 0
    for row in ws.iter_rows(min_row=2):
        brand_val   = str(row[0].value or "").strip().lower()
        cover_val   = str(row[1].value or "").strip().lower()
        channel_val = str(row[2].value or "").strip().lower()

        if brand_val != BRAND.lower() or channel_val != "direct":
            continue

        offer = direct_offers.get(cover_val)
        if not offer:
            continue

        for field, col_name in EXCEL_COL_MAP.items():
            column = _find_column_index(col_idx, col_name)
            if column is None:
                continue
            value = offer.get(field)
            row[column].value = (
                None if (value is None or str(value).strip().lower() == "none")
                else value
            )
        rows_updated += 1

    return rows_updated


def update_excel(results, filepath=EXCEL_FILE):
    """Write Direct-channel results into the matching brand rows.
    'none' values become blank cells. Other brands and Aggregator rows untouched."""
    if not os.path.exists(filepath):
        log.warning(f"Excel file not found: {filepath} â€” skipping update")
        return

    wb = openpyxl.load_workbook(filepath)
    rows_updated = _write_results_to_workbook(wb, results)
    wb.save(filepath)
    log.info(f"Excel updated: {rows_updated} {BRAND} Direct row(s) written to {filepath}")


def update_excel_on_s3(results, bucket=BUCKET, key=S3_EXCEL_KEY):
    """Download comp_offer.xlsx from S3, update this brand's Direct rows, and overwrite it."""
    try:
        import boto3
    except ImportError:
        log.error("boto3 is not installed - cannot update Excel workbook on S3")
        return

    s3 = boto3.client("s3", region_name=AWS_REGION)
    obj = s3.get_object(Bucket=bucket, Key=key)
    wb = openpyxl.load_workbook(io.BytesIO(obj["Body"].read()))
    rows_updated = _write_results_to_workbook(wb, results)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.read(),
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    log.info(f"Excel updated on S3: {rows_updated} {BRAND} Direct row(s) written to s3://{bucket}/{key}")


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
if __name__ == '__main__':
    log.info("=" * 50)
    log.info(f"Starting scrape: {SOURCE} / {DATASET}")
    log.info("=" * 50)

    content, results = scrape()

    if not content:
        log.warning("No content found â€” file will not be saved")
    else:
        payload = build_payload(content)
        save_locally(payload)
        update_excel(results)
        if UPDATE_S3_EXCEL:
            update_excel_on_s3(results)

    log.info("Scrape complete")
