import logging
import time
from typing import Optional, List

from ...commons.data import NEWSROOM_COMPETITOR_SOURCE_URLS, NEWSROOM_SKIP_URL_KEYWORDS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "newsrooms"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_static(url: str, source_name: str, url_keywords: List[str], max_articles: int = 10) -> List[str]:
    """Scrape a static HTML newsroom page and extract article links by URL keyword filtering."""
    articles = []
    seen = set()

    try:
        soup = fetch_url(url)
        if not soup:
            logger.warning("Could not fetch page for %s — skipping.", source_name)
            return []

        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True)
            href = link["href"]

            if not href.startswith("http"):
                href = url.rstrip("/") + "/" + href.lstrip("/")

            if href in seen:
                continue
            if len(text) > 20 and any(kw in href for kw in url_keywords):
                if any(skip in href for skip in NEWSROOM_SKIP_URL_KEYWORDS):
                    continue
                articles.append(f"[{source_name}] {text} ({href})")
                seen.add(href)
                if len(articles) >= max_articles:
                    break
    except Exception as e:
        logger.error("Static fetch error for %s: %s", source_name, e)

    return articles


def scrape_newsrooms() -> str:
    """Scrape competitor newsrooms and return combined content string."""
    logger.info("--- Competitor Newsrooms ---")
    all_articles = []

    for source in NEWSROOM_COMPETITOR_SOURCE_URLS:
        logger.info("Fetching %s...", source["name"])
        articles = fetch_static(
            source["url"],
            source["name"],
            source.get("article_url_keywords", [])
        )
        all_articles.extend(articles)
        logger.info("✓ %s: found %d articles", source["name"], len(articles))
        time.sleep(2)

    return "\n\n".join(all_articles)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape competitor newsrooms and upload to S3 or save locally."""
    logger.info("Starting competitor newsrooms scraper: BUPA, NIB, HCF and HBF")
    content = scrape_newsrooms()

    if not content:
        logger.warning("No articles found — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.COMPETITOR_NEWS.value,
        fetch_run_date(),
        TIER.PHI.value,
        " / ".join([s["url"] for s in NEWSROOM_COMPETITOR_SOURCE_URLS])
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")