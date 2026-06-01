import io
import logging
import re
from datetime import datetime
from typing import Optional, List, Tuple
from urllib.parse import urlparse

import pdfplumber

from ...commons.data import AMA_REPORT_URL, AMA_SOURCE_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_payload, download_pdf, fetch_cutoff_date,
    fetch_run_date, fetch_url, parse_date,
    save_local, upload_to_s3
)

SOURCE = "ama"
KEYWORD = "private health insurance"
DATE_FORMATS = ["%d %B %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_report_publish_date(report_url: str) -> Optional[datetime]:
    """Extract publication date from a report page."""
    soup = fetch_url(report_url)
    if not soup:
        logger.warning("Could not fetch report page: %s", report_url)
        return None

    time_tag = soup.find("time")
    if time_tag:
        pub_date = (
            parse_date(time_tag.get("datetime", ""), DATE_FORMATS)
            or parse_date(time_tag.get_text(), DATE_FORMATS)
        )
        if pub_date:
            return pub_date

    for node in soup.find_all(string=re.compile(r"^\s*Published\s*$", re.IGNORECASE)):
        sibling = node.find_next(string=True)
        while sibling and not sibling.strip():
            sibling = sibling.find_next(string=True)
        if sibling:
            pub_date = parse_date(sibling.strip())
            if pub_date:
                return pub_date

    date_pattern = re.compile(
        r"\b(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})\b"
    )
    for text_node in soup.stripped_strings:
        m = date_pattern.search(text_node)
        if m:
            pub_date = parse_date(m.group(1))
            if pub_date:
                return pub_date

    return None


def find_report_url(listing_url: str, keyword: str) -> Optional[str]:
    """Find the most relevant report URL from the AMA listing page."""
    soup = fetch_url(listing_url)
    if not soup:
        logger.error("Could not fetch listing page: %s", listing_url)
        return None

    parsed_base = urlparse(listing_url)
    base_url = f"{parsed_base.scheme}://{parsed_base.netloc}"

    candidates = soup.find_all("a", string=re.compile(keyword, re.IGNORECASE))
    if not candidates:
        candidates = [
            a for a in soup.find_all("a")
            if a.get_text(strip=True)
            and re.search(keyword, a.get_text(strip=True), re.IGNORECASE)
        ]

    if not candidates:
        logger.error("No report titles matching '%s' found on: %s", keyword, listing_url)
        return None

    dated_candidates: List[Tuple[datetime, str, str]] = []
    undated_candidates: List[Tuple[str, str]] = []

    for anchor in candidates:
        title = anchor.get_text(strip=True)
        href = anchor.get("href", "")
        if not href:
            continue

        if href.startswith("/"):
            href = base_url + href

        logger.info("Checking report: '%s'\n  %s", title, href)
        pub_date = get_report_publish_date(href)

        if pub_date:
            if pub_date >= fetch_cutoff_date(7):
                logger.info("Within range (%s) - using this report.", pub_date.date())
                return href
            logger.info("Outside 7-day range (%s) - noting as fallback.", pub_date.date())
            dated_candidates.append((pub_date, title, href))
        else:
            logger.warning("Could not determine publish date for '%s'. Noting as fallback.", title)
            undated_candidates.append((title, href))

    # Fall back to most recent dated report
    if dated_candidates:
        dated_candidates.sort(key=lambda x: x[0], reverse=True)
        most_recent_date, most_recent_title, most_recent_href = dated_candidates[0]
        logger.info(
            "No reports within the last 30 days. Falling back to most recent: '%s' (%s)",
            most_recent_title, most_recent_date.date()
        )
        return most_recent_href

    # Fall back to first undated candidate
    if undated_candidates:
        title, href = undated_candidates[0]
        logger.info("No dated reports found. Falling back to first candidate: '%s'", title)
        return href

    logger.warning("No valid report URLs found for keyword '%s' on: %s", keyword, listing_url)
    return None


def find_pdf_url(page_url: str) -> Optional[str]:
    """Find the PDF download link on a report page."""
    soup = fetch_url(page_url)
    if not soup:
        logger.error("Could not fetch report page: %s", page_url)
        return None

    pdf_link = soup.find("a", href=re.compile(r"\.pdf$", re.IGNORECASE))
    if not pdf_link:
        logger.error("No PDF link found on page: %s", page_url)
        return None

    href = pdf_link["href"]
    if href.startswith("/"):
        parsed = urlparse(page_url)
        href = f"{parsed.scheme}://{parsed.netloc}{href}"

    logger.info("Found PDF: %s", href)
    return href


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract and clean text from PDF bytes."""
    pages_text = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        logger.info("Extracting text from %d pages...", len(pdf.pages))
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                cleaned = re.sub(r" \n {3,}", " \n\n ", text.strip())
                pages_text.append(cleaned)

    return " \n\n ".join(pages_text)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape() -> Optional[str]:
    """Find, download and extract text from the latest AMA PHI report."""
    report_page_url = find_report_url(AMA_REPORT_URL, KEYWORD)
    if not report_page_url:
        return None

    pdf_url = find_pdf_url(report_page_url)
    if not pdf_url:
        return None

    pdf_bytes = download_pdf(pdf_url)
    if not pdf_bytes:
        logger.error("Failed to download PDF from: %s", pdf_url)
        return None

    text = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        logger.error("PDF text extraction returned empty content.")
        return None

    return text


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape AMA PHI report and upload to S3 or save locally."""
    logger.info("Scraping AMA Private Health Insurance Report Card from: %s", AMA_SOURCE_URL)
    content = scrape()

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_REPORT.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        AMA_SOURCE_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")