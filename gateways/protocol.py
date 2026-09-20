import struct

# --- Nasdaq ITCH 5.0 Protocols ---

# ITCH 5.0 Add Order (Type 'A')
# C-Struct Layout: 
# char message_type (1)
# uint16_t stock_locate (2)
# uint16_t tracking_number (2)
# uint64_t timestamp (8)
# uint64_t order_reference_number (8)
# char buy_sell_indicator (1)
# uint32_t shares (4)
# char stock[8] (8)
# uint32_t price (4)
# Total: 38 bytes
ITCH_ADD_ORDER_FMT = '<c H H Q Q c I 8s I'
ITCH_ADD_ORDER_SIZE = struct.calcsize(ITCH_ADD_ORDER_FMT)


# --- CME MDP 3.0 SBE Protocols ---

# SBE Simplified Book Update
# SBEHeader: uint16, uint16, uint16, uint16 (8 bytes)
# CMEBookUpdate: header(8) + uint64(8) + uint32(4) + uint8(1) 
# MDEntry: uint8(1) + char(1) + uint32(4) + uint32(4) + int64(8) + int32(4) = (22 bytes)
# Total: 43 bytes
SBE_BOOK_UPDATE_FMT = '<H H H H Q I B B c I I q i'
SBE_BOOK_UPDATE_SIZE = struct.calcsize(SBE_BOOK_UPDATE_FMT)

# --- Network Configuration ---
MCAST_IP = '127.0.0.1'

# Dedicated Ports per Genuine Exchange
PORT_BINANCE_SPOT = 5000
PORT_COINBASE_SPOT = 5001
PORT_KRAKEN_SPOT = 5002

PORT_DERIBIT_OPT = 5003
PORT_OKX_OPT = 5004
PORT_BINANCE_OPT = 5005
