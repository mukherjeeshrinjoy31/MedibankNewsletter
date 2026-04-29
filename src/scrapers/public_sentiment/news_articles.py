import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from ...commons.tiers import TIER
from ...commons.dataset import DATASET
from ...commons.data import HEADERS, NEWS_KEYWORDS, NEWS_SOURCES
from ...utils.helpers import build_payload, fetch_cutoff_date, upload_to_s3, save_local
from ...utils.html import parse_date, strip_html

ALL_KEYWORDS = [kw.lower() for kws in NEWS_KEYWORDS.values() for kw in kws]

# make sure articles contain both 2 keyword groups
def matches_keywords(text: str, matches: int = 2) -> bool:
    text = text.lower()
    groups_matched = sum(
        any(kw in text for kw in kws) for kws in NEWS_KEYWORDS.values()
    )
    return groups_matched == matches

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

        if pub_date and pub_date < fetch_cutoff_date(7):
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

def run(local: Optional[str] = None) -> bool:
    for source_id, source_cfg in NEWS_SOURCES.items():
        content = scrape_source(source_id, source_cfg)
        if not content:
            print(f"[SKIP] {source_id} — no content to upload.")
            continue

        payload = build_payload(
            content,
            source_id,
            DATASET.NEWS.value,
            datetime.now(timezone.utc).isoformat(),
            TIER.PUBLIC_SENTIMENT.value,
            source_cfg["url"]
        )

        if local:
            save_local(payload)
        else:
            upload_to_s3(payload)
# run "python news_scrape.py --local data" to save locally to a "data" directory instead of uploading to S3 to view the scraped content