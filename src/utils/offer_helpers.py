from datetime import datetime, timezone
import io
import json
import logging
import os
import re

from bs4 import BeautifulSoup
import openpyxl

from ..commons.config import AWS_REGION, BUCKET_COMP_OFFER, EXPECTED_BUCKET_OWNER
from ..commons.offers_data import COVER_TYPES, OFFER_EXCEL_FILE, EXCEL_COL_MAP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)

S3_EXCEL_KEY = os.getenv('S3_EXCEL_KEY', f'raw/excel/{OFFER_EXCEL_FILE}')


def detect_cover_type(text):
    """Determine which cover type the text refers to."""
    t = text.lower()
    has_hospital = "hospital" in t
    has_extras   = "extras"   in t
    if has_hospital and has_extras:
        return COVER_TYPES[0]
    if has_extras and not has_hospital:
        return COVER_TYPES[2]
    if has_hospital and not has_extras:
        return COVER_TYPES[1]
    return None


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

    weeks_free = "none"
    m = re.search(r'(?:up to\s+)?(\d+)\s*weeks?\s*free', text_lower)
    if m:
        weeks_free = f"up to {m.group(1)} weeks free"

    waiting_waive = "none"
    m = re.search(
        r'(?:skip the\s+)?2\s*&?\s*6\s*month\s*'
        r'(?:waiting\s*periods?|waits?|wait)\s*'
        r'(?:on\s+(?:eligible\s+)?extras|waived?)',
        text_lower
    )
    if m:
        waiting_waive = m.group(0).strip()

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


def aggregate_offers(all_offers, root_url, offer_url):
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
        if cover == COVER_TYPES[2] and "/extras-cover" in source_page:
            page_match = 10
        elif cover == COVER_TYPES[1] and "/hospital-cover" in source_page:
            page_match = 10
        elif cover == COVER_TYPES[0] and (source_page.rstrip("/") in {root_url, offer_url}):
            page_match = 5
        if cover == COVER_TYPES[2] and "extras only cover" in terms.lower():
            page_match += 5
        if cover == COVER_TYPES[2] and "extras" in terms_url.lower():
            page_match += 8
        if cover == COVER_TYPES[0] and "hospital and extras" in terms.lower():
            page_match += 5
        if cover == COVER_TYPES[0] and re.search(r'12[-_\s]*weeks?|12w', terms_url.lower()):
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


def load_last_offer(last_offer_file):
    try:
        if os.path.exists(last_offer_file):
            with open(last_offer_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        logger.warning("Could not load last offer: %s", e)
    return None

def save_locally(payload, source, dataset, local_dir="."):
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_dir = os.path.join(local_dir, "data", "offer")      # ✅ data/offer subfolder
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{source}_{dataset}_{date}.json")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        logger.info("Saved: %s", filename)
    except Exception as e:
        logger.exception("Failed to save file: %s", e)


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


def _write_results_to_workbook(wb, results, brand):
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

        if brand_val != brand.lower() or channel_val != "direct":
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


def update_excel(results, brand, filepath=OFFER_EXCEL_FILE):
    """Write Direct-channel results into the matching brand rows."""
    if not os.path.exists(filepath):
        logger.warning("Excel file not found: %s — skipping update", filepath)
        return

    wb = openpyxl.load_workbook(filepath)
    rows_updated = _write_results_to_workbook(wb, results, brand)
    wb.save(filepath)
    logger.info("Excel updated: %d %s Direct row(s) written to %s", rows_updated, brand, filepath)


def update_excel_on_s3(results, brand, bucket=BUCKET_COMP_OFFER, key=S3_EXCEL_KEY):
    """Download comp_offer.xlsx from S3, update this brand's Direct rows, and overwrite it."""
    try:
        import boto3
    except ImportError:
        logger.error("boto3 is not installed - cannot update Excel workbook on S3")
        return

    s3 = boto3.client("s3", region_name=AWS_REGION)
    obj = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=EXPECTED_BUCKET_OWNER)
    wb = openpyxl.load_workbook(io.BytesIO(obj["Body"].read()))
    rows_updated = _write_results_to_workbook(wb, results, brand)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.read(),
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ExpectedBucketOwner=EXPECTED_BUCKET_OWNER,
    )
    logger.info("Excel updated on S3: %d %s Direct row(s) written to s3://%s/%s", rows_updated, brand, bucket, key)