import io
import os
import shutil
import zipfile
from typing import Optional

import pandas as pd
import pdfplumber
import requests
import xml.etree.ElementTree as ET

from ...commons.data import HEADERS, PRIVATE_HEALTH_FALLBACK_ZIP_URL, PRIVATE_HEALTH_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, extract_pdf_text, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE     = "privatehealth"
OUTPUT_DIR = "data/privatehealth"
SKIP_EXTS  = {".xsd", ".txt"}


def read_csv(filepath: str) -> str:
    """Read a CSV file and return as formatted string."""
    try:
        df = pd.read_csv(filepath, nrows=50)
        df = df.dropna(how="all")
        df = df.fillna("")
        return df.to_csv(index=False)
    except Exception as e:
        return f"Could not read CSV: {e}"


def read_xml(filepath: str) -> str:
    """Extract text content from an XML file."""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        lines = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                lines.append(f"{tag}: {elem.text.strip()}")
        return "\n".join(lines[:200])
    except Exception as e:
        return f"Could not read XML: {e}"


def read_file(filepath: str) -> str:
    """Route file to appropriate reader based on extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in SKIP_EXTS:
        return ""
    elif ext == ".csv":
        return read_csv(filepath)
    elif ext == ".xml":
        return read_xml(filepath)
    elif ext == ".pdf":
        return extract_pdf_text(filepath)
    return ""


def scrape_privatehealth() -> str:
    """Download and extract PHI product ZIP, read all files, return combined content."""
    print("--- PrivateHealth.gov.au ZIP ---")
    print("Finding latest ZIP file...")

    soup = fetch_url(PRIVATE_HEALTH_URL)
    zip_url = None
    if soup:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".zip" in href.lower() and "privatehealth" in href.lower():
                zip_url = href
                break

    if not zip_url:
        print("Couldn't find ZIP dynamically — using known fallback URL")
        zip_url = PRIVATE_HEALTH_FALLBACK_ZIP_URL

    print(f"Downloading: {zip_url}")
    r = requests.get(zip_url, headers=HEADERS, timeout=60)

    content = "PrivateHealth.gov.au Monthly Product Data\n\n"

    if r.status_code != 200:
        print(f"✗ Failed: {r.status_code}")
        return (content + "Download failed. Check data.gov.au manually.").strip()

    print("✓ ZIP downloaded! Extracting...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(OUTPUT_DIR)
        extracted = z.namelist()

    print(f"✓ Extracted {len(extracted)} files")

    for filename in extracted:
        ext = os.path.splitext(filename)[1].lower()
        if ext in SKIP_EXTS:
            continue

        filepath = os.path.join(OUTPUT_DIR, filename)
        print(f"Reading: {filename}...")
        text = read_file(filepath)

        if text:
            content += f"=== {filename} ===\n{text}\n\n"
            print(f"✓ {filename} — {len(text):,} chars extracted")

    shutil.rmtree(OUTPUT_DIR)
    print(f"Deleted folder: {OUTPUT_DIR}")

    return content.strip()


def run(local: Optional[str] = None) -> bool:
    """Scrape PHI product data and upload to S3 or save locally."""
    print(f"Starting PHI Scraper for private health from: {PRIVATE_HEALTH_URL}")
    content = scrape_privatehealth()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PRODUCTS.value,
        fetch_run_date(),
        TIER.PHI.value,
        PRIVATE_HEALTH_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)