import os
import time
import datetime
import requests
import pandas as pd
import pandas_ta as ta

# ==========================================
# 1. CONFIGURATION
# ==========================================
# Reads from GitHub Secrets or local environment variable
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "YOUR_UPSTOX_ACCESS_TOKEN")

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

INDICES = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT"
}

# ==========================================
# 2. AUTOMATED EXPIRY FETCHER
# ==========================================
def get_automated_expiries(index_name, index_key):
    """Fetches active contracts from Upstox and picks Weekly (Tuesday) or Monthly expiry."""
    url = "https://upstox.com"
    params = {"instrument_key": index_key}
    res = requests.get(url, headers=HEADERS, params=params).json()
    
    if res.get("status") != "success" or not res.get("data"):
        return None
        
    # Extract unique sorted expiry dates (YYYY-MM-DD)
    expiries = sorted(list({item["expiry"] for item in res["data"]}))
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    future_expiries = [d for d in expiries if d >= today_str]
    
    if not future_expiries:
        return None

    if index_name == "NIFTY":
        # Pick the nearest Tuesday expiry (weekday() == 1 is Tuesday)
        # Fallback to nearest available expiry if Tuesday was a holiday shifted to Monday
        for exp in future_expiries:
            dt = datetime.datetime.strptime(exp, "%Y-%m-%d").date()
            if dt.weekday() == 1:
                return exp
        return future_expiries[0]
    else:
        # Monthly expiry for BANKNIFTY, FINNIFTY, MIDCPNIFTY
        # Group by (year, month) and take the last expiry of the nearest active month
        first_dt = datetime.datetime.strptime(future_expiries[0], "%Y-%m-%d").date()
        current_month_expiries = [
            exp for exp in future_expiries 
            if datetime.datetime.strptime(exp, "%Y-%m-%d").month == first_dt.month
        ]
        return current_month_expiries[-1]

# ==========================================
# 3. CANDLE & OPTION CHAIN FUNCTIONS
# ==========================================
def get_candles(instrument_key):
    """Fetches historical + live intraday 1-min candles and resamples to 5-min."""
    encoded_key = requests.utils.quote(instrument_key)
    to_date = datetime.date.today().strftime("%Y-%m-%d")
    from_date = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    
    hist_url = f"https://upstox.com{encoded_key}/1minute/{to_date}/{from_date}"
    intra_url = f"https://upstox.comintraday/{encoded_key}/1minute"
    
    hist_res = requests.get(hist_url, headers=HEADERS).json()
    intra_res = requests.get(intra_url, headers=HEADERS).json()
    
    candles = []
    if hist_res.get("status") == "success":
        candles.extend(hist_res["data"]["candles"])
    if intra_res.get("status") == "success":
        candles.extend(intra_res["data"]["candles"])
        
    if not candles:
        return None

    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").set_index("timestamp")
    
    df_5m = df.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    
    return df_5m

def get_target_ce_keys(index_key, expiry_date, spot_price):
    """Fetches Option Chain and returns ATM and +1/+2 OTM Call instrument keys."""
    url = "https://upstox.com"
    params = {"instrument_key": index_key, "expiry_date": expiry_date}
    res = requests.get(url, headers=HEADERS, params=params).json()
    
    if res.get("status") != "success":
        return []
        
    ce_list = []
    for item in res["data"]:
        strike = item["strike_price"]
        if strike >= spot_price - 100 and "call_options" in item:
            ce_list.append((strike, item["call_options"]["instrument_key"]))
            
    ce_list.sort(key=lambda x: x[0])
    return ce_list[:3]

# ==========================================
# 4. INDICATOR CHECK (200 SMA + SUPERTREND)
# ==========================================
def check_bullish_setup(df):
    """Checks if Close > 200 SMA and Close > SuperTrend(10,3)."""
    if df is None or len(df) < 205:
        return False, {}

    df["SMA_200"] = ta.sma(df["close"], length=200)
    st = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3)
    df["ST_DIR"] = st["SUPERTd_10_3.0"]  # 1 = Bullish, -1 = Bearish
    
    latest = df.iloc[-1]
    close_price = latest["close"]
    
    above_sma = close_price > latest["SMA_200"]
    above_st = latest["ST_DIR"] == 1
    
    is_bullish = above_sma and above_st
    details = {
        "close": round(close_price, 2),
        "sma200": round(latest["SMA_200"], 2),
        "supertrend_bullish": above_st
    }
    return is_bullish, details

# ==========================================
# 5. SCANNER EXECUTION
# ==========================================
def run_scan_once():
    print(f"=== Scan started at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    for name, inst_key in INDICES.items():
        expiry = get_automated_expiries(name, inst_key)
        if not expiry:
            print(f"[ERROR] Could not fetch expiry for {name}")
            continue
            
        df_index = get_candles(inst_key)
        idx_bullish, idx_info = check_bullish_setup(df_index)
        
        if idx_bullish:
            print(f"[MATCH] {name} (Exp: {expiry}) ABOVE 200 SMA & SuperTrend | Close: {idx_info['close']}")
            ce_contracts = get_target_ce_keys(inst_key, expiry, idx_info["close"])
            
            for strike, ce_key in ce_contracts:
                df_ce = get_candles(ce_key)
                ce_bullish, ce_info = check_bullish_setup(df_ce)
                
                if ce_bullish:
                    print(f"   >>> [CE CONFIRMED] {name} {strike} CE ({expiry}) | Price: {ce_info['close']} | SMA200: {ce_info['sma200']}")
                else:
                    print(f"   --- {name} {strike} CE not aligned ({ce_info})")
        else:
            print(f"[WAIT] {name} (Exp: {expiry}) not aligned. {idx_info}")

if __name__ == "__main__":
    # Runs once if triggered by GitHub Actions, or loops locally every 5 mins
    if os.getenv("GITHUB_ACTIONS") == "true":
        run_scan_once()
    else:
        while True:
            run_scan_once()
            time.sleep(300)
