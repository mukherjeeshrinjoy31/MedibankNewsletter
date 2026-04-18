import requests
import os
import json
import time
from datetime import datetime

def download_accc_reports():
    print("--- ACCC PHI Reports ---")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    
    files = [
        {
            "name": "accc_phi_report_2024_25.pdf",
            "url": "https://www.accc.gov.au/system/files/private-health-insurance-report-2024-25.pdf",
            "description": "ACCC Private Health Insurance Report 2024-25"
        },
        {
            "name": "accc_phi_report_2023_24.pdf",
            "url": "https://www.accc.gov.au/system/files/private-health-insurance-report-2023-24.pdf",
            "description": "ACCC Private Health Insurance Report 2023-24"
        }
    ]
    
    os.makedirs("data/accc", exist_ok=True)
    
    content = "ACCC Private Health Insurance Reports\n\n"
    
    for file in files:
        print(f"Downloading: {file['name']}...")
        response = requests.get(file["url"], headers=headers, timeout=30)
        if response.status_code == 200:
            with open(f"data/accc/{file['name']}", "wb") as f:
                f.write(response.content)
            size_mb = len(response.content) / 1024 / 1024
            content += f"- {file['description']} ({size_mb:.1f} MB)\n"
            content += f"  URL: {file['url']}\n\n"
            print(f"✓ Saved: {file['name']} ({size_mb:.1f} MB)")
        else:
            print(f"✗ Failed: {response.status_code}")
        time.sleep(1)
    
    # build standard JSON payload
    payload = {
        "source":     "accc",
        "tier":       "phi_industry",
        "dataset":    "phi_reports",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.accc.gov.au/about-us/publications/serial-publications/private-health-insurance-reports",
        "content":    content.strip()
    }
    
    with open("data/accc/accc_phi_reports.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved: accc_phi_reports.json")
    print("ACCC done!\n")

download_accc_reports()