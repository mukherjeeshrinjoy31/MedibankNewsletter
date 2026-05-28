"""
AHM direct offers scraper.

Generalised template: only the BRAND CONFIG block at the top is brand-specific.
The rest of the logic â€” cover type detection, offer extraction, aggregation,
Excel update â€” works for any insurer's offer pages.
"""
import json
import logging
import requests
import sys
import os
import re
import io
import openpyxl
from urllib.parse import urljoin
from datetime import datetime, timezone
from bs4 import BeautifulSoup


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# BRAND CONFIG â€” the only per-brand block
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
SOURCE          = 'ahm'
BRAND           = 'AHM'           # must match Brand column in Excel
TIER            = 'medibank_specific'
DATASET         = 'direct_offers'
BUCKET          = 'p000268ds-comp-offers'
LAST_OFFER_FILE = f'{SOURCE}_last_offer.txt'
EXCEL_FILE      = 'comp_offer.xlsx'
AWS_REGION      = os.getenv('AWS_REGION', 'ap-southeast-2')
S3_EXCEL_KEY    = os.getenv('S3_EXCEL_KEY', f'raw/excel/{EXCEL_FILE}')
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')
LOG_FILE        = f'{SOURCE}_direct_offers.log'
ROOT_URL        = 'https://ahm.com.au/health-insurance'

# Pages to scrape. Each page can optionally include a "cover_hint" â€” useful
# when the page is dedicated to one cover type and the heading text alone
# can't be relied on (e.g. nib's hospital-only page). For AHM the heading
# text is descriptive enough so no hints are needed.
PAGES = [
    {"url": "https://ahm.com.au/offer"},
    {"url": "https://ahm.com.au/health-insurance"},
    {"url": "https://ahm.com.au/health-insurance/hospital-cover"},
    {"url": "https://ahm.com.au/health-insurance/extras-cover", "cover_hint": "extras only"},
]
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•


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


# â”€â”€ Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


# â”€â”€ Helper: detect cover type from text â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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


def parse_html(response):
    html = response.content.decode("utf-8", errors="replace")
    return BeautifulSoup(html, "html.parser")


def _terms_link_score(href, link_text, cover_type):
    """Score a candidate ahm offer terms link for the current cover type."""
    candidate = f"{href} {link_text}".lower()
    score = 0

    if "/offer/" in candidate:
        score += 5
    if "see terms" in candidate:
        score += 10

    if cover_type == "extras only":
        if "extras" in candidate:
            score += 80
        if re.search(r"\b8\s*weeks?\b|8-weeks|extras8", candidate):
            score += 40
        if "hospital" in candidate and "extras" not in candidate:
            score -= 80
        if re.search(r"\b12\s*weeks?\b|12-weeks|12w", candidate):
            score -= 30

    elif cover_type == "hospital + extras":
        if "hospital" in candidate:
            score += 50
        if re.search(r"\b12\s*weeks?\b|12-weeks|12w", candidate):
            score += 40
        if "extras-only" in candidate or "extras only" in candidate:
            score -= 80

    elif cover_type == "hospital only":
        if "hospital" in candidate:
            score += 50
        if "extras-only" in candidate or "extras only" in candidate:
            score -= 80

    return score


def find_terms_url(section, base_url, offer_text="", cover_type=None):
    """Find the closest ahm 'See terms' link for an offer card."""
    best_link = None
    best_score = 0

    for container in [section, *section.find_parents(limit=3)]:
        links = container.find_all("a", href=True)
        for link in links:
            link_text = _clean_text(link.get_text(" ", strip=True)).lower()
            href = link["href"].lower()
            if "see terms" not in link_text and "/offer/" not in href:
                continue
            if any(skip in href for skip in ("privacy", "terms-of-use", "website-terms")):
                continue
            score = _terms_link_score(href, link_text, cover_type)
            if score > best_score:
                best_score = score
                best_link = link["href"]

    return urljoin(base_url, best_link) if best_link else None


def fallback_terms_conditions(terms_url):
    """Future-safe fallback when ahm's terms page cannot be parsed."""
    if not terms_url:
        return "none"
    return f"See terms: {terms_url}"


def weeks_free_from_terms_url(terms_url):
    """Extract a weeks-free value from the selected offer terms URL."""
    if not terms_url:
        return None
    url_text = terms_url.lower().replace("%20", " ")
    m = re.search(r'(\d+)[-_\s]*weeks?', url_text)
    if not m:
        return None
    return f"up to {m.group(1)} weeks free"


def extract_terms_section(page_text):
    """Extract ahm's main offer terms section from a terms page."""
    page_text = _clean_text(page_text)
    start = re.search(
        r"general\s*[-\u2013\u2014]\s*offer\s+for\s+new\s+joins",
        page_text,
        re.IGNORECASE
    )
    if not start:
        return None

    page_text = page_text[start.start():]
    stop = re.search(
        r"(?:^|\s)(?:\d+\s+weeks?\s+free\s*:|waive\s+any\s+2\s*&\s*6\s+month|"
        r"offer\s+terms\s*&\s*conditions|"
        r"was this article helpful|call us on|about us|privacy policy|copyright|©)\b",
        page_text,
        re.IGNORECASE
    )
    if stop:
        page_text = page_text[:stop.start()]

    page_text = _clean_text(page_text)
    return page_text if len(page_text) > 80 else None


def fetch_rendered_terms_text(terms_url):
    """Use Playwright if available for client-rendered ahm terms pages."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Playwright is not installed; cannot render ahm terms page")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1200},
                user_agent=HEADERS["User-Agent"],
            )
            page = context.new_page()
            page.goto(terms_url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            text = ""
            for _ in range(12):
                try:
                    text = page.locator("body").inner_text(timeout=5000)
                except Exception:
                    text = ""
                if re.search(r"general\s*[-\u2013\u2014]\s*offer\s+for\s+new\s+joins", text, re.IGNORECASE):
                    break
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    pass
                page.wait_for_timeout(1000)

            browser.close()
            return text
    except Exception as e:
        log.warning(f"Could not render terms from {terms_url}: {e}")
        return None


def fetch_terms_conditions(terms_url):
    """Fetch ahm terms text when available; otherwise return the terms URL."""
    if not terms_url:
        return "none"
    try:
        response = requests.get(terms_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = parse_html(response)
        page_text = _clean_text(soup.get_text(" ", strip=True))

        terms_text = extract_terms_section(page_text)
        if terms_text:
            return terms_text

        rendered_text = fetch_rendered_terms_text(terms_url)
        if rendered_text:
            terms_text = extract_terms_section(rendered_text)
            if terms_text:
                return terms_text

        return fallback_terms_conditions(terms_url)

    except Exception as e:
        log.warning(f"Could not fetch terms from {terms_url}: {e}")
        return fallback_terms_conditions(terms_url)


def extract_end_date(text):
    """Extract an offer end date from offer copy or terms text."""
    text_lower = _clean_text(text).lower()
    date_pattern = (
        r'\d{1,2}\s+'
        r'(?:january|february|march|april|may|june|july|august|september|october|november|december|'
        r'jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)'
        r'(?:\s+\d{4})?'
        r'(?:\s+\d{1,2}:\d{2}\s*(?:am|pm)?)?'
        r'(?:\s*(?:aedt|aest|aet|act|acdt|acst|awst))?'
    )
    m = re.search(r'(?:offer ends?|online by|join by|available until|valid until|expires?)'
                  r'[\s,]*(' + date_pattern + r')', text_lower)
    if m:
        return m.group(1).strip()
    return "none"


def extract_offer(text):
    """Return {weeks_free, waiting_waive, other, end_date} for an offer block.
    Any field with no match returns the literal string 'none'."""
    text_lower = text.lower()

    # Weeks free
    weeks_free = "none"
    m = re.search(r'(?:up to\s+)?(\d+)\s*weeks?\s*free', text_lower)
    if m:
        weeks_free = f"up to {m.group(1)} weeks free"

    # Waiting period waive â€” must be explicitly tied to the offer
    waiting_waive = "none"
    m = re.search(
        r'(?:skip the\s+)?2\s*&?\s*6\s*month\s*'
        r'(?:waiting\s*periods?|waits?|wait)\s*'
        r'(?:on\s+(?:eligible\s+)?extras|waived?)',
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
        "end_date":         extract_end_date(text),
        "terms_conditions": "none",
    }


# â”€â”€ Helper: find offers on a page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def find_offers_on_page(url, cover_hint=None):
    """Find offer blocks on a single page. cover_hint forces classification."""
    try:
        log.info(f"Scraping: {url}")
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = parse_html(response)

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

            section_text = section.get_text(separator=" ", strip=True)

            # Classify from the offer text first; page hints are only fallback.
            cover_type = detect_cover_type(heading_text)
            if not cover_type:
                cover_type = detect_cover_type(section_text[:300])
            if not cover_type and re.search(r'\bextras\s+(?:products?|only\s+cover)\b', section_text, re.IGNORECASE):
                cover_type = "extras only"
            if not cover_type and re.search(r'\bhospital\s*&?\s*extras\b', section_text, re.IGNORECASE):
                cover_type = "hospital + extras"
            if not cover_type:
                cover_type = cover_hint
            if not cover_type:
                continue

            terms_url = find_terms_url(section, url, section_text, cover_type)
            offer = extract_offer(section_text)
            url_weeks_free = weeks_free_from_terms_url(terms_url)
            if url_weeks_free:
                offer["weeks_free"] = url_weeks_free
            offer["terms_conditions"] = fetch_terms_conditions(terms_url)
            offer["cover_type"]  = cover_type
            offer["terms_url"]   = terms_url or "none"
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
    offer_fields = ["weeks_free", "waiting_waive", "other", "end_date", "terms_conditions"]

    def offer_score(offer):
        cover = offer.get("cover_type", "")
        source_page = offer.get("source_page", "")
        terms = offer.get("terms_conditions", "")
        terms_url = offer.get("terms_url", "")
        filled = sum(1 for k in offer_fields if offer.get(k) != "none")
        page_match = 0
        if cover == "extras only" and "/extras-cover" in source_page:
            page_match = 10
        elif cover == "hospital only" and "/hospital-cover" in source_page:
            page_match = 10
        elif cover == "hospital + extras" and (source_page.rstrip("/") in {ROOT_URL, "https://ahm.com.au/offer"}):
            page_match = 5
        if cover == "extras only" and "extras only cover" in terms.lower():
            page_match += 5
        if cover == "extras only" and "extras" in terms_url.lower():
            page_match += 8
        if cover == "hospital + extras" and "hospital and extras" in terms.lower():
            page_match += 5
        if cover == "hospital + extras" and re.search(r'12[-_\s]*weeks?|12w', terms_url.lower()):
            page_match += 5
        return page_match + filled

    for offer in all_offers:
        cover = offer["cover_type"]
        if cover not in by_cover:
            by_cover[cover] = offer
            continue
        existing = by_cover[cover]
        if offer_score(offer) > offer_score(existing):
            by_cover[cover] = offer

    final = []
    for cover_type in COVER_TYPES:
        if cover_type in by_cover:
            offer = by_cover[cover_type]
            offer["offer_detection"] = "PROMOTION DETECTED"
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
    for page in PAGES:
        offers = find_offers_on_page(page["url"], page.get("cover_hint"))
        all_offers.extend(offers)

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