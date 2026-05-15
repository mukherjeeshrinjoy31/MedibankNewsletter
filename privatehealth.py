import requests
import zipfile
import io
import os
import json
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "privatehealth"
DATASET = "products"
TIER    = "phi_industry"
URL     = "https://data.gov.au/data/dataset/private-health-insurance"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_privatehealth() -> str:
    print("--- PrivateHealth.gov.au ZIP ---")

    # find the latest zip link on the page dynamically
    print("Finding latest ZIP file...")
    response = requests.get(URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(response.text, "html.parser")

    zip_url = None
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if ".zip" in href.lower() and "privatehealth" in href.lower():
            zip_url = href
            break

    # fallback just in case
    if not zip_url:
        print("Couldn't find ZIP dynamically — using known fallback URL")
        zip_url = "https://data.gov.au/data/dataset/8ab10b1f-6eac-423c-abc5-bbffc31b216c/resource/ca9c9e9f-a114-4e9a-a29f-6b3f641b8e6f/download/privatehealth-01-mar-2026.zip"

    print(f"Downloading: {zip_url}")
    r = requests.get(zip_url, headers=HEADERS, timeout=60)

    content = "PrivateHealth.gov.au Monthly Product Data\n\n"

    if r.status_code == 200:
        print("✓ ZIP downloaded! Extracting...")
        os.makedirs("data/privatehealth", exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            z.extractall("data/privatehealth/")
            extracted = z.namelist()

        print(f"✓ Extracted {len(extracted)} files")
        content += "Files extracted:\n"
        for f in extracted:
            content += f"- {f}\n"
        content += "\nCovers all registered PHI products from 29 insurers — prices, tiers, exclusions, hospital agreements."
    else:
        print(f"✗ Failed: {r.status_code}")
        content += "Download failed. Check data.gov.au manually."

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
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/privatehealth",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    content = scrape_privatehealth()
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)