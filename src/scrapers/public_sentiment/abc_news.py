import json
import re
from datetime import datetime, timezone
from typing import Optional
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from playwright.sync_api import sync_playwright
from ...utils.helpers import build_content_list, build_payload, fetch_cutoff_date, fetch_run_date, is_boilerplate, matches_keywords, save_local, upload_to_s3

from ...commons.data import ABC_NEWS_URL, NEWS_BOILERPLATE_PATTERNS, NEWS_KEYWORDS, NEWS_URLS

# ---- Config ------------------------------------------------------
SOURCE = "abc"
MAX_ARTICLES = 40  
SCROLL_PASSES = 4 
ARTICLE_URL_PATTERN = re.compile(r"^/news/(?:.+/)?\d{4}-\d{2}-\d{2}/.+/\d+$")

# ---- Helpers ------------------------------------------------------
def parse_abc_date(page) -> datetime | None:
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


# ---- Scraping Logic ------------------------------------------------------
def collect_links(page, url: str) -> list[dict]:
    """Scroll through a listing page and return all candidate <a> elements."""
    print(f"  Scanning: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        for _ in range(SCROLL_PASSES):
            page.keyboard.press("End")
            page.wait_for_timeout(2_000)
    except Exception as exc:
        print(f"  [WARN] Failed to load {url}: {exc}")
        return []

    return page.eval_on_selector_all(
        "a[href*='/news/']",
        """elements => elements.map(el => ({
            text: el.innerText.trim().replace(/^result number \\d+\\s*/i, ''),
            href: el.getAttribute('href'),
            parentText: el.closest('article')?.innerText
                        || el.parentElement?.innerText
                        || ''
        }))"""
    )


def fetch_article_body(page, url: str) -> tuple[str, datetime | None]:
    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
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
        body = f"(Error extracting body: {exc})"

    return body, pub_date


def scrape_abc_playwright(max_articles: int = MAX_ARTICLES) -> list[dict]:
    all_links: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        print("\nCollecting article links …\n")
        for source_url in NEWS_URLS["ABC"]:
            links = collect_links(listing_page, source_url)
            print(f"  Got {len(links)} links from {source_url}")
            all_links.extend(links)

        seen_hrefs: set[str] = set()
        candidates: list[dict] = []
        rejected = {"url_pattern": 0, "duplicate": 0, "short_headline": 0, "keyword": 0}

        for link in all_links:
            href = link.get("href", "")
            headline = link.get("text", "").strip()
            parent_text = link.get("parentText", "").strip()

            if href.startswith("https://www.abc.net.au"):
                href = href[len("https://www.abc.net.au"):]
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
                "url": f"https://www.abc.net.au{href}",
                "body": "",
                "pub_date": None,
            })

        print(f"\nTotal links: {len(all_links)}")
        print(f"Rejections: {rejected}")
        print(f"After keyword filter: {len(candidates)} candidate(s). Fetching top {max_articles} …\n")

        candidates = candidates[:max_articles]

        article_page = browser.new_page()
        kept: list[dict] = []

        for i, article in enumerate(candidates):
            label = article["headline"][:65]
            print(f"  [{i+1}/{len(candidates)}] {label} …")

            body, pub_date = fetch_article_body(article_page, article["url"])
            article["body"] = body
            article["pub_date"] = pub_date

            # skip articles outside our look-back window
            if pub_date and pub_date < fetch_cutoff_date(7):
                print(f"    → Skipped (too old: {pub_date.date()})")
                continue

            if pub_date:
                article["pub_date"] = pub_date.isoformat()
            else:
                article["pub_date"] = None   # unknown date – keep anyway

            kept.append(article)
        browser.close()
    print(f"\nArticles kept after date filter: {len(kept)}")
    return kept

def run(local: Optional[str] = None) -> bool:
    print("Starting Playwright-based ABC News scraper — PHI / health-tech")
    articles = scrape_abc_playwright(MAX_ARTICLES)
    if not articles:
        print("No matching articles found.")
    else:
        content = build_content_list(articles)  
    print(f"\nExtracted {len(content):,} characters of text.")
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

# run "python ama.py --local" to save locally to a "data" directory instead of uploading to S3