import logging
from typing import Optional

from ...commons.config import MODE_AWS, MODE_LOCAL

from ...commons.data import BOILERPLATE, HBF_URL, OFFER_KEYWORDS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_payload, clean_text, fetch_run_date, fetch_url,
    load_last_offer, save_current_offer, save_local, upload_to_s3
)

SOURCE          = "hbf"
LAST_OFFER_FILE = "data/newsletter/offer_txt/hbf_last_offer.txt"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape(local=None) -> Optional[str]:
    """Scrape HBF hero banner and detect current promotional offer."""
    soup = fetch_url(HBF_URL)
    if not soup:
        logger.error("fetch_url returned None for HBF page.")
        return None

    h1 = soup.find("h1")
    if not h1:
        logger.warning("No h1 found on page.")
        return None

    parent = h1.find_parent()
    if not parent:
        logger.warning("No parent found for h1.")
        return None

    text = clean_text(parent.get_text(separator=" ", strip=True), BOILERPLATE["HBF"])
    if not text:
        logger.warning("No text found in hero banner.")
        return None

    logger.info("Extracted hero banner: %s...", text[:100])

    has_offer = any(word in text.lower() for word in OFFER_KEYWORDS)
    offer_detection = "PROMOTION DETECTED" if has_offer else "NO CURRENT PROMOTION FOUND"
    logger.info("Offer detection: %s", offer_detection)

    mode = MODE_LOCAL if local else MODE_AWS
    last_offer = load_last_offer(LAST_OFFER_FILE, mode=mode, s3_prefix="raw/newsletter/offer_txt")
    if last_offer and last_offer == text:
        offer_status = "OFFER STATUS: UNCHANGED from last week"
        logger.info("Offer unchanged from last week.")
    else:
        offer_status = "OFFER STATUS: NEW or CHANGED this week"
        logger.info("Offer is new or changed this week.")

    save_current_offer(text, LAST_OFFER_FILE, mode=mode, s3_prefix="raw/newsletter/offer_txt")

    return (
        f"Source: {SOURCE} | Dataset: {DATASET.CUSTOMER_OFFERS.value} | "
        f"Run Date: {fetch_run_date()}\n\n"
        f"{offer_detection}\n"
        f"{offer_status}\n\n"
        f"HBF Hero Banner:\n\n"
        f"{text}"
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape HBF offers and upload to S3 or save locally."""
    logger.info("Scraping offers from competitor HBF from: %s", HBF_URL)
    content = scrape(local)                  # ✅ pass local

    if not content:
        logger.warning("No content extracted — skipping.")
        return False

    logger.info("Extracted %d characters of text.", len(content))
    payload = build_payload(
        content,
        SOURCE,
        DATASET.CUSTOMER_OFFERS.value,
        fetch_run_date(),
        TIER.MEDIBANK_SPECIFIC.value,
        HBF_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")