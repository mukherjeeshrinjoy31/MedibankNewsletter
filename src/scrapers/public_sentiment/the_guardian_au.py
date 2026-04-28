import json
import re
import argparse
import boto3
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# ---- Config ------------------------------------------------------
TIER = "public-sentiment"
DATASET = "news"
BUCKET = "p000268ds-medibank-intelligence"
SOURCE = "guardian"
URL = "https://www.theguardian.com/au"

CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)

GUARDIAN_URLS = [
    "https://www.theguardian.com/australia-news/health",
    "https://www.theguardian.com/australia-news",
    "https://www.theguardian.com/au/lifeandstyle",
]

MAX_ARTICLES = 20
SCROLL_PASSES = 4

# Matches Guardian article URL paths: /section/.../2026/apr/27/slug
# Slug must end with word chars — rules out /all, #fragment etc.
ARTICLE_URL_PATTERN = re.compile(
    r"^/(?:[a-z0-9\-]+/)*\d{4}/[a-z]{3}/\d{2}/[a-z0-9][a-z0-9\-]*$"
)

# Section slugs that are never editorial articles
EXCLUDED_SECTIONS = {
    "live",       # live blogs
    "video",      # video pages
    "audio",      # podcasts
    "picture",    # picture galleries
    "morning-mail-newsletter",
    "afternoon-update-newsletter",
}

# Extracts /2026/apr/27/ from a Guardian URL path
_URL_DATE_RE = re.compile(r"/(\d{4})/([a-z]{3})/(\d{2})/")

KEYWORDS = {
    "phi": [
        "medibank", "bupa", "nib", "hcf", "hbf",
        "private health insurance", "health fund",
        "health cover", "health insurer", "private health",
    ],
    "health_tech": [
        "health technology", "digital health", "health ai",
        "medical ai", "health innovation", "medtech",
        "telehealth", "health data", "wearable health",
        "health automation", "clinical ai", "precision medicine",
    ],
}

BOILERPLATE_PATTERNS = [
    r"^sign in",
    r"^subscribe",
    r"^support the guardian",
    r"^print this page",
    r"^reuse this content",
    r"^\(.+:.+\)$",
    r"^[a-z ]+:$",
    r"^topics$",
    r"^more on this story",
]

# JS that collects article card data in one round-trip.
# Starts from <a href*='/202'> anchors, deduplicates by href,
# walks up to the card container to find headline + datetime.
_CARD_JS = """
elements => {
    const seen = new Set();
    const results = [];

    for (const el of elements) {
        let href = el.getAttribute('href') || '';

        // Normalise: strip domain prefix if present
        if (href.startsWith('https://www.theguardian.com')) {
            href = href.slice('https://www.theguardian.com'.length);
        }

        // Must be a relative Guardian path
        if (!href.startsWith('/')) continue;
        // Skip archive indexes, comment anchors, non-article paths
        if (href.endsWith('/all')) continue;
        if (href.includes('#')) continue;

        if (seen.has(href)) continue;
        seen.add(href);

        // Walk up to nearest card container
        const card = el.closest('article')
                  || el.closest('[class*="card"]')
                  || el.closest('[class*="container"]')
                  || el.closest('li')
                  || el.parentElement;

        // Headline: heading element in card > aria-label > anchor text
        let headline = '';
        if (card) {
            const h = card.querySelector('h1,h2,h3,h4');
            if (h) headline = h.innerText.trim();
        }
        if (!headline) {
            headline = (el.getAttribute('aria-label') || el.innerText || '').trim();
        }

        // Datetime from <time> in the card
        const timeEl = card ? card.querySelector('time[datetime]') : null;
        const datetime = timeEl ? timeEl.getAttribute('datetime') : null;

        // Full card text for keyword matching
        const cardText = card ? card.innerText : '';

        results.push({ href, headline, datetime, cardText });
    }
    return results;
}
"""


# ---- Helpers ------------------------------------------------------
def matches_keywords(text: str) -> bool:
    text = text.lower()
    return any(any(kw in text for kw in kws) for kws in KEYWORDS.values())


def is_boilerplate(text: str) -> bool:
    t = text.lower().strip()
    return any(re.match(pat, t) for pat in BOILERPLATE_PATTERNS)


def is_excluded_section(href: str) -> bool:
    parts = href.strip("/").split("/")
    return any(seg in EXCLUDED_SECTIONS for seg in parts)


def date_from_url(href: str) -> datetime | None:
    """Parse the date embedded in a Guardian URL path (e.g. /2026/apr/27/)."""
    m = _URL_DATE_RE.search(href)
    if not m:
        return None
    try:
        raw = f"{m.group(3)} {m.group(2)} {m.group(1)}"
        return datetime.strptime(raw, "%d %b %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def date_from_str(raw_dt: str | None) -> datetime | None:
    if not raw_dt:
        return None
    try:
        dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return None


def extract_pub_date(page) -> datetime | None:
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

    try:
        meta = page.get_attribute('meta[property="article:published_time"]', "content")
        if meta:
            dt = datetime.fromisoformat(meta.replace("Z", "+00:00"))
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        pass

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


# ---- Scraping Logic ------------------------------------------------------
def collect_links_paginated(page, url: str, max_pages: int = 10, cutoff: datetime = None) -> list[dict]:

    all_links: list[dict] = []

    for page_num in range(1, max_pages + 1):
        paginated_url = f"{url}?page={page_num}"
        print(f"  Scanning: {paginated_url}")

        try:
            page.goto(paginated_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(3_000)
            for _ in range(SCROLL_PASSES):
                page.keyboard.press("End")
                page.wait_for_timeout(2_000)
        except Exception as exc:
            print(f"  [WARN] Failed to load {paginated_url}: {exc}")
            break

        raw_cards = page.eval_on_selector_all("a[href*='/202']", _CARD_JS)

        if not raw_cards:
            print(f"  No links found on page {page_num}, stopping.")
            break

        page_links: list[dict] = []

        for card in raw_cards:
            href = card.get("href", "")

            # Must match article URL pattern
            if not ARTICLE_URL_PATTERN.match(href):
                continue

            # Skip non-article sections
            if is_excluded_section(href):
                continue

            # Resolve date — no network calls
            pub_date = date_from_str(card.get("datetime")) or date_from_url(href)

            # Skip links with suspiciously old dates (persistent footer junk
            # like the 2022 newsletter signup that appears on every page)
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

        print(f"  Page {page_num}: {len(page_links)} links "
              f"({len(dated)} dated, {len(old)} older than cutoff)")
        for l in page_links:
            label = l["headline"] or l["href"]

        # Stop when every dateable link on this page is beyond the cutoff
        if cutoff and dated and len(old) == len(dated):
            print(f"  All dated links older than cutoff — stopping pagination.")
            break

    return all_links


def fetch_article_body(page, url: str) -> tuple[str, datetime | None]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
    except Exception as exc:
        return f"(Error loading article: {exc})", None

    pub_date = extract_pub_date(page)

    try:
        paragraphs = page.eval_on_selector_all(
            "article p",
            "els => els.map(el => el.innerText.trim()).filter(t => t.length > 30)"
        )
        paragraphs = [p for p in paragraphs if not is_boilerplate(p)]
        body = "\n\n".join(paragraphs) if paragraphs else "(Could not extract body)"
    except Exception as exc:
        body = f"(Error extracting body: {exc})"

    return body, pub_date


def scrape_guardian(max_articles: int = MAX_ARTICLES) -> list[dict]:
    all_links: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        print("\nCollecting article links …\n")
        for source_url in GUARDIAN_URLS:
            links = collect_links_paginated(
                listing_page, source_url, max_pages=10, cutoff=CUTOFF_DATE
            )
            print(f"  → {len(links)} links from {source_url}\n")
            all_links.extend(links)

        seen_hrefs: set[str] = set()
        candidates: list[dict] = []
        rejected = {
            "duplicate": 0, "short_headline": 0,
            "keyword": 0, "too_old": 0,
        }

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
                    if datetime.fromisoformat(pub_date_str) < CUTOFF_DATE:
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

        print(f"Total links collected : {len(all_links)}")
        print(f"Rejections            : {rejected}")
        print(f"Candidates            : {len(candidates)} — fetching top {max_articles}\n")

        candidates = candidates[:max_articles]
        article_page = browser.new_page()
        kept: list[dict] = []

        for i, article in enumerate(candidates):
            print(f"  [{i+1}/{len(candidates)}] {article['headline'][:65]} …")

            body, pub_date = fetch_article_body(article_page, article["url"])
            article["body"] = body

            # Precise date from the article page; fall back to listing-page date
            if pub_date is None and article["pub_date"]:
                try:
                    pub_date = datetime.fromisoformat(article["pub_date"])
                except Exception:
                    pass

            if pub_date is None:
                print(f"    → Skipped (could not determine date)")
                continue
            if pub_date < CUTOFF_DATE:
                print(f"    → Skipped (too old: {pub_date.date()})")
                continue

            article["pub_date"] = pub_date.isoformat()
            kept.append(article)

        browser.close()

    print(f"\nArticles kept: {len(kept)}")
    return kept


# ---- Output Helpers ------------------------------------------------------
def build_content_list(articles: list[dict]) -> list[dict]:
    return [
        {
            "index": i,
            "headline": a["headline"],
            "published": a["pub_date"] or "unknown",
            "source": a["url"],
            "body": a["body"],
        }
        for i, a in enumerate(articles, start=1)
    ]


def build_payload(content: list[dict]) -> dict:
    return {
        "source": SOURCE,
        "tier": TIER,
        "dataset": DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "content": content,
    }


def upload_to_s3(payload: dict) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    key = (
        f"raw/{payload['tier']}/{payload['source']}_"
        f"{payload['dataset']}_"
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")


def save_local(payload: dict, directory: str = ".") -> None:
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{run_date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}")


# ---- Main ----------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Playwright-based Guardian AU scraper — PHI / health-tech"
    )
    parser.add_argument(
        "--local",
        metavar="DIR",
        nargs="?",
        const=".",
        help="Save JSON locally instead of uploading to S3 (default dir: .)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=MAX_ARTICLES,
        help=f"Max articles to fetch (default: {MAX_ARTICLES})",
    )
    args = parser.parse_args()

    articles = scrape_guardian(max_articles=args.max)

    if not articles:
        print("No matching articles found.")
    else:
        content = build_content_list(articles)
        payload = build_payload(content)

        if args.local is not None:
            save_local(payload, args.local)
        else:
            upload_to_s3(payload)

        print(f"\nDone. {len(articles)} article(s) processed.")