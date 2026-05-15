from typing import Optional

import time

from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...commons.data import NEWSROOM_COMPETITOR_SOURCE_URLS, NEWSROOM_SKIP_URL_KEYWORDS
from ...utils.helpers import build_payload, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "newsrooms"

def fetch_static(url: str, source_name: str, url_keywords: list, max_articles: int = 10) -> list:
    """Scrape static HTML page and extract article links by URL keyword filtering."""
    articles = []
    seen = set()
    try:
        soup = fetch_url(url)
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
        print(f"✗ Static fetch error for {source_name}: {e}")
    return articles


def scrape_newsrooms() -> str:
    """Scrape competitor newsrooms and return combined content string."""
    print("--- Competitor Newsrooms ---")
    all_articles = []

    for source in NEWSROOM_COMPETITOR_SOURCE_URLS:
        print(f"Fetching {source['name']}...")
        articles = fetch_static(
            source["url"],
            source["name"],
            source.get("article_url_keywords", [])
        )
        all_articles.extend(articles)
        print(f"✓ {source['name']}: found {len(articles)} articles")
        time.sleep(2)

    return "\n\n".join(all_articles)


def run(local: Optional[str] = None) -> bool:
    """Scrape competitor newsrooms and upload to S3 or save locally."""
    print("Starting PHI Scrapper for competitor newsrooms: BUPA, NIB, HCF and HBF")
    content = scrape_newsrooms()
    print(f"\nExtracted {len(content):,} characters of text.")
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