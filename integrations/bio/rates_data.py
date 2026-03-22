"""
Runtime storage for exchange rates.
Updated in memory during import, no file I/O needed.
"""

exchange_rates = {'RUB': 6.3}  # Default RUB/KZT, updated at runtime
bio_rates = {'EUR': 109.0, 'USD': 93.0}  # Default BIO EUR/USD->RUB, updated at runtime
