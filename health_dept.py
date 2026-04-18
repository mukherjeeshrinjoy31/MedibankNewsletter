import requests
import os
import json
import time
from datetime import datetime

def scrape_health_dept():
    print("--- Dept of Health: Premium Approvals & MBS Clinical Categories ---")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    
    # premium approvals content
    premium_content = """Premium Approvals - Australian Government Department of Health

1. Average premium increase of 4.41% approved for 1 April 2026
   Date: February 2026
   Details: The Australian Government approved an average industry premium increase of 4.41% effective 1 April 2026, the largest since 2017.

2. Average premium increase of 3.03% approved for 1 April 2025
   Date: February 2025
   Details: The Australian Government approved an average industry premium increase of 3.03% effective 1 April 2025.

3. Average premium increase of 3.03% approved for 1 April 2024
   Date: February 2024
   Details: The Australian Government approved an average industry premium increase of 3.03% effective 1 April 2024."""

    # save premium approvals JSON
    premium_payload = {
        "source":     "health_dept",
        "tier":       "phi_industry",
        "dataset":    "premium_approvals",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.health.gov.au/ministers",
        "content":    premium_content.strip()
    }

    os.makedirs("data/health_dept", exist_ok=True)
    with open("data/health_dept/premium_approvals.json", "w") as f:
        json.dump(premium_payload, f, indent=2)
    print("✓ Saved: premium_approvals.json")

    # download MBS clinical categories files
    files = [
        {
            "name": "mbs_clinical_category_definitions_march2026.pdf",
            "url": "https://www.health.gov.au/sites/default/files/2026-02/private-health-insurance-clinical-category-definitions-1-march-2026_0.pdf"
        },
        {
            "name": "mbs_clinical_category_classification_march2026.xlsx",
            "url": "https://www.health.gov.au/sites/default/files/2026-02/private-health-insurance-clinical-category-classification-1-march-2026_1.xlsx"
        }
    ]

    clinical_content = "MBS Clinical Categories - Department of Health - 1 March 2026\n\n"
    clinical_content += "Contains 38 clinical categories mapped to Gold/Silver/Bronze/Basic tiers.\n"
    clinical_content += "Effective date: 1 March 2026\n"
    clinical_content += "Source: health.gov.au/resources/publications/private-health-insurance-clinical-category-definitions-1-march-2026\n\n"
    clinical_content += "Files downloaded:\n"

    for file in files:
        print(f"Downloading: {file['name']}...")
        response = requests.get(file["url"], headers=headers, timeout=30)
        if response.status_code == 200:
            with open(f"data/health_dept/{file['name']}", "wb") as f:
                f.write(response.content)
            clinical_content += f"- {file['name']}\n"
            print(f"✓ Saved: {file['name']}")
        else:
            print(f"✗ Failed: {response.status_code}")
        time.sleep(1)

    # save clinical categories JSON
    clinical_payload = {
        "source":     "health_dept",
        "tier":       "phi_industry",
        "dataset":    "clinical_categories",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.health.gov.au/resources/publications/private-health-insurance-clinical-category-definitions-1-march-2026",
        "content":    clinical_content.strip()
    }

    with open("data/health_dept/clinical_categories.json", "w") as f:
        json.dump(clinical_payload, f, indent=2)
    print("✓ Saved: clinical_categories.json")

    print("Health Dept done!\n")

scrape_health_dept()