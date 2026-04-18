import requests
from bs4 import BeautifulSoup
import os
import json
import time
from datetime import datetime

def scrape_newsrooms():
    print("--- Competitor Newsrooms ---")
    
    sources = [
        {"name": "Bupa", "url": "https://media.bupa.com.au/"},
        {"name": "NIB", "url": "https://www.nib.com.au/media"},
        {"name": "HCF", "url": "https://www.hcf.com.au/about-us/media-centre/media-releases"},
        {"name": "HBF", "url": "https://www.hbf.com.au/about-hbf/newsroom"}
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    
    all_articles = []
    
    for source in sources:
        print(f"Fetching {source['name']} newsroom...")
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
                            href = source["url"].rstrip("/") + "/" + href.lstrip("/")
                        all_articles.append(f"[{source['name']}] {text} ({href})")
                        count += 1
                        if count >= 10:
                            break
                print(f"✓ {source['name']}: found {count} articles")
            else:
                print(f"✗ {source['name']}: Failed {response.status_code}")
        except Exception as e:
            print(f"✗ {source['name']}: Error — {e}")
        time.sleep(2)
    
    # build standard JSON payload
    payload = {
        "source":     "newsrooms",
        "tier":       "phi_industry",
        "dataset":    "competitor_news",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://media.bupa.com.au / https://www.nib.com.au/media / https://www.hcf.com.au/about-us/media-centre / https://www.hbf.com.au/about-hbf/newsroom",
        "content":    "\n".join(all_articles)
    }
    
    os.makedirs("data/newsrooms", exist_ok=True)
    with open("data/newsrooms/competitor_news.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print(f"\nTotal articles saved: {len(all_articles)}")
    print("✓ Saved to data/newsrooms/competitor_news.json")
    print("Newsrooms done!\n")

scrape_newsrooms()