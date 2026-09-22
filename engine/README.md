# C++20 Ultra-Low-Latency Arbitrage & Order Book Engine

High-performance C++20 execution engine designed for sub-microsecond cross-venue options and spot arbitrage.

## Key Features
- **Kernel-Bypass Ingress**: Uses Linux AF_XDP (eXpress Data Path) ring buffers (`af_xdp_core.cpp`, `xdp_prog.c`) for raw network frame ingress without kernel network stack overhead.
- **Lock-Free Order Books**: Cacheline-aligned L2 BBO books (`order_book.h`) with atomic updates.
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
