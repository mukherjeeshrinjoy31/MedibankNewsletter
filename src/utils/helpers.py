import shutil

import boto3
import json
import os
import requests
import time
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from typing import Optional
from ..commons.config import AWS_REGION, BUCKET, EXPECTED_BUCKET_OWNER
from ..commons.data import HEADERS, BOILERPLATE

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("nib_asx_announcements.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

def clean_text(text, boiler_plate):
    for phrase in boiler_plate:
        text = text.replace(phrase, "")
    text = " ".join(text.split())
    return text.strip()  

def fetch_run_date():
    return datetime.now(timezone.utc).isoformat()

def fetch_cutoff_date(n_days: int):
    return datetime.now(timezone.utc) - timedelta(days=n_days)

def build_payload(content: str, source: str, dataset: str, scrapped_at: datetime, tier: str, url: str) -> dict:
    return {
        'source': source,
        'tier': tier,
        'dataset': dataset,
        'scraped_at': scrapped_at,
        'url': url,
        'content': content
    }

def upload_to_s3(payload: dict) -> None:
    s3  = boto3.client("s3", region_name=AWS_REGION)
    key = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    s3.put_object(
        Bucket=BUCKET, 
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType='application/json',
        ExpectedBucketOwner=EXPECTED_BUCKET_OWNER
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")

import os
import json
from datetime import datetime, timezone

def save_local(payload: dict) -> str:
    """
    Save payload to data/{tier}/{source}_{dataset}_{dataset}_{run_date}.json.
    Does NOT delete the data directory.
    Returns the full path of the saved file.
    """
    # Build directory path
    tier_dir = os.path.join("data", payload["tier"])
    os.makedirs(tier_dir, exist_ok=True)

    # Build run date
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build filename
    dataset = payload["dataset"]
    filename = f"{payload['source']}_{dataset}_{dataset}_{run_date}.json"
    path = os.path.join(tier_dir, filename)

    # Write file
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"Saved locally: {path}")

def download_pdf(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    print(f"Downloaded PDF ({len(response.content) / 1024:.0f} KB)")
    return response.content

def fetch_article_links(search_tag_url: str, base_url: str, url: str):
    try:
        soup = fetch_url(url)
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if search_tag_url in href:
                full_url = base_url + href if href.startswith("/") else href
                if full_url not in links:
                    links.append(full_url)

        log.info(f"Found {len(links)} articles total")
        return links
    except Exception as e:
        log.error(f"Failed to get article links: {e}")
        return []

def fetch_url(url: str) -> Optional[BeautifulSoup]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        time.sleep(1)  # Be polite to the server
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None
    

# ── Helper: load last week's offer ──────────────────────────────
def load_last_offer(last_offer_file):
    try:
        if os.path.exists(last_offer_file):
            with open(last_offer_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        log.warning(f"Could not load last offer: {e}")
    return None


# ── Helper: save this week's offer ──────────────────────────────
def save_current_offer(offer_text, path):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)   # ← FIX
        with open(path, "w", encoding="utf-8") as f:
            f.write(offer_text)
    except Exception as e:
        log.warning(f"Could not save current offer: {e}")
