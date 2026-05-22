import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional, List, Set

import requests
import trafilatura

from ...commons.data import HEADERS, NEWS_KEYWORDS, NEWS_SOURCES, WHOLE_WORD_KEYWORDS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_run_date, save_local, upload_to_s3
from ...utils.html import parse_date, strip_html

SOURCE = "news"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyword Matching
# ---------------------------------------------------------------------------

def keyword_found(kw: str, text: str) -> bool:
    """Whole-word matching for short ambiguous keywords, substring for others."""
    if kw in WHOLE_WORD_KEYWORDS:
        return bool(re.search(rf'\b{re.escape(kw)}\b', text))
    return kw in text


def matches_keywords(text: str, matches: int = 1) -> bool:
    """Return True if text matches at least `matches` keyword groups."""
    text = text.lower()
    groups_matched = sum(
        any(keyword_found(kw, text) for kw in kws)
        for kws in NEWS_KEYWORDS.values()
    )
    return groups_matched >= matches


# ---------------------------------------------------------------------------
# Article Fetching
# ---------------------------------------------------------------------------

def fetch_article_text(url: str) -> str:
    """Fetch and extract plain text from a full article page using trafilatura."""
    try:
        response = requests.get(url, timeout=20, headers=HEADERS)
        response.raise_for_status()
        text = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        return text or ""
    except Exception as e:
        logger.warning("Could not fetch article text from %s: %s", url, e)
        return ""


def fetch_feed(feed_url: str) -> List[dict]:
    """Fetch and parse an RSS/Atom feed, returning keyword-matched articles."""
    try:
        response = requests.get(feed_url, timeout=10, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error("Error fetching feed %s: %s", feed_url, e)
        return []

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.error("Error parsing XML from feed %s: %s", feed_url, e)
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

        full_text = fetch_article_text(url)
        combined_text = f"{title} {description} {full_text}"

        if not matches_keywords(combined_text):
            continue

        logger.info("Matched article: %s", title[:80])
        articles.append({
            "title": title,
            "published": pub_date.isoformat() if pub_date else pub_date_str,
            "url": url,
            "body": full_text if full_text else description
        })

    return articles


# ---------------------------------------------------------------------------
# Source Scraping
# ---------------------------------------------------------------------------

def scrape_source(source_id: str, source_config: dict) -> Optional[List[dict]]:
    """Scrape all feeds for a source, deduplicate and return sorted articles."""
    all_articles: List[dict] = []
    seen_urls: Set[str] = set()

    for feed_url in source_config["feeds"]:
        logger.info("Scraping feed: %s", feed_url)
        for article in fetch_feed(feed_url):
            url = article["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            all_articles.append(article)

    if not all_articles:
        logger.warning("No articles found for source: %s", source_id)
        return None

    all_articles.sort(key=lambda x: x["published"], reverse=True)

    return [
        {
            "index": i,
            "title": a["title"],
            "published": a["published"],
            "url": a["url"],
            "body": a["body"]
        }
        for i, a in enumerate(all_articles, start=1)
    ]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape all news sources and upload to S3 or save locally."""
    logger.info("Starting news articles scraper")

    for source_id, source_cfg in NEWS_SOURCES.items():
        content = scrape_source(source_id, source_cfg)

        if not content:
            logger.warning("[SKIP] %s — no content to upload.", source_id)
            continue

        payload = build_payload(
            content,
            source_id,
            DATASET.NEWS.value,
            fetch_run_date(),
            TIER.PUBLIC_SENTIMENT.value,
            source_cfg["url"]
        )

        if local:
            save_local(payload)
        else:
            upload_to_s3(payload)

    return True


if __name__ == "__main__":
    run(local="data")