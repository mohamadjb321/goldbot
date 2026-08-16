import os
import unittest
from unittest.mock import Mock, patch

import main
import requests


PAYLOAD = {
    "gold": [
        {
            "symbol": "IR_GOLD_18K",
            "price": 19_079_400,
            "unit": "تومان",
            "date": "1405/05/24",
            "time": "19:59",
        },
        {
            "symbol": "IR_COIN_HALF",
            "price": 96_000_000,
            "unit": "تومان",
            "date": "1405/05/24",
            "time": "17:09",
        },
        {
            "symbol": "IR_COIN_EMAMI",
            "price": 189_000_000,
            "unit": "تومان",
            "date": "1405/05/25",
            "time": "10:15",
        },
    ]
}


class BrsApiTests(unittest.TestCase):
    def test_parses_required_market_symbols_without_unit_conversion(self):
        result = main.parse_brsapi_market_prices(PAYLOAD)

        self.assertEqual(result["gold_18k"].price, 19_079_400)
        self.assertEqual(result["coin_emami"].price, 189_000_000)
        self.assertEqual(result["coin_half"].price, 96_000_000)
        self.assertTrue(all(item.unit == "تومان" for item in result.values()))

    def test_rejects_missing_symbol(self):
        with self.assertRaisesRegex(ValueError, "IR_COIN_HALF"):
            main.parse_brsapi_market_prices(
                {"gold": [PAYLOAD["gold"][0], PAYLOAD["gold"][2]]}
            )

    def test_rejects_unexpected_unit(self):
        payload = {"gold": [dict(row) for row in PAYLOAD["gold"]]}
        payload["gold"][0]["unit"] = "ریال"

        with self.assertRaisesRegex(ValueError, "Unexpected BrsApi unit"):
            main.parse_brsapi_market_prices(payload)

    def test_fetches_all_prices_in_one_request(self):
        response = Mock()
        response.json.return_value = PAYLOAD
        response.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BRSAPI_API_KEY": "secret"}), patch(
            "main.requests.get", return_value=response
        ) as request:
            result = main.get_brsapi_market_prices()

        self.assertEqual(result["coin_emami"].price, 189_000_000)
        request.assert_called_once_with(
            main.BRSAPI_GOLD_URL,
            params={"key": "secret"},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
                "User-Agent": "curl/8.7.1",
                "Referer": "https://brsapi.ir/",
                "Cache-Control": "no-cache",
                "Host": "Api.BrsApi.ir",
            },
            timeout=(10, 45),
        )

    def test_retries_timeout_then_succeeds(self):
        response = Mock()
        response.json.return_value = PAYLOAD
        response.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BRSAPI_API_KEY": "secret"}), patch(
            "main.requests.get",
            side_effect=[requests.ReadTimeout("slow"), response],
        ) as request, patch("main.time.sleep") as sleep:
            result = main.get_brsapi_market_prices()

        self.assertEqual(result["gold_18k"].price, 19_079_400)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_uses_backoff_for_repeated_transient_failures(self):
        response = Mock()
        response.json.return_value = PAYLOAD
        response.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BRSAPI_API_KEY": "secret"}), patch(
            "main.requests.get",
            side_effect=[
                requests.ReadTimeout("slow"),
                requests.ConnectionError("temporary"),
                response,
            ],
        ), patch("main.time.sleep") as sleep:
            main.get_brsapi_market_prices()

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 15])

    def test_retries_retryable_http_status(self):
        failed_response = Mock(status_code=503)
        failure = requests.HTTPError("service unavailable", response=failed_response)
        success = Mock()
        success.json.return_value = PAYLOAD
        success.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BRSAPI_API_KEY": "secret"}), patch(
            "main.requests.get", side_effect=[failure, success]
        ) as request, patch("main.time.sleep") as sleep:
            main.get_brsapi_market_prices()

        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_does_not_retry_authentication_failure(self):
        failed_response = Mock(status_code=401)
        failure = requests.HTTPError("unauthorized", response=failed_response)

        with patch.dict(os.environ, {"BRSAPI_API_KEY": "secret"}), patch(
            "main.requests.get", side_effect=failure
        ) as request, patch("main.time.sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                main.get_brsapi_market_prices()

        request.assert_called_once()
        sleep.assert_not_called()

    def test_fails_after_four_timeouts_without_partial_prices(self):
        with patch.dict(os.environ, {"BRSAPI_API_KEY": "secret"}), patch(
            "main.requests.get", side_effect=requests.ReadTimeout("slow")
        ) as request, patch("main.time.sleep") as sleep:
            with self.assertRaises(requests.ReadTimeout):
                main.get_brsapi_market_prices()

        self.assertEqual(request.call_count, 4)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list], [5, 15, 30]
        )

    def test_bubble_amount_and_percent(self):
        amount, percent = main.bubble(120, 100)
        self.assertEqual(amount, 20)
        self.assertEqual(percent, 20)

    def test_api_key_is_redacted_from_errors(self):
        with patch.dict(os.environ, {"BRSAPI_API_KEY": "top-secret"}):
            message = main.safe_error_message(
                RuntimeError("failed https://example.test?key=top-secret")
            )

        self.assertNotIn("top-secret", message)
        self.assertIn("***", message)

    def test_report_contains_three_brsapi_market_prices(self):
        parsed = main.parse_brsapi_market_prices(PAYLOAD)
        with patch("main.get_ounce_price", return_value=4_375), patch(
            "main.get_tether_price", return_value=1_800_000
        ), patch("main.get_brsapi_market_prices", return_value=parsed):
            report = main.build_message()

        self.assertIn("طلای ۱۸ عیار", report)
        self.assertIn("بازار: 19,079,400 تومان", report)
        self.assertIn("سکه امامی", report)
        self.assertIn("بازار: 189,000,000 تومان", report)
        self.assertIn("نیم‌سکه", report)
        self.assertIn("ذاتی: 92,672,688 تومان", report)
        self.assertIn("بازار: 96,000,000 تومان", report)
        directional_bubbles = report.count("حباب مثبت") + report.count("حباب منفی")
        self.assertEqual(directional_bubbles, 3)
        self.assertIn("تتر: <b>1,800,000 ریال</b>", report)
        self.assertIn("<b>ارزش ذاتی و حباب طلا و سکه</b>", report)
        self.assertNotIn("Time:", report)
        self.assertIn("🕒 آخرین به‌روزرسانی: 1405/05/25 10:15", report)
        self.assertNotIn("نیم‌سکه: 1405/", report)

    def test_bubble_text_uses_directional_labels(self):
        self.assertIn("🟢", main.bubble_text(-100, -2.5))
        self.assertIn("حباب منفی", main.bubble_text(-100, -2.5))
        self.assertIn("🔴", main.bubble_text(100, 2.5))
        self.assertIn("حباب مثبت", main.bubble_text(100, 2.5))

    def test_telegram_uses_html_parse_mode(self):
        response = Mock()
        response.json.return_value = {"ok": True}
        response.raise_for_status.return_value = None

        with patch.dict(os.environ, {"BOT_TOKEN": "token", "CHAT_ID": "@Risktory"}), patch(
            "main.requests.post", return_value=response
        ) as request:
            main.send_message("<b>report</b>")

        self.assertEqual(request.call_args.kwargs["json"]["parse_mode"], "HTML")


if __name__ == "__main__":
    unittest.main()
