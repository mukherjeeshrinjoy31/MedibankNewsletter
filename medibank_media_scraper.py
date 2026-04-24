import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'medibank'
TIER    = 'medibank_specific'
DATASET = 'media_releases'
URL     = 'https://www.medibank.com.au/livebetter/newsroom/classification/media-releases'
BUCKET  = 'p000268ds-medibank-intelligence' 

# ── Boilerplate to strip ─────────────────────────────────────────
BOILERPLATE = [
    "These details are for journalist enquiries only.",
    "If you are a customer please call",
    "Copyright © 2026 Medibank Private Limited.",
    "All rights reserved.",
    "ABN 47 080 890 259.",
    "Read more",
]

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("medibank_media_scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── 7 Day Filter ────────────────────────────────────────────────
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)


# ── Step 1: Get all article links ───────────────────────────────
def get_article_links():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/livebetter/newsroom/post/" in href:
                full_url = "https://www.medibank.com.au" + href if href.startswith("/") else href
                if full_url not in links:
                    links.append(full_url)

        log.info(f"Found {len(links)} articles total")
        return links

    except Exception as e:
        log.error(f"Failed to get article links: {e}")
        return []


# ── Step 2: Clean boilerplate from text ─────────────────────────
def clean_text(text):
    for phrase in BOILERPLATE:
        text = text.replace(phrase, "")
    text = " ".join(text.split())
    return text.strip()


# ── Step 3: Scrape each article ─────────────────────────────────
def scrape_article(article_url):
    try:
        response = requests.get(article_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # 7 day filter
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            try:
                pub_date = datetime.fromisoformat(time_tag["datetime"])
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                if pub_date < CUTOFF_DATE:
                    log.info(f"  Skipping (older than 7 days): {article_url}")
                    return None
            except Exception as e:
                log.warning(f"  Could not parse date, including anyway: {e}")

        headline = soup.find("h1")
        headline_text = headline.get_text(strip=True) if headline else ""

        paragraphs = soup.find_all("p")
        body_text = " ".join(
            p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
        )

        full_text = clean_text(f"{headline_text}. {body_text}")

        if not full_text:
            log.warning(f"  Empty content after cleaning: {article_url}")
            return None

        return full_text

    except Exception as e:
        log.error(f"  Failed to scrape {article_url}: {e}")
        return None


# ── Step 3: Build payload ────────────────────────────────────────
def build_payload(articles):
    run_date = datetime.now(timezone.utc).isoformat()
    content_parts = [
        f"Source: {SOURCE} | Dataset: {DATASET} | Run Date: {run_date} | Articles: {len(articles)}"
    ]
    for i, text in enumerate(articles, 1):
        content_parts.append(f"{i}. {text}")

    return {
        'source':     SOURCE,
        'tier':       TIER,
        'dataset':    DATASET,
        'scraped_at': run_date,
        'url':        URL,
        'content':    "\n".join(content_parts),
    }


# ── Step 5: Save locally (swap for upload_to_s3 when ready) ─────
def save_locally(payload):
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    filename = f"{SOURCE}_{DATASET}_{date}.json"
    try:
        with open(filename, "w") as f:
            json.dump(payload, f, indent=2)
        log.info(f"Saved: {filename}")
    except Exception as e:
        log.error(f"Failed to save file: {e}")


# ── Step 6: Upload to S3 (uncomment when ready for S3) ──────────
# def upload_to_s3(payload):
#     import boto3
#     s3   = boto3.client('s3', region_name='ap-southeast-2')
#     date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
#     key  = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{date}.json"
#     s3.put_object(Bucket=BUCKET, Key=key,
#                   Body=json.dumps(payload, ensure_ascii=False),
#                   ContentType='application/json')
#     log.info(f'Uploaded: s3://{BUCKET}/{key}')


# ── Main ─────────────────────────────────────────────────────────
def scrape():
    links = get_article_links()

    if not links:
        log.error("No links found — skipping this run")
        return []

    articles = []
    for link in links:
        log.info(f"Scraping: {link}")
        text = scrape_article(link)
        if text:
            articles.append(text)
        time.sleep(1)

    log.info(f"{len(articles)} articles within the last 7 days")
    return articles


if __name__ == '__main__':
    log.info("=" * 50)
    log.info(f"Starting scrape: {SOURCE} / {DATASET}")
    log.info("=" * 50)

    articles = scrape()

    if not articles:
        log.warning("No articles found — file will not be saved")
    else:
        payload = build_payload(articles)
        save_locally(payload)
        # swap to upload_to_s3(payload) when ready for S3

    log.info("Scrape complete")
