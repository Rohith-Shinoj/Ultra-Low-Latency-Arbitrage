import asyncio
import json
import urllib.request
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import ITCH_ADD_ORDER_FMT, MCAST_IP, PORT_CBOE_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

def load_equity_contract():
    cfg_path = os.path.join(os.path.dirname(__file__), 'active_contracts.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                eq = json.load(f).get('equity', {})
                cboe_opt = eq.get('cboe_option', 'SPY260923C00791000')
                underlying = eq.get('underlying', 'SPY')
                strike = float(eq.get('strike', 791.0))
                sym = eq.get('sym', f"{underlying}_C{int(strike)}")
                L = len(underlying)
                if len(cboe_opt) >= L + 7:
                    c_opt = cboe_opt[:L+6] + 'C' + cboe_opt[L+7:]
                    p_opt = cboe_opt[:L+6] + 'P' + cboe_opt[L+7:]
                else:
                    c_opt = cboe_opt
                    p_opt = cboe_opt
                return underlying, c_opt, p_opt, strike, sym
        except Exception:
            pass
    return 'SPY', 'SPY260923C00791000', 'SPY260923P00791000', 791.0, 'SPY_C791'

def fetch_cboe_options(underlying):
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{underlying}.json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode())['data']

async def run_cboe():
    underlying, target_call, target_put_name, strike_val, target_sym = load_equity_contract()
    print(f"Starting CBOE Equity Options Gateway ({underlying} - {target_call} [{target_sym}])")
    seq = 1
    last_contract = None
    loop = asyncio.get_running_loop()
    backoff = 3.0
    sym_padded = target_sym.encode('utf-8')[:8].ljust(8, b'\x00')
    while True:
        try:
            data = await loop.run_in_executor(None, fetch_cboe_options, underlying)
            options = data.get('options', [])
            target = [o for o in options if o.get('option') == target_call]
            target_put = [o for o in options if o.get('option') == target_put_name]
            spy_spot = float(data.get('current_price', 0.0))

            if target:
                last_contract = target[0]
                # Save live quant analytics for contract
                try:
                    qpath = os.path.join(os.path.dirname(__file__), 'cboe_greeks.json')
                    with open(qpath, 'w') as qf:
                        json.dump({
                            'iv': float(last_contract.get('iv', 0)),
                            'delta': float(last_contract.get('delta', 0)),
                            'gamma': float(last_contract.get('gamma', 0)),
                            'vega': float(last_contract.get('vega', 0)),
                            'theta': float(last_contract.get('theta', 0)),
                            'rho': float(last_contract.get('rho', 0)),
                            'theo': float(last_contract.get('theo', 0)),
                            'bid_size': float(last_contract.get('bid_size', 0)),
                            'ask_size': float(last_contract.get('ask_size', 0)),
                            'volume': float(last_contract.get('volume', 0)),
                            'open_interest': float(last_contract.get('open_interest', 0))
                        }, qf)
                except Exception:
                    pass

            if target and target_put:
                c_c = target[0]
                p_c = target_put[0]
                try:
                    ppath = os.path.join(os.path.dirname(__file__), 'cboe_parity.json')
                    with open(ppath, 'w') as pf:
                        json.dump({
                            'spot': spy_spot,
                            'strike': strike_val,
                            'call_bid': float(c_c.get('bid', 0)),
                            'call_ask': float(c_c.get('ask', 0)),
                            'call_theo': float(c_c.get('theo', 0)),
                            'put_bid': float(p_c.get('bid', 0)),
                            'put_ask': float(p_c.get('ask', 0)),
                            'put_theo': float(p_c.get('theo', 0)),
                            'put_iv': float(p_c.get('iv', 0)),
                        }, pf)
                except Exception:
                    pass
            backoff = 3.0
        except Exception as e:
            print(f"CBOE fetch notice: {e}")
            backoff = min(backoff * 1.5, 15.0)

        if last_contract and 'bid' in last_contract and 'ask' in last_contract:
            try:
                ts = time.time_ns()
                bid = float(last_contract['bid'])
                ask = float(last_contract['ask'])
                bid_sz = int(float(last_contract['bid_size']) * 100) if 'bid_size' in last_contract else 100
                ask_sz = int(float(last_contract['ask_size']) * 100) if 'ask_size' in last_contract else 100

                if bid > 0:
                    px = int(bid * 10000)
                    payload_bid = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 1, 0, ts, seq, b'B', bid_sz, sym_padded, px)
                    sock.sendto(payload_bid, (MCAST_IP, PORT_CBOE_OPT))
                    seq += 1

                if ask > 0:
                    px = int(ask * 10000)
                    payload_ask = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 1, 0, ts, seq, b'S', ask_sz, sym_padded, px)
                    sock.sendto(payload_ask, (MCAST_IP, PORT_CBOE_OPT))
                    seq += 1
            except Exception as e:
                print(f"CBOE send notice: {e}")

        await asyncio.sleep(backoff)

if __name__ == '__main__':
    asyncio.run(run_cboe())
