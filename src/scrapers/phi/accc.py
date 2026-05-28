import logging
import os
import shutil
import time
from typing import Optional

import requests

from ...commons.data import ACCC_BASE_URL, ACCC_PHI_URL, HEADERS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_payload, extract_pdf_text, fetch_google_news_rss,
    fetch_run_date, fetch_url, save_local, upload_to_s3
)

SOURCE     = "accc"
RSS_URL    = "https://news.google.com/rss/search?q=ACCC+private+health+insurance+Australia&hl=en-AU&gl=AU&ceid=AU:en"
OUTPUT_DIR = "data/accc"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_pdfs() -> str:
    """Dynamically scrape ACCC PHI PDF reports. Returns content string or empty string."""
    logger.info("Fetching ACCC page...")
    soup = fetch_url(ACCC_PHI_URL)

    if not soup:
        logger.warning("fetch_url returned None — request failed.")
        return ""

    report_links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        if "readspeaker" in href.lower() or "rsent" in href.lower():
            continue

        if "private-health-insurance-report" in href.lower() and "serial-publications" in href.lower():
            if not href.startswith("http"):
                href = ACCC_BASE_URL + href
            if href != ACCC_PHI_URL:
                report_links.append((text, href))

    logger.info("Found %d report pages", len(report_links))

    if not report_links:
        logger.warning("No report links found.")
        return ""

    content = "ACCC Private Health Insurance Reports\n\n"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for title, page_url in report_links[:3]:
        logger.info("Fetching report page: %s...", title)
        report_soup = fetch_url(page_url)
        if not report_soup:
            continue

        for link in report_soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower():
                if not href.startswith("http"):
                    href = ACCC_BASE_URL + href
                filename = href.split("/")[-1]
                filepath = os.path.join(OUTPUT_DIR, filename)
                logger.info("Downloading: %s...", filename)
                try:
                    r = requests.get(href, headers=HEADERS, timeout=30)
                    if r.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(r.content)
                        size_mb = len(r.content) / 1024 / 1024
                        logger.info("✓ %s (%.1f MB)", filename, size_mb)

                        text = extract_pdf_text(filepath)
                        content += f"=== {title} ===\n{text}\n\n"
                        logger.info("Extracted %d chars", len(text))
                    else:
                        logger.warning("Failed to download %s: %s", filename, r.status_code)
                except Exception as e:
                    logger.error("Error downloading %s: %s", filename, e)
                break
        time.sleep(1)

    shutil.rmtree(OUTPUT_DIR)
    logger.info("Deleted folder: %s", OUTPUT_DIR)

    return content.strip() if len(content) > 50 else ""


def scrape_accc() -> str:
    """Scrape ACCC PHI reports — dynamic PDFs first, then Google News RSS fallback."""
    logger.info("--- ACCC PHI Reports ---")

    content = scrape_pdfs()
    if content:
        return content

    logger.warning("PDF scraping failed — falling back to Google News RSS.")
    return fetch_google_news_rss(RSS_URL, "ACCC Private Health Insurance — Latest News", 90)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape ACCC PHI reports and upload to S3 or save locally."""
    logger.info("Starting ACCC Scraper from: %s", ACCC_PHI_URL)
    content = scrape_accc()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_REPORT.value,
        fetch_run_date(),
        TIER.PHI.value,
        ACCC_PHI_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")