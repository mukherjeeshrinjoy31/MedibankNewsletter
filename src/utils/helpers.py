import boto3
import json
import os
import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from typing import Optional
from ..commons.config import AWS_REGION, BUCKET, EXPECTED_BUCKET_OWNER
from ..commons.data import HEADERS

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

def save_local(payload: dict, directory: str = ".") -> None:
    os.makedirs(directory, exist_ok=True)
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{run_date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}") 

def download_pdf(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    print(f"Downloaded PDF ({len(response.content) / 1024:.0f} KB)")
    return response.content

def fetch_url(url: str) -> Optional[BeautifulSoup]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        time.sleep(1)  # Be polite to the server
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None