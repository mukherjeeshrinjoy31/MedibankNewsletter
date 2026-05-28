import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from playwright.sync_api import sync_playwright

from ...commons.data import ABC_NEWS_URL, NEWS_BOILERPLATE_PATTERNS, NEWS_URLS
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_content_list, build_payload, fetch_cutoff_date,
    fetch_run_date, is_boilerplate, matches_keywords,
    save_local, upload_to_s3
)

SOURCE = "abc"
MAX_ARTICLES = 40
SCROLL_PASSES = 4
ARTICLE_URL_PATTERN = re.compile(r"^/news/(?:.+/)?\d{4}-\d{2}-\d{2}/.+/\d+$")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_abc_date(page) -> Optional[datetime]:
    """Extract publication date from JSON-LD or meta tags."""
    try:
        raw = page.eval_on_selector_all(
            'script[type="application/ld+json"]',
            "els => els.map(el => el.textContent)"
        )
        for blob in raw:
            data = json.loads(blob)
            if isinstance(data, list):
                data = data[0]
            date_str = data.get("datePublished") or data.get("dateModified")
            if date_str:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
    except Exception:
        pass

    try:
        meta = page.get_attribute('meta[property="article:published_time"]', "content")
        if meta:
            dt = datetime.fromisoformat(meta.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def collect_links(page, url: str) -> List[dict]:
    """Scroll through a listing page and return all candidate article links."""
    logger.info("Scanning: %s", url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        for _ in range(SCROLL_PASSES):
            page.keyboard.press("End")
            page.wait_for_timeout(2_000)
    except Exception as exc:
        logger.warning("Failed to load %s: %s", url, exc)
        return []

    return page.eval_on_selector_all(
        "a[href*='/news/']",
        """elements => elements.map(el => ({
            text: el.innerText.trim().replace(/^result number \\d+\\s*/i, ''),
            href: el.getAttribute('href'),
            parentText: el.closest('article')
                        ?.querySelector('h1,h2,h3,h4')
                        ?.innerText?.trim()
                        || el.parentElement?.innerText?.trim()
                        || ''
        }))"""
    )


def fetch_article_body(page, url: str) -> Tuple[str, Optional[datetime]]:
    """Fetch article page and extract body text and publication date."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    except Exception as exc:
        logger.warning("Error loading article %s: %s", url, exc)
        return f"(Error loading article: {exc})", None

    pub_date = parse_abc_date(page)

    try:
        paragraphs = page.eval_on_selector_all(
            "article p",
            "els => els.map(el => el.innerText.trim()).filter(t => t.length > 30)"
        )
        paragraphs = [p for p in paragraphs if not is_boilerplate(p, NEWS_BOILERPLATE_PATTERNS["ABC"])]
        body = "\n\n".join(paragraphs) if paragraphs else "(Could not extract body)"
    except Exception as exc:
        logger.warning("Error extracting body from %s: %s", url, exc)
        body = f"(Error extracting body: {exc})"

    return body, pub_date


def scrape_abc_playwright(max_articles: int = MAX_ARTICLES) -> List[dict]:
    """Collect and filter ABC news articles using Playwright."""
    all_links: List[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        logger.info("Collecting article links...")
        for source_url in NEWS_URLS["ABC"]:
            links = collect_links(listing_page, source_url)
            logger.info("Got %d links from %s", len(links), source_url)
            all_links.extend(links)
        
        listing_page.close()

        seen_hrefs: set = set()
        candidates: List[dict] = []
        rejected = {"url_pattern": 0, "duplicate": 0, "short_headline": 0, "keyword": 0}

        for i, link in enumerate(all_links):

            if len(candidates) >= max_articles:
                break

            href = link.get("href", "")
            headline = link.get("text", "").strip()
            parent_text = link.get("parentText", "").strip()

            if href.startswith("https://www.abc.net.au"):
                href = href[len("https://www.abc.net.au"):]
            href = href.rstrip("/")

            if not ARTICLE_URL_PATTERN.match(href):
                rejected["url_pattern"] += 1
                continue
            if href in seen_hrefs:
                rejected["duplicate"] += 1
                continue
            if len(headline) < 15:
                rejected["short_headline"] += 1
                continue
            seen_hrefs.add(href)
            url = f"https://www.abc.net.au{href}"

            article_page = browser.new_page()
            try:
                body, pub_date = fetch_article_body(article_page, url)
            except Exception as exc:
                logger.info("Failed to fetch body for %s: %s", url, exc)
                continue
            finally:
                article_page.close()
            
            if not matches_keywords(headline + " " + parent_text + " " + body):
                rejected["keyword"] += 1
                continue
            
            logger.info("[%d] %s", i + 1, headline)
            if pub_date and pub_date < fetch_cutoff_date(7):
                    logger.info("Skipped (too old: %s)", pub_date.date())
                    continue

            candidates.append({
                "headline": headline,
                "url": url,
                "body": body,
                "pub_date": pub_date.isoformat() if pub_date else None,
            })

        browser.close()

    logger.info("\nTotal links: %d", len(all_links))
    logger.info("Rejections: %s", rejected)
    logger.info("Articles kept: %d", len(candidates))
    return candidates


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape ABC News articles and upload to S3 or save locally."""
    logger.info("Starting Playwright-based ABC News scraper")
    articles = scrape_abc_playwright(MAX_ARTICLES)

    if not articles:
        logger.warning("No matching articles found — skipping.")
        return False

    content = build_content_list(articles)
    logger.info("Extracted %d characters of text.", len(content))

    payload = build_payload(
        content,
        SOURCE,
        DATASET.NEWS.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        ABC_NEWS_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")