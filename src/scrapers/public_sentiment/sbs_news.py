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
SOURCE = "sbs"
URL = "https://www.sbs.com.au/news"

CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)

# Pages to scan for article links
SBS_URLS = [
    "https://www.sbs.com.au/news/collection/health-and-wellbeing",
    "https://www.sbs.com.au/news/tag/subject/health",
    "https://www.sbs.com.au/news/collection/just-in-articles",
    "https://www.sbs.com.au/news/tag/section/life",
    "https://www.sbs.com.au/search?query=private+health+insurance&sort=date&filter=news"
]

MAX_ARTICLES = 20
SCROLL_PASSES = 4

ARTICLE_URL_PATTERN = re.compile(
    r"^/news/article/[a-z0-9][a-z0-9\-]+/[a-z0-9]+$"
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
    r"^sign up now",
    r"^sbs on the money",
    r"^sbs news in easy english",
    r"^your daily ten minute",
    r"^get the latest with our",
    r"^live stream",
    r"^follow the latest",
    r"^from breaking headlines",
    r"^[a-z ]+:$",
    r"^\(.+:.+\)$",
]

# ---- Helpers ------------------------------------------------------
def matches_keywords(text: str) -> bool:
    text = text.lower()
    groups_matched = sum(
        any(kw in text for kw in kws) for kws in KEYWORDS.values()
    )
    return groups_matched >= 1


def is_boilerplate(text: str) -> bool:
    t = text.lower().strip()
    return any(re.match(pat, t) for pat in BOILERPLATE_PATTERNS)

def parse_date(text: str) -> datetime | None:
    match = re.search(r"(\d{1,2})[\s\n]+([A-Za-z]+)[\s\n]+(\d{4})", text)
    if match:
        raw = f"{match.group(1)} {match.group(2)} {match.group(3)}"
        for fmt in ("%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


# ---- Scraping Logic ------------------------------------------------------
def collect_links_paginated(page, url: str, max_pages: int = 2, cutoff: datetime = None) -> list[dict]:
    all_links = []

    for page_num in range(1, max_pages + 1):
        paginated_url = url if page_num == 1 else f"{url}?page={page_num}"
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
            print(f"  No links found on page {page_num}, stopping.")
            break

        stop = False
        page_links = []

        for link in links:
            href = link.get("href", "")
            if not href:
                continue
            if not href.startswith("http"):
                article_url = f"https://www.sbs.com.au{href}"
            else:
                article_url = href

            # Visit each article to check its date
            pub_date = None
            try:
                page.goto(article_url, wait_until="domcontentloaded", timeout=20_000)
                page.wait_for_timeout(1_500)

                # 1. article-scoped <time datetime>
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

                # 2. "Published DD Month YYYY" text
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

            except Exception as exc:
                print(f"  [WARN] Could not visit {article_url}: {exc}")

            if pub_date is not None and pub_date < cutoff:
                print(f"  Found article older than cutoff ({pub_date.date()}): {link.get('text', '')[:60]}, stopping pagination.")
                stop = True
                # Go back to listing page for next iteration
                try:
                    page.goto(paginated_url, wait_until="domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                break

            link["pub_date"] = pub_date.isoformat() if pub_date else None
            page_links.append(link)

        all_links.extend(page_links)
        print(f"  Got {len(page_links)} valid links on page {page_num}")

        if stop:
            break

    return all_links


def fetch_article_body(page, url: str) -> tuple[str, datetime | None]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2_000)
    except Exception as exc:
        return f"(Error loading article: {exc})", None

    pub_date = None

    # 1. Try article-scoped <time> elements, take the earliest (= publish date)
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

    # 2. Fall back: "Published DD Month YYYY" text in article body
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

    # 3. Last resort: parse_date on full page text
    if pub_date is None:
        try:
            pub_date = parse_date(page.inner_text("body") or "")
        except Exception:
            pass

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


def scrape_sbs(max_articles: int = MAX_ARTICLES) -> list[dict]:
    all_links: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        listing_page = browser.new_page()

        print("\nCollecting article links …\n")
        for source_url in SBS_URLS:
            links = collect_links_paginated(listing_page, source_url, max_pages=2, cutoff=CUTOFF_DATE)
            print(f"  Got {len(links)} links from {source_url}")
            all_links.extend(links)

        seen_hrefs: set[str] = set()
        candidates: list[dict] = []
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

            if pub_date is None:
                print(f"    → Skipped (could not determine date)")
                continue
            if pub_date < CUTOFF_DATE:
                print(f"    → Skipped (too old: {pub_date.date()})")
                continue

            article["pub_date"] = pub_date.isoformat() if pub_date else None

            kept.append(article)

        browser.close()

    print(f"\nArticles kept after date filter: {len(kept)}")
    return kept


# ---- Output Helpers ------------------------------------------------------
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
        description="Playwright-based SBS News scraper — PHI / health-tech"
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

    articles = scrape_sbs(max_articles=args.max)

    if not articles:
        print("No matching articles found.")
    else:
        content = build_content_list(articles)
        payload = build_payload(content)

        if args.local:
            save_local(payload, args.local)
        else:
            upload_to_s3(payload)

        print(f"\nDone. {len(articles)} article(s) processed.")
