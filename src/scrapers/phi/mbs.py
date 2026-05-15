import shutil
from typing import Optional

import os
import time

import requests
from bs4 import BeautifulSoup

from ...commons.data import HEADERS, MBS_BASE_URL, MBS_DOWNLOAD_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_run_date, fetch_url, save_local, upload_to_s3, fetch_google_news_rss

SOURCE = "mbs"

RSS_URL = "https://news.google.com/rss/search?q=Medicare+Benefits+Schedule+MBS+changes+Australia&hl=en-AU&gl=AU&ceid=AU:en"
CUTOFF_DAYS = 365


def scrape_xml() -> str:
    """Attempt to dynamically scrape MBS XML files. Returns content string or empty string."""
    print("Fetching MBS downloads page...")
    soup = fetch_url(MBS_DOWNLOAD_URL)

    if not soup:
        print("fetch_url returned None — request failed")
        return ""

    download_pages = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "Downloads-" in href and ("2025" in href or "2026" in href):
            if not href.startswith("http"):
                href = MBS_BASE_URL + href
            download_pages.append((link.get_text(strip=True), href))

    print(f"Found {len(download_pages)} download pages")

    xml_links = []
    for text, page_url in download_pages[:6]:
        try:
            r = requests.get(page_url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                page_soup = BeautifulSoup(r.text, "html.parser")
                for a in page_soup.find_all("a", href=True):
                    if ".xml" in a["href"].lower() and "version" in a["href"].lower():
                        xml_url = a["href"]
                        if not xml_url.startswith("http"):
                            xml_url = MBS_BASE_URL + xml_url
                        xml_links.append((a.get_text(strip=True), xml_url))
                        break
            time.sleep(1)
        except Exception as e:
            print(f"Error fetching page: {e}")

    if not xml_links:
        print("No XML links found dynamically — MBS page structure may have changed.")
        return ""

    content = "Medicare Benefits Schedule (MBS) XML Files\n\n"
    os.makedirs("data/mbs", exist_ok=True)
    for title, xml_url in xml_links:
        filename = xml_url.split("$FILE/")[-1] if "$FILE/" in xml_url else xml_url.split("/")[-1]
        print(f"Downloading: {filename}...")
        try:
            r = requests.get(xml_url, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                with open(f"data/mbs/{filename}", "wb") as f:
                    f.write(r.content)
                size_mb = len(r.content) / 1024 / 1024
                content += f"- {filename} ({size_mb:.1f} MB)\n"
                print(f"✓ {filename} ({size_mb:.1f} MB)")
            else:
                print(f"✗ Failed: {r.status_code}")
        except Exception as e:
            print(f"✗ Error: {e}")
        time.sleep(2)

    shutil.rmtree("data/mbs")
    print("Deleted folder: data/mbs")

    return content.strip()


def scrape_mbs() -> str:
    """Scrape MBS XML files dynamically, falling back to Google News RSS."""
    print("--- MBS Scraper ---")

    content = scrape_xml()
    if content:
        return content
    return fetch_google_news_rss(RSS_URL, "Medicare Benefits Schedule (MBS) — Latest News", 90)


def run(local: Optional[str] = None) -> bool:
    """Scrape MBS data and upload to S3 or save locally."""
    print(f"Starting MBS Scraper from: {MBS_DOWNLOAD_URL}")
    content = scrape_mbs()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.SCHEDULE.value,
        fetch_run_date(),
        TIER.PHI.value,
        MBS_DOWNLOAD_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
      