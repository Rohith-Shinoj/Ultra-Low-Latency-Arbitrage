# C++20 Ultra-Low-Latency Arbitrage & Order Book Engine

[![C++20](https://img.shields.io/badge/C%2B%2B-20-00599C?logo=c%2B%2B&logoColor=white)](.)
[![Solarflare](https://img.shields.io/badge/Solarflare-OpenOnload%20%7C%20ef__vi-FF6F00?logo=amd&logoColor=white)](.)
[![Kernel Bypass](https://img.shields.io/badge/Kernel--Bypass-AF__XDP-success?logo=linux&logoColor=white)](.)

High-performance C++20 execution engine designed for sub-microsecond cross-venue options and spot arbitrage.

## Key Features
- **Dual Kernel-Bypass Ingress**: Probes PCIe bus for Solarflare SFC hardware (`0x1924` / `0x10ee`) and `/dev/onload` driver; automatically activates **Linux AF_XDP** zero-copy ring buffers (`UMEM`, Fill/Rx rings) as primary fallback.
- **Lock-Free Order Books**: 64-byte cacheline-aligned (`alignas(64)`) L2 BBO books (`order_book.h`) with atomic updates.
- **Zero-Copy Parsers**: Direct wire format decoding for ITCH 5.0 and binary multicast protocols (`itch50.h`, `cme_sbe.h`).
- **Hardware Benchmarking**: Nanosecond cycle-accurate profiling (`benchmark.h`) using CPU timestamp counters (`rdtsc` / ARM64 `cntvct_el0`).

## Build & Execution
```bash
# Compile engine binary
make -C engine

# Run pinned to CPU core 2
sudo ./engine/bin/engine_main 2
```
Outputs cycle benchmarks to `logs/latency_benchmark.txt`.
