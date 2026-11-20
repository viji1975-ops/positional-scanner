import calendar
import datetime
import urllib.parse
import requests
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upstox 200 SMA + SuperTrend Scanner", layout="wide")
st.title("📈 Upstox Live Intraday Scanner (5m: 200 SMA + SuperTrend)")

default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "") if "UPSTOX_ACCESS_TOKEN" in st.secrets else ""
raw_token = st.sidebar.text_input(
    "Upstox Daily Access Token", 
    value=default_token, 
    type="password",
    help="Paste your daily Upstox Access Token here"
)
access_token = raw_token.strip()

if st.sidebar.button("🔄 Refresh / Run Scan Now", type="primary"):
    st.rerun()

if not access_token:
    st.warning("⚠️ Please enter your Upstox Access Token in the left sidebar to start scanning.")
    st.stop()

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {access_token}"
}

S = chr(47)
HOST = "a" + "p" + "i" + "." + "upstox.com"
BASE_API = "https:" + S + S + HOST + S + "v2"

INDICES = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT"
}

def get_last_weekday_of_month(year, month, target_weekday):
    _, last_day = calendar.monthrange(year, month)
    d = datetime.date(year, month, last_day)
    while d.weekday() != target_weekday:
        d -= datetime.timedelta(days=1)
    return d

def get_candidate_expiries(index_name):
    ist_today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).date()
    candidates = []
    if index_name == "NIFTY":
        # Nearest Tuesday (1) or Thursday (3) within next 10 days
        for offset in range(0, 10):
            d = ist_today + datetime.timedelta(days=offset)
            if d.weekday() in (1, 3):
                candidates.append(d.strftime("%Y-%m-%d"))
    else:
        # Monthly expiry: Last Tuesday (1) or Last Thursday (3) of current/next month
        for m_offset in (0, 1):
            m = ist_today.month + m_offset
            y = ist_today.year + (1 if m > 12 else 0)
            m = m if m <= 12 else 1
            for wd in (1, 3):
                d = get_last_weekday_of_month(y, m, wd)
                if d >= ist_today:
                    candidates.append(d.strftime("%Y-%m-%d"))
    return sorted(list(set(candidates)))

def safe_get_json(url, params=None):
    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=15, allow_redirects=False)
        if res.status_code in (301, 302, 307, 308):
            return None, f"HTTP {res.status_code} Redirect blocked (Location: {res.headers.get('Location')})"
        if not res.text.strip():
            return None, f"HTTP {res.status_code}: Empty response (Check Token validity)."
        data = res.json()
        if res.status_code != 200 or data.get("status") != "success":
            return None, f"HTTP {res.status_code}: {data}"
        return data, None
    except Exception as e:
        return None, str(e)

def get_valid_chain_and_strikes(index_name, index_key, spot_price):
    url = f"{BASE_API}{S}option{S}chain"
    candidates = get_candidate_expiries(index_name)
    last_err = "No active option chain found"
    for exp in candidates:
        data, err = safe_get_json(url, params={"instrument_key": index_key, "expiry_date": exp})
        if err:
            last_err = err
        if data and data.get("data"):
            ce_list = []
            for item in data["data"]:
                strike = float(item["strike_price"])
                if strike >= spot_price - 100 and "call_options" in item:
                    ce_list.append((strike, item["call_options"]["instrument_key"]))
            ce_list.sort()
            if ce_list:
                return exp, ce_list[:3], None
    fallback_exp = next(iter(candidates), "-")
    return fallback_exp, [], f"{last_err} (Tried: {', '.join(candidates)})"

def get_candles(instrument_key):
    encoded_key = urllib.parse.quote(instrument_key, safe="")
    ist_today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).date()
    to_date = ist_today.strftime("%Y-%m-%d")
    from_date = (ist_today - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    
    hist_url = f"{BASE_API}{S}historical-candle{S}{encoded_key}{S}1minute{S}{to_date}{S}{from_date}"
    intra_url = f"{BASE_API}{S}historical-candle{S}intraday{S}{encoded_key}{S}1minute"
    
    hist_res, hist_err = safe_get_json(hist_url)
    intra_res, intra_err = safe_get_json(intra_url)
    
    candles = []
    if hist_res and hist_res.get("data", {}).get("candles"):
        candles.extend(hist_res["data"]["candles"])
    if intra_res and intra_res.get("data", {}).get("candles"):
        candles.extend(intra_res["data"]["candles"])
        
    if not candles:
        return None, hist_err or intra_err

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
    
    return df_5m, None

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

ist_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)
st.caption(f"Last scanned: {ist_now.strftime('%Y-%m-%d %H:%M:%S')} IST")

index_rows = []
ce_rows = []

with st.spinner("Scanning 5-minute charts for Indices & Call Options..."):
    for name, inst_key in INDICES.items():
        df_index, err = get_candles(inst_key)
        if df_index is None:
            st.error(f"❌ {name}: {err}")
            continue
            
        idx_bullish, idx_info = check_bullish_setup(df_index)
        spot_price = idx_info["close"] if isinstance(idx_info["close"], float) else float(df_index["close"].iloc[-1])
        expiry, ce_contracts, ce_err = get_valid_chain_and_strikes(name, inst_key, spot_price)
        
        index_rows.append({
            "Index": name,
            "Auto Expiry": expiry,
            "Close": idx_info["close"],
            "200 SMA": idx_info["sma200"],
            "SuperTrend (10,3)": idx_info["st"],
            "Status": "✅ MATCH (Above Both)" if idx_bullish else "⏳ Waiting"
        })
        
        if idx_bullish:
            if ce_err:
                st.warning(f"⚠️ {name} Option Chain: {ce_err}")
            for strike, ce_key in ce_contracts:
                df_ce, _ = get_candles(ce_key)
                ce_bullish, ce_info = check_bullish_setup(df_ce)
                ce_rows.append({
                    "Index": name,
                    "Contract": f"{int(strike)} CE",
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
