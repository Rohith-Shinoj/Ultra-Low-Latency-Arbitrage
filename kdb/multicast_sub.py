import socket
import struct
import select
from datetime import datetime
import numpy as np
from qpython import qconnection
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gateways'))
from protocol import ITCH_ADD_ORDER_FMT, SBE_BOOK_UPDATE_FMT

MCAST_IP = '239.1.1.1'
PORTS = {
    5000: b'BINANCE',
    5001: b'COINBASE',
    5002: b'KRAKEN',
    5003: b'DERIBIT',
    5004: b'OKX',
    5005: b'BINANCE_OPT'
}

SEC_DEFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gateways', 'security_defs.json')
sec_cache = {}

def get_option_symbol(sec_id):
    global sec_cache
    sid_str = str(sec_id)
    if sid_str in sec_cache:
        return sec_cache[sid_str].encode()
    if os.path.exists(SEC_DEFS_FILE):
        try:
            import json
            with open(SEC_DEFS_FILE, 'r') as f:
                sec_cache = json.load(f)
            if sid_str in sec_cache:
                return sec_cache[sid_str].encode()
        except Exception:
            pass
    return f"OPT_{sec_id}".encode()

def create_mcast_socket(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', port))
    
    # Join multicast group specifically on veth1 (10.10.10.2), which is the receiving end of the veth pair
    #mreq = struct.pack("4s4s", socket.inet_aton(MCAST_IP), socket.inet_aton('10.10.10.2'))
    #sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return sock

import time

def send_upd(q, table, row):
    try:
        q.sendSync('upd', table, row)
        return True
    except Exception:
        try:
            try:
                q.close()
            except Exception:
                pass
            time.sleep(0.2)
            q.open()
            q.sendSync('upd', table, row)
            print("Reconnected to KDB+ Tickerplant")
            return True
        except Exception:
            return False

def main():
    q = qconnection.QConnection(host='localhost', port=5020)
    try:
        q.open()
        print("Connected to KDB+ Tickerplant (Port 5020)")
    except Exception as e:
        print(f"Failed to connect to KDB: {e}")
        return

    sockets = {create_mcast_socket(port): port for port in PORTS.keys()}
    print("Listening to UDP Multicast on ports 5000-5005...")

    ITCH_SIZE = struct.calcsize(ITCH_ADD_ORDER_FMT)
    SBE_SIZE = struct.calcsize(SBE_BOOK_UPDATE_FMT)

    try:
        while True:
            readable, _, _ = select.select(sockets.keys(), [], [])
            for sock in readable:
                data, addr = sock.recvfrom(1024)
                port = sockets[sock]
                exch = PORTS[port]

                if port <= 5002: # Spot (ITCH)
                    if len(data) == ITCH_SIZE:
                        msg_type, loc, track, ts, ref, side, qty, sym, px = struct.unpack(ITCH_ADD_ORDER_FMT, data)
                        sym_str = sym.decode('utf-8').strip('\x00')
                        price_float = px / 10000.0
                        qty_int = int(qty / 100)
                        
                        # Use np.datetime64 for KDB timestamps if using pandas/numpy, but qPython takes standard lists
                        # We'll just push simple tuples/lists
                        # qpython upd format: ('upd', 'SpotBook', [[time], [sym], [price], [size], [side], [exch]])
                        # To keep it simple, we push one tick at a time

                        try:
                            # Use numpy.datetime64 for qPython QTIMESTAMP
                            dt = np.datetime64(int(ts), 'ns')
                            send_upd(q, 'SpotBook', (dt, sym_str.encode(), float(price_float), int(qty_int), side, exch))
                        except Exception as e:
                            print(f"Spot Insert Error: {e}")
                else: # Options (SBE)
                    if len(data) == SBE_SIZE:
                        fields = struct.unpack(SBE_BOOK_UPDATE_FMT, data)
                        ts = fields[4]
                        entry_type = fields[8]
                        sec_id = fields[9]
                        px = fields[11]
                        qty = fields[12]
                        
                        price_float = px / 10000.0
                        qty_int = int(qty)
                        sym_bytes = get_option_symbol(sec_id)
                        side_byte = entry_type if entry_type in [b'C', b'P', b'B', b'S'] else b'C'
                        
                        try:
                            dt = np.datetime64(int(ts), 'ns')
                            send_upd(q, 'OptBook', (dt, sym_bytes, float(price_float), int(qty_int), side_byte, exch))
                        except Exception as e:
                            print(f"Opt Insert Error: {e}")

    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        q.close()
        for sock in sockets.keys():
            sock.close()

if __name__ == '__main__':
    main()
