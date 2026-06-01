import logging
import os
import shutil
import time
from typing import Optional

import requests

from ...commons.data import HEADERS, HEALTH_DEPT_BASE_URL, HEALTH_DEPT_CLINICAL_URL, HEALTH_DEPT_MINISTERS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE     = "health_dept"
OUTPUT_DIR = "data/health_dept"

PREMIUM_RSS_URL  = "https://news.google.com/rss/search?q=private+health+insurance+premium+increase+Australia&hl=en-AU&gl=AU&ceid=AU:en"
CLINICAL_RSS_URL = "https://news.google.com/rss/search?q=MBS+clinical+categories+private+health+insurance+Australia&hl=en-AU&gl=AU&ceid=AU:en"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Premium Approvals
# ---------------------------------------------------------------------------

def scrape_premium_approvals() -> str:
    """Scrape Dept of Health ministers page for premium approval content."""
    logger.info("--- Dept of Health: Premium Approvals ---")
    logger.info("Fetching ministers page...")

    soup = fetch_url(HEALTH_DEPT_MINISTERS_URL)
    if soup:
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())

        if "premium" in text.lower():
            idx = text.lower().find("premium")
            content = "Dept of Health - Premium Approvals\n\n"
            content += text[max(0, idx - 200):idx + 2000]
            logger.info("Found premium content dynamically.")
            return content.strip()

    logger.warning("Premium content not found — falling back to Google News RSS.")
    return fetch_google_news_rss(PREMIUM_RSS_URL, "Dept of Health — Premium Approvals Latest News", 30)


# ---------------------------------------------------------------------------
# Clinical Categories
# ---------------------------------------------------------------------------

def scrape_clinical_categories() -> str:
    """Scrape Dept of Health for clinical category files, falling back to RSS."""
    logger.info("--- Dept of Health: Clinical Categories ---")
    logger.info("Fetching clinical categories page...")

    soup = fetch_url(HEALTH_DEPT_CLINICAL_URL)
    if soup:
        links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)
            if (".xlsx" in href.lower() or ".pdf" in href.lower()) and "clinical" in href.lower():
                if not href.startswith("http"):
                    href = HEALTH_DEPT_BASE_URL + href
                links.append((text, href))

        if links:
            content = "Dept of Health - Clinical Categories\n\n"
            os.makedirs(OUTPUT_DIR, exist_ok=True)

            for title, href in links[:3]:
                filename = href.split("/")[-1]
                logger.info("Downloading: %s...", filename)
                try:
                    r = requests.get(href, headers=HEADERS, timeout=30)
                    if r.status_code == 200:
                        with open(os.path.join(OUTPUT_DIR, filename), "wb") as f:
                            f.write(r.content)
                        content += f"- {title}: {filename}\n"
                        logger.info("✓ %s", filename)
                    else:
                        logger.warning("Failed to download %s: %s", filename, r.status_code)
                except Exception as e:
                    logger.error("Error downloading %s: %s", filename, e)
                time.sleep(1)

            shutil.rmtree(OUTPUT_DIR)
            logger.info("Deleted folder: %s", OUTPUT_DIR)
            return content.strip()

    logger.warning("No clinical category files found — falling back to Google News RSS.")
    return fetch_google_news_rss(CLINICAL_RSS_URL, "Dept of Health — Clinical Categories Latest News", 30)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape Dept of Health premium approvals and clinical categories."""
    logger.info("Starting Health Dept Scraper")

    premium_content = scrape_premium_approvals()
    logger.info("Extracted %d characters (premium approvals)", len(premium_content))
    premium_payload = build_payload(
        premium_content,
        SOURCE,
        DATASET.PREMIUM_APPROVALS.value,
        fetch_run_date(),
        TIER.PHI.value,
        HEALTH_DEPT_MINISTERS_URL
    )

    clinical_content = scrape_clinical_categories()
    logger.info("Extracted %d characters (clinical categories)", len(clinical_content))
    clinical_payload = build_payload(
        clinical_content,
        SOURCE,
        DATASET.CLINICAL_CATEGORIES.value,
        fetch_run_date(),
        TIER.PHI.value,
        HEALTH_DEPT_CLINICAL_URL
    )

    if local:
        save_local(premium_payload)
        save_local(clinical_payload)
    else:
        upload_to_s3(premium_payload)
        upload_to_s3(clinical_payload)
    return True


if __name__ == "__main__":
    run(local="data")