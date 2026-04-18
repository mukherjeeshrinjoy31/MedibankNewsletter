import os
import json
from datetime import datetime

def scrape_ombudsman():
    print("--- PHI Ombudsman Reports ---")
    
    reports = [
        {
            "title": "Private Health Insurance - Quarterly Update 114: April to June 2025 (with annual summary 2024-25)",
            "quarter": "Q4 2024-25",
            "date": "2025"
        },
        {
            "title": "Private Health Insurance - Quarterly Update 113: January to March 2025",
            "quarter": "Q3 2024-25",
            "date": "2025"
        },
        {
            "title": "Private Health Insurance - Quarterly Update 112: October to December 2024 - Hospital agreement dispute between Healthscope, Bupa and AHSA",
            "quarter": "Q2 2024-25",
            "date": "2024"
        },
        {
            "title": "Private Health Insurance - Quarterly Update 111: July to September 2024",
            "quarter": "Q1 2024-25",
            "date": "2024"
        },
        {
            "title": "Private Health Insurance - Quarterly Update 110: January to June 2024 with Annual Summary 2023-24",
            "quarter": "Q3-Q4 2023-24",
            "date": "2024"
        }
    ]
    
    # convert to plain text for content field
    content = ""
    for report in reports:
        content += f"Title: {report['title']}\n"
        content += f"Quarter: {report['quarter']}\n"
        content += f"Date: {report['date']}\n\n"
    
    # build standard JSON payload
    payload = {
        "source":     "ombudsman",
        "tier":       "phi_industry",
        "dataset":    "phi_reports",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.ombudsman.gov.au/industry-and-agency-oversight/industry-updates/private-health-insurance-updates",
        "content":    content.strip()
    }
    
    os.makedirs("data/ombudsman", exist_ok=True)
    with open("data/ombudsman/phi_reports.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved to data/ombudsman/phi_reports.json")
    print("Ombudsman done!\n")

scrape_ombudsman()