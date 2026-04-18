# PHI Industry Signals — Data Scrapers
**RMIT WIL | Medibank AI-Driven Market Intelligence Pipeline**
**Tier 2: Private Health Insurance (PHI) Industry Signals**
**Author: Anushka Sauran (s4109010)**

---

## Overview
This folder contains all data scrapers for the PHI Industry Signals tier (Tier 2) of the Medibank Market Intelligence Pipeline. Each scraper collects data from a specific publicly available source and saves it locally, ready for conversion to the standardised JSON schema and upload to AWS S3.

---

## Scrapers

| File | Source | Output | Format |
|---|---|---|---|
| `apra.py` | APRA Quarterly PHI Statistics | `data/apra/` | XLSX + JSON |
| `apra_annual.py` | APRA Annual PHI Statistics | `data/apra/` | XLSX + JSON |
| `privatehealth.py` | PrivateHealth.gov.au Monthly ZIP | `data/privatehealth/` | XML / CSV + JSON |
| `legislation.py` | Federal Register of Legislation | `data/legislation/` | JSON |
| `ombudsman.py` | PHI Ombudsman Quarterly Reports | `data/ombudsman/` | JSON |
| `mbs.py` | MBS Online XML | `data/mbs/` | XML + JSON |
| `health_dept.py` | Dept of Health — Premium Approvals & MBS Clinical Categories | `data/health_dept/` | PDF / XLSX + JSON |
| `accc.py` | ACCC PHI Annual Reports | `data/accc/` | PDF + JSON |
| `newsrooms.py` | Competitor Newsrooms (Bupa, NIB, HCF, HBF) | `data/newsrooms/` | JSON |
| `state_health.py` | State Health Dept Sites (NSW, VIC, QLD) | `data/state_health/` | JSON |

---

## Setup

**1. Clone the repository and navigate to this folder**
```bash
git clone <repo-url>
cd phi_industry
```

**2. Create and activate a virtual environment**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

---

## Running the Scrapers

Run each scraper individually:
```bash
python scrapers/apra.py
python scrapers/apra_annual.py
python scrapers/privatehealth.py
python scrapers/legislation.py
python scrapers/ombudsman.py
python scrapers/mbs.py
python scrapers/health_dept.py
python scrapers/accc.py
python scrapers/newsrooms.py
python scrapers/state_health.py
```

All output is saved to the `data/` folder automatically.

---

## Dependencies

` ` `
requests
beautifulsoup4
feedparser
pandas
openpyxl
lxml
pdfplumber
` ` `

Install via:
```bash
pip install -r requirements.txt
```

---

## Notes

- All sources are publicly available — no API keys or authentication required
- Some sources (Ombudsman, Legislation) use hardcoded JSON due to scraping blocks — these are reliable and updated manually when new releases are published
- For competitor newsrooms, always verify Terms of Service before scraping
- All scrapers output a standardised JSON file following the v2.0 schema 
(source, tier, dataset, scraped_at, url, content) ready for S3 upload
- Two years of APRA data (2023–2025) is recommended for trend analysis; all other sources use current releases only

---

## Data Sources

| Source | Link | Update Frequency |
|---|---|---|
| APRA Quarterly PHI Statistics | [apra.gov.au](https://www.apra.gov.au/quarterly-private-health-insurance-statistics) | Quarterly |
| APRA Annual PHI Statistics | [apra.gov.au](https://www.apra.gov.au/operations-of-private-health-insurers-annual-report) | Annual |
| PrivateHealth.gov.au ZIP | [data.gov.au](https://data.gov.au/data/dataset/private-health-insurance) | Monthly |
| Dept of Health — Premium Approvals | [health.gov.au](https://www.health.gov.au/ministers) | Annual (April) |
| Dept of Health — MBS Clinical Categories | [health.gov.au](https://www.health.gov.au/resources/publications/private-health-insurance-clinical-category-definitions-1-march-2026) | When MBS changes |
| MBS Online XML | [mbsonline.gov.au](http://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/downloads) | Monthly |
| PHI Ombudsman Reports | [ombudsman.gov.au](https://www.ombudsman.gov.au/industry-and-agency-oversight/industry-updates/private-health-insurance-updates) | Quarterly |
| Federal Register of Legislation | [legislation.gov.au](https://www.legislation.gov.au/Series/F2007L00523) | As published |
| ACCC Reports | [accc.gov.au](https://www.accc.gov.au/about-us/publications/serial-publications/private-health-insurance-reports) | Annual + ad hoc |
| Competitor Newsrooms | Bupa / NIB / HCF / HBF | As published |
| State Health Dept Sites | NSW / VIC / QLD Health | As published |

---

*RMIT University — Master of Data Science WIL Program*
*Medibank Partnership — March to June 2026*