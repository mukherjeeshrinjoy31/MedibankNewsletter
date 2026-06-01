import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict

import pdfplumber
import requests
from bs4 import BeautifulSoup

from ...commons.data import ASX_NIB_ANNOUNCEMENTS_URL, BOILERPLATE, HEADERS, NIB_ASX_SKIP_TITLES
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "nib"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_date_from_parent(title: str, parent) -> tuple:
    """Extract publication date from parent element text and clean it from title."""
    date_text = ""
    if parent:
        parent_text = parent.get_text(separator="|", strip=True)
        date_match = re.search(
            r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
            parent_text
        )
        if date_match:
            date_text = date_match.group(1)
            title = title.replace(date_text, "").strip()
    return title, date_text


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def get_announcement_links() -> List[Dict]:
    """Scrape NIB ASX announcements page and return links within the 7-day cutoff."""
    soup = fetch_url(ASX_NIB_ANNOUNCEMENTS_URL)
    if not soup:
        logger.error("Could not fetch NIB announcements page.")
        return []

    announcements = []

    for a in soup.find_all("a", href=True):
        href = a["href"]

        if "/docs/" not in href:
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        if any(junk in title for junk in NIB_ASX_SKIP_TITLES):
            continue

        parent = a.find_parent()
        title, date_text = extract_date_from_parent(title, parent)

        if date_text:
            try:
                pub_date = datetime.strptime(date_text, "%d %B %Y").replace(tzinfo=timezone.utc)
                if pub_date < fetch_cutoff_date(7):
                    logger.info("Skipping (older than 7 days): %s", title)
                    continue
            except Exception as e:
                logger.warning("Could not parse date '%s': %s", date_text, e)

        full_url = f"https://www.nib.com.au{href}" if href.startswith("/") else href
        announcements.append({"title": title, "date": date_text, "url": full_url})
        logger.info("Found: %s — %s", title, date_text)

    logger.info("Found %d announcements within last 7 days", len(announcements))
    return announcements


def get_pdf_content(announcement_url: str) -> Optional[bytes]:
    """Follow an announcement URL and return PDF bytes if found."""
    try:
        response = requests.get(announcement_url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        if "application/pdf" in response.headers.get("Content-Type", ""):
            return response.content

        soup = BeautifulSoup(response.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.endswith(".pdf"):
                pdf_url = f"https://www.nib.com.au{href}" if href.startswith("/") else href
                logger.info("Found PDF: %s", pdf_url)
                pdf_response = requests.get(pdf_url, headers=HEADERS, timeout=15)
                pdf_response.raise_for_status()
                return pdf_response.content

        if response.content[:4] == b'%PDF':
            return response.content

        logger.warning("No PDF found at: %s", announcement_url)
        return None

    except Exception as e:
        logger.error("Failed to get PDF from %s: %s", announcement_url, e)
        return None


def extract_pdf_text(pdf_content: bytes) -> Optional[str]:
    """Extract and clean text from PDF bytes."""
    try:
        text = ""
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        for phrase in BOILERPLATE["NIB"]:
            text = text.replace(phrase, "")

        text = text.encode("utf-8", errors="ignore").decode("utf-8")
        return " ".join(text.split()).strip()

    except Exception as e:
        logger.error("Failed to extract PDF text: %s", e)
        return None


def scrape() -> Optional[str]:
    """Scrape all recent NIB ASX announcements and return combined content."""
    announcements = get_announcement_links()

    if not announcements:
        logger.warning("No announcements found within last 7 days.")
        return None

    all_content = []

    for i, announcement in enumerate(announcements):
        title = announcement["title"]
        date  = announcement["date"]
        logger.info("Processing (%d/%d): %s", i + 1, len(announcements), title)

        pdf_content = get_pdf_content(announcement["url"])
        if pdf_content:
            text = extract_pdf_text(pdf_content)
            if text:
                all_content.append(f"{i+1}. {title} — {date}\n{text}")
                logger.info("Extracted %d characters", len(text))
            else:
                all_content.append(f"{i+1}. {title} — {date}")
                logger.warning("PDF extraction failed, using title only.")
        else:
            all_content.append(f"{i+1}. {title} — {date}")
            logger.warning("No PDF found, using title only.")

        time.sleep(1)

    return (
        f"Source: {SOURCE} | Dataset: {DATASET.ASX_ANNOUNCEMENTS.value} | "
        f"Run Date: {fetch_run_date()} | Announcements: {len(all_content)}\n\n"
        + "\n\n".join(all_content)
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape NIB ASX announcements and upload to S3 or save locally."""
    logger.info("Scraping NIB ASX Announcements from: %s", ASX_NIB_ANNOUNCEMENTS_URL)
    content = scrape()

    if not content:
        logger.warning("No announcements found within last 7 days — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
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


if __name__ == "__main__":
    run(local="data")