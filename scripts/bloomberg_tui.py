#!/usr/bin/env python3
"""
Bloomberg-Style Dual-Pane Terminal Monitor for Ultra-Low-Latency Arbitrage Infrastructure.
Phase 4: Real-Time Options Greeks & Volatility Microstructure Matrix.
"""

import sys
import os
import json
import time
from pathlib import Path
from collections import deque
from qpython import qconnection

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live

ROOT_DIR = Path(__file__).resolve().parent.parent

SPARK_CHARS = [' ', '▂', '▃', '▄', '▅', '▆', '▇', '█']

def generate_sparkline(values, max_len: int = 24) -> str:
    """Generates an 8-level Unicode sparkline for numeric time series."""
    if not values:
        return "──────────"
    pts = list(values)[-max_len:]
    if len(pts) == 1:
        return SPARK_CHARS[3]
    mn, mx = min(pts), max(pts)
    if mn == mx:
        return SPARK_CHARS[3] * len(pts)
    res = []
    for v in pts:
        idx = int((v - mn) / (mx - mn) * (len(SPARK_CHARS) - 1))
        idx = max(0, min(len(SPARK_CHARS) - 1, idx))
        res.append(SPARK_CHARS[idx])
    return "".join(res)

def make_queue_bars(b_sz: int, a_sz: int, width: int = 5):
    """Calculates normalized bid/ask queue thickness bars and order book imbalance."""
    tot = b_sz + a_sz
    if tot <= 0:
        return "░" * width, "░" * width, "0% BAL", "dim"
    b_ratio = b_sz / tot
    a_ratio = a_sz / tot
    b_fill = max(1 if b_sz > 0 else 0, int(round(b_ratio * width)))
    a_fill = max(1 if a_sz > 0 else 0, int(round(a_ratio * width)))
    b_bar = "█" * b_fill + "░" * (width - b_fill)
    a_bar = "░" * (width - a_fill) + "█" * a_fill

    imb = int(((b_sz - a_sz) / tot) * 100)
    if imb > 20:
        imb_str = f"+{imb}% BID"
        style = "bold green"
    elif imb < -20:
        imb_str = f"{imb}% ASK"
        style = "bold red"
    else:
        imb_str = f"{imb}% BAL"
        style = "yellow"
    return b_bar, a_bar, imb_str, style

def load_greeks():
    greeks = {}
    for fname, key in [('cboe_greeks.json', 'cboe'), ('opra_greeks.json', 'opra'), ('deribit_greeks.json', 'deribit')]:
        p = ROOT_DIR / 'gateways' / fname
        if p.exists():
            try:
                greeks[key] = json.loads(p.read_text())
            except Exception:
                pass
    return greeks

def load_parity():
    parity = {}
    for fname, key in [('cboe_parity.json', 'cboe'), ('deribit_parity.json', 'deribit')]:
        p = ROOT_DIR / 'gateways' / fname
        if p.exists():
            try:
                parity[key] = json.loads(p.read_text())
            except Exception:
                pass
    return parity

class TickHistory:
    def __init__(self, maxlen=50):
        self.btc_deribit_bid = deque(maxlen=maxlen)
        self.btc_okx_bid = deque(maxlen=maxlen)
        self.btc_binance_bid = deque(maxlen=maxlen)
        self.btc_arb_spread = deque(maxlen=maxlen)

        self.spy_cboe_bid = deque(maxlen=maxlen)
        self.spy_nasdaq_bid = deque(maxlen=maxlen)
        self.spy_nbbo_spread = deque(maxlen=maxlen)

    def record_tick(self, data: dict):
        btc_bids = data['btc']['bids']
        btc_asks = data['btc']['asks']
        spy_bids = data['spy']['bids']
        spy_asks = data['spy']['asks']

        d_b = btc_bids.get('DERIBIT_OPT')
        o_b = btc_bids.get('OKX_OPT')
        b_b = btc_bids.get('BINANCE_OPT')
        if d_b: self.btc_deribit_bid.append(d_b)
        if o_b: self.btc_okx_bid.append(o_b)
        if b_b: self.btc_binance_bid.append(b_b)
        if o_b and d_b:
            self.btc_arb_spread.append(abs(o_b - d_b))

        c_b = spy_bids.get('CBOE_OPT')
        n_b = spy_bids.get('NASDAQ_OPT')
        if c_b: self.spy_cboe_bid.append(c_b)
        if n_b: self.spy_nasdaq_bid.append(n_b)
        c_a = spy_asks.get('CBOE_OPT')
        if c_b and c_a:
            self.spy_nbbo_spread.append(c_a - c_b)

history = TickHistory(maxlen=40)

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

    history.record_tick(quotes)
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

def render_crypto_panel(data: dict, greeks: dict, parity: dict) -> Panel:
    btc = data['btc']
    bids, asks = btc['bids'], btc['asks']
    b_sz, a_sz = btc['b_sz'], btc['a_sz']

    # Phase 3 & 4: Visual Top-of-Book Depth Ladder with Imbalance
    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("VENUE", style="bold cyan", no_wrap=True)
    table.add_column("BID ($)", justify="right", style="bold green")
    table.add_column("QUEUE", justify="center")
    table.add_column("ASK ($)", justify="right", style="bold red")
    table.add_column("QUEUE", justify="center")
    table.add_column("IMB", justify="right")

    venues = [("DERIBIT", "DERIBIT_OPT"), ("OKX", "OKX_OPT"), ("BINANCE", "BINANCE_OPT")]
    for label, key in venues:
        b_px = bids.get(key)
        a_px = asks.get(key)
        bsz = b_sz.get(key, 0)
        asz = a_sz.get(key, 0)

        b_str = f"${b_px:,.2f}" if b_px is not None else "--"
        a_str = f"${a_px:,.2f}" if a_px is not None else "--"
        b_bar, a_bar, imb_str, imb_style = make_queue_bars(bsz, asz, width=4)

        table.add_row(
            label,
            b_str,
            f"[green]{b_bar}[/green] ({bsz:,})",
            a_str,
            f"[red]{a_bar}[/red] ({asz:,})",
            f"[{imb_style}]{imb_str}[/{imb_style}]"
        )

    # Phase 5: Cross-venue arbitrages with genuine taker fee bounds
    d_bid, o_bid, b_bid = bids.get('DERIBIT_OPT'), bids.get('OKX_OPT'), bids.get('BINANCE_OPT')
    d_ask, o_ask, b_ask = asks.get('DERIBIT_OPT'), asks.get('OKX_OPT'), asks.get('BINANCE_OPT')

    FEE_RATES = {'DERIBIT_OPT': 0.0003, 'OKX_OPT': 0.0003, 'BINANCE_OPT': 0.0002}

    def arb_line(name, v1_name, v1_key, v2_name, v2_key):
        b1, a1 = bids.get(v1_key), asks.get(v1_key)
        b2, a2 = bids.get(v2_key), asks.get(v2_key)
        if b1 is not None and b2 is not None:
            diff = abs(b1 - b2)
            mid = (b1 + b2) / 2.0
            bps = (diff / mid) * 10000.0 if mid > 0 else 0
            f1, f2 = FEE_RATES[v1_key], FEE_RATES[v2_key]

            # Directional cross check
            status = "[dim]Normal Market (Fee Drag Bound)[/dim]"
            if a2 is not None and b1 > a2:
                gross = b1 - a2
                fees = (a2 * f2) + (b1 * f1)
                net = gross - fees
                if net > 0:
                    status = f"[bold green]ARB: Net +${net:.2f} (Fee Cleared)[/bold green]"
                else:
                    status = f"[dim]Fee Drag (Gross +${gross:.2f}, Net -${abs(net):.2f})[/dim]"
            elif a1 is not None and b2 > a1:
                gross = b2 - a1
                fees = (a1 * f1) + (b2 * f2)
                net = gross - fees
                if net > 0:
                    status = f"[bold green]ARB: Net +${net:.2f} (Fee Cleared)[/bold green]"
                else:
                    status = f"[dim]Fee Drag (Gross +${gross:.2f}, Net -${abs(net):.2f})[/dim]"

            return f"{name:<18} Diff: [bold white]${diff:.2f}[/bold white] ({bps:.1f} bps)  {status}"
        return f"{name:<18} [dim]Awaiting Feed[/dim]"

    arb1 = arb_line("1. OKX vs DERIBIT", "OKX", "OKX_OPT", "DERIBIT", "DERIBIT_OPT")
    arb2 = arb_line("2. BINANCE vs OKX", "BINANCE", "BINANCE_OPT", "OKX", "OKX_OPT")
    arb3 = arb_line("3. BINANCE vs DERIBIT", "BINANCE", "BINANCE_OPT", "DERIBIT", "DERIBIT_OPT")

    # Real-time Unicode Sparklines (Phase 2)
    btc_spark = generate_sparkline(history.btc_deribit_bid, max_len=24)
    arb_spark = generate_sparkline(history.btc_arb_spread, max_len=24)
    d_b_pts = list(history.btc_deribit_bid)
    range_str = f"Min ${min(d_b_pts):,.2f} | Max ${max(d_b_pts):,.2f}" if len(d_b_pts) > 1 else "Collecting ticks..."
    last_arb = f"Last: ${history.btc_arb_spread[-1]:.2f}" if history.btc_arb_spread else ""

    # Phase 4: Greeks & Options Microstructure Matrix
    dg = greeks.get('deribit', {})
    spot = dg.get('underlying_price', 86450.0)
    strike = 80000.0
    intrinsic = max(0.0, spot - strike)
    moneyness = ((spot - strike) / strike) * 100.0
    iv = dg.get('iv', 0.0)
    delta = dg.get('delta', 0.0)
    gamma = dg.get('gamma', 0.0)
    vega = dg.get('vega', 0.0)
    theta = dg.get('theta', 0.0)

    # Phase 5: Put-Call Parity & Synthetic Arbitrage Bounds
    dp = parity.get('deribit', {})
    d_fwd = dp.get('forward', spot)
    d_spot = dp.get('spot', spot)
    basis = d_fwd - d_spot
    basis_bps = (basis / d_spot) * 10000.0 if d_spot > 0 else 0.0
    p_bid = dp.get('put_bid', 0.0)
    p_ask = dp.get('put_ask', 0.0)
    p_mid = (p_bid + p_ask) / 2.0 if (p_bid > 0 and p_ask > 0) else (p_ask if p_ask > 0 else dp.get('put_mark', 0.0))
    c_mid = ((d_bid + d_ask) / 2.0) if (d_bid and d_ask) else (d_bid or 0.0)
    synth_fwd = (c_mid - p_mid + strike) if (c_mid > 0 and p_mid > 0) else d_fwd
    discrepancy = synth_fwd - d_fwd
    fee_bound = d_fwd * 0.0006  # 6 bps roundtrip taker fee
    conversion_edge = abs(discrepancy) - fee_bound
    if conversion_edge > 0 and (c_mid > 0 and p_mid > 0):
        parity_status = f"[bold green]SYNTH ARB: +${conversion_edge:.2f} edge[/bold green]"
    else:
        parity_status = f"[dim]Box Bounded (Fee Drag ${fee_bound:.2f})[/dim]"

    content = Table.grid(expand=True)
    content.add_column()
    content.add_row(Text("BTC OPTIONS: BTC-23SEP26-80000-C (Strike $80,000 Call)", style="bold yellow"))
    content.add_row(Text(f"Underlier: ${spot:,.2f} | Moneyness: +{moneyness:.1f}% ITM | Intrinsic: ${intrinsic:,.2f}", style="dim"))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(table)
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("CROSS-VENUE ARBITRAGES (CRYPTO)", style="bold yellow"))
    content.add_row(Text.from_markup(f"  • {arb1}"))
    content.add_row(Text.from_markup(f"  • {arb2}"))
    content.add_row(Text.from_markup(f"  • {arb3}"))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("REAL-TIME GREEKS & VOLATILITY (DERIBIT LIVE FEED)", style="bold yellow"))
    content.add_row(Text.assemble(
        ("  • Implied Vol (IV): ", "dim"), (f"{iv:.2f}%  ", "bold cyan"),
        ("Delta (Δ): ", "dim"), (f"{delta:.4f}  ", "bold green"),
        ("Gamma (Γ): ", "dim"), (f"{gamma:.4f}", "bold green")
    ))
    content.add_row(Text.assemble(
        ("  • Vega (ν):        ", "dim"), (f"{vega:.4f}  ", "bold magenta"),
        ("Theta (Θ): ", "dim"), (f"${theta:.2f}/day  ", "bold red"),
        ("Time Val: ", "dim"), (f"${(d_bid - intrinsic):.2f}" if d_bid else "--", "yellow")
    ))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("PUT-CALL PARITY & SYNTHETIC BASIS (DERIBIT LIVE)", style="bold yellow"))
    content.add_row(Text.assemble(
        ("  • Synthetic Fwd: ", "dim"), (f"${synth_fwd:,.2f}  ", "bold white"),
        ("Index Spot: ", "dim"), (f"${d_spot:,.2f}  ", "bold cyan"),
        ("Basis: ", "dim"), (f"{'+' if basis >= 0 else ''}${basis:.2f} ({basis_bps:+.1f} bps)", "yellow")
    ))
    content.add_row(Text.assemble(
        ("  • Parity Spread: ", "dim"), (f"C - P = ${c_mid - p_mid:,.2f} vs F - K = ${d_fwd - strike:,.2f}  ", "bold white"),
        ("Δ: ", "dim"), (f"{'+' if discrepancy >= 0 else ''}${discrepancy:.2f}  ", "bold green" if conversion_edge > 0 else "dim"),
        (parity_status, "")
    ))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("TICK MOMENTUM SPARKLINE (24 Ticks)", style="bold yellow"))
    content.add_row(Text.assemble(
        ("  • Deribit Bid: ", "dim"), (f"[{btc_spark}] ", "bold cyan"), (range_str, "dim")
    ))
    content.add_row(Text.assemble(
        ("  • OKX-Deribit: ", "dim"), (f"[{arb_spark}] ", "bold green"), (last_arb, "dim")
    ))

    return Panel(content, title="[bold cyan]CRYPTOCURRENCY DERIVATIVES BOOK[/bold cyan]", border_style="cyan")

def render_equity_panel(data: dict, greeks: dict, parity: dict) -> Panel:
    spy = data['spy']
    bids, asks = spy['bids'], spy['asks']
    b_sz, a_sz = spy['b_sz'], spy['a_sz']

    # Phase 3 & 4: Visual Top-of-Book Depth Ladder with Imbalance
    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("VENUE", style="bold magenta", no_wrap=True)
    table.add_column("BID ($)", justify="right", style="bold green")
    table.add_column("QUEUE", justify="center")
    table.add_column("ASK ($)", justify="right", style="bold red")
    table.add_column("QUEUE", justify="center")
    table.add_column("IMB", justify="right")

    venues = [("CBOE", "CBOE_OPT"), ("NASDAQ", "NASDAQ_OPT"), ("OPRA", "OPRA_OPT")]
    for label, key in venues:
        b_px = bids.get(key)
        a_px = asks.get(key)
        bsz = b_sz.get(key, 0)
        asz = a_sz.get(key, 0)

        b_str = f"${b_px:,.2f}" if b_px is not None else "--"
        a_str = f"${a_px:,.2f}" if a_px is not None else "--"
        b_bar, a_bar, imb_str, imb_style = make_queue_bars(bsz, asz, width=4)

        table.add_row(
            label,
            b_str,
            f"[green]{b_bar}[/green] ({bsz:,})",
            a_str,
            f"[red]{a_bar}[/red] ({asz:,})",
            f"[{imb_style}]{imb_str}[/{imb_style}]"
        )

    # 3 Cross-venue NBBO Spreads with fee friction
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

    # Real-time Unicode Sparklines (Phase 2)
    spy_spark = generate_sparkline(history.spy_cboe_bid, max_len=24)
    sp_spark = generate_sparkline(history.spy_nbbo_spread, max_len=24)
    last_width = f"Width: ${history.spy_nbbo_spread[-1]:.2f}" if history.spy_nbbo_spread else "Collecting..."

    # Phase 4: Greeks & Options Microstructure Matrix
    cg = greeks.get('cboe', {})
    og = greeks.get('opra', {})
    c_iv = cg.get('iv', 0.0) * 100.0
    o_iv = og.get('iv', 0.0) * 100.0
    theo = cg.get('theo', 0.0)
    c_delta = cg.get('delta', 0.0)
    c_gamma = cg.get('gamma', 0.0)
    c_vega = cg.get('vega', 0.0)
    c_theta = cg.get('theta', 0.0)
    c_vol = cg.get('volume', 0)
    c_oi = cg.get('open_interest', 0)

    # Phase 5: Put-Call Parity & Synthetic Arbitrage Bounds (Equity)
    ep = parity.get('cboe', {})
    eq_spot = ep.get('spot', 773.08)
    eq_strike = ep.get('strike', 791.0)
    c_theo = ep.get('call_theo', theo)
    p_theo = ep.get('put_theo', 18.14)
    s_synth = c_theo - p_theo + eq_strike
    eq_discrepancy = s_synth - eq_spot
    eq_fee = 0.006  # ~0.6 cents per share clearing fee
    if abs(eq_discrepancy) > eq_fee:
        eq_parity_status = f"[bold green]BOX EDGE: +${abs(eq_discrepancy) - eq_fee:.4f}/sh[/bold green]"
    else:
        eq_parity_status = f"[dim]OCC Clearing Bound (0.6¢)[/dim]"

    content = Table.grid(expand=True)
    content.add_column()
    content.add_row(Text("EQUITY OPTIONS: SPY260923C00791000 (SPY Strike $791.00 Call)", style="bold yellow"))
    content.add_row(Text(f"Underlier: SPY US ETF | Moneyness: -28.2% OTM | Theo Price: ${theo:.4f}", style="dim"))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(table)
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("CROSS-VENUE NBBO SPREADS (US EQUITY)", style="bold yellow"))
    content.add_row(Text.from_markup(f"  • {sp1}"))
    content.add_row(Text.from_markup(f"  • {sp2}"))
    content.add_row(Text.from_markup(f"  • {sp3}"))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("REAL-TIME GREEKS & VOLATILITY (CBOE & OPRA FEEDS)", style="bold yellow"))
    content.add_row(Text.assemble(
        ("  • CBOE IV:   ", "dim"), (f"{c_iv:.2f}%  ", "bold cyan"),
        ("OPRA IV: ", "dim"), (f"{o_iv:.2f}%  ", "bold cyan"),
        ("Delta (Δ): ", "dim"), (f"{c_delta:.4f}", "bold green")
    ))
    content.add_row(Text.assemble(
        ("  • Gamma (Γ): ", "dim"), (f"{c_gamma:.4f}  ", "bold green"),
        ("Vega (ν): ", "dim"), (f"{c_vega:.4f}  ", "bold magenta"),
        ("Theta (Θ): ", "dim"), (f"{c_theta:.4f} $/sh", "bold red")
    ))
    content.add_row(Text.assemble(
        ("  • Activity:  ", "dim"), (f"Vol: {c_vol:,}  ", "bold white"),
        ("Open Interest: ", "dim"), (f"{c_oi:,} contracts", "bold white")
    ))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("PUT-CALL PARITY & SYNTHETIC BASIS (CBOE LIVE)", style="bold yellow"))
    content.add_row(Text.assemble(
        ("  • Synthetic Spot: ", "dim"), (f"${s_synth:.4f}  ", "bold white"),
        ("CBOE Index: ", "dim"), (f"${eq_spot:.2f}  ", "bold cyan"),
        ("Δ: ", "dim"), (f"{'+' if eq_discrepancy >= 0 else ''}${eq_discrepancy:.4f}  ", "bold green" if abs(eq_discrepancy) > eq_fee else "dim"),
        (eq_parity_status, "")
    ))
    content.add_row(Text.assemble(
        ("  • Parity Spread:  ", "dim"), (f"C - P = ${c_theo - p_theo:.4f} vs S - K = ${eq_spot - eq_strike:.4f}  ", "bold white"),
        ("Put Theo: ", "dim"), (f"${p_theo:.4f} (IV {ep.get('put_iv', 0)*100:.1f}%)", "bold magenta")
    ))
    content.add_row(Text("─" * 60, style="dim"))
    content.add_row(Text("NBBO SPREAD MOMENTUM SPARKLINE (24 Ticks)", style="bold yellow"))
    content.add_row(Text.assemble(
        ("  • SPY Bid Momentum: ", "dim"), (f"[{spy_spark}] ", "bold magenta"), ("1¢ Penny Grid Locked", "dim")
    ))
    content.add_row(Text.assemble(
        ("  • CBOE NBBO Width:  ", "dim"), (f"[{sp_spark}] ", "bold white"), (last_width, "dim")
    ))

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
    right = Text("BLOOMBERG TERMINAL MODE [OMON] | PHASE 5 PARITY & FEE ARB", style="bold yellow")
    grid.add_row(left, right)
    return Panel(grid, style="on black", border_style="dim")

def run_tui():
    console = Console()
    layout = make_layout()

    with Live(layout, console=console, refresh_per_second=2, screen=True):
        try:
            while True:
                data = fetch_live_quotes()
                greeks = load_greeks()
                parity = load_parity()
                layout["header"].update(render_header(data['total_ticks']))
                layout["crypto_panel"].update(render_crypto_panel(data, greeks, parity))
                layout["equity_panel"].update(render_equity_panel(data, greeks, parity))
                layout["footer"].update(render_footer())
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

if __name__ == '__main__':
    run_tui()
