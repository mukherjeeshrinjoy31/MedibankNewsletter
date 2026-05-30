"""
Finder Health Insurance aggregator scraper.
Scrapes direct offer data from finder.com.au and fills Aggregator rows in comp_offer.xlsx.
"""
import io
import json
import logging
import os
import re
import time
from typing import Optional
from urllib.parse import urlencode

import pdfplumber
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from ..commons.dataset import DATASET
from ..commons.offers_data import BRANDS, COVER_CATEGORY, EXTRAS_ONLY, HOSPITAL_EXTRAS, HOSPITAL_ONLY, SOURCE, FINDER_URL
from ..commons.data import HCF_URL 
from ..utils.helpers import build_payload, fetch_run_date, upload_to_s3
from ..utils.offer_helpers import make_browser_context, save_locally, update_excel, update_excel_on_s3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

# ---- Config -----------------------------------------------------------------
TIER_EXCEL      = "excel"
BRAND           = "Finder"
UPDATE_S3_EXCEL = os.getenv('UPDATE_S3_EXCEL', '1').strip().lower() not in ('0', 'false', 'no')

QUIZ_PARAMS = {
    "lifestage":   "Any",
    "state":       "VIC",
    "INCOME_TIER": "base_tier",
    "DOB_MAIN":    "1990-01-01",
    "quizId":      "25f6d5b4-be64-46da-b4ce-1049bbd4a546",
}

COVER_TYPES = {
    HOSPITAL_EXTRAS: {"covertype": "Combined", "covercategory": COVER_CATEGORY},
    HOSPITAL_ONLY:     {"covertype": "Hospital", "covercategory": COVER_CATEGORY},
    EXTRAS_ONLY:       {"covertype": "Extras"}
}

BASE_RESULTS_URL       = "https://www.finder.com.au/health-insurance/health-insurance-results"
FINDER_REWARDS_URL     = "https://www.finder.com.au/finder-rewards"
HCF_LOYALTY_PHRASE     = "hcf loyalty"
HCF_MEMBERS_OFFERS_URL = "https://www.hcf.com.au/members/members-offers-and-discounts"

REWARDS_COVER = {
    "hospital & extras": HOSPITAL_EXTRAS,
    "hospital + extras": HOSPITAL_EXTRAS,
    "hospital only":     HOSPITAL_ONLY,
    "extras only":       EXTRAS_ONLY,
}

# ---- Compiled regex patterns ------------------------------------------------
WEEKS_FREE_PAT   = re.compile(r'\d+\s*(?:\+\d+\s*)?weeks?\s*free', re.I)
WAITING_PAT      = re.compile(r'\d+\s*(?:and\s*\d+\s*)?month.*?wait|waived waiting|no waiting period|waits waived', re.I)
GIFT_CARD_PAT    = re.compile(r'\$\d+\s*[\w\s]*?\b(?:gift\s*card|e-gift)', re.I)
OTHER_KEYWORDS   = re.compile(r'loyalty|reward|discount|bonus|cashback|cash\s*back|voucher|prize|store|e-gift', re.I)
PRICE_PREFIX_PAT = re.compile(r'^\$?\d+(?:\.\d+)?\s*(?:per\s+\w+\s*)?', re.I)
SENTENCE_SPLIT   = re.compile(r'(?<=[.!?])\s+')

BOILERPLATE_PATTERNS = [
    r'Go to Site',
    r'View details',
    r'Compare product selection',
    r'Compare loading',
    r'loading',
    r'\[View details\]',
    r'\|\s*loading\s*\|',
]

TC_END_BOILERPLATE = re.compile(
    r'(?:'
    r'All\s+Rights\s+Reserved'
    r'|©\s*\d{4}\s+Hive\s+Empire'
    r'|Terms\s+of\s+service\s+Privacy'
    r'|ABN\s+\d+'
    r'|Level\s+\d+,\s+\d+\s+York\s+St'
    r'|Australia\s+Canada\s+United\s+Kingdom\s+United\s+States'
    r')',
    re.I
)


# ---- URL Builder ------------------------------------------------------------
def build_url(cover_params: dict) -> str:
    params = {**QUIZ_PARAMS, **cover_params}
    return f"{BASE_RESULTS_URL}?{urlencode(params)}#quiz-results-table"


# ---- Core Scraping ----------------------------------------------------------
def load_results_page(page, cover_params: dict):
    url = build_url(cover_params)
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    time.sleep(5)
    try:
        page.click("button:has-text('Accept')", timeout=4000)
        time.sleep(5)
    except PWTimeout:
        pass
    try:
        page.wait_for_selector("table tr", timeout=15000)
    except PWTimeout:
        pass


def reset_provider_filters(page):
    try:
        for text in ["All providers", "All Providers", "All health insurers", "All"]:
            all_label = page.query_selector(f"label:has-text('{text}')")
            if all_label:
                all_label.scroll_into_view_if_needed()
                all_label.click()
                time.sleep(3)
                return True
    except Exception:
        pass
    return False


def filter_by_provider(page, brand_label: str) -> bool:
    try:
        reset_provider_filters(page)
        search_input = page.wait_for_selector(
            "input.searchInput[placeholder='Search for a provider']", timeout=10000
        )
        search_input.click()
        search_input.fill("")
        search_input.type(brand_label, delay=80)
        time.sleep(5)
        label = (page.query_selector(f"label:has-text('{brand_label}')") or
                 page.query_selector(f"label:has-text('{brand_label.lower()}')"))
        if not label:
            return False
        label.scroll_into_view_if_needed()
        label.click()
        time.sleep(5)
        return True
    except Exception:
        return False


def clear_provider_filter(page, url: str):
    if reset_provider_filters(page):
        return
    log.warning("Could not reset filter via click — reloading page")
    page.goto(url, timeout=45000, wait_until="domcontentloaded")
    time.sleep(5)


def parse_offer_text(raw_text: str) -> dict:
    for pattern in BOILERPLATE_PATTERNS:
        raw_text = re.sub(pattern, '', raw_text, flags=re.I)
    cleaned = re.sub(r'\s*\|\s*', ' | ', raw_text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    lower = cleaned.lower()

    weeks = ""
    m = re.search(r'(?:up to\s+)?(\d+(?:\+\d+)?)\s*weeks?\s*free', lower)
    if m:
        weeks = m.group(1)

    waiting = ""
    m_wait = re.search(r'(\d+)\s*and\s*(\d+)\s*month', lower)
    if m_wait:
        waiting = f"{m_wait.group(1)} and {m_wait.group(2)} month waits waived"
    else:
        m_wait2 = re.search(r'(\d+)\s*month.*?(?:wait|extra)', lower)
        if m_wait2:
            waiting = f"{m_wait2.group(1)} month waits waived"
    if not waiting and any(x in lower for x in ["waived waiting", "no waiting period", "waits waived"]):
        waiting = "waiting period waived"

    end_date = ""
    date_match = re.search(r'(?:ends?|until|by)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})', lower)
    if date_match:
        end_date = date_match.group(1)
    else:
        date_match2 = re.search(r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})', lower)
        if date_match2 and any(y in lower for y in ["offer ends", "ends", "join by"]):
            end_date = date_match2.group(1)

    gift_card = ""
    gift_match = re.search(r'\$(\d+)\s*(?:[\w\s]*?)\b(?:gift\s*card|e-gift)', lower)
    if gift_match:
        gift_card = f"${gift_match.group(1)} gift card"

    sentences = SENTENCE_SPLIT.split(raw_text.strip())
    other_sentences = []
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if WEEKS_FREE_PAT.search(sent):
            continue
        if WAITING_PAT.search(sent):
            continue
        if GIFT_CARD_PAT.search(sent):
            continue
        if OTHER_KEYWORDS.search(sent):
            cleaned_sent = PRICE_PREFIX_PAT.sub("", sent).strip()
            if cleaned_sent:
                other_sentences.append(cleaned_sent)

    other_parts = []
    if gift_card:
        other_parts.append(gift_card)
    if other_sentences:
        other_parts.append(" ".join(other_sentences))

    return {
        "weeks_free":       weeks,
        "waiting_waive":    waiting,
        "other":            " | ".join(other_parts),
        "end_date":         end_date,
        "terms_conditions": "",
    }


def extract_offers(page, cover_type_name: str, cover_params: dict) -> list:
    results = []
    base_url = build_url(cover_params)

    for brand_key, search_name in BRANDS.items():
        applied = filter_by_provider(page, search_name)
        offer_data = {
            "brand":            brand_key,
            "cover_type":       cover_type_name,
            "cover_category":   cover_params.get("covercategory", ""),
            "weeks_free":       "",
            "waiting_waive":    "",
            "other":            "",
            "end_date":         "",
            "terms_conditions": "",
        }
        if applied:
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("table tr")
            if rows and len(rows) > 1:
                first_row_text = rows[1].get_text(" ", strip=True)
                offer_data.update(parse_offer_text(first_row_text))
        else:
            log.warning("Could not filter %s", brand_key)

        results.append(offer_data)
        clear_provider_filter(page, base_url)

    return results


# ---- Finder Rewards ---------------------------------------------------------
def scrape_reward_detail_tc(page, detail_url: str) -> str:
    try:
        log.info("Scraping T&C from: %s", detail_url)
        page.goto(detail_url, timeout=30000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("h1, h2, h3", timeout=10000)
        except PWTimeout:
            pass

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)
        full_text = re.sub(r'\s+', ' ', full_text)

        sentinel = TC_END_BOILERPLATE.search(full_text)
        if sentinel:
            full_text = full_text[:sentinel.start()]

        label_pat = re.compile(
            r'(Eligibility Requirements?|Eligibility|Excluded Covers?|Payment Requirement|Reward Fulfilment Date|Stackable Offer)\s*:\s*',
            re.I
        )
        positions = [(m.group(1), m.end()) for m in label_pat.finditer(full_text)]

        if not positions:
            log.warning("No labelled T&C fields found at %s", detail_url)
            return "See Finder Rewards page for full T&Cs"

        seen_labels = set()
        parts = []
        for i, (label, value_start) in enumerate(positions):
            label_norm = label.lower().strip()
            if label_norm in seen_labels:
                continue
            seen_labels.add(label_norm)
            if i + 1 < len(positions):
                next_label_match = label_pat.search(full_text, value_start)
                value = full_text[value_start:next_label_match.start()].strip().rstrip('|').strip()
            else:
                value = full_text[value_start:].strip().rstrip('|').strip()
            if value:
                parts.append(f"{label}: {value}")

        log.info("Extracted %d T&C fields: %s", len(parts), list(seen_labels))
        return " | ".join(parts)

    except Exception as e:
        log.exception("T&C scrape failed: %s", e)
        return ""


def scrape_finder_rewards(page) -> list:
    log.info("Scraping Finder Rewards page...")
    page.goto(FINDER_REWARDS_URL, timeout=45000, wait_until="domcontentloaded")
    time.sleep(2)
    try:
        page.click("button:has-text('Accept')", timeout=5000)
        time.sleep(2)
    except PWTimeout:
        pass

    end_date_pat = re.compile(r'ends?\s+(\d{1,2}\s+[a-z]{3,}\s+\d{4})', re.I)
    get_with_pat = re.compile(r'Get\s+(?:up to\s+)?\$(\d+)', re.I)
    seen = set()

    reward_cards = page.query_selector_all(
        "[data-testid*='rewards_banner_card_list--card'], "
        "[data-niche-group='Health insurance']"
    )
    if not reward_cards:
        reward_cards = page.query_selector_all(".rewards-banner-card-list__card-wrapper")

    log.info("Found %d potential cards - scanning...", len(reward_cards))

    pending = []
    for card in reward_cards:
        try:
            text = card.inner_text()
            if not any(brand in text.lower() for brand in BRANDS.keys()):
                continue
            if "Health Insurance" not in text:
                continue
            amount_match = get_with_pat.search(text)
            if not amount_match:
                continue
            amount_val = f"${amount_match.group(1)}"

            brand_key = None
            for key in BRANDS:
                if key.lower() in text.lower():
                    brand_key = key
                    break
            if not brand_key:
                continue

            detail_url = ""
            redirect = card.get_attribute("data-redirect-url")
            if redirect and redirect != "/finder-rewards":
                detail_url = (
                    "https://www.finder.com.au" + redirect
                    if redirect.startswith("/") else redirect
                )
            if not detail_url:
                link = card.query_selector("a[href*='finder-rewards/']")
                if link:
                    href = link.get_attribute("href") or ""
                    if href and "refer-a-friend" not in href:
                        detail_url = (
                            "https://www.finder.com.au" + href
                            if href.startswith("/") else href
                        )

            cover_type = None
            container_text = text.lower()
            for alias, ct in REWARDS_COVER.items():
                if alias.lower() in container_text:
                    cover_type = ct
                    break

            ed_m = end_date_pat.search(text)
            end_date = ed_m.group(1).strip() if ed_m else ""

            dedup_key = (brand_key, cover_type, amount_val)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            if detail_url:
                log.info("Queued detail URL for %s (%s): %s", brand_key, cover_type, detail_url)
            else:
                log.warning("No detail URL found for %s %s", brand_key, amount_val)

            pending.append({
                "brand_key":        brand_key,
                "cover_type":       cover_type,
                "amount":           amount_val,
                "end_date":         end_date,
                "detail_url":       detail_url,
                "terms_conditions": "",
            })
        except Exception:
            continue

    log.info("Collected %d unique reward cards. Starting T&C pass...", len(pending))

    url_to_tc: dict = {}
    for entry in pending:
        url = entry["detail_url"]
        if not url:
            continue
        if url not in url_to_tc:
            url_to_tc[url] = scrape_reward_detail_tc(page, url)
        entry["terms_conditions"] = url_to_tc[url]

    rewards = []
    for entry in pending:
        rewards.append({
            "brand_key":        entry["brand_key"],
            "cover_type":       entry["cover_type"],
            "amount":           entry["amount"],
            "end_date":         entry["end_date"],
            "terms_conditions": entry["terms_conditions"],
        })
        log.info("Found Finder Reward: %s | %s | %s | ends %s",
                 entry["brand_key"], entry["cover_type"],
                 entry["amount"], entry["end_date"])

    log.info("Total rewards found: %d", len(rewards))
    return rewards


def annotate_with_finder_rewards(offers: list, rewards: list) -> list:
    reward_pat_cache = {}
    for offer in offers:
        other_col    = offer.get("other", "")
        end_date_col = offer.get("end_date", "")
        if not other_col:
            continue
        for reward in rewards:
            if offer["brand"] != reward["brand_key"]:
                continue
            amount           = reward["amount"]
            end_date         = reward["end_date"]
            terms_conditions = reward.get("terms_conditions", "")
            tag              = "Finder Rewards"

            if amount not in reward_pat_cache:
                reward_pat_cache[amount] = re.compile(re.escape(amount) + r'\s*REWARD', re.I)
            pat = reward_pat_cache[amount]

            if pat.search(other_col) and tag not in other_col and tag not in end_date_col:
                other_col = pat.sub(lambda mo: f"{mo.group(0)} ({tag})", other_col)
                offer["other"] = other_col
                offer["end_date"] = end_date_col + f" | {tag}: {end_date}" if end_date else end_date_col
                if terms_conditions:
                    existing  = offer.get("terms_conditions", "")
                    finder_tc = f"Finder Reward: {terms_conditions}"
                    offer["terms_conditions"] = (existing + " | " + finder_tc).lstrip(" | ") if existing else finder_tc
    return offers


# ---- HCF Loyalty T&C --------------------------------------------------------
def scrape_hcf_loyalty_tc(page) -> str:
    log.info("Navigating to HCF members offers page: %s", HCF_MEMBERS_OFFERS_URL)
    try:
        page.goto(HCF_MEMBERS_OFFERS_URL, timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        try:
            page.click("button:has-text('Accept')", timeout=4000)
            time.sleep(2)
        except PWTimeout:
            pass

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        tc_url = None
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True).lower()
            href = a["href"]

            if href.startswith("http"):
                full_href = href
            elif href.startswith("/"):
                full_href = HCF_URL + href
            else:
                full_href = href

            if any(kw in text for kw in ["terms and conditions", "terms & conditions", "t&c", "t&cs"]):
                tc_url = full_href
                break
            if any(kw in href.lower() for kw in ["terms-and-conditions", "terms_and_conditions", "tandc", "t-and-c"]):
                tc_url = full_href
                break

        if not tc_url:
            log.warning("No T&C link found on HCF members offers page")
            return ""

        log.info("Found HCF T&C URL: %s", tc_url)

        if tc_url.lower().endswith(".pdf"):
            log.info("Detected PDF — downloading and extracting with pdfplumber...")
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36"
            }
            response = requests.get(tc_url, headers=headers, timeout=30)
            response.raise_for_status()
            pdf_bytes = io.BytesIO(response.content)

            page_texts = []
            with pdfplumber.open(pdf_bytes) as pdf:
                for pdf_page in pdf.pages:
                    w, h = pdf_page.width, pdf_page.height
                    left_text  = pdf_page.within_bbox((0,   0, w/2, h)).extract_text() or ""
                    right_text = pdf_page.within_bbox((w/2, 0, w,   h)).extract_text() or ""
                    page_texts.append(left_text + " " + right_text)

            full_text = " ".join(page_texts)
            full_text = re.sub(r'\s+', ' ', full_text).strip()

            eligibility_start = re.search(r'ELIGIBLE MEMBERS AND MEMBERSHIP TIERS', full_text)
            eligibility_end   = re.search(r'HCF THANK YOU OFFERS AND REWARDS', full_text)
            if eligibility_start and eligibility_end and eligibility_start.start() < eligibility_end.start():
                full_text = full_text[eligibility_start.start():eligibility_end.start()].strip()
                log.info("Eligibility section extracted (%d chars)", len(full_text))
            elif eligibility_start:
                full_text = full_text[eligibility_start.start():].strip()
                log.info("Eligibility section extracted (no end boundary, %d chars)", len(full_text))
            else:
                log.warning("Eligibility section heading not found in PDF — using full text")
        else:
            log.info("Detected HTML page — navigating with Playwright...")
            page.goto(tc_url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)
            try:
                page.wait_for_selector("h1, h2, h3", timeout=10000)
            except PWTimeout:
                pass
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            full_text = soup.get_text(" ", strip=True)
            full_text = re.sub(r'\s+', ' ', full_text).strip()

        sentinel = TC_END_BOILERPLATE.search(full_text)
        if sentinel:
            full_text = full_text[:sentinel.start()].strip()

        if not full_text:
            log.warning("HCF T&C page returned empty content")
            return ""

        log.info("HCF T&C scraped (%d chars)", len(full_text))
        return full_text

    except Exception as e:
        log.exception("HCF loyalty T&C scrape failed: %s", e)
        return ""


def annotate_hcf_loyalty_tc(offers: list, page) -> list:
    hcf_loyalty_offers = any(
        o.get("brand") == "hcf" and HCF_LOYALTY_PHRASE in o.get("other", "").lower()
        for o in offers
    )

    if not hcf_loyalty_offers:
        log.info("No HCF offers contain the loyalty program phrase — skipping HCF loyalty T&C scrape")
        return offers

    log.info("Found HCF offer(s) with loyalty program phrase — scraping T&C...")
    tc_text = scrape_hcf_loyalty_tc(page)

    if not tc_text:
        log.warning("HCF loyalty T&C came back empty; terms_conditions field unchanged")
        return offers

    hcf_tc_entry = f"HCF Loyalty Program T&C: {tc_text}"
    for offer in offers:
        if offer.get("brand") != "hcf":
            continue
        if HCF_LOYALTY_PHRASE not in offer.get("other", "").lower():
            continue
        existing = offer.get("terms_conditions", "")
        offer["terms_conditions"] = (existing + " | " + hcf_tc_entry).lstrip(" | ") if existing else hcf_tc_entry
        log.info("Appended HCF loyalty T&C to offer: brand=hcf, cover_type=%s, cover_category=%s",
                 offer.get("cover_type"), offer.get("cover_category"))

    return offers

# ---- Main Scrape ------------------------------------------------------------
def scrape_finder() -> list:
    all_offers = []
    with sync_playwright() as p:
        browser, ctx = make_browser_context(p)
        page = ctx.new_page()
        try:
            for cover_key, cover_params in COVER_TYPES.items():
                for covercategory in cover_params.get("covercategory", [""]):
                    log.info("Scraping %s...", cover_key)
                    if covercategory:
                        cover_params["covercategory"] = covercategory
                        log.info("cover_params: %s", cover_params)
                    load_results_page(page, cover_params)
                    offers = extract_offers(page, cover_key, cover_params)
                    all_offers.extend(offers)

            finder_rewards = scrape_finder_rewards(page)
            all_offers = annotate_with_finder_rewards(all_offers, finder_rewards)
            all_offers = annotate_hcf_loyalty_tc(all_offers, page)

        except Exception as e:
            log.exception("Scrape failed: %s", e)
            raise
        finally:
            browser.close()

    return all_offers


# ---- Entrypoint -------------------------------------------------------------
def run(local: Optional[str] = None) -> bool:
    log.info("Run mode: %s", "local" if local else "S3")
    log.info("=" * 50)
    log.info("Starting scrape: %s / %s", SOURCE.FINDER.value, DATASET.OFFERS.value)
    log.info("=" * 50)

    content_list = scrape_finder()
    if not content_list:
        log.warning("No content found — file will not be saved")
        return False

    payload = build_payload(
        json.dumps(content_list),
        SOURCE.FINDER.value,
        DATASET.OFFERS.value,
        fetch_run_date(),
        TIER_EXCEL,
        FINDER_URL
    )

    if local:
        save_locally(payload, SOURCE.FINDER.value, DATASET.OFFERS.value)
        update_excel(content_list, BRAND)
    else:
        upload_to_s3(payload, is_offer_json=True)
        if UPDATE_S3_EXCEL:
            update_excel_on_s3(content_list, BRAND)

    log.info("Scrape complete")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Finder Health Insurance Scraper")
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data", help="Save outputs locally")
    args = parser.parse_args()
    run(local=args.local)


if __name__ == "__main__":
    main()