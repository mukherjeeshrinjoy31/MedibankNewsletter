import json
import logging
import os
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional, List, Dict

import boto3
import feedparser
import pdfplumber
import requests

from ..commons.config import AWS_REGION, BUCKET, EXPECTED_BUCKET_OWNER
from ..commons.data import HEADERS, NEWS_KEYWORDS, WHOLE_WORD_KEYWORDS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date Helpers
# ---------------------------------------------------------------------------

def fetch_run_date() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def fetch_cutoff_date(n_days: int) -> datetime:
    """Return UTC datetime n_days ago."""
    return datetime.now(timezone.utc) - timedelta(days=n_days)


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def build_payload(content, source: str, dataset: str, scraped_at: str, tier: str, url) -> dict:
    """Build a standard payload dict for S3 upload or local save."""
    return {
        "source": source,
        "tier": tier,
        "dataset": dataset,
        "scraped_at": scraped_at,
        "url": url,
        "content": content
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def upload_to_s3(payload: dict, is_offer_json: bool = False) -> None:
    """Upload payload JSON to S3."""
    s3  = boto3.client("s3", region_name=AWS_REGION)
    prefix = "raw/offer_json" if is_offer_json else f"raw/{payload['tier']}"
    key = f"{prefix}/{payload['source']}_{payload['dataset']}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
        ExpectedBucketOwner=EXPECTED_BUCKET_OWNER
    )
    logger.info("Uploaded: s3://%s/%s", BUCKET, key)


def save_local(payload: dict) -> str:
    """Save payload to data/{tier}/{source}_{dataset}_{run_date}.json."""
    tier_dir = os.path.join("data", payload["tier"])
    os.makedirs(tier_dir, exist_ok=True)

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{payload['source']}_{payload['dataset']}_{run_date}.json"
    path = os.path.join(tier_dir, filename)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    logger.info("Saved locally: %s", path)
    return path


# ---------------------------------------------------------------------------
# HTTP Helpers
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        time.sleep(1)
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        logger.error("Error fetching %s: %s", url, e)
        return None


def download_pdf(pdf_url: str) -> Optional[bytes]:
    """Download a PDF from a URL and return its bytes."""
    try:
        response = requests.get(pdf_url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        logger.info("Downloaded PDF (%d KB)", len(response.content) / 1024)
        return response.content
    except Exception as e:
        logger.error("Failed to download PDF from %s: %s", pdf_url, e)
        return None


def fetch_article_links(search_tag_url: str, base_url: str, url: str) -> List[str]:
    """Scrape a page and return unique article links matching the search tag."""
    soup = fetch_url(url)
    if not soup:
        logger.error("Could not fetch article links from: %s", url)
        return []

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if search_tag_url in href:
            full_url = base_url + href if href.startswith("/") else href
            if full_url not in links:
                links.append(full_url)

    logger.info("Found %d articles total", len(links))
    return links


# ---------------------------------------------------------------------------
# Text Helpers
# ---------------------------------------------------------------------------

def clean_text(text: str, boiler_plate: List[str]) -> str:
    """Remove boilerplate phrases and normalise whitespace."""
    for phrase in boiler_plate:
        text = text.replace(phrase, "")
    return " ".join(text.split()).strip()

def keyword_found(kw: str, text: str) -> bool:
    if kw in WHOLE_WORD_KEYWORDS:
        return bool(re.search(rf'\b{re.escape(kw)}\b', text))
    return kw in text

def matches_keywords(text: str) -> bool:
    """Return True if text matches at least one keyword group."""
    text = text.lower()
    return any(keyword_found(kw, text) for kw in NEWS_KEYWORDS)


def is_boilerplate(text: str, boilerplate_patterns: List[str]) -> bool:
    """Return True if text matches any boilerplate regex pattern."""
    t = text.lower().strip()
    return any(re.match(pat, t) for pat in boilerplate_patterns)


def parse_date(text: str) -> Optional[datetime]:
    """Extract and parse a date from free text."""
    match = re.search(r"(\d{1,2})[\s\n]+([A-Za-z]+)[\s\n]+(\d{4})", text)
    if match:
        raw = f"{match.group(1)} {match.group(2)} {match.group(3)}"
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def build_content_list(articles: List[Dict]) -> List[Dict]:
    """Format a list of article dicts into a structured content list."""
    return [
        {
            "index": i,
            "headline": article["headline"],
            "published": article["pub_date"] or "unknown",
            "source": article["url"],
            "body": article["body"],
        }
        for i, article in enumerate(articles, start=1)
    ]


# ---------------------------------------------------------------------------
# PDF Helpers
# ---------------------------------------------------------------------------

def extract_pdf_text(filepath: str) -> str:
    """Extract and clean text from a downloaded PDF file."""
    try:
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return " ".join(text.split()).strip()
    except Exception as e:
        logger.error("PDF extraction error: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Offer File Helpers
# ---------------------------------------------------------------------------

def load_last_offer(last_offer_file: str) -> Optional[str]:
    """Load last week's offer text from file."""
    try:
        if os.path.exists(last_offer_file):
            with open(last_offer_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        logger.warning("Could not load last offer: %s", e)
    return None


def save_current_offer(offer_text: str, path: str) -> None:
    """Save this week's offer text to file for next week's comparison."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(offer_text)
    except Exception as e:
        logger.warning("Could not save current offer: %s", e)


# ---------------------------------------------------------------------------
# Google News RSS
# ---------------------------------------------------------------------------

def fetch_google_news_rss(rss_url: str, header: str, cutoff_days: int) -> str:
    """Fetch recent news articles from a Google News RSS feed."""
    content = f"{header}\n\n"
    cutoff = fetch_cutoff_date(cutoff_days)

    try:
        feed = feedparser.parse(rss_url)

        if not feed.entries:
            logger.warning("No entries found in Google News RSS feed.")
            return (content + "No news found via Google News RSS.").strip()

        articles_added = 0
        for entry in feed.entries:
            pub_date_str = entry.get("published", "")
            try:
                pub_date = parsedate_to_datetime(pub_date_str)
                if pub_date < cutoff:
                    continue
            except Exception:
                pass

            content += f"Title: {entry.title}\n"
            content += f"Link: {entry.link}\n"
            content += f"Published: {pub_date_str}\n\n"
            articles_added += 1

        logger.info("Found %d articles via Google News RSS", articles_added)

    except Exception as e:
        logger.error("Google News RSS failed: %s", e)
        content += f"Google News RSS failed: {e}\n"

    return content.strip()