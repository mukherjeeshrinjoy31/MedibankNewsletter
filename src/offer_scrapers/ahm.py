"""
AHM direct offers scraper.

Generalised template: only the BRAND CONFIG block at the top is brand-specific.
The rest of the logic — cover type detection, offer extraction, aggregation,
Excel update — works for any insurer's offer pages.
"""
import json
import logging
from typing import Optional
import requests
import os
import re
from urllib.parse import urljoin
from datetime import datetime, timezone

from ..commons.data import HEADERS
from ..commons.dataset import DATASET
from ..commons.offers_data import AHM_OFFER_URL, AHM_ROOT_URL, AHM_SCRAPE_PAGES, COVER_TYPES, SOURCE
from ..commons.tiers import TIER
from ..utils.helpers import build_payload, fetch_run_date, save_current_offer, upload_to_s3
from ..utils.offer_helpers import _clean_text, aggregate_offers, detect_cover_type, extract_offer, parse_html, save_locally, update_excel, update_excel_on_s3, load_last_offer

BRAND           = 'AHM'
LAST_OFFER_FILE = f'offer_files/{SOURCE.AHM.value}_last_offer.txt'
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

log = logging.getLogger(__name__)


def _terms_link_score(href, link_text, cover_type):
    """Score a candidate ahm offer terms link for the current cover type."""
    candidate = f"{href} {link_text}".lower()
    score = 0

    if "/offer/" in candidate:
        score += 5
    if "see terms" in candidate:
        score += 10

    if cover_type == COVER_TYPES[2]:
        if "extras" in candidate:
            score += 80
        if re.search(r"\b8\s*weeks?\b|8-weeks|extras8", candidate):
            score += 40
        if "hospital" in candidate and "extras" not in candidate:
            score -= 80
        if re.search(r"\b12\s*weeks?\b|12-weeks|12w", candidate):
            score -= 30

    elif cover_type == COVER_TYPES[0]:
        if "hospital" in candidate:
            score += 50
        if re.search(r"\b12\s*weeks?\b|12-weeks|12w", candidate):
            score += 40
        if "extras-only" in candidate or COVER_TYPES[2] in candidate:
            score -= 80

    elif cover_type == COVER_TYPES[1]:
        if "hospital" in candidate:
            score += 50
        if "extras-only" in candidate or COVER_TYPES[2] in candidate:
            score -= 80

    return score


def find_terms_url(section, base_url, cover_type=None):
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
        log.warning("Could not render terms from %s: %s", terms_url, e)
        return None


_terms_cache = {}

def fetch_terms_conditions(terms_url):
    if not terms_url:
        return "none"
    if terms_url in _terms_cache:
        return _terms_cache[terms_url]
    try:
        response = requests.get(terms_url, headers=HEADERS, timeout=15)
        if not response.ok:
            log.warning("Skipping terms — HTTP %s: %s", response.status_code, terms_url)
            result = fallback_terms_conditions(terms_url)
            _terms_cache[terms_url] = result
            return result

        soup = parse_html(response)
        page_text = _clean_text(soup.get_text(" ", strip=True))

        terms_text = extract_terms_section(page_text)
        if terms_text:
            _terms_cache[terms_url] = terms_text
            return terms_text

        rendered_text = fetch_rendered_terms_text(terms_url)
        if rendered_text:
            terms_text = extract_terms_section(rendered_text)
            if terms_text:
                _terms_cache[terms_url] = terms_text
                return terms_text

        result = fallback_terms_conditions(terms_url)
        _terms_cache[terms_url] = result
        return result

    except Exception as e:
        log.warning("Could not fetch terms from %s: %s", terms_url, e)
        result = fallback_terms_conditions(terms_url)
        _terms_cache[terms_url] = result
        return result


def find_offers_on_page(url, cover_hint=None):
    """Find offer blocks on a single page. cover_hint forces classification."""
    try:
        log.info("Scraping: %s", url)
        response = requests.get(url, headers=HEADERS, timeout=15)
        if not response.ok:
            log.warning("Skipping %s — HTTP %s", url, response.status_code)
            return []
        soup = parse_html(response)

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

            terms_url = find_terms_url(section, url, cover_type)
            offer = extract_offer(section_text)
            url_weeks_free = weeks_free_from_terms_url(terms_url)
            if url_weeks_free:
                offer["weeks_free"] = url_weeks_free
            offer["terms_conditions"] = fetch_terms_conditions(terms_url)
            offer["cover_type"]  = cover_type
            offer["terms_url"]   = terms_url or "none"
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


def scrape_ahm():
    """Scrape all pages, aggregate by cover type, and return (text, results)."""
    all_offers = []
    for page in AHM_SCRAPE_PAGES:
        offers = find_offers_on_page(page["url"], page.get("cover_hint"))
        all_offers.extend(offers)

    results = aggregate_offers(all_offers, AHM_ROOT_URL, AHM_OFFER_URL)

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
        f"Source: {SOURCE.AHM.value} | Dataset: {DATASET.DIRECT_OFFERS.value} | Run Date: {run_date}",  # ✅ fixed
        f"{offer_status}",
        "",
        f"{BRAND} Direct Offers (aggregated from {len(AHM_SCRAPE_PAGES)} pages):",
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
    log.info("Starting scrape: %s / %s", SOURCE.AHM.value, DATASET.DIRECT_OFFERS.value)
    log.info("=" * 50)

    content, results = scrape_ahm()
    if not content:
        log.warning("No content found — file will not be saved")
        return False

    payload = build_payload(
        content,
        SOURCE.AHM.value,
        DATASET.DIRECT_OFFERS.value,
        fetch_run_date(),
        TIER.MACRO.value,
        AHM_ROOT_URL
    )

    if local:
        save_locally(payload, SOURCE.AHM.value, DATASET.DIRECT_OFFERS.value)
        update_excel(results, BRAND)
    else:
        update_excel(results, BRAND)
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