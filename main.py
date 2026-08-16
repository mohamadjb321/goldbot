from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

import requests

KITCO_GOLD_URL = "https://www.kitco.com/charts/gold"
TETHER_URL = os.getenv("TETHER_URL", "")
NOBITEX_USDT_URL = "https://apiv2.nobitex.ir/v3/orderbook/USDTIRT"
BRSAPI_GOLD_URL = "https://Api.BrsApi.ir/Market/Gold_Currency.php"
BRSAPI_MAX_ATTEMPTS = 4
BRSAPI_TIMEOUT = (10, 45)
BRSAPI_RETRY_DELAYS = (5, 15, 30)
BRSAPI_RETRYABLE_STATUSES = {406, 408, 425, 429, 500, 502, 503, 504, 522}

MARKET_SYMBOLS = {
    "gold_18k": "IR_GOLD_18K",
    "coin_emami": "IR_COIN_EMAMI",
    "coin_half": "IR_COIN_HALF",
}


@dataclass(frozen=True)
class MarketPrice:
    price: float
    unit: str
    date: str
    time: str


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


def fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_brsapi_market_prices(payload: object) -> dict[str, MarketPrice]:
    if not isinstance(payload, dict) or not isinstance(payload.get("gold"), list):
        raise ValueError("Invalid BrsApi gold response")

    by_symbol: dict[str, dict[str, Any]] = {}
    for row in payload["gold"]:
        if isinstance(row, dict) and isinstance(row.get("symbol"), str):
            by_symbol[row["symbol"]] = row

    result: dict[str, MarketPrice] = {}
    for key, symbol in MARKET_SYMBOLS.items():
        row = by_symbol.get(symbol)
        if row is None:
            raise ValueError(f"Missing BrsApi symbol: {symbol}")

        unit = str(row.get("unit", "")).strip()
        if unit != "تومان":
            raise ValueError(f"Unexpected BrsApi unit for {symbol}: {unit or 'missing'}")

        price = parse_number(str(row.get("price", "")))
        if price <= 0:
            raise ValueError(f"Invalid BrsApi price for {symbol}")

        date = str(row.get("date", "")).strip()
        time = str(row.get("time", "")).strip()
        if not date or not time:
            raise ValueError(f"Missing BrsApi timestamp for {symbol}")

        result[key] = MarketPrice(price=price, unit=unit, date=date, time=time)

    return result


def get_brsapi_market_prices() -> dict[str, MarketPrice]:
    api_key = os.environ.get("BRSAPI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("BRSAPI_API_KEY is not set")

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        "User-Agent": "curl/8.7.1",
        "Referer": "https://brsapi.ir/",
        "Cache-Control": "no-cache",
        "Host": "Api.BrsApi.ir",
    }

    for attempt in range(1, BRSAPI_MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                BRSAPI_GOLD_URL,
                params={"key": api_key},
                headers=headers,
                timeout=BRSAPI_TIMEOUT,
            )
            response.raise_for_status()
            prices = parse_brsapi_market_prices(response.json())
            if attempt > 1:
                print(f"[BrsApi] request succeeded on attempt {attempt}", flush=True)
            return prices
        except Exception as exc:
            retryable = is_retryable_brsapi_error(exc)
            final_attempt = attempt == BRSAPI_MAX_ATTEMPTS
            print(
                f"[BrsApi] attempt {attempt}/{BRSAPI_MAX_ATTEMPTS} failed: "
                f"{safe_error_message(exc)}",
                flush=True,
            )
            if not retryable or final_attempt:
                raise

            delay = BRSAPI_RETRY_DELAYS[attempt - 1]
            print(f"[BrsApi] retrying in {delay} seconds", flush=True)
            time.sleep(delay)

    raise RuntimeError("BrsApi retry loop exited unexpectedly")


def is_retryable_brsapi_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        return status in BRSAPI_RETRYABLE_STATUSES or bool(status and status >= 500)
    # A successful HTTP response with incomplete or invalid JSON can be a
    # transient upstream response. Retry it, but never reuse partial prices.
    return isinstance(exc, ValueError)


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


def get_tether_from_webpage() -> float:
    if not TETHER_URL:
        raise ValueError("TETHER_URL is not set")

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
        if "تومان" in line and index > 0:
            return parse_number(lines[index - 1])

    raise ValueError("Could not find Tether price in webpage")


def get_tether_from_nobitex() -> float:
    data = fetch_json(NOBITEX_USDT_URL)

    for key in ("lastTradePrice", "lastUpdatePrice", "mark"):
        value = data.get(key)
        if value:
            return parse_number(str(value))

    bids = data.get("bids") or []
    asks = data.get("asks") or []

    if bids and asks:
        return (parse_number(str(bids[0][0])) + parse_number(str(asks[0][0]))) / 2
    if asks:
        return parse_number(str(asks[0][0]))
    if bids:
        return parse_number(str(bids[0][0]))

    raise ValueError("Could not find Tether price from Nobitex")


def get_tether_price() -> float:
    try:
        return get_tether_from_webpage()
    except Exception:
        return get_tether_from_nobitex()


def fmt(value: float) -> str:
    return f"{round(value):,}"


def bubble(market: float, intrinsic: float) -> tuple[float, float]:
    if intrinsic <= 0:
        raise ValueError("Intrinsic price must be positive")
    amount = market - intrinsic
    return amount, (amount / intrinsic) * 100


def signed_fmt(value: float) -> str:
    return f"{value:+,.0f}"


def signed_percent(value: float) -> str:
    return f"{value:+.1f}%"


def bubble_text(amount: float, percent: float) -> str:
    if amount > 0:
        icon, label = "🔴", "حباب مثبت"
    elif amount < 0:
        icon, label = "🟢", "حباب منفی"
    else:
        icon, label = "⚪️", "بدون حباب"
    return (
        f"• {icon} <b>{label}:</b> {fmt(abs(amount))} تومان "
        f"({abs(percent):.1f}٪)"
    )


def market_timestamp(prices: dict[str, MarketPrice]) -> str:
    latest = max(prices.values(), key=lambda item: (item.date, item.time))
    return f"{latest.date} {latest.time}"


def tehran_clock() -> str:
    return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%H:%M")


def tehran_time() -> str:
    return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M")


def build_message() -> str:
    ounce = get_ounce_price()
    tether = get_tether_price()
    market = get_brsapi_market_prices()

    gold_750 = ((tether * ounce) / 31.107) * (750 / 999.9)
    seke = (((tether * ounce) * 8.133 * 90) / (99.99 * 31.1034)) + 5000
    # Official half-coin gross weight is 4.0665 grams (0.900 fineness).
    nim_seke = (((tether * ounce) * 4.0665 * 90) / (99.99 * 31.1034)) + 5000

    # The existing intrinsic formulas use the Nobitex IRT payload as rial.
    # BrsApi explicitly returns these three market prices in toman, so convert
    # only the finished intrinsic outputs for display/comparison. The formulas
    # themselves remain unchanged.
    gold_750_toman = gold_750 / 10
    seke_toman = seke / 10
    nim_seke_toman = nim_seke / 10

    gold_bubble, gold_bubble_percent = bubble(
        market["gold_18k"].price, gold_750_toman
    )
    coin_bubble, coin_bubble_percent = bubble(
        market["coin_emami"].price, seke_toman
    )
    half_bubble, half_bubble_percent = bubble(
        market["coin_half"].price, nim_seke_toman
    )

    return (
        f"🟡 <b>ارزش ذاتی و حباب طلا و سکه</b>\n"
        f"🗓 تاریخ بازار: {market['gold_18k'].date} | ⏰ {tehran_clock()}\n\n"
        f"🌍 اونس جهانی: <b>{fmt(ounce)} دلار</b>\n"
        f"💵 تتر: <b>{fmt(tether)} ریال</b>\n\n"
        f"🥇 <b>طلای ۱۸ عیار</b>\n"
        f"• <b>بازار: {fmt(market['gold_18k'].price)} تومان</b>\n"
        f"• ذاتی: {fmt(gold_750_toman)} تومان\n"
        f"{bubble_text(gold_bubble, gold_bubble_percent)}\n\n"
        f"🪙 <b>سکه امامی</b>\n"
        f"• <b>بازار: {fmt(market['coin_emami'].price)} تومان</b>\n"
        f"• ذاتی: {fmt(seke_toman)} تومان\n"
        f"{bubble_text(coin_bubble, coin_bubble_percent)}\n\n"
        f"🌗 <b>نیم‌سکه</b>\n"
        f"• <b>بازار: {fmt(market['coin_half'].price)} تومان</b>\n"
        f"• ذاتی: {fmt(nim_seke_toman)} تومان\n"
        f"{bubble_text(half_bubble, half_bubble_percent)}\n\n"
        f"🕒 آخرین به‌روزرسانی: {market_timestamp(market)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Risktory</b> | @Risktory\n"
        f"روایت ریسک در بازارها"
    )


def safe_error_message(exc: Exception) -> str:
    text = str(exc)
    api_key = os.environ.get("BRSAPI_API_KEY", "").strip()
    if api_key:
        text = text.replace(api_key, "***")
    return text


def send_message(text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{os.environ['BOT_TOKEN']}/sendMessage",
        json={
            "chat_id": os.environ["CHAT_ID"],
            "text": text,
            "parse_mode": "HTML",
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
        # Do not publish operational failures to the public channel. Raising
        # also makes GitHub Actions fail visibly instead of reporting success.
        raise RuntimeError(
            f"Error fetching price data: {safe_error_message(exc)}"
        ) from exc
    send_message(message)


if __name__ == "__main__":
    main()
