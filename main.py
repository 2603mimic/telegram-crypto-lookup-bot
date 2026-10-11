import asyncio
import json
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeAllChatAdministrators, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, BotCommandScopeDefault, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

load_dotenv(dotenv_path='.env')

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TOKEN:
    raise RuntimeError('TELEGRAM_BOT_TOKEN not found. Set it in your .env file.')

CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 60
LOOKUP_STATE_KEY = 'awaiting_address'

CHAIN_IDS = {
    'bitcoin': {'coin_id': 'bitcoin', 'decimals': 8, 'display': 'Bitcoin'},
    'litecoin': {'coin_id': 'litecoin', 'decimals': 8, 'display': 'Litecoin'},
    'dogecoin': {'coin_id': 'dogecoin', 'decimals': 8, 'display': 'Dogecoin'},
    'bitcoin_cash': {'coin_id': 'bitcoin-cash', 'decimals': 8, 'display': 'Bitcoin Cash'},
    'ethereum': {'coin_id': 'ethereum', 'decimals': 18, 'display': 'Ethereum'},
    'bnb': {'coin_id': 'binancecoin', 'decimals': 18, 'display': 'BNB Chain'},
    'polygon': {'coin_id': 'matic-network', 'decimals': 18, 'display': 'Polygon'},
    'arbitrum': {'coin_id': 'arbitrum', 'decimals': 18, 'display': 'Arbitrum'},
    'optimism': {'coin_id': 'optimism', 'decimals': 18, 'display': 'Optimism'},
    'base': {'coin_id': 'base', 'decimals': 18, 'display': 'Base'},
    'avalanche': {'coin_id': 'avalanche-2', 'decimals': 18, 'display': 'Avalanche'},
    'solana': {'coin_id': 'solana', 'decimals': 9, 'display': 'Solana'},
    'tron': {'coin_id': 'tron', 'decimals': 6, 'display': 'Tron'},
    'xrp': {'coin_id': 'ripple', 'decimals': 6, 'display': 'XRP'},
    'cardano': {'coin_id': 'cardano', 'decimals': 6, 'display': 'Cardano'},
    'ton': {'coin_id': 'the-open-network', 'decimals': 9, 'display': 'TON'},
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


def format_amount(value: Decimal, decimals: int = 0) -> Decimal:
    if decimals:
        return value / (Decimal(10) ** Decimal(decimals))
    return value


def to_decimal(value: Any, default: Decimal = Decimal('0')) -> Decimal:
    if value is None or value == '':
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def coin_gecko_id_for_chain(chain: str) -> str:
    return CHAIN_IDS.get(chain, {}).get('coin_id', 'bitcoin')


def choose_supported_chain(address: str) -> Optional[str]:
    if not address or not address.strip():
        return None
    value = address.strip()
    low = value.lower()

    if low.startswith('bc1') or (len(value) in range(26, 36) and re.fullmatch(r'[13][A-Za-z0-9]{24,34}', value)):
        return 'bitcoin'
    if low.startswith('ltc1') or low.startswith(('l', 'm')) and len(value) in range(26, 36):
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


def is_supported_address(value: str) -> bool:
    return choose_supported_chain(value) is not None


async def async_get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: float = 20.0, headers: Optional[Dict[str, str]] = None) -> Any:
    async with httpx.AsyncClient(timeout=timeout, headers=headers or {}) as client:
        response = await client.get(url, params=params)
        if response.status_code >= 400:
            raise ValueError(f'HTTP {response.status_code}: {response.text[:150]}')
        return response.json()


async def get_coin_price(chain: str) -> Decimal:
    coin_id = coin_gecko_id_for_chain(chain)
    url = 'https://api.coingecko.com/api/v3/simple/price'
    data = await async_get_json(url, params={'ids': coin_id, 'vs_currencies': 'usd'}, timeout=25.0)
    if isinstance(data, dict):
        price = data.get(coin_id, {}).get('usd')
        if price is not None:
            return Decimal(str(price))
    raise ValueError(f'Price for {coin_id} unavailable')


async def fetch_native_data_for_evm(chain: str, address: str) -> Dict[str, Any]:
    base_url = EVM_CHAIN_BASE_URLS.get(chain)
    if not base_url:
        return {'chain': chain, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False}

    try:
        balance_url = f'{base_url}/api?module=account&action=balance&address={address}'
        balance_payload = await async_get_json(balance_url)
        balance = to_decimal(balance_payload.get('result', 0) if isinstance(balance_payload, dict) else 0)
        value = balance / (Decimal(10) ** Decimal(CHAIN_IDS[chain]['decimals']))

        tx_url = f'{base_url}/api?module=account&action=txlist&address={address}&page=1&offset=2000'
        tx_payload = await async_get_json(tx_url)
        txs = tx_payload.get('result', []) if isinstance(tx_payload, dict) else []
        if not isinstance(txs, list):
            txs = []

        received = Decimal('0')
        sent = Decimal('0')
        for tx in txs:
            value_raw = to_decimal(tx.get('value', 0))
            from_addr = (tx.get('from') or '').lower()
            to_addr = (tx.get('to') or '').lower()
            if from_addr == address.lower():
                sent += value_raw
            if to_addr == address.lower():
                received += value_raw

        activity = bool(received or sent or value or txs)
        return {
            'chain': chain,
            'received': received / (Decimal(10) ** Decimal(CHAIN_IDS[chain]['decimals'])),
            'sent': sent / (Decimal(10) ** Decimal(CHAIN_IDS[chain]['decimals'])),
            'balance': value,
            'tx_count': len(txs),
            'activity': activity,
            'approx': len(txs) >= 2000,
        }
    except Exception:
        return {'chain': chain, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False}


async def fetch_bitcoin_like_data(chain: str, address: str) -> Dict[str, Any]:
    slug_map = {
        'bitcoin': 'bitcoin',
        'litecoin': 'litecoin',
        'dogecoin': 'dogecoin',
        'bitcoin_cash': 'bitcoin-cash',
    }
    blockchair_chain = {
        'bitcoin': 'bitcoin',
        'litecoin': 'litecoin',
        'dogecoin': 'dogecoin',
        'bitcoin_cash': 'bitcoin-cash',
    }
    base_url = f'https://api.blockchair.com/{blockchair_chain[chain]}/dashboards/address/{address}'
    try:
        payload = await async_get_json(base_url, timeout=25.0)
        data = payload.get('data', {}) if isinstance(payload, dict) else {}
        wallet = data.get(address) or data.get('address') or data
        if isinstance(wallet, dict):
            received = to_decimal(wallet.get('received'))
            sent = to_decimal(wallet.get('sent'))
            balance = to_decimal(wallet.get('balance'))
            tx_count = int(wallet.get('transactions', 0) or 0)
            coin_price = await get_coin_price(chain)
            return {
                'chain': chain,
                'received': received / (Decimal(10) ** Decimal(CHAIN_IDS[chain]['decimals'])),
                'sent': sent / (Decimal(10) ** Decimal(CHAIN_IDS[chain]['decimals'])),
                'balance': balance / (Decimal(10) ** Decimal(CHAIN_IDS[chain]['decimals'])),
                'tx_count': tx_count,
                'activity': bool(received or sent or balance or tx_count),
                'price': coin_price,
                'approx': False,
            }
    except Exception:
        pass

    return {'chain': chain, 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False, 'price': Decimal('0'), 'approx': False}


async def fetch_solana_data(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json(f'https://api.solscan.io/account?address={address}', timeout=25.0)
        if isinstance(payload, dict):
            balance = to_decimal(payload.get('balance', payload.get('solana_balance', 0)))
            tx_count = int(payload.get('tx_count', payload.get('txCount', payload.get('transactions', 0)) or 0))
            received = to_decimal(payload.get('received', 0))
            sent = to_decimal(payload.get('sent', 0))
            price = await get_coin_price('solana')
            return {
                'chain': 'solana',
                'received': received / Decimal(10) ** Decimal(9),
                'sent': sent / Decimal(10) ** Decimal(9),
                'balance': balance / Decimal(10) ** Decimal(9),
                'tx_count': tx_count,
                'activity': bool(received or sent or balance or tx_count),
                'price': price,
                'approx': False,
            }
    except Exception:
        pass
    return {'chain': 'solana', 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False, 'price': Decimal('0'), 'approx': False}


async def fetch_tron_data(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json(f'https://api.trongrid.io/v1/accounts/{address}', timeout=25.0)
        account = (payload.get('data') or [None])[0] if isinstance(payload, dict) else None
        if isinstance(account, dict):
            balance = to_decimal(account.get('balance', 0)) / Decimal(10) ** Decimal(6)
            tx_count = int(account.get('txCount', account.get('transactions_count', 0)) or 0)
            price = await get_coin_price('tron')
            return {
                'chain': 'tron',
                'received': Decimal('0'),
                'sent': Decimal('0'),
                'balance': balance,
                'tx_count': tx_count,
                'activity': bool(balance or tx_count),
                'price': price,
                'approx': False,
            }
    except Exception:
        pass
    return {'chain': 'tron', 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False, 'price': Decimal('0'), 'approx': False}


async def fetch_xrp_data(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json(f'https://data.ripple.com/v2/accounts/{address}/transactions?limit=200', timeout=25.0)
        txs = payload.get('transactions', []) if isinstance(payload, dict) else []
        received = Decimal('0')
        sent = Decimal('0')
        for tx in txs:
            values = tx.get('outcome', {}).get('delivered_amount')
            if isinstance(values, dict):
                amount = to_decimal(values.get('value', 0))
                if tx.get('type') in {'Payment'}:
                    if tx.get('account') == address:
                        sent += amount
                    if tx.get('destination') == address:
                        received += amount
        account_payload = await async_get_json(f'https://data.ripple.com/v2/accounts/{address}', timeout=25.0)
        balance = to_decimal((account_payload.get('account_data') or {}).get('Balance', 0)) / Decimal(10) ** Decimal(6)
        price = await get_coin_price('xrp')
        return {
            'chain': 'xrp',
            'received': received,
            'sent': sent,
            'balance': balance,
            'tx_count': len(txs),
            'activity': bool(received or sent or balance or txs),
            'price': price,
            'approx': len(txs) >= 200,
        }
    except Exception:
        pass
    return {'chain': 'xrp', 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False, 'price': Decimal('0'), 'approx': False}


async def fetch_cardano_data(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json('https://api.koios.rest/api/v1/address_info', params={'_address': address}, timeout=25.0)
        item = (payload or [{}])[0]
        if isinstance(item, dict):
            balance = to_decimal(item.get('balance', 0)) / Decimal(10) ** Decimal(6)
            received = to_decimal(item.get('total_received_sum', 0)) / Decimal(10) ** Decimal(6)
            sent = to_decimal(item.get('total_sent_sum', 0)) / Decimal(10) ** Decimal(6)
            tx_count = int(item.get('tx_count', item.get('transactions', 0)) or 0)
            price = await get_coin_price('cardano')
            return {
                'chain': 'cardano',
                'received': received,
                'sent': sent,
                'balance': balance,
                'tx_count': tx_count,
                'activity': bool(received or sent or balance or tx_count),
                'price': price,
                'approx': False,
            }
    except Exception:
        pass
    return {'chain': 'cardano', 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False, 'price': Decimal('0'), 'approx': False}


async def fetch_ton_data(address: str) -> Dict[str, Any]:
    try:
        payload = await async_get_json('https://toncenter.com/api/v2/getAddressInformation', params={'address': address}, timeout=25.0)
        result = payload.get('result', {}) if isinstance(payload, dict) else {}
        balance_nanotons = to_decimal(result.get('balance', 0))
        price = await get_coin_price('ton')
        return {
            'chain': 'ton',
            'received': Decimal('0'),
            'sent': Decimal('0'),
            'balance': balance_nanotons / Decimal(10) ** Decimal(9),
            'tx_count': int(result.get('tx_count', result.get('transactions_count', 0)) or 0),
            'activity': bool(balance_nanotons or result.get('tx_count')),
            'price': price,
            'approx': False,
        }
    except Exception:
        pass
    return {'chain': 'ton', 'received': Decimal('0'), 'sent': Decimal('0'), 'balance': Decimal('0'), 'tx_count': 0, 'activity': False, 'price': Decimal('0'), 'approx': False}


async def fetch_token_data(chain: str, address: str, token_symbol: str, token_contract: Optional[str], decimals: int) -> Dict[str, Any]:
    if not token_contract:
        return {'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0'), 'has_activity': False}

    if chain in EVM_CHAIN_NAMES:
        base_url = EVM_CHAIN_BASE_URLS[chain]
        try:
            balance_url = f'{base_url}/api?module=account&action=tokenbalance&contractaddress={token_contract}&address={address}'
            balance_payload = await async_get_json(balance_url)
            balance = to_decimal(balance_payload.get('result', 0) if isinstance(balance_payload, dict) else 0) / Decimal(10) ** Decimal(decimals)

            tx_url = f'{base_url}/api?module=account&action=tokentx&contractaddress={token_contract}&address={address}&page=1&offset=2000'
            tx_payload = await async_get_json(tx_url)
            txs = tx_payload.get('result', []) if isinstance(tx_payload, dict) else []
            if not isinstance(txs, list):
                txs = []
            received = Decimal('0')
            sent = Decimal('0')
            for tx in txs:
                value = to_decimal(tx.get('value', 0)) / Decimal(10) ** Decimal(decimals)
                if (tx.get('from') or '').lower() == address.lower():
                    sent += value
                if (tx.get('to') or '').lower() == address.lower():
                    received += value
            return {
                'received_usd': received,
                'sent_usd': sent,
                'balance_usd': balance,
                'has_activity': bool(received or sent or balance),
                'approx': len(txs) >= 2000,
            }
        except Exception:
            return {'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0'), 'has_activity': False, 'approx': False}

    if chain == 'solana':
        try:
            payload = await async_get_json(f'https://public-api.solscan.io/account/tokens?address={address}', timeout=25.0)
            if isinstance(payload, list):
                for item in payload:
                    if str(item.get('tokenAddress') or '').casefold() == str(token_contract).casefold():
                        balance = to_decimal(item.get('amount', 0)) / Decimal(10) ** Decimal(decimals)
                        received = to_decimal(item.get('received', 0)) / Decimal(10) ** Decimal(decimals)
                        sent = to_decimal(item.get('sent', 0)) / Decimal(10) ** Decimal(decimals)
                        return {'received_usd': received, 'sent_usd': sent, 'balance_usd': balance, 'has_activity': bool(received or sent or balance)}
        except Exception:
            pass
        return {'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0'), 'has_activity': False}

    if chain == 'tron':
        try:
            payload = await async_get_json(f'https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=200', timeout=25.0)
            txs = payload.get('data', []) if isinstance(payload, dict) else []
            received = Decimal('0')
            sent = Decimal('0')
            balance = Decimal('0')
            for tx in txs:
                token_info = tx.get('tokenInfo') or {}
                if str(token_info.get('address') or '').casefold() == str(token_contract).casefold():
                    value = to_decimal(tx.get('value', 0)) / Decimal(10) ** Decimal(decimals)
                    if (tx.get('from') or '').casefold() == address.casefold():
                        sent += value
                    if (tx.get('to') or '').casefold() == address.casefold():
                        received += value
            token_payload = await async_get_json(f'https://api.trongrid.io/v1/accounts/{address}', timeout=25.0)
            data = token_payload.get('data', []) if isinstance(token_payload, dict) else []
            for item in data:
                for token in item.get('trc20token_balances', []):
                    if str(token.get('token_name') or '').casefold() in {'usdt', 'usdc'}:
                        if str(token.get('token_id') or '').casefold() == str(token_contract).casefold() or token.get('token_address') == token_contract:
                            balance = to_decimal(token.get('balance', 0)) / Decimal(10) ** Decimal(decimals)
            return {'received_usd': received, 'sent_usd': sent, 'balance_usd': balance, 'has_activity': bool(received or sent or balance)}
        except Exception:
            pass
        return {'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0'), 'has_activity': False}

    return {'received_usd': Decimal('0'), 'sent_usd': Decimal('0'), 'balance_usd': Decimal('0'), 'has_activity': False}


async def lookup_address_data(address: str) -> Dict[str, Any]:
    chain = choose_supported_chain(address)
    if chain is None:
        raise ValueError('Unsupported address')

    if chain == 'ethereum':
        tasks = [fetch_native_data_for_evm(chain_name, address) for chain_name in EVM_CHAIN_NAMES]
        results = await asyncio.gather(*tasks)
        active = [r for r in results if r.get('activity')]
        native_output = []
        for r in active:
            chain_name = r['chain']
            label = CHAIN_IDS[chain_name]['display']
            native_output.append({
                'name': label,
                'received': r['received'],
                'sent': r['sent'],
                'balance': r['balance'],
                'tx_count': r['tx_count'],
                'price': await get_coin_price(chain_name),
                'approx': r.get('approx', False),
                'token_data': {}
            })
        return {'chain': 'ethereum', 'native_results': native_output, 'address': address}

    if chain in {'bitcoin', 'litecoin', 'dogecoin', 'bitcoin_cash'}:
        data = await fetch_bitcoin_like_data(chain, address)
        return {'chain': chain, 'native_results': [{
            'name': CHAIN_IDS[chain]['display'],
            'received': data['received'],
            'sent': data['sent'],
            'balance': data['balance'],
            'tx_count': data['tx_count'],
            'price': data['price'],
            'approx': data.get('approx', False),
            'token_data': {}
        }], 'address': address}

    if chain == 'solana':
        data = await fetch_solana_data(address)
        return {'chain': chain, 'native_results': [{
            'name': CHAIN_IDS['solana']['display'],
            'received': data['received'],
            'sent': data['sent'],
            'balance': data['balance'],
            'tx_count': data['tx_count'],
            'price': data['price'],
            'approx': data.get('approx', False),
            'token_data': {}
        }], 'address': address}

    if chain == 'tron':
        data = await fetch_tron_data(address)
        return {'chain': chain, 'native_results': [{
            'name': CHAIN_IDS['tron']['display'],
            'received': data['received'],
            'sent': data['sent'],
            'balance': data['balance'],
            'tx_count': data['tx_count'],
            'price': data['price'],
            'approx': data.get('approx', False),
            'token_data': {}
        }], 'address': address}

    if chain == 'xrp':
        data = await fetch_xrp_data(address)
        return {'chain': chain, 'native_results': [{
            'name': CHAIN_IDS['xrp']['display'],
            'received': data['received'],
            'sent': data['sent'],
            'balance': data['balance'],
            'tx_count': data['tx_count'],
            'price': data['price'],
            'approx': data.get('approx', False),
            'token_data': {}
        }], 'address': address}

    if chain == 'cardano':
        data = await fetch_cardano_data(address)
        return {'chain': chain, 'native_results': [{
            'name': CHAIN_IDS['cardano']['display'],
            'received': data['received'],
            'sent': data['sent'],
            'balance': data['balance'],
            'tx_count': data['tx_count'],
            'price': data['price'],
            'approx': data.get('approx', False),
            'token_data': {}
        }], 'address': address}

    if chain == 'ton':
        data = await fetch_ton_data(address)
        return {'chain': chain, 'native_results': [{
            'name': CHAIN_IDS['ton']['display'],
            'received': data['received'],
            'sent': data['sent'],
            'balance': data['balance'],
            'tx_count': data['tx_count'],
            'price': data['price'],
            'approx': data.get('approx', False),
            'token_data': {}
        }], 'address': address}

    raise ValueError('Unsupported address')


async def format_token_lines_for_chain(chain: str, address: str) -> List[str]:
    lines: List[str] = []
    contracts = TOKEN_CONTRACTS.get(chain, {})
    if not contracts:
        return lines

    for ticker in ['usdt', 'usdc']:
        contract, decimals = contracts.get(ticker, (None, 6))
        if not contract:
            continue
        result = await fetch_token_data(chain, address, ticker.upper(), contract, decimals)
        if result.get('has_activity'):
            usd_received = result['received_usd']
            usd_sent = result['sent_usd']
            usd_balance = result['balance_usd']
            lines.append(f'{ticker.upper()}: received ${usd_received:,.2f}, sent ${usd_sent:,.2f}, balance ${usd_balance:,.2f}')
    return lines


def humanized_value(value: Decimal) -> str:
    return f'{value:,.8f}'.rstrip('0').rstrip('.') if value < Decimal('1') else f'{value:,.8f}'.rstrip('0').rstrip('.')


async def build_report(address: str) -> str:
    data = await lookup_address_data(address)
    sections: List[str] = []
    native_results = data.get('native_results', [])

    if not native_results:
        return 'No activity found for this address.'

    for native in native_results:
        chain_name = native['name']
        usd_value = native['balance'] * native['price']
        token_lines = await format_token_lines_for_chain(native['name'].lower().replace(' ', '_').replace('-', '_').replace(' chain', ''), address)
        if native['name'].lower().replace(' ', '_').replace('-', '_').replace(' chain', '') == 'bnb':
            chain_key = 'bnb'
        elif native['name'].lower() == 'bitcoin cash':
            chain_key = 'bitcoin_cash'
        else:
            chain_key = native['name'].lower().replace(' ', '_').replace('-', '_').replace(' chain', '')

        if chain_key not in CHAIN_IDS:
            chain_key = choose_supported_chain(address)

        if chain_key == 'ethereum' and native['name'] == 'Ethereum':
            chain_key = 'ethereum'
        token_lines = await format_token_lines_for_chain(chain_key, address)

        lines = [
            f'{chain_name}',
            f'Address: {address[:8]}...{address[-6:]}',
            f'Total received: {humanized_value(native["received"])} {chain_name.split()[0] if len(chain_name.split()) == 1 else ""}'.strip(),
            f'Total sent: {humanized_value(native["sent"])} {chain_name.split()[0] if len(chain_name.split()) == 1 else ""}'.strip(),
            f'Current balance: {humanized_value(native["balance"])} {chain_name.split()[0] if len(chain_name.split()) == 1 else ""}'.strip(),
            f'Tx count: {native["tx_count"]}',
            f'USD value: ${usd_value:,.2f}',
        ]
        if native.get('approx'):
            lines.append('Approximate totals (API cap reached).')
        if token_lines:
            lines.extend(token_lines)
        sections.append('\n'.join(lines))

    return '\n\n'.join(sections)


async def handle_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    if update.message.text and update.message.text.startswith('/') and update.message.text != '/lookup':
        return
    context.chat_data[LOOKUP_STATE_KEY] = True
    await update.message.reply_text('Paste the address')


async def handle_address_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
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
    await application.bot.set_my_commands([
        BotCommand('lookup', 'Look up a crypto address'),
    ])


def main() -> None:
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler('lookup', handle_lookup))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_address_reply))
    application.post_init = startup_actions
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
