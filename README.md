# Ultra-Low-Latency Cross-Venue Arbitrage Terminal

[![C++20](https://img.shields.io/badge/C%2B%2B-20-00599C?logo=c%2B%2B&logoColor=white)](engine/)
[![Solarflare](https://img.shields.io/badge/Solarflare-OpenOnload%20%7C%20ef__vi-FF6F00?logo=amd&logoColor=white)](engine/)
[![Kernel Bypass](https://img.shields.io/badge/Kernel--Bypass-AF__XDP-success?logo=linux&logoColor=white)](engine/)
[![KDB+/q](https://img.shields.io/badge/Database-KDB%2B%20%2F%20q-black)](kdb/)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](gateways/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

An institutional-grade, ultra-low-latency arbitrage pipeline and Bloomberg-style dual-pane terminal for cross-venue options and spot markets across Equity and Crypto.

---

## Live Terminal

<p align="center">
  <img src="assets/demo.gif" alt="Bloomberg-Style Dual-Pane Terminal Demo" width="100%">
</p>

---

## Architecture Overview

```
                                  ┌────────────────────────┐
                                  │   6 Exchange Gateways  │
                                  │  (3 Equity + 3 Crypto) │
                                  └───────────┬────────────┘
                                              │ Direct Market Feeds
                                              ▼
                                 ┌─────────────────────────┐
                                 │  Kernel-Bypass Ingress  │
                                 │  • Solarflare OpenOnload│
                                 │  • Linux AF_XDP (eBPF)  │
                                 └────────────┬────────────┘
                                              │ Zero-Copy UMEM Rings / Direct DMA
                     ┌────────────────────────┴────────────────────────┐
                     ▼                                                 ▼
        ┌─────────────────────────┐                       ┌─────────────────────────┐
        │   C++20 Engine (ULL)    │                       │      KDB+ Pipeline      │
        │  • Solarflare / AF_XDP  │                       │  • In-Memory Tickerplant│
        │  • Zero-Copy Parsing    │                       │  • Microstructure Store │
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
- **6 Multi-Venue Pipelines**: 3 Equity (CBOE, Nasdaq, OPRA) and 3 Crypto venues (Deribit, OKX, Binance).
- **Binary Normalization**: Normalizes exchange L2 books and trades directly into compact binary wire packets (Nasdaq ITCH 5.0 format for equity options, CME MDP 3.0 SBE format for crypto options).
- **Real-Time Quant Greeks**: In-flight Black-Scholes Greeks ($\Delta$, $\Gamma$, $\nu$, $\Theta$, IV) and Put-Call Parity arbitrage signals across 10 core assets.

### 2. C++20 Ultra-Low-Latency Engine (`engine/`)
- **Dual Kernel-Bypass Ingress (Solarflare OpenOnload + Linux AF_XDP)**:
  - **Solarflare OpenOnload / `ef_vi` Scan**: Proactive hardware scanner probes PCIe network adapters for Solarflare vendor IDs (`0x1924` for Solarflare Communications, `0x10ee` for AMD/Xilinx SFC), `/dev/onload` character devices, and active Onload namespaces. Configures `SO_BUSY_POLL` spinning and user-space direct-NIC DMA when present.
  - **Linux AF_XDP (eXpress Data Path)**: Utilizes native eBPF driver/SKB hooks and AF_XDP zero-copy ring buffers (`UMEM`, Fill Ring, Completion Ring, Rx Ring) to route wire frames directly into userspace memory buffers (`bpf_redirect_map`), completely bypassing the Linux network stack for deterministic sub-microsecond packet ingestion.
- **Zero-Copy & Lock-Free Design**: In-place pointer-cast packet parsing with 64-byte cacheline-aligned (`alignas(64)`) lock-free L2 BBO order books.
- **Core Pinning & Latency Profiling**: Thread isolated and pinned to CPU Core 2; hardware cycle timers (`rdtsc` / `cntvct_el0`) capture nanosecond stage-by-stage percentiles (P50, P90, P99, P99.9).

### 3. KDB+/q Streaming Pipeline (`kdb/`)
- **In-Memory Tickerplant (`kdb/tp.q`)**: High-throughput columnar database running on port `5020`, streaming live `SpotBook` and `OptBook` tables with an in-memory rolling buffer and monotonic cumulative tick tracking (`tot_ticks`).
- **Real-Time Microstructure Store**: Maintains tick-by-tick order book depth, cross-venue spread histories, and execution audit trails via IPC.

### 4. Bloomberg-Style Terminal Interface (`scripts/bloomberg_tui.py`)
- **Dual-Pane Options Matrix**: Simultaneous side-by-side L2 Depth-of-Market books for both Crypto and Equity options.
- **Independent Stream Toggling (`[TAB]`)**: Toggles bottom tape between single-asset Crypto and Equity streams without affecting top books.
- **Contract Discovery (`[ESC]`)**: Dynamic options matrix to browse and hot-swap active strikes and expiries across all 10 assets.
- **Optimized Rendering Engine**: Uses persistent KDB+ IPC client connections and fast tail-seek log inspection for high-frequency screen repaints.
- **Live Hardware Telemetry**: Real-time dock displaying pinned CPU utilization and nanosecond pipeline latency percentiles.

---

## Prerequisites & Installation

### 1. System Packages (`sudo apt` / `snap`)
Install C++20 build tools, Clang/LLVM for eBPF compilation, Linux kernel headers, and AF_XDP/BPF development libraries:

**Via APT (Standard Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y \
    build-essential \
    clang \
    llvm \
    libbpf-dev \
    libxdp-dev \
    linux-headers-$(uname -r) \
    python3 \
    python3-pip \
    python3-venv \
    rlwrap
```

**Via Snap (Optional / Alternative):**
If you manage your developer toolchain via `snap`, Clang and packaging tools can alternatively be installed with:
```bash
# Optional snap toolchain installations
sudo snap install --classic clangd
```
> [!NOTE]
> Host kernel headers (`linux-headers-$(uname -r)`), `libbpf-dev`, and `libxdp-dev` must be installed through `apt` to match your running kernel release for eBPF/AF_XDP driver bindings.

### 2. Python Dependencies (`requirements.txt`)
Install the required asynchronous networking, quantitative calculation, and terminal rendering packages:

```bash
pip install -r requirements.txt
```

### 3. KDB+/q Engine & License
The tick pipeline runs on **KDB+/q**. Download the free personal evaluation edition for Linux from [Kx Systems](https://kx.com/download/):
- Unzip the downloaded archive (e.g. `l64.zip`) into `~/q`:
  ```bash
  mkdir -p ~/q
  unzip l64.zip -d ~/q
  ```
- Copy your KX license file (`kc.lic` or `k4.lic` received by email from KX) to `~/q/`:
  ```bash
  cp /path/to/kc.lic ~/q/
  ```
- Add `q` and `QHOME` to your shell profile (`~/.bashrc`):
  ```bash
  export QHOME="$HOME/q"
  export PATH="$QHOME/l64:$PATH"
  ```
> [!TIP]
> `./start.sh` automatically detects and exports `QHOME=~/q` and `PATH=$HOME/q/l64:$PATH` if `~/q` or `~/.kx` is present.


---

## Quick Start & Replication

### 1. Build Engine & Compile eBPF Bytecode
The C++20 engine and eBPF filter program (`xdp_prog.c`) can be compiled using:
```bash
make -C engine
```
This builds:
- `engine/bin/xdp_prog.o`: eBPF bytecode compiled via `clang -target bpf -g -O2` with BTF debug symbols.
- `engine/bin/engine_main`: C++20 binary compiled with `-lxdp -lbpf -lpthread`.

### 2. Privilege Requirements for AF_XDP
Attaching an eBPF program to a network device (`bpf_xdp_attach`) and binding raw `AF_XDP` socket rings (`xsk_socket__create`) requires administrative capabilities (`CAP_NET_ADMIN` and `CAP_BPF`). 

Launch the pipeline with `sudo`:
```bash
# Launch Bloomberg-style terminal TUI
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

> [!NOTE]
> Alternatively, you can grant the binary standalone capabilities without running the entire suite as root:
> ```bash
> sudo setcap cap_net_admin,cap_bpf=ep engine/bin/engine_main
> ./start.sh
> ```

### 3. Verifying Kernel Bypass Ingress
Once running, you can independently verify that eBPF and AF_XDP are actively handling ingress:

1. **Verify eBPF XDP hook attachment on loopback:**
   ```bash
   ip link show dev lo
   ```
   *Expected output:* Confirms `xdp` or `xdpgeneric prog/xdp id <id>` is active on `lo`.

2. **Verify AF_XDP socket descriptors:**
   ```bash
   sudo ls -l /proc/$(pgrep -f engine_main | head -n1)/fd
   ```
   *Expected output:* Confirms `anon_inode:bpf-prog`, `anon_inode:bpf-map`, and `socket:[...]` (family `AF_XDP`) with direct UMEM memory frame bindings.

3. **Verify KDB+ tickerplant ingestion:**
   ```bash
   python3 -c "from qpython import qconnection; q = qconnection.QConnection('localhost', 5020); q.open(); print('Total Ticks Ingested:', q('tot_ticks'))"
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
├── requirements.txt     # Core Python library dependencies
└── .gitignore           # Repository ignore rules (ignores .md except READMEs)
```
