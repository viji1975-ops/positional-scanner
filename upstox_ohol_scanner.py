import requests
import pandas as pd
import gzip
import json
from io import BytesIO

# ==========================================
# CONFIGURATION
# ==========================================
ACCESS_TOKEN = "YOUR_UPSTOX_ACCESS_TOKEN"
STRIKE_RANGE = 5          # Checks ATM +/- 5 strikes (11 strikes total per stock)
MIN_OPTION_VOLUME = 5000  # Minimum traded quantity to avoid illiquid strikes

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

def get_fno_instruments():
    """Downloads Upstox daily NSE JSON master file for F&O stocks and nearest expiry options."""
    url = "https://upstox.com"
    print("Downloading Upstox NSE instrument master...")
    res = requests.get(url)
    with gzip.GzipFile(fileobj=BytesIO(res.content)) as f:
        data = json.loads(f.read().decode("utf-8"))
    
    df = pd.DataFrame(data)
    
    # Filter current month options (nearest expiry)
    opts = df[(df['segment'] == 'NSE_FO') & (df['instrument_type'].isin(['CE', 'PE']))].copy()
    nearest_expiry = opts['expiry'].min()
    opts = opts[opts['expiry'] == nearest_expiry]
    
    # Filter underlying F&O equities
    fno_symbols = opts['name'].unique()
    eqs = df[(df['segment'] == 'NSE_EQ') & (df['trading_symbol'].isin(fno_symbols))].copy()
    
    return eqs, opts

def fetch_full_quotes_batch(instrument_keys):
    """Fetches live OHLC + Volume data in batches of 450 using Upstox Full Market Quote API."""
    quote_map = {}
    url = "https://upstox.com"
    
    for i in range(0, len(instrument_keys), 450):
        batch = instrument_keys[i:i+450]
        params = {"instrument_key": ",".join(batch)}
        res = requests.get(url, headers=HEADERS, params=params).json()
        
        if res.get("status") == "success":
            for key, val in res["data"].items():
                norm_key = key.replace(":", "|")
                quote_map[norm_key] = {
                    "ohlc": val.get("ohlc", {}),
                    "ltp": val.get("last_price", 0),
                    "volume": val.get("volume", 0)
                }
    return quote_map

def run_scanner():
    eqs, opts = get_fno_instruments()
    
    # Step 1: Fetch live quotes for all F&O Equities
    eq_keys = eqs['instrument_key'].tolist()
    eq_quotes = fetch_full_quotes_batch(eq_keys)
    
    # Step 2: Filter stocks with exact Open == Low OR Open == High
    candidates = []
    option_keys_to_fetch = set()
    
    for _, row in eqs.iterrows():
        sym = row['trading_symbol']
        ekey = row['instrument_key']
        q_data = eq_quotes.get(ekey)
        
        if not q_data or not q_data['ohlc']:
            continue
            
        ohlc = q_data['ohlc']
        ltp = q_data['ltp']
        if ohlc.get('open', 0) == 0:
            continue
            
        is_eq_ol = (ohlc['open'] == ohlc['low']) and (ltp > ohlc['open'])
        is_eq_oh = (ohlc['open'] == ohlc['high']) and (ltp < ohlc['open'])
        
        if is_eq_ol or is_eq_oh:
            sym_opts = opts[opts['name'] == sym].copy()
            if sym_opts.empty:
                continue
                
            # Sort unique strikes ascending to easily slice ATM +/- 5 strikes
            unique_strikes = sorted(sym_opts['strike_price'].unique())
            atm_strike = min(unique_strikes, key=lambda x: abs(x - ohlc['open']))
            atm_idx = unique_strikes.index(atm_strike)
            
            start_idx = max(0, atm_idx - STRIKE_RANGE)
            end_idx = min(len(unique_strikes), atm_idx + STRIKE_RANGE + 1)
            selected_strikes = unique_strikes[start_idx:end_idx]
            
            strike_pairs = []
            for strike in selected_strikes:
                ce_row = sym_opts[(sym_opts['strike_price'] == strike) & (sym_opts['instrument_type'] == 'CE')]
                pe_row = sym_opts[(sym_opts['strike_price'] == strike) & (sym_opts['instrument_type'] == 'PE')]
                
                if not ce_row.empty and not pe_row.empty:
                    ce_key = ce_row.iloc['instrument_key']
                    pe_key = pe_row.iloc['instrument_key']
                    step_diff = unique_strikes.index(strike) - atm_idx
                    moneyness = "ATM" if step_diff == 0 else f"ATM{step_diff:+d}"
                    
                    strike_pairs.append({
                        "strike": strike,
                        "moneyness": moneyness,
                        "ce_key": ce_key,
                        "pe_key": pe_key
                    })
                    option_keys_to_fetch.update([ce_key, pe_key])
            
            if strike_pairs:
                candidates.append({
                    "symbol": sym,
                    "eq_ohlc": ohlc,
                    "eq_ltp": ltp,
                    "is_eq_ol": is_eq_ol,
                    "is_eq_oh": is_eq_oh,
                    "strike_pairs": strike_pairs
                })

    if not candidates:
        print("No F&O stocks currently have exact Equity Open=Low or Open=High.")
        return

    # Step 3: Fetch live quotes + volumes for all ATM +/- 5 strikes
    opt_quotes = fetch_full_quotes_batch(list(option_keys_to_fetch))
    
    results = []
    for item in candidates:
        for pair in item['strike_pairs']:
            ce_data = opt_quotes.get(pair['ce_key'])
            pe_data = opt_quotes.get(pair['pe_key'])
            
            if not ce_data or not pe_data:
                continue
                
            # Liquidity filter: skip strikes where either leg lacks minimum volume
            if ce_data['volume'] < MIN_OPTION_VOLUME or pe_data['volume'] < MIN_OPTION_VOLUME:
                continue
                
            ce_o = ce_data['ohlc']
            pe_o = pe_data['ohlc']
            if not ce_o or not pe_o or ce_o.get('open', 0) == 0 or pe_o.get('open', 0) == 0:
                continue
                
            # Exact Open=Low and Open=High checks
            ce_ol = (ce_o['open'] == ce_o['low']) and (ce_data['ltp'] > ce_o['open'])
            ce_oh = (ce_o['open'] == ce_o['high']) and (ce_data['ltp'] < ce_o['open'])
            pe_ol = (pe_o['open'] == pe_o['low']) and (pe_data['ltp'] > pe_o['open'])
            pe_oh = (pe_o['open'] == pe_o['high']) and (pe_data['ltp'] < pe_o['open'])
            
            signal = None
            priority = 99
            
            # BULLISH SETUPS (Stock Open == Low)
            if item['is_eq_ol'] and ce_ol:
                if pe_oh:
                    signal = "🔥 HIGHLIGHT BULLISH (EQ O=L | CE O=L | PE O=H)"
                    priority = 1
                else:
                    signal = "✅ BULLISH (EQ O=L | CE O=L)"
                    priority = 3
                    
            # BEARISH SETUPS (Stock Open == High)
            elif item['is_eq_oh'] and pe_ol:
                if ce_oh:
                    signal = "🔥 HIGHLIGHT BEARISH (EQ O=H | PE O=L | CE O=H)"
                    priority = 2
                else:
                    signal = "🔻 BEARISH (EQ O=H | PE O=L)"
                    priority = 4
                    
            if signal:
                results.append({
                    "Priority": priority,
                    "Signal": signal,
                    "Stock": item['symbol'],
                    "Strike": f"{pair['strike']} ({pair['moneyness']})",
                    "EQ_Open": item['eq_ohlc']['open'],
                    "EQ_LTP": item['eq_ltp'],
                    "CE_Open": ce_o['open'],
                    "CE_LTP": ce_data['ltp'],
                    "CE_Vol": ce_data['volume'],
                    "PE_Open": pe_o['open'],
                    "PE_LTP": pe_data['ltp'],
                    "PE_Vol": pe_data['volume']
                })

    # Step 4: Sort and display
    if results:
        res_df = pd.DataFrame(results)
        res_df = res_df.sort_values(by=["Priority", "Stock", "Strike"]).drop(columns=["Priority"])
        print(f"\n=== LIVE MULTI-STRIKE OHL SCANNER (Min Vol: {MIN_OPTION_VOLUME}) ===")
        print(res_df.to_string(index=False))
    else:
        print("\nNo liquid multi-strike OHL matches found right now.")

if __name__ == "__main__":
    run_scanner()
