# Crypto Address Lookup Bot

Async Telegram bot for looking up crypto addresses with long polling.

Features:
- Reads `TELEGRAM_BOT_TOKEN` from `.env` via `python-dotenv`.
- Resets all Telegram bot commands on startup and leaves exactly `/lookup`.
- Accepts one address reply after `/lookup`.
- Detects Bitcoin, Ethereum/EVM, Solana, Tron, XRP, Litecoin, Dogecoin, Bitcoin Cash, Cardano, and TON addresses.
- Shows native totals, current balance, tx count, and USD value.
- Adds USDT/USDC summaries when history exists.
- Ignores unrelated messages.

Setup:
1. Copy `.env.example` to `.env` and paste your bot token.
2. Install dependencies:
   `python -m pip install -r requirements.txt`
3. Run:
   `python main.py`
   or
   `./run.sh`

Notes:
- `.env` is ignored in `.gitignore`.
- No token is hardcoded or logged.
- API calls are asynchronous and use rate-limit-friendly retry behavior.
