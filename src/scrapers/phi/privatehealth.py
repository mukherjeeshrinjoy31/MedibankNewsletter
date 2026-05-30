import io
import logging
import os
import shutil
import zipfile
from typing import Optional

import pandas as pd
import requests
import xml.etree.ElementTree as ET

from ...commons.data import HEADERS, PRIVATE_HEALTH_FALLBACK_ZIP_URL, PRIVATE_HEALTH_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, extract_pdf_text, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE     = "privatehealth"
OUTPUT_DIR = "data/privatehealth"
SKIP_EXTS  = {".xsd", ".txt"}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File Readers
# ---------------------------------------------------------------------------

def read_csv(filepath: str) -> str:
    """Read a CSV file and return as formatted string."""
    try:
        df = pd.read_csv(filepath, nrows=50)
        df = df.dropna(how="all")
        df = df.fillna("")
        return df.to_csv(index=False)
    except Exception as e:
        logger.exception("Could not read CSV %s: %s", filepath, e)
        return ""


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
        logger.exception("Could not read XML %s: %s", filepath, e)
        return ""


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


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_privatehealth() -> str:
    """Download and extract PHI product ZIP, read all files, return combined content."""
    logger.info("--- PrivateHealth.gov.au ZIP ---")
    logger.info("Finding latest ZIP file...")

    soup = fetch_url(PRIVATE_HEALTH_URL)
    zip_url = None
    if soup:
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if ".zip" in href.lower() and "privatehealth" in href.lower():
                zip_url = href
                break

    if not zip_url:
        logger.warning("Could not find ZIP dynamically — using fallback URL.")
        zip_url = PRIVATE_HEALTH_FALLBACK_ZIP_URL

    logger.info("Downloading: %s", zip_url)

    try:
        r = requests.get(zip_url, headers=HEADERS, timeout=60)
    except Exception as e:
        logger.exception("Failed to download ZIP: %s", e)
        return ""

    if r.status_code != 200:
        logger.error("Failed to download ZIP: HTTP %s", r.status_code)
        return ""

    logger.info("✓ ZIP downloaded! Extracting...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        z.extractall(OUTPUT_DIR)
        extracted = z.namelist()

    logger.info("✓ Extracted %d files", len(extracted))

    content = "PrivateHealth.gov.au Monthly Product Data\n\n"

    for filename in extracted:
        ext = os.path.splitext(filename)[1].lower()
        if ext in SKIP_EXTS:
            continue

        filepath = os.path.join(OUTPUT_DIR, filename)
        logger.info("Reading: %s...", filename)
        text = read_file(filepath)

        if text:
            content += f"=== {filename} ===\n{text}\n\n"
            logger.info("✓ %s — %d chars extracted", filename, len(text))

    shutil.rmtree(OUTPUT_DIR)
    logger.info("Deleted folder: %s", OUTPUT_DIR)

    return content.strip()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape PHI product data and upload to S3 or save locally."""
    logger.info("Starting PHI Scraper for private health from: %s", PRIVATE_HEALTH_URL)
    content = scrape_privatehealth()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
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
    return True


if __name__ == "__main__":
    run(local="data")