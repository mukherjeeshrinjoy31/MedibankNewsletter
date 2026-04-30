import requests
import feedparser
import os
import json
import time
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "accc"
DATASET = "phi_reports"
TIER    = "phi_industry"
URL     = "https://www.accc.gov.au/about-us/publications/serial-publications/private-health-insurance-reports"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_accc() -> str:
    print("--- ACCC PHI Reports ---")

    content = "ACCC Private Health Insurance Reports\n\n"

    # try to find pdf links dynamically
    try:
        print("Fetching ACCC page...")
        response = requests.get(URL, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            pdf_links = []

            for link in soup.find_all("a", href=True):
                href = link["href"]
                text = link.get_text(strip=True)
                if ".pdf" in href.lower() and "private-health" in href.lower():
                    if not href.startswith("http"):
                        href = "https://www.accc.gov.au" + href
                    pdf_links.append((text, href))

            if pdf_links:
                os.makedirs("data/accc", exist_ok=True)
                for title, href in pdf_links[:3]:
                    filename = href.split("/")[-1]
                    print(f"Downloading: {filename}...")
                    r = requests.get(href, headers=HEADERS, timeout=30)
                    if r.status_code == 200:
                        with open(f"data/accc/{filename}", "wb") as f:
                            f.write(r.content)
                        size_mb = len(r.content) / 1024 / 1024
                        content += f"- {title}: {filename} ({size_mb:.1f} MB)\n"
                        print(f"✓ {filename} ({size_mb:.1f} MB)")
                    else:
                        print(f"✗ Failed: {r.status_code}")
                    time.sleep(1)

                return content.strip()

        print("Page returned limited content")

    except Exception as e:
        print(f"Dynamic scraping failed: {e}")

    # fallback — google news rss for latest accc phi news
    print("Trying Google News RSS for ACCC updates...")
    try:
        rss_url = "https://news.google.com/rss/search?q=ACCC+private+health+insurance+Australia&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(rss_url)
        if feed.entries:
            content += "Latest ACCC PHI news via Google News:\n\n"
            for entry in feed.entries[:10]:
                content += f"Title: {entry.title}\n"
                content += f"Link: {entry.link}\n"
                content += f"Published: {entry.get('published', 'N/A')}\n\n"
            print(f"✓ Found {len(feed.entries[:10])} articles via Google News RSS")
            return content.strip()

    except Exception as e:
        print(f"Google News RSS failed: {e}")

    # last resort — known files
    print("Using known files as last resort")
    known_files = [
        {
            "name": "accc_phi_report_2024_25.pdf",
            "url": "https://www.accc.gov.au/system/files/private-health-insurance-report-2024-25.pdf",
            "title": "ACCC PHI Report 2024-25"
        },
        {
            "name": "accc_phi_report_2023_24.pdf",
            "url": "https://www.accc.gov.au/system/files/private-health-insurance-report-2023-24.pdf",
            "title": "ACCC PHI Report 2023-24"
        }
    ]

    os.makedirs("data/accc", exist_ok=True)
    for file in known_files:
        print(f"Downloading: {file['name']}...")
        r = requests.get(file["url"], headers=HEADERS, timeout=30)
        if r.status_code == 200:
            with open(f"data/accc/{file['name']}", "wb") as f:
                f.write(r.content)
            size_mb = len(r.content) / 1024 / 1024
            content += f"- {file['title']}: {file['name']} ({size_mb:.1f} MB)\n"
            print(f"✓ {file['name']} ({size_mb:.1f} MB)")
        else:
            print(f"✗ Failed: {r.status_code}")
        time.sleep(1)

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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/accc",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_accc()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)