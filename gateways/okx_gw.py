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

def fetch_okx_option():
    req = urllib.request.Request(
        'https://www.okx.com/api/v5/market/ticker?instId=BTC-USD-260923-80000-C',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())['data'][0]

def fetch_btc_index():
    req = urllib.request.Request(
        'https://www.okx.com/api/v5/market/index-tickers?instId=BTC-USD',
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return float(json.loads(r.read().decode())['data'][0]['idxPx'])

async def run_okx():
    print("Starting OKX Live BTC Options Gateway (BTC-USD-260923-80000-C)")
    seq = 1
    loop = asyncio.get_running_loop()
    while True:
        try:
            tick = await loop.run_in_executor(None, fetch_okx_option)
            idx = await loop.run_in_executor(None, fetch_btc_index)
            ts = time.time_ns()

            if 'bidPx' in tick and 'askPx' in tick:
                bid_btc = float(tick['bidPx'])
                ask_btc = float(tick['askPx'])

                if bid_btc > 0:
                    bid_usd = bid_btc * idx
                    bid_px = int(bid_usd * 10000)
                    bid_sz = int(float(tick['bidSz']) * 100) if 'bidSz' in tick else 0
                    payload_bid = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1002, seq, bid_px, bid_sz)
                    sock.sendto(payload_bid, (MCAST_IP, PORT_OKX_OPT))
                    seq += 1

                if ask_btc > 0:
                    ask_usd = ask_btc * idx
                    ask_px = int(ask_usd * 10000)
                    ask_sz = int(float(tick['askSz']) * 100) if 'askSz' in tick else 0
                    payload_ask = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'1', 1002, seq, ask_px, ask_sz)
                    sock.sendto(payload_ask, (MCAST_IP, PORT_OKX_OPT))
                    seq += 1

            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"OKX BTC Option Gateway polling notice: {e}")
            await asyncio.sleep(2.0)

if __name__ == '__main__':
    asyncio.run(run_okx())
