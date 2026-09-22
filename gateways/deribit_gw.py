import asyncio
import json
import websockets
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import SBE_BOOK_UPDATE_FMT, MCAST_IP, PORT_DERIBIT_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

def load_crypto_contract():
    cfg_path = os.path.join(os.path.dirname(__file__), 'active_contracts.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                c = json.load(f).get('crypto', {})
                inst = c.get('deribit_instrument', 'BTC-23SEP26-80000-C')
                parts = inst.split('-')
                if len(parts) == 4:
                    put_inst = f"{parts[0]}-{parts[1]}-{parts[2]}-P"
                    call_inst = f"{parts[0]}-{parts[1]}-{parts[2]}-C"
                else:
                    call_inst = inst
                    put_inst = inst.replace('-C', '-P')
                return call_inst, put_inst, float(c.get('strike', 80000.0))
        except Exception:
            pass
    return "BTC-23SEP26-80000-C", "BTC-23SEP26-80000-P", 80000.0

async def run_ws():
    url = "wss://www.deribit.com/ws/api/v2"
    call_inst, put_inst, strike_val = load_crypto_contract()
    call_channel = f"ticker.{call_inst}.100ms"
    put_channel = f"ticker.{put_inst}.100ms"
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'public/subscribe',
                    'params': {'channels': [call_channel, put_channel]}
                }))
                await ws.recv()
                print(f"Connected to Deribit Live Options WS ({call_channel}, {put_channel})")
                seq = 1
                last_call_bid = 0.0
                last_call_ask = 0.0
                last_put_bid = 0.0
                last_put_ask = 0.0
                last_fwd = 0.0
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if 'params' not in data:
                        continue
                    ch = data['params'].get('channel', '')
                    tick = data['params'].get('data', {})
                    if 'index_price' not in tick:
                        continue
                    ts = time.time_ns()
                    idx = float(tick['index_price'])
                    fwd = float(tick.get('underlying_price', idx))
                    last_fwd = fwd

                    # Detect if linear USDC contract (e.g. SOL, XRP, AVAX) or inverse crypto-settled (BTC, ETH)
                    is_usdc = ('USDC' in call_inst or 'USDT' in call_inst)

                    # If Put tick, capture Put quotes and update deribit_parity.json
                    if put_inst in ch:
                        p_bid_raw = float(tick.get('best_bid_price') or 0.0)
                        p_ask_raw = float(tick.get('best_ask_price') or 0.0)
                        p_mark_raw = float(tick.get('mark_price') or 0.0)
                        last_put_bid = p_bid_raw if is_usdc else (p_bid_raw * idx)
                        last_put_ask = p_ask_raw if is_usdc else (p_ask_raw * idx)
                        put_mark_usd = p_mark_raw if is_usdc else (p_mark_raw * idx)
                        try:
                            with open(os.path.join(os.path.dirname(__file__), 'deribit_parity.json'), 'w') as pf:
                                json.dump({
                                    'spot': idx,
                                    'forward': last_fwd,
                                    'strike': strike_val,
                                    'call_bid': last_call_bid,
                                    'call_ask': last_call_ask,
                                    'put_bid': last_put_bid,
                                    'put_ask': last_put_ask,
                                    'put_mark': put_mark_usd
                                }, pf)
                        except Exception:
                            pass
                        continue

                    # Call Option processing
                    if 'greeks' in tick or 'mark_iv' in tick:
                        try:
                            g = tick.get('greeks') or {}
                            with open(os.path.join(os.path.dirname(__file__), 'deribit_greeks.json'), 'w') as qf:
                                json.dump({
                                    'iv': float(tick.get('mark_iv', 0)),
                                    'delta': float(g.get('delta', 0)),
                                    'gamma': float(g.get('gamma', 0)),
                                    'vega': float(g.get('vega', 0)),
                                    'theta': float(g.get('theta', 0)),
                                    'underlying_price': fwd
                                }, qf)
                        except Exception:
                            pass

                    b_px_val = tick.get('best_bid_price')
                    if b_px_val is not None and float(b_px_val) > 0:
                        bid_usd = float(b_px_val) if is_usdc else (float(b_px_val) * idx)
                        last_call_bid = bid_usd
                        bid_px = int(bid_usd * 10000)
                        bid_qty = int(float(tick.get('best_bid_amount', 0)) * 100)
                        payload_bid = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1001, seq, bid_px, bid_qty)
                        sock.sendto(payload_bid, (MCAST_IP, PORT_DERIBIT_OPT))
                        seq += 1

                    a_px_val = tick.get('best_ask_price')
                    if a_px_val is not None and float(a_px_val) > 0:
                        ask_usd = float(a_px_val) if is_usdc else (float(a_px_val) * idx)
                        last_call_ask = ask_usd
                        ask_px = int(ask_usd * 10000)
                        ask_qty = int(float(tick.get('best_ask_amount', 0)) * 100)
                        payload_ask = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'1', 1001, seq, ask_px, ask_qty)
                        sock.sendto(payload_ask, (MCAST_IP, PORT_DERIBIT_OPT))
                        seq += 1

                    # Update parity metrics from Call side as well
                    try:
                        with open(os.path.join(os.path.dirname(__file__), 'deribit_parity.json'), 'w') as pf:
                            json.dump({
                                'spot': idx,
                                'forward': last_fwd,
                                'strike': strike_val,
                                'call_bid': last_call_bid,
                                'call_ask': last_call_ask,
                                'put_bid': last_put_bid,
                                'put_ask': last_put_ask,
                                'put_mark': 0.0
                            }, pf)
                    except Exception:
                        pass

        except Exception as e:
            print(f"Deribit BTC Option WS notice: {e}, reconnecting...")
            await asyncio.sleep(2)

if __name__ == '__main__':
    asyncio.run(run_ws())
