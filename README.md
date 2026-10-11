# Crypto Address Lookup Bot

A Telegram bot built with Python and `python-telegram-bot` using async long polling. It listens for `/lookup`, asks for an address, detects the chain, and returns native-coin totals plus optional USDT/USDC summaries when history is present.

## Requirements

- Python 3.11+
- Telegram bot token in `.env`
- Internet access for public blockchain APIs

## Setup

1. Copy `.env.example` to `.env` and add your Telegram bot token:

   cp .env.example .env

2. Update the token value in `.env`:

   TELEGRAM_BOT_TOKEN=your_actual_token_here

3. Install dependencies:

   python -m pip install -r requirements.txt

4. Run the bot:

   python main.py

   or:

   ./run.sh

## Notes

- The bot deletes all existing Telegram bot commands on startup and sets exactly one command: `/lookup`.
- It ignores all non-command messages until `/lookup` is issued.
- It loads the token with `python-dotenv` from `.env` and never hardcodes secrets.
- The project intentionally avoids any secret or token commit by adding `.env` to `.gitignore`.
- For public chain data, the code uses free APIs such as Blockchair, Blockscout, Solscan, TronGrid, Koios, and CoinGecko.

## Testing

Run the included unit tests:

pytest -q
