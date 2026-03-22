"""
Pipeline orchestrator: currency update -> BIO collection -> PosPro migration.
Runs in a background thread, updates shared progress object.
"""

import logging
import os
from datetime import datetime

from . import currency, rates_data
from .collector import run_collection
from .migrator import run_migration
from .progress import progress

log = logging.getLogger(__name__)


def run_full_pipeline():
    """
    Runs the full BIO import pipeline.
    Called in a background thread from the API route.
    """
    progress.reset()
    progress.update(status="running", started_at=datetime.now().isoformat())

    try:
        # Step 0: Update currency rates
        log.info("Updating currency rates...")
        currency.update_all_rates(rates_data)
        log.info(f"Rates: RUB={rates_data.exchange_rates.get('RUB')}, "
                 f"EUR={rates_data.bio_rates.get('EUR')}, USD={rates_data.bio_rates.get('USD')}")

        # Step 1: Collect from BIO API -> SQLite
        progress.update(stage="collecting")
        log.info("Starting BIO collection...")
        run_collection(progress)
        progress.update(collecting_done=True)
        log.info(f"Collection done: {progress.collecting_products_count} products")

        # Step 2: Migrate from SQLite -> PosPro API
        progress.update(stage="migrating")
        log.info("Starting migration to PosPro...")
        api_url = os.getenv('API_BASE_URL', 'https://pospro-new-server.onrender.com/api')
        run_migration(progress, api_url=api_url)
        progress.update(migrating_done=True)
        log.info("Migration done")

        progress.update(status="completed", finished_at=datetime.now().isoformat(), stage=None)
        log.info("Full pipeline completed successfully")

    except Exception as e:
        log.exception(f"Pipeline error: {e}")
        progress.update(
            status="error",
            error=str(e),
            finished_at=datetime.now().isoformat(),
            stage=None
        )
        # Mark current stage as errored
        if progress.stage == "collecting":
            progress.update(collecting_error=str(e))
        elif progress.stage == "migrating":
            progress.update(migrating_error=str(e))
