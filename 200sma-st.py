import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upstox 200 SMA + SuperTrend Scanner", layout="wide")
st.title("📈 Upstox Live Intraday Scanner (5m: 200 SMA + SuperTrend)")

default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "") if "UPSTOX_ACCESS_TOKEN" in st.secrets else ""
raw_token = st.sidebar.text_input("Upstox Daily Access Token", value=default_token, type="password")
access_token = raw_token.strip()

if st.sidebar.button("🔄 Refresh / Run Scan Now", type="primary"):
    st.rerun()

if not access_token:
    st.warning("⚠️ Please enter your Upstox Access Token in the left sidebar.")
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

def safe_get_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if not res.text.strip():
            return None, f"HTTP {res.status_code}: Empty response (Token expired or invalid)."
        try:
            data = res.json()
            if res.status_code != 200 or data.get("status") != "success":
                return None, f"HTTP {res.status_code}: {data}"
            return data, None
        except ValueError:
            return None, f"HTTP {res.status_code}: Upstox blocked Streamlit Cloud US IP (Returned HTML)."
    except Exception as e:
        return None, str(e)

def get_candles(instrument_key):
    encoded_key = requests.utils.quote(instrument_key)
    ist_today = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)).date()
    to_date = ist_today.strftime("%Y-%m-%d")
    from_date = (ist_today - datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    
    hist_url = f"https://upstox.com{encoded_key}/1minute/{to_date}/{from_date}"
    intra_url = f"https://upstox.comintraday/{encoded_key}/1minute"
    
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
for name, inst_key in INDICES.items():
    df_index, err = get_candles(inst_key)
    if df_index is None:
        st.error(f"❌ {name}: {err}")
        continue
        
    idx_bullish, idx_info = check_bullish_setup(df_index)
    index_rows.append({
        "Index": name,
        "Close": idx_info["close"],
        "200 SMA": idx_info["sma200"],
        "SuperTrend (10,3)": idx_info["st"],
        "Status": "✅ MATCH (Above Both)" if idx_bullish else "⏳ Waiting"
    })

if index_rows:
    st.dataframe(pd.DataFrame(index_rows), use_container_width=True, hide_index=True)
