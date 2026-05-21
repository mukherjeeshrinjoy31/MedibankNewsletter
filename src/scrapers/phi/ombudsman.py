from typing import Optional

from ...commons.data import OMBUDSMAN_PHI_URL, OMBUDSMAN_RSS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "ombudsman"


def scrape_ombudsman() -> str:
    """Scrape PHI Ombudsman page, falling back to Google News RSS."""
    print("--- PHI Ombudsman Reports ---")
    print("Fetching Ombudsman page...")

    soup = fetch_url(OMBUDSMAN_PHI_URL)
    if soup:
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())

        if len(text) > 200:
            content = f"PHI Ombudsman Quarterly Reports\n\n{text[:5000]}"
            print(f"✓ Extracted {len(text):,} characters from page")
            return content.strip()

    print("Page scraping failed — falling back to Google News RSS")
    return fetch_google_news_rss(OMBUDSMAN_RSS_URL, "PHI Ombudsman — Latest News", 365)


def run(local: Optional[str] = None) -> bool:
    """Scrape PHI Ombudsman reports and upload to S3 or save locally."""
    print(f"Starting Ombudsman Scraper from: {OMBUDSMAN_PHI_URL}")
    content = scrape_ombudsman()
    print(f"\nExtracted {len(content):,} characters of text.")
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