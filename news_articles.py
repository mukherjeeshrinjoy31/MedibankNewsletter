import json
import boto3
import argparse
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

# ---- Config ------------------------------------------------------
TIER = "public-sentiment"
DATASET = "news"
BUCKET = "p000268ds-medibank-intelligence"
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)
SOURCES = {
    "abc": {
        "url": "https://www.abc.net.au/",
        "feeds": [
            "https://www.abc.net.au/news/feed/5470430/rss.xml", # abc top stories
            "https://www.abc.net.au/news/feed/45910/rss.xml", # abc top stories
            "https://www.abc.net.au/news/feed/7112600/rss.xml", # abc health
            "https://www.abc.net.au/news/feed/9167776/rss.xml" # abc health
        ],
    },
    "sbs": {
        "url": "https://www.sbs.com.au/news",
        "feeds": [
            "https://www.sbs.com.au/news/feed", # sbs top stories,
            "https://www.sbs.com.au/feed/news/podcast-rss/headlines-on-health" # sbs health podcast
        ],
    },
    "theguardian": {
        "url": "https://www.theguardian.com/au",
        "feeds": [
            "https://www.theguardian.com/au/rss" # the guardian top stories
        ],
    }
}

# keywords for filtering articles
KEYWORDS = {
    "phi": [
        "medibank", "bupa", "nib", "hcf", "hbf",
        "private health insurance", "health fund", 
        "health cover", "health insurer"
    ],
    "health_tech": [
        "health technology", "digital health", "health ai",
        "medical ai", "health innovation", "medtech",
        "telehealth", "health data", "wearable health",
        "health automation", "clinical ai", "precision medicine"
    ]
}

# ---- Helper Functions ------------------------------------------------------

ALL_KEYWORDS = [kw.lower() for kws in KEYWORDS.values() for kw in kws]

DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S %z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ"
]

class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)
    def get_data(self):
        return ''.join(self.parts).strip()

def strip_html(raw: str)   -> str:
    stripper = MLStripper()
    stripper.feed(raw or "")
    return stripper.get_data()

def parse_date(date_str: str) -> datetime | None:
    if not date_str:
        return None
    for date_format in DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str.strip(), date_format)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

# make sure articles contain both 2 keyword groups
def matches_keywords(text: str, matches: int = 2) -> bool:
    text = text.lower()
    groups_matched = sum(
        any(kw in text for kw in kws) for kws in KEYWORDS.values()
    )
    return groups_matched == matches

# ---- Main Scraping Logic ------------------------------------------------------
def fetch_feed(feed_url: str) -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(feed_url, timeout=10, headers=headers)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching feed {feed_url}: {e}")
        return []
    
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print(f"Error parsing XML from feed {feed_url}: {e}")
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = root.findall('.//item') or root.findall('.//atom:entry', ns)

    articles = []
    for item in items:
        def text(tag: str, _item=item) -> str:
            el = _item.find(tag)
            if el is None:
                el = _item.find(f"atom:{tag}", ns)
            return (el.text or '').strip() if el is not None else ''
        
        title = strip_html(text('title'))
        description = strip_html(text('description') or text('summary'))
        url = text('link') or text("id")
        pub_date_str = text('pubDate') or text('published') or text('updated')

        pub_date = parse_date(pub_date_str)

        if pub_date and pub_date < CUTOFF_DATE:
            continue

        if not matches_keywords(f"{title} {description}"):
            continue

        articles.append({
            "title": title,
            "description": description,
            "url": url,
            "pub_date": pub_date.isoformat() if pub_date else pub_date_str
            })
    return articles

def scrape_source(source_id: str, source_config: dict) -> str:
    all_articles: list[dict] = []
    seen_urls: set[str] = set()

    for feed_url in source_config["feeds"]:
        print(f"Scraping feed {feed_url} for source {source_id}...")
        for article in fetch_feed(feed_url):
            url = article["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            all_articles.append(article)
    
    if not all_articles:
        print(f"No articles found for source {source_id}.")
        return None
    
    # sort articles by publication date (newest first)
    all_articles.sort(key=lambda x: x["pub_date"], reverse=True)

    run_date = datetime.now(timezone.utc).isoformat()
    lines = [f"Source: {source_id}", f"Run Date: {run_date} | Articles: {len(all_articles)} | Scraped: {run_date}", ""]

    for i, article in enumerate(all_articles, start=1):
        lines.append(f"{i}. {article['title']}")
        lines.append(f"Published: {article['pub_date']}")
        lines.append(f"Source: {article['url']}")
        lines.append(f"Content:{article['description']}")
        lines.append(" \n ")
    
    return " \n ".join(lines)

# ---- Output Helper ------------------------------------------------------
def build_payload(source_id: str, source_url:str, content: str) -> dict:
    return {
        "source": source_id,
        "tier": TIER,
        "dataset": DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url": source_url,
        "content": content
    }

def upload_to_s3(payload: dict) -> None:
    s3  = boto3.client("s3", region_name="ap-southeast-2")
    key = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    s3.put_object(
        Bucket=BUCKET, 
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType='application/json'
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")

def save_local(payload: dict, directory: str = ".") -> None:
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{run_date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}")

# ---- Main Execution ------------------------------------------------------
if __name__ == "__main__":
 
    parser = argparse.ArgumentParser(description="RSS news scraper — PHI / health / AI")
    parser.add_argument(
        "--local",
        metavar="DIR",
        nargs="?",
        const=".",
        help="Save JSON files locally to DIR instead of uploading to S3 (default: current directory)",
    )
    args = parser.parse_args()
 
    for source_id, source_cfg in SOURCES.items():
        content = scrape_source(source_id, source_cfg)
        if not content:
            print(f"[SKIP] {source_id} — no content to upload.")
            continue
 
        payload = build_payload(source_id, source_cfg["url"], content)
 
        if args.local:
            save_local(payload, args.local)
        else:
            upload_to_s3(payload)


# run "python news_scrape.py --local data" to save locally to a "data" directory instead of uploading to S3 to view the scraped content