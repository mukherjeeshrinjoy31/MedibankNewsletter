import argparse
import logging
import os
import shutil
from typing import Optional

from src.scrapers.public_sentiment.canstar_health_awards import run as run_canstar
from src.scrapers.public_sentiment.ama import run as run_ama
from src.scrapers.public_sentiment.choice_articles import run as run_choice
from src.scrapers.public_sentiment.news_articles import run as run_news
from src.scrapers.stock_market.stock_prices import run as run_stock_prices
from src.scrapers.medibank_specific.medibank_asx_scraper import run as run_medibank_asx
from src.scrapers.medibank_specific.nib_asx_scraper import run as run_nib_asx
from src.scrapers.medibank_specific.medibank_media_scraper import run as run_medibank_media
from src.scrapers.medibank_specific.hbf_home_page_offers_scraper import run as run_hbf_offers
from src.scrapers.medibank_specific.hcf_home_page_offers_scraper import run as run_hcf_offers
# add other scrapers here as needed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

class ScraperOrchestrator:
    def __init__(self, local: Optional[str]):
        self.local = local
        self.scrapers = [
            ("canstar_health_awards", run_canstar),
            ("ama", run_ama),
            ("choice_articles", run_choice),
            ("news_articles", run_news),
            ("stock_prices", run_stock_prices),
            ("medibank_asx", run_medibank_asx),
            ("nib_asx", run_nib_asx),
            ("medibank_media", run_medibank_media),
            ("hbf_offers", run_hbf_offers),
            ("hcf_offers", run_hcf_offers)
        ]

    def run_all(self):
        summary = {}

        if self.local:  # only delete if saving locally
            data_root = "data"
            if os.path.exists(data_root):
                shutil.rmtree(data_root)
                logger.info("Deleted existing data/ directory for a fresh run")

        for name, fn in self.scrapers:
            logger.info("Starting %s", name)
            try:
                ok = fn(self.local)
                summary[name] = {"success": bool(ok)}
                logger.info("Finished %s (success=%s)", name, ok)
            except Exception as exc:
                logger.exception("Error running %s", name)
                summary[name] = {"success": False, "error": str(exc)}
        return summary

def main():
    parser = argparse.ArgumentParser(description="Run all public_sentiment scrapers")
    parser.add_argument("--local", metavar="DIR", nargs="?", const=".", help="Save outputs locally")
    args = parser.parse_args()

    orchestrator = ScraperOrchestrator(args.local)
    summary = orchestrator.run_all()

    for name, info in summary.items():
        status = "OK" if info["success"] else f"FAILED: {info.get('error')}"
        logger.info("%s -> %s", name, status)

if __name__ == "__main__":
    main()
