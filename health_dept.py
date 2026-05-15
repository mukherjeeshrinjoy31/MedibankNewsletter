import requests
import feedparser
import os
import json
import time
import argparse
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# config
SOURCE  = "health_dept"
TIER    = "phi_industry"
BUCKET  = "p000268ds-medibank-intelligence-us"
HEADERS = {"User-Agent": "Mozilla/5.0"}

def scrape_premium_approvals() -> str:
    print("--- Dept of Health: Premium Approvals ---")

    url = "https://www.health.gov.au/ministers"
    content = "Dept of Health - Premium Approvals\n\n"

    # try scraping the page first
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            text = " ".join(text.split())

            if "premium" in text.lower():
                idx = text.lower().find("premium")
                content += text[max(0, idx-200):idx+2000]
                print(f"✓ Found premium content dynamically")
                return content.strip()

    except Exception as e:
        print(f"Dynamic scraping failed: {e}")

    # fallback — google news rss for latest premium approval news
    print("Trying Google News RSS for premium approval updates...")
    try:
        rss_url = "https://news.google.com/rss/search?q=private+health+insurance+premium+increase+Australia&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(rss_url)
        if feed.entries:
            content += "Latest premium approval news via Google News:\n\n"
            for entry in feed.entries[:10]:
                content += f"Title: {entry.title}\n"
                content += f"Link: {entry.link}\n"
                content += f"Published: {entry.get('published', 'N/A')}\n\n"
            print(f"✓ Found {len(feed.entries[:10])} articles via Google News RSS")
            return content.strip()
    except Exception as e:
        print(f"Google News RSS failed: {e}")

    # last resort — known entries
    print("Using known entries as last resort")
    known_approvals = [
        {
            "title": "Average premium increase of 4.41% approved for 1 April 2026",
            "date": "February 2026",
            "details": "Largest average increase since 2017."
        },
        {
            "title": "Average premium increase of 3.03% approved for 1 April 2025",
            "date": "February 2025",
            "details": "Government approved 3.03% average increase."
        },
        {
            "title": "Average premium increase of 3.03% approved for 1 April 2024",
            "date": "February 2024",
            "details": "Government approved 3.03% average increase."
        }
    ]

    for item in known_approvals:
        content += f"Title: {item['title']}\n"
        content += f"Date: {item['date']}\n"
        content += f"Details: {item['details']}\n\n"

    print(f"✓ Loaded {len(known_approvals)} known approvals")
    return content.strip()

def scrape_clinical_categories() -> str:
    print("--- Dept of Health: MBS Clinical Categories ---")

    url = "https://www.health.gov.au/resources/collections/private-health-insurance-clinical-category-and-procedure-type"
    content = "Dept of Health - MBS Clinical Categories\n\n"

    # try to find latest files dynamically
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            links = []
            for link in soup.find_all("a", href=True):
                href = link["href"]
                text = link.get_text(strip=True)
                if (".xlsx" in href.lower() or ".pdf" in href.lower()) and "clinical" in href.lower():
                    if not href.startswith("http"):
                        href = "https://www.health.gov.au" + href
                    links.append((text, href))

            if links:
                os.makedirs("data/health_dept", exist_ok=True)
                for title, href in links[:3]:
                    filename = href.split("/")[-1]
                    print(f"Downloading: {filename}...")
                    r = requests.get(href, headers=HEADERS, timeout=30)
                    if r.status_code == 200:
                        with open(f"data/health_dept/{filename}", "wb") as f:
                            f.write(r.content)
                        content += f"- {title}: {filename}\n"
                        print(f"✓ {filename}")
                    time.sleep(1)
                return content.strip()

    except Exception as e:
        print(f"Dynamic scraping failed: {e}")

    # fallback — google news rss for mbs clinical category updates
    print("Trying Google News RSS for clinical category updates...")
    try:
        rss_url = "https://news.google.com/rss/search?q=MBS+clinical+categories+private+health+insurance+Australia&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(rss_url)
        if feed.entries:
            content += "Latest MBS clinical category news via Google News:\n\n"
            for entry in feed.entries[:10]:
                content += f"Title: {entry.title}\n"
                content += f"Link: {entry.link}\n"
                content += f"Published: {entry.get('published', 'N/A')}\n\n"
            print(f"✓ Found {len(feed.entries[:10])} articles via Google News RSS")

            # still download known files for actual data
            print("Also downloading known clinical category files...")
            known_files = [
                {
                    "name": "mbs_clinical_category_definitions_march2026.pdf",
                    "url": "https://www.health.gov.au/sites/default/files/2026-02/private-health-insurance-clinical-category-definitions-1-march-2026_0.pdf"
                },
                {
                    "name": "mbs_clinical_category_classification_march2026.xlsx",
                    "url": "https://www.health.gov.au/sites/default/files/2026-02/private-health-insurance-clinical-category-classification-1-march-2026_1.xlsx"
                }
            ]

            os.makedirs("data/health_dept", exist_ok=True)
            for file in known_files:
                print(f"Downloading: {file['name']}...")
                r = requests.get(file["url"], headers=HEADERS, timeout=30)
                if r.status_code == 200:
                    with open(f"data/health_dept/{file['name']}", "wb") as f:
                        f.write(r.content)
                    content += f"- {file['name']}\n"
                    print(f"✓ {file['name']}")
                else:
                    print(f"✗ Failed: {r.status_code}")
                time.sleep(1)

            return content.strip()

    except Exception as e:
        print(f"Google News RSS failed: {e}")

    return content.strip()

# --- Output Helpers ---
def build_payload(content: str, dataset: str, url: str) -> dict:
    return {
        "source":     SOURCE,
        "tier":       TIER,
        "dataset":    dataset,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url":        url,
        "content":    content,
    }

def save_local(payload: dict, directory: str = ".") -> None:
    os.makedirs(directory, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{SOURCE}_{payload['dataset']}_{date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✓ Saved locally: {path}")

def upload_to_s3(payload: dict) -> None:
    import boto3
    s3 = boto3.client("s3", region_name="us-east-1")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"raw/{TIER}/{SOURCE}_{payload['dataset']}_{date}.json"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"✓ Uploaded: s3://{BUCKET}/{key}")

# --- Main ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data/health_dept",
                        help="save locally instead of uploading to S3")
    args = parser.parse_args()

    premium_content = scrape_premium_approvals()
    premium_payload = build_payload(
        premium_content,
        "premium_approvals",
        "https://www.health.gov.au/ministers"
    )

    clinical_content = scrape_clinical_categories()
    clinical_payload = build_payload(
        clinical_content,
        "clinical_categories",
        "https://www.health.gov.au/resources/collections/private-health-insurance-clinical-category-and-procedure-type"
    )

    if args.local:
        save_local(premium_payload, args.local)
        save_local(clinical_payload, args.local)
    else:
        upload_to_s3(premium_payload)
        upload_to_s3(clinical_payload)