import io
import re
from typing import Optional
import pdfplumber
from datetime import datetime
from urllib.parse import urlparse

from ...commons.data import AMA_REPORT_URL, AMA_SOURCE_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, download_pdf, fetch_cutoff_date, fetch_run_date, fetch_url, parse_date, save_local, upload_to_s3

# ---- Config ------------------------------------------------------
SOURCE = "ama" # Australian Medical Association
KEYWORD = "private health insurance"
DATE_FORMATS = ["%d %B %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y"]

def get_report_publish_date(report_url: str) -> Optional[datetime]:
    soup = fetch_url(report_url)
 
    time_tag = soup.find("time")
    if time_tag:
        pub_date = parse_date(time_tag.get("datetime", ""), DATE_FORMATS) or parse_date(time_tag.get_text(), DATE_FORMATS)
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

def find_report_url(listing_url: str, keyword: str) -> str:
    soup = fetch_url(listing_url)
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
        raise RuntimeError(
            f"No report titles matching '{keyword}' found on: {listing_url}"
        )
 
    dated_candidates: list[tuple[datetime, str, str]] = []   # (pub_date, title, href)
    undated_candidates: list[tuple[str, str]] = []            # (title, href)
 
    for anchor in candidates:
        title = anchor.get_text(strip=True)
        href = anchor.get("href", "")
        if not href:
            continue
 
        if href.startswith("/"):
            href = base_url + href
 
        print(f"Checking report: '{title}'\n  {href}")
        pub_date = get_report_publish_date(href)
 
        if pub_date:
            if pub_date >= fetch_cutoff_date(7):
                print(f"  Within range ({pub_date.date()}) - using this report.")
                return href
            print(f"  Outside 30-day range ({pub_date.date()}) - noting as fallback.")
            dated_candidates.append((pub_date, title, href))
        else:
            print("  Warning: could not determine publish date. Noting as fallback.")
            undated_candidates.append((title, href))
 
    # fall back to the most recent dated report
    if dated_candidates:
        dated_candidates.sort(key=lambda x: x[0], reverse=True)
        most_recent_date, most_recent_title, most_recent_href = dated_candidates[0]
        print(
            f"\nNo reports within the last 30 days. "
            f"Falling back to most recent: '{most_recent_title}' ({most_recent_date.date()})"
        )
        return most_recent_href
 
    # use the first undated candidate if all reports are undated
    if undated_candidates:
        title, href = undated_candidates[0]
        print(f"\nNo dated reports found. Falling back to first candidate: '{title}'")
        return href
 
    print(f"No valid report URLs found for keyword '{keyword}' on: {listing_url}. Skipping.")
    return None

def find_pdf_url(page_url: str) -> str:
    soup = fetch_url(page_url)

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

def scrape() -> Optional[str]:
    report_page_url = find_report_url(AMA_REPORT_URL, KEYWORD)
    if not report_page_url:
        return None
    pdf_url = find_pdf_url(report_page_url)
    pdf_bytes = download_pdf(pdf_url)
    text = extract_text_from_pdf(pdf_bytes)

    if not text.strip():
        raise RuntimeError("PDF text extraction returned empty content.")
    return text

def run(local: Optional[str] = None) -> bool:
    print(f"Scraping AMA Private Health Insurance Report Card from: \n  {AMA_SOURCE_URL} \n")
    content = scrape()
    if content is None:
        print("Nothing to upload. Exiting.")
        exit(1)
    print(f"\nExtracted {len(content):,} characters of text.")
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