import os

TEMPLATE = """import asyncio
import json
import websockets
import struct
import time
import socket
from protocol import {fmt}, {ip}, {port}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton('10.10.10.1'))

async def run_ws():
    url = "{url}"
    async with websockets.connect(url) as ws:
        {sub_msg}
        print("Connected to {name} WS")
        seq = 1
        while True:
            try:
                msg = await ws.recv()
                {parse_logic}
                sock.sendto(payload, ({ip}, {port}))
                seq += 1
            except Exception as e:
                pass

if __name__ == '__main__':
    asyncio.run(run_ws())
"""

gateways = {
    "binance_gw.py": {
        "fmt": "ITCH_ADD_ORDER_FMT", "ip": "MCAST_IP", "port": "PORT_BINANCE_SPOT",
        "url": "wss://stream.binance.com:9443/ws/btcusdt@trade", "name": "Binance Spot",
        "sub_msg": "",
        "parse_logic": """data = json.loads(msg)
                price = int(float(data['p']) * 10000)
                qty = int(float(data['q']) * 100)
                ts = data['E'] * 1000000
                side = b'S' if data['m'] else b'B'
                payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 1, 0, ts, seq, side, qty, b'BTCUSDT\\0', price)"""
    },
    "coinbase_gw.py": {
        "fmt": "ITCH_ADD_ORDER_FMT", "ip": "MCAST_IP", "port": "PORT_COINBASE_SPOT",
        "url": "wss://ws-feed.exchange.coinbase.com", "name": "Coinbase Spot",
        "sub_msg": "await ws.send(json.dumps({'type': 'subscribe', 'product_ids': ['BTC-USD'], 'channels': ['ticker']}))",
        "parse_logic": """data = json.loads(msg)
                if data.get('type') != 'ticker' or 'price' not in data: continue
                price = int(float(data['price']) * 10000)
                qty = int(float(data['last_size']) * 100)
                ts = int(time.time() * 1e9)
                side = b'B' if data.get('side') == 'buy' else b'S'
                payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 2, 0, ts, seq, side, qty, b'BTC-USD\\0', price)"""
    },
    "kraken_gw.py": {
        "fmt": "ITCH_ADD_ORDER_FMT", "ip": "MCAST_IP", "port": "PORT_KRAKEN_SPOT",
        "url": "wss://ws.kraken.com", "name": "Kraken Spot",
        "sub_msg": "await ws.send(json.dumps({'event': 'subscribe', 'pair': ['XBT/USD'], 'subscription': {'name': 'trade'}}))",
        "parse_logic": """data = json.loads(msg)
                if not isinstance(data, list): continue
                for trade in data[1]:
                    price = int(float(trade[0]) * 10000)
                    qty = int(float(trade[1]) * 100)
                    ts = int(float(trade[2]) * 1e9)
                    side = b'B' if trade[3] == 'b' else b'S'
                    payload = struct.pack(ITCH_ADD_ORDER_FMT, b'A', 3, 0, ts, seq, side, qty, b'XBT/USD\\0', price)"""
    },
    "deribit_gw.py": {
        "fmt": "SBE_BOOK_UPDATE_FMT", "ip": "MCAST_IP", "port": "PORT_DERIBIT_OPT",
        "url": "wss://test.deribit.com/ws/api/v2", "name": "Deribit Options",
        "sub_msg": "await ws.send(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'public/subscribe', 'params': {'channels': ['ticker.BTC-PERPETUAL.raw']}}))",
        "parse_logic": """data = json.loads(msg)
                if 'params' not in data: continue
                tick = data['params']['data']
                ts = tick['timestamp'] * 1000000
                price = int(tick['last_price'] * 10000)
                qty = int(tick.get('best_bid_amount', 1) * 100)
                payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1001, seq, price, qty)"""
    },
    "okx_gw.py": {
        "fmt": "SBE_BOOK_UPDATE_FMT", "ip": "MCAST_IP", "port": "PORT_OKX_OPT",
        "url": "wss://ws.okx.com:8443/ws/v5/public", "name": "OKX Options",
        "sub_msg": "await ws.send(json.dumps({'op': 'subscribe', 'args': [{'channel': 'tickers', 'instId': 'BTC-USD-SWAP'}]}))",
        "parse_logic": """data = json.loads(msg)
                if 'data' not in data: continue
                tick = data['data'][0]
                ts = int(tick['ts']) * 1000000
                price = int(float(tick['last']) * 10000)
                qty = int(float(tick.get('vol24h', 1)) * 100)
                payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1002, seq, price, qty)"""
    },
    "binance_opt_gw.py": {
        "fmt": "SBE_BOOK_UPDATE_FMT", "ip": "MCAST_IP", "port": "PORT_BINANCE_OPT",
        "url": "wss://fstream.binance.com/ws/btcusdt@ticker", "name": "Binance Options/Futures",
        "sub_msg": "",
        "parse_logic": """data = json.loads(msg)
                if 'c' not in data: continue
                ts = data['E'] * 1000000
                price = int(float(data['c']) * 10000)
                qty = int(float(data['v']) * 100)
                payload = struct.pack(SBE_BOOK_UPDATE_FMT, 32, 32, 1, 1, ts, 1, 1, 0, b'0', 1003, seq, price, qty)"""
    }
}

for filename, cfg in gateways.items():
    with open(f"gateways/{filename}", 'w') as f:
        f.write(TEMPLATE.format(**cfg))
    print(f"Generated {filename}")
