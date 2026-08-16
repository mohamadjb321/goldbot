# goldbot

Telegram report for intrinsic and current market prices of 18K gold, Emami coin,
and half coin. Market prices are fetched once per run from BrsApi's
`Market/Gold_Currency.php` endpoint. The existing ounce, Tether, and intrinsic
price formulas remain unchanged.

Required GitHub Actions secrets:

- `BOT_TOKEN`
- `CHAT_ID`
- `BRSAPI_API_KEY`
