#!/usr/bin/env python3
"""
Options Contract Catalog Discovery Engine.
Queries live public exchange APIs to fetch and cache top active contracts
across 5 Cryptos (BTC, ETH, SOL, XRP, AVAX) and 5 Equities (SPY, QQQ, AAPL, NVDA, TSLA).
"""

import os
import json
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
CATALOG_FILE = ROOT_DIR / "gateways" / "contract_catalog.json"

CRYPTO_UNDERLYINGS = ["BTC", "ETH", "SOL", "XRP", "AVAX"]
EQUITY_UNDERLYINGS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]

def fetch_crypto_catalog():
    catalog = {}
    for curr in CRYPTO_UNDERLYINGS:
        curr_param = "USDC" if curr in ["SOL", "XRP", "AVAX"] else curr
        url = f"https://www.deribit.com/api/v2/public/get_instruments?currency={curr_param}&kind=option&expired=false"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (ULL-Arbitrage-Engine)'})
            with urllib.request.urlopen(req, timeout=10) as r:
                res = json.loads(r.read().decode())['result']
                
                # Filter for target currency
                if curr in ["SOL", "XRP", "AVAX"]:
                    res = [x for x in res if x.get('instrument_name', '').startswith(f"{curr}_USDC") or x.get('instrument_name', '').startswith(f"{curr}-")]
                
                # Also fetch index / spot price for this currency
                idx_url = f"https://www.deribit.com/api/v2/public/get_index_price?index_name={curr.lower()}_usd" if curr in ["BTC", "ETH"] else f"https://www.deribit.com/api/v2/public/get_index_price?index_name={curr.lower()}_usdc"
                spot = 0.0
                try:
                    idx_req = urllib.request.Request(idx_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(idx_req, timeout=5) as ir:
                        spot = float(json.loads(ir.read().decode())['result']['index_price'])
                except Exception:
                    pass

                # Parse contracts
                parsed = []
                for inst in res:
                    name = inst.get('instrument_name', '')
                    parts = name.split('-')
                    if len(parts) >= 4:
                        exp = parts[1]
                        try:
                            stk_str_raw = parts[2].replace('d', '.')
                            stk = float(stk_str_raw)
                            cp = parts[3]
                            dist = abs(stk - spot) if spot > 0 else stk
                            parsed.append({
                                'instrument_name': name,
                                'underlying': curr,
                                'expiry': exp,
                                'strike': stk,
                                'call_put': cp,
                                'dist': dist,
                                'min_price': inst.get('min_price', 0.0),
                            })
                        except ValueError:
                            pass

                # Select top 5 near-the-money active contracts (prioritizing nearest expiry and closest strike)
                # Group by expiry
                by_exp = {}
                for p in parsed:
                    by_exp.setdefault(p['expiry'], []).append(p)

                # Pick expiry with at least 5 strikes
                target_exp = ""
                for exp in sorted(by_exp.keys(), key=lambda e: (len(e), e)):
                    calls = [p for p in by_exp[exp] if p['call_put'] == 'C']
                    if len(calls) >= 5:
                        target_exp = exp
                        break
                if not target_exp and by_exp:
                    target_exp = max(by_exp.keys(), key=lambda k: len([p for p in by_exp[k] if p['call_put'] == 'C']))

                exp_contracts = [p for p in by_exp.get(target_exp, []) if p['call_put'] == 'C']
                exp_contracts.sort(key=lambda x: x['dist'])
                top5 = exp_contracts[:5]
                top5.sort(key=lambda x: x['strike'])

                # Format exchange symbols for each contract
                final_contracts = []
                for c in top5:
                    stk_str = f"{int(c['strike']) if c['strike'].is_integer() else c['strike']}"
                    try:
                        dt = datetime.strptime(c['expiry'], "%d%b%y")
                        yymmdd = dt.strftime("%y%m%d")
                    except Exception:
                        yymmdd = "260923"

                    okx_inst = f"{curr}-USD-{yymmdd}-{stk_str}-{c['call_put']}"
                    binance_inst = f"{curr}-{yymmdd}-{stk_str}-{c['call_put']}"
                    sym_name = f"{curr}_{c['call_put']}{stk_str}"

                    final_contracts.append({
                        'deribit_instrument': c['instrument_name'],
                        'underlying': curr,
                        'expiry': c['expiry'],
                        'strike': c['strike'],
                        'call_put': c['call_put'],
                        'okx_inst_id': okx_inst,
                        'binance_symbol': binance_inst,
                        'sym': sym_name
                    })

                catalog[curr] = {
                    'spot': spot,
                    'expiry': target_exp,
                    'contracts': final_contracts
                }
        except Exception as e:
            print(f"Error fetching crypto catalog for {curr}: {e}")

    return catalog

def fetch_equity_catalog():
    catalog = {}
    for sym in EQUITY_UNDERLYINGS:
        url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (ULL-Arbitrage-Engine)'})
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode())['data']
                spot = float(data.get('current_price', 0.0))
                options = data.get('options', [])

                # Filter Calls and find nearest expiry that has at least 5 contracts
                L = len(sym)
                expiries = sorted(list(set([o['option'][L:L+6] for o in options if len(o.get('option', '')) >= L+7])))
                target_exp = ""
                exp_calls = []
                for exp in expiries:
                    calls = [o for o in options if o.get('option', '')[L:L+6] == exp and o.get('option', '')[L+6:L+7] == 'C']
                    if len(calls) >= 5:
                        target_exp = exp
                        exp_calls = calls
                        break
                if not target_exp and expiries:
                    target_exp = expiries[0]
                    exp_calls = [o for o in options if o.get('option', '')[L:L+6] == target_exp and o.get('option', '')[L+6:L+7] == 'C']
                
                parsed = []
                for o in exp_calls:
                    name = o.get('option', '')
                    try:
                        stk = float(name[L+7:]) / 1000.0
                        parsed.append({
                            'cboe_option': name,
                            'underlying': sym,
                            'expiry': target_exp,
                            'strike': stk,
                            'call_put': 'C',
                            'bid': float(o.get('bid', 0.0)),
                            'ask': float(o.get('ask', 0.0)),
                            'iv': float(o.get('iv', 0.0)),
                            'theo': float(o.get('theo', 0.0)),
                            'dist': abs(stk - spot)
                        })
                    except ValueError:
                        pass

                parsed.sort(key=lambda x: x['dist'])
                top5 = parsed[:5]
                top5.sort(key=lambda x: x['strike'])

                try:
                    dt = datetime.strptime(target_exp, "%y%m%d")
                    nasdaq_exp = dt.strftime("%b %d")
                except Exception:
                    nasdaq_exp = "Sep 23"

                final_contracts = []
                for c in top5:
                    final_contracts.append({
                        'cboe_option': c['cboe_option'],
                        'underlying': sym,
                        'expiry': target_exp,
                        'strike': c['strike'],
                        'call_put': 'C',
                        'nasdaq_strike': f"{c['strike']:.2f}",
                        'nasdaq_expiry': nasdaq_exp,
                        'sym': f"{sym}_C{int(c['strike'])}",
                        'bid': c['bid'],
                        'ask': c['ask'],
                        'iv': c['iv'],
                        'theo': c['theo']
                    })

                catalog[sym] = {
                    'spot': spot,
                    'expiry': target_exp,
                    'contracts': final_contracts
                }
        except Exception as e:
            print(f"Error fetching equity catalog for {sym}: {e}")

    return catalog

def refresh_catalog():
    print("[Contract Catalog] Discovering live contracts across 5 cryptos and 5 equities...")
    crypto_cat = fetch_crypto_catalog()
    equity_cat = fetch_equity_catalog()
    full_cat = {
        'timestamp': datetime.utcnow().isoformat(),
        'crypto': crypto_cat,
        'equity': equity_cat
    }
    CATALOG_FILE.write_text(json.dumps(full_cat, indent=2))
    print(f"[Contract Catalog] Catalog successfully generated and saved to {CATALOG_FILE}")
    return full_cat

def load_catalog(auto_refresh=True):
    if CATALOG_FILE.exists():
        try:
            return json.loads(CATALOG_FILE.read_text())
        except Exception:
            pass
    if auto_refresh:
        return refresh_catalog()
    return {'crypto': {}, 'equity': {}}

if __name__ == '__main__':
    refresh_catalog()
