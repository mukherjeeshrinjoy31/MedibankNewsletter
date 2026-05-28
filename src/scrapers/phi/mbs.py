import logging
import os
import shutil
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ...commons.data import HEADERS, MBS_BASE_URL, MBS_DOWNLOAD_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "mbs"

RSS_URL = "https://news.google.com/rss/search?q=Medicare+Benefits+Schedule+MBS+changes+Australia&hl=en-AU&gl=AU&ceid=AU:en"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_xml() -> str:
    """Dynamically scrape MBS XML files. Returns content string or empty string."""
    logger.info("Fetching MBS downloads page...")
    soup = fetch_url(MBS_DOWNLOAD_URL)

    if not soup:
        logger.warning("fetch_url returned None — request failed.")
        return ""

    download_pages = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "Downloads-" in href and ("2025" in href or "2026" in href):
            if not href.startswith("http"):
                href = MBS_BASE_URL + href
            download_pages.append((link.get_text(strip=True), href))

    logger.info("Found %d download pages", len(download_pages))

    xml_links = []
    for text, page_url in download_pages[:6]:
        try:
            r = requests.get(page_url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                page_soup = BeautifulSoup(r.text, "html.parser")
                for a in page_soup.find_all("a", href=True):
                    if ".xml" in a["href"].lower() and "version" in a["href"].lower():
                        xml_url = a["href"]
                        if not xml_url.startswith("http"):
                            xml_url = MBS_BASE_URL + xml_url
                        xml_links.append((a.get_text(strip=True), xml_url))
                        break
            time.sleep(1)
        except Exception as e:
            logger.error("Error fetching page %s: %s", page_url, e)

    if not xml_links:
        logger.warning("No XML links found dynamically — MBS page structure may have changed.")
        return ""

    content = "Medicare Benefits Schedule (MBS) XML Files\n\n"
    os.makedirs("data/mbs", exist_ok=True)

    for title, xml_url in xml_links:
        filename = xml_url.split("$FILE/")[-1] if "$FILE/" in xml_url else xml_url.split("/")[-1]
        logger.info("Downloading: %s...", filename)
        try:
            r = requests.get(xml_url, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                with open(f"data/mbs/{filename}", "wb") as f:
                    f.write(r.content)
                size_mb = len(r.content) / 1024 / 1024
                content += f"- {filename} ({size_mb:.1f} MB)\n"
                logger.info("✓ %s (%.1f MB)", filename, size_mb)
            else:
                logger.warning("Failed to download %s: %s", filename, r.status_code)
        except Exception as e:
            logger.error("Error downloading %s: %s", filename, e)
        time.sleep(2)

    shutil.rmtree("data/mbs")
    logger.info("Deleted folder: data/mbs")

    return content.strip()


def scrape_mbs() -> str:
    """Scrape MBS XML files dynamically, falling back to Google News RSS."""
    logger.info("--- MBS Scraper ---")

    content = scrape_xml()
    if content:
        return content

    logger.warning("Dynamic scraping failed — falling back to Google News RSS.")
    return fetch_google_news_rss(RSS_URL, "Medicare Benefits Schedule (MBS) — Latest News", 90)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape MBS data and upload to S3 or save locally."""
    logger.info("Starting MBS Scraper from: %s", MBS_DOWNLOAD_URL)
    content = scrape_mbs()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.SCHEDULE.value,
        fetch_run_date(),
        TIER.PHI.value,
        MBS_DOWNLOAD_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")