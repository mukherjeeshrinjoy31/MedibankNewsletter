import argparse
from typing import Optional
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
import re

from commons.dataset import DATASET
from commons.tiers import TIER

from ...commons.data import DATE_FORMATS, HEADERS, OZBARGAIN_URL, RSS_FEED_URL
from ...utils.helpers import build_payload, fetch_run_date, fetch_cutoff_date, save_local, upload_to_s3

# ---- Config ------------------------------------------------------
SOURCE = "ozbargain"

# ---- Helper Functions ------------------------------------------------------
class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)
    def get_data(self):
        return ''.join(self.parts).strip()

def strip_html(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()

def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    
    try:
        return datetime.strptime(date_str.strip(), DATE_FORMATS[3])
    except ValueError:
        pass
    
    try:
        return datetime.fromisoformat(date_str.strip())
    except ValueError:
        pass
    print(f"  Warning: unrecognised date format: {date_str!r}")
    return None

NS = {"ozb": OZBARGAIN_URL}

def _ozb_attr(item: ET.Element, tag: str, attr: str) -> str | None:
    el = item.find(f"ozb:{tag}", NS)
    return (el.get(attr) or "").strip() if el is not None else ""

def to_int(val: str) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
        
def parse_vote_count(item: ET.Element) -> dict | None:
    pos = to_int(_ozb_attr(item, "meta", "votes-pos"))
    neg = to_int(_ozb_attr(item, "meta", "votes-neg"))
    return {"votes_pos": pos, "votes_neg": neg, "votes_net": pos - neg}

def parse_category(item: ET.Element) -> str | None:
    el = item.find("category", NS)
    return (el.text or "").strip() if el is not None else ""

def parse_coupon_code(description_text: str) -> str | None:
    # explicit [CODE] in brackets
    m = re.search(r"\[([A-Z0-9_\-]{3,30})\]", description_text)
    if m:
        return m.group(1)
    # "code: ABCDEF" label (case-insensitive label, uppercase value)
    m = re.search(r"(?:promo|coupon|code)[:\s]+([A-Z0-9_\-]{3,30})", description_text, re.I)
    if m:
        candidate = m.group(1)
        if candidate == candidate.upper():
            return candidate
    return None

def is_active(exipry_str: datetime | None) -> bool:
    if exipry_str is None:
        return False
    return exipry_str > datetime.now(timezone.utc) 

# ---- Main Scraping Logic ------------------------------------------------------
def fetch_feed(feed_url: str) -> list[dict]:

    try:
        response = requests.get(feed_url, timeout=10, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching feed {feed_url}: {e}")
        return []
    
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"Error parsing XML from feed {feed_url}: {e}")
        return []

    items = root.findall(".//item")
    if not items:
        print("No <item> elements found in feed.")
        return []
 
    print(f"Found {len(items)} items in feed — applying 7-day cutoff ...")
 
    deals = []
    for item in items:
        def _text(tag: str, _item=item) -> str:
            el = _item.find(tag)
            return (el.text or "").strip() if el is not None else ""
 
        title        = strip_html(_text("title"))
        deal_url     = _text("link") or _text("guid")
        pub_date_str = _text("pubDate")
        description  = strip_html(_text("description"))

        expiry_str = _ozb_attr(item, "meta", "expiry")
        expiry_date = parse_date(expiry_str) if expiry_str else None

        pub_date = parse_date(pub_date_str)
        within_cutoff = pub_date and pub_date >= fetch_cutoff_date(30)
        still_active = is_active(expiry_date)


        if not still_active and not within_cutoff:
            print(f"  Skipped (old &expired): {title}")
            continue

        # deals information
        vote_count      = parse_vote_count(item)
        category        = parse_category(item)
        coupon_code     = parse_coupon_code(description)
 
        destination_url = _ozb_attr(item, "meta", "url")
 
        date_iso = pub_date.isoformat() if pub_date else pub_date_str
        date_str = pub_date.strftime("%-d %B %Y") if pub_date else None
 
        deals.append({
            "title":           title,
            "deal_url":        deal_url,
            "destination_url": destination_url,
            "date_str":        date_str,
            "date_iso":        date_iso,
            "expiry_date":     expiry_date.isoformat() if expiry_date else None,
            "still_active":   still_active,
            **vote_count,
            "category":        category,
            "coupon_code":     coupon_code,
            "description":     description,
        })
        print(f"Fetched complete deal: {title}")
 
    return deals

# ---- Main ------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OzBargain Medibank Deals RSS Scraper")
    parser.add_argument(
        "--local", metavar="DIR", nargs="?", const=".",
        help="Save JSON locally to DIR instead of uploading to S3 (default: current directory)",
    )
    args = parser.parse_args()
 
    print("Starting Medibank deal scrape from OzBargain RSS feed...")
    deals = fetch_feed(RSS_FEED_URL)
 
    if not deals:
        print("No deals found within the cutoff date.")
        exit(1)
 
    print(f"\nSuccessfully scraped {len(deals)} recent Medibank deals.")
 
    payload = build_payload(deals)
 
    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)

def run(local: Optional[str] = None) -> bool:
    print(f"Scraping Medibank deals (OzBargain RSS feed) from: \n  {OZBARGAIN_URL} \n")
    content = fetch_feed()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.DEALS.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        OZBARGAIN_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True

# run "python ama.py --local" to save locally to a "data" directory instead of uploading to S3