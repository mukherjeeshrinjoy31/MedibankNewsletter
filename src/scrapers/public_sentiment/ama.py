import io
import re
import pdfplumber
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Optional
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...commons.data import AMA_SOURCE_URL, HEADERS
from ...utils.helpers import build_payload, download_pdf, fetch_url, save_local, upload_to_s3

# ------------------------------------------------------------------
SOURCE = "ama"

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

def scrape() -> str:
    pdf_url = find_pdf_url(AMA_SOURCE_URL)
    pdf_bytes = download_pdf(pdf_url)
    text = extract_text_from_pdf(pdf_bytes)

    if not text.strip():
        raise RuntimeError("PDF text extraction returned empty content.")
    return text

def run(local: Optional[str] = None) -> bool:
    print(f"Scraping AMA Private Health Insurance Report Card from: \n  {AMA_SOURCE_URL} \n")
    content = scrape()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_REPORT.value,
        datetime.now(timezone.utc).isoformat(),
        TIER.PUBLIC_SENTIMENT.value,
        AMA_SOURCE_URL
    )

    if local:
        save_local(payload, local)
    else:
        upload_to_s3(payload)
    return True

# run "python ama.py --local" to save locally to a "data" directory instead of uploading to S3