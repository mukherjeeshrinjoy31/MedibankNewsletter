import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from typing import Optional
from ...commons.data import ARTICLES_SEARCH_URL, HEADERS, MONTH_MAP
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_url, save_local, upload_to_s3
from ...commons.tiers import TIER
from ...commons.dataset import DATASET

MAX_PAGES = 10

# ---- Helper Functions ------------------------------------------------------
def is_within_cutoff(article_date: Optional[datetime]) -> bool:
    if article_date is None:
        return True
    return article_date >= fetch_cutoff_date(30)


from typing import Optional
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import re

def parse_article_date(soup: BeautifulSoup) -> Optional[datetime]:
    text = soup.get_text(" ", strip=True)

    # Primary: "Last updated: 22 Apr 2025"
    match = re.search(r"Last updated:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
    if match:
        day, month_str, year = match.groups()
        full_month = MONTH_MAP.get(month_str[:3].lower(), month_str)
        try:
            return datetime.strptime(f"{day} {full_month} {year}", "%d %B %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    # Fallback: "April 22, 2025"
    match = re.search(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if match:
        try:
            return datetime.strptime(match.group(0), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None



def fetch_article_content(article_url: str) -> dict:
    print(f"  Fetching content: {article_url}")
    soup = fetch_url(article_url)
    if soup is None:
        return {"full_text": ""}

    body = (
        soup.find("article")
        or soup.find("main")
        or soup.find("div", class_=re.compile(r"content|article-body|article-content|post-content", re.I))
        or soup.find("div", id=re.compile(r"content|article", re.I))
    )

    full_text = body.get_text(" ", strip=True) if body else soup.get_text(" ", strip=True)
    return {"full_text": full_text}


# ---- Pagination (Fixed) ------------------------------------------------------
def get_all_search_page_urls(base_url: str, max_pages: int = MAX_PAGES) -> list[str]:
    urls = [base_url]
    for page in range(2, max_pages + 1):
        urls.append(f"https://www.choice.com.au/page/{page}?s=Medibank&tab=articles")
    return urls


# ---- Main Scraper ------------------------------------------------------
def scrape_medibank_articles() -> list[dict]:
    results: list[dict] = []
    search_urls = get_all_search_page_urls(ARTICLES_SEARCH_URL)

    for page_num, search_url in enumerate(search_urls, 1):
        print(f"\n=== Checking search page {page_num}: {search_url} ===")
        soup = fetch_url(search_url)
        if soup is None:
            continue

        article_urls = set()
        for link_el in soup.select('a[href*="/articles/"]'):
            href = link_el.get("href", "")
            if href.startswith("/"):
                href = f"https://www.choice.com.au{href}"

            if "/articles/" not in href:
                continue

            link_text = link_el.get_text(strip=True).lower()

            # Strong pre-filter — only keep likely relevant articles
            if ("medibank" in link_text or
                any(word in link_text for word in ["health insurance", "health fund", "premium", "bupa", "hcf", "nib", "hbf", "extras", "gold cover", "hospital cover"])):
                article_urls.add(href)

        print(f"  Found {len(article_urls)} potentially relevant articles on this page")

        for article_url in sorted(article_urls):
            article_content = fetch_article_content(article_url)

            soup_article = fetch_url(article_url)
            if soup_article is None:
                continue

            # Title
            title_el = (
                soup_article.find("h1")
                or soup_article.find("h2", class_=re.compile(r"title|headline|article-title", re.I))
                or soup_article.find("h2")
            )
            title = title_el.get_text(strip=True) if title_el else "Untitled"

            # Date
            article_date = parse_article_date(soup_article)
            date_iso = article_date.isoformat() if article_date else None
            date_str = f"{article_date.day} {article_date.strftime('%B %Y')}" if article_date else None

            if not is_within_cutoff(article_date):
                print(f"    Skipped (before cutoff): {title}")
                continue

            # Summary
            summary = ""
            if soup_article:
                p = soup_article.find("p")
                if p:
                    summary = p.get_text(strip=True)[:500]

            results.append({
                "title": title,
                "article_url": article_url,
                "date_str": date_str,
                "date_iso": date_iso,
                "summary": summary,
                **article_content,
            })

    return results

# ---- Main ------------------------------------------------------
def run(local: Optional[str] = None) -> bool:
    print("Starting Medibank article scrape from choice.com.au...")
    articles = scrape_medibank_articles()
    if not articles:
        print("No articles found within the cutoff date.")
        return False

    print(f"\nSuccessfully scraped {len(articles)} recent Medibank-related articles.")
    payload = build_payload(
        articles,
        "choice",
        DATASET.ARTICLES.value,
        datetime.now(timezone.utc).isoformat(),
        TIER.PUBLIC_SENTIMENT.value,
        ARTICLES_SEARCH_URL
    )

    if local:
        save_local(payload, local)
    else:
        upload_to_s3(payload)
    return True