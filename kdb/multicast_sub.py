import time
import socket
import struct
import select
from datetime import datetime
import numpy as np
if not hasattr(np, 'string_'):
    np.string_ = np.bytes_
from qpython import qconnection
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gateways'))
from protocol import ITCH_ADD_ORDER_FMT, SBE_BOOK_UPDATE_FMT

MCAST_IP = '239.1.1.1'
PORTS = {
    5000: b'CBOE_OPT',
    5001: b'NASDAQ_OPT',
    5002: b'OPRA_OPT',
    5003: b'DERIBIT_OPT',
    5004: b'OKX_OPT',
    5005: b'BINANCE_OPT'
}

ACTIVE_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gateways', 'active_contracts.json')
SEC_DEFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gateways', 'security_defs.json')
sec_cache = {}
last_cfg_mtime = 0

def get_option_symbol(sec_id):
    global sec_cache, last_cfg_mtime
    sid_str = str(sec_id)
    now = time.time()
    if now - last_cfg_mtime > 1.0:
        last_cfg_mtime = now
        # Prefer active_contracts.json for real-time dynamic contract switching
        if os.path.exists(ACTIVE_CFG_FILE):
            try:
                import json
                with open(ACTIVE_CFG_FILE, 'r') as f:
                    cfg = json.load(f)
                    c_sym = cfg.get('crypto', {}).get('sym')
                    if c_sym:
                        sec_cache['1001'] = c_sym
                        sec_cache['1002'] = c_sym
                        sec_cache['1003'] = c_sym
            except Exception:
                pass
        elif os.path.exists(SEC_DEFS_FILE):
            try:
                import json
                with open(SEC_DEFS_FILE, 'r') as f:
                    sec_cache = json.load(f)
            except Exception:
                pass

    if sid_str in sec_cache:
        return sec_cache[sid_str].encode()
    return f"OPT_{sec_id}".encode()

def create_mcast_socket(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, 'SO_REUSEPORT'):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
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
    connected = False
    for _ in range(15):
        try:
            q.open()
            connected = True
            print("Connected to KDB+ Tickerplant (Port 5020)")
            break
        except Exception:
            time.sleep(0.5)
    if not connected:
        print("Failed to connect to KDB after retries")
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

                if port <= 5002: # Equity Options (ITCH)
                    if len(data) == ITCH_SIZE:
                        msg_type, loc, track, ts, ref, side, qty, sym, px = struct.unpack(ITCH_ADD_ORDER_FMT, data)
                        sym_str = sym.decode('utf-8').strip('\x00')
                        price_float = px / 10000.0
                        qty_int = int(qty / 100)
                        
                        try:
                            dt = np.datetime64(int(ts), 'ns')
                            send_upd(q, 'OptBook', (dt, sym_str.encode(), float(price_float), int(qty_int), side, exch))
                        except Exception as e:
                            print(f"Equity Opt Insert Error: {e}")
                else: # Crypto Options (SBE)
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
                        side_byte = b'B' if entry_type in [b'0', b'B'] else (b'S' if entry_type in [b'1', b'S'] else entry_type)
                        
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
