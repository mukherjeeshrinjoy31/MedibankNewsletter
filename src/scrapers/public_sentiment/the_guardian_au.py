import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

from playwright.sync_api import sync_playwright

from ...commons.data import EXCLUDED_SECTIONS, GUARDIAN_NEWS_URL, NEWS_BOILERPLATE_PATTERNS, NEWS_URLS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_content_list, build_payload, fetch_cutoff_date,
    fetch_run_date, is_boilerplate, matches_keywords,
    save_local, upload_to_s3
)

SOURCE       = "guardian"
MAX_ARTICLES = 20
SCROLL_PASSES = 4

ARTICLE_URL_PATTERN = re.compile(r"^/(?:[a-z0-9\-]+/)*\d{4}/[a-z]{3}/\d{2}/[a-z0-9][a-z0-9\-]*$")
_URL_DATE_RE = re.compile(r"/(\d{4})/([a-z]{3})/(\d{2})/")

# JS that collects article card data in one round-trip
_CARD_JS = """
elements => {
    const seen = new Set();
    const results = [];

    for (const el of elements) {
        let href = el.getAttribute('href') || '';

        if (href.startsWith('https://www.theguardian.com')) {
            href = href.slice('https://www.theguardian.com'.length);
        }

        if (!href.startsWith('/')) continue;
        if (href.endsWith('/all')) continue;
        if (href.includes('#')) continue;
        if (seen.has(href)) continue;
        seen.add(href);

        const card = el.closest('article')
                  || el.closest('[class*="card"]')
                  || el.closest('[class*="container"]')
                  || el.closest('li')
                  || el.parentElement;

        let headline = '';
        if (card) {
            const h = card.querySelector('h1,h2,h3,h4');
            if (h) headline = h.innerText.trim();
        }
        if (!headline) {
            headline = (el.getAttribute('aria-label') || el.innerText || '').trim();
        }

        const timeEl = card ? card.querySelector('time[datetime]') : null;
        const datetime = timeEl ? timeEl.getAttribute('datetime') : null;
        const cardText = card ? card.innerText : '';

        results.push({ href, headline, datetime, cardText });
    }
    return results;
}
"""

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_excluded_section(href: str) -> bool:
    """Return True if the URL path belongs to an excluded section."""
    parts = href.strip("/").split("/")
    return any(seg in EXCLUDED_SECTIONS for seg in parts)


def date_from_url(href: str) -> Optional[datetime]:
    """Parse the date embedded in a Guardian URL path (e.g. /2026/apr/27/)."""
    m = _URL_DATE_RE.search(href)
    if not m:
        return None
    try:
        raw = f"{m.group(3)} {m.group(2)} {m.group(1)}"
        return datetime.strptime(raw, "%d %b %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def date_from_str(raw_dt: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 datetime string."""
    if not raw_dt:
        return None
    try:
        dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


def extract_pub_date(page) -> Optional[datetime]:
    """
    Extract publication date from a Guardian article page.

    Tries three strategies in order:
      1. JSON-LD structured data
      2. article:published_time meta tag
      3. article-scoped <time datetime> elements
    """
    # Strategy 1 — JSON-LD structured data
    try:
        blobs = page.eval_on_selector_all(
            'script[type="application/ld+json"]',
            "els => els.map(el => el.textContent)"
        )
        for blob in blobs:
            data = json.loads(blob)
            if isinstance(data, list):
                data = data[0]
            date_str = data.get("datePublished") or data.get("dateCreated")
            if date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        pass

    # Strategy 2 — article:published_time meta tag
    try:
        meta = page.get_attribute('meta[property="article:published_time"]', "content")
        if meta:
            dt = datetime.fromisoformat(meta.replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        pass

    # Strategy 3 — article-scoped <time> elements
    try:
        attrs = page.eval_on_selector_all(
            "article time[datetime]",
            "els => els.map(el => el.getAttribute('datetime'))"
        )
        candidates = []
        for attr in attrs:
            try:
                dt = datetime.fromisoformat(attr.replace("Z", "+00:00"))
                candidates.append(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
            except ValueError:
                pass
        if candidates:
            return min(candidates)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def collect_links_paginated(
    page,
    url: str,
    max_pages: int = 10,
    cutoff: Optional[datetime] = None
) -> List[Dict]:
    """Paginate through a Guardian listing page and collect valid article links."""
    all_links: List[Dict] = []

    for page_num in range(1, max_pages + 1):
        paginated_url = f"{url}?page={page_num}"
        logger.info("Scanning: %s", paginated_url)

        try:
            page.goto(paginated_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3_000)
            for _ in range(SCROLL_PASSES):
                page.keyboard.press("End")
                page.wait_for_timeout(2_000)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", paginated_url, exc)
            break

        raw_cards = page.eval_on_selector_all("a[href*='/202']", _CARD_JS)
        if not raw_cards:
            logger.info("No links found on page %d — stopping.", page_num)
            break

        page_links: List[Dict] = []

        for card in raw_cards:
            href = card.get("href", "")

            if not ARTICLE_URL_PATTERN.match(href):
                continue
            if is_excluded_section(href):
                continue

            pub_date = date_from_str(card.get("datetime")) or date_from_url(href)

            # Skip persistent footer junk with old dates
            if pub_date and pub_date.year < 2024:
                continue

            page_links.append({
                "href": href,
                "headline": card.get("headline", "").strip(),
                "cardText": card.get("cardText", ""),
                "pub_date": pub_date.isoformat() if pub_date else None,
            })

        all_links.extend(page_links)

        dated = [l for l in page_links if l["pub_date"]]
        old = [
            l for l in dated
            if cutoff and datetime.fromisoformat(l["pub_date"]) < cutoff
        ]

        logger.info(
            "Page %d: %d links (%d dated, %d older than cutoff)",
            page_num, len(page_links), len(dated), len(old)
        )

        if cutoff and dated and len(old) == len(dated):
            logger.info("All dated links older than cutoff — stopping pagination.")
            break

    return all_links


def fetch_article_body(page, url: str) -> Tuple[str, Optional[datetime]]:
    """Fetch a Guardian article page and extract body text and publication date."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
    except Exception as exc:
        logger.warning("Error loading article %s: %s", url, exc)
        return f"(Error loading article: {exc})", None

    pub_date = extract_pub_date(page)

    try:
        paragraphs = page.eval_on_selector_all(
            "article p",
            "els => els.map(el => el.innerText.trim()).filter(t => t.length > 30)"
        )
        paragraphs = [p for p in paragraphs if not is_boilerplate(p, NEWS_BOILERPLATE_PATTERNS["GUARDIAN"])]
        body = "\n\n".join(paragraphs) if paragraphs else "(Could not extract body)"
    except Exception as exc:
        logger.warning("Error extracting body from %s: %s", url, exc)
        body = f"(Error extracting body: {exc})"

    return body, pub_date


def scrape_guardian(max_articles: int = MAX_ARTICLES) -> List[Dict]:
    """Collect and filter Guardian AU articles using Playwright."""
    all_links: List[Dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        logger.info("Collecting article links...")
        for source_url in NEWS_URLS["GUARDIAN"]:
            links = collect_links_paginated(
                listing_page, source_url,
                max_pages=10,
                cutoff=fetch_cutoff_date(7)
            )
            logger.info("%d links from %s", len(links), source_url)
            all_links.extend(links)

        seen_hrefs: set = set()
        candidates: List[Dict] = []
        rejected = {"duplicate": 0, "short_headline": 0, "keyword": 0, "too_old": 0}

        for link in all_links:
            href = link["href"]
            headline = link["headline"]
            card_text = link.get("cardText", "")
            pub_date_str = link.get("pub_date")

            if href in seen_hrefs:
                rejected["duplicate"] += 1
                continue
            if len(headline) < 15:
                rejected["short_headline"] += 1
                continue
            if not matches_keywords(headline + " " + card_text):
                rejected["keyword"] += 1
                continue
            if pub_date_str:
                try:
                    if datetime.fromisoformat(pub_date_str) < fetch_cutoff_date(7):
                        rejected["too_old"] += 1
                        continue
                except Exception:
                    pass

            seen_hrefs.add(href)
            candidates.append({
                "headline": headline,
                "url": f"https://www.theguardian.com{href}",
                "body": "",
                "pub_date": pub_date_str,
            })

        logger.info("Total links collected: %d", len(all_links))
        logger.info("Rejections: %s", rejected)
        logger.info("Candidates: %d — fetching top %d", len(candidates), max_articles)

        candidates = candidates[:max_articles]
        article_page = browser.new_page()
        kept: List[Dict] = []

        for i, article in enumerate(candidates):
            logger.info("[%d/%d] %s", i + 1, len(candidates), article["headline"][:65])

            body, pub_date = fetch_article_body(article_page, article["url"])
            article["body"] = body

            # Use listing-page date as fallback if article page date not found
            if pub_date is None and article["pub_date"]:
                try:
                    pub_date = datetime.fromisoformat(article["pub_date"])
                except Exception:
                    pass

            if pub_date is None:
                logger.info("Skipped (could not determine date)")
                continue
            if pub_date < fetch_cutoff_date(7):
                logger.info("Skipped (too old: %s)", pub_date.date())
                continue

            article["pub_date"] = pub_date.isoformat()
            kept.append(article)

        browser.close()

    logger.info("Articles kept: %d", len(kept))
    return kept


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape Guardian AU articles and upload to S3 or save locally."""
    logger.info("Starting Playwright-based Guardian AU scraper")
    articles = scrape_guardian(MAX_ARTICLES)

    if not articles:
        logger.warning("No matching articles found — skipping.")
        return False

    content = build_content_list(articles)
    logger.info("Extracted %d articles.", len(content))

    payload = build_payload(
        content,
        SOURCE,
        DATASET.NEWS.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        GUARDIAN_NEWS_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")