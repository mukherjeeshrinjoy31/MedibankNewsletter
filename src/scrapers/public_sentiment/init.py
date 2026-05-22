"""
Public Sentiment Scrapers
-------------------------
Scrapers for public-facing news, awards, deals and consumer sentiment
sources relevant to Medibank and the private health insurance industry.

Scrapers:
    abc_news            - ABC News articles via Playwright
    ama                 - AMA Private Health Insurance Report Card (PDF)
    canstar_health_awards - Canstar insurance award pages
    choice_articles     - Choice.com.au Medibank-related articles
    news_articles       - ABC, SBS, Guardian RSS feeds via trafilatura
    ozbargain_deals     - OzBargain Medibank deals RSS feed
    sbs_news            - SBS News articles via Playwright
    the_guardian_au     - The Guardian AU articles via Playwright
"""

from .abc_news import run as run_abc_news
from .ama import run as run_ama
from .canstar_health_awards import run as run_canstar
from .choice_articles import run as run_choice
from .news_articles import run as run_news
from .ozbargain_deals import run as run_ozbargain
from .sbs_news import run as run_sbs_news
from .the_guardian_au import run as run_guardian

__all__ = [
    "run_abc_news",
    "run_ama",
    "run_canstar",
    "run_choice",
    "run_news",
    "run_ozbargain",
    "run_sbs_news",
    "run_guardian",
]