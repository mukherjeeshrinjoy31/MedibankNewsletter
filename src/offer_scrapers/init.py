"""
Offer Scrapers
--------------
Scrapers for direct and aggregator health insurance offer data.
Each scraper collects current promotional offers from insurer websites
and aggregator platforms, updating both S3 JSON files and the
competitor offer Excel workbook.

Scrapers:
    ahm      - AHM direct offer pages
    medibank  - Medibank direct offer pages
    hbf       - HBF direct offer pages (Playwright)
    hcf       - HCF direct offer pages
    nib       - NIB direct offer pages
    bupa      - Bupa direct offer pages (Playwright)
    finder    - Finder.com.au aggregator (Playwright, runs last)
"""

from .ahm import run as run_ahm
from .medibank import run as run_medibank
from .hbf import run as run_hbf
from .hcf import run as run_hcf
from .nib import run as run_nib
from .bupa import run as run_bupa
from .finder import run as run_finder

__all__ = [
    "run_ahm",
    "run_medibank",
    "run_hbf",
    "run_hcf",
    "run_nib",
    "run_bupa",
    "run_finder",
]