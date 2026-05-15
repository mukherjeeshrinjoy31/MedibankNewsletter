import requests
import os
import json
import time
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "newsrooms"
DATASET = "competitor_news"
TIER    = "phi_industry"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# competitor newsroom urls
SOURCES = [
    {"name": "Bupa",  "url": "https://media.bupa.com.au/"},
    {"name": "NIB",   "url": "https://www.nib.com.au/media"},
    {"name": "HCF",   "url": "https://www.hcf.com.au/about-us/media-centre/media-releases"},
    {"name": "HBF",   "url": "https://www.hbf.com.au/about-hbf/newsroom"}
]

def scrape_newsrooms() -> str:
    print("--- Competitor Newsrooms ---")

    all_articles = []

    for source in SOURCES:
        print(f"Fetching {source['name']}...")
        try:
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
                            href = source["url"].rstrip("/") + "/" + href.lstrip("/")
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
        "url":        " / ".join([s["url"] for s in SOURCES]),
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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/newsrooms",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_newsrooms()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)