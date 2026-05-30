# bupa.py — Competitor offer scraper for Bupa Health Insurance

import logging
import re
import os
import time
from typing import Optional
from bs4 import BeautifulSoup
from collections import defaultdict
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from ..commons.dataset import DATASET
from ..commons.tiers import TIER
from ..utils.helpers import build_payload, fetch_run_date, upload_to_s3
from ..utils.offer_helpers import (
    detect_cover_type, extract_offer_blocks, make_browser_context, save_locally,
    scrape_rss, update_excel, update_excel_on_s3
)
from ..commons.offers_data import (
    BUPA_OFFER_PAGES, BUPA_OFFER_URL, ENDDATE_PAT2, EXTRAS_ONLY,
    HOSPITAL_EXTRAS, HOSPITAL_ONLY, TC_KEYWORDS,
    WAITING_PAT, WAITING_PAT2, WEEKS_PAT, SOURCE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ---- Config ----
BRAND           = "Bupa"
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')

# ---- Regex Patterns ----
ENDDATE_PAT = re.compile(r'(?:ends?|until|by|join by)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s*\d{2,4})', re.I)
GIFT_PAT    = re.compile(r'\$[\d,]+\s*(?:everyday rewards(?: dollars)?|rewards dollars?|gift card|eftpos|visa)', re.I)
EDR_PAT     = re.compile(r'collect\s+\$([\d,]+)\s+everyday rewards dollars', re.I)
PROMO_PAT   = re.compile(r'(?:promo(?:tion)?\s*code|use\s+(?:promo\s+)?code|enter\s+code)[:\s]+([A-Z0-9]+)', re.I)

COVER_TYPE_KEYWORDS = {
    HOSPITAL_EXTRAS: ["hospital and extras", "hospital & extras", "combined", "hospital + extras",
                      "hospital and extra", "everyday rewards", "everyday120", "family or couples",
                      "singles cover", "family cover"],
    HOSPITAL_ONLY:   ["hospital only", "hospital cover", "hospital-only", "standalone hospital",
                      "hospital product", "6wfhospital"],
    EXTRAS_ONLY:     ["extras only", "extras cover", "extras-only", "standalone extras",
                      "extras product", "extras8wf"],
}


def fetch_page_playwright(page, url: str) -> BeautifulSoup | None:
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(4)
        try:
            page.click("button:has-text('Accept')", timeout=3000)
            time.sleep(2)
        except PWTimeout:
            pass
        html = page.content()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


def parse_tandc_structured(text: str, cover_type: str = "") -> str:
    lower = text.lower()
    parts = []
    seen_labels = set()

    def add(label, value):
        if label not in seen_labels and value:
            seen_labels.add(label)
            parts.append(f"{label}: {value.strip().title()}")

    elig_match = re.search(r'(new members only|new bupa members only|eligible customers?)', lower)
    if elig_match:
        add("Eligibility", elig_match.group(1))

    period_match = re.search(r'(?:join\s+directly|join\s+on)\s*(?:combined\s*)?(?:eligible\s*)?(?:hospital[^.]*)?(?:products?\s*)?by\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})', lower)
    if period_match:
        add("Offer Period", f"Join by {period_match.group(1)}")

    if cover_type != "hospital only":
        wait_match = re.search(r'(waive?\s*the\s*\d+\s*(?:and|&)\s*\d+\s*month[^.]*)', lower)
        if wait_match:
            add("Waiting Periods", wait_match.group(1))

    if cover_type != "hospital only":
        fulfil_match = re.search(r'(\d+\s*weeks?\s*free\s*applied\s*over\s*[\d\s\w]+)', lower)
        if fulfil_match:
            add("Fulfilment", fulfil_match.group(1))

        annual_match = re.search(r'(\d+\s*years?\s*for\s*annual\s*payers)', lower)
        if annual_match:
            add("Annual Payers", annual_match.group(1))

    pay_match = re.search(r'(direct\s*debit[^.]*)', lower)
    if pay_match:
        add("Payment", pay_match.group(1))

    excl_match = re.search(r'exclu(?:ding|des?|sions?)[:\s]+([^.]{10,})', lower)
    if excl_match:
        add("Excluded", excl_match.group(1))

    return " | ".join(parts) if parts else text[:200]


def extract_tandc_text(soup: BeautifulSoup, cover_type: str) -> str:
    found = []
    for tag in soup.find_all(["p", "li", "span"]):
        text = tag.get_text(separator=" ", strip=True)
        text = re.sub(r',?\s*opens?\s+in\s+a\s+new\s+tab', '', text, flags=re.I).strip()
        text = re.sub(r'T&Cs?\s*(?:apply\.?)?', '', text, flags=re.I).strip()
        text = re.sub(r'\s+', ' ', text).strip()
        lower = text.lower()
        if not any(kw in lower for kw in TC_KEYWORDS):
            continue
        if not (20 < len(text) < 300):
            continue
        if text in found:
            continue

        if cover_type == "hospital only":
            if (
                any(k in lower for k in ["hospital only", "hospital-only"]) and "extras" not in lower
                or any(k in lower for k in ["eligible members", "new members"]) and "extras" not in lower
            ):
                found.append(text)

        elif cover_type == "hospital + extras":
            if (
                any(k in lower for k in ["combined", "hospital and extras", "hospital + extras",
                                          "hospital & extras", "hospital and extras"])
                or any(k in lower for k in ["eligible members", "new members", "waiting period"])
            ):
                found.append(text)

        elif cover_type == "extras only":
            if any(k in lower for k in ["extras only", "extras cover"]):
                found.append(text)

    if not found:
        return ""

    combined = " ".join(list(dict.fromkeys(found)))
    return parse_tandc_structured(combined, cover_type)


def scrape_all_pages() -> tuple[list[str], dict]:
    log.info("--- Bupa Scraper ---")
    all_blocks = []
    tandc_by_cover = defaultdict(list)

    PAGE_COVER_MAP = {
        "Bupa Offers":            ["hospital + extras", "hospital only", "extras only"],
        "Bupa Hospital & Extras": ["hospital + extras"],
        "Bupa Hospital Only":     ["hospital only"],
        "Bupa Extras Only":       ["extras only"],
    }

    with sync_playwright() as p:
        browser, ctx = make_browser_context(p)
        pw_page = ctx.new_page()

        try:
            for page in BUPA_OFFER_PAGES:
                log.info("Fetching %s...", page['name'])
                soup = fetch_page_playwright(pw_page, page["url"])
                if soup:
                    blocks = extract_offer_blocks(soup)
                    all_blocks.extend(blocks)
                    for ct in PAGE_COVER_MAP.get(page["name"], []):
                        text = extract_tandc_text(soup, ct)
                        if text:
                            tandc_by_cover[ct].append(text)
                    log.info("%s: %d offer blocks found", page['name'], len(blocks))
                else:
                    log.warning("%s: failed to fetch", page['name'])
                time.sleep(2)
        finally:
            browser.close()

    rss_blocks = scrape_rss(BRAND)
    all_blocks.extend(rss_blocks)

    tandc_final = {ct: texts[0] for ct, texts in tandc_by_cover.items() if texts}

    return all_blocks, tandc_final


# ---- Offer Parsing ----
def parse_offer(text: str) -> dict:
    lower = text.lower()

    weeks = ""
    m = WEEKS_PAT.search(lower)
    if m:
        weeks = m.group(1)

    waiting = ""
    m_wait = WAITING_PAT.search(lower)
    if m_wait:
        waiting = f"{m_wait.group(1)} & {m_wait.group(2)} month waits waived"
    else:
        m_wait2 = WAITING_PAT2.search(lower)
        if m_wait2:
            waiting = f"{m_wait2.group(1)} month waits waived"

    end_date = ""
    m_date = ENDDATE_PAT.search(lower)
    if m_date:
        end_date = m_date.group(1).strip().title()
    else:
        m_date2 = ENDDATE_PAT2.search(lower)
        if m_date2:
            end_date = m_date2.group(1).strip().title()

    other_parts = []
    m_edr = EDR_PAT.search(text)
    if m_edr:
        edr_promo = ""
        edr_date = ""
        m_edr_promo = re.search(r'(?:enter\s+code|code)\s*([A-Z0-9]*EVERYDAY[A-Z0-9]*)', text, re.I)
        if m_edr_promo:
            edr_promo = f"Code: {m_edr_promo.group(1)}"
        m_edr_date = re.search(r'(?:available until|until)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})', text, re.I)
        if m_edr_date:
            edr_date = f"ends {m_edr_date.group(1).strip().title()}"
        edr_parts = ["$300–$600 Everyday Rewards Dollars"]
        if edr_promo:
            edr_parts.append(edr_promo)
        if edr_date:
            edr_parts.append(edr_date)
        other_parts.append(
            f"Everyday Rewards: {', '.join(edr_parts[1:])}" if len(edr_parts) > 1
            else "Everyday Rewards: $300–$600 Everyday Rewards Dollars"
        )
    elif GIFT_PAT.search(text):
        m_gift = GIFT_PAT.search(text)
        other_parts.append(m_gift.group(0).strip())

    m_promo = PROMO_PAT.search(text)
    if m_promo and "everyday" not in m_promo.group(1).lower():
        other_parts.append(f"Code: {m_promo.group(1)}")

    return {
        "weeks_free":    weeks,
        "waiting_waive": waiting,
        "other":         " | ".join(other_parts),
        "end_date":      end_date,
        "terms_conditions": "",
    }


def build_structured_offers(blocks: list[str], tandc_by_cover: dict = {}) -> dict:
    grouped = defaultdict(list)
    seen_parsed = set()
    for block in blocks:
        cover_type = detect_cover_type(block)
        if not cover_type:
            continue
        parsed = parse_offer(block)
        if not any([parsed["weeks_free"], parsed["waiting_waive"],
                    parsed["other"], parsed["end_date"]]):
            continue
        if not parsed["weeks_free"] and not (parsed["other"] and parsed["end_date"]):
            continue
        normalized = re.sub(r'\$[\d,]+', '', parsed["other"])
        normalized = re.sub(r'ends?\s+\d{1,2}\s+\w+\s+\d{4}', '', normalized, flags=re.I)
        normalized = re.sub(r'Code:\s*[A-Z0-9]+', '', normalized, flags=re.I)
        normalized = re.sub(r'\s+', ' ', normalized).strip(" |")
        key = (cover_type, parsed["weeks_free"], normalized)
        if key in seen_parsed:
            continue
        seen_parsed.add(key)
        tandc = tandc_by_cover.get(cover_type, "")
        if tandc and "Offer Period" not in tandc and parsed["end_date"]:
            tandc = tandc + f" | Offer Period: Join By {parsed['end_date']}"
        elif not tandc and parsed["end_date"]:
            tandc = f"Offer Period: Join By {parsed['end_date']}"
        parsed["terms_conditions"] = tandc
        grouped[cover_type].append(parsed)

    return grouped


def merge_bupa_offers(offers: list[dict]) -> dict:
    seen = set()
    unique_offers = []
    for offer in offers:
        key = (offer["weeks_free"], offer["other"], offer["end_date"])
        if key not in seen and any([offer["weeks_free"], offer["waiting_waive"],
                                    offer["other"], offer["end_date"]]):
            seen.add(key)
            unique_offers.append(offer)

    if not unique_offers:
        return {"weeks_free": "", "waiting_waive": "", "other": "", "end_date": "", "terms_conditions": ""}
    if len(unique_offers) == 1:
        return unique_offers[0]

    primary = next((o for o in unique_offers if o["weeks_free"]), unique_offers[0])
    secondary = [o for o in unique_offers if o is not primary]

    merged = {
        "weeks_free":    primary["weeks_free"],
        "waiting_waive": primary["waiting_waive"],
        "other":         primary["other"],
        "end_date":      primary["end_date"],
        "terms_conditions": primary.get("terms_conditions", ""),
    }

    seen_parts = set(filter(None, merged["other"].split(" | ")))
    for sec in secondary:
        parts = []
        sec_other_clean = re.sub(r',?\s*ends\s+\d{1,2}\s+\w+\s+\d{4}', '', sec.get("other", ""), flags=re.I).strip(" ,|")
        if sec_other_clean and not sec_other_clean.rstrip().endswith(':') and sec_other_clean not in seen_parts:
            parts.append(sec_other_clean)
            seen_parts.add(sec_other_clean)
        if sec["weeks_free"]:
            wf = f"{sec['weeks_free']} weeks free"
            if wf not in seen_parts:
                parts.append(wf)
                seen_parts.add(wf)
        if sec["end_date"] and sec["end_date"] not in merged["end_date"]:
            label = "Everyday Rewards" if "everyday" in sec.get("other", "").lower() else "Alt offer"
            merged["end_date"] = f"{merged['end_date']} | {label}: {sec['end_date']}"
        if parts:
            merged["other"] = " | ".join(filter(None, [merged["other"]] + parts))

    return merged


def run(local: Optional[str] = None):
    log.info("Run mode: %s", "local" if local else "S3")
    log.info("=" * 50)
    log.info("Starting scrape: %s / %s", SOURCE.BUPA.value, DATASET.COMPETITOR_OFFERS.value)
    log.info("=" * 50)

    blocks, tandc_by_cover = scrape_all_pages()
    log.info("T&C text found for: %s", list(tandc_by_cover.keys()))
    structured_offers = build_structured_offers(blocks, tandc_by_cover)
    log.info("Structured offers found for: %s", list(structured_offers.keys()))

    content = "\n\n".join(blocks)
    if not content:
        log.warning("No content found — file will not be saved")
        return False

    payload = build_payload(
        content,
        SOURCE.BUPA.value,
        DATASET.COMPETITOR_OFFERS.value,
        fetch_run_date(),
        TIER.PHI.value,
        BUPA_OFFER_URL
    )

    if local:
        save_locally(payload, SOURCE.BUPA.value, DATASET.COMPETITOR_OFFERS.value)
        update_excel(structured_offers, BRAND, merge_fn=merge_bupa_offers)
    else:
        upload_to_s3(payload, is_offer_json=True)
        update_excel(structured_offers, BRAND, merge_fn=merge_bupa_offers)
        if UPDATE_S3_EXCEL:
            update_excel_on_s3(structured_offers, BRAND, merge_fn=merge_bupa_offers)

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