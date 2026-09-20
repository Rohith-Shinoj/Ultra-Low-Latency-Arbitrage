import asyncio
import json
import websockets
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import SBE_BOOK_UPDATE_FMT, MCAST_IP, PORT_OKX_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

async def run_ws():
    url = "wss://ws.okx.com:8443/ws/v5/public"
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps({'op': 'subscribe', 'args': [{'channel': 'tickers', 'instId': 'BTC-USD-SWAP'}]}))
                print("Connected to OKX Live Derivatives WS (BTC-USD-SWAP)")
                seq = 1
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if 'data' not in data or not data['data']:
                        continue
                    tick = data['data'][0]
                    if 'last' not in tick:
                        continue
                    ts = time.time_ns()
                    price = int(float(tick['last']) * 10000)
                    qty = int(float(tick.get('vol24h', 1)) * 100)
                    payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'C', 1002, seq, price, qty)
                    sock.sendto(payload, (MCAST_IP, PORT_OKX_OPT))
                    seq += 1
        except Exception as e:
            print(f"OKX WS error: {e}, reconnecting...")
            await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(run_ws())
