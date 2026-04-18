import requests
from bs4 import BeautifulSoup
import feedparser
import os
import json
import time
from datetime import datetime

def scrape_state_health_sites():
    print("--- State Health Department Sites ---")
    
    sources = [
        {"name": "NSW Health", "url": "https://www.health.nsw.gov.au/news/Pages/default.aspx"},
        {"name": "VIC Health", "url": "https://www.health.vic.gov.au/media-releases"},
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    
    all_articles = []
    
    # scrape NSW and VIC
    for source in sources:
        print(f"Fetching {source['name']}...")
        try:
            response = requests.get(source["url"], headers=headers, timeout=30)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                links = soup.find_all("a", href=True)
                count = 0
                for link in links:
                    text = link.get_text(strip=True)
                    href = link["href"]
                    if len(text) > 20:
                        if not href.startswith("http"):
                            base = "https://" + source["url"].split("/")[2]
                            href = base + "/" + href.lstrip("/")
                        all_articles.append(f"[{source['name']}] {text} ({href})")
                        count += 1
                        if count >= 10:
                            break
                print(f"✓ {source['name']}: found {count} articles")
            else:
                print(f"✗ {source['name']}: Failed {response.status_code} — skipping")
        except Exception as e:
            print(f"✗ {source['name']}: Error — {e}")
        time.sleep(2)
    
    # QLD via Google News RSS
    print("Fetching QLD Health via Google News RSS...")
    try:
        qld_url = "https://news.google.com/rss/search?q=Queensland+Health+private+hospital&hl=en-AU&gl=AU&ceid=AU:en"
        feed = feedparser.parse(qld_url)
        count = 0
        for entry in feed.entries[:10]:
            all_articles.append(f"[QLD Health - Google News] {entry.title} ({entry.link})")
            count += 1
        print(f"✓ QLD Health (Google News): found {count} articles")
    except Exception as e:
        print(f"✗ QLD Health: Error — {e}")
    
    # build standard JSON payload
    payload = {
        "source":     "state_health",
        "tier":       "phi_industry",
        "dataset":    "hospital_news",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.health.nsw.gov.au / https://www.health.vic.gov.au / https://www.health.qld.gov.au",
        "content":    "\n".join(all_articles)
    }
    
    os.makedirs("data/state_health", exist_ok=True)
    with open("data/state_health/state_health_news.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print(f"\nTotal articles saved: {len(all_articles)}")
    print("✓ Saved to data/state_health/state_health_news.json")
    print("State Health done!\n")

scrape_state_health_sites()