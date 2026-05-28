"""
Macro Scrapers
--------------
Scrapers for macroeconomic data sources relevant to the
private health insurance industry and Medibank's operating environment.

Scrapers:
    abs_scraper - Australian Bureau of Statistics statistical release pages
                  (CPI, Labour Force, Labour Force Detailed)
"""

from .abs_scraper import run as run_abs

__all__ = [
    "run_abs",
]