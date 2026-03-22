"""
Currency rate fetching for BIO import pipeline.
Combines Halyk Bank RUB/KZT rate and BIO API EUR/USD rates.
Stores results in rates_data module (no file I/O).
"""

import logging
import requests

log = logging.getLogger(__name__)

# BIO API credentials
BIO_BASE_URL = "http://api.bioshop.ru:8030"
BIO_AUTH_CREDENTIALS = {
    "login": "dilyara@pospro.kz",
    "password": "qo8qe7ti"
}


def fetch_rub_rate():
    """
    Fetches RUB/KZT sell rate from Halyk Bank API.
    Returns rate with +1% markup.
    """
    url = "https://back.halykbank.kz/common/currency-history"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://halykbank.kz/exchange-rates"
    }

    response = requests.get(url, headers=headers, timeout=60)
    response.raise_for_status()

    data = response.json()

    if not data.get("result") or not data.get("data"):
        raise ValueError("Неверный формат ответа от Halyk Bank API.")

    currency_history = data["data"].get("currencyHistory", [])
    if not currency_history:
        raise ValueError("Не найдены данные о курсах валют.")

    # Handle both list and dict formats
    if isinstance(currency_history, list):
        if len(currency_history) == 0:
            raise ValueError("Список currency_history пуст.")
        latest_data = currency_history[0]
    elif isinstance(currency_history, dict):
        if '0' in currency_history:
            latest_data = currency_history['0']
        else:
            keys = list(currency_history.keys())
            if keys:
                sorted_keys = sorted(keys, key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
                latest_data = currency_history[sorted_keys[0]]
            else:
                raise ValueError("Словарь currency_history пуст.")
    else:
        raise ValueError(f"Неожиданный тип currency_history: {type(currency_history)}")

    # Try legalPersons (old format), then cards (new format)
    currency_source = latest_data.get("legalPersons") or latest_data.get("cards") or {}

    rub_data = currency_source.get("RUB/KZT")
    if not rub_data:
        raise ValueError("Не найден курс RUB в данных API.")

    sell_rate = rub_data.get("sell")
    if sell_rate is None:
        raise ValueError("Не найден курс продажи RUB.")

    # Add 1% markup
    rate_value = round(sell_rate + (sell_rate * 0.01), 2)
    return rate_value


def fetch_bio_rates():
    """
    Fetches EUR/USD rates from BIO API (rates relative to RUB).
    Returns dict like {'EUR': 110.09, 'USD': 97.97}
    """
    headers = {"content-type": "application/json; charset=utf-8"}

    response = requests.post(
        f"{BIO_BASE_URL}/auth",
        headers=headers,
        json=BIO_AUTH_CREDENTIALS,
        timeout=60
    )
    response.raise_for_status()

    data = response.json()

    if "rates" not in data:
        raise ValueError("Курсы валют не найдены в ответе BIO API")

    rates_array = data["rates"]
    bio_rates = {}

    # Priority: look for "УЕ EUR ВН" and "УЕ USD ВН" first
    for rate_item in rates_array:
        currency = rate_item.get("currency", "")
        rate = rate_item.get("rate")
        frequency = rate_item.get("frequency", 1)

        if rate is not None:
            final_rate = rate * frequency
            rate_value = round(final_rate + (final_rate * 0.01), 2)

            if currency == "УЕ EUR ВН":
                bio_rates["EUR"] = rate_value
            elif currency == "УЕ USD ВН":
                bio_rates["USD"] = rate_value

    # Fallback to plain EUR/USD if special rates not found
    if "EUR" not in bio_rates or "USD" not in bio_rates:
        for rate_item in rates_array:
            currency = rate_item.get("currency", "").upper()
            rate = rate_item.get("rate")
            frequency = rate_item.get("frequency", 1)

            if rate is not None:
                final_rate = rate * frequency
                rate_value = round(final_rate + (final_rate * 0.01), 2)

                if currency == "EUR" and "EUR" not in bio_rates:
                    bio_rates["EUR"] = rate_value
                elif currency == "USD" and "USD" not in bio_rates:
                    bio_rates["USD"] = rate_value

    # Defaults if still missing
    if "EUR" not in bio_rates:
        bio_rates["EUR"] = 109.0
        log.warning("EUR rate not found in BIO API, using default 109.0")
    if "USD" not in bio_rates:
        bio_rates["USD"] = 93.0
        log.warning("USD rate not found in BIO API, using default 93.0")

    return bio_rates


def update_all_rates(rates_data_module):
    """
    Fetches all rates and updates the rates_data module in memory.
    """
    # Fetch RUB/KZT
    try:
        rub_rate = fetch_rub_rate()
        rates_data_module.exchange_rates["RUB"] = rub_rate
        log.info(f"RUB/KZT rate updated: {rub_rate}")
    except Exception as e:
        log.warning(f"Failed to fetch RUB rate: {e}. Using existing: {rates_data_module.exchange_rates.get('RUB')}")

    # Fetch BIO EUR/USD rates
    try:
        bio_rates = fetch_bio_rates()
        rates_data_module.bio_rates = bio_rates
        log.info(f"BIO rates updated: {bio_rates}")
    except Exception as e:
        log.warning(f"Failed to fetch BIO rates: {e}. Using existing: {rates_data_module.bio_rates}")
