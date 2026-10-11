# Crypto Address Lookup Bot

An async Telegram bot built with Python and `python-telegram-bot` using long polling.

Features:
- Reads `TELEGRAM_BOT_TOKEN` from `.env` via `python-dotenv`.
- Resets all Telegram bot commands on startup and leaves exactly `/lookup`.
- Accepts one address reply after `/lookup`.
- Detects Bitcoin, Ethereum/EVM, Solana, Tron, XRP, Litecoin, Dogecoin, Bitcoin Cash, Cardano, and TON addresses.
- Shows native totals, current balance, tx count, and USD value.
- Adds USDT/USDC summaries when history exists.
- Ignores unrelated messages.

Setup locally:
1. Copy `.env.example` to `.env` and insert your Telegram bot token.
2. Install dependencies:
   `python -m pip install -r requirements.txt`
3. Run:
   `python main.py`
   or
   `./run.sh`

Deploy to Railway:
1. Push this repository to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Add the environment variable:
   `TELEGRAM_BOT_TOKEN=your_bot_token_here`
4. Railway will build from `Dockerfile` and start with `python main.py`.

Notes:
- `.env` is ignored in `.gitignore`.
- No token is hardcoded or logged.
- API calls are asynchronous and use rate-limit-friendly behavior.
