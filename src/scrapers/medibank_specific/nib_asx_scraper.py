import io
import json
import time
import logging
from typing import Optional
import re
import requests
import pdfplumber
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from ...commons.data import ASX_NIB_ANNOUNCEMENTS_URL, BOILERPLATE, HEADERS, NIB_ASX_SKIP_TITLES
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_run_date, fetch_url, save_local, upload_to_s3

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'nib'

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

# ── Step 1: Get announcement links from the main page ────────────
def get_announcement_links():
    try:
        soup = fetch_url(ASX_NIB_ANNOUNCEMENTS_URL)
        announcements = []

        for a in soup.find_all("a", href=True):
            href = a["href"]

            if "/docs/" not in href:
                continue

            title = a.get_text(strip=True)
            if not title:
                continue

            # Skip junk titles
            if any(junk in title for junk in NIB_ASX_SKIP_TITLES):
                continue

            # The date sits in a separate element after the link
            # Look at the parent element text to find the date
            date_text = ""
            parent = a.find_parent()
            title, date_text = extract_date_from_parent(title, parent)

            # 7 day filter
            if date_text:
                try:
                    pub_date = datetime.strptime(date_text, "%d %B %Y")
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                    if pub_date < fetch_cutoff_date(7):
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

def extract_date_from_parent(title, parent):
    if parent:
        parent_text = parent.get_text(separator="|", strip=True)
                # Date format is like "8 April 2026"
        date_match = re.search(
                    r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
                    parent_text
                )
        if date_match:
            date_text = date_match.group(1)
                    # Clean date from title if it got merged in
            title = title.replace(date_text, "").strip()
    return title,date_text


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
        for phrase in BOILERPLATE['NIB']:
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
                log.warning("  PDF extraction failed, using title only")
        else:
            all_content.append(f"{i+1}. {title} — {date}")
            log.warning("  No PDF found, using title only")

        time.sleep(1)

    content = (
        f"Source: {SOURCE} | Dataset: {DATASET.ASX_ANNOUNCEMENTS} | "
        f"Run Date: {fetch_run_date()} | "
        f"Announcements: {len(all_content)}\n\n"
        + "\n\n".join(all_content)
    )

    return content


def run(local: Optional[str] = None) -> bool:
    print(f"Scraping Medibank Specific Sources (NIB ASX Announcements) from: \n  {ASX_NIB_ANNOUNCEMENTS_URL} \n")
    content = scrape()

    if not content:
        print("No announcements found within last 7 days — skipping.")
        return False

    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.ASX_ANNOUNCEMENTS.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        ASX_NIB_ANNOUNCEMENTS_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True
