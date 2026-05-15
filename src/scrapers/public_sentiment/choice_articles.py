import json
from urllib.parse import urljoin, urlencode, urlparse
import boto3
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from typing import Optional
from ...commons.data import ARTICLES_SEARCH_URL, HEADERS, MONTH_MAP
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_url, save_local, upload_to_s3
from ...commons.tiers import TIER
from ...commons.dataset import DATASET


# ---- Config ------------------------------------------------------
SOURCE = "choice"
DATASET = "articles"
TIER   = "public-sentiment"
URL = "https://www.choice.com.au"
BASE_SEARCH_URL = "https://www.choice.com.au/?s=Medibank&tab=articles"
BUCKET = "p000268ds-medibank-intelligence-us"

CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)
MAX_PAGES = 10
SEARCH_TERM = "Medibank"
SEARCH_TAB = "articles"

HEADERS = {"User-Agent": "Mozilla/5.0"}

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

def discover_search_url(base_url: str, search_term: str, tab: str) -> str:

    print(f"Discovering search URL from homepage: {base_url}")
    soup = fetch_url(base_url)
 
    form_action = None
    query_param = "s"  
 
    if soup:
        search_form = (
            soup.find("form", attrs={"role": "search"})
            or soup.find("form", id=re.compile(r"search", re.I))
            or soup.find("form", class_=re.compile(r"search", re.I))
        )
 
        if search_form is None:
            for form in soup.find_all("form"):
                if form.find("input", attrs={"type": "search"}) or \
                   form.find("input", attrs={"name": "s"}):
                    search_form = form
                    break
 
        if search_form:
            raw_action = search_form.get("action", "").strip()
            form_action = urljoin(base_url, raw_action) if raw_action else base_url
 
            # Identify the query parameter name from the search input field
            search_input = (
                search_form.find("input", attrs={"type": "search"})
                or search_form.find("input", attrs={"name": re.compile(r"^s$|query|q|search", re.I)})
            )
            if search_input and search_input.get("name"):
                query_param = search_input["name"]
 
            print(f"Found search form → action='{form_action}', param='{query_param}'")
        else:
            print("No search form found on homepage; using base URL as form action.")
            form_action = base_url
 
    else:
        print("Could not fetch homepage; falling back to default search pattern.")
        form_action = base_url
 
    params = {query_param: search_term, "tab": tab}
    search_url = f"{form_action.rstrip('/')}/?{urlencode(params)}"
    print(f"  Constructed search URL: {search_url}")
    return search_url

def get_all_search_page_urls(base_search_url: str, max_pages: int = MAX_PAGES) -> list[str]:

    urls = [base_search_url]
 
    parsed = urlparse(base_search_url)
    qs = f"?{parsed.query}" if parsed.query else ""
    origin = f"{parsed.scheme}://{parsed.netloc}"
 
    for page in range(2, max_pages + 1):
        urls.append(f"{origin}/page/{page}{qs}")
 
    return urls

# ---- Main Scraper ------------------------------------------------------
def scrape_medibank_articles() -> list[dict]:
    results: list[dict] = []
    
    base_search_url = discover_search_url(URL, SEARCH_TERM, SEARCH_TAB)
    search_urls = get_all_search_page_urls(base_search_url)

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


# ---- Output Helpers ------------------------------------------------------
def build_payload(content: list[dict]) -> dict:
    return {
        "source": SOURCE,
        "tier": TIER,
        "dataset": DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url": URL,
        "content": content,
    }


def save_local(payload: dict, directory: str = ".") -> None:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{SOURCE}_{DATASET}_{date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\nSaved locally: {path}")


def upload_to_s3(payload: dict) -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{date}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"Uploaded to S3: s3://{BUCKET}/{key}")


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
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True