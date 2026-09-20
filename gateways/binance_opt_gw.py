import asyncio
import json
import websockets
import struct
import time
import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import SBE_BOOK_UPDATE_FMT, MCAST_IP, PORT_BINANCE_OPT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)

async def run_ws():
    url = "wss://fstream.binance.com/ws/btcusdt@ticker"
    while True:
        try:
            async with websockets.connect(url) as ws:
                print("Connected to Binance Live Derivatives/Futures WS (btcusdt@ticker)")
                seq = 1
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if 'c' not in data:
                        continue
                    ts = time.time_ns()
                    price = int(float(data['c']) * 10000)
                    qty = int(float(data['v']) * 100)
                    payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'C', 1003, seq, price, qty)
                    sock.sendto(payload, (MCAST_IP, PORT_BINANCE_OPT))
                    seq += 1
        except Exception as e:
            print(f"Binance Futures WS error: {e}, reconnecting...")
            await asyncio.sleep(1)

if __name__ == '__main__':
    asyncio.run(run_ws())
