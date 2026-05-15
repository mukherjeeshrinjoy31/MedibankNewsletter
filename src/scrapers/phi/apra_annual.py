import os

from typing import Optional
from ...commons.data import APRA_ANNUAL_STATISTICS_URL, APRA_BASE_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.apra_helpers import download_and_extract
from ...utils.helpers import build_payload, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE   = "apra"

def scrape_apra_annual() -> str:
    print("--- APRA Annual Stats ---")

    soup = fetch_url(APRA_ANNUAL_STATISTICS_URL)

    xlsx_links = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if ".xlsx" in href.lower():
            if not href.startswith("http"):
                href = APRA_BASE_URL + href
            xlsx_links.append((link.get_text(strip=True), href))

    print(f"Found {len(xlsx_links)} XLSX files")
    os.makedirs("data/apra", exist_ok=True)

    content = download_and_extract(xlsx_links, "APRA Annual Private Health Insurance Statistics\n\n")

    if not xlsx_links:
        print("No links found — page likely uses JavaScript.")
        content += f"Could not extract links dynamically. Check: {APRA_ANNUAL_STATISTICS_URL}\n"

    return content.strip()   

def run(local: Optional[str] = None) -> bool:
    print(f"Starting PHI Scrapper for APRA from : {APRA_ANNUAL_STATISTICS_URL}")
    content = scrape_apra_annual()  
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.PHI_ANNUAL.value,
        fetch_run_date(),
        TIER.PHI.value,
        APRA_ANNUAL_STATISTICS_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True