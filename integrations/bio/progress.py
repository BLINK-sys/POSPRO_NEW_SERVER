"""
Thread-safe progress tracker for BIO import pipeline.
Singleton instance shared between collector, migrator, and SSE endpoint.
"""

import threading
from datetime import datetime


class ImportProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.status = "idle"  # idle | running | completed | error
            self.stage = None  # "collecting" | "migrating" | None
            self.started_at = None
            self.finished_at = None
            self.error = None

            # Stage 1: Collecting from BIO API
            self.collecting_total_categories = 0
            self.collecting_processed_categories = 0
            self.collecting_products_count = 0
            self.collecting_current_category = ""
            self.collecting_done = False
            self.collecting_error = None

            # Stage 2: Migrating to PosPro
            self.migrating_total = 0
            self.migrating_processed = 0
            self.migrating_created = 0
            self.migrating_updated = 0
            self.migrating_errors = []
            self.migrating_done = False
            self.migrating_error = None
            self.deactivated_products = []
            self.reactivated_products = []

    def update(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def append_deactivated(self, product_name):
        with self._lock:
            self.deactivated_products.append(product_name)

    def append_reactivated(self, product_name):
        with self._lock:
            self.reactivated_products.append(product_name)

    def append_migrating_error(self, error_msg):
        with self._lock:
            self.migrating_errors.append(error_msg)

    def increment_products_count(self):
        with self._lock:
            self.collecting_products_count += 1

    def increment_migrating(self, created=False, updated=False):
        with self._lock:
            self.migrating_processed += 1
            if created:
                self.migrating_created += 1
            if updated:
                self.migrating_updated += 1

    def to_dict(self):
        with self._lock:
            return {
                "status": self.status,
                "stage": self.stage,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
                "collecting": {
                    "total_categories": self.collecting_total_categories,
                    "processed_categories": self.collecting_processed_categories,
                    "products_count": self.collecting_products_count,
                    "current_category": self.collecting_current_category,
                    "done": self.collecting_done,
                    "error": self.collecting_error,
                },
                "migrating": {
                    "total": self.migrating_total,
                    "processed": self.migrating_processed,
                    "created": self.migrating_created,
                    "updated": self.migrating_updated,
                    "errors": self.migrating_errors[:50],  # Limit to 50 errors in response
                    "errors_total": len(self.migrating_errors),
                    "done": self.migrating_done,
                    "error": self.migrating_error,
                    "deactivated_products": self.deactivated_products,
                    "reactivated_products": self.reactivated_products,
                },
            }


# Singleton instance
progress = ImportProgress()
