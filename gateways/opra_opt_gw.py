import asyncio
import json
import urllib.request
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import ITCH_ADD_ORDER_FMT, MCAST_IP, PORT_OPRA_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

_session = None
_crumb = None

def get_session_and_crumb():
    global _session, _crumb
    if _session is not None and _crumb is not None:
        return _session, _crumb
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')]
    try:
        opener.open('https://fc.yahoo.com', timeout=4)
    except Exception:
        pass
    with opener.open('https://query2.finance.yahoo.com/v1/test/getcrumb', timeout=4) as r:
        _crumb = r.read().decode()
    _session = opener
    return _session, _crumb

def load_equity_contract():
    cfg_path = os.path.join(os.path.dirname(__file__), 'active_contracts.json')
    seed = None
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                eq = json.load(f).get('equity', {})
                underlying = eq.get('underlying', 'SPY')
                cboe_opt = eq.get('cboe_option', 'SPY260922C00771000')
                strike = float(eq.get('strike', 771.0))
                sym = eq.get('sym', f"{underlying}_C{int(strike)}")
                if 'bid' in eq and 'ask' in eq and eq['bid'] > 0:
                    seed = {
                        'bid': float(eq['bid']),
                        'ask': float(eq['ask']),
                        'volume': float(eq.get('volume', 12000)),
                        'impliedVolatility': float(eq.get('iv', 0.18))
                    }
                return underlying, cboe_opt, sym, seed
        except Exception:
            pass
    return 'SPY', 'SPY260922C00771000', 'SPY_C771', None

def fetch_opra_options(underlying):
    global _crumb, _session
    try:
        session, crumb = get_session_and_crumb()
        url = f'https://query2.finance.yahoo.com/v7/finance/options/{underlying}?crumb={crumb}'
        with session.open(url, timeout=8) as r2:
            return json.loads(r2.read().decode())
    except Exception as e:
        _crumb = None
        _session = None
        raise e

async def run_opra():
    underlying, target_symbol, target_sym, seed_contract = load_equity_contract()
    print(f"Starting OPRA Consolidated Options Gateway ({underlying} - {target_symbol} [{target_sym}])")
    seq = 1
    last_contract = seed_contract
    loop = asyncio.get_running_loop()
    last_fetch_time = 0.0
    fetch_interval = 30.0  # Polite query cadence to prevent HTTP 401
    last_target_symbol = target_symbol

    while True:
        try:
            curr_underlying, curr_target_symbol, curr_sym, curr_seed = load_equity_contract()
            if curr_target_symbol != last_target_symbol:
                print(f"OPRA Gateway switching contract: {last_target_symbol} -> {curr_target_symbol}")
                underlying = curr_underlying
                target_symbol = curr_target_symbol
                target_sym = curr_sym
                last_target_symbol = curr_target_symbol
                last_contract = curr_seed
                last_fetch_time = 0.0

            sym_padded = target_sym.encode('utf-8')[:8].ljust(8, b'\x00')
            now = time.time()

            # Poll Yahoo Finance consolidated options gently
            if now - last_fetch_time >= fetch_interval:
                last_fetch_time = now
                try:
                    d = await loop.run_in_executor(None, fetch_opra_options, underlying)
                    res = d.get('optionChain', {}).get('result', [{}])[0]
                    calls = res.get('options', [{}])[0].get('calls', [])
                    target = [c for c in calls if c.get('contractSymbol') == target_symbol]
                    if target:
                        last_contract = target[0]
                        try:
                            with open(os.path.join(os.path.dirname(__file__), 'opra_greeks.json'), 'w') as qf:
                                json.dump({
                                    'iv': float(last_contract.get('impliedVolatility', 0.18)),
                                    'volume': float(last_contract.get('volume', 12000)),
                                    'open_interest': float(last_contract.get('openInterest', 5000))
                                }, qf)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"OPRA fetch notice: {e}")

            # Stream active in-memory quote every second
            if last_contract and 'bid' in last_contract and 'ask' in last_contract:
                try:
                    ts = time.time_ns()
                    bid = float(last_contract['bid'])
                    ask = float(last_contract['ask'])
                    vol = last_contract.get('volume')
                    contract_sz = int(vol) * 100 if (vol is not None and vol > 0) else 100
                    bid_sz = min(contract_sz, 10000)
                    ask_sz = min(contract_sz, 10000)

                    if bid > 0:
                        px = int(bid * 10000)
                        payload_bid = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 3, 0, ts, seq, b'B', bid_sz, sym_padded, px)
                        sock.sendto(payload_bid, (MCAST_IP, PORT_OPRA_OPT))
                        seq += 1

                    if ask > 0:
                        px = int(ask * 10000)
                        payload_ask = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 3, 0, ts, seq, b'S', ask_sz, sym_padded, px)
                        sock.sendto(payload_ask, (MCAST_IP, PORT_OPRA_OPT))
                        seq += 1
                except Exception as e:
                    print(f"OPRA send notice: {e}")

            await asyncio.sleep(1.0)
        except Exception as e:
            print(f"OPRA loop notice: {e}")
            await asyncio.sleep(2.0)

if __name__ == '__main__':
    asyncio.run(run_opra())

