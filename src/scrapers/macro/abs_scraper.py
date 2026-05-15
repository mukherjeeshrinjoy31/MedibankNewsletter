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

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ...commons.data import MACRO_NOISE_TAGS, MACRO_URLS
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_run_date, save_local, upload_to_s3

source = "abs"

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
    for tag in soup.find_all(MACRO_NOISE_TAGS):
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
# Entrypoint
# ---------------------------------------------------------------------------

def scrape_page(url: str) -> dict:
    """Scrape a single ABS page and upload it to S3. Returns the payload."""
    html = fetch_page(url)
    return extract_text(html)

def run(local: Optional[str] = None) -> bool:
    print("Scraping multiple ABS statistical release pages")
    for url, slug, dataset in MACRO_URLS:
        log.info("--- Starting: %s ---", slug)
        content = scrape_page(url)
        print(f"\nExtracted {len(content):,} characters of text.")
        payload = build_payload(
            content,
            source,
            dataset,
            fetch_run_date(),
            TIER.MACRO.value,
            url  
        )
        if local:
            save_local(payload)
        else:
            upload_to_s3(payload)

if __name__ == "__main__":
    run(local=True)