import asyncio
import json
import urllib.request
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import SBE_BOOK_UPDATE_FMT, MCAST_IP, PORT_BINANCE_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

def load_crypto_contract():
    cfg_path = os.path.join(os.path.dirname(__file__), 'active_contracts.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                c = json.load(f).get('crypto', {})
                return c.get('binance_symbol', 'BTC-260923-80000-C')
        except Exception:
            pass
    return 'BTC-260923-80000-C'

def fetch_binance_option(symbol):
    req = urllib.request.Request(
        f'https://eapi.binance.com/eapi/v1/ticker?symbol={symbol}',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            res = json.loads(r.read().decode())
            return res[0] if isinstance(res, list) and res else None
    except Exception:
        return None

async def run_binance():
    symbol = load_crypto_contract()
    print(f"Starting Binance Live Options Gateway ({symbol})")
    seq = 1
    loop = asyncio.get_running_loop()
    last_tick = None
    last_symbol = symbol

    while True:
        try:
            curr_symbol = load_crypto_contract()
            if curr_symbol != last_symbol:
                print(f"Binance Gateway switching contract: {last_symbol} -> {curr_symbol}")
                symbol = curr_symbol
                last_symbol = curr_symbol
                last_tick = None

            tick = await loop.run_in_executor(None, fetch_binance_option, symbol)
            if tick and 'bidPrice' in tick and 'askPrice' in tick:
                last_tick = tick

            active_tick = last_tick
            if active_tick and 'bidPrice' in active_tick and 'askPrice' in active_tick:
                ts = time.time_ns()
                bid = float(active_tick['bidPrice'])
                ask = float(active_tick['askPrice'])
                qty_raw = active_tick.get('lastQty')
                bid_sz = int(float(qty_raw) * 100) if qty_raw else 100

                if bid > 0:
                    px = int(bid * 10000)
                    payload_bid = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1003, seq, px, bid_sz)
                    sock.sendto(payload_bid, (MCAST_IP, PORT_BINANCE_OPT))
                    seq += 1

                if ask > 0:
                    px = int(ask * 10000)
                    payload_ask = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'1', 1003, seq, px, bid_sz)
                    sock.sendto(payload_ask, (MCAST_IP, PORT_BINANCE_OPT))
                    seq += 1

            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"Binance BTC Option Gateway polling notice: {e}")
            await asyncio.sleep(2.0)

if __name__ == '__main__':
    asyncio.run(run_binance())

