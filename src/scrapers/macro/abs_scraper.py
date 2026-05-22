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
"""

import logging
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ...commons.data import MACRO_NOISE_TAGS, MACRO_URLS
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_run_date, save_local, upload_to_s3

SOURCE = "abs"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_page(url: str, timeout: int = 30) -> Optional[str]:
    """Download the page HTML and return it as a string."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-AU,en;q=0.9",
    }
    try:
        logger.info("Fetching %s", url)
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        logger.info("HTTP %s — %.1f KB received", response.status_code, len(response.content) / 1024)
        return response.text
    except requests.RequestException as e:
        logger.error("Failed to fetch %s: %s", url, e)
        return None


def extract_text(html: str) -> str:
    """
    Parse HTML and return clean plain text.

    Steps:
      1. Remove noise tags (scripts, nav, footer, etc.)
      2. Extract text with space separators
      3. Strip embedded JSON blobs from ABS interactive charts
      4. Normalise whitespace
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(MACRO_NOISE_TAGS):
        tag.decompose()

    raw_text = soup.get_text(separator=" ")

    # Strip embedded JSON chart data (arrays and objects)
    raw_text = re.sub(r'\[[^\[\]]*\]', " ", raw_text)
    raw_text = re.sub(r'\[[^\[\]]*\]', " ", raw_text)

    clean = " ".join(raw_text.split())
    logger.info("Extracted %d characters of plain text", len(clean))
    return clean


def scrape_page(url: str) -> Optional[str]:
    """Fetch and extract text from a single ABS page."""
    html = fetch_page(url)
    if not html:
        return None
    return extract_text(html)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape all ABS pages and upload to S3 or save locally."""
    logger.info("Scraping multiple ABS statistical release pages")
    success = True

    for url, slug, dataset in MACRO_URLS:
        logger.info("--- Starting: %s ---", slug)
        content = scrape_page(url)

        if not content:
            logger.warning("No content extracted for %s — skipping", slug)
            success = False
            continue

        logger.info("Extracted %d characters of text.", len(content))
        payload = build_payload(
            content,
            SOURCE,
            dataset,
            fetch_run_date(),
            TIER.MACRO.value,
            url
        )

        if local:
            save_local(payload)
        else:
            upload_to_s3(payload)

    return success