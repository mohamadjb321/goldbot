from __future__ import annotations

import os
import re
from datetime import datetime
from html.parser import HTMLParser

import requests

KITCO_GOLD_URL = "https://www.kitco.com/charts/gold"
BONBAST_URL = "https://www.bon-bast.com/"
OUNCE_TO_GRAM = 31.103431


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.lines.append(text)


def fetch(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.text


def parse_number(value: str) -> float:
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    match = re.search(r"\d[\d,]*(?:\.\d+)?", value.translate(digits))
    if not match:
        raise ValueError(f"Could not parse number from {value!r}")
    return float(match.group(0).replace(",", ""))


def html_lines(html: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(html)
    return parser.lines


def get_ounce_bid() -> float:
    html = fetch(KITCO_GOLD_URL)
    price_pattern = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^\d+(?:\.\d+)?$")

    for index, line in enumerate(html_lines(html)):
        if line.casefold() == "bid":
            for candidate in html_lines(html)[index + 1 : index + 10]:
                if price_pattern.match(candidate):
                    return parse_number(candidate)

    for pattern in (r'"bid"\s*:\s*"?(\d[\d,]*(?:\.\d+)?)"?', r"Bid[^0-9]{0,80}(\d[\d,]*(?:\.\d+)?)"):
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return parse_number(match.group(1))

    raise ValueError("Could not find Kitco ounce bid price")


def get_usd_price() -> float:
    html = fetch(BONBAST_URL)
    match = re.search(r'id=["\']usd1["\'][^>]*>\s*([^<]+)', html, re.IGNORECASE)
    if not match:
        match = re.search(r'["\']usd1["\']\s*:\s*["\']?([^,"\'}<\s]+)', html, re.IGNORECASE)
    if not match:
        raise ValueError("Could not find USD price with id='usd1'")
    return parse_number(match.group(1))


def fmt(value: float) -> str:
    return f"{round(value):,}"


def build_message() -> str:
    ounce = get_ounce_bid()
    usd = get_usd_price()

    gold_999 = ounce * usd * OUNCE_TO_GRAM
    gold_750 = (750 / 999) * ounce * usd * OUNCE_TO_GRAM
    seke = (8.133 * ounce * usd * 0.9 / (0.9999 * OUNCE_TO_GRAM)) + 50000

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
