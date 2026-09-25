#!/usr/bin/env python3
"""
Central Gateway & Pipeline Controller for Ultra-Low-Latency Arbitrage Infrastructure.
Manages 6 genuine live options venues (3 Crypto + 3 Equity), C++20 execution engine, KDB+ tickerplant.
"""

import sys
import os
import time
import signal
import subprocess
import argparse
from pathlib import Path
import glob

import shutil

# Ensure user site-packages and binaries (KX/KDB+, ~/.local/bin) are accessible when invoked via sudo
_candidate_homes = []
if "SUDO_USER" in os.environ:
    try:
        import pwd
        _candidate_homes.append(pwd.getpwnam(os.environ["SUDO_USER"]).pw_dir)
    except Exception:
        pass
_candidate_homes.extend([str(Path.home()), "/home/ubuntu"])

for _uh in _candidate_homes:
    if os.path.isdir(_uh):
        for p in glob.glob(f"{_uh}/.local/lib/python*/site-packages"):
            if p not in sys.path:
                sys.path.insert(0, p)
        _kx_dir = Path(_uh) / ".kx"
        if _kx_dir.is_dir() and ((_kx_dir / "kc.lic").exists() or (_kx_dir / "k4.lic").exists()):
            os.environ["QLIC"] = str(_kx_dir)
            if (_kx_dir / "q").is_dir():
                os.environ["QHOME"] = str(_kx_dir / "q")
        else:
            _q_dir = Path(_uh) / "q"
            if _q_dir.is_dir():
                if "QHOME" not in os.environ:
                    os.environ["QHOME"] = str(_q_dir)
                if "QLIC" not in os.environ:
                    os.environ["QLIC"] = str(_q_dir)
            if _kx_dir.is_dir():
                if "QLIC" not in os.environ and (_kx_dir / "kc.lic").exists():
                    os.environ["QLIC"] = str(_kx_dir)
                if "QHOME" not in os.environ and (_kx_dir / "q").is_dir():
                    os.environ["QHOME"] = str(_kx_dir / "q")
        for b in [f"{_uh}/.kx/bin", f"{_uh}/q/l64", f"{_uh}/q/bin", f"{_uh}/.local/bin", f"{_uh}/bin"]:
            if os.path.isdir(b) and b not in os.environ.get("PATH", "").split(":"):
                os.environ["PATH"] = f"{b}:{os.environ.get('PATH', '')}"

# Locate 'q' binary
Q_BIN = None
for _uh in _candidate_homes:
    kx_q = Path(_uh) / ".kx" / "bin" / "q"
    if kx_q.is_file() and os.access(kx_q, os.X_OK):
        Q_BIN = str(kx_q)
        break

if not Q_BIN:
    Q_BIN = shutil.which("q")
if not Q_BIN:
    for candidate in [
        str(Path.home() / ".kx" / "bin" / "q"),
        str(Path.home() / "q" / "l64" / "q"),
        str(Path.home() / ".local" / "bin" / "q"),
        "/home/ubuntu/.kx/bin/q",
        "/usr/local/bin/q",
        "/opt/kx/bin/q",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            Q_BIN = candidate
            break
if not Q_BIN:
    Q_BIN = "q"

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
PIDS_DIR = ROOT_DIR / ".pids"
LOGS_DIR = ROOT_DIR / "logs"

PIDS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

COMPONENTS = {
    "kdb": {
        "desc": "KDB+ Tickerplant (Port 5020)",
        "cmd": [Q_BIN, "kdb/tp.q", "-p", "5020"],
        "type": "Database",
        "match": f"{Q_BIN} kdb/tp.q",
    },
    "sub": {
        "desc": "Multicast Ingestion to KDB+",
        "cmd": ["python3", "-u", "kdb/multicast_sub.py"],
        "type": "Ingestion",
        "match": "python3 kdb/multicast_sub.py",
    },
    "engine": {
        "desc": "C++20 ULL Arbitrage Engine (AF_XDP Core)",
        "cmd": ["engine/bin/engine_main", "2"],
        "type": "C++ Engine",
        "match": "engine/bin/engine_main",
    },
    "cboe": {
        "desc": "CBOE Equity Options GW (SPY)",
        "cmd": ["python3", "-u", "gateways/cboe_opt_gw.py"],
        "type": "Equity Opt GW",
        "match": "python3 gateways/cboe_opt_gw.py",
    },
    "nasdaq": {
        "desc": "Nasdaq Options Market GW (SPY)",
        "cmd": ["python3", "-u", "gateways/nasdaq_opt_gw.py"],
        "type": "Equity Opt GW",
        "match": "python3 gateways/nasdaq_opt_gw.py",
    },
    "opra": {
        "desc": "OPRA Consolidated Options GW (SPY)",
        "cmd": ["python3", "-u", "gateways/opra_opt_gw.py"],
        "type": "Equity Opt GW",
        "match": "python3 gateways/opra_opt_gw.py",
    },
    "deribit": {
        "desc": "Deribit Options GW (BTC-PERPETUAL)",
        "cmd": ["python3", "-u", "gateways/deribit_gw.py"],
        "type": "Crypto Opt GW",
        "match": "python3 gateways/deribit_gw.py",
    },
    "okx": {
        "desc": "OKX Options GW (BTC-USD-SWAP)",
        "cmd": ["python3", "-u", "gateways/okx_gw.py"],
        "type": "Crypto Opt GW",
        "match": "python3 gateways/okx_gw.py",
    },
    "binance_opt": {
        "desc": "Binance Options GW (btcusdt@bookTicker)",
        "cmd": ["python3", "-u", "gateways/binance_opt_gw.py"],
        "type": "Crypto Opt GW",
        "match": "python3 gateways/binance_opt_gw.py",
    },
}

GATEWAYS = ["cboe", "nasdaq", "opra", "deribit", "okx", "binance_opt"]
ALL_COMPONENTS = ["kdb", "sub", "engine"] + GATEWAYS

# ANSI formatting
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def get_pid_file(name):
    return PIDS_DIR / f"{name}.pid"

def get_log_file(name):
    return LOGS_DIR / f"{name}.log"

def get_status(name):
    pid_file = get_pid_file(name)
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return True, pid
        except (ValueError, OSError):
            pid_file.unlink(missing_ok=True)
    return False, None

def start_component(name):
    cfg = COMPONENTS[name]
    running, pid = get_status(name)
    if running:
        print(f"  {CYAN}●{RESET} {name:<12} already running (PID {pid})")
        return True

    # Auto-compile C++ engine if binary is missing or source files have been modified
    if name == "engine":
        engine_bin = ROOT_DIR / "engine" / "bin" / "engine_main"
        needs_build = not engine_bin.exists()
        if not needs_build:
            bin_mtime = engine_bin.stat().st_mtime
            for p in (ROOT_DIR / "engine").rglob("*"):
                if p.suffix in (".cpp", ".c", ".h", ".hpp") or p.name == "Makefile":
                    if p.stat().st_mtime > bin_mtime:
                        needs_build = True
                        break
        if needs_build:
            print(f"  {CYAN}⚡ Building C++ engine (make -C engine)...{RESET}")
            res = subprocess.run(["make", "-C", str(ROOT_DIR / "engine")], capture_output=True, text=True)
            if res.returncode != 0:
                print(f"  {RED}✖ Engine compilation failed:{RESET}\n{res.stderr}")
                return False

    log_path = get_log_file(name)
    log_file = open(log_path, "a")

    try:
        proc = subprocess.Popen(
            cfg["cmd"],
            cwd=str(ROOT_DIR),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            start_new_session=True,
        )
        time.sleep(0.3)
        if proc.poll() is not None:
            print(f"  {RED}✖{RESET} {name:<12} failed to start (exit code {proc.returncode}). Check {log_path}")
            return False

        get_pid_file(name).write_text(str(proc.pid))
        print(f"  {GREEN}✔{RESET} {name:<12} started (PID {proc.pid}) -> {log_path.name}")
        return True
    except Exception as e:
        print(f"  {RED}✖{RESET} {name:<12} error: {e}")
        return False

def find_pids_by_match(match_str):
    pids = []
    try:
        res = subprocess.run(["pgrep", "-f", match_str], capture_output=True, text=True)
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                if line.isdigit():
                    pids.append(int(line))
    except Exception:
        pass
    return pids

def stop_component(name):
    cfg = COMPONENTS[name]
    running, pid = get_status(name)

    match_pids = find_pids_by_match(cfg["match"])
    all_pids = set(match_pids)
    if pid:
        all_pids.add(pid)

    # Filter out current Python control process PID if it matches
    all_pids.discard(os.getpid())

    if not all_pids:
        print(f"  {YELLOW}○{RESET} {name:<12} not running")
        get_pid_file(name).unlink(missing_ok=True)
        return True

    for p in all_pids:
        try:
            os.kill(p, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.1)
                try:
                    os.kill(p, 0)
                except OSError:
                    break
            else:
                os.kill(p, signal.SIGKILL)
        except OSError:
            pass

    print(f"  {GREEN}✔{RESET} {name:<12} stopped")
    get_pid_file(name).unlink(missing_ok=True)
    return True

def cmd_start(targets):
    if not targets or "all" in targets:
        print(f"{BOLD}Starting Entire Pipeline (KDB + Engine + 6 Live Options Gateways)...{RESET}")
        for c in ALL_COMPONENTS:
            start_component(c)
            if c in ["kdb", "engine"]:
                time.sleep(0.5)
    elif "gateways" in targets:
        print(f"{BOLD}Starting All 6 Options Gateways...{RESET}")
        for c in GATEWAYS:
            start_component(c)
    else:
        for t in targets:
            if t in COMPONENTS:
                start_component(t)
            else:
                print(f"{RED}Unknown component:{RESET} {t}")

def cmd_stop(targets):
    if not targets or "all" in targets:
        print(f"{BOLD}Stopping All Components...{RESET}")
        for c in reversed(ALL_COMPONENTS):
            stop_component(c)
    elif "gateways" in targets:
        print(f"{BOLD}Stopping All Gateways...{RESET}")
        for c in GATEWAYS:
            stop_component(c)
    else:
        for t in targets:
            if t in COMPONENTS:
                stop_component(t)
            else:
                print(f"{RED}Unknown component:{RESET} {t}")

def cmd_restart(targets):
    cmd_stop(targets)
    time.sleep(0.5)
    cmd_start(targets)

def cmd_status():
    print(f"\n{BOLD}{'COMPONENT':<14} {'TYPE':<16} {'STATUS':<12} {'PID':<8} {'DESCRIPTION'}{RESET}")
    print("─" * 75)
    all_ok = True
    for name, cfg in COMPONENTS.items():
        running, pid = get_status(name)
        if running:
            status_str = f"{GREEN}RUNNING{RESET}"
            pid_str = str(pid)
        else:
            status_str = f"{RED}STOPPED{RESET}"
            pid_str = "-"
            all_ok = False
        print(f"{name:<14} {cfg['type']:<16} {status_str:<21} {pid_str:<8} {cfg['desc']}")
    print("─" * 75)
    print(f"Overall Health: {GREEN if all_ok else YELLOW}{'HEALTHY - ALL RUNNING' if all_ok else 'PARTIAL'}{RESET}\n")

def load_quant_greeks():
    greeks = {}
    for fname, key in [('cboe_greeks.json', 'cboe'), ('opra_greeks.json', 'opra'), ('deribit_greeks.json', 'deribit')]:
        fpath = ROOT_DIR / 'gateways' / fname
        if fpath.exists():
            try:
                import json
                greeks[key] = json.loads(fpath.read_text())
            except Exception:
                pass
    return greeks

def load_engine_latency_stats():
    bench_file = ROOT_DIR / "logs" / "latency_benchmark.txt"
    if bench_file.exists():
        try:
            txt = bench_file.read_text()
            if "ULTRA-LOW-LATENCY PIPELINE BENCHMARK REPORT" in txt:
                report_part = txt.split("ULTRA-LOW-LATENCY PIPELINE BENCHMARK REPORT")[1].strip()
                return report_part
        except Exception:
            pass
    return None

def cmd_query():
    """Queries KDB+ and C++ engine to show live counts, cross-exchange prices, quant Greeks, and latency."""
    try:
        import numpy as np
        if not hasattr(np, 'string_'):
            np.string_ = np.bytes_
        from qpython import qconnection
        q = qconnection.QConnection(host='localhost', port=5020, timeout=3.0)
        q.open()
        
        opt_count = q('count OptBook')
        
        print(f"\n{BOLD}═══════════════════════════════════════════════════════════════════════════════════════{RESET}")
        print(f"       CROSS-VENUE ARBITRAGE, QUANT GREEKS & ULTRA-LOW-LATENCY ENGINE MATRIX           ")
        print(f"═══════════════════════════════════════════════════════════════════════════════════════")
        print(f" OptBook Ingested Ticks: {CYAN}{opt_count}{RESET} | Ingress Engine: {GREEN}AF_XDP (Kernel Bypass){RESET} | CPU Core: {GREEN}2 (Pinned){RESET}\n")
        
        greeks = load_quant_greeks()

        if opt_count > 0:
            # Query strictly filtered by contract symbol
            bids_btc_res = q('select last price, last size by exch from OptBook where side="B", sym like "BTC*"')
            asks_btc_res = q('select last price, last size by exch from OptBook where side="S", sym like "BTC*"')

            bids_spy_res = q('select last price, last size by exch from OptBook where side="B", sym like "SPY*"')
            asks_spy_res = q('select last price, last size by exch from OptBook where side="S", sym like "SPY*"')
            
            def parse_res(res):
                out_px = {}
                out_sz = {}
                for exch, row in res.items():
                    name = (exch[0] if hasattr(exch, '__getitem__') else exch)
                    name_str = name.decode() if hasattr(name, 'decode') else str(name)
                    out_px[name_str] = float(row[0])
                    out_sz[name_str] = int(row[1]) if len(row) > 1 else 0
                return out_px, out_sz

            bids_btc, sz_bids_btc = parse_res(bids_btc_res)
            asks_btc, sz_asks_btc = parse_res(asks_btc_res)

            bids_spy, sz_bids_spy = parse_res(bids_spy_res)
            asks_spy, sz_asks_spy = parse_res(asks_spy_res)

            def fmt_px(px, sz=None):
                if px is None:
                    return "--"
                sz_str = f" ({sz:,} sz)" if sz is not None and sz > 0 else ""
                return f"${px:,.2f}{sz_str}"

            def calc_diff(p1, p2):
                if p1 is not None and p2 is not None:
                    diff = abs(p1 - p2)
                    mid = (p1 + p2) / 2.0 if (p1 + p2) > 0 else 1.0
                    bps = (diff / mid) * 10000.0
                    return f"${diff:.2f} ({bps:.1f} bps)"
                return "--"

            def eval_crypto_arb(b_px, a_px, taker_fee_bps=2.5):
                if b_px is not None and a_px is not None:
                    gross = b_px - a_px
                    fee_est = (b_px + a_px) * (taker_fee_bps / 10000.0)
                    net = gross - fee_est
                    if gross > 0:
                        return f"{GREEN}[CROSS-VENUE ARBITRAGE: Gross +${gross:.2f} | Net +${net:.2f}]{RESET}"
                    return f"[Normal Market | Spread -${abs(gross):.2f}]"
                return "[Awaiting Feed]"

            # 1. Three BTC Options Cross-Venue Arbitrages
            print(f"{BOLD}[1] BTC OPTIONS: BTC-23SEP26-80000-C (Strike $80,000 Call){RESET}")
            d_bid, d_bid_sz = bids_btc.get('DERIBIT_OPT'), sz_bids_btc.get('DERIBIT_OPT')
            d_ask, d_ask_sz = asks_btc.get('DERIBIT_OPT'), sz_asks_btc.get('DERIBIT_OPT')
            o_bid, o_bid_sz = bids_btc.get('OKX_OPT'), sz_bids_btc.get('OKX_OPT')
            o_ask, o_ask_sz = asks_btc.get('OKX_OPT'), sz_asks_btc.get('OKX_OPT')
            b_bid, b_bid_sz = bids_btc.get('BINANCE_OPT'), sz_bids_btc.get('BINANCE_OPT')
            b_ask, b_ask_sz = asks_btc.get('BINANCE_OPT'), sz_asks_btc.get('BINANCE_OPT')

            print(f"  • DERIBIT: Bid {fmt_px(d_bid, d_bid_sz)} | Ask {fmt_px(d_ask, d_ask_sz)}")
            print(f"  • OKX:     Bid {fmt_px(o_bid, o_bid_sz)} | Ask {fmt_px(o_ask, o_ask_sz)}")
            print(f"  • BINANCE: Bid {fmt_px(b_bid, b_bid_sz)} | Ask {fmt_px(b_ask, b_ask_sz)}")
            print(f"  ─── 3 Cross-Venue Arbitrages (BTC Options) ───")
            print(f"  1. OKX vs DERIBIT: Bid Diff = {calc_diff(o_bid, d_bid)} | {eval_crypto_arb(o_bid, d_ask)}")
            print(f"  2. BINANCE vs OKX: Bid Diff = {calc_diff(b_bid, o_bid)} | {eval_crypto_arb(b_bid, o_ask)}")
            print(f"  3. BINANCE vs DERIBIT: Bid Diff = {calc_diff(b_bid, d_bid)} | {eval_crypto_arb(b_bid, d_ask)}")
            
            # Quantitative Greeks & Microstructure (BTC)
            dg = greeks.get('deribit', {})
            if dg:
                spot = dg.get('underlying_price', 86300.0)
                intrinsic = max(0.0, spot - 80000.0)
                print(f"  ─── Quant Options Microstructure (Deribit Derivatives Engine) ───")
                print(f"  • Underlying BTC Spot: ${spot:,.2f} | Intrinsic Value: ${intrinsic:,.2f}")
                print(f"  • Implied Vol (IV): {dg.get('iv', 0.0):.2f}% | Delta (Δ): {dg.get('delta', 0.0):.4f} | Gamma (Γ): {dg.get('gamma', 0.0):.4f}")
                print(f"  • Vega (ν): {dg.get('vega', 0.0):.4f} | Theta (Θ): ${dg.get('theta', 0.0):.2f}/day\n")
            else:
                print()

            # 2. Three Equity Options Cross-Venue Spreads
            print(f"{BOLD}[2] EQUITY OPTIONS: SPY260923C00791000 (SPY Strike $791.00 Call){RESET}")
            c_bid, c_bid_sz = bids_spy.get('CBOE_OPT'), sz_bids_spy.get('CBOE_OPT')
            c_ask, c_ask_sz = asks_spy.get('CBOE_OPT'), sz_asks_spy.get('CBOE_OPT')
            n_bid, n_bid_sz = bids_spy.get('NASDAQ_OPT'), sz_bids_spy.get('NASDAQ_OPT')
            n_ask, n_ask_sz = asks_spy.get('NASDAQ_OPT'), sz_asks_spy.get('NASDAQ_OPT')
            p_bid, p_bid_sz = bids_spy.get('OPRA_OPT'), sz_bids_spy.get('OPRA_OPT')
            p_ask, p_ask_sz = asks_spy.get('OPRA_OPT'), sz_asks_spy.get('OPRA_OPT')

            print(f"  • CBOE:    Bid {fmt_px(c_bid, c_bid_sz)} | Ask {fmt_px(c_ask, c_ask_sz)}")
            print(f"  • NASDAQ:  Bid {fmt_px(n_bid, n_bid_sz)} | Ask {fmt_px(n_ask, n_ask_sz)}")
            print(f"  • OPRA:    Bid {fmt_px(p_bid, p_bid_sz)} | Ask {fmt_px(p_ask, p_ask_sz)}")
            print(f"  ─── 3 Cross-Venue Bid-Ask Spreads (Equity Options) ───")
            print(f"  1. CBOE vs NASDAQ: NBBO Bid Spread = {calc_diff(c_bid, n_bid)} | Ask Spread = {calc_diff(c_ask, n_ask)}")
            print(f"  2. NASDAQ vs OPRA: NBBO Bid Spread = {calc_diff(n_bid, p_bid)} | Ask Spread = {calc_diff(n_ask, p_ask)}")
            print(f"  3. CBOE vs OPRA:   NBBO Bid Spread = {calc_diff(c_bid, p_bid)} | Ask Spread = {calc_diff(c_ask, p_ask)}")

            # Quantitative Greeks & Microstructure (Equity)
            cg = greeks.get('cboe', {})
            og = greeks.get('opra', {})
            if cg or og:
                print(f"  ─── Quant Options Microstructure (CBOE & OPRA Institutional Feeds) ───")
                if cg:
                    print(f"  • CBOE IV: {cg.get('iv', 0.0)*100:.2f}% | Theo Price: ${cg.get('theo', 0.0):.4f} | Volume: {cg.get('volume', 0):,.0f} | OI: {cg.get('open_interest', 0):,.0f}")
                    print(f"  • CBOE Greeks: Delta (Δ): {cg.get('delta', 0.0):.4f} | Gamma (Γ): {cg.get('gamma', 0.0):.4f} | Vega (ν): {cg.get('vega', 0.0):.4f} | Theta (Θ): {cg.get('theta', 0.0):.4f}")
                if og:
                    print(f"  • OPRA Consolidated IV: {og.get('iv', 0.0)*100:.2f}% | Consolidated Volume: {og.get('volume', 0):,.0f}")
                print()

            # 3. Hardware Latency Profile
            lat_stats = load_engine_latency_stats()
            if lat_stats:
                print(f"{BOLD}[3] ULTRA-LOW-LATENCY PIPELINE PERFORMANCE (ARM64 cntvct_el0 Cycle Timers){RESET}")
                lines = lat_stats.splitlines()
                # Print stage breakdown cleanly
                for line in lines:
                    if any(k in line for k in ["Hardware Timer", "Stage", "1. Packet", "2. Zero", "3. L2", "4. Arb", "END-TO-END", "Total Packets"]):
                        print(f"  {line}")
                print(f"═══════════════════════════════════════════════════════════════════════════════════════\n")

        q.close()
    except Exception as e:
        print(f"{RED}Could not query KDB+ on port 5020:{RESET} {e}")

HELP_TEXT = f"""{BOLD}NAME{RESET}
    start.sh - Ultra-Low-Latency Arbitrage Infrastructure & Trading Terminal

{BOLD}SYNOPSIS{RESET}
    {BOLD}./start.sh{RESET} [{CYAN}OPTION{RESET}] [{YELLOW}TARGETS...{RESET}]

{BOLD}DESCRIPTION{RESET}
    Central control interface and Bloomberg-style institutional trading terminal
    for the ultra-low-latency cross-venue equity & crypto options arbitrage system.

    Running {BOLD}./start.sh{RESET} with no options launches the interactive Bloomberg TUI.

{BOLD}OPTIONS{RESET}
    {CYAN}--tui{RESET}                  Launch full-scale Bloomberg-style dual-pane TUI monitor (default)
    {CYAN}--select{RESET}               Launch interactive options contract discovery & selector in TUI
    {CYAN}--no-select{RESET}            Launch TUI directly into trading books (skipping contract selector)
    {CYAN}--status{RESET}               Show live status, PIDs, and health dashboard of all components
    {CYAN}--start{RESET} [{YELLOW}TARGET...{RESET}]    Start components (default: all)
    {CYAN}--stop{RESET} [{YELLOW}TARGET...{RESET}]     Stop components (default: all)
    {CYAN}--restart{RESET} [{YELLOW}TARGET...{RESET}]  Restart components (default: all)
    {CYAN}--query{RESET}                Query live KDB+ tick counts, cross-exchange prices & Greeks
    {CYAN}--benchmark{RESET}            Display cycle-accurate hardware latency benchmarks (TSC/rdtsc)
    {CYAN}--monitor{RESET}              Continuously stream real-time cross-venue arbitrage matrix
    {CYAN}-h, --help{RESET}             Display this help manual and exit

{BOLD}COMPONENTS{RESET}
    {YELLOW}all{RESET}                 All services (tickerplant, subscriber, engine, gateways)
    {YELLOW}gateways{RESET}            All 6 exchange gateways (cboe, nasdaq, opra, deribit, okx, binance_opt)
    {YELLOW}tickerplant{RESET}         KDB+ tick database & feed handler (port 5020)
    {YELLOW}subscriber{RESET}          Multicast receiver & KDB+ ingest daemon
    {YELLOW}engine{RESET}              C++20 lock-free arbitrage execution engine
    {YELLOW}cboe{RESET}                CBOE S&P 500 options binary market data gateway (UDP 5000)
    {YELLOW}nasdaq{RESET}              NASDAQ ITCH options binary gateway (UDP 5001)
    {YELLOW}opra{RESET}                OPRA national market system options gateway (UDP 5002)
    {YELLOW}deribit{RESET}             Deribit crypto options gateway (UDP 5003)
    {YELLOW}okx{RESET}                 OKX crypto options gateway (UDP 5004)
    {YELLOW}binance_opt{RESET}         Binance crypto options gateway (UDP 5005)

{BOLD}EXAMPLES{RESET}
    ./start.sh                  # Launch Bloomberg terminal TUI (default)
    ./start.sh --status         # Check health and PIDs of all components
    ./start.sh --restart all    # Restart entire pipeline
    ./start.sh --start gateways # Start all 6 options gateways
    ./start.sh --benchmark      # View nanosecond cycle-accurate engine benchmarks
    ./start.sh --query          # Query KDB+ cross-venue quote snapshots
"""

def cmd_benchmark():
    """Displays latest hardware latency benchmarks from the C++ engine."""
    engine_log = ROOT_DIR / "logs" / "engine.log"
    bench_file = ROOT_DIR / "logs" / "latency_benchmark.txt"

    if bench_file.exists():
        print(bench_file.read_text())
    elif engine_log.exists():
        content = engine_log.read_text(encoding='utf-8', errors='replace')
        blocks = content.split("CROSS-VENUE ARBITRAGE & BID-ASK SPREAD ENGINE MATRIX")
        if len(blocks) > 1:
            print(blocks[-1].strip())
    else:
        print(f"{YELLOW}Engine is collecting cycles... run `./start.sh --start engine` and check again.{RESET}")

def cmd_monitor():
    """Continuously monitors cross-venue arbitrage matrix and streams updates in real time."""
    print(f"{CYAN}Starting real-time live arbitrage monitor. Press Ctrl+C to stop...{RESET}")
    try:
        while True:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{BOLD}LIVE STREAMING ENGINE MONITOR — {now_str}{RESET}")
            cmd_query()
            time.sleep(1.0)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Stopped live streaming monitor.{RESET}")

def cmd_tui(extra_args=None):
    """Launches full-scale Bloomberg terminal TUI dual-pane interface."""
    import bloomberg_tui
    start_in_sel = True
    if extra_args and "--no-select" in extra_args:
        start_in_sel = False
    bloomberg_tui.run_tui(start_in_select=start_in_sel)

def cmd_select(extra_args=None):
    """Launches interactive options contract discovery and dynamic selector inside TUI."""
    import bloomberg_tui
    bloomberg_tui.run_tui(start_in_select=True)

def main():
    args = sys.argv[1:]

    # Default action: no arguments launches Bloomberg TUI directly
    if not args:
        cmd_tui()
        return

    first = args[0]

    # Standard Help display
    if first in ("-h", "--help", "help"):
        print(HELP_TEXT)
        return

    # Handle --start=target or --stop=target syntax
    target_from_equals = []
    if "=" in first:
        opt_key, opt_val = first.split("=", 1)
        first = opt_key
        if opt_val:
            target_from_equals = [opt_val]

    # Command dispatch supporting both standard --flags and legacy commands
    if first in ("--tui", "tui"):
        cmd_tui(args[1:])
    elif first == "--no-select":
        cmd_tui(["--no-select"] + args[1:])
    elif first in ("--select", "select"):
        cmd_select(args[1:])
    elif first in ("--status", "status"):
        cmd_status()
    elif first in ("--start", "start"):
        targets = target_from_equals or (args[1:] if len(args) > 1 else ["all"])
        cmd_start(targets)
    elif first in ("--stop", "stop"):
        targets = target_from_equals or (args[1:] if len(args) > 1 else ["all"])
        cmd_stop(targets)
    elif first in ("--restart", "restart"):
        targets = target_from_equals or (args[1:] if len(args) > 1 else ["all"])
        cmd_restart(targets)
    elif first in ("--query", "query"):
        cmd_query()
    elif first in ("--benchmark", "benchmark"):
        cmd_benchmark()
    elif first in ("--monitor", "monitor"):
        cmd_monitor()
    else:
        sys.stderr.write(f"./start.sh: unrecognized option '{first}'\nRun './start.sh --help' for available options.\n")
        sys.exit(1)

if __name__ == "__main__":
    main()

