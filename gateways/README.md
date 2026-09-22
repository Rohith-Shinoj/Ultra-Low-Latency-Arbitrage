# Market Data Gateways

Collection of 6 standalone market data gateways connecting to live exchange WebSocket/REST feeds and broadcasting standardized binary packets over UDP multicast.

## Venues & Multicast Ports

| Gateway Script | Market Type | Venue | Multicast Port | Target Instruments |
| :--- | :--- | :--- | :--- | :--- |
| `cboe_opt_gw.py` | Equity Options | CBOE | `UDP 5000` | SPY, QQQ, AAPL, NVDA, TSLA |
| `nasdaq_opt_gw.py` | Equity Options | Nasdaq Options | `UDP 5001` | SPY, QQQ, AAPL, NVDA, TSLA |
| `opra_opt_gw.py` | Equity Options | OPRA Consolidated | `UDP 5002` | SPY, QQQ, AAPL, NVDA, TSLA |
| `deribit_gw.py` | Crypto Options | Deribit | `UDP 5003` | BTC, ETH, SOL, XRP, AVAX |
| `okx_gw.py` | Crypto Options | OKX | `UDP 5004` | BTC, ETH, SOL, XRP, AVAX |
| `binance_opt_gw.py` | Crypto Options | Binance | `UDP 5005` | BTC, ETH, SOL, XRP, AVAX |

## Configuration Files
- `active_contracts.json`: Real-time active contract selections synced with the terminal selector.
- `security_defs.json`: Options contract metadata (strikes, expiries, instrument names).
- `contract_catalog.json`: Discovered options contract catalogue across all supported assets.
