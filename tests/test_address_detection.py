import asyncio
import os
import re
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeDefault, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv(dotenv_path='.env')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError('TELEGRAM_BOT_TOKEN is not set. Add it to your .env file before starting the bot.')

LOOKUP_STATE_KEY = 'awaiting_address'
CACHE_TTL_SECONDS = 60
CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
PRICE_CACHE: Dict[str, Tuple[float, Decimal]] = {}

CHAIN_META = {
    'bitcoin': {'symbol': 'BTC', 'coin_id': 'bitcoin', 'decimals': 8, 'display': 'Bitcoin'},
    'litecoin': {'symbol': 'LTC', 'coin_id': 'litecoin', 'decimals': 8, 'display': 'Litecoin'},
    'dogecoin': {'symbol': 'DOGE', 'coin_id': 'dogecoin', 'decimals': 8, 'display': 'Dogecoin'},
    'bitcoin_cash': {'symbol': 'BCH', 'coin_id': 'bitcoin-cash', 'decimals': 8, 'display': 'Bitcoin Cash'},
    'ethereum': {'symbol': 'ETH', 'coin_id': 'ethereum', 'decimals': 18, 'display': 'Ethereum'},
    'bnb': {'symbol': 'BNB', 'coin_id': 'binancecoin', 'decimals': 18, 'display': 'BNB Chain'},
    'polygon': {'symbol': 'POL', 'coin_id': 'matic-network', 'decimals': 18, 'display': 'Polygon'},
    'arbitrum': {'symbol': 'ETH', 'coin_id': 'arbitrum', 'decimals': 18, 'display': 'Arbitrum'},
    'optimism': {'symbol': 'ETH', 'coin_id': 'optimism', 'decimals': 18, 'display': 'Optimism'},
    'base': {'symbol': 'ETH', 'coin_id': 'base', 'decimals': 18, 'display': 'Base'},
    'avalanche': {'symbol': 'AVAX', 'coin_id': 'avalanche-2', 'decimals': 18, 'display': 'Avalanche'},
    'solana': {'symbol': 'SOL', 'coin_id': 'solana', 'decimals': 9, 'display': 'Solana'},
    'tron': {'symbol': 'TRX', 'coin_id': 'tron', 'decimals': 6, 'display': 'Tron'},
    'xrp': {'symbol': 'XRP', 'coin_id': 'ripple', 'decimals': 6, 'display': 'XRP'},
    'cardano': {'symbol': 'ADA', 'coin_id': 'cardano', 'decimals': 6, 'display': 'Cardano'},
    'ton': {'symbol': 'TON', 'coin_id': 'the-open-network', 'decimals': 9, 'display': 'TON'},
}

EVM_CHAIN_NAMES = ['ethereum', 'bnb', 'polygon', 'arbitrum', 'optimism', 'base', 'avalanche']
EVM_CHAIN_BASE_URLS = {
    'ethereum': 'https://eth.blockscout.com',
    'bnb': 'https://bnb.blockscout.com',
    'polygon': 'https://polygon.blockscout.com',
    'arbitrum': 'https://arbitrum.blockscout.com',
    'optimism': 'https://optimism.blockscout.com',
    'base': 'https://base.blockscout.com',
    'avalanche': 'https://avalanche.blockscout.com',
}

TOKEN_CONTRACTS = {
    'ethereum': {'usdt': ('0xdAC17F958D2ee523a2206206994597C13D831ec7', 6), 'usdc': ('0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 6)},
    'bnb': {'usdt': ('0x55d398326f99059fF775485246999027B3197955', 18), 'usdc': ('0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d', 18)},
    'polygon': {'usdt': ('0xc2132D05D31c914a87C6611C10748AEb04B58e8F', 6), 'usdc': ('0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359', 6)},
    'arbitrum': {'usdt': ('0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9', 6), 'usdc': ('0xaf88d065e77c8cC2239327C5EDb3A432268e5831', 6)},
    'optimism': {'usdt': ('0x01bFF41798a0BcF287b996046Ca68b395DbC1071F', 6), 'usdc': ('0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85', 6)},
    'base': {'usdt': ('0xfde4C96c8593536E31F229EA8f37b2EA9dA4D66c', 6), 'usdc': ('0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', 6)},
    'avalanche': {'usdt': ('0x9702230a8e4f61eB487b6fDd96C5bB4A2e6001f3', 6), 'usdc': ('0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E', 6)},
    'solana': {'usdt': ('Es9vMFrzaCERsby2HcPUa5dsnEkA5Qn7cVWSk8fjS1bM', 6), 'usdc': ('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 6)},
    'tron': {'usdt': ('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t', 6), 'usdc': ('TPYmHEhy5n8TCEfYGqW2rP4j2bM2kC1PD7', 6)},
    'ton': {'usdt': (None, 9), 'usdc': (None, 9)},
}


def to_decimal(value: Any, default: Decimal = Decimal('0')) -> Decimal:
    if value in (None, '', 'null', 'None'):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def humanize_coin(value: Decimal) -> str:
    s = format(value, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    if s == '-0':
        return '0'
    return s or '0'


def short_address(address: str) -> str:
    if len(address) <= 12:
        return address
    return f'{address[:8]}...{address[-6:]}'


def cache_get(key: str) -> Optional[Any]:
    item = CACHE.get(key)
    if not item:
        return None
    expires_at, payload = item
    if time.time() > expires_at:
        CACHE.pop(key, None)
        return None
    return payload


def cache_set(key: str, payload: Any) -> None:
    CACHE[key] = (time.time() + CACHE_TTL_SECONDS, payload)


def choose_supported_chain(address: str) -> Optional[str]:
    value = (address or '').strip()
    if not value:
        return None
    low = value.lower()

    if low.startswith('bc1') or re.fullmatch(r'[13][A-Za-z0-9]{25,34}', value):
        return 'bitcoin'
    if low.startswith('ltc1') or (low.startswith('l') or low.startswith('m')) and len(value) in range(26, 36):
        return 'litecoin'
    if value.startswith('D') and len(value) in range(33, 60):
        return 'dogecoin'
    if 'bitcoincash:' in low or re.fullmatch(r'[qp][A-Za-z0-9]{20,80}', value):
        return 'bitcoin_cash'
    if value.startswith('T') and len(value) in range(33, 60):
        return 'tron'
    if value.startswith('r') and len(value) in range(25, 40):
        return 'xrp'
    if low.startswith('addr1'):
        return 'cardano'
    if low.startswith(('eq', 'uq')):
        return 'ton'
    if low.startswith('0x') and len(value) in range(42, 66):
        return 'ethereum'
    if re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}', value):
        return 'solana'
    return None


def is_supported_address(address: str) -> bool:
    return choose_supported_chain(address) is not None


async def async_get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Any:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, params=params)
        if response.status_code >= 400:
            raise ValueError(f'HTTP {response.status_code}: {response.text[:200]}')
        return response.json()


async def get_coin_price(chain_key: str) -> Decimal:
    chain_key = chain_key.lower()
    cache_key = f'price:{chain_key}'
    cached = PRICE_CACHE.get(cache_key)
    if cached and time.time() < cached[0]:
        return cached[1]

    coin_id = CHAIN_META.get(chain_key, CHAIN_META['bitcoin'])['coin_id']
    payload = await async_get_json(
        'https://api.coingecko.com/api/v3/simple/price',
        params={'ids': coin_id, 'vs_currencies': 'usd'},
        timeout=25.0,
    )
    price = payload.get(coin_id, {}).get('usd')
    if price is None:
        raise ValueError(f'No USD markets for {coin_id}')
    value = Decimal(str(price))
    PRICE_CACHE[cache_key] = (time.time() + 60, value)
    return value


async def fetch_evm_native(chain: str, address: str) -> Dict[str, Any]:
    base = EVM_CHAIN_BASE_URLS.get(chain)
    if not base:
        return {'chain': chain, 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}

    try:
        balance_task = async_get_json(f'{base}/api?module=account&action=balance&address={address}')
        tx_task = async_get_json(f'{base}/api?module=account&action=txlist&address={address}&page=1&offset=2000')
        balance_payload, tx_payload = await asyncio.gather(balance_task, tx_task)

        balance_raw = to_decimal((balance_payload or {}).get('result', 0))
        balance = balance_raw / (Decimal(10) ** Decimal(CHAIN_META[chain]['decimals']))

        txs = (tx_payload or {}).get('result', []) if isinstance(tx_payload, dict) else []
        if not isinstance(txs, list):
            txs = []

        received = Decimal('0')
        sent = Decimal('0')
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            value_raw = to_decimal(tx.get('value', 0))
            value = value_raw / (Decimal(10) ** Decimal(CHAIN_META[chain]['decimals']))
            from_addr = (tx.get('from') or '').lower()
            to_addr = (tx.get('to') or '').lower()
            if from_addr == address.lower():
                sent += value
            if to_addr == address.lower():
                received += value

        activity = bool(balance > 0 or received > 0 or sent > 0 or len(txs) > 0)
        return {
            'chain': chain,
            'activity': activity,
            'received': received,
            'sent': sent,
            'balance': balance,
            'tx_count': len(txs),
            'approx': len(txs) >= 2000,
        }
    except Exception:
        return {'chain': chain, 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_bitcoin_like(chain: str, address: str) -> Dict[str, Any]:
    blockchair_chain = {
        'bitcoin': 'bitcoin',
        'litecoin': 'litecoin',
        'dogecoin': 'dogecoin',
        'bitcoin_cash': 'bitcoin-cash',
    }
    try:
        payload = await async_get_json(f'https://api.blockchair.com/{blockchair_chain[chain]}/dashboards/address/{address}', timeout=25.0)
        data = (payload or {}).get('data', {})
        wallet = data.get(address) or next(iter(data.values()), {}) if isinstance(data, dict) else {}
        if not isinstance(wallet, dict):
            return {'chain': chain, 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}

        received = to_decimal(wallet.get('received')) / (Decimal(10) ** Decimal(CHAIN_META[chain]['decimals']))
        sent = to_decimal(wallet.get('sent')) / (Decimal(10) ** Decimal(CHAIN_META[chain]['decimals']))
        balance = to_decimal(wallet.get('balance')) / (Decimal(10) ** Decimal(CHAIN_META[chain]['decimals']))
        tx_count = int(wallet.get('transactions', 0) or 0)
        return {
            'chain': chain,
            'activity': bool(received > 0 or sent > 0 or balance > 0 or tx_count > 0),
            'received': received,
            'sent': sent,
            'balance': balance,
            'tx_count': tx_count,
            'approx': False,
        }
    except Exception:
        return {'chain': chain, 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_solana(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json(f'https://api.solscan.io/account?address={address}', timeout=25.0)
        balance = to_decimal((payload or {}).get('balance', (payload or {}).get('solana_balance', 0))) / Decimal(10) ** 9
        received = to_decimal((payload or {}).get('received', 0)) / Decimal(10) ** 9
        sent = to_decimal((payload or {}).get('sent', 0)) / Decimal(10) ** 9
        tx_count = int((payload or {}).get('tx_count', (payload or {}).get('txCount', 0)) or 0)
        return {
            'chain': 'solana',
            'activity': bool(balance > 0 or received > 0 or sent > 0 or tx_count > 0),
            'received': received,
            'sent': sent,
            'balance': balance,
            'tx_count': tx_count,
            'approx': False,
        }
    except Exception:
        return {'chain': 'solana', 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_tron(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json(f'https://api.trongrid.io/v1/accounts/{address}', timeout=25.0)
        account = (payload or {}).get('data', [{}])[0] if isinstance(payload, dict) else {}
        balance = to_decimal(account.get('balance', 0)) / Decimal(10) ** 6
        tx_count = int(account.get('txCount', account.get('transactions_count', 0)) or 0)
        return {
            'chain': 'tron',
            'activity': bool(balance > 0 or tx_count > 0),
            'received': Decimal('0'),
            'sent': Decimal('0'),
            'balance': balance,
            'tx_count': tx_count,
            'approx': False,
        }
    except Exception:
        return {'chain': 'tron', 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_xrp(address: str) -> Dict[str, Any]:
    try:
        tx_payload = await async_get_json(f'https://data.ripple.com/v2/accounts/{address}/transactions?limit=200', timeout=25.0)
        txs = (tx_payload or {}).get('transactions', []) if isinstance(tx_payload, dict) else []
        received = Decimal('0')
        sent = Decimal('0')
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            if tx.get('type') != 'Payment':
                continue
            outcome = tx.get('outcome', {})
            delivered = outcome.get('delivered_amount')
            if isinstance(delivered, dict):
                amount = to_decimal(delivered.get('value'))
                if tx.get('account') == address:
                    sent += amount
                if tx.get('destination') == address:
                    received += amount
        account_payload = await async_get_json(f'https://data.ripple.com/v2/accounts/{address}', timeout=25.0)
        balance = to_decimal(((account_payload or {}).get('account_data') or {}).get('Balance', 0)) / Decimal(10) ** 6
        return {
            'chain': 'xrp',
            'activity': bool(received > 0 or sent > 0 or balance > 0 or len(txs) > 0),
            'received': received,
            'sent': sent,
            'balance': balance,
            'tx_count': len(txs),
            'approx': len(txs) >= 200,
        }
    except Exception:
        return {'chain': 'xrp', 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_cardano(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json('https://api.koios.rest/api/v1/address_info', params={'_address': address}, timeout=25.0)
        item = (payload or [{}])[0] if isinstance(payload, list) and payload else {}
        if not isinstance(item, dict):
            return {'chain': 'cardano', 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}
        balance = to_decimal(item.get('balance', 0)) / Decimal(10) ** 6
        received = to_decimal(item.get('total_received_sum', 0)) / Decimal(10) ** 6
        sent = to_decimal(item.get('total_sent_sum', 0)) / Decimal(10) ** 6
        tx_count = int(item.get('tx_count', item.get('transactions', 0)) or 0)
        return {
            'chain': 'cardano',
            'activity': bool(balance > 0 or received > 0 or sent > 0 or tx_count > 0),
            'received': received,
            'sent': sent,
            'balance': balance,
            'tx_count': tx_count,
            'approx': False,
        }
    except Exception:
        return {'chain': 'cardano', 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_ton(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json('https://toncenter.com/api/v2/getAddressInformation', params={'address': address}, timeout=25.0)
        result = (payload or {}).get('result', {}) if isinstance(payload, dict) else {}
        balance = to_decimal(result.get('balance', 0)) / Decimal(10) ** 9
        tx_count = int(result.get('tx_count', result.get('transactions_count', 0)) or 0)
        return {
            'chain': 'ton',
            'activity': bool(balance > 0 or tx_count > 0),
            'received': Decimal('0'),
            'sent': Decimal('0'),
            'balance': balance,
            'tx_count': tx_count,
            'approx': False,
        }
    except Exception:
        return {'chain': 'ton', 'activity': False, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'approx': False}


async def fetch_token_info(chain: str, address: str, token_symbol: str, contract: Optional[str], decimals: int) -> Dict[str, Any]:
    if not contract:
        return {'has_activity': False, 'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0')}

    try:
        if chain in EVM_CHAIN_NAMES:
            base = EVM_CHAIN_BASE_URLS[chain]
            balance_task = async_get_json(f'{base}/api?module=account&action=tokenbalance&contractaddress={contract}&address={address}')
            tx_task = async_get_json(f'{base}/api?module=account&action=tokentx&contractaddress={contract}&address={address}&page=1&offset=2000')
            balance_payload, tx_payload = await asyncio.gather(balance_task, tx_task)
            balance = to_decimal((balance_payload or {}).get('result', 0)) / (Decimal(10) ** Decimal(decimals))
            txs = (tx_payload or {}).get('result', []) if isinstance(tx_payload, dict) else []
            if not isinstance(txs, list):
                txs = []
            received = Decimal('0')
            sent = Decimal('0')
            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                value = to_decimal(tx.get('value', 0)) / (Decimal(10) ** Decimal(decimals))
                if (tx.get('from') or '').lower() == address.lower():
                    sent += value
                if (tx.get('to') or '').lower() == address.lower():
                    received += value
            return {'has_activity': bool(balance > 0 or received > 0 or sent > 0 or len(txs) > 0), 'received_usd': received, 'sent_usd': sent, 'balance_usd': balance}

        if chain == 'solana':
            payload = await async_get_json(f'https://public-api.solscan.io/account/tokens?address={address}', timeout=25.0)
            if isinstance(payload, list):
                for item in payload:
                    if str(item.get('tokenAddress') or '').casefold() == str(contract).casefold():
                        balance = to_decimal(item.get('amount', 0)) / (Decimal(10) ** Decimal(decimals))
                        received = to_decimal(item.get('received', 0)) / (Decimal(10) ** Decimal(decimals))
                        sent = to_decimal(item.get('sent', 0)) / (Decimal(10) ** Decimal(decimals))
                        return {'has_activity': bool(balance > 0 or received > 0 or sent > 0), 'received_usd': received, 'sent_usd': sent, 'balance_usd': balance}

        if chain == 'tron':
            payload = await async_get_json(f'https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=200', timeout=25.0)
            txs = (payload or {}).get('data', []) if isinstance(payload, dict) else []
            received = Decimal('0')
            sent = Decimal('0')
            balance = Decimal('0')
            for tx in txs:
                if not isinstance(tx, dict):
                    continue
                token_info = tx.get('tokenInfo', {})
                token_contract = str(token_info.get('address') or '')
                if token_contract.casefold() != str(contract).casefold():
                    continue
                value = to_decimal(tx.get('value', 0)) / (Decimal(10) ** Decimal(decimals))
                if (tx.get('from') or '').lower() == address.lower():
                    sent += value
                if (tx.get('to') or '').lower() == address.lower():
                    received += value
            return {'has_activity': bool(received > 0 or sent > 0 or balance > 0), 'received_usd': received, 'sent_usd': sent, 'balance_usd': balance}
    except Exception:
        pass

    return {'has_activity': False, 'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0')}


async def format_token_lines(chain: str, address: str) -> List[str]:
    lines: List[str] = []
    contracts = TOKEN_CONTRACTS.get(chain, {})
    if not contracts:
        return lines

    for symbol in ('usdt', 'usdc'):
        contract, decimals = contracts.get(symbol, (None, 6))
        if not contract:
            continue
        info = await fetch_token_info(chain, address, symbol.upper(), contract, decimals)
        if info.get('has_activity'):
            lines.append(
                f'{symbol.upper()}: received ${info["received_usd"]:,.2f}, '
                f'sent ${info["sent_usd"]:,.2f}, balance ${info["balance_usd"]:,.2f}'
            )
    return lines


async def lookup_address_data(address: str) -> Dict[str, Any]:
    chain = choose_supported_chain(address)
    if chain is None:
        raise ValueError('Unsupported address')

    if chain == 'ethereum':
        laters = await asyncio.gather(*(fetch_evm_native(name, address) for name in EVM_CHAIN_NAMES))
        active = [item for item in laters if item.get('activity')]
        return {'native_results': [{'name': CHAIN_META[item['chain']]['display'], 'chain_key': item['chain'], 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price(item['chain']), 'approx': item.get('approx', False)} for item in active]}

    if chain in {'bitcoin', 'litecoin', 'dogecoin', 'bitcoin_cash'}:
        item = await fetch_bitcoin_like(chain, address)
        return {'native_results': [{'name': CHAIN_META[chain]['display'], 'chain_key': chain, 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price(chain), 'approx': item.get('approx', False)}]}

    if chain == 'solana':
        item = await fetch_solana(address)
        return {'native_results': [{'name': CHAIN_META['solana']['display'], 'chain_key': 'solana', 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price('solana'), 'approx': item.get('approx', False)}]}

    if chain == 'tron':
        item = await fetch_tron(address)
        return {'native_results': [{'name': CHAIN_META['tron']['display'], 'chain_key': 'tron', 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price('tron'), 'approx': item.get('approx', False)}]}

    if chain == 'xrp':
        item = await fetch_xrp(address)
        return {'native_results': [{'name': CHAIN_META['xrp']['display'], 'chain_key': 'xrp', 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price('xrp'), 'approx': item.get('approx', False)}]}

    if chain == 'cardano':
        item = await fetch_cardano(address)
        return {'native_results': [{'name': CHAIN_META['cardano']['display'], 'chain_key': 'cardano', 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price('cardano'), 'approx': item.get('approx', False)}]}

    if chain == 'ton':
        item = await fetch_ton(address)
        return {'native_results': [{'name': CHAIN_META['ton']['display'], 'chain_key': 'ton', 'received': item['received'], 'sent': item['sent'], 'balance': item['balance'], 'tx_count': item['tx_count'], 'price': await get_coin_price('ton'), 'approx': item.get('approx', False)}]}

    raise ValueError('Unsupported chain')


async def build_report(address: str) -> str:
    data = await lookup_address_data(address)
    native_results = data.get('native_results', [])
    if not native_results:
        return 'No activity found for this address.'

    blocks: List[str] = []
    for native in native_results:
        chain_key = native['chain_key']
        symbol = CHAIN_META.get(chain_key, {}).get('symbol', 'COIN')
        usd_value = native['balance'] * native['price']
        token_lines = await format_token_lines(chain_key, address)
        lines = [
            f'{native["name"]}',
            f'Address: {short_address(address)}',
            f'Total received: {humanize_coin(native["received"])} {symbol}',
            f'Total sent: {humanize_coin(native["sent"])} {symbol}',
            f'Current balance: {humanize_coin(native["balance"])} {symbol}',
            f'Tx count: {native["tx_count"]}',
            f'USD value: ${usd_value:,.2f}',
        ]
        if native.get('approx'):
            lines.append('Approximate totals (API cap reached).')
        if token_lines:
            lines.extend(token_lines)
        blocks.append('\n'.join(lines))

    return '\n\n'.join(blocks)


async def handle_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    context.chat_data[LOOKUP_STATE_KEY] = True
    await update.message.reply_text('Paste the address')


async def handle_address_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    if update.message.text.startswith('/'):
        return
    if not context.chat_data.get(LOOKUP_STATE_KEY):
        return

    address = update.message.text.strip()
    if not is_supported_address(address):
        context.chat_data[LOOKUP_STATE_KEY] = False
        await update.message.reply_text("That doesn't look like a supported address. Send /lookup to try again.")
        return

    try:
        report = await build_report(address)
        await update.message.reply_text(report)
    except Exception:
        await update.message.reply_text('I hit a temporary API issue. Please try again in a moment.')
    finally:
        context.chat_data[LOOKUP_STATE_KEY] = False


async def startup_actions(application: Application) -> None:
    scopes = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ]
    for scope in scopes:
        await application.bot.delete_my_commands(scope=scope)
    await application.bot.set_my_commands([BotCommand('lookup', 'Look up a crypto address')])


def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler('lookup', handle_lookup))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address_reply))
    app.post_init = startup_actions
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
