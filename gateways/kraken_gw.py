import asyncio
import json
import websockets
import struct
import time
import socket
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import ITCH_ADD_ORDER_FMT, MCAST_IP, PORT_KRAKEN_SPOT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
#sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('10.10.10.1'))

async def run_ws():
    url = "wss://ws.kraken.com"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({'event': 'subscribe', 'pair': ['XBT/USD'], 'subscription': {'name': 'ticker'}}))
        await ws.send(json.dumps({'event': 'subscribe', 'pair': ['XBT/USD'], 'subscription': {'name': 'trade'}}))
        print("Connected to Kraken Spot WS (Ticker + Trades)")
        seq = 1
        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if not isinstance(data, list) or len(data) < 2:
                    continue
                
                # Handle Ticker Updates
                if isinstance(data[1], dict) and 'c' in data[1]:
                    c_data = data[1]['c']
                    price = int(float(c_data[0]) * 10000)
                    qty = 100
                    ts = time.time_ns()
                    side = b'B'
                    payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 3, 0, ts, seq, side, qty, b'BTC-USD\0', price)
                    sock.sendto(payload, (MCAST_IP, PORT_KRAKEN_SPOT))
                    seq += 1
                # Handle Trade Updates
                elif isinstance(data[1], list):
                    for trade in data[1]:
                        price = int(float(trade[0]) * 10000)
                        qty = int(float(trade[1]) * 100)
                        ts = time.time_ns()
                        side = b'B' if trade[3] == 'b' else b'S'
                        payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 3, 0, ts, seq, side, qty, b'BTC-USD\0', price)
                        sock.sendto(payload, (MCAST_IP, PORT_KRAKEN_SPOT))
                        seq += 1
            except Exception as e:
                pass

if __name__ == '__main__':
    asyncio.run(run_ws())
