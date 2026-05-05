from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests

OUNCE_TO_GRAM = 31.103431
TE_LOGIN = os.getenv("TE_API_KEY", "guest:guest")


def as_records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        return data.to_dict("records")
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def number_from_record(record: dict[str, Any]) -> float | None:
    for key in ("Last", "last", "Close", "close", "Price", "price", "Value", "value"):
        value = record.get(key)
        if value is None:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def valid_gold(value: float) -> bool:
    return 1_000 <= value <= 10_000


def valid_usd_irr(value: float) -> bool:
    return 10_000 <= value <= 2_000_000


def tradingeconomics_symbol(symbols: str | list[str]) -> float:
    import tradingeconomics as te

    te.login(TE_LOGIN)
    data = te.getMarketsBySymbol(symbols=symbols)
    for record in as_records(data):
        value = number_from_record(record)
        if value is not None:
            return value
    raise ValueError(f"No numeric market value found for {symbols!r}")


def get_gold_ounce() -> float:
    try:
        value = tradingeconomics_symbol(["gold", "gac:com", "xauusd:cur"])
        if valid_gold(value):
            return value
    except Exception:
        pass

    response = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/GC=F",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    value = float(result["meta"]["regularMarketPrice"])
    if not valid_gold(value):
        raise ValueError(f"Invalid fallback gold price: {value}")
    return value


def get_usd_irr() -> float:
    try:
        value = tradingeconomics_symbol(["usdirr:cur", "usd/irr:cur", "usd"])
        if valid_usd_irr(value):
            return value
    except Exception:
        pass

    response = requests.get("https://open.er-api.com/v6/latest/USD", timeout=30)
    response.raise_for_status()
    data = response.json()
    value = float(data["rates"]["IRR"])
    if not valid_usd_irr(value):
        raise ValueError(f"Invalid fallback USD/IRR price: {value}")
    return value


def fmt(value: float) -> str:
    return f"{round(value):,}"


def build_message() -> str:
    ounce = get_gold_ounce()
    usd = get_usd_irr()

    gold_999 = ounce * usd * OUNCE_TO_GRAM
    gold_750 = (750 / 999) * ounce * usd * OUNCE_TO_GRAM
    seke = (8.133 * ounce * usd * 0.9 / (0.9999 * OUNCE_TO_GRAM)) + 50_000

    return (
        f"Ounce: {fmt(ounce)}\n"
        f"USD: {fmt(usd)}\n\n"
        f"طلای 24 عیار:\n{fmt(gold_999)} تومان\n\n"
        f"قیمت ذاتی طلای 18 عیار:\n{fmt(gold_750)} تومان\n\n"
        f"قیمت ذاتی سکه:\n{fmt(seke)} تومان\n\n"
        f"Time: {datetime.now():%Y-%m-%d %H:%M}"
    )


def send_message(text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/sendMessage",
        json={
            "chat_id": os.environ["CHAT_ID"],
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data)


def main() -> None:
    try:
        message = build_message()
    except Exception as exc:
        message = f"Error fetching gold prices:\n{exc}\n\nTime: {datetime.now():%Y-%m-%d %H:%M}"
    send_message(message)


if __name__ == "__main__":
    main()
