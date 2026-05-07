import argparse
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from bs4 import BeautifulSoup
import boto3
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---- Config -----------------------------------------------------------------
BUCKET  = "p000268ds-medibank-intelligence-us"
TIER    = "offers"
DATASET = "finder_health_offers"
SOURCE  = "finder"
URL     = "https://www.finder.com.au/health-insurance"

BRANDS = {
    "medibank": "Medibank",
    "ahm":      "ahm",
    "bupa":     "Bupa",
    "nib":      "nib",
    "hcf":      "HCF",
    "hbf":      "HBF",
}


# Shared quiz params — encode the "average Australian" profile
QUIZ_PARAMS = {
    "lifestage":   "Any",
    "state":       "VIC",
    "INCOME_TIER": "base_tier",
    "DOB_MAIN":    "1990-01-01",
    "quizId":      "25f6d5b4-be64-46da-b4ce-1049bbd4a546",
}

# Per-cover-type params — only what differs from QUIZ_PARAMS.
# covercategory is omitted for extras only
COVER_TYPES = {
    "hospital + extras": {"covertype": "Combined", "covercategory": "basic"},
    "hospital only":     {"covertype": "Hospital", "covercategory": "basic"},
    "extras only":       {"covertype": "Extras"},
}

BASE_RESULTS_URL = "https://www.finder.com.au/health-insurance/health-insurance-results"

# ---- Compiled regex patterns ------------------------------------------------
WEEKS_FREE_PAT  = re.compile(r'\d+\s*(?:\+\d+\s*)?weeks?\s*free', re.I)
WAITING_PAT     = re.compile(r'\d+\s*(?:and\s*\d+\s*)?month.*?wait|waived waiting|no waiting period|waits waived', re.I)
GIFT_CARD_PAT   = re.compile(r'\$\d+\s*[\w\s]*?\b(?:gift\s*card|e-gift)', re.I)
OTHER_KEYWORDS  = re.compile(r'loyalty|reward|discount|bonus|cashback|cash\s*back|voucher|prize|store|e-gift', re.I)
PRICE_PREFIX_PAT = re.compile(r'^\$?\d+(?:\.\d+)?\s*(?:per\s+\w+\s*)?', re.I)
SENTENCE_SPLIT  = re.compile(r'(?<=[.!?])\s+')


def build_url(cover_params: dict) -> str:
    """Build results URL by merging shared QUIZ_PARAMS with cover-specific params."""
    params = {**QUIZ_PARAMS, **cover_params}
    return f"{BASE_RESULTS_URL}?{urlencode(params)}#quiz-results-table"


# ---- Helpers ----------------------------------------------------------------
def make_browser_context(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
        locale="en-AU",
        timezone_id="Australia/Melbourne",
        extra_http_headers={"Accept-Language": "en-AU,en;q=0.9"},
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return browser, ctx


# ---- Core Functions ---------------------------------------------------------
def load_results_page(page, cover_params: dict):
    url = build_url(cover_params)
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(3)

    try:
        page.click("button:has-text('Accept')", timeout=4000)
        time.sleep(1)
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
                time.sleep(2)
                return True
    except Exception:
        pass
    return False


def filter_by_provider(page, brand_label: str) -> bool:
    try:
        reset_provider_filters(page)

        search_input = page.wait_for_selector("input.searchInput[placeholder='Search for a provider']", timeout=10000)
        search_input.click()
        search_input.fill("")
        search_input.type(brand_label, delay=80)
        time.sleep(2.5)

        label = (page.query_selector(f"label:has-text('{brand_label}')") or
                 page.query_selector(f"label:has-text('{brand_label.lower()}')"))

        if not label:
            return False

        label.scroll_into_view_if_needed()
        label.click()
        time.sleep(3)
        return True
    except Exception:
        return False


def clear_provider_filter(page, url: str):
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    time.sleep(2)


def parse_offer_text(raw_text: str) -> dict:
    lower = raw_text.lower()
 
    # Weeks free
    weeks = ""
    m = re.search(r'(?:up to\s+)?(\d+(?:\+\d+)?)\s*weeks?\s*free', lower)
    if m:
        weeks = m.group(1)
 
    # Waiting period waive
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
 
    # Offer end date
    end_date = ""
    date_match = re.search(r'(?:ends?|until|by)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})', lower)
    if date_match:
        end_date = date_match.group(1)
    else:
        date_match2 = re.search(r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})', lower)
        if date_match2 and any(y in lower for y in ["offer ends", "ends", "join by"]):
            end_date = date_match2.group(1)
 
    # Gift card, extracted independently so it isn't missed when it shares a sentence with weeks free
    gift_card = ""
    gift_match = re.search(r'\$(\d+)\s*(?:[\w\s]*?)\b(?:gift\s*card|e-gift)', lower)
    if gift_match:
        gift_card = f"${gift_match.group(1)} gift card"
 
    # Other, full sentences containing offer keywords, excluding weeks-free, waiting-period,
    # and gift-card sentences (gift card is already captured above as a structured value).
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
            continue  # already captured as gift_card
        if OTHER_KEYWORDS.search(sent):
            cleaned = PRICE_PREFIX_PAT.sub("", sent).strip()
            if cleaned:
                other_sentences.append(cleaned)
 
    other_parts = []
    if gift_card:
        other_parts.append(gift_card)
    if other_sentences:
        other_parts.append(" ".join(other_sentences))
 
    return {
        "weeks_free": weeks,
        "waiting_waive": waiting,
        "other": " | ".join(other_parts),
        "offer_ends": end_date
    }


def extract_offers(page, cover_type_name: str, cover_params: dict) -> list:
    results = []
    base_url = build_url(cover_params)

    for brand_key, search_name in BRANDS.items():
        applied = filter_by_provider(page, search_name)
        if not applied:
            results.append({
                "brand": brand_key,
                "cover_type": cover_type_name,
                "weeks_free": "",
                "waiting_waive": "",
                "other": "",
                "offer_ends": ""
            })
            clear_provider_filter(page, base_url)
            continue

        time.sleep(2)
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table tr")

        offer_data = {
            "brand": brand_key,
            "cover_type": cover_type_name,
            "weeks_free": "",
            "waiting_waive": "",
            "other": "",
            "offer_ends": ""
        }

        if rows and len(rows) > 1:
            first_row_text = rows[1].get_text(" ", strip=True)
            offer_data.update(parse_offer_text(first_row_text))

        results.append(offer_data)
        clear_provider_filter(page, base_url)
        time.sleep(1.5)

    return results


def run() -> list:
    all_offers = []
    with sync_playwright() as p:
        browser, ctx = make_browser_context(p)
        page = ctx.new_page()

        try:
            for cover_key, cover_params in COVER_TYPES.items():
                print(f"Scraping {cover_key}...")
                load_results_page(page, cover_params)
                offers = extract_offers(page, cover_key, cover_params)
                all_offers.extend(offers)
        except Exception as e:
            print(f"[error] {e}")
            raise
        finally:
            browser.close()

    return all_offers


# ---- Output -----------------------------------------------------------------
def build_payload(content: list[dict]) -> dict:
    return {
        "source": SOURCE,
        "tier": TIER,
        "dataset": DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "aggregator_offers": content
    }


def save_local(payload: dict, directory: str = ".") -> None:
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{run_date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}")


def upload_to_s3(payload: dict) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    key = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")


# ---- Main -------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Finder Health Insurance Scraper")
    parser.add_argument("--local", metavar="DIR", nargs="?", const=".", help="Save locally")
    args = parser.parse_args()

    content_list = run()
    payload = build_payload(content_list)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)