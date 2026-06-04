import argparse
import importlib
import logging
import os
import pkgutil
import time
from datetime import timedelta
from typing import Optional


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class OfferScraperOrchestrator:
    def __init__(self, local: Optional[str]):
        self.local = local
        self.scrapers = self._discover_scrapers()

    def _discover_scrapers(self):
        scrapers = []
        package = "src.offer_scrapers"
        package_path = os.path.join(
            os.path.dirname(__file__), "offer_scrapers"
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

        # Always run finder last
        scrapers.sort(key=lambda x: x[0] == "finder")

        return scrapers

    def run_all(self):
        summary = {}
        pipeline_start = time.time()

        for name, fn in self.scrapers:
            scraper_start = time.time()
            logger.info("Starting %s", name)
            try:
                ok = fn(self.local)
                duration = timedelta(seconds=int(time.time() - scraper_start))
                summary[name] = {"success": bool(ok), "duration": str(duration)}
                logger.info("Finished %s (success=%s, duration=%s)", name, ok, duration)
            except Exception as exc:
                duration = timedelta(seconds=int(time.time() - scraper_start))
                logger.exception("Error running %s", name)
                summary[name] = {"success": False, "error": str(exc), "duration": str(duration)}

        pipeline_duration = timedelta(seconds=int(time.time() - pipeline_start))
        return summary, pipeline_duration


def main():
    parser = argparse.ArgumentParser(description="Run all offer scrapers")
    parser.add_argument("--local", metavar="DIR", nargs="?", const="data", help="Save outputs locally")
    args = parser.parse_args()

    orchestrator = OfferScraperOrchestrator(args.local)
    summary, total_duration = orchestrator.run_all()

    logger.info("=" * 65)
    logger.info("%-30s %-10s %s", "SCRAPER", "STATUS", "DURATION")
    logger.info("=" * 65)
    for name, info in summary.items():
        status = "OK" if info["success"] else "FAILED"
        logger.info("%-30s %-10s %s", name, status, info.get("duration", ""))
    logger.info("=" * 65)
    logger.info("Total duration: %s", total_duration)
    logger.info("=" * 65)


if __name__ == "__main__":
    main()