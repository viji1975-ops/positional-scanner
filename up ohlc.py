import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Upstox OHOL Scanner", layout="wide")

# Safely load token from Streamlit Secrets or Environment Variables
ACCESS_TOKEN = st.secrets.get("UPSTOX_ACCESS_TOKEN", os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

INSTRUMENTS = {
    "NSE_EQ|INE467B01029": "NSE:TCS",
    "NSE_EQ|INE002A01018": "NSE:RELIANCE",
    "NSE_EQ|INE040A01034": "NSE:HDFCBANK",
    "NSE_EQ|INE090A01021": "NSE:ICICIBANK",
    "NSE_EQ|INE208A01029": "NSE:ASHOKLEY",
    "NSE_EQ|INE463V01026": "NSE:ANANDRATHI",
}

@st.cache_data(ttl=3600)
def get_historical_stats(instrument_key):
    """Fetches daily candles to compute 14-day ATR and 20-day Avg Volume."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    
    # Safe URL construction without spaces
    clean_key = instrument_key.strip()
    url = f"https://upstox.com{clean_key}/day/{to_date}/{from_date}"
    
    resp = requests.get(url, headers=HEADERS, timeout=10).json()
    candles = resp.get("data", {}).get("candles", [])
    
    if len(candles) < 15:
        return None, None

    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume", "oi"])
    df = df.iloc[::-1].reset_index(drop=True)

    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
    atr_14 = df["tr"].tail(14).mean()
    avg_vol_20 = df["volume"].tail(20).mean()
    
    return round(atr_14, 2), avg_vol_20

def scan_ohol():
    if not ACCESS_TOKEN:
        st.error("Missing UPSTOX_ACCESS_TOKEN. Please add it in Streamlit App Settings -> Secrets.")
        return pd.DataFrame()

    # Passing params as a dict prevents LocationParseError completely
    url = "https://upstox.com"
    params = {"instrument_key": ",".join(k.strip() for k in INSTRUMENTS.keys())}
    
    response = requests.get(url, headers=HEADERS, params=params, timeout=10).json()
    if response.get("status") != "success":
        st.error(f"Upstox API Error: {response}")
        return pd.DataFrame()

    quotes = response.get("data", {})
    results = []

    for key, symbol in INSTRUMENTS.items():
        resp_key = key.replace("|", ":")
        data = quotes.get(resp_key)
        if not data:
            continue

        ohlc = data.get("ohlc", {})
        open_p = ohlc.get("open", 0)
        high_p = ohlc.get("high", 0)
        low_p = ohlc.get("low", 0)
        ltp = data.get("last_price", 0)
        curr_vol = data.get("volume", 0)

        if open_p == 0:
            continue

        tolerance = open_p * 0.0005
        is_open_high = abs(open_p - high_p) <= tolerance
        is_open_low = abs(open_p - low_p) <= tolerance

        if not (is_open_high or is_open_low):
            continue

        atr, avg_vol = get_historical_stats(key)
        if not atr or not avg_vol:
            continue

        risk_unit = atr * 0.5
        vol_ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0

        if vol_ratio >= 4.0:
            power = "🔥 Ultra"
        elif vol_ratio >= 2.0:
            power = "⚡ Strong"
        else:
            power = "Normal"

        if is_open_high:
            pattern = f"Open=High ({open_p:.2f})"
            status = "Active" if ltp <= open_p else "Reversed"
            t1 = round(open_p - risk_unit, 1)
            t2 = round(open_p - (risk_unit * 2), 1)
            rev_tgt = str(round(open_p + risk_unit, 1)) if status == "Reversed" else "N/A"
        else:
            pattern = f"Open=Low ({open_p:.2f})"
            status = "Active" if ltp >= open_p else "Reversed"
            t1 = round(open_p + risk_unit, 1)
            t2 = round(open_p + (risk_unit * 2), 1)
            rev_tgt = str(round(open_p - risk_unit, 1)) if status == "Reversed" else "N/A"

        results.append({
            "Symbol": symbol,
            "Pattern": pattern,
            "Status": status,
            "Price (₹)": f"{ltp:.2f}",
            "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
            "Rev Target": rev_tgt,
            "Volume": f"{vol_ratio}x",
            "Power": power
        })

    return pd.DataFrame(results)

# --- Streamlit UI ---
st.title("📊 Intraday Open=High / Open=Low Scanner")

if st.button("🔄 Refresh Live Data"):
    st.rerun()

df_results = scan_ohol()

if df_results.empty:
    st.info("No Open=High or Open=Low setups detected right now (or market is closed).")
else:
    st.dataframe(df_results, use_container_width=True, hide_index=True)
