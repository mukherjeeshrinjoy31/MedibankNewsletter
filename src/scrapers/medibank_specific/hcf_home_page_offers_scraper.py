import json
import logging
import requests
import sys
import os
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'hcf'
TIER    = 'medibank_specific'
DATASET = 'customer_offers'
URL     = 'https://www.hcf.com.au'
BUCKET  = 'p000268ds-medibank-intelligence'

# File to store last week's offer for comparison
LAST_OFFER_FILE = 'hcf_last_offer.txt'

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Boilerplate to strip ─────────────────────────────────────────
BOILERPLATE = [
    "Get a quote",
    "Compare cover",
    "Get a quick quote",
    "Chat to us",
    "Login",
]

# ── Offer keywords ───────────────────────────────────────────────
OFFER_KEYWORDS = ["free", "weeks", "gift", "discount", "save", "offer ends", "%", "bonus"]

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


# ── Helper: clean text ───────────────────────────────────────────
def clean(text):
    for phrase in BOILERPLATE:
        text = text.replace(phrase, "")
    return " ".join(text.split()).strip()


# ── Helper: load last week's offer ──────────────────────────────
def load_last_offer():
    try:
        if os.path.exists(LAST_OFFER_FILE):
            with open(LAST_OFFER_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception as e:
        log.warning(f"Could not load last offer: {e}")
    return None


# ── Helper: save this week's offer ──────────────────────────────
def save_current_offer(offer_text):
    try:
        with open(LAST_OFFER_FILE, "w", encoding="utf-8") as f:
            f.write(offer_text)
    except Exception as e:
        log.warning(f"Could not save current offer: {e}")


# ── Step 1: Scrape hero banner ───────────────────────────────────
def scrape() -> str:
    try:
        response = requests.get(URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        h1 = soup.find("h1")
        if not h1:
            log.warning("No h1 found on page")
            return None

        parent = h1.find_parent()
        if not parent:
            log.warning("No parent found for h1")
            return None

        text = clean(parent.get_text(separator=" ", strip=True))
        if not text:
            log.warning("No text found in hero banner")
            return None

        log.info(f"Extracted hero banner: {text[:100]}...")

        # ── Check for promotional offer ──────────────────────────
        has_offer = any(word in text.lower() for word in OFFER_KEYWORDS)
        offer_detection = "PROMOTION DETECTED" if has_offer else "NO CURRENT PROMOTION FOUND"
        log.info(f"Offer detection: {offer_detection}")

        # ── Compare with last week ───────────────────────────────
        last_offer = load_last_offer()
        if last_offer and last_offer == text:
            offer_status = "OFFER STATUS: UNCHANGED from last week"
            log.info("Offer unchanged from last week")
        else:
            offer_status = "OFFER STATUS: NEW or CHANGED this week"
            log.info("Offer is new or changed this week")

        # Save current offer for next week's comparison
        save_current_offer(text)

        run_date = datetime.now(timezone.utc).isoformat()
        content = (
            f"Source: {SOURCE} | Dataset: {DATASET} | "
            f"Run Date: {run_date}\n\n"
            f"{offer_detection}\n"
            f"{offer_status}\n\n"
            f"HCF Hero Banner:\n\n"
            f"{text}"
        )

        return content

    except Exception as e:
        log.error(f"Failed to scrape HCF hero banner: {e}")
        return None


# ── Step 2: Build payload ────────────────────────────────────────
def build_payload(content: str) -> dict:
    return {
        'source':     SOURCE,
        'tier':       TIER,
        'dataset':    DATASET,
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'url':        URL,
        'content':    content,
    }


# ── Step 3: Save locally ─────────────────────────────────────────
def save_locally(payload: dict) -> None:
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    filename = f"{SOURCE}_{DATASET}_{date}.json"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        log.info(f"Saved: {filename}")
    except Exception as e:
        log.error(f"Failed to save file: {e}")


# ── Step 4: Upload to S3 (uncomment when ready) ──────────────────
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
