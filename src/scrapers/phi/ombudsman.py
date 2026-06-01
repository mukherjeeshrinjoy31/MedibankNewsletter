import logging
from typing import Optional

from ...commons.data import OMBUDSMAN_PHI_URL, OMBUDSMAN_RSS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "ombudsman"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_ombudsman() -> str:
    """Scrape PHI Ombudsman page, falling back to Google News RSS."""
    logger.info("--- PHI Ombudsman Reports ---")
    logger.info("Fetching Ombudsman page...")

    soup = fetch_url(OMBUDSMAN_PHI_URL)
    if soup:
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())

        if len(text) > 200:
            content = f"PHI Ombudsman Quarterly Reports\n\n{text[:5000]}"
            logger.info("Extracted %d characters from page.", len(text))
            return content.strip()

    logger.warning("Page scraping failed — falling back to Google News RSS.")
    return fetch_google_news_rss(OMBUDSMAN_RSS_URL, "PHI Ombudsman — Latest News", 365)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape PHI Ombudsman reports and upload to S3 or save locally."""
    logger.info("Starting Ombudsman Scraper from: %s", OMBUDSMAN_PHI_URL)
    content = scrape_ombudsman()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.OMBUDSMAN_REPORTS.value,
        fetch_run_date(),
        TIER.PHI.value,
        OMBUDSMAN_PHI_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")