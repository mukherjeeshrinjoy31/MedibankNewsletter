import json
import re
import argparse
import boto3
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

# ---- Config ------------------------------------------------------
TIER = "public-sentiment"
DATASET = "news"
BUCKET = "rmit-publicsentiment-demo-397348546955-ap-southeast-2-an"
SOURCE = "abc"
URL = "https://www.abc.net.au/"

# How far back to look (match weekly run cadence with some overlap)
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)

# Pages to scan for article links
ABC_URLS = [
    "https://www.abc.net.au/news/health",
    "https://www.abc.net.au/news/",
    "https://www.abc.net.au/news/australia/",
    "https://www.abc.net.au/news/search/?query=health+australia",
    "https://www.abc.net.au/news/search/?query=private+health+insurance"
]

MAX_ARTICLES = 40  
SCROLL_PASSES = 4 

ARTICLE_URL_PATTERN = re.compile(
    r"^/news/(?:.+/)?\d{4}-\d{2}-\d{2}/.+/\d+$"
)

KEYWORDS = {
    "phi": [
        "medibank", "bupa", "nib", "hcf", "hbf",
        "private health insurance", "health fund",
        "health cover", "health insurer", "private health"
    ],
    "health_tech": [
        "health technology", "digital health", "health ai",
        "medical ai", "health innovation", "medtech",
        "telehealth", "health data", "wearable health",
        "health automation", "clinical ai", "precision medicine",
    ],
}

BOILERPLATE_PATTERNS = [
    r"^topic:?$",
    r"^this site is protected by recaptcha",
    r"^follow @abc",
    r"^\(.+:.+\)$",
    r"^analysis by ",
    r"^live$",
    r"^[a-z ]+:$",
]

# ---- Helpers ------------------------------------------------------

def matches_keywords(text: str) -> bool:
    text = text.lower()
    groups_matched = sum(
        any(kw in text for kw in kws) for kws in KEYWORDS.values()
    )
    return groups_matched >= 1 # match either phi or health-tech (not necessarily both)


def is_boilerplate(text: str) -> bool:
    t = text.lower().strip()
    return any(re.match(pat, t) for pat in BOILERPLATE_PATTERNS)


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
        page.goto(url, wait_until="networkidle", timeout=30_000)
        for _ in range(SCROLL_PASSES):
            page.keyboard.press("End")
            page.wait_for_timeout(1_500)
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
        paragraphs = [p for p in paragraphs if not is_boilerplate(p)]
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
        for source_url in ABC_URLS:
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
            if pub_date and pub_date < CUTOFF_DATE:
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


# ---- Output Helpers ---------------------------------------
def build_content_list(articles: list[dict]) -> list[dict]:
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
    s3 = boto3.client("s3", region_name="ap-southeast-2")
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


# ---- Main ---------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Playwright-based ABC News scraper — PHI / health-tech"
    )
    parser.add_argument(
        "--local",
        metavar="DIR",
        nargs="?",
        const=".",
        help="Save JSON locally to DIR instead of uploading to S3 (default: current dir)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=MAX_ARTICLES,
        help=f"Max articles to fetch (default: {MAX_ARTICLES})",
    )
    args = parser.parse_args()

    articles = scrape_abc_playwright(max_articles=args.max)

    if not articles:
        print("No matching articles found.")
    else:
        run_date = datetime.now(timezone.utc).isoformat()
        content = build_content_list(articles)  
        payload = build_payload(content)

        if args.local:
            save_local(payload, args.local)
        else:
            upload_to_s3(payload)

        print(f"\nDone. {len(articles)} article(s) processed.")

# run "python news_articles_playwright.py --local data" to save locally