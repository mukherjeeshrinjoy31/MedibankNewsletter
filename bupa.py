# bupa.py — Competitor offer scraper for Bupa Health Insurance
# Scrapes direct offer data from bupa.com.au and fills Direct rows in comp_offer.xlsx

import re
import io
import os
import json
import time
import argparse
import feedparser
import openpyxl
import boto3
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from collections import defaultdict
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---- Config ----
SOURCE  = "bupa"
DATASET = "competitor_offers"
TIER    = "phi_industry"
BUCKET  = "p000268ds-comp-offers"
SHEET   = "comp_offer.xlsx"

OFFER_PAGES = [
    {"name": "Bupa Offers",            "url": "https://www.bupa.com.au/offers"},
    {"name": "Bupa Hospital & Extras", "url": "https://www.bupa.com.au/health-insurance/hospital-and-extras-cover"},
    {"name": "Bupa Hospital Only",     "url": "https://www.bupa.com.au/health-insurance/hospital-cover"},
    {"name": "Bupa Extras Only",       "url": "https://www.bupa.com.au/health-insurance/extras-cover"},
]

OFFER_KEYWORDS = ["weeks free", "week free", "waiting period", "waiver", "promo",
                  "offer", "bonus", "discount", "join by", "ends", "new members",
                  "everyday rewards", "gift card", "10weeksfree", "everyday120"]

TC_KEYWORDS = ["new members only", "t&cs apply", "eligibility", "ineligible",
               "fulfilled", "residency", "exclusions apply", "terms and conditions",
               "annual payers", "direct debit", "maintained", "excluding"]

# ---- Regex Patterns ----
WEEKS_PAT    = re.compile(r'(?:up to\s+)?(\d+(?:\+\d+)?)\s*weeks?\s*free', re.I)
WAITING_PAT  = re.compile(r'(\d+)\s*(?:and|&)\s*(\d+)\s*month.*?(?:wait|waiv)', re.I)
WAITING_PAT2 = re.compile(r'(\d+)\s*month.*?(?:wait|waiv)', re.I)
ENDDATE_PAT  = re.compile(r'(?:ends?|until|by|join by)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s*\d{2,4})', re.I)
ENDDATE_PAT2 = re.compile(r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})', re.I)
GIFT_PAT     = re.compile(r'\$[\d,]+\s*(?:everyday rewards(?: dollars)?|rewards dollars?|gift card|eftpos|visa)', re.I)
EDR_PAT      = re.compile(r'collect\s+\$([\d,]+)\s+everyday rewards dollars', re.I)
PROMO_PAT    = re.compile(r'(?:promo(?:tion)?\s*code|use\s+(?:promo\s+)?code|enter\s+code)[:\s]+([A-Z0-9]+)', re.I)

EXCEL_COL_MAP = {
    "weeks_free":    "Offer : Weeks Free",
    "waiting_waive": "Offer : Waiting period waive",
    "other":         "Offer : Other",
    "end_date":      "Offer : End date",
    "tandc":         "Offer : T&C",
}

COVER_TYPE_KEYWORDS = {
    "hospital + extras": ["hospital and extras", "hospital & extras", "combined", "hospital + extras",
                          "hospital and extra", "everyday rewards", "everyday120", "family or couples",
                          "singles cover", "family cover"],
    "hospital only":     ["hospital only", "hospital cover", "hospital-only", "standalone hospital",
                          "hospital product", "6wfhospital"],
    "extras only":       ["extras only", "extras cover", "extras-only", "standalone extras",
                          "extras product", "extras8wf"],
}

# ---- Playwright Scraping ----
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


def fetch_page_playwright(page, url: str) -> BeautifulSoup | None:
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        time.sleep(4)
        # Accept cookies if present
        try:
            page.click("button:has-text('Accept')", timeout=3000)
            time.sleep(2)
        except PWTimeout:
            pass
        html = page.content()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"  ✗ {url}: {e}")
        return None


def parse_tandc_structured(text: str, cover_type: str = "") -> str:
    """Parse raw T&C small print into structured labelled format."""
    lower = text.lower()
    parts = []
    seen_labels = set()

    def add(label, value):
        if label not in seen_labels and value:
            seen_labels.add(label)
            parts.append(f"{label}: {value.strip().title()}")

    # Eligibility
    elig_match = re.search(r'(new members only|new bupa members only|eligible customers?)', lower)
    if elig_match:
        add("Eligibility", elig_match.group(1))

    # Offer period — only from join/directly context, not "available until" (EDR)
    period_match = re.search(r'(?:join\s+directly|join\s+on)\s*(?:combined\s*)?(?:eligible\s*)?(?:hospital[^.]*)?(?:products?\s*)?by\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})', lower)
    if period_match:
        add("Offer Period", f"Join by {period_match.group(1)}")

    # Waiting periods — only for H+E
    if cover_type != "hospital only":
        wait_match = re.search(r'(waive?\s*the\s*\d+\s*(?:and|&)\s*\d+\s*month[^.]*)', lower)
        if wait_match:
            add("Waiting Periods", wait_match.group(1))

    # Fulfilment — only for H+E (10 weeks over 2 years doesn't apply to hospital only)
    if cover_type != "hospital only":
        fulfil_match = re.search(r'(\d+\s*weeks?\s*free\s*applied\s*over\s*[\d\s\w]+)', lower)
        if fulfil_match:
            add("Fulfilment", fulfil_match.group(1))

        # Annual payers note
        annual_match = re.search(r'(\d+\s*years?\s*for\s*annual\s*payers)', lower)
        if annual_match:
            add("Annual Payers", annual_match.group(1))

    # Payment requirement
    pay_match = re.search(r'(direct\s*debit[^.]*)', lower)
    if pay_match:
        add("Payment", pay_match.group(1))

    # Excluded covers
    excl_match = re.search(r'exclu(?:ding|des?|sions?)[:\s]+([^.]{10,})', lower)
    if excl_match:
        add("Excluded", excl_match.group(1))

    return " | ".join(parts) if parts else text[:200]


def extract_tandc_text(soup: BeautifulSoup, cover_type: str) -> str:
    """Extract and structure T&C small print text for a given cover type."""

    if cover_type == "hospital only":
        # Find the container that has 6WFHOSPITAL promo code and grab nearby small print
        for tag in soup.find_all(string=re.compile(r'6WFHOSPITAL', re.I)):
            container = tag.parent
            for _ in range(6):
                container_text = container.get_text(separator=" ", strip=True)
                if "new members" in container_text.lower() or "exclusions" in container_text.lower():
                    cleaned = re.sub(r',?\s*opens?\s+in\s+a\s+new\s+tab', '', container_text, flags=re.I)
                    cleaned = re.sub(r'\*?T&Cs?\s*(?:and\s*exclusions?\s*)?apply\.?', '', cleaned, flags=re.I)
                    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                    if 20 < len(cleaned) < 400:
                        return parse_tandc_structured(cleaned, cover_type)
                if container.parent:
                    container = container.parent
                else:
                    break
        # Fallback — grab any small print without "extras" mention
        found = []
        for tag in soup.find_all(["p", "li", "span"]):
            text = tag.get_text(separator=" ", strip=True)
            text = re.sub(r',?\s*opens?\s+in\s+a\s+new\s+tab', '', text, flags=re.I).strip()
            text = re.sub(r'\*?T&Cs?\s*(?:and\s*exclusions?\s*)?apply\.?', '', text, flags=re.I).strip()
            text = re.sub(r'\s+', ' ', text).strip()
            lower = text.lower()
            if any(kw in lower for kw in TC_KEYWORDS) and 20 < len(text) < 250:
                if "extras" not in lower and text not in found:
                    found.append(text)
        if found:
            return parse_tandc_structured(" ".join(list(dict.fromkeys(found))), cover_type)
        return ""

    # For H+E and extras only
    found = []
    for tag in soup.find_all(["p", "li", "span"]):
        text = tag.get_text(separator=" ", strip=True)
        text = re.sub(r',?\s*opens?\s+in\s+a\s+new\s+tab', '', text, flags=re.I).strip()
        text = re.sub(r'\*?T&Cs?\s*(?:and\s*exclusions?\s*)?apply\.?', '', text, flags=re.I).strip()
        text = re.sub(r'\s+', ' ', text).strip()
        lower = text.lower()
        if not any(kw in lower for kw in TC_KEYWORDS):
            continue
        if not (20 < len(text) < 300):
            continue
        if text in found:
            continue
        if cover_type == "hospital + extras":
            if any(k in lower for k in ["combined", "hospital and extras", "hospital + extras", "hospital & extras", "extras"]):
                found.append(text)
            elif any(k in lower for k in ["new members only", "annual payers"]):
                found.append(text)
        elif cover_type == "extras only":
            if any(k in lower for k in ["extras only", "standalone extras"]):
                found.append(text)

    if not found:
        return ""

    combined = " ".join(list(dict.fromkeys(found)))
    return parse_tandc_structured(combined, cover_type)


def extract_offer_blocks(soup: BeautifulSoup) -> list[str]:
    found = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "span", "div"]):
        text = tag.get_text(separator=" ", strip=True)
        if any(kw in text.lower() for kw in OFFER_KEYWORDS):
            if 20 < len(text) < 600 and text not in found:
                found.append(text)
    return found[:30]


def scrape_rss() -> list[str]:
    print("  Fetching Bupa offers via Google News RSS...")
    rss_url = "https://news.google.com/rss/search?q=Bupa+health+insurance+offer+weeks+free+Australia&hl=en-AU&gl=AU&ceid=AU:en"
    feed = feedparser.parse(rss_url)
    entries = []
    for entry in feed.entries[:10]:
        entries.append(f"{entry.title} | {entry.link} | {entry.get('published', '')}")
    print(f"  ✓ Found {len(entries)} RSS articles")
    return entries


def scrape_all_pages() -> tuple[list[str], dict]:
    print("--- Bupa Scraper ---")
    all_blocks = []
    tandc_by_cover = defaultdict(list)

    # Map each page to its specific cover type for T&C extraction
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
            for page in OFFER_PAGES:
                print(f"  Fetching {page['name']}...")
                soup = fetch_page_playwright(pw_page, page["url"])
                if soup:
                    blocks = extract_offer_blocks(soup)
                    all_blocks.extend(blocks)
                    # Only extract T&C for the cover types relevant to this page
                    for ct in PAGE_COVER_MAP.get(page["name"], []):
                        text = extract_tandc_text(soup, ct)
                        if text:
                            tandc_by_cover[ct].append(text)
                    print(f"  ✓ {page['name']}: {len(blocks)} offer blocks found")
                else:
                    print(f"  ✗ {page['name']}: failed")
                time.sleep(2)
        finally:
            browser.close()

    # Always supplement with RSS
    rss_blocks = scrape_rss()
    all_blocks.extend(rss_blocks)

    # Take first unique T&C per cover type
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
        other_parts.append(f"Everyday Rewards: {', '.join(edr_parts[1:])}" if len(edr_parts) > 1 else "Everyday Rewards: $300–$600 Everyday Rewards Dollars")
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
        "tandc":         "",
    }


def detect_cover_type(text: str) -> str | None:
    lower = text.lower()
    for cover_type, keywords in COVER_TYPE_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return cover_type
    return None


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
        # Skip incomplete fragments — must have weeks_free OR (other AND end_date)
        if not parsed["weeks_free"] and not (parsed["other"] and parsed["end_date"]):
            continue
        # Normalize key: strip dollar amounts, dates and promo codes from other
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
        parsed["tandc"] = tandc
        grouped[cover_type].append(parsed)

    return grouped


def merge_offers(offers: list[dict]) -> dict:
    seen = set()
    unique_offers = []
    for offer in offers:
        key = (offer["weeks_free"], offer["other"], offer["end_date"])
        if key not in seen and any([offer["weeks_free"], offer["waiting_waive"], offer["other"], offer["end_date"]]):
            seen.add(key)
            unique_offers.append(offer)

    if not unique_offers:
        return {"weeks_free": "", "waiting_waive": "", "other": "", "end_date": "", "tandc": ""}

    if len(unique_offers) == 1:
        return unique_offers[0]

    # Split into primary (has weeks free) and secondary
    primary = next((o for o in unique_offers if o["weeks_free"]), unique_offers[0])
    secondary = [o for o in unique_offers if o is not primary]

    merged = {
        "weeks_free":    primary["weeks_free"],
        "waiting_waive": primary["waiting_waive"],
        "other":         primary["other"],
        "end_date":      primary["end_date"],
        "tandc":         primary.get("tandc", ""),
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


# ---- Excel Helpers ----
def _header_index(ws) -> dict:
    idx = {}
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.strip() in EXCEL_COL_MAP.values():
                idx[cell.value.strip()] = cell.column - 1
        if len(idx) == len(EXCEL_COL_MAP):
            break
    return idx


def fill_excel(wb: openpyxl.Workbook, structured_offers: dict) -> None:
    ws = wb["table"]
    col_idx = _header_index(ws)

    for row in ws.iter_rows(min_row=2):
        brand_val   = str(row[0].value or "").strip().upper()
        cover_val   = str(row[1].value or "").strip().lower()
        channel_val = str(row[2].value or "").strip().lower()

        if brand_val != "BUPA" or channel_val != "direct":
            continue

        # Always clear first to avoid stale data from previous runs
        for field, col_name in EXCEL_COL_MAP.items():
            if col_name in col_idx:
                row[col_idx[col_name]].value = None

        offers_for_cover = structured_offers.get(cover_val, [])
        if not offers_for_cover:
            weeks_col = EXCEL_COL_MAP["weeks_free"]
            if weeks_col in col_idx:
                row[col_idx[weeks_col]].value = "No current offer"
            continue

        merged = merge_offers(offers_for_cover)
        for field, col_name in EXCEL_COL_MAP.items():
            if col_name in col_idx:
                value = merged.get(field)
                row[col_idx[col_name]].value = value if value else None

    print("✓ Filled BUPA Direct rows in Excel")


# ---- S3 Helpers ----
def update_on_s3(structured_offers: dict) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    key = f"raw/excel/{SHEET}"
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    wb = openpyxl.load_workbook(io.BytesIO(obj["Body"].read()))
    fill_excel(wb, structured_offers)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=buf.read(),
        ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    print(f"✓ Updated: s3://{BUCKET}/{key}")


def update_excel_local(structured_offers: dict, directory: str = ".") -> None:
    src = os.path.join(directory, SHEET)
    if not os.path.exists(src):
        print(f"⚠ {src} not found — skipping Excel update")
        return
    wb = openpyxl.load_workbook(src)
    fill_excel(wb, structured_offers)
    wb.save(src)
    print(f"✓ Updated locally: {src}")


# ---- Output Helpers ----
def build_payload(content: str) -> dict:
    return {
        "source":     SOURCE,
        "tier":       TIER,
        "dataset":    DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url":        "https://www.bupa.com.au/offers",
        "content":    content,
    }


def save_local(payload: dict, directory: str = ".") -> None:
    os.makedirs(directory, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{SOURCE}_{DATASET}_{date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✓ Saved locally: {path}")


def upload_json_to_s3(payload: dict) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"raw/json/{SOURCE}_{DATASET}_{date}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"✓ Uploaded JSON: s3://{BUCKET}/{key}")


# ---- Main ----
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/competitors",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    blocks, tandc_by_cover = scrape_all_pages()
    print(f"\n✓ T&C text found for: {list(tandc_by_cover.keys())}")
    structured_offers = build_structured_offers(blocks, tandc_by_cover)
    print(f"\n✓ Structured offers found for: {list(structured_offers.keys())}")

    content = "\n\n".join(blocks)
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
        update_excel_local(structured_offers, args.local)
    else:
        upload_json_to_s3(payload)
        update_on_s3(structured_offers)