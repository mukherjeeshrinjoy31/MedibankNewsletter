import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

from playwright.sync_api import sync_playwright

from ...commons.data import NEWS_BOILERPLATE_PATTERNS, NEWS_URLS, SBS_NEWS_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import (
    build_payload, fetch_cutoff_date, fetch_run_date,
    is_boilerplate, matches_keywords, parse_date,
    save_local, upload_to_s3
)

SOURCE       = "sbs"
MAX_ARTICLES = 20
SCROLL_PASSES = 4
ARTICLE_URL_PATTERN = re.compile(r"^/news/article/[a-z0-9][a-z0-9\-]+/[a-z0-9]+$")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_pub_date_from_page(page) -> Optional[datetime]:
    """
    Extract publication date from an SBS article page.

    Tries three strategies in order:
      1. article-scoped <time datetime> elements
      2. "Published DD Month YYYY" text in article body
      3. parse_date on full page body text
    """
    pub_date = None

    # Strategy 1 — article-scoped <time> elements, take earliest (= publish date)
    try:
        time_attrs = page.eval_on_selector_all(
            "article time[datetime]",
            "els => els.map(el => el.getAttribute('datetime'))"
        )
        candidates = []
        for attr in time_attrs:
            try:
                dt = datetime.fromisoformat(attr.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                candidates.append(dt)
            except ValueError:
                pass
        if candidates:
            pub_date = min(candidates)
    except Exception:
        pass

    # Strategy 2 — "Published DD Month YYYY" text pattern
    if pub_date is None:
        try:
            body_text = page.inner_text("article") or ""
            match = re.search(
                r"[Pp]ublished\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
                body_text
            )
            if match:
                raw = f"{match.group(1)} {match.group(2)} {match.group(3)}"
                for fmt in ("%d %b %Y", "%d %B %Y"):
                    try:
                        pub_date = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
        except Exception:
            pass

    # Strategy 3 — parse_date on full page text
    if pub_date is None:
        try:
            pub_date = parse_date(page.inner_text("body") or "")
        except Exception:
            pass

    return pub_date


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def collect_links_paginated(
    page,
    url: str,
    max_pages: int = 2,
    cutoff: Optional[datetime] = None
) -> List[Dict]:
    """Paginate through an SBS listing page and collect valid article links."""
    all_links = []

    for page_num in range(1, max_pages + 1):
        paginated_url = url if page_num == 1 else f"{url}?page={page_num}"
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

        links = page.eval_on_selector_all(
            "a[href*='/news/article/']",
            """elements => elements.map(el => ({
                text: el.innerText.trim().replace(/^SBS NEWS\\s*/i, '').trim(),
                href: el.getAttribute('href'),
                parentText: el.closest('article')?.innerText
                            || el.closest('[class*=\"card\"]')?.innerText
                            || el.closest('li')?.innerText
                            || el.parentElement?.innerText
                            || ''
            }))"""
        )

        if not links:
            logger.info("No links found on page %d — stopping.", page_num)
            break

        stop = False
        page_links = []

        for link in links:
            href = link.get("href", "")
            if not href:
                continue

            article_url = href if href.startswith("http") else f"https://www.sbs.com.au{href}"

            pub_date = None
            try:
                page.goto(article_url, wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(1_500)
                pub_date = extract_pub_date_from_page(page)
            except Exception as exc:
                logger.warning("Could not visit %s: %s", article_url, exc)

            if pub_date is not None and cutoff and pub_date < cutoff:
                logger.info(
                    "Found article older than cutoff (%s): %s — stopping pagination.",
                    pub_date.date(), link.get("text", "")[:60]
                )
                stop = True
                try:
                    page.goto(paginated_url, wait_until="domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                break

            link["pub_date"] = pub_date.isoformat() if pub_date else None
            page_links.append(link)

        all_links.extend(page_links)
        logger.info("Got %d valid links on page %d", len(page_links), page_num)

        if stop:
            break

    return all_links


def fetch_article_body(page, url: str) -> Tuple[str, Optional[datetime]]:
    """Fetch an SBS article page and extract body text and publication date."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
    except Exception as exc:
        logger.warning("Error loading article %s: %s", url, exc)
        return f"(Error loading article: {exc})", None

    pub_date = extract_pub_date_from_page(page)

    try:
        paragraphs = page.eval_on_selector_all(
            "article p",
            "els => els.map(el => el.innerText.trim()).filter(t => t.length > 30)"
        )
        paragraphs = [p for p in paragraphs if not is_boilerplate(p, NEWS_BOILERPLATE_PATTERNS["SBS"])]
        body = "\n\n".join(paragraphs) if paragraphs else "(Could not extract body)"
    except Exception as exc:
        logger.warning("Error extracting body from %s: %s", url, exc)
        body = f"(Error extracting body: {exc})"

    return body, pub_date


def scrape_sbs(max_articles: int = MAX_ARTICLES) -> List[Dict]:
    """Collect and filter SBS news articles using Playwright."""
    all_links: List[Dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        logger.info("Collecting article links...")
        for source_url in NEWS_URLS["SBS"]:
            links = collect_links_paginated(
                listing_page, source_url,
                max_pages=2,
                cutoff=fetch_cutoff_date(7)
            )
            logger.info("Got %d links from %s", len(links), source_url)
            all_links.extend(links)

        seen_hrefs: set = set()
        candidates: List[Dict] = []
        rejected = {"url_pattern": 0, "duplicate": 0, "short_headline": 0, "keyword": 0}

        for link in all_links:
            href = link.get("href", "")
            headline = link.get("text", "").strip()
            parent_text = link.get("parentText", "").strip()

            if href.startswith("https://www.sbs.com.au"):
                href = href[len("https://www.sbs.com.au"):]
            if not ARTICLE_URL_PATTERN.match(href):
                rejected["url_pattern"] += 1
                continue
            if href in seen_hrefs:
                rejected["duplicate"] += 1
                continue
            if len(headline) < 15:
                rejected["short_headline"] += 1
                continue
            if not matches_keywords(headline + " " + parent_text):
                rejected["keyword"] += 1
                continue

            seen_hrefs.add(href)
            candidates.append({
                "headline": headline,
                "url": f"https://www.sbs.com.au{href}",
                "body": "",
                "pub_date": None,
            })

        logger.info("Total links: %d", len(all_links))
        logger.info("Rejections: %s", rejected)
        logger.info("After keyword filter: %d candidate(s). Fetching top %d...", len(candidates), max_articles)

        candidates = candidates[:max_articles]
        article_page = browser.new_page()
        kept: List[Dict] = []

        for i, article in enumerate(candidates):
            label = article["headline"][:65]
            logger.info("[%d/%d] %s", i + 1, len(candidates), label)

            body, pub_date = fetch_article_body(article_page, article["url"])
            article["body"] = body
            article["pub_date"] = pub_date

            if pub_date is None:
                logger.info("Skipped (could not determine date)")
                continue
            if pub_date < fetch_cutoff_date(7):
                logger.info("Skipped (too old: %s)", pub_date.date())
                continue

            article["pub_date"] = pub_date.isoformat()
            kept.append(article)

        browser.close()

    logger.info("Articles kept after date filter: %d", len(kept))
    return kept


def build_content_list(articles: List[Dict]) -> List[Dict]:
    """Format articles into a structured content list for the payload."""
    return [
        {
            "index": i,
            "headline": article["headline"],
            "published": article["pub_date"] or "unknown",
            "source": article["url"],
            "body": article["body"],
        }
        for i, article in enumerate(articles, start=1)
    ]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape SBS News articles and upload to S3 or save locally."""
    logger.info("Starting Playwright-based SBS News scraper")
    articles = scrape_sbs(MAX_ARTICLES)

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
        SBS_NEWS_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")