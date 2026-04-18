import requests
import os
import json
import time
import pandas as pd
from datetime import datetime

def download_apra_annual():
    print("--- APRA Annual Stats ---")
    
    files = [
        {
            "name": "annual_performance_database_2024_25.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2025-12/Annual%20private%20health%20insurance%20performance%20statistics%20database%20-%202024-2025.xlsx",
            "description": "Annual PHI Performance Statistics Database 2024-25"
        },
        {
            "name": "annual_performance_data_specifications.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2024-12/20241213%20-%20Annual%20private%20health%20insurance%20performance%20statistics%20-%20data%20specifications.xlsx",
            "description": "Annual PHI Performance Data Specifications"
        },
        {
            "name": "annual_membership_and_benefits_2024_25.xlsx",
            "url": "https://www.apra.gov.au/sites/default/files/2025-12/Annual%20private%20health%20insurance%20membership%20and%20benefits%20statistics%20-%202024-2025.xlsx",
            "description": "Annual PHI Membership and Benefits 2024-25"
        }
    ]
    
    os.makedirs("data/apra", exist_ok=True)
    
    content = "APRA Annual Private Health Insurance Statistics - 2024-25\n\n"
    
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
        "dataset":    "phi_annual",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://www.apra.gov.au/operations-of-private-health-insurers-annual-report",
        "content":    content.strip()
    }
    
    with open("data/apra/apra_annual.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved: data/apra/apra_annual.json")
    print("APRA Annual done!\n")

download_apra_annual()