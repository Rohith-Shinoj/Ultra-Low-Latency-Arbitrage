# Ultra-Low-Latency Cross-Venue Arbitrage & Trading Terminal

An institutional-grade, ultra-low-latency arbitrage pipeline and Bloomberg-style dual-pane terminal for cross-venue options and spot markets across Equity and Crypto.

---

## Architecture Overview

```
                                  ┌────────────────────────┐
                                  │   6 Exchange Gateways  │
                                  │  (3 Equity + 3 Crypto) │
                                  └───────────┬────────────┘
                                              │ UDP Multicast (Ports 5000-5005)
                     ┌────────────────────────┴────────────────────────┐
                     ▼                                                 ▼
        ┌─────────────────────────┐                       ┌─────────────────────────┐
        │   C++20 Engine (AF_XDP) │                       │      KDB+ Pipeline      │
        │  • Kernel-Bypass Sockets│                       │  • Multicast Subscriber │
        │  • Zero-Copy Parsing    │                       │  • In-Memory Tickerplant│
        │  • Lock-Free L2 Books   │                       │  • Port 5020 (tp.q)     │
        │  • Cycle Latency (rdtsc)│                       └────────────┬────────────┘
        └────────────┬────────────┘                                    │
                     │                                                 │
                     └────────────────────────┬────────────────────────┘
                                              ▼
                                 ┌─────────────────────────────┐
                                 │   Bloomberg-Style Terminal  │
                                 │       (sudo ./start.sh)     │
                                 └─────────────────────────────┘
```

### 1. Market Data Gateways (`gateways/`)
- **6 Multi-Venue Pipelines**: 3 Equity (CBOE `UDP 5000`, Nasdaq `UDP 5001`, OPRA `UDP 5002`) and 3 Crypto venues (Deribit `UDP 5003`, OKX `UDP 5004`, Binance `UDP 5005`).
- **Binary Normalization**: Normalizes exchange L2 books and trades into compact binary packets broadcast over dedicated UDP multicast feeds.
- **Real-Time Quant Greeks**: In-flight Black-Scholes Greeks ($\Delta$, $\Gamma$, $\nu$, $\Theta$, IV) and Put-Call Parity arbitrage signals across 10 core assets.

### 2. C++20 Ultra-Low-Latency Engine (`engine/`)
- **AF_XDP Kernel Bypass**: Direct-to-ring wire ingestion using Linux AF_XDP (with fallback to non-blocking zero-copy socket rings), completely bypassing the OS network stack.
- **Hardware Acceleration Provision**: Primary bypass via AF_XDP with architectural hooks for enterprise Solarflare OpenOnload / `ef_vi` hardware adapters.
- **Zero-Copy & Lock-Free Design**: In-place pointer-cast packet parsing with 64-byte cacheline-aligned (`alignas(64)`) lock-free L2 BBO order books.
- **Core Pinning & Latency Profiling**: Thread isolated and pinned to CPU Core 2; hardware cycle timers (`rdtsc` / `cntvct_el0`) capture nanosecond stage-by-stage percentiles (P50, P90, P99, P99.9).

### 3. KDB+/q Streaming Pipeline (`kdb/`)
- **In-Memory Tickerplant (`kdb/tp.q`)**: High-throughput columnar database running on port `5020`, streaming live `SpotBook` and `OptBook` tables.
- **Asynchronous Subscriber (`kdb/multicast_sub.py`)**: Consumes multicast UDP frames and streams vectorized tick records into KDB+ via `qPython`.

### 4. Bloomberg-Style Terminal Interface (`scripts/bloomberg_tui.py`)
- **Dual-Pane Options Matrix**: Simultaneous side-by-side L2 Depth-of-Market books for both Crypto and Equity options.
- **Independent Stream Toggling (`[TAB]`)**: Toggles bottom tape between single-asset Crypto and Equity streams without affecting top books.
- **Contract Discovery (`[ESC]`)**: Dynamic options matrix to browse and hot-swap active strikes and expiries across all 10 assets.
- **Live Hardware Telemetry**: Real-time dock displaying pinned CPU utilization and nanosecond pipeline latency percentiles.

---

## Quick Start

The entire pipeline and trading terminal are managed through `sudo ./start.sh`.

```bash
# Launch Bloomberg-style terminal TUI directly (requires sudo for kernel AF_XDP & raw sockets)
sudo ./start.sh

# Check real-time process health and PIDs of all components
sudo ./start.sh --status

# Restart all infrastructure services (KDB+, subscriber, engine, gateways)
sudo ./start.sh --restart all

# Query live KDB+ tick counts, cross-venue prices, and quant Greeks
sudo ./start.sh --query

# View hardware latency benchmarks from the C++ engine
sudo ./start.sh --benchmark

# Display full CLI manual
sudo ./start.sh --help
```

---

## Terminal Navigation

| Key | Action |
| :--- | :--- |
| `[TAB]` | Toggle lower live stream tape between **Crypto** and **Equity** |
| `[Left]` / `[c]` | Expand Crypto options pane (100% width) |
| `[Right]` / `[e]` | Expand Equity options pane (100% width) |
| `[Up]` / `[Down]` / `[b]` | Reset to 50/50 Dual-Pane Split mode |
| `[ESC]` | Return to / open the Contract Discovery & Selection screen |
| `[q]` | Exit the terminal |

---

## Directory Structure

```text
├── engine/              # C++20 lock-free execution engine & AF_XDP kernel bypass
├── gateways/            # 6 market data gateways and contract definitions
├── kdb/                 # KDB+ tickerplant (tp.q), schemas, and multicast subscriber
├── scripts/             # Controller (control.py), Bloomberg TUI, contract selector
├── start.sh             # Root-level launcher and CLI management script
└── .gitignore           # Repository ignore rules (ignores .md except READMEs)
```
