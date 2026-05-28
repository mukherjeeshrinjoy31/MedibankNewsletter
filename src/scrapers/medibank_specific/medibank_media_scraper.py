import logging
import time
from datetime import datetime, timezone
from typing import Optional

from ...commons.data import BOILERPLATE, MEDIBANK_BASE_URL, MEDIBANK_NEWSROOM_TAG, MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_payload, clean_text, fetch_article_links, fetch_cutoff_date,
    fetch_run_date, fetch_url, save_local, upload_to_s3
)

SOURCE = "medibank"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_article(article_url: str) -> Optional[str]:
    """Fetch and extract text from a single Medibank media release article."""
    soup = fetch_url(article_url)
    if not soup:
        logger.warning("Could not fetch article: %s", article_url)
        return None

    # Apply 7-day cutoff filter using article publish date
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        try:
            pub_date = datetime.fromisoformat(time_tag["datetime"])
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            if pub_date < fetch_cutoff_date(7):
                logger.info("Skipping (older than 7 days): %s", article_url)
                return None
        except Exception as e:
            logger.warning("Could not parse date, including anyway: %s", e)

    headline = soup.find("h1")
    headline_text = headline.get_text(strip=True) if headline else ""

    paragraphs = soup.find_all("p")
    body_text = " ".join(
        p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
    )

    full_text = clean_text(f"{headline_text}. {body_text}", BOILERPLATE["MEDIBANK"])

    if not full_text:
        logger.warning("Empty content after cleaning: %s", article_url)
        return None

    return full_text


def scrape() -> Optional[str]:
    """Scrape all recent Medibank media release articles and return combined content."""
    links = fetch_article_links(
        MEDIBANK_NEWSROOM_TAG,
        MEDIBANK_BASE_URL,
        MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL
    )

    if not links:
        logger.error("No links found — skipping this run.")
        return None

    articles = []
    for link in links:
        logger.info("Scraping: %s", link)
        text = scrape_article(link)
        if text:
            articles.append(text)
        time.sleep(1)

    logger.info("%d articles within the last 7 days", len(articles))

    if not articles:
        return None

    content_parts = [
        f"Source: {SOURCE} | Dataset: {DATASET.MEDIA_RELEASES.value} | "
        f"Run Date: {fetch_run_date()} | Articles: {len(articles)}"
    ]
    for i, text in enumerate(articles, 1):
        content_parts.append(f"{i}. {text}")

    return "\n\n".join(content_parts)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape Medibank media releases and upload to S3 or save locally."""
    logger.info("Scraping Medibank Media Releases from: %s", MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL)
    content = scrape()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.MEDIA_RELEASES.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")