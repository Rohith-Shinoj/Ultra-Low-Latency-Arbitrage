import asyncio
import json
import urllib.request
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import ITCH_ADD_ORDER_FMT, MCAST_IP, PORT_NASDAQ_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

def load_equity_contract():
    cfg_path = os.path.join(os.path.dirname(__file__), 'active_contracts.json')
    seed = None
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                eq = json.load(f).get('equity', {})
                underlying = eq.get('underlying', 'SPY')
                nasdaq_strike = str(eq.get('nasdaq_strike', '771.00'))
                nasdaq_expiry = str(eq.get('nasdaq_expiry', 'Sep 22'))
                strike = float(eq.get('strike', 771.0))
                sym = eq.get('sym', f"{underlying}_C{int(strike)}")
                if 'bid' in eq and 'ask' in eq and eq['bid'] > 0:
                    seed = {'c_Bid': str(eq['bid']), 'c_Ask': str(eq['ask'])}
                return underlying, nasdaq_strike, nasdaq_expiry, sym, seed
        except Exception:
            pass
    return 'SPY', '771.00', 'Sep 22', 'SPY_C771', None

def fetch_nasdaq_options(underlying):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
    }
    assetclass = 'etf' if underlying in ['SPY', 'QQQ'] else 'stocks'
    url = f'https://api.nasdaq.com/api/quote/{underlying}/option-chain?assetclass={assetclass}'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

async def run_nasdaq():
    underlying, target_strike, target_expiry, target_sym, seed_contract = load_equity_contract()
    print(f"Starting Nasdaq Options Market Gateway ({underlying} {target_strike} {target_expiry} [{target_sym}])")
    seq = 1
    last_contract = seed_contract
    loop = asyncio.get_running_loop()
    last_target = (target_strike, target_expiry)

    while True:
        try:
            curr_underlying, curr_strike, curr_expiry, curr_sym, curr_seed = load_equity_contract()
            if (curr_strike, curr_expiry) != last_target:
                print(f"Nasdaq Gateway switching contract: {last_target} -> ({curr_strike}, {curr_expiry})")
                underlying = curr_underlying
                target_strike = curr_strike
                target_expiry = curr_expiry
                target_sym = curr_sym
                last_target = (curr_strike, curr_expiry)
                last_contract = curr_seed

            sym_padded = target_sym.encode('utf-8')[:8].ljust(8, b'\x00')

            try:
                d = await loop.run_in_executor(None, fetch_nasdaq_options, underlying)
                rows = ((d.get('data') or {}).get('table') or {}).get('rows') or []
                target = [r for r in rows if r.get('strike') == target_strike and r.get('expiryDate') == target_expiry]
                if target:
                    last_contract = target[0]
            except Exception as e:
                print(f"Nasdaq fetch notice: {e}")

            if last_contract and 'c_Bid' in last_contract and 'c_Ask' in last_contract:
                try:
                    bid_str = last_contract['c_Bid']
                    ask_str = last_contract['c_Ask']
                    if bid_str != '--' and ask_str != '--':
                        ts = time.time_ns()
                        bid = float(bid_str)
                        ask = float(ask_str)
                        qty = 100

                        if bid > 0:
                            px = int(bid * 10000)
                            payload_bid = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 2, 0, ts, seq, b'B', qty, sym_padded, px)
                            sock.sendto(payload_bid, (MCAST_IP, PORT_NASDAQ_OPT))
                            seq += 1

                        if ask > 0:
                            px = int(ask * 10000)
                            payload_ask = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 2, 0, ts, seq, b'S', qty, sym_padded, px)
                            sock.sendto(payload_ask, (MCAST_IP, PORT_NASDAQ_OPT))
                            seq += 1
                except Exception as e:
                    print(f"Nasdaq send notice: {e}")

            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"Nasdaq loop notice: {e}")
            await asyncio.sleep(2.0)

if __name__ == '__main__':
    asyncio.run(run_nasdaq())

