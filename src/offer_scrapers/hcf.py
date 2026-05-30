# hcf.py — Competitor offer scraper for HCF Health Insurance

import logging
import re
import os
import time
from typing import Optional
from bs4 import BeautifulSoup
from collections import defaultdict

from ..commons.dataset import DATASET
from ..commons.offers_data import (
    ENDDATE_PAT2, EXTRAS_ONLY, HCF_OFFER_PAGES, HCF_OFFER_URL,
    HOSPITAL_EXTRAS, HOSPITAL_ONLY, SOURCE, TC_KEYWORDS,
    WAITING_PAT, WAITING_PAT2, WEEKS_PAT
)
from ..commons.tiers import TIER
from ..utils.helpers import build_payload, fetch_run_date, upload_to_s3
from ..utils.offer_helpers import (
    detect_cover_type, extract_offer_blocks, fetch_page,
    save_locally, scrape_rss, update_excel, update_excel_on_s3
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ---- Config -----------------------------------------------------------------
BRAND           = "HCF"
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')

# ---- Regex Patterns ---------------------------------------------------------
ENDDATE_PAT  = re.compile(r'(?:ends?|until|by|join by|closes?)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s*\d{2,4})', re.I)
ENDDATE_PAT3 = re.compile(r'(?:ends?|until|by|join by|closes?)\s+(\d{1,2}\s+[A-Za-z]+)(?:\s|\.)', re.I)
GIFT_PAT     = re.compile(r'\$[\d,]+\s*(?:digital\s*prepaid\s*mastercard|gift\s*card|e-gift|visa|mastercard|cashback)', re.I)
PROMO_PAT    = re.compile(r'(?:promo(?:tion)?\s*code|use\s+(?:promo\s+)?code|enter\s+code|code)[:\s]+([A-Z0-9]{6,})', re.I)

COVER_TYPE_KEYWORDS = {
    HOSPITAL_EXTRAS: ["hospital and extras", "hospital & extras", "combined",
                      "hospital + extras", "hospital and extra"],
    HOSPITAL_ONLY:   ["hospital only", "hospital cover", "hospital-only",
                      "standalone hospital", "hospital product"],
    EXTRAS_ONLY:     ["extras only", "extras cover", "extras-only",
                      "standalone extras", "extras product"],
}


def scrape_all_pages() -> tuple[list[str], dict]:
    log.info("--- HCF Scraper ---")
    all_blocks = []
    tandc_by_cover = defaultdict(list)

    PAGE_COVER_MAP = {
        "HCF Homepage":             ["hospital + extras", "hospital only", "extras only"],
        "HCF Find Health Insurance":["hospital + extras", "hospital only", "extras only"],
        "HCF Hospital & Extras":    ["hospital + extras"],
        "HCF Hospital Only":        ["hospital only"],
        "HCF Extras Only":          ["extras only"],
    }

    for page in HCF_OFFER_PAGES:
        log.info("Fetching %s...", page['name'])
        soup = fetch_page(page["url"])
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

    rss_blocks = scrape_rss(BRAND)
    all_blocks.extend(rss_blocks)

    tandc_final = {ct: texts[0] for ct, texts in tandc_by_cover.items() if texts}

    return all_blocks, tandc_final


# ---- T&C Extraction ---------------------------------------------------------
def parse_tandc_structured(text: str, cover_type: str = "") -> str:
    lower = text.lower()
    parts = []
    seen_labels = set()

    def add(label, value):
        if label not in seen_labels and value:
            seen_labels.add(label)
            parts.append(f"{label}: {value.strip().title()}")

    elig_match = re.search(r'(new members? only|eligible members?|eligible customers?|australian residents?)', lower)
    if elig_match:
        add("Eligibility", elig_match.group(1))

    period_match = re.search(r'(?:join|take out)(?:\s+eligible)?\s+(?:combined\s+)?(?:hospital[^.]*)?(?:cover\s+)?by\s+(\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?)', lower)
    if period_match:
        date = period_match.group(1).strip()
        if not re.search(r'\d{4}', date):
            date += " 2026"
        add("Offer Period", f"Join by {date}")

    if cover_type != "hospital only":
        wait_match = re.search(r'(waive?\s*the?\s*\d+[-\s]month[^.]*|skip\s*the?\s*\d+[^.]*month[^.]*waiting[^.]*)', lower)
        if wait_match:
            add("Waiting Periods", wait_match.group(1))

    fulfil_match = re.search(r'(?:after|following)\s+(\d+\s*(?:days?|months?|years?))[^.]*(?:free|weeks)', lower)
    if fulfil_match:
        add("Fulfilment", f"After {fulfil_match.group(1)}")

    gift_match = re.search(r'(\$[\d,]+\s*(?:digital\s*prepaid\s*mastercard|gift\s*card|e-gift|mastercard|cashback))', lower)
    if gift_match:
        add("Reward", gift_match.group(1).title())

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


# ---- Offer Parsing ----------------------------------------------------------
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
        else:
            m_date3 = ENDDATE_PAT3.search(lower)
            if m_date3:
                end_date = m_date3.group(1).strip().title() + " 2026"

    other_parts = []
    m_gift = GIFT_PAT.search(text)
    if m_gift:
        other_parts.append(m_gift.group(0).strip())
    m_promo = PROMO_PAT.search(text)
    if m_promo:
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


def merge_hcf_offers(offers: list[dict]) -> dict:
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
            merged["end_date"] = f"{merged['end_date']} | Alt: {sec['end_date']}"
        if parts:
            merged["other"] = " | ".join(filter(None, [merged["other"]] + parts))

    return merged


def run(local: Optional[str] = None):
    log.info("Run mode: %s", "local" if local else "S3")
    log.info("=" * 50)
    log.info("Starting scrape: %s / %s", SOURCE.HCF.value, DATASET.COMPETITOR_OFFERS.value)
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
        SOURCE.HCF.value,
        DATASET.COMPETITOR_OFFERS.value,
        fetch_run_date(),
        TIER.PHI.value,
        HCF_OFFER_URL
    )

    if local:
        save_locally(payload, SOURCE.HCF.value, DATASET.COMPETITOR_OFFERS.value)
        update_excel(structured_offers, BRAND, merge_fn=merge_hcf_offers)
    else:
        upload_to_s3(payload, is_offer_json=True)
        update_excel(structured_offers, BRAND, merge_fn=merge_hcf_offers)
        if UPDATE_S3_EXCEL:
            update_excel_on_s3(structured_offers, BRAND, merge_fn=merge_hcf_offers)

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