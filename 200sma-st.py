import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upstox 200 SMA + SuperTrend Scanner", layout="wide")
st.title("📈 Upstox Live Intraday Scanner (5m: 200 SMA + SuperTrend)")

# ==========================================
# 1. SIDEBAR TOKEN INPUT
# ==========================================
default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "")
access_token = st.sidebar.text_input(
    "Upstox Daily Access Token", 
    value=default_token, 
    type="password",
    help="Paste your daily Upstox Access Token here"
)

if st.sidebar.button("🔄 Refresh / Run Scan Now", type="primary"):
    st.rerun()

if not access_token:
    st.warning("⚠️ Please enter your Upstox Access Token in the left sidebar (or add it to Streamlit Secrets) to start scanning.")
    st.stop()

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {access_token}"
}

INDICES = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT"
}

# ==========================================
# 2. AUTOMATED EXPIRY & DATA FUNCTIONS
# ==========================================
def get_automated_expiries(index_name, index_key):
    url = "https://upstox.com"
    res = requests.get(url, headers=HEADERS, params={"instrument_key": index_key}).json()
    
    if res.get("status") != "success" or not res.get("data"):
        return None, res.get("errors", "API Error")
        
    expiries = sorted(list({item["expiry"] for item in res["data"]}))
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    future_expiries = [d for d in expiries if d >= today_str]
    
    if not future_expiries:
        return None, "No future expiries found"

    if index_name == "NIFTY":
        for exp in future_expiries:
            dt = datetime.datetime.strptime(exp, "%Y-%m-%d").date()
            if dt.weekday() == 1:  # Tuesday
                return exp, None
        return future_expiries[0], None
    else:
        first_dt = datetime.datetime.strptime(future_expiries[0], "%Y-%m-%d").date()
        current_month_expiries = [
            exp for exp in future_expiries 
            if datetime.datetime.strptime(exp, "%Y-%m-%d").month == first_dt.month
        ]
        return current_month_expiries[-1], None

def get_candles(instrument_key):
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
# 3. INDICATOR CALCULATION
# ==========================================
def calculate_supertrend(df, period=10, multiplier=3):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    
    hl2 = (high + low) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    in_uptrend = [True] * len(df)
    
    for i in range(1, len(df)):
        if close.iloc[i] > upperband.iloc[i - 1]:
            in_uptrend[i] = True
        elif close.iloc[i] < lowerband.iloc[i - 1]:
            in_uptrend[i] = False
        else:
            in_uptrend[i] = in_uptrend[i - 1]
            if in_uptrend[i] and lowerband.iloc[i] < lowerband.iloc[i - 1]:
                lowerband.iloc[i] = lowerband.iloc[i - 1]
            if not in_uptrend[i] and upperband.iloc[i] > upperband.iloc[i - 1]:
                upperband.iloc[i] = upperband.iloc[i - 1]
                
    return pd.Series(np.where(in_uptrend, 1, -1), index=df.index)

def check_bullish_setup(df):
    if df is None or len(df) < 205:
        return False, {"close": "-", "sma200": "-", "st": "Insufficient Data"}

    df["SMA_200"] = df["close"].rolling(window=200).mean()
    df["ST_DIR"] = calculate_supertrend(df, period=10, multiplier=3)
    
    latest = df.iloc[-1]
    close_price = float(latest["close"])
    sma_200 = float(latest["SMA_200"])
    above_sma = close_price > sma_200
    above_st = latest["ST_DIR"] == 1
    
    return bool(above_sma and above_st), {
        "close": round(close_price, 2),
        "sma200": round(sma_200, 2),
        "st": "🟢 Bullish" if above_st else "🔴 Bearish"
    }

# ==========================================
# 4. RENDER DASHBOARD
# ==========================================
st.caption(f"Last scanned: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")

index_rows = []
ce_rows = []

with st.spinner("Fetching live market data from Upstox..."):
    for name, inst_key in INDICES.items():
        expiry, err = get_automated_expiries(name, inst_key)
        if not expiry:
            st.error(f"❌ {name} Error: {err} (Check if your Upstox Token is valid for today)")
            continue
            
        df_index = get_candles(inst_key)
        idx_bullish, idx_info = check_bullish_setup(df_index)
        
        index_rows.append({
            "Index": name,
            "Auto Expiry": expiry,
            "Close": idx_info["close"],
            "200 SMA": idx_info["sma200"],
            "SuperTrend (10,3)": idx_info["st"],
            "Status": "✅ MATCH (Above Both)" if idx_bullish else "⏳ Waiting"
        })
        
        if idx_bullish:
            ce_contracts = get_target_ce_keys(inst_key, expiry, idx_info["close"])
            for strike, ce_key in ce_contracts:
                df_ce = get_candles(ce_key)
                ce_bullish, ce_info = check_bullish_setup(df_ce)
                ce_rows.append({
                    "Index": name,
                    "Contract": f"{strike} CE",
                    "Expiry": expiry,
                    "CE Close": ce_info["close"],
                    "CE 200 SMA": ce_info["sma200"],
                    "CE SuperTrend": ce_info["st"],
                    "Signal": "🚀 CONFIRMED BUY SETUP" if ce_bullish else "⏳ CE Not Aligned"
                })

st.subheader("1. Index Status (5-Minute Timeframe)")
if index_rows:
    st.dataframe(pd.DataFrame(index_rows), use_container_width=True, hide_index=True)

st.subheader("2. Matching Call Options (CE) Status")
if ce_rows:
    st.dataframe(pd.DataFrame(ce_rows), use_container_width=True, hide_index=True)
else:
    st.info("No indices are currently above both 200 SMA and SuperTrend, or no CE contracts matched yet.")
