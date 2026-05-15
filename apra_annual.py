import requests
import os
import json
import time
import argparse
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE   = "apra"
DATASET  = "phi_annual"
TIER     = "phi_industry"
URL      = "https://www.apra.gov.au/operations-of-private-health-insurers-annual-report"
BUCKET   = "p000268ds-medibank-intelligence-us"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

def scrape_apra_annual() -> str:
    print("--- APRA Annual Stats ---")

    # grab the page and look for xlsx links
    response = requests.get(URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(response.text, "html.parser")

    xlsx_links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if ".xlsx" in href.lower():
            if not href.startswith("http"):
                href = "https://www.apra.gov.au" + href
            xlsx_links.append((link.get_text(strip=True), href))

    print(f"Found {len(xlsx_links)} XLSX files")
    os.makedirs("data/apra", exist_ok=True)

    content = "APRA Annual Private Health Insurance Statistics\n\n"

    # download and extract top 5
    for title, href in xlsx_links[:5]:
        filename = href.split("/")[-1]
        print(f"Downloading: {filename}...")
        try:
            r = requests.get(href, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                filepath = f"data/apra/{filename}"
                with open(filepath, "wb") as f:
                    f.write(r.content)
                try:
                    df = pd.read_excel(filepath, sheet_name=0, nrows=20)
                    content += f"=== {title} ===\n"
                    content += df.to_string(index=False) + "\n\n"
                    print(f"✓ {filename}")
                except Exception:
                    content += f"=== {title} ===\nDownloaded but could not extract text. URL: {href}\n\n"
            else:
                print(f"✗ Failed: {r.status_code}")
        except Exception as e:
            print(f"✗ Error: {e}")
        time.sleep(1)

    if not xlsx_links:
        print("No links found — page likely uses JavaScript.")
        content += f"Could not extract links dynamically. Check: {URL}\n"

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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/apra",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_apra_annual()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)