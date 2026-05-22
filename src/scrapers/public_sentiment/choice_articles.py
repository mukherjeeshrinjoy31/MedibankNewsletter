import logging
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set
from urllib.parse import urljoin, urlencode, urlparse

from bs4 import BeautifulSoup

from ...commons.data import ARTICLES_SEARCH_URL, MONTH_MAP
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_cutoff_date, fetch_run_date, fetch_url, save_local, upload_to_s3

SOURCE      = "choice"
URL         = "https://www.choice.com.au"
MAX_PAGES   = 10
SEARCH_TERM = "Medibank"
SEARCH_TAB  = "articles"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_within_cutoff(article_date: Optional[datetime]) -> bool:
    """Return True if article is within the 30-day cutoff or has no date."""
    if article_date is None:
        return True
    return article_date >= fetch_cutoff_date(30)


def parse_article_date(soup: BeautifulSoup) -> Optional[datetime]:
    """Extract and parse article date from page content."""
    text = soup.get_text(" ", strip=True)

    # Primary: "Last updated: 22 Apr 2025"
    match = re.search(r"Last updated:\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
    if match:
        day, month_str, year = match.groups()
        full_month = MONTH_MAP.get(month_str[:3], month_str)
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


def fetch_article_content(article_url: str) -> Dict:
    """Fetch and extract full text from an article page."""
    logger.info("Fetching content: %s", article_url)
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
    """Dynamically discover the search URL from the homepage."""
    logger.info("Discovering search URL from homepage: %s", base_url)
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
                if (form.find("input", attrs={"type": "search"}) or
                        form.find("input", attrs={"name": "s"})):
                    search_form = form
                    break

        if search_form:
            raw_action = search_form.get("action", "").strip()
            form_action = urljoin(base_url, raw_action) if raw_action else base_url

            search_input = (
                search_form.find("input", attrs={"type": "search"})
                or search_form.find("input", attrs={"name": re.compile(r"^s$|query|q|search", re.I)})
            )
            if search_input and search_input.get("name"):
                query_param = search_input["name"]

            logger.info("Found search form → action='%s', param='%s'", form_action, query_param)
        else:
            logger.warning("No search form found — using base URL as form action.")
            form_action = base_url
    else:
        logger.warning("Could not fetch homepage — falling back to default search pattern.")
        form_action = base_url

    params = {query_param: search_term, "tab": tab}
    search_url = f"{form_action.rstrip('/')}/?{urlencode(params)}"
    logger.info("Constructed search URL: %s", search_url)
    return search_url


def get_all_search_page_urls(base_search_url: str, max_pages: int = MAX_PAGES) -> List[str]:
    """Generate paginated search URLs."""
    urls = [base_search_url]

    parsed = urlparse(base_search_url)
    qs = f"?{parsed.query}" if parsed.query else ""
    origin = f"{parsed.scheme}://{parsed.netloc}"

    for page in range(2, max_pages + 1):
        urls.append(f"{origin}/page/{page}{qs}")

    return urls


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_medibank_articles() -> List[Dict]:
    """Scrape Medibank-related articles from choice.com.au."""
    results: List[Dict] = []

    base_search_url = discover_search_url(URL, SEARCH_TERM, SEARCH_TAB)
    search_urls = get_all_search_page_urls(base_search_url)

    for page_num, search_url in enumerate(search_urls, 1):
        logger.info("Checking search page %d: %s", page_num, search_url)
        soup = fetch_url(search_url)
        if soup is None:
            logger.warning("Could not fetch search page %d — skipping.", page_num)
            continue

        article_urls: Set[str] = set()
        for link_el in soup.select('a[href*="/articles/"]'):
            href = link_el.get("href", "")
            if href.startswith("/"):
                href = f"https://www.choice.com.au{href}"

            if "/articles/" not in href:
                continue

            link_text = link_el.get_text(strip=True).lower()
            if ("medibank" in link_text or
                    any(word in link_text for word in [
                        "health insurance", "health fund", "premium",
                        "bupa", "hcf", "nib", "hbf", "extras",
                        "gold cover", "hospital cover"
                    ])):
                article_urls.add(href)

        logger.info("Found %d potentially relevant articles on page %d", len(article_urls), page_num)

        for article_url in sorted(article_urls):
            article_content = fetch_article_content(article_url)

            soup_article = fetch_url(article_url)
            if soup_article is None:
                logger.warning("Could not fetch article: %s — skipping.", article_url)
                continue

            title_el = (
                soup_article.find("h1")
                or soup_article.find("h2", class_=re.compile(r"title|headline|article-title", re.I))
                or soup_article.find("h2")
            )
            title = title_el.get_text(strip=True) if title_el else "Untitled"

            article_date = parse_article_date(soup_article)
            date_iso = article_date.isoformat() if article_date else None
            date_str = f"{article_date.day} {article_date.strftime('%B %Y')}" if article_date else None

            if not is_within_cutoff(article_date):
                logger.info("Skipped (before cutoff): %s", title)
                continue

            summary = ""
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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape Choice articles and upload to S3 or save locally."""
    logger.info("Starting Medibank article scrape from choice.com.au")
    articles = scrape_medibank_articles()

    if not articles:
        logger.warning("No articles found within the cutoff date.")
        return False

    logger.info("Successfully scraped %d recent Medibank-related articles.", len(articles))
    payload = build_payload(
        articles,
        SOURCE,
        DATASET.ARTICLES.value,
        fetch_run_date(),
        TIER.PUBLIC_SENTIMENT.value,
        ARTICLES_SEARCH_URL
    )

    if local:
        save_local(payload)
    else:
        upload_to_s3(payload)
    return True


if __name__ == "__main__":
    run(local="data")