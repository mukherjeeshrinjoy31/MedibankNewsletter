import json
import re
import boto3
import argparse
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
import requests
import urllib.parse

# ---- Config ------------------------------------------------------
SOURCE = "canstar"
DATASET = "awards"
TIER   = "public-sentiment"
URL    = "https://www.canstar.com.au/star-ratings-awards/" # url for all canstar awards
BUCKET = "p000268ds-medibank-intelligence"

INSURANCE_PROVIDERS = "medibank"
HEADERS = {"User-Agent": "Mozilla/5.0"}
CUTOFF_DATE = datetime.now(timezone.utc) - timedelta(days=7)

# list of Canstar award pages to scrape based on Medibank's product focus
INSURANCE_AWARD_URLS = [
    # General insurance awards
    "https://www.canstar.com.au/star-ratings-awards/insurer-of-the-year-award/",
    "https://www.canstar.com.au/travel-insurance/star-ratings-awards/",
    "https://www.canstar.com.au/pet-insurance/star-ratings-awards/",
    # Personal insurance awards
    "https://www.canstar.com.au/star-ratings-awards/health-insurance/",
    "https://www.canstar.com.au/star-ratings-awards/overseas-student-working-visa-health/",
    "https://www.canstar.com.au/star-ratings-awards/direct-life-insurance/",
    "https://www.canstar.com.au/star-ratings-awards/direct-income-protection/",
    # Customer satisfaction awards
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-health-insurer-award/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-travel-insurance-award/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-pet-insurance-awards/"
]

# ---- Helper Functions ------------------------------------------------------

def fetch_url(url: str) -> BeautifulSoup | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return None

def medibank_mentioned(soup: BeautifulSoup) -> bool:
    return INSURANCE_PROVIDERS in soup.get_text().lower()

def extract_page_meta(soup: BeautifulSoup, url: str) -> dict:
    '''Extract metadata: title, release date, key stats'''
    meta = {"url": url}

    title_el = soup.find("h1")
    if title_el:
        meta["title"] = title_el.get_text(strip=True)
    
    released_date = soup.find(string=lambda t: t and "Released:" in t)
    if released_date:
        meta["released_date"] = released_date.strip()

    stats = [
        li.get_text(separator=" ", strip=True)
        for li in soup.select("ul li")
        if any(kw in li.get_text() for kw in [
            "providers assessed", "profiles considered",
            "policy variations", "award-winning"
        ])
    ]
    if stats:
        meta["key_stats"] = stats

    return meta

def cutoff_date(meta: dict) -> bool:
    released_date = meta.get("released_date", "")
    if not released_date:
        return True
    try:
        date_str = released_date.replace("Released:", "").strip()
        release_dt = datetime.strptime(date_str, "%d %B, %Y").replace(tzinfo=timezone.utc)
        return release_dt >= CUTOFF_DATE
    except ValueError:
        return True

# ---- Main Scraping Logic ------------------------------------------------------
def extract_medibank_awards(soup: BeautifulSoup) -> list[dict]:
    awards_list = []

    for h4 in soup.select("h4"):
        link = h4.find("a")
        if not link:
            continue
 
        provider = link.get_text(strip=True)
        if INSURANCE_PROVIDERS not in provider.lower():
            continue

        full_text = h4.get_text(strip=True)
        awards_raw = full_text[len(provider):]

        awards = [
            a.strip()
            for a in re.split(r"(?=Outstanding Value Award)", awards_raw)
            if a.strip()
        ]

        desc_el = h4.find_next_sibling("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        awards_list.append(
            {
            "provider": provider,
            "awards": awards,
            "description": description
            }
        )
    
    # Fallback: some awards are presented as images of the winner logos rather than text
    # 1. winner presented by the logo filename in the src url
    # <div> Award type
    # <img> src url contains provider name
    # <span> Award category
    # <p> Description
    if not awards_list:
        for article in soup.find_all("article"):
            img = article.find("img")
            if not img:
                continue
 
            img_src = img.get("src", "") + " " + img.get("srcset", "")
            if INSURANCE_PROVIDERS not in img_src.lower():
                continue
 
            award_type_div = article.find("div")
            award_type = award_type_div.get_text(strip=True) if award_type_div else "Award Winner"
 
            category_span = article.find("span")
            category = category_span.get_text(strip=True) if category_span else ""
 
            award_title = f"{award_type} – {category}" if category else award_type
 
            desc_el = article.find("p")
            description = desc_el.get_text(strip=True) if desc_el else ""
 
            src_filename = img.get("src", "").split("/")[-1]
            provider_name = urllib.parse.unquote(src_filename).split(" Logo")[0].split(".")[0]
 
            awards_list.append(
                {
                    "provider": provider_name if provider_name else "Medibank",
                    "awards": [award_title],
                    "description": description,
                }
            )
    
    # 2. winner presented as an <img> logo with award title in a nearby <span class="group-title">
    if not awards_list:
        for img in soup.find_all("img", alt=True):
            if INSURANCE_PROVIDERS not in img["alt"].lower():
                continue
 
            award_title = "Award Winner"
            for parent in img.parents:
                group_title = parent.find("span", class_="group-title")
                if group_title:
                    award_title = group_title.get_text(strip=True)
                    break
 
            awards_list.append(
                {
                    "provider": img["alt"],
                    "awards": [award_title],
                    "description": "",
                }
            )
 
    return awards_list

def scrape_all_insurance_awards() -> list[dict]:
    results = []
 
    for url in INSURANCE_AWARD_URLS:
        print(f"Checking: {url}")
        soup = fetch_url(url)
        if soup is None:
            continue
 
        if not medibank_mentioned(soup):
            print("Medibank not mentioned. Skipping.")
            continue
        
        meta = extract_page_meta(soup, url)
        if not cutoff_date(meta):
            # if the award was released before the cutoff date (7 days), then skip it
            # if no release date is found, assume it's relevant and keep it
            print("Award released before cutoff date. Skipping.")
            continue

        awards_list = extract_medibank_awards(soup)
        if not awards_list:
            print("Medibank mentioned but no awards found. Skipping.")
            continue
 
        print("Extracting awards...")
 
        results.append(
            {
                **meta,
                "medibank_awards": awards_list,
            }
        )
 
    return results

# ---- Output Helpers ------------------------------------------------------
def build_payload(content: str) -> dict:
    return {
        "source":     SOURCE,
        "tier":       TIER,
        "dataset":    DATASET,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "url":        URL,
        "content":    content,
    }
 
def upload_to_s3(payload: dict) -> None:
    s3 = boto3.client("s3", region_name="ap-southeast-2")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = (
        f"raw/{payload['tier']}/"
        f"{payload['source']}_{payload['dataset']}_{date}.json"
    )
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False),
        ContentType="application/json",
    )
    print(f"Uploaded: s3://{BUCKET}/{key}")
 
def save_local(payload: dict, directory: str = ".") -> None:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"{directory}/{payload['source']}_{payload['dataset']}_{date}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved locally: {path}")


# ---- Main Execution ------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Canstar health insurance awards scraper"
    )
    parser.add_argument(
        "--local",
        metavar="DIR",
        nargs="?",
        const=".",
        help="Save JSON locally to DIR instead of uploading to S3 (default: current directory)",
    )
    args = parser.parse_args()
 
    content = scrape_all_insurance_awards()
    if not content:
        print("[SKIP] Medibank was not found on any insurance award page — skipping output.")
        raise SystemExit(1)
 
    print(f"\nFound Medibank awards on {len(content)} page(s).")
    payload = build_payload(content)
 
    if args.local:
        save_local(payload, args.local)
    else:
        upload_to_s3(payload)


    