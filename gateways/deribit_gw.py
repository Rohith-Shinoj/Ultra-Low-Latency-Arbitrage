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
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'public/subscribe',
                    'params': {'channels': ['ticker.BTC-PERPETUAL.raw']}
                }))
                print("Connected to Deribit Live Derivatives WS (BTC-PERPETUAL)")
                seq = 1
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if 'params' not in data:
                        continue
                    tick = data['params'].get('data', {})
                    if 'last_price' not in tick:
                        continue
                    ts = time.time_ns()
                    price = int(float(tick['last_price']) * 10000)
                    qty = int(float(tick.get('best_bid_amount', 1)) * 100)
                    payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'C', 1001, seq, price, qty)
                    sock.sendto(payload, (MCAST_IP, PORT_DERIBIT_OPT))
                    seq += 1
        except Exception as e:
            # Fallback to testnet if cloud IP blocked
            try:
                test_url = "wss://test.deribit.com/ws/api/v2"
                async with websockets.connect(test_url) as ws:
                    await ws.send(json.dumps({
                        'jsonrpc': '2.0',
                        'id': 1,
                        'method': 'public/subscribe',
                        'params': {'channels': ['ticker.BTC-PERPETUAL.raw']}
                    }))
                    print("Connected to Deribit WS (Testnet Fallback)")
                    seq = 1
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if 'params' not in data:
                            continue
                        tick = data['params'].get('data', {})
                        if 'last_price' not in tick:
                            continue
                        ts = time.time_ns()
                        price = int(float(tick['last_price']) * 10000)
                        qty = int(float(tick.get('best_bid_amount', 1)) * 100)
                        payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'C', 1001, seq, price, qty)
                        sock.sendto(payload, (MCAST_IP, PORT_DERIBIT_OPT))
                        seq += 1
            except Exception:
                await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(run_ws())
