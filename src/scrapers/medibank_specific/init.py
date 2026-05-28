"""
Medibank Specific Scrapers
--------------------------
Scrapers for Medibank-specific sources including ASX releases,
media releases, competitor home page offers and NIB ASX announcements.

Scrapers:
    medibank_asx_scraper          - Medibank ASX release articles
    medibank_media_scraper        - Medibank media release articles
    hbf_home_page_offers_scraper  - HBF competitor home page offers
    hcf_home_page_offers_scraper  - HCF competitor home page offers
    nib_asx_scraper               - NIB ASX announcements (PDF extraction)
"""

from .hbf_home_page_offers_scraper import run as run_hbf_offers
from .hcf_home_page_offers_scraper import run as run_hcf_offers
from .medibank_asx_scraper import run as run_medibank_asx
from .medibank_media_scraper import run as run_medibank_media
from .nib_asx_scraper import run as run_nib_asx

__all__ = [
    "run_hbf_offers",
    "run_hcf_offers",
    "run_medibank_asx",
    "run_medibank_media",
    "run_nib_asx",
]