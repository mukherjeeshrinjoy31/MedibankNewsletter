"""
ABS Scraper
-----------
Fetches multiple ABS statistical release pages, extracts clean plain text,
and uploads a structured JSON record per page to S3.

Pages scraped:
    - Consumer Price Index (CPI)
    - Labour Force, Australia
    - Labour Force, Australia, Detailed

Output schema per file:
    source      : "abs"
    tier        : "macro"
    scraped_at  : ISO 8601 UTC timestamp
    url         : source page URL
    content     : clean plain text extracted from the page

S3 paths:
    raw/macro/abs_cpi_{YYYY-MM-DD}.json
    raw/macro/abs_labour_force_{YYYY-MM-DD}.json
    raw/macro/abs_labour_force_detailed_{YYYY-MM-DD}.json
"""

import json
import logging
import re
from datetime import datetime, timezone

import boto3
import requests
from bs4 import BeautifulSoup


session = boto3.Session(profile_name='RMIT-ResearchAdmin-851166494260')
s3 = session.client('s3', region_name='us-east-1')
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Each entry: (page URL, S3 key slug, dataset name)
PAGES = [
    (
        "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation"
        "/consumer-price-index-australia/latest-release",
        "abs_cpi",
        "cpi",
    ),
    (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment"
        "/labour-force-australia/latest-release",
        "abs_labour_force",
        "labour_force",
    ),
    (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment"
        "/labour-force-australia-detailed/latest-release",
        "abs_labour_force_detailed",
        "labour_force_detailed",
    ),
]

S3_BUCKET = "p000268ds-medibank-intelligence-us"
S3_REGION = "us-east-1"

# Tags that contribute no readable content and produce noise if included
_NOISE_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "form", "button"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_page(url: str, timeout: int = 30) -> str:
    """Download the page HTML and return it as a string."""
    headers = {
        # Identify as a browser so the ABS server does not block the request.
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-AU,en;q=0.9",
    }
    log.info("Fetching %s", url)
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()  # raises HTTPError for 4xx/5xx responses
    log.info("HTTP %s — %.1f KB received", response.status_code, len(response.content) / 1024)
    return response.text


def extract_text(html: str) -> str:
    """
    Parse HTML with BeautifulSoup and return clean plain text.

    Strategy:
      1. Remove noise tags (scripts, nav, footer, etc.) before extraction
         so their hidden text is never included.
      2. Use get_text(separator=" ") to replace tag boundaries with spaces
         rather than concatenating words together.
      3. Strip embedded JSON blobs left behind by ABS interactive charts
         (both array and object forms).
      4. Normalise whitespace: collapse multiple spaces/newlines into a
         single space and strip leading/trailing whitespace.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove tags that contribute no meaningful content
    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    raw_text = soup.get_text(separator=" ")

    # Strip embedded JSON left behind by ABS interactive charts.
    # The page embeds two kinds of chart data as inline text:
    #   - JSON arrays:  [["Jun-23", ...], [[100], [119.2], ...]]
    #   - JSON objects: [{"value":"EBRF","x_value":"26","y_value":"107.1",...}]
    # Neither is natural language; both would confuse an LLM.
    raw_text = re.sub(r'\[[^\[\]]*\]', " ", raw_text)   # innermost arrays/objects first
    raw_text = re.sub(r'\[[^\[\]]*\]', " ", raw_text)   # second pass for nested brackets

    # Collapse all whitespace sequences (spaces, tabs, newlines) into a
    # single space and strip the result.
    clean = " ".join(raw_text.split())

    log.info("Extracted %d characters of plain text", len(clean))
    return clean


# ---------------------------------------------------------------------------
# S3 Upload
# ---------------------------------------------------------------------------

def build_s3_key(slug: str, date: datetime) -> str:
    """Return the S3 object key for a given slug and date."""
    return f"raw/macro/{slug}_{date.strftime('%Y-%m-%d')}.json"


def upload_to_s3(payload: dict, bucket: str, key: str, region: str) -> None:
    """
    Serialise *payload* to JSON and upload it to S3.

    boto3 picks up credentials from the standard AWS credential chain:
    environment variables → ~/.aws/credentials → IAM role — whichever is
    configured locally will be used automatically.
    """
    s3 = session.client("s3", region_name=region)
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    log.info("Uploading to s3://%s/%s", bucket, key)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )
    log.info("Upload complete")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def scrape_page(url: str, slug: str, dataset: str, now: datetime) -> dict:
    """Scrape a single ABS page and upload it to S3. Returns the payload."""
    html = fetch_page(url)
    content = extract_text(html)

    payload = {
        "source": "abs",
        "tier": "macro",
        "dataset": dataset,
        "scraped_at": now.isoformat(),
        "url": url,
        "content": content,
    }

    key = build_s3_key(slug, now)
    upload_to_s3(payload, S3_BUCKET, key, S3_REGION)

    return payload


def run() -> list[dict]:
    """
    Scrape all configured ABS pages and upload each to S3.
    Returns a list of payloads (one per page).
    """
    now = datetime.now(timezone.utc)
    results = []

    for url, slug, dataset in PAGES:
        log.info("--- Starting: %s ---", slug)
        payload = scrape_page(url, slug, dataset, now)
        results.append(payload)

    log.info("All %d pages scraped and uploaded.", len(results))
    return results


if __name__ == "__main__":
    results = run()
    print()
    for r in results:
        slug = r["url"].split("/")[-3].replace("-", "_")
        key = r["url"].split("/")[-3]
        print(f"  url        : {r['url']}")
        print(f"  scraped_at : {r['scraped_at']}")
        print(f"  content    : {len(r['content']):,} chars")
        print(f"  preview    : {r['content'][:120]}")
        print()
