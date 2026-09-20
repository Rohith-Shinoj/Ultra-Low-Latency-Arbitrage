import asyncio
import json
import websockets
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import ITCH_ADD_ORDER_FMT, MCAST_IP, PORT_BINANCE_SPOT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

async def run_ws():
    url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("Connected to Binance Spot WS (Live btcusdt@trade)")
                seq = 1
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if 'p' not in data:
                        continue
                    price = int(float(data['p']) * 10000)
                    qty = int(float(data['q']) * 100)
                    ts = time.time_ns()
                    side = b'S' if data.get('m') else b'B'
                    payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 1, 0, ts, seq, side, qty, b'BTC-USD\0', price)
                    sock.sendto(payload, (MCAST_IP, PORT_BINANCE_SPOT))
                    seq += 1
        except Exception as e:
            print(f"Binance WS error: {e}, reconnecting...")
            await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(run_ws())
