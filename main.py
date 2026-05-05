from __future__ import annotations

import os
import re
from datetime import datetime
from html.parser import HTMLParser

import requests

KITCO_GOLD_URL = "https://www.kitco.com/charts/gold"
TETHER_URL = os.getenv("TETHER_URL") or "https://www.tgju.org/profile/crypto-tether"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.lines.append(text)


def fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def html_lines(html: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(html)
    return parser.lines


def parse_number(value: str) -> float:
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    value = value.translate(digits)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    if not match:
        raise ValueError(f"Could not parse number from {value!r}")
    return float(match.group(0).replace(",", ""))


def get_ounce_price() -> float:
    html = fetch(KITCO_GOLD_URL)
    lines = html_lines(html)
    price_pattern = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^\d+(?:\.\d+)?$")

    for index, line in enumerate(lines):
        if line.casefold() == "bid":
            for candidate in lines[index + 1 : index + 10]:
                if price_pattern.match(candidate):
                    return parse_number(candidate)

    for pattern in (
        r'"bid"\s*:\s*"?(\d[\d,]*(?:\.\d+)?)"?',
        r"Bid[^0-9]{0,80}(\d[\d,]*(?:\.\d+)?)",
    ):
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return parse_number(match.group(1))

    raise ValueError("Could not find Kitco ounce price")


def get_tether_price() -> float:
    html = fetch(TETHER_URL)

    patterns = (
        r"<span[^>]*>\s*([۰-۹٠-٩\d,]+)\s*</span>\s*<span[^>]*>\s*تومان\s*</span>",
        r"([۰-۹٠-٩\d,]+)\s*</span>\s*<span[^>]*>\s*تومان\s*</span>",
    )

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return parse_number(match.group(1))

    lines = html_lines(html)
    for index, line in enumerate(lines):
        if line == "تومان" and index > 0:
            return parse_number(lines[index - 1])

    raise ValueError("Could not find Tether price in Toman")


def fmt(value: float) -> str:
    return f"{round(value):,}"


def build_message() -> str:
    ounce = get_ounce_price()
    tether = get_tether_price()

    gold_999 = (tether * ounce) / 31.1034
    gold_750 = ((tether * ounce) / 31.107) * (750 / 999.9)
    seke = (((tether * ounce) * 8.133 * 90) / (99.99 * 31.1034)) + 5000
    nim_seke = (((tether * ounce) * 4.665 * 90) / (99.99 * 31.1034)) + 5000
    rob_seke = (((tether * ounce) * 2.03225 * 90) / (99.99 * 31.1034)) + 5000

    return (
        "تمام قیمتهای زیر به تومان است.\n\n"
        f"Ounce: {fmt(ounce)} dollar\n"
        f"Tether: {fmt(tether)} تومان\n\n"
        f"قیمت ذاتی طلای 24 عیار:\n{fmt(gold_999)}\n\n"
        f"قیمت ذاتی طلای 18 عیار:\n{fmt(gold_750)}\n\n"
        f"قیمت ذاتی سکه:\n{fmt(seke)}\n\n"
        f"قیمت ذاتی نیم سکه:\n{fmt(nim_seke)}\n\n"
        f"قیمت ذاتی ربع سکه:\n{fmt(rob_seke)}\n\n"
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
        message = f"Error fetching price data:\n{exc}\n\nTime: {datetime.now():%Y-%m-%d %H:%M}"
    send_message(message)


if __name__ == "__main__":
    main()
