"""
PHI Industry Scrapers
---------------------
Scrapers for Private Health Insurance industry data sources including
regulatory bodies, government departments and industry publications.

Scrapers:
    accc          - ACCC PHI Senate reports (PDF)
    apra          - APRA quarterly PHI statistics (XLSX)
    apra_annual   - APRA annual PHI statistics (XLSX)
    health_dept   - Dept of Health premium approvals and clinical categories
    legislation   - Federal Register of Legislation PHI amendment rules
    mbs           - Medicare Benefits Schedule XML files
    newsrooms     - Competitor newsrooms (Bupa, NIB, HCF, HBF)
    ombudsman     - PHI Ombudsman quarterly reports
    privatehealth - PrivateHealth.gov.au monthly product data ZIP
"""

from .accc import run as run_accc
from .apra import run as run_apra
from .apra_annual import run as run_apra_annual
from .health_dept import run as run_health_dept
from .legislation import run as run_legislation
from .mbs import run as run_mbs
from .newsrooms import run as run_newsrooms
from .ombudsman import run as run_ombudsman
from .privatehealth import run as run_privatehealth

__all__ = [
    "run_accc",
    "run_apra",
    "run_apra_annual",
    "run_health_dept",
    "run_legislation",
    "run_mbs",
    "run_newsrooms",
    "run_ombudsman",
    "run_privatehealth",
]