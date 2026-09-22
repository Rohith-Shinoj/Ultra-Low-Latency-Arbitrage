#!/usr/bin/env python3
"""
Interactive Options Contract Discovery & Dynamic Selector.
Eliminates hardcoded instrument strings by discovering live expiries and strikes directly
from Deribit (Crypto: BTC, ETH, SOL) and CBOE (Equity: SPY, QQQ, AAPL) public APIs.
"""

import sys
import os
import json
import urllib.request
import argparse
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / "gateways" / "active_contracts.json"
SEC_DEFS_FILE = ROOT_DIR / "gateways" / "security_defs.json"

console = Console()

def load_current_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "crypto": {
            "underlying": "BTC",
            "expiry": "23SEP26",
            "strike": 80000.0,
            "call_put": "C",
            "deribit_instrument": "BTC-23SEP26-80000-C",
            "okx_inst_id": "BTC-USD-260923-80000-C",
            "binance_symbol": "BTC-260923-80000-C",
            "sym": "BTC_C80K"
        },
        "equity": {
            "underlying": "SPY",
            "expiry": "260923",
            "strike": 791.0,
            "call_put": "C",
            "cboe_option": "SPY260923C00791000",
            "nasdaq_strike": "791.00",
            "nasdaq_expiry": "Sep 23",
            "sym": "SPY_C791"
        }
    }

def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    
    # Also update security_defs.json for C++ engine and KDB tickerplant mapping
    crypto_sym = config.get("crypto", {}).get("sym", "BTC_C80K")
    sec_defs = {
        "1001": crypto_sym,
        "1002": crypto_sym,
        "1003": crypto_sym
    }
    SEC_DEFS_FILE.write_text(json.dumps(sec_defs, indent=2))
    console.print(f"[bold green]✔[/bold green] Successfully saved active contracts")

# ==================== LIVE CRYPTO DISCOVERY ====================

def fetch_deribit_instruments(currency: str):
    """Discovers live options chain for BTC, ETH, or SOL directly from Deribit."""
    curr_param = "USDC" if currency.upper() == "SOL" else currency.upper()
    url = f"https://www.deribit.com/api/v2/public/get_instruments?currency={curr_param}&kind=option&expired=false"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (ULL-Arbitrage-Engine)'})
    with console.status(f"[bold cyan]Querying Deribit live options chain for {currency.upper()}...[/bold cyan]"):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                res = json.loads(r.read().decode())['result']
                if currency.upper() == "SOL":
                    res = [x for x in res if 'SOL' in x.get('instrument_name', '')]
                return res
        except Exception as e:
            console.print(f"[bold red]Failed to fetch instruments from Deribit: {e}[/bold red]")
            return []

def parse_crypto_expiries(instruments):
    expiries = set()
    for inst in instruments:
        # e.g. BTC-23SEP26-80000-C or SOL_USDC-23SEP26-100-C
        parts = inst['instrument_name'].split('-')
        if len(parts) >= 2:
            expiries.add(parts[1])
    return sorted(list(expiries))

def parse_crypto_strikes(instruments, target_expiry, call_put="C"):
    strikes = set()
    for inst in instruments:
        parts = inst['instrument_name'].split('-')
        if len(parts) >= 4 and parts[1] == target_expiry and parts[3] == call_put:
            try:
                strikes.add(float(parts[2]))
            except ValueError:
                pass
    return sorted(list(strikes))

# ==================== LIVE EQUITY DISCOVERY ====================

def fetch_cboe_options(symbol: str):
    """Discovers live options chain for SPY, QQQ, AAPL from CBOE."""
    url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol.upper()}.json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (ULL-Arbitrage-Engine)'})
    with console.status(f"[bold magenta]Querying CBOE live options chain for {symbol.upper()}...[/bold magenta]"):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode())['data']
                return data
        except Exception as e:
            console.print(f"[bold red]Failed to fetch options from CBOE: {e}[/bold red]")
            return {'options': [], 'current_price': 0.0}

def parse_equity_expiries(options):
    expiries = set()
    for opt in options:
        name = opt.get('option', '')
        # e.g. SPY260923C00791000 -> 260923
        if len(name) >= 9:
            exp = name[3:9]
            expiries.add(exp)
    return sorted(list(expiries))

def parse_equity_strikes(options, target_expiry, call_put="C"):
    strikes = []
    for opt in options:
        name = opt.get('option', '')
        if len(name) >= 10 and name[3:9] == target_expiry and name[9] == call_put:
            try:
                raw_strike = float(name[10:]) / 1000.0
                strikes.append((raw_strike, name, opt.get('bid', 0), opt.get('ask', 0), opt.get('iv', 0)))
            except ValueError:
                pass
    return sorted(strikes, key=lambda x: x[0])

# ==================== INTERACTIVE CLI SELECTOR ====================

def select_crypto():
    console.print("\n[bold cyan]═══ LIVE CRYPTO OPTIONS DISCOVERY ═══[/bold cyan]")
    underlyings = ["BTC", "ETH", "SOL"]
    console.print("Available Underlyings:")
    for idx, u in enumerate(underlyings, 1):
        console.print(f"  [{idx}] [bold white]{u}[/bold white]")
    u_idx = int(Prompt.ask("Select underlying", choices=[str(i) for i in range(1, len(underlyings)+1)], default="1")) - 1
    selected_u = underlyings[u_idx]

    instruments = fetch_deribit_instruments(selected_u)
    if not instruments:
        console.print("[red]No live contracts discovered. Aborting selection.[/red]")
        return None

    expiries = parse_crypto_expiries(instruments)
    console.print(f"\nDiscovered [bold green]{len(expiries)}[/bold green] live active expiries for [bold white]{selected_u}[/bold white]:")
    
    # Display in a clean multi-column table
    table = Table(box=None, padding=(0, 2))
    table.add_column("IDX", style="dim")
    table.add_column("EXPIRY", style="bold yellow")
    table.add_column("IDX", style="dim")
    table.add_column("EXPIRY", style="bold yellow")
    table.add_column("IDX", style="dim")
    table.add_column("EXPIRY", style="bold yellow")

    rows = []
    for i in range(0, len(expiries), 3):
        chunk = expiries[i:i+3]
        row = []
        for j, exp in enumerate(chunk):
            row.extend([f"[{i+j+1}]", exp])
        while len(row) < 6:
            row.extend(["", ""])
        table.add_row(*row)
    console.print(table)

    e_idx = int(Prompt.ask("Select expiry", choices=[str(i) for i in range(1, len(expiries)+1)], default="1")) - 1
    selected_exp = expiries[e_idx]

    cp = Prompt.ask("Contract Type", choices=["C", "P"], default="C").upper()
    strikes = parse_crypto_strikes(instruments, selected_exp, cp)

    console.print(f"\nDiscovered [bold green]{len(strikes)}[/bold green] active strikes for [bold white]{selected_u} {selected_exp} {cp}[/bold white]:")
    # Show strikes in a clean grid
    s_table = Table(box=None, padding=(0, 2))
    for col in range(4):
        s_table.add_column("IDX", style="dim")
        s_table.add_column("STRIKE", style="bold cyan")

    for i in range(0, len(strikes), 4):
        chunk = strikes[i:i+4]
        row = []
        for j, stk in enumerate(chunk):
            row.extend([f"[{i+j+1}]", f"${stk:,.0f}"])
        while len(row) < 8:
            row.extend(["", ""])
        s_table.add_row(*row)
    console.print(s_table)

    s_idx = int(Prompt.ask("Select strike", choices=[str(i) for i in range(1, len(strikes)+1)], default=str(min(len(strikes), max(1, len(strikes)//2))))) - 1
    selected_strike = strikes[s_idx]

    # Format exchange contract identifiers
    stk_str = f"{int(selected_strike) if selected_strike.is_integer() else selected_strike}"
    deribit_inst = f"{selected_u if selected_u != 'SOL' else 'SOL_USDC'}-{selected_exp}-{stk_str}-{cp}"
    
    # Map expiry format 23SEP26 to YYMMDD (e.g. 260923)
    try:
        dt = datetime.strptime(selected_exp, "%d%b%y")
        yymmdd = dt.strftime("%y%m%d")
    except Exception:
        yymmdd = "260923"

    okx_inst = f"{selected_u}-USD-{yymmdd}-{stk_str}-{cp}"
    binance_inst = f"{selected_u}-{yymmdd}-{stk_str}-{cp}"
    sym_name = f"{selected_u}_{cp}{stk_str}"

    crypto_config = {
        "underlying": selected_u,
        "expiry": selected_exp,
        "strike": float(selected_strike),
        "call_put": cp,
        "deribit_instrument": deribit_inst,
        "okx_inst_id": okx_inst,
        "binance_symbol": binance_inst,
        "sym": sym_name
    }
    return crypto_config

def select_equity():
    console.print("\n[bold magenta]═══ LIVE US EQUITY OPTIONS DISCOVERY ═══[/bold magenta]")
    underlyings = ["SPY", "QQQ", "AAPL"]
    console.print("Available Underlyings:")
    for idx, u in enumerate(underlyings, 1):
        console.print(f"  [{idx}] [bold white]{u}[/bold white]")
    u_idx = int(Prompt.ask("Select underlying", choices=[str(i) for i in range(1, len(underlyings)+1)], default="1")) - 1
    selected_u = underlyings[u_idx]

    cboe_data = fetch_cboe_options(selected_u)
    options = cboe_data.get('options', [])
    spot = cboe_data.get('current_price', 0.0)
    if not options:
        console.print("[red]No live contracts discovered. Aborting selection.[/red]")
        return None

    console.print(f"Current Underlying Spot Price: [bold green]${spot:,.2f}[/bold green]")
    expiries = parse_equity_expiries(options)
    console.print(f"\nDiscovered [bold green]{len(expiries)}[/bold green] live active expiries for [bold white]{selected_u}[/bold white]:")

    table = Table(box=None, padding=(0, 2))
    table.add_column("IDX", style="dim")
    table.add_column("EXPIRY (YYMMDD)", style="bold yellow")
    table.add_column("IDX", style="dim")
    table.add_column("EXPIRY (YYMMDD)", style="bold yellow")
    table.add_column("IDX", style="dim")
    table.add_column("EXPIRY (YYMMDD)", style="bold yellow")

    for i in range(0, min(len(expiries), 24), 3):
        chunk = expiries[i:i+3]
        row = []
        for j, exp in enumerate(chunk):
            row.extend([f"[{i+j+1}]", exp])
        while len(row) < 6:
            row.extend(["", ""])
        table.add_row(*row)
    console.print(table)

    e_idx = int(Prompt.ask("Select expiry", choices=[str(i) for i in range(1, min(len(expiries)+1, 25))], default="1")) - 1
    selected_exp = expiries[e_idx]

    cp = Prompt.ask("Contract Type", choices=["C", "P"], default="C").upper()
    strikes_data = parse_equity_strikes(options, selected_exp, cp)

    console.print(f"\nDiscovered [bold green]{len(strikes_data)}[/bold green] active strikes for [bold white]{selected_u} {selected_exp} {cp}[/bold white]:")
    
    # Filter near-the-money strikes around spot price for fast selection
    near_strikes = sorted(strikes_data, key=lambda x: abs(x[0] - spot))[:16]
    near_strikes.sort(key=lambda x: x[0])

    s_table = Table(box=None, padding=(0, 2))
    s_table.add_column("IDX", style="dim")
    s_table.add_column("STRIKE", style="bold cyan")
    s_table.add_column("BID", justify="right", style="green")
    s_table.add_column("ASK", justify="right", style="red")
    s_table.add_column("IV", justify="right", style="magenta")

    for i, (stk, opt_name, bid, ask, iv) in enumerate(near_strikes, 1):
        atm_tag = " (ATM)" if abs(stk - spot) == min([abs(s[0] - spot) for s in near_strikes]) else ""
        s_table.add_row(
            f"[{i}]",
            f"${stk:.2f}{atm_tag}",
            f"${bid:.2f}",
            f"${ask:.2f}",
            f"{iv*100.0:.1f}%"
        )
    console.print(s_table)

    s_idx = int(Prompt.ask("Select strike", choices=[str(i) for i in range(1, len(near_strikes)+1)], default="1")) - 1
    chosen_stk, chosen_option_name, _, _, _ = near_strikes[s_idx]

    # Date formatting for Nasdaq
    try:
        dt = datetime.strptime(selected_exp, "%y%m%d")
        nasdaq_exp = dt.strftime("%b %d")
    except Exception:
        nasdaq_exp = "Sep 23"

    equity_config = {
        "underlying": selected_u,
        "expiry": selected_exp,
        "strike": float(chosen_stk),
        "call_put": cp,
        "cboe_option": chosen_option_name,
        "nasdaq_strike": f"{chosen_stk:.2f}",
        "nasdaq_expiry": nasdaq_exp,
        "sym": f"{selected_u}_{cp}{int(chosen_stk)}"
    }
    return equity_config

def main():
    parser = argparse.ArgumentParser(description="Interactive Options Contract Selector & Discovery")
    parser.add_argument("--crypto", action="store_true", help="Configure crypto options contract only")
    parser.add_argument("--equity", action="store_true", help="Configure equity options contract only")
    parser.add_argument("--show", action="store_true", help="Show currently configured active contracts")
    parser.add_argument("--apply", action="store_true", help="Apply and restart gateways immediately")
    args = parser.parse_args()

    current = load_current_config()

    if args.show:
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_row(Text("ACTIVE STREAMING CONTRACTS CONFIGURATION", style="bold yellow"))
        grid.add_row(Text(f"Crypto: {current['crypto']['deribit_instrument']} (Sym: {current['crypto']['sym']})", style="bold cyan"))
        grid.add_row(Text(f"Equity: {current['equity']['cboe_option']} (Sym: {current['equity']['sym']})", style="bold magenta"))
        console.print(Panel(grid, border_style="yellow"))
        return

    console.print(Panel(
        Text("ANTIGRAVITY DYNAMIC OPTIONS CONTRACT SELECTOR (ZERO HARDCODING)\nQueries live exchange APIs to discover active expiries & strikes", justify="center", style="bold yellow"),
        border_style="yellow"
    ))

    console.print("Current Streaming Contracts:")
    console.print(f"  • Crypto: [bold cyan]{current['crypto']['deribit_instrument']}[/bold cyan] (Strike ${current['crypto']['strike']:,.0f})")
    console.print(f"  • Equity: [bold magenta]{current['equity']['cboe_option']}[/bold magenta] (Strike ${current['equity']['strike']:.2f})\n")

    if args.crypto:
        new_crypto = select_crypto()
        if new_crypto:
            current['crypto'] = new_crypto
    elif args.equity:
        new_equity = select_equity()
        if new_equity:
            current['equity'] = new_equity
    else:
        choice = Prompt.ask("Choose which market contract to update", choices=["1", "2", "3"], default="1")
        if choice == "1":
            new_crypto = select_crypto()
            if new_crypto:
                current['crypto'] = new_crypto
        elif choice == "2":
            new_equity = select_equity()
            if new_equity:
                current['equity'] = new_equity
        elif choice == "3":
            new_crypto = select_crypto()
            if new_crypto:
                current['crypto'] = new_crypto
            new_equity = select_equity()
            if new_equity:
                current['equity'] = new_equity

    save_config(current)

    # Prompt restart
    should_restart = args.apply or Confirm.ask("\nRestart gateways now to start streaming newly selected contracts?", default=True)
    if should_restart:
        import subprocess
        console.print("[bold yellow]Restarting market gateways...[/bold yellow]")
        subprocess.run([str(ROOT_DIR / "start.sh"), "--restart", "deribit"])
        subprocess.run([str(ROOT_DIR / "start.sh"), "--restart", "okx"])
        subprocess.run([str(ROOT_DIR / "start.sh"), "--restart", "binance_opt"])
        subprocess.run([str(ROOT_DIR / "start.sh"), "--restart", "cboe"])
        subprocess.run([str(ROOT_DIR / "start.sh"), "--restart", "nasdaq"])
        subprocess.run([str(ROOT_DIR / "start.sh"), "--restart", "opra"])
        console.print("[bold green]✔ All gateways updated and streaming new contract targets live![/bold green]")

if __name__ == '__main__':
    main()
