from typing import Optional
import os
import shutil
import time

import pdfplumber
import requests

from ...commons.data import ACCC_BASE_URL, HEADERS, ACCC_PHI_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_google_news_rss, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "accc"
RSS_URL = "https://news.google.com/rss/search?q=ACCC+private+health+insurance+Australia&hl=en-AU&gl=AU&ceid=AU:en"
OUTPUT_DIR = "data/accc"


def extract_pdf_text(filepath: str) -> str:
    """Extract and clean text from a downloaded PDF file."""
    try:
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return " ".join(text.split()).strip()
    except Exception as e:
        print(f"✗ PDF extraction error: {e}")
        return ""


def scrape_pdfs() -> str:
    """Attempt to dynamically scrape ACCC PHI PDF reports. Returns content string or empty string."""
    print("Fetching ACCC page...")
    soup = fetch_url(ACCC_PHI_URL)

    if not soup:
        print("fetch_url returned None — request failed")
        return ""

    # Find report sub-page links
    report_links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        if "readspeaker" in href.lower() or "rsent" in href.lower():
            continue

        if "private-health-insurance-report" in href.lower() and "serial-publications" in href.lower():
            if not href.startswith("http"):
                href = ACCC_BASE_URL + href
            if href != ACCC_PHI_URL:
                report_links.append((text, href))

    print(f"Found {len(report_links)} report pages")

    if not report_links:
        print("No report links found.")
        return ""

    content = "ACCC Private Health Insurance Reports\n\n"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for title, page_url in report_links[:3]:
        print(f"Fetching report page: {title}...")
        report_soup = fetch_url(page_url)
        if not report_soup:
            continue

        for link in report_soup.find_all("a", href=True):
            href = link["href"]
            if ".pdf" in href.lower():
                if not href.startswith("http"):
                    href = ACCC_BASE_URL + href
                filename = href.split("/")[-1]
                filepath = os.path.join(OUTPUT_DIR, filename)
                print(f"Downloading: {filename}...")
                try:
                    r = requests.get(href, headers=HEADERS, timeout=30)
                    if r.status_code == 200:
                        with open(filepath, "wb") as f:
                            f.write(r.content)
                        size_mb = len(r.content) / 1024 / 1024
                        print(f"✓ {filename} ({size_mb:.1f} MB)")

                        text = extract_pdf_text(filepath)
                        content += f"=== {title} ===\n{text}\n\n"
                        print(f"  Extracted {len(text):,} chars")
                    else:
                        print(f"✗ Failed: {r.status_code}")
                except Exception as e:
                    print(f"✗ Error: {e}")
                break
        time.sleep(1)

    # Delete downloaded files after extraction
    shutil.rmtree(OUTPUT_DIR)
    print(f"Deleted folder: {OUTPUT_DIR}")

    return content.strip() if len(content) > 50 else ""


def scrape_accc() -> str:
    """Scrape ACCC PHI reports — dynamic PDFs first, then Google News RSS fallback."""
    print("--- ACCC PHI Reports ---")

    content = scrape_pdfs()
    if content:
        return content

    return fetch_google_news_rss(RSS_URL, "ACCC Private Health Insurance — Latest News", 90)


def run(local: Optional[str] = None) -> bool:
    """Scrape ACCC PHI reports and upload to S3 or save locally."""
    print(f"Starting ACCC Scraper from: {ACCC_PHI_URL}")
    content = scrape_accc()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_REPORT.value,
        fetch_run_date(),
        TIER.PHI.value,
        ACCC_PHI_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)


if __name__ == "__main__":
    run(local=True)