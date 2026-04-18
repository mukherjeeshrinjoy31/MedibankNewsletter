import requests
import zipfile
import io
import os
import json
import time
from datetime import datetime

def download_privatehealth_zip():
    print("--- PrivateHealth.gov.au ZIP ---")
    
    url = "https://data.gov.au/data/dataset/8ab10b1f-6eac-423c-abc5-bbffc31b216c/resource/ca9c9e9f-a114-4e9a-a29f-6b3f641b8e6f/download/privatehealth-01-mar-2026.zip"
    
    print("Downloading ZIP file...")
    response = requests.get(url, timeout=60)
    
    content = "PrivateHealth.gov.au Monthly Product Data - March 2026\n\n"
    
    if response.status_code == 200:
        print("✓ ZIP downloaded! Extracting...")
        os.makedirs("data/privatehealth", exist_ok=True)
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall("data/privatehealth/")
            extracted = z.namelist()
        
        print(f"✓ Extracted {len(extracted)} files")
        content += "Files extracted from PrivateHealth.gov.au March 2026 ZIP:\n"
        for f in extracted:
            content += f"- {f}\n"
        content += "\nContains: XML files for all registered PHI products from all 29 insurers, "
        content += "CSV files for hospital agreements and fund changes, "
        content += "covering prices, coverage tiers, exclusions, and waiting periods."
    else:
        print(f"✗ Failed: {response.status_code}")
        content += "Download failed. Manual download required from data.gov.au"
    
    # build standard JSON payload
    payload = {
        "source":     "privatehealth",
        "tier":       "phi_industry",
        "dataset":    "products",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "https://data.gov.au/data/dataset/private-health-insurance",
        "content":    content.strip()
    }
    
    with open("data/privatehealth/privatehealth_products.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved: data/privatehealth/privatehealth_products.json")
    print("PrivateHealth done!\n")

download_privatehealth_zip()