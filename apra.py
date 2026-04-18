import requests
import os
import json
import time
import pandas as pd
from datetime import datetime

def download_apra_quarterly():
    print("--- APRA Quarterly Stats ---")
    
    files = [
        {
            "name": "membership_and_benefits_dec2025.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2026-02/Quarterly%20Private%20Health%20Insurance%20Membership%20and%20Benefits%20December%202025.xlsx",
            "description": "Quarterly PHI Membership and Benefits - December 2025"
        },
        {
            "name": "membership_coverage_dec2025.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2026-02/Quarterly%20Private%20Health%20Insurance%20Membership%20Coverage%20December%202025.xlsx",
            "description": "Quarterly PHI Membership Coverage - December 2025"
        },
        {
            "name": "medical_gap_dec2025.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2026-02/Quarterly%20Private%20Health%20Insurance%20Medical%20Gap%20December%202025.xlsx",
            "description": "Quarterly PHI Medical Gap - December 2025"
        },
        {
            "name": "membership_trends_dec2025.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2026-02/Quarterly%20Private%20Health%20Insurance%20Membership%20Trends%20December%202025.xlsx",
            "description": "Quarterly PHI Membership Trends - December 2025"
        },
        {
            "name": "benefit_trends_dec2025.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2026-02/Quarterly%20Private%20Health%20Insurance%20Benefit%20Trends%20December%202025.xlsx",
            "description": "Quarterly PHI Benefit Trends - December 2025"
        }
    ]
    
    os.makedirs("data/apra", exist_ok=True)
    
    content = "APRA Quarterly Private Health Insurance Statistics - December 2025\n\n"
    
    for file in files:
        print(f"Downloading: {file['name']}...")
        response = requests.get(file["url"])
        
        if response.status_code == 200:
            filepath = f"data/apra/{file['name']}"
            with open(filepath, "wb") as f:
                f.write(response.content)
            print(f"✓ Downloaded: {file['name']}")
            
            # extract text from xlsx
            try:
                df = pd.read_excel(filepath, sheet_name=0, nrows=20)
                content += f"=== {file['description']} ===\n"
                content += df.to_string(index=False) + "\n\n"
                print(f"✓ Extracted text from: {file['name']}")
            except Exception as e:
                content += f"=== {file['description']} ===\n"
                content += f"File downloaded. Manual review required.\n\n"
                print(f"⚠ Could not extract text: {e}")
        else:
            print(f"✗ Failed: {response.status_code}")
        
        time.sleep(1)
    
    # build standard JSON payload
    payload = {
        "source":     "apra",
        "tier":       "phi_industry",
        "dataset":    "phi_stats",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.apra.gov.au/quarterly-private-health-insurance-statistics",
        "content":    content.strip()
    }
    
    with open("data/apra/apra_quarterly.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved: data/apra/apra_quarterly.json")
    print("APRA Quarterly done!\n")

download_apra_quarterly()