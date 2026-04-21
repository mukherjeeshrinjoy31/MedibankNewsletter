import io
import json
import re
import boto3
import requests
import pdfplumber
import argparse
from datetime import datetime, timezone
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ---- Config ------------------------------------------------------
SOURCE = "ama"
DATASET = "phi_report"
TIER   = "public-sentiment"
URL    = "https://www.ama.com.au/articles/ama-private-health-insurance-report-card-2025"
BUCKET  = "p000268ds-medibank-intelligence"
# ------------------------------------------------------------------
HEADERS = {"User-Agent": "Mozilla/5.0"}

def find_pdf_url(page_url: str) -> str:

    try:
        response = requests.get(page_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Error fetching URL: {e}") from e

    soup = BeautifulSoup(response.text, "html.parser")

    pdf_link = soup.find("a", href=re.compile(r"\.pdf$", re.IGNORECASE))
    if not pdf_link:
        raise RuntimeError(f"No PDF link found on page: {page_url}")

    href = pdf_link["href"]

    # Handle relative URLs
    if href.startswith("/"):
        parsed = urlparse(page_url)
        href = f"{parsed.scheme}://{parsed.netloc}{href}"

    print(f"Found PDF: {href}")
    return href


def download_pdf(pdf_url: str) -> bytes:
    response = requests.get(pdf_url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    print(f"Downloaded PDF ({len(response.content) / 1024:.0f} KB)")
    return response.content


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    pages_text = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        print(f"Extracting text from {len(pdf.pages)} pages...")
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text:
                cleaned = re.sub(r" \n {3,}", " \n\n ", text.strip())
                pages_text.append(cleaned)

    return " \n\n ".join(pages_text)


def scrape() -> str:
    pdf_url = find_pdf_url(URL)
    pdf_bytes = download_pdf(pdf_url)
    text = extract_text_from_pdf(pdf_bytes)

    if not text.strip():
        raise RuntimeError("PDF text extraction returned empty content.")

    return text


def build_payload(content: str) -> dict:
    return {
        "source":     SOURCE,
        "tier":       TIER,
        "dataset":    DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url":        URL,
        "content":    content
    }


def upload_to_s3(payload: dict) -> None:
    s3 = boto3.client("s3", region_name="ap-southeast-2")
    key = (
        f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")


def save_local(payload: dict, directory: str = ".") -> None:
    import os
    os.makedirs(directory, exist_ok=True)
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{run_date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AMA PHI Report Card scraper")
    parser.add_argument(
        "--local",
        metavar="DIR",
        nargs="?",
        const=".",
        help="Save JSON locally to DIR instead of uploading to S3 (default: current directory)",
    )
    args = parser.parse_args()

    print(f"Scraping AMA Private Health Insurance Report Card from: \n  {URL} \n")
    content = scrape()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(content)

    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)

# run "python ama.py --local" to save locally to a "data" directory instead of uploading to S3