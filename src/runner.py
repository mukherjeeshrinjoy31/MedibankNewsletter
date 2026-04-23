import argparse
import logging
from typing import Optional

from src.scrapers.public_sentiment.canstar_health_awards import run as run_canstar
from src.scrapers.public_sentiment.ama import run as run_ama
from src.scrapers.public_sentiment.choice_articles import run as run_choice
from src.scrapers.public_sentiment.news_articles import run as run_news
from src.scrapers.stock_market.stock_prices import run as run_stock_prices
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
            # Add the new stock prices scraper
            ("stock_prices", run_stock_prices),
        ]

    def run_all(self):
        summary = {}
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
