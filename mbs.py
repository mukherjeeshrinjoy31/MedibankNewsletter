import requests
import feedparser
import os
import json
import time
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "mbs"
DATASET = "schedule"
TIER    = "phi_industry"
URL     = "http://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/downloads"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_mbs() -> str:
    print("--- MBS Online XML ---")

    content = "Medicare Benefits Schedule (MBS) XML Files\n\n"

    # try to find xml links dynamically from the downloads page
    try:
        print("Fetching MBS downloads page...")
        response = requests.get(URL, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")

            # look for links to individual download pages
            download_pages = []
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "downloads-" in href.lower() and ("2025" in href or "2026" in href):
                    if not href.startswith("http"):
                        href = "http://www.mbsonline.gov.au" + href
                    download_pages.append((link.get_text(strip=True), href))

            print(f"Found {len(download_pages)} download pages")

            # visit each page and grab the latest xml
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
                                    xml_url = "http://www.mbsonline.gov.au" + xml_url
                                xml_links.append((a.get_text(strip=True), xml_url))
                                break
                    time.sleep(1)
                except Exception as e:
                    print(f"Error fetching page: {e}")

            if xml_links:
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

                return content.strip()

    except Exception as e:
        print(f"Dynamic scraping failed: {e}")

    # fallback — google news rss for mbs updates
    print("Trying Google News RSS for MBS updates...")
    try:
        rss_url = "https://news.google.com/rss/search?q=Medicare+Benefits+Schedule+MBS+changes+Australia&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(rss_url)

        if feed.entries:
            content += "Latest MBS news via Google News:\n\n"
            for entry in feed.entries[:10]:
                content += f"Title: {entry.title}\n"
                content += f"Link: {entry.link}\n"
                content += f"Published: {entry.get('published', 'N/A')}\n\n"
            print(f"✓ Found {len(feed.entries[:10])} articles via Google News RSS")

            # still download known xml files for the actual schedule data
            print("Also downloading known MBS XML files...")
            known_files = [
                {
                    "name": "MBS_XML_20260301_v2.xml",
                    "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/dd6984c45a944962ca258d8600139d55/$FILE/MBS-XML-20260301-version%202.XML"
                },
                {
                    "name": "MBS_XML_20260101.xml",
                    "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/ba88a4b5d1c80bbaca258d490018207c/$FILE/MBS-XML-20260101.XML"
                },
                {
                    "name": "MBS_XML_20251101_v2.xml",
                    "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/928fae91a23256aaca258d0d0007eede/$FILE/MBS-XML-20251101%20Version%202.XML"
                },
                {
                    "name": "MBS_XML_20250701_v3.xml",
                    "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/0b61e1e80b332754ca258c9e0000c7d8/$FILE/MBS-XML-20250701%20Version%203.XML"
                },
                {
                    "name": "MBS_XML_20250301.xml",
                    "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/C73750F033F64E1CCA258C190017A963/$File/MBS-XML-20250301.XML"
                },
                {
                    "name": "MBS_XML_20250101.xml",
                    "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/9A8C6D685899CD47CA258BE800197F3B/$File/MBS-XML-20250101.xml"
                }
            ]

            os.makedirs("data/mbs", exist_ok=True)
            content += "\nMBS XML Files Downloaded:\n"
            for file in known_files:
                try:
                    r = requests.get(file["url"], headers=HEADERS, timeout=60)
                    if r.status_code == 200:
                        with open(f"data/mbs/{file['name']}", "wb") as f:
                            f.write(r.content)
                        size_mb = len(r.content) / 1024 / 1024
                        content += f"- {file['name']} ({size_mb:.1f} MB)\n"
                        print(f"✓ {file['name']} ({size_mb:.1f} MB)")
                    else:
                        print(f"✗ Failed: {r.status_code}")
                except Exception as e:
                    print(f"✗ Error: {e}")
                time.sleep(2)

            return content.strip()

    except Exception as e:
        print(f"Google News RSS failed: {e}")

    return content.strip()

# --- Output Helpers ---
def build_payload(content: str) -> dict:
    return {
        "source":     SOURCE,
        "tier":       TIER,
        "dataset":    DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url":        URL,
        "content":    content,
    }

def save_local(payload: dict, directory: str = ".") -> None:
    os.makedirs(directory, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{SOURCE}_{DATASET}_{date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✓ Saved locally: {path}")

def upload_to_s3(payload: dict) -> None:
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"raw/{TIER}/{SOURCE}_{DATASET}_{date}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"✓ Uploaded: s3://{BUCKET}/{key}")

# --- Main ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/mbs",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_mbs()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)