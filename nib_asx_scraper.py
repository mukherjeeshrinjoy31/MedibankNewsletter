import io
import json
import time
import logging
import requests
import pdfplumber
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'nib'
TIER    = 'medibank_specific'
DATASET = 'asx_announcements'
URL     = 'https://www.nib.com.au/shareholders/announcements'
BUCKET  = 'p000268ds-medibank-intelligence'

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Boilerplate to strip ─────────────────────────────────────────
BOILERPLATE = [
    "Copyright © 2026 nib health funds limited",
    "ABN 83 000 124 381",
    "Terms & Conditions",
    "Privacy Policy",
    "Code of Conduct",
    "All of the documents below are in PDF format",
    "Reconciliation Action Plan",
]

# ── Junk titles to skip ──────────────────────────────────────────
SKIP_TITLES = [
    "View our Reconciliation Action Plan",
    "Terms & Conditions",
    "Privacy Policy",
    "Code of Conduct",
]

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

# Fix Windows terminal encoding
import sys
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 7 Day Filter ────────────────────────────────────────────────
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=30)


# ── Step 1: Get announcement links from the main page ────────────
def get_announcement_links():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        announcements = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if "/docs/" not in href:
                continue

            title = a.get_text(strip=True)
            if not title:
                continue

            # Skip junk titles
            if any(junk in title for junk in SKIP_TITLES):
                continue

            # The date sits in a separate element after the link
            # Look at the parent element text to find the date
            date_text = ""
            parent = a.find_parent()
            if parent:
                parent_text = parent.get_text(separator="|", strip=True)
                # Date format is like "8 April 2026"
                import re
                date_match = re.search(
                    r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
                    parent_text
                )
                if date_match:
                    date_text = date_match.group(1)
                    # Clean date from title if it got merged in
                    title = title.replace(date_text, "").strip()

            # 7 day filter
            if date_text:
                try:
                    pub_date = datetime.strptime(date_text, "%d %B %Y")
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    if pub_date < CUTOFF_DATE:
                        log.info(f"  Skipping (older than 7 days): {title}")
                        continue
                except Exception as e:
                    log.warning(f"  Could not parse date '{date_text}': {e}")

            # Build full URL
            full_url = f"https://www.nib.com.au{href}" if href.startswith("/") else href

            announcements.append({
                "title": title,
                "date":  date_text,
                "url":   full_url
            })
            log.info(f"  Found: {title} — {date_text}")

        log.info(f"Found {len(announcements)} announcements within last 7 days")
        return announcements

    except Exception as e:
        log.error(f"Failed to get announcement links: {e}")
        return []


# ── Step 2: Follow link and find the actual PDF URL ──────────────
def get_pdf_content(announcement_url):
    try:
        response = requests.get(announcement_url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        # Check if redirected directly to PDF
        if "application/pdf" in response.headers.get("Content-Type", ""):
            return response.content

        # Parse page to find a PDF link
        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".pdf"):
                pdf_url = f"https://www.nib.com.au{href}" if href.startswith("/") else href
                log.info(f"  Found PDF: {pdf_url}")
                pdf_response = requests.get(pdf_url, headers=HEADERS, timeout=15)
                pdf_response.raise_for_status()
                return pdf_response.content

        # Try if raw response is a PDF
        if response.content[:4] == b'%PDF':
            return response.content

        log.warning(f"  No PDF found at: {announcement_url}")
        return None

    except Exception as e:
        log.error(f"  Failed to get PDF from {announcement_url}: {e}")
        return None


# ── Step 3: Extract text from PDF ────────────────────────────────
def extract_pdf_text(pdf_content):
    try:
        text = ""
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        # Clean boilerplate
        for phrase in BOILERPLATE:
            text = text.replace(phrase, "")

        # Clean up encoding artifacts
        text = text.encode("utf-8", errors="ignore").decode("utf-8")
        text = " ".join(text.split()).strip()
        return text

    except Exception as e:
        log.error(f"  Failed to extract PDF text: {e}")
        return None


# ── Step 4: Scrape all announcements ────────────────────────────
def scrape():
    announcements = get_announcement_links()

    if not announcements:
        log.warning("No announcements found within last 7 days")
        return None

    all_content = []

    for i, announcement in enumerate(announcements):
        title = announcement['title']
        date  = announcement['date']
        log.info(f"Processing ({i+1}/{len(announcements)}): {title}")

        pdf_content = get_pdf_content(announcement["url"])

        if pdf_content:
            text = extract_pdf_text(pdf_content)
            if text:
                all_content.append(f"{i+1}. {title} — {date}\n{text}")
                log.info(f"  Extracted {len(text)} characters")
            else:
                all_content.append(f"{i+1}. {title} — {date}")
                log.warning(f"  PDF extraction failed, using title only")
        else:
            all_content.append(f"{i+1}. {title} — {date}")
            log.warning(f"  No PDF found, using title only")

        time.sleep(1)

    run_date = datetime.now(timezone.utc).isoformat()
    content = (
        f"Source: {SOURCE} | Dataset: {DATASET} | "
        f"Run Date: {run_date} | "
        f"Announcements: {len(all_content)}\n\n"
        + "\n\n".join(all_content)
    )

    return content


# ── Step 5: Build payload ────────────────────────────────────────
def build_payload(content: str) -> dict:
    return {
        'source':     SOURCE,
        'tier':       TIER,
        'dataset':    DATASET,
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'url':        URL,
        'content':    content,
    }


# ── Step 6: Save locally ─────────────────────────────────────────
def save_locally(payload: dict) -> None:
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    filename = f"{SOURCE}_{DATASET}_{date}.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"Saved: {filename}")
    except Exception as e:
        log.error(f"Failed to save file: {e}")


# ── Step 7: Upload to S3 (uncomment when ready) ──────────────────
# def upload_to_s3(payload: dict) -> None:
#     import boto3
#     s3   = boto3.client('s3', region_name='ap-southeast-2')
#     date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
#     key  = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{date}.json"
#     s3.put_object(Bucket=BUCKET, Key=key,
#                   Body=json.dumps(payload, ensure_ascii=False),
#                   ContentType='application/json')
#     log.info(f'Uploaded: s3://{BUCKET}/{key}')


# ── Main ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("=" * 50)
    log.info(f"Starting scrape: {SOURCE} / {DATASET}")
    log.info("=" * 50)

    content = scrape()

    if not content:
        log.warning("No content found — file will not be saved")
    else:
        payload = build_payload(content)
        save_locally(payload)
        # swap to upload_to_s3(payload) when ready for S3

    log.info("Scrape complete")
