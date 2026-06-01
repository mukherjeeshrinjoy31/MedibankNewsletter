import logging
import os
from typing import Optional

from ...commons.data import APRA_BASE_URL, APRA_QUARTERLY_STATISTICS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.apra_helpers import download_and_extract
from ...utils.helpers import build_payload, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "apra"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_apra_quarterly() -> str:
    """Scrape APRA quarterly PHI statistics XLSX files and extract content."""
    logger.info("--- APRA Quarterly Stats ---")

    soup = fetch_url(APRA_QUARTERLY_STATISTICS_URL)
    if not soup:
        logger.error("fetch_url returned None — request failed.")
        return ""

    xlsx_links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if ".xlsx" in href.lower():
            if not href.startswith("http"):
                href = APRA_BASE_URL + href
            xlsx_links.append((link.get_text(strip=True), href))

    logger.info("Found %d XLSX files", len(xlsx_links))

    if not xlsx_links:
        logger.warning("No links found — page likely uses JavaScript.")
        return ""

    os.makedirs("data/apra", exist_ok=True)
    content = download_and_extract(xlsx_links, "APRA Quarterly Private Health Insurance Statistics\n\n")

    return content.strip()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape APRA quarterly PHI statistics and upload to S3 or save locally."""
    logger.info("Starting APRA Quarterly Scraper from: %s", APRA_QUARTERLY_STATISTICS_URL)
    content = scrape_apra_quarterly()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_STATS.value,
        fetch_run_date(),
        TIER.PHI.value,
        APRA_QUARTERLY_STATISTICS_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")