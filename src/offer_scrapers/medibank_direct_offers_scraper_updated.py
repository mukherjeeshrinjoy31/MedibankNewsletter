"""
Medibank direct offers scraper.

Generalised template: only the BRAND CONFIG block at the top is brand-specific.
The rest of the logic - cover type detection, offer extraction, aggregation,
Excel update - works for any insurer's offer pages.
"""
import json
import logging
from typing import Optional
import requests
import os
import re
from datetime import datetime, timezone

from ..commons.data import HEADERS
from ..commons.dataset import DATASET
from ..commons.offers_data import COVER_TYPES, SOURCE, MEDIBANK_ROOT_URL, MEDIBANK_SCRAPE_PAGES, MEDIBANK_OFFER_URL, TERM_HEADINGS, TERMS_STOP_MARKERS
from ..commons.tiers import TIER
from ..utils.helpers import build_payload, fetch_run_date, save_current_offer
from ..utils.offer_helpers import (
    _clean_text, aggregate_offers, detect_cover_type, extract_offer,
    extract_end_date, parse_html, save_locally, update_excel,
    update_excel_on_s3, load_last_offer
)

BRAND           = 'Medibank'
LAST_OFFER_FILE = f'offer_files/{SOURCE.MEDIBANK.value}_last_offer.txt'
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

def extract_page_terms(soup):
    """Extract full relevant T&C blocks from the page's Things you should know section."""
    page_text = soup.get_text("\n", strip=True)
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
            h for h in TERM_HEADINGS if h.lower() == heading.lower()
        )
        terms_by_heading.setdefault(canonical_heading, []).append(block)

    return terms_by_heading


def terms_for_cover_type(terms_by_heading, cover_type):
    """Return T&C text relevant to the detected offer cover type."""
    if cover_type == COVER_TYPES[0]:
        wanted = ["Hospital and Extras offer:"]
    elif cover_type == COVER_TYPES[2]:
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


def find_offers_on_page(url, cover_hint=None):
    """Find offer blocks on a single page. cover_hint forces classification."""
    try:
        log.info("Scraping: %s", url)
        response = requests.get(url, headers=HEADERS, timeout=15)
        if not response.ok:
            log.warning("Skipping %s — HTTP %s", url, response.status_code)
            return []
        soup = parse_html(response)
        page_terms = extract_page_terms(soup)

        offers_found = []

        for tag in soup.find_all(["h1", "h2", "h3", "p", "div"]):
            heading_text = tag.get_text(strip=True).lower()

            if "weeks free" not in heading_text and "gift card" not in heading_text:
                continue
            if len(heading_text) > 500:
                continue

            section = tag.find_parent()
            if not section:
                continue

            section_text = section.get_text(separator=" ", strip=True)

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

            if any(o["cover_type"] == cover_type and o["source_page"] == url
                   for o in offers_found):
                continue

            offers_found.append(offer)
            log.info("  Found offer: %s — %s", cover_type, tag.get_text(strip=True)[:60])

        return offers_found

    except Exception as e:
        log.exception("Failed to scrape %s: %s", url, e)
        return []


def scrape_medibank():
    """Scrape all pages, aggregate by cover type, and return (text, results)."""
    all_offers = []
    for page in MEDIBANK_SCRAPE_PAGES:
        offers = find_offers_on_page(page["url"], page.get("cover_hint"))
        all_offers.extend(offers)

    results = aggregate_offers(all_offers, MEDIBANK_ROOT_URL, MEDIBANK_OFFER_URL)

    current_text = json.dumps(results, ensure_ascii=False)
    last_offer   = load_last_offer(LAST_OFFER_FILE)
    if last_offer and last_offer == current_text:
        offer_status = "OFFER STATUS: UNCHANGED from last week"
    else:
        offer_status = "OFFER STATUS: NEW or CHANGED this week"
    save_current_offer(current_text, LAST_OFFER_FILE)
    log.info(offer_status)

    run_date = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Source: {SOURCE.MEDIBANK.value} | Dataset: {DATASET.DIRECT_OFFERS.value} | Run Date: {run_date}",
        f"{offer_status}",
        "",
        f"{BRAND} Direct Offers (aggregated from {len(MEDIBANK_SCRAPE_PAGES)} pages):",
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


def run(local: Optional[str] = None):
    log.info("Run mode: %s", "local" if local else "S3")
    log.info("=" * 50)
    log.info("Starting scrape: %s / %s", SOURCE.MEDIBANK.value, DATASET.DIRECT_OFFERS.value)
    log.info("=" * 50)

    content, results = scrape_medibank()
    if not content:
        log.warning("No content found — file will not be saved")
        return False

    payload = build_payload(
        content,
        SOURCE.MEDIBANK.value,
        DATASET.DIRECT_OFFERS.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        MEDIBANK_ROOT_URL
    )

    if local:
        save_locally(payload, SOURCE.MEDIBANK.value, DATASET.DIRECT_OFFERS.value)
    else:
        update_excel(results, BRAND)
        if UPDATE_S3_EXCEL:
            update_excel_on_s3(results, BRAND)

    log.info("Scrape complete")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data", help="Save outputs locally")
    args = parser.parse_args()
    run(local=args.local)


if __name__ == "__main__":
    main()