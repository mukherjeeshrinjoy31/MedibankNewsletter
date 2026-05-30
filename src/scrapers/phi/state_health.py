import logging
import time
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from ...commons.data import HEADERS, STATE_HEALTH_SOURCES
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_run_date, save_local, upload_to_s3

SOURCE = "state_health"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_state_health() -> str:
    """Scrape all state health department sites and return combined content."""
    logger.info("--- State Health Department Sites ---")
    all_articles = []

    for source in STATE_HEALTH_SOURCES:
        logger.info("Fetching %s...", source['name'])
        try:
            if source["type"] == "rss":
                feed = feedparser.parse(source["url"])
                count = 0
                for entry in feed.entries[:10]:
                    all_articles.append(f"[{source['name']}] {entry.title} ({entry.link})")
                    count += 1
                logger.info("%s: found %d articles", source['name'], count)

            else:
                response = requests.get(source["url"], headers=HEADERS, timeout=30)
                if not response.ok:
                    logger.warning("%s: Failed HTTP %s", source['name'], response.status_code)
                else:
                    soup = BeautifulSoup(response.text, "html.parser")
                    links = soup.find_all("a", href=True)
                    count = 0
                    for link in links:
                        text = link.get_text(strip=True)
                        href = link["href"]
                        if len(text) > 20:
                            if not href.startswith("http"):
                                base = "https://" + source["url"].split("/")[2]
                                href = base + "/" + href.lstrip("/")
                            all_articles.append(f"[{source['name']}] {text} ({href})")
                            count += 1
                            if count >= 10:
                                break
                    logger.info("%s: found %d articles", source['name'], count)

        except Exception as e:
            logger.exception("%s: Error — %s", source['name'], e)

        time.sleep(2)

    return "\n".join(all_articles)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape state health sites and upload to S3 or save locally."""
    logger.info("Starting State Health scraper")
    content = scrape_state_health()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.HOSPITAL_NEWS.value,
        fetch_run_date(),
        TIER.PHI.value,
        STATE_HEALTH_SOURCES[0]["url"] if STATE_HEALTH_SOURCES else ""
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    run(local="data")