import time
import logging
from typing import Optional
from datetime import datetime, timezone
from ...commons.data import BOILERPLATE, MEDIBANK_BASE_URL, MEDIBANK_NEWSROOM_TAG, ASX_MEDIBANK_RELEASES_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, clean_text, fetch_article_links, fetch_cutoff_date, fetch_run_date, fetch_url, save_local, upload_to_s3

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'medibank'


# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("nib_asx_announcements.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# Fix Windows terminal encoding
import sys
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Step 3: Scrape each article ─────────────────────────────────
def scrape_article(article_url):
    try:
        soup = fetch_url(article_url)
        # 7 day filter
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                pub_date = datetime.fromisoformat(time_tag["datetime"])
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                if pub_date < fetch_cutoff_date(7):
                    log.info(f"  Skipping (older than 7 days): {article_url}")
                    return None
            except Exception as e:
                log.warning(f"  Could not parse date, including anyway: {e}")

        headline = soup.find("h1")
        headline_text = headline.get_text(strip=True) if headline else ""

        paragraphs = soup.find_all("p")
        body_text = " ".join(
            p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
        )

        full_text = clean_text(f"{headline_text}. {body_text}", BOILERPLATE['MEDIBANK'])

        if not full_text:
            log.warning(f"  Empty content after cleaning: {article_url}")
            return None

        return full_text

    except Exception as e:
        log.error(f"  Failed to scrape {article_url}: {e}")
        return None


def scrape():
    links = fetch_article_links(
        MEDIBANK_NEWSROOM_TAG,
        MEDIBANK_BASE_URL,
        ASX_MEDIBANK_RELEASES_URL
    )
    if not links:
        log.error("No links found — skipping this run")
        return []

    articles = []
    for link in links:
        log.info(f"Scraping: {link}")
        text = scrape_article(link)
        if text:
            articles.append(text)
        time.sleep(1)

    log.info(f"{len(articles)} articles within the last 7 days")
    content_parts = [
        f"Source: {SOURCE} | Dataset: {DATASET.ASX_RELEASES.value} | Run Date: {fetch_run_date()} | Articles: {len(articles)}"
    ]
    for i, text in enumerate(articles, 1):
        content_parts.append(f"{i}. {text}")
    return content_parts    


def run(local: Optional[str] = None) -> bool:
    print(f"Scraping Medibank Specific Sources (ASX Releases) from: \n  {ASX_MEDIBANK_RELEASES_URL} \n")
    content = scrape()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.ASX_RELEASES.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        ASX_MEDIBANK_RELEASES_URL  
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True    
