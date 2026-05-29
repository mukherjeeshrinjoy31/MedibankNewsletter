import argparse
import importlib
import logging
import os
import pkgutil
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class OfferScraperOrchestrator:
    def __init__(self, local: Optional[str]):
        self.local = local
        self.scrapers = self._discover_scrapers()

    def _discover_scrapers(self):
        scrapers = []
        package = "src.offer_scrapers"                           # ✅ fixed
        package_path = os.path.join(
            os.path.dirname(__file__), "offer_scrapers"          # ✅ fixed
        )

        if not os.path.exists(package_path):
            logger.error("offer_scrapers folder not found at: %s", package_path)
            return scrapers

        for _, module_name, _ in pkgutil.iter_modules([package_path]):
            if module_name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"{package}.{module_name}")
                if hasattr(module, "run"):
                    scrapers.append((module_name, module.run))
                    logger.info("Discovered scraper: %s", module_name)
                else:
                    logger.warning("Skipping %s — no run() found", module_name)
            except Exception as e:
                logger.warning("Could not import %s: %s", module_name, e)

        if not scrapers:
            logger.warning("No scrapers discovered — check offer_scrapers folder path")

        return scrapers

    def run_all(self):
        for name, fn in self.scrapers:
            logger.info("Starting %s", name)
            try:
                fn()
                logger.info("Finished %s", name)
            except Exception:
                logger.exception("Error running %s", name)


def main():
    parser = argparse.ArgumentParser(description="Run all offer scrapers")
    parser.add_argument("--local", metavar="DIR", nargs="?", const=".", help="Save outputs locally")
    args = parser.parse_args()

    orchestrator = OfferScraperOrchestrator(args.local)
    orchestrator.run_all()


if __name__ == "__main__":
    main()