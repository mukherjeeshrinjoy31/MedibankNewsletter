from typing import Optional

from ...commons.data import HEADERS, LEGISLATION_PHI_URL, LEGISLATION_RSS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "legislation"

def scrape_legislation() -> str:
    """Scrape PHI amendment rules from the Federal Register of Legislation."""
    print("--- Federal Register of Legislation ---")
    print("Fetching legislation page...")

    soup = fetch_url(LEGISLATION_PHI_URL)

    if soup:
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())

        if len(text) > 200:
            content = f"PHI Amendment Rules - Federal Register of Legislation\n\n{text[:5000]}"
            print(f"✓ Extracted {len(text):,} characters from page")
            return content.strip()

    print("Page scraping failed — falling back to Google News RSS")
    return fetch_google_news_rss(
        LEGISLATION_RSS_URL,
        "PHI Legislation — Latest News",
        CUTOFF_DAYS=365
    )


def run(local: Optional[str] = None) -> bool:
    """Scrape PHI legislation and upload to S3 or save locally."""
    print(f"Starting Legislation Scraper from: {LEGISLATION_PHI_URL}")
    content = scrape_legislation()
    print(f"\nExtracted {len(content):,} characters of text.")
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
