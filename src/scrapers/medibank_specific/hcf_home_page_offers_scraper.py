import logging
import sys
from typing import Optional

from ...commons.dataset import DATASET
from ...commons.tiers import TIER

from ...commons.data import BOILERPLATE, HCF_URL, OFFER_KEYWORDS
from ...utils.helpers import build_payload, clean_text, fetch_run_date, fetch_url, load_last_offer, save_current_offer, save_local, upload_to_s3

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'hcf'

# File to store last week's offer for comparison
LAST_OFFER_FILE = 'offer_files/hcf_last_offer.txt'

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("hcf_offers.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Step 1: Scrape hero banner ───────────────────────────────────
def scrape() -> str:
    try:
        soup = fetch_url(HCF_URL)

        h1 = soup.find("h1")
        if not h1:
            log.warning("No h1 found on page")
            return None

        parent = h1.find_parent()
        if not parent:
            log.warning("No parent found for h1")
            return None

        text = clean_text(parent.get_text(separator=" ", strip=True), BOILERPLATE["HCF"])
        if not text:
            log.warning("No text found in hero banner")
            return None

        log.info(f"Extracted hero banner: {text[:100]}...")

        # ── Check for promotional offer ──────────────────────────
        has_offer = any(word in text.lower() for word in OFFER_KEYWORDS)
        offer_detection = "PROMOTION DETECTED" if has_offer else "NO CURRENT PROMOTION FOUND"
        log.info(f"Offer detection: {offer_detection}")

        # ── Compare with last week ───────────────────────────────
        last_offer = load_last_offer(LAST_OFFER_FILE)
        if last_offer and last_offer == text:
            offer_status = "OFFER STATUS: UNCHANGED from last week"
            log.info("Offer unchanged from last week")
        else:
            offer_status = "OFFER STATUS: NEW or CHANGED this week"
            log.info("Offer is new or changed this week")

        # Save current offer for next week's comparison
        save_current_offer(text, LAST_OFFER_FILE)

        content = (
            f"Source: {SOURCE} | Dataset: {DATASET} | "
            f"Run Date: {fetch_run_date()}\n\n"
            f"{offer_detection}\n"
            f"{offer_status}\n\n"
            f"HCF Hero Banner:\n\n"
            f"{text}"
        )

        return content

    except Exception as e:
        log.error(f"Failed to scrape HCF hero banner: {e}")
        return None


def run(local: Optional[str] = None) -> bool:
    print(f"Scraping offers from competitor HBF from: \n  {HCF_URL} \n")
    content = scrape()
    print(f"\nExtracted {len(content):,} characters of text.")
    payload = build_payload(
        content,
        SOURCE,
        DATASET.CUSTOMER_OFFERS.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        HCF_URL  
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True   
