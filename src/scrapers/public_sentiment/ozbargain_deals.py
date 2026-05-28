import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional, List, Dict

import requests

from ...commons.data import DATE_FORMATS, HEADERS, OZBARGAIN_URL, RSS_FEED_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_run_date, save_local, upload_to_s3
from ...utils.html import strip_html

SOURCE = "ozbargain"

NS = {"ozb": OZBARGAIN_URL}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string using known formats, falling back to fromisoformat."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), DATE_FORMATS[3])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(date_str.strip())
    except ValueError:
        pass
    logger.warning("Unrecognised date format: %r", date_str)
    return None


def _ozb_attr(item: ET.Element, tag: str, attr: str) -> Optional[str]:
    """Extract an attribute from an OzBargain-namespaced XML element."""
    el = item.find(f"ozb:{tag}", NS)
    return (el.get(attr) or "").strip() if el is not None else ""


def to_int(val: str) -> int:
    """Safely convert a string to int, returning 0 on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def parse_vote_count(item: ET.Element) -> Dict:
    """Extract positive, negative and net vote counts from a feed item."""
    pos = to_int(_ozb_attr(item, "meta", "votes-pos"))
    neg = to_int(_ozb_attr(item, "meta", "votes-neg"))
    return {"votes_pos": pos, "votes_neg": neg, "votes_net": pos - neg}


def parse_category(item: ET.Element) -> str:
    """Extract the category text from a feed item."""
    el = item.find("category", NS)
    return (el.text or "").strip() if el is not None else ""


def parse_coupon_code(description_text: str) -> Optional[str]:
    """Extract a coupon or promo code from deal description text."""
    m = re.search(r"\[([A-Z0-9_\-]{3,30})\]", description_text)
    if m:
        return m.group(1)
    m = re.search(r"(?:promo|coupon|code)[:\s]+([A-Z0-9_\-]{3,30})", description_text, re.I)
    if m:
        candidate = m.group(1)
        if candidate == candidate.upper():
            return candidate
    return None


def is_active(expiry_date: Optional[datetime]) -> bool:
    """Return True if the deal has not yet expired."""
    if expiry_date is None:
        return False
    return expiry_date > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_feed(feed_url: str) -> List[dict]:
    """Fetch and parse OzBargain RSS feed, returning filtered deals."""
    try:
        response = requests.get(feed_url, timeout=10, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error("Error fetching feed %s: %s", feed_url, e)
        return []

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        logger.error("Error parsing XML from feed %s: %s", feed_url, e)
        return []

    items = root.findall(".//item")
    if not items:
        logger.warning("No <item> elements found in feed.")
        return []

    logger.info("Found %d items in feed — applying cutoff filter...", len(items))

    deals = []
    for item in items:
        def _text(tag: str, _item=item) -> str:
            el = _item.find(tag)
            return (el.text or "").strip() if el is not None else ""

        title        = strip_html(_text("title"))
        deal_url     = _text("link") or _text("guid")
        pub_date_str = _text("pubDate")
        description  = strip_html(_text("description"))

        expiry_str  = _ozb_attr(item, "meta", "expiry")
        expiry_date = parse_date(expiry_str) if expiry_str else None
        pub_date    = parse_date(pub_date_str)

        within_cutoff = pub_date and pub_date >= fetch_cutoff_date(30)
        still_active  = is_active(expiry_date)

        if not still_active and not within_cutoff:
            logger.info("Skipped (old & expired): %s", title)
            continue

        vote_count      = parse_vote_count(item)
        category        = parse_category(item)
        coupon_code     = parse_coupon_code(description)
        destination_url = _ozb_attr(item, "meta", "url")
        date_iso        = pub_date.isoformat() if pub_date else pub_date_str
        date_str        = pub_date.strftime("%d %B %Y") if pub_date else None

        deals.append({
            "title":           title,
            "deal_url":        deal_url,
            "destination_url": destination_url,
            "date_str":        date_str,
            "date_iso":        date_iso,
            "expiry_date":     expiry_date.isoformat() if expiry_date else None,
            "still_active":    still_active,
            **vote_count,
            "category":        category,
            "coupon_code":     coupon_code,
            "description":     description,
        })
        logger.info("Fetched deal: %s", title)

    return deals


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape OzBargain Medibank deals and upload to S3 or save locally."""
    logger.info("Scraping Medibank deals from OzBargain RSS feed: %s", OZBARGAIN_URL)
    deals = fetch_feed(RSS_FEED_URL)

    if not deals:
        logger.warning("No deals found within the cutoff date.")
        return False

    logger.info("Found %d deals.", len(deals))
    payload = build_payload(
        deals,
        SOURCE,
        DATASET.DEALS.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        OZBARGAIN_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")