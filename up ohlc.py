import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Upstox OHOL Scanner", layout="wide")

# --- Sidebar: Daily Upstox Token Input ---
st.sidebar.header("🔑 Upstox API Settings")
default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()

user_token = st.sidebar.text_input(
    "Paste Daily Access Token",
    value="",
    type="password",
    placeholder="Paste today's Upstox token here...",
    help="Upstox tokens expire daily at 3:30 AM IST. Paste your fresh morning token here."
)

# Use the sidebar token if provided; otherwise fall back to Streamlit Secrets
ACCESS_TOKEN = user_token.strip() if user_token.strip() else default_token

if user_token.strip():
    st.sidebar.success("✅ Using token pasted in sidebar")
elif default_token:
    st.sidebar.info("ℹ️ Using token from Streamlit Secrets")
else:
    st.sidebar.warning("⚠️ No token found. Paste your token above.")

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
def get_historical_stats(instrument_key, token):
    """Fetches daily candles to compute 14-day ATR and 20-day Avg Volume."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    
    clean_key = instrument_key.strip()
    url = f"https://upstox.com{clean_key}/day/{to_date}/{from_date}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code != 200 or not res.text.strip():
        return None, None

    try:
        candles = res.json().get("data", {}).get("candles", [])
    except Exception:
        return None, None
    
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
        st.warning("👈 Please paste your daily Upstox Access Token in the left sidebar to start scanning.")
        return pd.DataFrame()

    url = "https://upstox.com"
    params = {"instrument_key": ",".join(k.strip() for k in INSTRUMENTS.keys())}
    
    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=10)
    except requests.RequestException as e:
        st.error(f"Network error connecting to Upstox: {e}")
        return pd.DataFrame()

    if res.status_code == 401:
        st.error("🔒 Token Expired or Invalid (HTTP 401). Please generate a fresh Upstox token for today and paste it in the left sidebar.")
        return pd.DataFrame()
    elif res.status_code != 200 or not res.text.strip():
        st.error(f"Upstox API Error (HTTP {res.status_code}): {res.text or 'Empty response'}")
        return pd.DataFrame()

    try:
        response = res.json()
    except Exception:
        st.error(f"Invalid response from Upstox: {res.text[:200]}")
        return pd.DataFrame()

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

        atr, avg_vol = get_historical_stats(key, ACCESS_TOKEN)
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

def style_scanner_table(df):
    """Applies color styling matching your screenshot."""
    def highlight_pattern(val):
        if "Open=High" in str(val):
            return "color: #ff5252; font-weight: bold;"
        elif "Open=Low" in str(val):
            return "color: #4caf50; font-weight: bold;"
        return ""

    def highlight_status(val):
        return "color: #4caf50; font-weight: bold;" if val == "Active" else "color: #ff9800; font-weight: bold;"

    def highlight_power(val):
        if "Ultra" in str(val):
            return "background-color: #9c27b0; color: white; font-weight: bold;"
        elif "Strong" in str(val):
            return "background-color: #2196f3; color: white; font-weight: bold;"
        return ""

    return (
        df.style
        .map(highlight_pattern, subset=["Pattern"])
        .map(highlight_status, subset=["Status"])
        .map(lambda _: "color: #00bcd4; font-weight: bold;", subset=["Normal Tgt (1:1|1:2)"])
        .map(highlight_power, subset=["Power"])
    )

# --- Main App UI ---
st.title("📊 Intraday Open=High / Open=Low Scanner")

if st.button("🔄 Refresh Live Data"):
    st.rerun()

df_results = scan_ohol()

if not df_results.empty:
    st.dataframe(style_scanner_table(df_results), use_container_width=True, hide_index=True)
elif ACCESS_TOKEN:
    st.info("No Open=High or Open=Low setups detected right now (check again after 9:15 AM IST market open).")
