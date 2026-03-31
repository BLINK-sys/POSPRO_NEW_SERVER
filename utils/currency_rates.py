import requests


def fetch_rub_rate_halyk() -> float:
    """
    Fetch RUB/KZT sell rate from Halyk Bank API (for business).
    Returns rate with +1% markup.
    """
    URL = "https://back.halykbank.kz/common/currency-history"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://halykbank.kz/exchange-rates"
    }

    response = requests.get(URL, headers=headers, timeout=15)
    response.raise_for_status()

    data = response.json()

    if not data.get("result") or not data.get("data"):
        raise ValueError("Неверный формат ответа от API Halyk Bank")

    currency_history = data["data"].get("currencyHistory", [])
    if not currency_history:
        raise ValueError("Не найдены данные о курсах валют")

    # Handle both list and dict formats
    if isinstance(currency_history, list):
        if not currency_history:
            raise ValueError("Список currency_history пуст")
        latest_data = currency_history[0]
    elif isinstance(currency_history, dict):
        if '0' in currency_history:
            latest_data = currency_history['0']
        else:
            keys = sorted(currency_history.keys(),
                          key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
            if not keys:
                raise ValueError("Словарь currency_history пуст")
            latest_data = currency_history[keys[0]]
    else:
        raise ValueError(f"Неожиданный тип currency_history: {type(currency_history)}")

    currency_source = latest_data.get("legalPersons") or latest_data.get("cards") or {}

    rub_data = currency_source.get("RUB/KZT")
    if not rub_data:
        raise ValueError("Не найден курс RUB в данных API")

    sell_rate = rub_data.get("sell")
    if sell_rate is None:
        raise ValueError("Не найден курс продажи RUB")

    # Add 1% markup (same logic as BioApiNewShop)
    rate_value = round(sell_rate + (sell_rate * 0.01), 2)

    return rate_value
