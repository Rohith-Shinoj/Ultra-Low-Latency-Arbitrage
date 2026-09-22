#!/usr/bin/env python3
"""
Bloomberg-Style Dual-Pane Terminal Monitor for Ultra-Low-Latency Arbitrage Infrastructure.
Phase 1: Parallel Side-by-Side Split Screen (Crypto Options vs. Equity Options).
"""

import sys
import os
import time
from pathlib import Path
from qpython import qconnection

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live

ROOT_DIR = Path(__file__).resolve().parent.parent

def fetch_live_quotes():
    """Queries KDB+ directly for strictly partitioned crypto and equity quotes."""
    quotes = {
        'btc': {'bids': {}, 'asks': {}, 'b_sz': {}, 'a_sz': {}},
        'spy': {'bids': {}, 'asks': {}, 'b_sz': {}, 'a_sz': {}},
        'total_ticks': 0
    }
    try:
        q = qconnection.QConnection(host='localhost', port=5020, timeout=1.0)
        q.open()
        quotes['total_ticks'] = int(q('count OptBook'))

        if quotes['total_ticks'] > 0:
            bids_btc = q('select last price, last size by exch from OptBook where side="B", sym like "BTC*"')
            asks_btc = q('select last price, last size by exch from OptBook where side="S", sym like "BTC*"')
            bids_spy = q('select last price, last size by exch from OptBook where side="B", sym like "SPY_C791*"')
            asks_spy = q('select last price, last size by exch from OptBook where side="S", sym like "SPY_C791*"')

            def parse_into(target, bids_res, asks_res):
                for exch, row in bids_res.items():
                    name = (exch[0] if hasattr(exch, '__getitem__') else exch)
                    name_str = name.decode() if hasattr(name, 'decode') else str(name)
                    target['bids'][name_str] = float(row[0])
                    target['b_sz'][name_str] = int(row[1]) if len(row) > 1 else 0
                for exch, row in asks_res.items():
                    name = (exch[0] if hasattr(exch, '__getitem__') else exch)
                    name_str = name.decode() if hasattr(name, 'decode') else str(name)
                    target['asks'][name_str] = float(row[0])
                    target['a_sz'][name_str] = int(row[1]) if len(row) > 1 else 0

            parse_into(quotes['btc'], bids_btc, asks_btc)
            parse_into(quotes['spy'], bids_spy, asks_spy)

        q.close()
    except Exception:
        pass
    return quotes

def make_layout() -> Layout:
    """Defines the dual-pane Bloomberg-style screen geometry."""
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["main"].split_row(
        Layout(name="crypto_panel", ratio=1),
        Layout(name="equity_panel", ratio=1),
    )
    return layout

def render_header(total_ticks: int) -> Panel:
    now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC")
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="center", ratio=2)
    grid.add_column(justify="right", ratio=1)

    title = Text("OMON <GO>  |  CROSS-VENUE ARBITRAGE & QUANT MONITOR", style="bold yellow")
    mid_info = Text.assemble(
        ("INGRESS: ", "dim"), ("AF_XDP (Kernel Bypass)  ", "bold green"),
        ("CPU: ", "dim"), ("Core 2 (Pinned)  ", "bold cyan"),
        ("FEED: ", "dim"), ("UDP Multicast (5000-5005)", "bold white"),
    )
    right_info = Text.assemble(
        ("TICKS: ", "dim"), (f"{total_ticks:,}  ", "bold green"),
        (now_str, "bold yellow")
    )
    grid.add_row(title, mid_info, right_info)
    return Panel(grid, style="on black", border_style="yellow")

def render_crypto_panel(data: dict) -> Panel:
    btc = data['btc']
    bids, asks = btc['bids'], btc['asks']
    b_sz, a_sz = btc['b_sz'], btc['a_sz']

    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("VENUE", style="bold cyan", width=11)
    table.add_column("BID ($)", justify="right", style="bold green", width=16)
    table.add_column("ASK ($)", justify="right", style="bold red", width=16)
    table.add_column("SPREAD ($)", justify="right", style="bold white", width=12)

    venues = [("DERIBIT", "DERIBIT_OPT"), ("OKX", "OKX_OPT"), ("BINANCE", "BINANCE_OPT")]
    for label, key in venues:
        b_px = bids.get(key)
        a_px = asks.get(key)
        bsz = b_sz.get(key, 0)
        asz = a_sz.get(key, 0)

        b_str = f"${b_px:,.2f} ({bsz:,})" if b_px is not None else "--"
        a_str = f"${a_px:,.2f} ({asz:,})" if a_px is not None else "--"
        sp_str = f"${(a_px - b_px):,.2f}" if (b_px is not None and a_px is not None) else "--"

        table.add_row(label, b_str, a_str, sp_str)

    # 3 Cross-venue arbitrages
    d_bid, o_bid, b_bid = bids.get('DERIBIT_OPT'), bids.get('OKX_OPT'), bids.get('BINANCE_OPT')
    d_ask, o_ask, b_ask = asks.get('DERIBIT_OPT'), asks.get('OKX_OPT'), asks.get('BINANCE_OPT')

    def arb_line(name, bid, ask, other_bid):
        if bid is not None and other_bid is not None:
            diff = abs(bid - other_bid)
            mid = (bid + other_bid) / 2.0
            bps = (diff / mid) * 10000.0 if mid > 0 else 0
            if ask is not None and bid > ask:
                net = (bid - ask) - (bid + ask) * 0.00025
                status = f"[bold green]ARB: Net +${net:.2f}[/bold green]"
            else:
                status = "[dim]Normal Market[/dim]"
            return f"{name:<18} Diff: [bold white]${diff:.2f}[/bold white] ({bps:.1f} bps)  {status}"
        return f"{name:<18} [dim]Awaiting Feed[/dim]"

    arb1 = arb_line("1. OKX vs DERIBIT", o_bid, d_ask, d_bid)
    arb2 = arb_line("2. BINANCE vs OKX", b_bid, o_ask, o_bid)
    arb3 = arb_line("3. BINANCE vs DERIBIT", b_bid, d_ask, d_bid)

    content = Table.grid(expand=True)
    content.add_column()
    content.add_row(Text("BTC OPTIONS: BTC-23SEP26-80000-C (Strike $80,000 Call)", style="bold yellow"))
    content.add_row(Text("Underlier: BTC Index | Multi-Exchange Order Book Top", style="dim"))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(table)
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("CROSS-VENUE ARBITRAGES (CRYPTO)", style="bold yellow"))
    content.add_row(Text.from_markup(f"  • {arb1}"))
    content.add_row(Text.from_markup(f"  • {arb2}"))
    content.add_row(Text.from_markup(f"  • {arb3}"))

    return Panel(content, title="[bold cyan]CRYPTOCURRENCY DERIVATIVES BOOK[/bold cyan]", border_style="cyan")

def render_equity_panel(data: dict) -> Panel:
    spy = data['spy']
    bids, asks = spy['bids'], spy['asks']
    b_sz, a_sz = spy['b_sz'], spy['a_sz']

    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("VENUE", style="bold magenta", width=11)
    table.add_column("BID ($)", justify="right", style="bold green", width=16)
    table.add_column("ASK ($)", justify="right", style="bold red", width=16)
    table.add_column("SPREAD ($)", justify="right", style="bold white", width=12)

    venues = [("CBOE", "CBOE_OPT"), ("NASDAQ", "NASDAQ_OPT"), ("OPRA", "OPRA_OPT")]
    for label, key in venues:
        b_px = bids.get(key)
        a_px = asks.get(key)
        bsz = b_sz.get(key, 0)
        asz = a_sz.get(key, 0)

        b_str = f"${b_px:,.2f} ({bsz:,})" if b_px is not None else "--"
        a_str = f"${a_px:,.2f} ({asz:,})" if a_px is not None else "--"
        sp_str = f"${(a_px - b_px):,.2f}" if (b_px is not None and a_px is not None) else "--"

        table.add_row(label, b_str, a_str, sp_str)

    # 3 Cross-venue NBBO Spreads
    c_b, n_b, p_b = bids.get('CBOE_OPT'), bids.get('NASDAQ_OPT'), bids.get('OPRA_OPT')
    c_a, n_a, p_a = asks.get('CBOE_OPT'), asks.get('NASDAQ_OPT'), asks.get('OPRA_OPT')

    def spread_line(name, b1, b2, a1, a2):
        if b1 is not None and b2 is not None:
            b_diff = abs(b1 - b2)
            a_diff = abs(a1 - a2) if (a1 is not None and a2 is not None) else 0.0
            return f"{name:<18} NBBO Bid Diff: [bold white]${b_diff:.2f}[/bold white] | Ask Diff: [bold white]${a_diff:.2f}[/bold white]"
        return f"{name:<18} [dim]Awaiting Feed[/dim]"

    sp1 = spread_line("1. CBOE vs NASDAQ", c_b, n_b, c_a, n_a)
    sp2 = spread_line("2. NASDAQ vs OPRA", n_b, p_b, n_a, p_a)
    sp3 = spread_line("3. CBOE vs OPRA", c_b, p_b, c_a, p_a)

    content = Table.grid(expand=True)
    content.add_column()
    content.add_row(Text("EQUITY OPTIONS: SPY260923C00791000 (SPY Strike $791.00 Call)", style="bold yellow"))
    content.add_row(Text("Underlier: SPY US ETF | National Best Bid & Offer (NBBO)", style="dim"))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(table)
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("CROSS-VENUE NBBO SPREADS (US EQUITY)", style="bold yellow"))
    content.add_row(Text.from_markup(f"  • {sp1}"))
    content.add_row(Text.from_markup(f"  • {sp2}"))
    content.add_row(Text.from_markup(f"  • {sp3}"))

    return Panel(content, title="[bold magenta]US EQUITY OPTIONS NBBO BOOK[/bold magenta]", border_style="magenta")

def render_footer() -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right", ratio=1)

    left = Text.assemble(
        ("COMMANDS: ", "dim"),
        ("[Ctrl+C] Exit  ", "bold white"),
        ("[r] Force Ingress Sync  ", "bold white"),
        ("ENGINE: ", "dim"),
        ("LIVE ARB EVALUATION ACTIVE", "bold green"),
    )
    right = Text("BLOOMBERG TERMINAL MODE [OMON] | PHASE 1 DUAL-PANE VIEW", style="bold yellow")
    grid.add_row(left, right)
    return Panel(grid, style="on black", border_style="dim")

def run_tui():
    console = Console()
    layout = make_layout()

    with Live(layout, console=console, refresh_per_second=2, screen=True):
        try:
            while True:
                data = fetch_live_quotes()
                layout["header"].update(render_header(data['total_ticks']))
                layout["crypto_panel"].update(render_crypto_panel(data))
                layout["equity_panel"].update(render_equity_panel(data))
                layout["footer"].update(render_footer())
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

if __name__ == '__main__':
    run_tui()
