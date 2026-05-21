import requests
import feedparser
import os
import json
import time
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "state_health"
DATASET = "hospital_news"
TIER    = "phi_industry"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# state health sites + qld via google news rss
SOURCES = [
    {"name": "NSW Health", "url": "https://www.health.nsw.gov.au/news/Pages/default.aspx", "type": "html"},
    {"name": "VIC Health", "url": "https://www.health.vic.gov.au/media-releases", "type": "html"},
    {"name": "QLD Health", "url": "https://news.google.com/rss/search?q=Queensland+Health+private+hospital&hl=en-AU&gl=AU&ceid=AU:en", "type": "rss"}
]

def scrape_state_health() -> str:
    print("--- State Health Department Sites ---")

    all_articles = []

    for source in SOURCES:
        print(f"Fetching {source['name']}...")
        try:
            # qld uses google news rss since their site blocks scraping
            if source["type"] == "rss":
                feed = feedparser.parse(source["url"])
                count = 0
                for entry in feed.entries[:10]:
                    all_articles.append(f"[{source['name']}] {entry.title} ({entry.link})")
                    count += 1
                print(f"✓ {source['name']}: found {count} articles")

            else:
                response = requests.get(source["url"], headers=HEADERS, timeout=30)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    links = soup.find_all("a", href=True)

                    count = 0
                    for link in links:
                        text = link.get_text(strip=True)
                        href = link["href"]
                        if len(text) > 20:
                            if not href.startswith("http"):
                                base = "https://" + source["url"].split("/")[2]
                                href = base + "/" + href.lstrip("/")
                            all_articles.append(f"[{source['name']}] {text} ({href})")
                            count += 1
                            if count >= 10:
                                break
                    print(f"✓ {source['name']}: found {count} articles")
                else:
                    print(f"✗ {source['name']}: Failed {response.status_code}")

        except Exception as e:
            print(f"✗ {source['name']}: Error — {e}")

        time.sleep(2)

    return "\n".join(all_articles)

# --- Output Helpers ---
def build_payload(content: str) -> dict:
    return {
        "source":     SOURCE,
        "tier":       TIER,
        "dataset":    DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url":        "https://www.health.nsw.gov.au / https://www.health.vic.gov.au / https://www.health.qld.gov.au",
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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/state_health",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_state_health()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)