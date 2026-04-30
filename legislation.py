import requests
import feedparser
import os
import json
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "legislation"
DATASET = "phi_amendments"
TIER    = "phi_industry"
URL     = "https://www.legislation.gov.au/Series/F2007L00523"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_legislation() -> str:
    print("--- Federal Register of Legislation ---")

    content = "PHI Amendment Rules - Federal Register of Legislation\n\n"

    # try scraping the page first
    try:
        print("Fetching legislation page...")
        response = requests.get(URL, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = " ".join(text.split())

            if len(text) > 200:
                content += text[:5000]
                print(f"✓ Extracted {len(text)} characters from page")
                return content.strip()

    except Exception as e:
        print(f"Page scraping failed: {e}")

    # fallback — google news rss for latest phi legislation updates
    print("Trying Google News RSS for legislation updates...")
    try:
        rss_url = "https://news.google.com/rss/search?q=private+health+insurance+legislation+amendment+Australia&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(rss_url)

        if feed.entries:
            content += "Latest PHI Legislation news via Google News:\n\n"
            for entry in feed.entries[:10]:
                content += f"Title: {entry.title}\n"
                content += f"Link: {entry.link}\n"
                content += f"Published: {entry.get('published', 'N/A')}\n\n"
            print(f"✓ Found {len(feed.entries[:10])} articles via Google News RSS")
            return content.strip()

    except Exception as e:
        print(f"Google News RSS failed: {e}")

    # last resort — known entries
    print("Using known entries as last resort")
    known_rules = [
        {
            "title": "PHI 17/26 — Private Health Insurance Legislation Amendment Rules (No. 2) 2026",
            "date": "25 February 2026",
            "summary": "Corrects admin error in PHI 16/26 — restores MBS items to Support list from 1 March 2026"
        },
        {
            "title": "PHI 16/26 — Private Health Insurance Legislation Amendment Rules (No. 1) 2026",
            "date": "20 February 2026",
            "summary": "GMST, PST and DIST changes from 1 March 2026 — ends 85% out-of-hospital benefit for 100+ items"
        },
        {
            "title": "PHI 100/24 — Private Health Insurance Legislation Amendment Rules (No. 1) 2025",
            "date": "17 December 2024",
            "summary": "DIST and PST changes effective 1 January 2025"
        }
    ]

    for rule in known_rules:
        content += f"Title: {rule['title']}\n"
        content += f"Date: {rule['date']}\n"
        content += f"Summary: {rule['summary']}\n\n"

    print(f"✓ Loaded {len(known_rules)} known rules")
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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/legislation",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_legislation()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)