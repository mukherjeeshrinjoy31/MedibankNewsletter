import os
import json
from datetime import datetime

def scrape_phi_legislation():
    print("--- PHI Legislation (Federal Register) ---")
    
    known_rules = [
        {
            "title": "Private Health Insurance Legislation Amendment Rules (No. 2) 2026 - PHI 17/26",
            "date": "25 February 2026",
            "summary": "Corrects administrative error in PHI 16/26 - restores items to Support list from 1 March 2026"
        },
        {
            "title": "Private Health Insurance Legislation Amendment Rules (No. 1) 2026 - PHI 16/26",
            "date": "20 February 2026",
            "summary": "GMST, PST and DIST changes from 1 March 2026 - ends 85% out-of-hospital benefit for 100+ items"
        },
        {
            "title": "Private Health Insurance Legislation Amendment Rules (No. 1) 2025 - PHI 100/24",
            "date": "17 December 2024",
            "summary": "DIST and PST changes from 1 January 2025"
        }
    ]
    
    # convert to plain text for content field
    content = ""
    for rule in known_rules:
        content += f"Title: {rule['title']}\n"
        content += f"Date: {rule['date']}\n"
        content += f"Summary: {rule['summary']}\n\n"
    
    # build standard JSON payload
    payload = {
        "source":     "legislation",
        "tier":       "phi_industry",
        "dataset":    "phi_amendments",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.legislation.gov.au/Series/F2007L00523",
        "content":    content.strip()
    }
    
    os.makedirs("data/legislation", exist_ok=True)
    with open("data/legislation/phi_amendment_rules.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved to data/legislation/phi_amendment_rules.json")
    print("Legislation done!\n")

scrape_phi_legislation()