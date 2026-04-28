import json
import boto3
import argparse
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re

# ---- Config ------------------------------------------------------
SOURCE = "ozbargain"
DATASET = "deals"
TIER   = "public-sentiment"
URL = "https://www.ozbargain.com.au"
BUCKET = "p000268ds-medibank-intelligence"

RSS_FEED_URL = "https://www.ozbargain.com.au/deals/medibank.com.au/feed"
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=30)

HEADERS = {"User-Agent": "Mozilla/5.0"}

DATE_FORMAT = "%a, %d %b %Y %H:%M:%S %z"

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
        return datetime.strptime(date_str.strip(), DATE_FORMAT)
    except ValueError:
        pass
    
    try:
        return datetime.fromisoformat(date_str.strip())
    except ValueError:
        pass
    print(f"  Warning: unrecognised date format: {date_str!r}")
    return None

NS = {"ozb": "https://www.ozbargain.com.au"}

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
        within_cutoff = pub_date and pub_date >= CUTOFF_DATE
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

# ---- Output Helpers ------------------------------------------------------
def build_payload(content: list[dict]) -> dict:
    return {
        "source": SOURCE,
        "tier": TIER,
        "dataset": DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "content": content
    }

def upload_to_s3(payload: dict) -> None:
    s3  = boto3.client("s3", region_name="us-east-1")
    key = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    s3.put_object(
        Bucket=BUCKET, 
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType='application/json'
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")

def save_local(payload: dict, directory: str = ".") -> None:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}")

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