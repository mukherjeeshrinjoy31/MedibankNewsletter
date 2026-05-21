from typing import Optional
import os
import shutil
import time

import requests

from ...commons.data import HEADERS, HEALTH_DEPT_BASE_URL, HEALTH_DEPT_CLINICAL_URL, HEALTH_DEPT_MINISTERS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE     = "health_dept"
OUTPUT_DIR = "data/health_dept"

PREMIUM_RSS_URL  = "https://news.google.com/rss/search?q=private+health+insurance+premium+increase+Australia&hl=en-AU&gl=AU&ceid=AU:en"
CLINICAL_RSS_URL = "https://news.google.com/rss/search?q=MBS+clinical+categories+private+health+insurance+Australia&hl=en-AU&gl=AU&ceid=AU:en"


# --- Premium Approvals ---

def scrape_premium_approvals() -> str:
    """Scrape Dept of Health ministers page for premium approval content."""
    print("--- Dept of Health: Premium Approvals ---")
    print("Fetching ministers page...")

    soup = fetch_url(HEALTH_DEPT_MINISTERS_URL)
    if soup:
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ", strip=True).split())

        if "premium" in text.lower():
            idx = text.lower().find("premium")
            content = "Dept of Health - Premium Approvals\n\n"
            content += text[max(0, idx - 200):idx + 2000]
            print("✓ Found premium content dynamically")
            return content.strip()

    print("Premium content not found — falling back to Google News RSS")
    return fetch_google_news_rss(PREMIUM_RSS_URL, "Dept of Health — Premium Approvals Latest News", 30)


# --- Clinical Categories ---

def scrape_clinical_categories() -> str:
    """Scrape Dept of Health for clinical category files, falling back to RSS."""
    print("--- Dept of Health: Clinical Categories ---")
    print("Fetching clinical categories page...")

    soup = fetch_url(HEALTH_DEPT_CLINICAL_URL)
    if soup:
        links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)
            if (".xlsx" in href.lower() or ".pdf" in href.lower()) and "clinical" in href.lower():
                if not href.startswith("http"):
                    href = HEALTH_DEPT_BASE_URL + href
                links.append((text, href))

        if links:
            content = "Dept of Health - Clinical Categories\n\n"
            os.makedirs(OUTPUT_DIR, exist_ok=True)

            for title, href in links[:3]:
                filename = href.split("/")[-1]
                print(f"Downloading: {filename}...")
                try:
                    r = requests.get(href, headers=HEADERS, timeout=30)
                    if r.status_code == 200:
                        with open(os.path.join(OUTPUT_DIR, filename), "wb") as f:
                            f.write(r.content)
                        content += f"- {title}: {filename}\n"
                        print(f"✓ {filename}")
                    else:
                        print(f"✗ Failed: {r.status_code}")
                except Exception as e:
                    print(f"✗ Error: {e}")
                time.sleep(1)

            shutil.rmtree(OUTPUT_DIR)
            print(f"Deleted folder: {OUTPUT_DIR}")
            return content.strip()

    print("No clinical category files found — falling back to Google News RSS")
    return fetch_google_news_rss(CLINICAL_RSS_URL, "Dept of Health — Clinical Categories Latest News", 30)


# --- Run ---

def run(local: Optional[str] = None) -> bool:
    """Scrape Dept of Health premium approvals and clinical categories."""
    print("Starting Health Dept Scraper")

    premium_content = scrape_premium_approvals()
    print(f"\nExtracted {len(premium_content):,} characters (premium approvals)")
    premium_payload = build_payload(
        premium_content,
        SOURCE,
        DATASET.PREMIUM_APPROVALS.value,
        fetch_run_date(),
        TIER.PHI.value,
        HEALTH_DEPT_MINISTERS_URL
    )

    clinical_content = scrape_clinical_categories()
    print(f"\nExtracted {len(clinical_content):,} characters (clinical categories)")
    clinical_payload = build_payload(
        clinical_content,
        SOURCE,
        DATASET.CLINICAL_CATEGORIES.value,
        fetch_run_date(),
        TIER.PHI.value,
        HEALTH_DEPT_CLINICAL_URL
    )

    if local:
        save_local(premium_payload)
        save_local(clinical_payload)
    else:
        upload_to_s3(premium_payload)
        upload_to_s3(clinical_payload)
    return True