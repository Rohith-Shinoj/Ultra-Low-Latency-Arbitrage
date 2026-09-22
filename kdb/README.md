# KDB+ Tick Ingestion & Timeseries Database

Real-time tick capture and in-memory analytics pipeline powered by KDB+/q.

## Components
- **`tp.q`**: In-memory tickerplant process listening on port `5020`. Handles table definitions, IPC client connections, and periodic flushing to `hdb/`.
- **`schema.q`**: Table schemas for tick-by-tick storage:
  - `SpotBook`: Timestamp, sym, price, size, side, venue.
  - `OptBook`: Timestamp, sym, price, size, side, venue.
- **`multicast_sub.py`**: Python daemon that subscribes to local UDP multicast feeds (ports 5000–5005) and ingests parsed records into `tp.q` using `qPython`.

## Manual Invocation
```bash
# Start tickerplant on port 5020
q kdb/tp.q -p 5020

# Run multicast ingest subscriber
python3 kdb/multicast_sub.py
```
*(Automated automatically via `sudo ./start.sh --start kdb sub`)*
