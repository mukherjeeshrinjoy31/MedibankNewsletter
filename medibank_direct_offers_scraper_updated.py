"""
Medibank direct offers scraper.

Generalised template: only the BRAND CONFIG block at the top is brand-specific.
The rest of the logic - cover type detection, offer extraction, aggregation,
Excel update - works for any insurer's offer pages.
"""
import json
import logging
import requests
import sys
import os
import re
import io
import openpyxl
from datetime import datetime, timezone
from bs4 import BeautifulSoup


# BRAND CONFIG - the only per-brand block
SOURCE          = 'medibank'
BRAND           = 'Medibank'      # must match Brand column in Excel
TIER            = 'medibank_specific'
DATASET         = 'direct_offers'
BUCKET          = 'p000268ds-comp-offers'
LAST_OFFER_FILE = f'{SOURCE}_last_offer.txt'
EXCEL_FILE      = 'comp_offer.xlsx'
AWS_REGION      = os.getenv('AWS_REGION', 'ap-southeast-2')
S3_EXCEL_KEY    = os.getenv('S3_EXCEL_KEY', f'raw/excel/{EXCEL_FILE}')
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')
LOG_FILE        = f'{SOURCE}_direct_offers.log'
ROOT_URL        = 'https://www.medibank.com.au'

# Pages to scrape. Each page can optionally include a "cover_hint" - useful
# when the page is dedicated to one cover type and the heading text alone
# can't be relied on.
PAGES = [
    {"url": "https://www.medibank.com.au"},
    {"url": "https://www.medibank.com.au/health-insurance/hospital-cover/"},
    {"url": "https://www.medibank.com.au/health-insurance/extras-cover/", "cover_hint": "extras only"},
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

TERM_HEADINGS = [
    "Hospital and Extras offer:",
    "12 weeks free terms:",
    "2&6 month waits waived on extras terms:",
    "Live Better rewards points terms:",
    "Live Better rewards terms:",
    "Extras only offer:",
    "Weeks free terms:",
    "Live Better points terms:",
]

TERMS_STOP_MARKERS = [
    "Health members save 15%",
    "Ready for your next adventure?",
    "2 months free pet insurance",
    "Get 2 months free on Medibank Life Insurance",
    "Request a call back",
    "COVID-19 Health Assist",
    "Insurance Health insurance",
]


# Logging
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


def _clean_text(text):
    text = fix_mojibake(text)
    return re.sub(r'\s+', ' ', text).strip()


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
        "\u00e2\u0082\u00ac": "â‚¬",
        "\u00c2\u00a0": " ",
        "\u00c2": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    if not any(marker in text for marker in ("Ã‚", "Ã¢", "ÃŽ", "Â¥", "â‚¬", "Â±")):
        return text
    try:
        return text.encode("windows-1252").decode("utf-8")
    except UnicodeError:
        return text


def parse_html(response):
    """Parse Medibank pages as UTF-8 to avoid characters like Ã‚ and Ã¢Â€Â™."""
    html = response.content.decode("utf-8", errors="replace")
    return BeautifulSoup(html, "html.parser")


def extract_page_terms(soup):
    """Extract full relevant T&C blocks from the page's Things you should know section."""
    page_text = fix_mojibake(soup.get_text("\n", strip=True))
    marker = re.search(r"things you should know", page_text, flags=re.IGNORECASE)
    if not marker:
        return {}

    terms_text = page_text[marker.end():]
    for stop_marker in TERMS_STOP_MARKERS:
        stop = re.search(re.escape(stop_marker), terms_text, flags=re.IGNORECASE)
        if stop:
            terms_text = terms_text[:stop.start()]
            break

    terms_by_heading = {}

    heading_regex = "|".join(re.escape(h) for h in TERM_HEADINGS)
    matches = list(re.finditer(heading_regex, terms_text, flags=re.IGNORECASE))

    for i, match in enumerate(matches):
        heading = match.group(0)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(terms_text)

        block = _clean_text(terms_text[start:end])
        block = re.sub(r"^[^\w]*(?=\w)", "", block).strip()

        canonical_heading = next(
            h for h in TERM_HEADINGS
            if h.lower() == heading.lower()
        )
        terms_by_heading.setdefault(canonical_heading, []).append(block)

    return terms_by_heading


def terms_for_cover_type(terms_by_heading, cover_type):
    """Return T&C text relevant to the detected offer cover type."""
    if cover_type == "hospital + extras":
        wanted = ["Hospital and Extras offer:"]
    elif cover_type == "extras only":
        wanted = ["Extras only offer:"]
    else:
        wanted = []

    blocks = []
    for heading in wanted:
        heading_blocks = terms_by_heading.get(heading, [])
        if not heading_blocks:
            continue
        blocks.append(heading_blocks[0])
    return "\n\n".join(blocks) if blocks else "none"


def extract_end_date(text):
    """Extract an offer end date from offer copy or matching T&C text."""
    text_lower = _clean_text(text).lower()

    date_pattern = (
        r'\d{1,2}\s+'
        r'(?:january|february|march|april|may|june|july|august|september|october|november|december|'
        r'jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)'
        r'(?:\s+\d{4})?'
        r'(?:\s+\d{1,2}:\d{2}\s*(?:am|pm)?)?'
        r'(?:\s*(?:aedt|aest|aet|act|acdt|acst|awst))?'
    )

    trigger_pattern = (
        r'(?:offer ends?|online by|join by|available until|valid until|expires?|'
        r'cover by|cover from|start eligible .*? cover from|'
        r'join and start .*? cover from|join and maintain .*? cover by)'
    )

    m = re.search(r'(?:' + date_pattern + r')\s*(?:-|\u2013|\u2014|to)\s*(' + date_pattern + r')', text_lower)
    if m:
        return m.group(1).strip()

    m = re.search(
        trigger_pattern + r'[\s,]*' + date_pattern + r'\s*(?:-|\u2013|\u2014|to)\s*(' + date_pattern + r')',
        text_lower
    )
    if m:
        return m.group(1).strip()

    m = re.search(trigger_pattern + r'[\s,]*(' + date_pattern + r')', text_lower)
    if m:
        return m.group(1).strip()

    return "none"


def extract_offer(text):
    """Return offer fields for an offer block.
    Any field with no match returns the literal string 'none'."""
    text_lower = text.lower()

    # Weeks free
    weeks_free = "none"
    m = re.search(r'(?:up to\s+)?(\d+)\s*weeks?\s*free', text_lower)
    if m:
        weeks_free = f"up to {m.group(1)} weeks free"

    # Waiting period waive - must be explicitly tied to the offer
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

    end_date = extract_end_date(text)

    return {
        "weeks_free":       weeks_free,
        "waiting_waive":    waiting_waive,
        "other":            ", ".join(other) if other else "none",
        "end_date":         end_date,
        "terms_conditions": "none",
    }


def find_offers_on_page(url, cover_hint=None):
    """Find offer blocks on a single page. cover_hint forces classification."""
    try:
        log.info(f"Scraping: {url}")
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = parse_html(response)
        page_terms = extract_page_terms(soup)

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

            # Classify the offer's cover type
            cover_type = cover_hint or detect_cover_type(heading_text)
            if not cover_type:
                cover_type = detect_cover_type(section_text[:300])
            if not cover_type:
                continue

            offer = extract_offer(section_text)
            offer["terms_conditions"] = terms_for_cover_type(page_terms, cover_type)
            if offer["end_date"] == "none" and offer["terms_conditions"] != "none":
                offer["end_date"] = extract_end_date(offer["terms_conditions"])
            offer["cover_type"]  = cover_type
            offer["source_page"] = url
            offer["heading"]     = tag.get_text(strip=True)

            # Avoid duplicates on same page (same cover type)
            if any(o["cover_type"] == cover_type and o["source_page"] == url
                   for o in offers_found):
                continue

            offers_found.append(offer)
            log.info(f"  Found offer: {cover_type} - {tag.get_text(strip=True)[:60]}")

        return offers_found

    except Exception as e:
        log.error(f"Failed to scrape {url}: {e}")
        return []


def aggregate_offers(all_offers):
    """Deduplicate by cover type. Keep the entry with the most populated fields."""
    by_cover = {}
    offer_fields = ["weeks_free", "waiting_waive", "other", "end_date", "terms_conditions"]

    def offer_score(offer):
        cover = offer.get("cover_type", "")
        source_page = offer.get("source_page", "")
        filled = sum(1 for k in offer_fields if offer.get(k) != "none")
        page_match = 0
        if cover == "extras only" and "/extras-cover/" in source_page:
            page_match = 10
        elif cover == "hospital only" and "/hospital-cover/" in source_page:
            page_match = 10
        elif cover == "hospital + extras" and source_page.rstrip("/") == ROOT_URL:
            page_match = 5
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


def build_payload(content):
    return {
        'source':     SOURCE,
        'tier':       TIER,
        'dataset':    DATASET,
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'url':        ROOT_URL,
        'content':    content,
    }


def save_locally(payload):
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    filename = f"{SOURCE}_{DATASET}_{date}.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"Saved: {filename}")
    except Exception as e:
        log.error(f"Failed to save file: {e}")


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
        log.warning(f"Excel file not found: {filepath} - skipping update")
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


if __name__ == '__main__':
    log.info("=" * 50)
    log.info(f"Starting scrape: {SOURCE} / {DATASET}")
    log.info("=" * 50)

    content, results = scrape()

    if not content:
        log.warning("No content found - file will not be saved")
    else:
        payload = build_payload(content)
        save_locally(payload)
        update_excel(results)
        if UPDATE_S3_EXCEL:
            update_excel_on_s3(results)

    log.info("Scrape complete")
