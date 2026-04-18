import requests
import os
import json
import time
from datetime import datetime

def download_mbs_xml():
    print("--- MBS Online XML ---")
    
    files = [
        {
            "name": "MBS_XML_20260301_v2.xml",
            "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/dd6984c45a944962ca258d8600139d55/$FILE/MBS-XML-20260301-version%202.XML",
            "description": "MBS XML March 2026 Version 2"
        },
        {
            "name": "MBS_XML_20260101.xml",
            "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/ba88a4b5d1c80bbaca258d490018207c/$FILE/MBS-XML-20260101.XML",
            "description": "MBS XML January 2026"
        },
        {
            "name": "MBS_XML_20251101_v2.xml",
            "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/928fae91a23256aaca258d0d0007eede/$FILE/MBS-XML-20251101%20Version%202.XML",
            "description": "MBS XML November 2025 Version 2"
        },
        {
            "name": "MBS_XML_20250701_v3.xml",
            "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/650f3eec0dfb990fca25692100069854/0b61e1e80b332754ca258c9e0000c7d8/$FILE/MBS-XML-20250701%20Version%203.XML",
            "description": "MBS XML July 2025 Version 3"
        },
        {
            "name": "MBS_XML_20250301.xml",
            "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/C73750F033F64E1CCA258C190017A963/$File/MBS-XML-20250301.XML",
            "description": "MBS XML March 2025"
        },
        {
            "name": "MBS_XML_20250101.xml",
            "url": "https://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/9A8C6D685899CD47CA258BE800197F3B/$File/MBS-XML-20250101.xml",
            "description": "MBS XML January 2025"
        }
    ]
    
    os.makedirs("data/mbs", exist_ok=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
    
    content = "Medicare Benefits Schedule (MBS) XML Files - 2025 to 2026\n\n"
    content += "Contains all MBS items, fees, and clinical category assignments.\n"
    content += "Source: mbsonline.gov.au\n\n"
    content += "Files downloaded:\n"
    
    for file in files:
        print(f"Downloading: {file['name']}...")
        response = requests.get(file["url"], headers=headers, timeout=60)
        
        if response.status_code == 200:
            with open(f"data/mbs/{file['name']}", "wb") as f:
                f.write(response.content)
            size_mb = len(response.content) / 1024 / 1024
            content += f"- {file['description']} ({size_mb:.1f} MB)\n"
            print(f"✓ Saved: {file['name']} ({size_mb:.1f} MB)")
        else:
            print(f"✗ Failed: {response.status_code}")
        
        time.sleep(2)
    
    # build standard JSON payload
    payload = {
        "source":     "mbs",
        "tier":       "phi_industry",
        "dataset":    "schedule",
        "scraped_at": datetime.utcnow().isoformat(),
        "url":        "http://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/downloads",
        "content":    content.strip()
    }
    
    with open("data/mbs/mbs_schedule.json", "w") as f:
        json.dump(payload, f, indent=2)
    
    print("✓ Saved: data/mbs/mbs_schedule.json")
    print("MBS done!\n")

download_mbs_xml()