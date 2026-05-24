import argparse
import logging
import os
import shutil
import time
from datetime import timedelta
from typing import Optional

from src.scrapers.public_sentiment.canstar_health_awards import run as run_canstar
from src.scrapers.public_sentiment.ama import run as run_ama
from src.scrapers.public_sentiment.choice_articles import run as run_choice
from src.scrapers.public_sentiment.news_articles import run as run_news
from src.scrapers.public_sentiment.abc_news import run as run_abc_news
from src.scrapers.public_sentiment.ozbargain_deals import run as run_ozbargain
from src.scrapers.public_sentiment.sbs_news import run as run_sbs_news
from src.scrapers.public_sentiment.the_guardian_au import run as run_guardian

from src.scrapers.stock_market.stock_prices import run as run_stock_prices
from src.scrapers.medibank_specific.medibank_asx_scraper import run as run_medibank_asx
from src.scrapers.medibank_specific.nib_asx_scraper import run as run_nib_asx
from src.scrapers.medibank_specific.medibank_media_scraper import run as run_medibank_media
from src.scrapers.medibank_specific.hbf_home_page_offers_scraper import run as run_hbf_offers
from src.scrapers.medibank_specific.hcf_home_page_offers_scraper import run as run_hcf_offers
from src.scrapers.phi.accc import run as run_accc
from src.scrapers.phi.apra import run as run_apra
from src.scrapers.phi.apra_annual import run as run_apra_annual
from src.scrapers.phi.health_dept import run as run_health_dept
from src.scrapers.phi.legislation import run as run_legislation
from src.scrapers.phi.mbs import run as run_mbs
from src.scrapers.phi.newsrooms import run as run_newsrooms
from src.scrapers.phi.ombudsman import run as run_ombudsman
from src.scrapers.phi.privatehealth import run as run_privatehealth
from src.scrapers.macro.abs_scraper import run as run_abs
from src.commons.tiers import TIER

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class ScraperOrchestrator:
    def __init__(self, local: Optional[str]):
        self.local = local
        self.scrapers = [
            # Public Sentiment
            #("canstar_health_awards", run_canstar,     TIER.PUBLIC_SENTIMENT),
            #("ama",                   run_ama,         TIER.PUBLIC_SENTIMENT),
            #("choice_articles",       run_choice,      TIER.PUBLIC_SENTIMENT),
            ("news_articles",         run_news,        TIER.PUBLIC_SENTIMENT),
            ("abc_news",              run_abc_news,    TIER.PUBLIC_SENTIMENT),
            #("ozbargain_deals",       run_ozbargain,   TIER.PUBLIC_SENTIMENT),
            ("sbs_news",              run_sbs_news,    TIER.PUBLIC_SENTIMENT),
            ("the_guardian_au",       run_guardian,    TIER.PUBLIC_SENTIMENT),
            # Stock Market
            
            # ("stock_prices",          run_stock_prices, TIER.COMPETITOR),
            # # Medibank Specific
            # ("medibank_asx",          run_medibank_asx,    TIER.MEDIBANK_SPECIFIC),
            # ("nib_asx",               run_nib_asx,         TIER.MEDIBANK_SPECIFIC),
            # ("medibank_media",        run_medibank_media,  TIER.MEDIBANK_SPECIFIC),
            # ("hbf_offers",            run_hbf_offers,      TIER.MEDIBANK_SPECIFIC),
            # ("hcf_offers",            run_hcf_offers,      TIER.MEDIBANK_SPECIFIC),
            # # PHI Industry
            # ("accc",                  run_accc,          TIER.PHI),
            # ("apra",                  run_apra,          TIER.PHI),
            # ("apra_annual",           run_apra_annual,   TIER.PHI),
            # ("health_dept",           run_health_dept,   TIER.PHI),
            # ("legislation",           run_legislation,   TIER.PHI),
            # ("mbs",                   run_mbs,           TIER.PHI),
            # ("newsrooms",             run_newsrooms,     TIER.PHI),
            # ("ombudsman",             run_ombudsman,     TIER.PHI),
            # ("privatehealth",         run_privatehealth, TIER.PHI),
            # # Macro
            # ("abs",                   run_abs,           TIER.MACRO),
        ]

    def run_all(self):
        summary = {}
        pipeline_start = time.time()

        if self.local:
            data_root = "data"
            if os.path.exists(data_root):
                shutil.rmtree(data_root)
                logger.info("Deleted existing data/ directory for a fresh run")

        for name, fn, tier in self.scrapers:
            scraper_start = time.time()
            logger.info("Starting %s", name)
            try:
                ok = fn(self.local)
                duration = timedelta(seconds=int(time.time() - scraper_start))
                summary[name] = {"success": bool(ok), "duration": str(duration), "category": tier.value}
                logger.info("Finished %s (success=%s, duration=%s)", name, ok, duration)
            except Exception as exc:
                duration = timedelta(seconds=int(time.time() - scraper_start))
                logger.exception("Error running %s", name)
                summary[name] = {"success": False, "error": str(exc), "duration": str(duration), "category": tier.value}

        pipeline_duration = timedelta(seconds=int(time.time() - pipeline_start))
        return summary, pipeline_duration


def main():
    parser = argparse.ArgumentParser(description="Run all scrapers")
    parser.add_argument("--local", metavar="DIR", nargs="?", const=".", help="Save outputs locally")
    args = parser.parse_args()

    orchestrator = ScraperOrchestrator(args.local)
    summary, total_duration = orchestrator.run_all()

    logger.info("=" * 75)
    logger.info("%-30s %-20s %-10s %s", "SCRAPER", "CATEGORY", "STATUS", "DURATION")
    logger.info("=" * 75)
    for name, info in summary.items():
        status = "OK" if info["success"] else "FAILED"
        logger.info("%-30s %-20s %-10s %s", name, info.get("category", ""), status, info.get("duration", ""))
    logger.info("=" * 75)
    logger.info("Total duration: %s", total_duration)
    logger.info("=" * 75)


if __name__ == "__main__":
    main()