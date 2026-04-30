import requests
import feedparser
import os
import json
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "ombudsman"
DATASET = "phi_reports"
TIER    = "phi_industry"
URL     = "https://www.ombudsman.gov.au/industry-and-agency-oversight/industry-updates/private-health-insurance-updates"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_ombudsman() -> str:
    print("--- PHI Ombudsman Reports ---")

    content = "PHI Ombudsman Quarterly Reports\n\n"

    # try scraping the page first
    try:
        print("Fetching Ombudsman page...")
        response = requests.get(URL, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = " ".join(text.split())

            if len(text) > 200:
                content += text[:5000]
                print(f"✓ Extracted {len(text)} characters from page")
                return content.strip()

    except Exception as e:
        print(f"Page scraping failed: {e}")

    # fallback — google news rss for latest ombudsman phi updates
    print("Trying Google News RSS for Ombudsman updates...")
    try:
        rss_url = "https://news.google.com/rss/search?q=private+health+insurance+ombudsman+Australia&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(rss_url)

        if feed.entries:
            content += "Latest PHI Ombudsman news via Google News:\n\n"
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
    known_reports = [
        {
            "title": "PHI Quarterly Update 114: April to June 2025 (with annual summary 2024-25)",
            "quarter": "Q4 2024-25",
            "date": "2025"
        },
        {
            "title": "PHI Quarterly Update 113: January to March 2025",
            "quarter": "Q3 2024-25",
            "date": "2025"
        },
        {
            "title": "PHI Quarterly Update 112: October to December 2024",
            "quarter": "Q2 2024-25",
            "date": "2024"
        }
    ]

    for report in known_reports:
        content += f"Title: {report['title']}\n"
        content += f"Quarter: {report['quarter']}\n"
        content += f"Date: {report['date']}\n\n"

    print(f"✓ Loaded {len(known_reports)} known reports")
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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/ombudsman",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_ombudsman()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)