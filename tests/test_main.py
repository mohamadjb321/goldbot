import os
import unittest
from unittest.mock import Mock, patch

import main


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
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
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
        self.assertIn("بازار: 96,000,000 تومان", report)
        self.assertEqual(report.count("حباب:"), 3)
        self.assertIn("تتر: 1,800,000 ریال", report)


if __name__ == "__main__":
    unittest.main()
