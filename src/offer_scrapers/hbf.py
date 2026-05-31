"""
HBF direct offers scraper.

Uses Playwright (headless Chromium) because HBF blocks plain HTTP requests
(returns 403 from datacenter IPs).
"""
import json
import logging
from typing import Optional
import os
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from ..commons.config import MODE_AWS, MODE_LOCAL

from ..commons.dataset import DATASET
from ..commons.offers_data import (
    COVER_TYPES, SOURCE,
    HBF_ROOT_URL, HBF_TERMS_URL, HBF_SCRAPE_PAGES
)
from ..commons.tiers import TIER
from ..utils.offer_helpers import (
    _clean_text, save_locally, update_excel, update_excel_on_s3
)
from ..utils.helpers import build_payload, fetch_run_date, save_current_offer, upload_to_s3, load_last_offer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ---- Config -----------------------------------------------------------------
BRAND           = 'HBF'
LAST_OFFER_FILE = f'data/comp_offer/offer_txt/{SOURCE.HBF.value}_last_offer.txt'
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')


# ---- T&C Extraction ---------------------------------------------------------
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


# ---- Offer Extraction -------------------------------------------------------
def extract_offer(text):
    """Return offer fields for an offer block. HBF-specific waiting waive detection."""
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
    else:
        m = re.search(
            r'(?:serve\s+)?no\s+waits?\s+on\s+(?:eligible\s+)?extras',
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


# ---- Playwright Helpers -----------------------------------------------------
def _fetch_rendered_html(url, page):
    """Use a shared Playwright page to fetch JS-rendered HTML."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log.warning("page.goto timed out for %s: %s — continuing", url, e)

    try:
        page.wait_for_selector("text=/weeks free/i", timeout=10000)
    except Exception:
        pass

    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    return page.content()


# ---- Page Scraping ----------------------------------------------------------
def find_offers_on_page(url, cover_hint=None, page=None, terms_by_cover=None):
    """Find offer blocks on a single page using Playwright."""
    try:
        log.info("Scraping: %s", url)
        if page is None:
            raise RuntimeError("HBF scraper requires a Playwright page")
        html = _fetch_rendered_html(url, page)
        soup = BeautifulSoup(html, "html.parser")

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

            if any(o["cover_type"] == cover_type and o["source_page"] == url
                   for o in offers_found):
                continue

            offers_found.append(offer)
            log.info("  Found offer: %s — %s", cover_type, tag.get_text(strip=True)[:60])

        return offers_found

    except Exception as e:
        log.exception("Failed to scrape %s: %s", url, e)
        return []


def detect_cover_type(text):
    """HBF cover type detection."""
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


# ---- Aggregation ------------------------------------------------------------
def aggregate_offers(all_offers):
    """Deduplicate by cover type. Keep entry with most populated fields."""
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
            has_data = any(
                offer.get(k, "none") != "none"
                for k in ["weeks_free", "waiting_waive", "other", "end_date", "terms_conditions"]
            )
            offer["offer_detection"] = (
                "PROMOTION DETECTED" if has_data else "NO CURRENT PROMOTION FOUND"
            )
        else:
            offer = {
                "cover_type":       cover_type,
                "offer_detection":  "NO CURRENT PROMOTION FOUND",
                "weeks_free":       "none",
                "waiting_waive":    "none",
                "other":            "none",
                "end_date":         "none",
                "terms_conditions": "none",
            }
        offer["channel"] = "direct"
        final.append(offer)

    return final


# ---- Main Scrape ------------------------------------------------------------
def scrape_hbf(local=None):
    """Scrape all HBF pages and return (text, results)."""
    all_offers = []

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
            terms_html = _fetch_rendered_html(HBF_TERMS_URL, browser_page)
            terms_by_cover = extract_hbf_terms_by_cover(terms_html)
            log.info("Loaded HBF T&C sections: %s", ', '.join(terms_by_cover) or 'none')
        except Exception as e:
            log.warning("Could not load HBF T&C page: %s", e)

        for cfg in HBF_SCRAPE_PAGES:
            offers = find_offers_on_page(
                cfg["url"], cfg.get("cover_hint"),
                page=browser_page, terms_by_cover=terms_by_cover
            )
            all_offers.extend(offers)

        browser.close()

    results = aggregate_offers(all_offers)

    current_text = json.dumps(results, ensure_ascii=False)
    mode         = MODE_LOCAL if local else MODE_AWS
    last_offer   = load_last_offer(LAST_OFFER_FILE, mode=mode)
    if last_offer and last_offer == current_text:
        offer_status = "OFFER STATUS: UNCHANGED from last week"
    else:
        offer_status = "OFFER STATUS: NEW or CHANGED this week"
    save_current_offer(current_text, LAST_OFFER_FILE, mode=mode)
    log.info(offer_status)

    run_date = datetime.now(timezone.utc).isoformat()
    lines = [
        f"Source: {SOURCE.HBF.value} | Dataset: {DATASET.DIRECT_OFFERS.value} | Run Date: {run_date}",
        f"{offer_status}",
        "",
        f"{BRAND} Direct Offers (aggregated from {len(HBF_SCRAPE_PAGES)} pages):",
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


# ---- Entrypoint -------------------------------------------------------------
def run(local: Optional[str] = None):
    log.info("Run mode: %s", "local" if local else "S3")
    log.info("=" * 50)
    log.info("Starting scrape: %s / %s", SOURCE.HBF.value, DATASET.DIRECT_OFFERS.value)
    log.info("=" * 50)

    content, results = scrape_hbf(local)     # ✅ pass local
    if not content:
        log.warning("No content found — file will not be saved")
        return False

    payload = build_payload(
        content,
        SOURCE.HBF.value,
        DATASET.DIRECT_OFFERS.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        HBF_ROOT_URL
    )

    if local:
        save_locally(payload, SOURCE.HBF.value, DATASET.DIRECT_OFFERS.value, local)
        update_excel(results, BRAND, local_dir=local)
    else:
        upload_to_s3(payload, is_offer_json=True)
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