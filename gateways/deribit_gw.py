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

async def run_ws():
    url = "wss://www.deribit.com/ws/api/v2"
    call_channel = "ticker.BTC-23SEP26-80000-C.100ms"
    put_channel = "ticker.BTC-23SEP26-80000-P.100ms"
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
                print(f"Connected to Deribit Live BTC Options WS ({call_channel}, {put_channel})")
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

                    # If Put tick, capture Put quotes and update deribit_parity.json
                    if 'BTC-23SEP26-80000-P' in ch:
                        p_bid_btc = float(tick.get('best_bid_price') or 0.0)
                        p_ask_btc = float(tick.get('best_ask_price') or 0.0)
                        p_mark_btc = float(tick.get('mark_price') or 0.0)
                        last_put_bid = p_bid_btc * idx
                        last_put_ask = p_ask_btc * idx
                        put_mark_usd = p_mark_btc * idx
                        try:
                            with open(os.path.join(os.path.dirname(__file__), 'deribit_parity.json'), 'w') as pf:
                                json.dump({
                                    'spot': idx,
                                    'forward': last_fwd,
                                    'strike': 80000.0,
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

                    if 'best_bid_price' in tick and tick['best_bid_price'] > 0:
                        bid_usd = float(tick['best_bid_price']) * idx
                        last_call_bid = bid_usd
                        bid_px = int(bid_usd * 10000)
                        bid_qty = int(float(tick['best_bid_amount']) * 100) if 'best_bid_amount' in tick else 0
                        payload_bid = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1001, seq, bid_px, bid_qty)
                        sock.sendto(payload_bid, (MCAST_IP, PORT_DERIBIT_OPT))
                        seq += 1

                    if 'best_ask_price' in tick and tick['best_ask_price'] > 0:
                        ask_usd = float(tick['best_ask_price']) * idx
                        last_call_ask = ask_usd
                        ask_px = int(ask_usd * 10000)
                        ask_qty = int(float(tick['best_ask_amount']) * 100) if 'best_ask_amount' in tick else 0
                        payload_ask = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'1', 1001, seq, ask_px, ask_qty)
                        sock.sendto(payload_ask, (MCAST_IP, PORT_DERIBIT_OPT))
                        seq += 1

                    # Update parity metrics from Call side as well
                    try:
                        with open(os.path.join(os.path.dirname(__file__), 'deribit_parity.json'), 'w') as pf:
                            json.dump({
                                'spot': idx,
                                'forward': last_fwd,
                                'strike': 80000.0,
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
