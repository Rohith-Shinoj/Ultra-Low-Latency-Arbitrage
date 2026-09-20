#!/usr/bin/env python3
"""
Central Gateway & Pipeline Controller for Ultra-Low-Latency Arbitrage Infrastructure.
Manages background processes, logging, health monitoring, and live KDB+ queries.
"""

import sys
import os
import time
import signal
import subprocess
import argparse
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parent.parent
PIDS_DIR = ROOT_DIR / ".pids"
LOGS_DIR = ROOT_DIR / "logs"

PIDS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

COMPONENTS = {
    "kdb": {
        "desc": "KDB+ Tickerplant (Port 5020)",
        "cmd": ["q", "kdb/tp.q", "-p", "5020"],
        "type": "Database",
        "match": "q kdb/tp.q",
    },
    "sub": {
        "desc": "Multicast Subscriber & Ingestion",
        "cmd": ["python3", "-u", "kdb/multicast_sub.py"],
        "type": "Ingestion",
        "match": "python3 kdb/multicast_sub.py",
    },
    "binance": {
        "desc": "Binance Spot Gateway (ITCH)",
        "cmd": ["python3", "-u", "gateways/binance_gw.py"],
        "type": "Spot GW",
        "match": "python3 gateways/binance_gw.py",
    },
    "coinbase": {
        "desc": "Coinbase Spot Gateway (ITCH)",
        "cmd": ["python3", "-u", "gateways/coinbase_gw.py"],
        "type": "Spot GW",
        "match": "python3 gateways/coinbase_gw.py",
    },
    "kraken": {
        "desc": "Kraken Spot Gateway (ITCH)",
        "cmd": ["python3", "-u", "gateways/kraken_gw.py"],
        "type": "Spot GW",
        "match": "python3 gateways/kraken_gw.py",
    },
    "deribit": {
        "desc": "Deribit Options/Derivatives Gateway (SBE)",
        "cmd": ["python3", "-u", "gateways/deribit_gw.py"],
        "type": "Options GW",
        "match": "python3 gateways/deribit_gw.py",
    },
    "okx": {
        "desc": "OKX Options/Swap Gateway (SBE)",
        "cmd": ["python3", "-u", "gateways/okx_gw.py"],
        "type": "Options GW",
        "match": "python3 gateways/okx_gw.py",
    },
    "binance_opt": {
        "desc": "Binance Futures/Options GW (SBE)",
        "cmd": ["python3", "-u", "gateways/binance_opt_gw.py"],
        "type": "Options GW",
        "match": "python3 gateways/binance_opt_gw.py",
    },
}

GATEWAYS = ["binance", "coinbase", "kraken", "deribit", "okx", "binance_opt"]
ALL_COMPONENTS = ["kdb", "sub"] + GATEWAYS

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

def find_system_pid(match_str):
    """Finds running process matching substring in cmdline."""
    try:
        output = subprocess.check_output(["pgrep", "-f", match_str], stderr=subprocess.DEVNULL)
        pids = [int(p) for p in output.decode().strip().split() if int(p) != os.getpid()]
        return pids[0] if pids else None
    except Exception:
        return None

def get_status(name):
    """Returns (is_running, pid) for a component."""
    pid_file = get_pid_file(name)
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return True, pid
        except (ValueError, OSError):
            pid_file.unlink(missing_ok=True)
            pid = None

    # Fallback to system process check
    match = COMPONENTS[name]["match"]
    sys_pid = find_system_pid(match)
    if sys_pid:
        pid_file.write_text(str(sys_pid))
        return True, sys_pid

    return False, None

def start_component(name):
    cfg = COMPONENTS[name]
    running, pid = get_status(name)
    if running:
        print(f"  {CYAN}●{RESET} {name:<12} already running (PID {pid})")
        return True

    log_path = get_log_file(name)
    log_file = open(log_path, "a")

    try:
        proc = subprocess.Popen(
            cfg["cmd"],
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
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

def stop_component(name):
    running, pid = get_status(name)
    if not running:
        print(f"  {YELLOW}○{RESET} {name:<12} is not running")
        get_pid_file(name).unlink(missing_ok=True)
        return True

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            os.kill(pid, signal.SIGKILL)
        print(f"  {RED}■{RESET} {name:<12} stopped (PID {pid})")
    except OSError as e:
        print(f"  {YELLOW}○{RESET} {name:<12} stopped with error: {e}")

    get_pid_file(name).unlink(missing_ok=True)
    return True

def cmd_start(targets):
    if not targets or "all" in targets:
        # Start in logical order: kdb -> sub -> gateways
        print(f"{BOLD}Starting All Components...{RESET}")
        for c in ALL_COMPONENTS:
            start_component(c)
    elif "gateways" in targets:
        print(f"{BOLD}Starting All Gateways...{RESET}")
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
        for leg in ["spot_gw.py", "cboe_opt_gw.py", "binance_gw.py", "coinbase_gw.py", "kraken_gw.py", "deribit_gw.py", "okx_gw.py", "binance_opt_gw.py"]:
            subprocess.run(["pkill", "-9", "-f", leg], stderr=subprocess.DEVNULL)
    elif "gateways" in targets:
        print(f"{BOLD}Stopping All Gateways...{RESET}")
        for c in GATEWAYS:
            stop_component(c)
        for leg in ["spot_gw.py", "cboe_opt_gw.py", "binance_gw.py", "coinbase_gw.py", "kraken_gw.py", "deribit_gw.py", "okx_gw.py", "binance_opt_gw.py"]:
            subprocess.run(["pkill", "-9", "-f", leg], stderr=subprocess.DEVNULL)
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
    for name in ALL_COMPONENTS:
        cfg = COMPONENTS[name]
        running, pid = get_status(name)
        status_str = f"{GREEN}RUNNING{RESET}" if running else f"{RED}STOPPED{RESET}"
        pid_str = str(pid) if pid else "—"
        print(f"{BOLD}{name:<14}{RESET} {cfg['type']:<16} {status_str:<21} {pid_str:<8} {cfg['desc']}")
    print("─" * 75 + "\n")

def format_kdb_timestamp(raw_time_ns):
    """Converts KDB int64 nanoseconds (epoch 2000-01-01) to HH:MM:SS.nnnnnnnnn."""
    try:
        import numpy as np
        kdb_epoch = np.datetime64('2000-01-01T00:00:00.000000000', 'ns')
        dt = kdb_epoch + np.timedelta64(int(raw_time_ns), 'ns')
        parts = str(dt).split('T')
        return parts[1] if len(parts) > 1 else str(raw_time_ns)
    except Exception:
        return str(raw_time_ns)

def get_backward_aligned_spot(q):
    """
    Backward Time-Alignment Matching:
    1. Pick the latest trade from KRAKEN (the slowest/anchor feed).
    2. Pick the trade on COINBASE closest in time to Kraken's timestamp.
    3. Pick the trade on BINANCE closest in time to Coinbase's timestamp.
    """
    counts = q('select count i by exch from SpotBook')
    tick_counts = {}
    for exch, row in counts.items():
        val = exch[0] if hasattr(exch, '__getitem__') else exch
        name = val.decode() if hasattr(val, 'decode') else str(val)
        tick_counts[name] = int(row[0])

    if tick_counts.get('KRAKEN', 0) > 0 and tick_counts.get('COINBASE', 0) > 0 and tick_counts.get('BINANCE', 0) > 0:
        # Anchor: Kraken latest tick
        k_res = q('select from SpotBook where exch=`KRAKEN')
        k_times = [int(t) for t in k_res['time']]
        k_prices = [float(p) for p in k_res['price']]
        k_time = k_times[-1]
        k_px = k_prices[-1]

        # Step 2: Pick closest Binance tick to Kraken's timestamp (Fastest feed -> smallest delta)
        bn_res = q('select from SpotBook where exch=`BINANCE')
        bn_times = [int(t) for t in bn_res['time']]
        bn_prices = [float(p) for p in bn_res['price']]
        bn_idx = min(range(len(bn_times)), key=lambda i: abs(bn_times[i] - k_time))
        bn_time = bn_times[bn_idx]
        bn_px = bn_prices[bn_idx]

        # Step 3: Pick closest Coinbase tick to Kraken's timestamp
        cb_res = q('select from SpotBook where exch=`COINBASE')
        cb_times = [int(t) for t in cb_res['time']]
        cb_prices = [float(p) for p in cb_res['price']]
        cb_idx = min(range(len(cb_times)), key=lambda i: abs(cb_times[i] - k_time))
        cb_time = cb_times[cb_idx]
        cb_px = cb_prices[cb_idx]

        aligned = [
            ('KRAKEN', k_px, tick_counts['KRAKEN'], k_time, "[Anchor / Slowest]"),
            ('BINANCE', bn_px, tick_counts['BINANCE'], bn_time, f"Δ {((bn_time - k_time)/1e6):+.2f} ms (Fastest Match)"),
            ('COINBASE', cb_px, tick_counts['COINBASE'], cb_time, f"Δ {((cb_time - k_time)/1e6):+.2f} ms"),
        ]
        return aligned
    else:
        # Fallback if any exchange has no ticks yet
        res = q('select last time, last price, count i by exch from SpotBook')
        aligned = []
        for exch, row in res.items():
            val = exch[0] if hasattr(exch, '__getitem__') else exch
            name = val.decode() if hasattr(val, 'decode') else str(val)
            aligned.append((name, float(row[1]), int(row[2]), int(row[0]), "[Latest]"))
        return aligned

def cmd_query():
    """Queries KDB+ directly to show live counts and cross-exchange prices."""
    try:
        from qpython import qconnection
        q = qconnection.QConnection(host='localhost', port=5020, timeout=3.0)
        q.open()
        
        spot_count = q('count SpotBook')
        opt_count = q('count OptBook')
        
        print(f"\n{BOLD}═══════════════════ LIVE KDB+ MARKET DATA ═══════════════════{RESET}")
        print(f" SpotBook Total Rows: {GREEN}{spot_count}{RESET} | OptBook Total Rows: {CYAN}{opt_count}{RESET}\n")
        
        if spot_count > 0:
            print(f"{BOLD}Latest Spot Prices Across Exchanges (Cross-Exchange Arbitrage):{RESET}")
            res = q('select last time, last price, count i by exch from SpotBook')
            print(f"{'EXCHANGE':<12} {'LATEST PRICE':<14} {'TOTAL TICKS':<12} {'LAST TIME (UTC + NS)'}")
            print("─" * 70)
            spot_prices = {}
            spot_times = {}
            for exch, row in res.items():
                val = exch[0] if hasattr(exch, '__getitem__') else exch
                exch_name = val.decode() if hasattr(val, 'decode') else str(val)
                raw_time = int(row[0])
                time_str = format_kdb_timestamp(raw_time)
                spot_times[exch_name] = raw_time
                px = float(row[1])
                spot_prices[exch_name] = px
                last_px = f"${px:,.2f}"
                ticks = str(row[2])
                print(f"{BOLD}{exch_name:<12}{RESET} {GREEN}{last_px:<14}{RESET} {ticks:<12} {time_str}")
            print("─" * 70)
            if len(spot_prices) >= 2:
                max_exch = max(spot_prices, key=spot_prices.get)
                min_exch = min(spot_prices, key=spot_prices.get)
                diff = spot_prices[max_exch] - spot_prices[min_exch]
                bps = (diff / spot_prices[min_exch]) * 10000
                print(f"  {YELLOW}▶ Cross-Exchange Spread:{RESET} ${diff:,.2f} ({bps:.1f} bps)")
            if len(spot_times) >= 2:
                max_t = max(spot_times.values())
                min_t = min(spot_times.values())
                delta_ns = max_t - min_t
                if delta_ns < 1000:
                    delta_str = f"{delta_ns:,} ns ({delta_ns/1000.0:.3f} µs)"
                elif delta_ns < 1_000_000:
                    delta_str = f"{delta_ns:,} ns ({delta_ns/1000.0:.2f} µs)"
                else:
                    delta_str = f"{delta_ns:,} ns ({delta_ns/1_000_000.0:.2f} ms)"
                print(f"  {YELLOW}▶ Cross-Exchange Latency Dispersion:{RESET} {delta_str}\n")
        
        if opt_count > 0:
            print(f"{BOLD}Latest Derivatives / Options Prices Across Exchanges (Cross-Exchange Arbitrage):{RESET}")
            res = q('select last sym, last time, last price, count i by exch from OptBook')
            print(f"{'EXCHANGE':<12} {'CONTRACT':<14} {'LATEST PRICE':<14} {'TOTAL TICKS':<12} {'LAST TIME (UTC + NS)'}")
            print("─" * 77)
            opt_prices = {}
            opt_times = {}
            contract_name = ""
            for exch, row in res.items():
                val = exch[0] if hasattr(exch, '__getitem__') else exch
                exch_name = val.decode() if hasattr(val, 'decode') else str(val)
                sym_raw = row[0]
                contract_name = sym_raw.decode() if hasattr(sym_raw, 'decode') else str(sym_raw)
                raw_time = int(row[1])
                time_str = format_kdb_timestamp(raw_time)
                opt_times[exch_name] = raw_time
                px = float(row[2])
                opt_prices[exch_name] = px
                last_px = f"${px:,.2f}"
                ticks = str(row[3])
                print(f"{BOLD}{exch_name:<12}{RESET} {contract_name:<14} {CYAN}{last_px:<14}{RESET} {ticks:<12} {time_str}")
            print("─" * 77)
            if len(opt_prices) >= 2:
                max_exch = max(opt_prices, key=opt_prices.get)
                min_exch = min(opt_prices, key=opt_prices.get)
                diff = opt_prices[max_exch] - opt_prices[min_exch]
                pct = (diff / opt_prices[min_exch]) * 100 if opt_prices[min_exch] > 0 else 0
                print(f"  {YELLOW}▶ Cross-Venue Arbitrage Spread:{RESET} ${diff:,.2f} ({pct:.1f}%)")
            if len(opt_times) >= 2:
                max_t = max(opt_times.values())
                min_t = min(opt_times.values())
                delta_ns = max_t - min_t
                if delta_ns < 1000:
                    delta_str = f"{delta_ns:,} ns ({delta_ns/1000.0:.3f} µs)"
                elif delta_ns < 1_000_000:
                    delta_str = f"{delta_ns:,} ns ({delta_ns/1000.0:.2f} µs)"
                else:
                    delta_str = f"{delta_ns:,} ns ({delta_ns/1_000_000.0:.2f} ms)"
                print(f"  {YELLOW}▶ Cross-Venue Latency Dispersion:{RESET} {delta_str}\n")

        q.close()
        print()
    except Exception as e:
        print(f"{RED}Could not query KDB+ on port 5020:{RESET} {e}")

def main():
    parser = argparse.ArgumentParser(description="Central Gateway & Arbitrage Infrastructure Controller")
    subparsers = parser.add_subparsers(dest="action", help="Action to perform")

    p_start = subparsers.add_parser("start", help="Start components (all, gateways, or specific name)")
    p_start.add_argument("targets", nargs="*", default=["all"])

    p_stop = subparsers.add_parser("stop", help="Stop components (all, gateways, or specific name)")
    p_stop.add_argument("targets", nargs="*", default=["all"])

    p_restart = subparsers.add_parser("restart", help="Restart components")
    p_restart.add_argument("targets", nargs="*", default=["all"])

    subparsers.add_parser("status", help="Show dashboard status of all components")
    subparsers.add_parser("query", help="Show live KDB+ table counts and cross-exchange prices")

    args = parser.parse_args()

    if args.action == "start":
        cmd_start(args.targets)
    elif args.action == "stop":
        cmd_stop(args.targets)
    elif args.action == "restart":
        cmd_restart(args.targets)
    elif args.action == "status":
        cmd_status()
    elif args.action == "query":
        cmd_query()
    else:
        cmd_status()

if __name__ == "__main__":
    main()
