import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, List, Dict

from bs4 import BeautifulSoup

from ...commons.data import INSURANCE_AWARD_URLS, INSURANCE_PROVIDERS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE = "canstar"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def medibank_mentioned(soup: BeautifulSoup) -> bool:
    """Check if Medibank is mentioned anywhere on the page."""
    return INSURANCE_PROVIDERS in soup.get_text().lower()


def extract_page_meta(soup: BeautifulSoup, url: str) -> Dict:
    """Extract page metadata — title, release date and key stats."""
    meta = {"url": url}

    title_el = soup.find("h1")
    if title_el:
        meta["title"] = title_el.get_text(strip=True)

    released_date = soup.find(string=lambda t: t and "Released:" in t)
    if released_date:
        meta["released_date"] = released_date.strip()

    stats = [
        li.get_text(separator=" ", strip=True)
        for li in soup.select("ul li")
        if any(kw in li.get_text() for kw in [
            "providers assessed", "profiles considered",
            "policy variations", "award-winning"
        ])
    ]
    if stats:
        meta["key_stats"] = stats

    return meta


def is_within_cutoff(meta: Dict) -> bool:
    """Return True if the award was released within the cutoff window or has no date."""
    released_date = meta.get("released_date", "")
    if not released_date:
        return True
    try:
        date_str = released_date.replace("Released:", "").strip()
        release_dt = datetime.strptime(date_str, "%d %B, %Y").replace(tzinfo=timezone.utc)
        return release_dt >= fetch_cutoff_date(7)
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Award Extraction
# ---------------------------------------------------------------------------

def extract_medibank_awards(soup: BeautifulSoup) -> List[Dict]:
    """
    Extract Medibank award entries from the page.

    Tries three strategies in order:
      1. Text-based h4 headings with award titles
      2. Image logo with award type in nearby div/span (fallback)
      3. Image alt text with nearby group-title span (fallback)
    """
    awards_list = []

    # Strategy 1 — text-based h4 headings
    for h4 in soup.select("h4"):
        link = h4.find("a")
        if not link:
            continue

        provider = link.get_text(strip=True)
        if INSURANCE_PROVIDERS not in provider.lower():
            continue

        full_text = h4.get_text(strip=True)
        awards_raw = full_text[len(provider):]
        awards = [
            a.strip()
            for a in re.split(r"(?=Outstanding Value Award)", awards_raw)
            if a.strip()
        ]

        desc_el = h4.find_next_sibling("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        awards_list.append({
            "provider": provider,
            "awards": awards,
            "description": description
        })

    # Strategy 2 — image logo with award type in nearby div/span
    if not awards_list:
        for article in soup.find_all("article"):
            img = article.find("img")
            if not img:
                continue

            img_src = img.get("src", "") + " " + img.get("srcset", "")
            if INSURANCE_PROVIDERS not in img_src.lower():
                continue

            award_type_div = article.find("div")
            award_type = award_type_div.get_text(strip=True) if award_type_div else "Award Winner"

            category_span = article.find("span")
            category = category_span.get_text(strip=True) if category_span else ""
            award_title = f"{award_type} – {category}" if category else award_type

            desc_el = article.find("p")
            description = desc_el.get_text(strip=True) if desc_el else ""

            src_filename = img.get("src", "").split("/")[-1]
            provider_name = urllib.parse.unquote(src_filename).split(" Logo")[0].split(".")[0]

            awards_list.append({
                "provider": provider_name if provider_name else "Medibank",
                "awards": [award_title],
                "description": description,
            })

    # Strategy 3 — image alt text with nearby group-title span
    if not awards_list:
        for img in soup.find_all("img", alt=True):
            if INSURANCE_PROVIDERS not in img["alt"].lower():
                continue

            award_title = "Award Winner"
            for parent in img.parents:
                group_title = parent.find("span", class_="group-title")
                if group_title:
                    award_title = group_title.get_text(strip=True)
                    break

            awards_list.append({
                "provider": img["alt"],
                "awards": [award_title],
                "description": "",
            })

    return awards_list


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_all_insurance_awards() -> List[Dict]:
    """Scrape all Canstar award pages and return Medibank award entries."""
    results = []

    for url in INSURANCE_AWARD_URLS:
        logger.info("Checking: %s", url)
        soup = fetch_url(url)
        if soup is None:
            logger.warning("Could not fetch page: %s — skipping", url)
            continue

        if not medibank_mentioned(soup):
            logger.info("Medibank not mentioned — skipping.")
            continue

        meta = extract_page_meta(soup, url)
        if not is_within_cutoff(meta):
            logger.info("Award released before cutoff date — skipping.")
            continue

        awards_list = extract_medibank_awards(soup)
        if not awards_list:
            logger.info("Medibank mentioned but no awards found — skipping.")
            continue

        logger.info("Extracting awards from: %s", url)
        results.append({
            **meta,
            "medibank_awards": awards_list,
        })

    return results


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape Canstar insurance awards and upload to S3 or save locally."""
    logger.info("Starting Canstar Health Awards scraper")
    content = scrape_all_insurance_awards()

    if not content:
        logger.warning("Medibank not found on any award page — skipping.")
        return False

    payload = build_payload(
        content,
        SOURCE,
        DATASET.AWARDS.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        INSURANCE_AWARD_URLS
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")