import boto3
import os
import json
from datetime import datetime

BUCKET = "p000268ds-medibank-intelligence-us"
REGION = "us-east-1"
TODAY = datetime.utcnow().strftime("%Y-%m-%d")

AWS_ACCESS_KEY_ID = ""
AWS_SECRET_ACCESS_KEY = ""
AWS_SESSION_TOKEN = ""
# all your JSON files to upload
files = [
    ("data/apra/apra_quarterly.json",          "raw/phi_industry/apra_phi_stats_{}.json"),
    ("data/apra/apra_annual.json",              "raw/phi_industry/apra_phi_annual_{}.json"),
    ("data/privatehealth/privatehealth_products.json", "raw/phi_industry/privatehealth_products_{}.json"),
    ("data/legislation/phi_amendment_rules.json", "raw/phi_industry/legislation_phi_amendments_{}.json"),
    ("data/ombudsman/phi_reports.json",         "raw/phi_industry/ombudsman_phi_reports_{}.json"),
    ("data/mbs/mbs_schedule.json",              "raw/phi_industry/mbs_schedule_{}.json"),
    ("data/health_dept/premium_approvals.json", "raw/phi_industry/health_dept_premium_approvals_{}.json"),
    ("data/health_dept/clinical_categories.json", "raw/phi_industry/health_dept_clinical_categories_{}.json"),
    ("data/accc/accc_phi_reports.json",         "raw/phi_industry/accc_phi_reports_{}.json"),
    ("data/newsrooms/competitor_news.json",     "raw/phi_industry/newsrooms_competitor_news_{}.json"),
    ("data/state_health/state_health_news.json", "raw/phi_industry/state_health_hospital_news_{}.json"),
]

def upload_to_s3():
    print("--- Uploading to S3 ---")
    
    s3 = boto3.client(
    "s3",
    region_name=REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    aws_session_token=AWS_SESSION_TOKEN
)
    
    for local_path, s3_key_template in files:
        s3_key = s3_key_template.format(TODAY)
        
        if os.path.exists(local_path):
            print(f"Uploading: {s3_key}...")
            try:
                s3.upload_file(local_path, BUCKET, s3_key)
                print(f"✓ Uploaded: {s3_key}")
            except Exception as e:
                print(f"✗ Failed: {e}")
        else:
            print(f"✗ File not found: {local_path}")
    
    print("\nAll uploads done!")

upload_to_s3()