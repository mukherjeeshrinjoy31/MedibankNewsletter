import logging
from typing import Optional

from ...commons.data import LEGISLATION_PHI_URL, LEGISLATION_RSS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "legislation"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_legislation() -> str:
    """Scrape PHI amendment rules from the Federal Register of Legislation."""
    logger.info("--- Federal Register of Legislation ---")
    logger.info("Fetching legislation page...")

    soup = fetch_url(LEGISLATION_PHI_URL)

    if soup:
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())

        if len(text) > 200:
            content = f"PHI Amendment Rules - Federal Register of Legislation\n\n{text[:5000]}"
            logger.info("Extracted %d characters from page.", len(text))
            return content.strip()

    logger.warning("Page scraping failed — falling back to Google News RSS.")
    return fetch_google_news_rss(LEGISLATION_RSS_URL, "PHI Legislation — Latest News", 365)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape PHI legislation and upload to S3 or save locally."""
    logger.info("Starting Legislation Scraper from: %s", LEGISLATION_PHI_URL)
    content = scrape_legislation()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_AMEND.value,
        fetch_run_date(),
        TIER.PHI.value,
        LEGISLATION_PHI_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")