import asyncio
import json
import urllib.request
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import SBE_BOOK_UPDATE_FMT, MCAST_IP, PORT_OKX_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

def load_crypto_contract():
    cfg_path = os.path.join(os.path.dirname(__file__), 'active_contracts.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                c = json.load(f).get('crypto', {})
                return c.get('okx_inst_id', 'BTC-USD-260923-80000-C'), c.get('underlying', 'BTC')
        except Exception:
            pass
    return 'BTC-USD-260923-80000-C', 'BTC'

def fetch_okx_option(inst_id):
    req = urllib.request.Request(
        f'https://www.okx.com/api/v5/market/ticker?instId={inst_id}',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode()).get('data', [])
            return data[0] if data else None
    except Exception:
        return None

def fetch_crypto_index(underlying):
    req = urllib.request.Request(
        f'https://www.okx.com/api/v5/market/index-tickers?instId={underlying}-USD',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode()).get('data', [])
            return float(data[0]['idxPx']) if data else 1.0
    except Exception:
        return 1.0

async def run_okx():
    inst_id, underlying = load_crypto_contract()
    print(f"Starting OKX Live Options Gateway ({inst_id})")
    seq = 1
    loop = asyncio.get_running_loop()
    last_tick = None
    last_idx = 86500.0
    last_inst_id = inst_id

    while True:
        try:
            curr_inst_id, curr_underlying = load_crypto_contract()
            if curr_inst_id != last_inst_id:
                print(f"OKX Gateway switching contract: {last_inst_id} -> {curr_inst_id}")
                inst_id = curr_inst_id
                underlying = curr_underlying
                last_inst_id = curr_inst_id
                last_tick = None

            tick = await loop.run_in_executor(None, fetch_okx_option, inst_id)
            if tick and 'bidPx' in tick and 'askPx' in tick:
                last_tick = tick
                idx = await loop.run_in_executor(None, fetch_crypto_index, underlying)
                if idx > 1.0:
                    last_idx = idx

            active_tick = last_tick
            if active_tick and 'bidPx' in active_tick and 'askPx' in active_tick:
                ts = time.time_ns()
                bid_btc = float(active_tick['bidPx'])
                ask_btc = float(active_tick['askPx'])

                if bid_btc > 0:
                    bid_usd = bid_btc * last_idx
                    bid_px = int(bid_usd * 10000)
                    bid_sz = int(float(active_tick['bidSz']) * 100) if 'bidSz' in active_tick else 0
                    payload_bid = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1002, seq, bid_px, bid_sz)
                    sock.sendto(payload_bid, (MCAST_IP, PORT_OKX_OPT))
                    seq += 1

                if ask_btc > 0:
                    ask_usd = ask_btc * last_idx
                    ask_px = int(ask_usd * 10000)
                    ask_sz = int(float(active_tick['askSz']) * 100) if 'askSz' in active_tick else 0
                    payload_ask = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'1', 1002, seq, ask_px, ask_sz)
                    sock.sendto(payload_ask, (MCAST_IP, PORT_OKX_OPT))
                    seq += 1

            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"OKX BTC Option Gateway polling notice: {e}")
            await asyncio.sleep(2.0)

if __name__ == '__main__':
    asyncio.run(run_okx())

