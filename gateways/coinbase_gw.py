import asyncio
import json
import websockets
import struct
import time
import socket
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from protocol import ITCH_ADD_ORDER_FMT, MCAST_IP, PORT_COINBASE_SPOT

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
#sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('10.10.10.1'))

async def run_ws():
    url = "wss://ws-feed.exchange.coinbase.com"
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({'type': 'subscribe', 'product_ids': ['BTC-USD'], 'channels': ['ticker']}))
        print("Connected to Coinbase Spot WS")
        seq = 1
        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get('type') != 'ticker' or 'price' not in data: continue
                price = int(float(data['price']) * 10000)
                qty = int(float(data['last_size']) * 100)
                ts = time.time_ns()
                side = b'B' if data.get('side') == 'buy' else b'S'
                payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 2, 0, ts, seq, side, qty, b'BTC-USD\0', price)
                sock.sendto(payload, (MCAST_IP, PORT_COINBASE_SPOT))
                seq += 1
            except Exception as e:
                pass

if __name__ == '__main__':
    asyncio.run(run_ws())
