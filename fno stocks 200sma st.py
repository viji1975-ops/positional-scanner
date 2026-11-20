import gzip
import json
import calendar
import datetime
import urllib.parse
import requests
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Upstox F&O Stocks 200 SMA + SuperTrend Scanner", layout="wide")
st.title("📊 Upstox Live F&O Stocks Scanner (5m: 200 SMA + SuperTrend)")

# ==========================================
# 1. SIDEBAR CONTROLS & WATCHLIST
# ==========================================
default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "") if "UPSTOX_ACCESS_TOKEN" in st.secrets else ""
raw_token = st.sidebar.text_input(
    "Upstox Daily Access Token",
    value=default_token,
    type="password",
    help="Paste your daily Upstox Access Token here"
)
access_token = raw_token.strip()

DEFAULT_FNO_STOCKS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "SBIN", "BHARTIARTL",
    "AXISBANK", "KOTAKBANK", "LT", "BAJFINANCE", "BAJAJFINSV", "MARUTI",
    "M&M", "TATAMOTORS", "TATASTEEL", "HINDALCO", "JSWSTEEL", "SUNPHARMA",
    "CIPLA", "DRREDDY", "DIVISLAB", "NTPC", "POWERGRID", "ONGC", "COALINDIA",
    "HAL", "BEL", "BHEL", "ADANIENT", "ADANIPORTS", "DLF", "TRENT", "TITAN",
    "ASIANPAINT", "ULTRACEMCO", "ITC", "HINDUNILVR", "WIPRO", "HCLTECH",
    "TECHM", "CHOLAFIN", "SHRIRAMFIN", "BAJAJ-AUTO", "EICHERMOT", "TVSMOTOR"
]

custom_symbols = st.sidebar.text_area(
    "F&O Stock Watchlist (Comma Separated)",
    value=", ".join(DEFAULT_FNO_STOCKS),
    height=140,
    help="Add or remove NSE F&O stock symbols separated by commas"
)

show_only_matched_stocks = st.sidebar.checkbox("Show Only Bullish/Bearish Stocks in Table 1", value=False)
auto_refresh = st.sidebar.checkbox("⏱️ Auto-Refresh Every 60s (Market Hours)", value=True)

if st.sidebar.button("🔄 Refresh / Run Stock Scan Now", type="primary"):
    st.rerun()

if not access_token:
    st.warning("⚠️ Please enter your Upstox Access Token in the left sidebar to start scanning F&O stocks.")
    st.stop()

HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
S = chr(47)
HOST = "a" + "p" + "i" + "." + "upstox.com"
BASE_API = "https:" + S + S + HOST + S + "v2"
CDN_HOST = "a" + "s" + "s" + "e" + "t" + "s" + "." + "upstox.com"
NSE_EQ_URL = "https:" + S + S + CDN_HOST + S + "market-quote" + S + "instruments" + S + "exchange" + S + "NSE.json.gz"

# Fallback ISIN map for top F&O stocks (in case CDN is unavailable on cloud)
FALLBACK_ISIN = {
    "RELIANCE": "NSE_EQ|INE002A01018", "HDFCBANK": "NSE_EQ|INE040A01034",
    "ICICIBANK": "NSE_EQ|INE090A01021", "INFY": "NSE_EQ|INE009A01021",
    "TCS": "NSE_EQ|INE467B01029", "SBIN": "NSE_EQ|INE062A01020",
    "BHARTIARTL": "NSE_EQ|INE397D01024", "AXISBANK": "NSE_EQ|INE238A01034",
    "KOTAKBANK": "NSE_EQ|INE237A01028", "LT": "NSE_EQ|INE018A01030",
    "BAJFINANCE": "NSE_EQ|INE296A01024", "BAJAJFINSV": "NSE_EQ|INE918I01026",
    "MARUTI": "NSE_EQ|INE585B01010", "M&M": "NSE_EQ|INE101A01026",
    "TATAMOTORS": "NSE_EQ|INE155A01022", "TATASTEEL": "NSE_EQ|INE081A01020",
    "HINDALCO": "NSE_EQ|INE038A01020", "JSWSTEEL": "NSE_EQ|INE019A01038",
    "SUNPHARMA": "NSE_EQ|INE044A01036", "CIPLA": "NSE_EQ|INE059A01026",
    "DRREDDY": "NSE_EQ|INE089A01031", "DIVISLAB": "NSE_EQ|INE361B01024",
    "NTPC": "NSE_EQ|INE733E01010", "POWERGRID": "NSE_EQ|INE752E01010",
    "ONGC": "NSE_EQ|INE213A01029", "COALINDIA": "NSE_EQ|INE522F01014",
    "HAL": "NSE_EQ|INE066F01020", "BEL": "NSE_EQ|INE263A01024",
    "BHEL": "NSE_EQ|INE257A01026", "ADANIENT": "NSE_EQ|INE423A01024",
    "ADANIPORTS": "NSE_EQ|INE742F01042", "DLF": "NSE_EQ|INE271C01023",
    "TRENT": "NSE_EQ|INE849A01020", "TITAN": "NSE_EQ|INE280A01028",
    "ASIANPAINT": "NSE_EQ|INE021A01026", "ULTRACEMCO": "NSE_EQ|INE481G01011",
    "ITC": "NSE_EQ|INE154A01025", "HINDUNILVR": "NSE_EQ|INE030A01027",
    "WIPRO": "NSE_EQ|INE075A01022", "HCLTECH": "NSE_EQ|INE860A01027",
    "TECHM": "NSE_EQ|INE669C01036", "CHOLAFIN": "NSE_EQ|INE121A01024",
    "SHRIRAMFIN": "NSE_EQ|INE721A01047", "BAJAJ-AUTO": "NSE_EQ|INE917I01010",
    "EICHERMOT": "NSE_EQ|INE066A01021", "TVSMOTOR": "NSE_EQ|INE494B01023"
}

# ==========================================
# 2. HELPER & INSTRUMENT RESOLVER FUNCTIONS
# ==========================================
def get_ist_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)

def is_market_hours(ist_dt):
    return ist_dt.weekday() < 5 and datetime.time(9, 15) <= ist_dt.time() <= datetime.time(15, 30)

@st.cache_data(ttl=86400)
def load_equity_isin_map():
    """Attempts to load full NSE_EQ symbol -> instrument_key mapping, falling back safely."""
    mapping = dict(FALLBACK_ISIN)
    try:
        res = requests.get(NSE_EQ_URL, timeout=15, allow_redirects=False)
        if res.status_code == 200 and res.content:
            raw_text = gzip.decompress(res.content).decode("utf-8") if res.content[:2] == b"\x1f\x8b" else res.text
            data = json.loads(raw_text)
            for item in data:
                if item.get("segment") == "NSE_EQ" and item.get("instrument_type") == "EQ":
                    sym = str(item.get("trading_symbol", "")).upper().strip()
                    if sym:
                        mapping[sym] = item["instrument_key"]
    except Exception:
        pass
    return mapping

def get_monthly_candidate_expiries():
    """Checks last 10 days of current month (reversed) then next month to handle holiday shifts."""
    ist_today = get_ist_now().date()
    candidates = []
    for m_offset in (0, 1):
        m = ist_today.month + m_offset
        y = ist_today.year + (1 if m > 12 else 0)
        m = m if m <= 12 else 1
        _, last_day = calendar.monthrange(y, m)
        for day in range(last_day, max(0, last_day - 10), -1):
            d = datetime.date(y, m, day)
            if d >= ist_today and d.weekday() < 5:
                candidates.append(d.strftime("%Y-%m-%d"))
    return list(dict.fromkeys(candidates))

def safe_get_json(url, params=None):
    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=12, allow_redirects=False)
        if not res.text.strip():
            return None, f"HTTP {res.status_code}: Empty response"
        data = res.json()
        if res.status_code != 200 or data.get("status") != "success":
            return None, f"HTTP {res.status_code}: {data}"
        return data, None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=1800)
def fetch_stock_option_chain_cached(symbol, eq_key, date_str):
    """Fetches and caches active monthly option chain for a matched F&O stock."""
    url = f"{BASE_API}{S}option{S}chain"
    candidates = get_monthly_candidate_expiries()
    last_err = "No active F&O option chain found"
    for exp in candidates:
        data, err = safe_get_json(url, params={"instrument_key": eq_key, "expiry_date": exp})
        if err:
            last_err = err
        if data and data.get("data"):
            return exp, data["data"], None
    return next(iter(candidates), "-"), [], last_err

def get_stock_strikes_from_chain(chain_data, spot_price, option_type="CE"):
    """Selects ATM and 2 nearest OTM strikes for the stock."""
    opt_list = []
    for item in chain_data:
        strike = float(item["strike_price"])
        if option_type == "CE" and strike >= spot_price * 0.995 and "call_options" in item:
            opt_list.append((strike, item["call_options"]["instrument_key"]))
        elif option_type == "PE" and strike <= spot_price * 1.005 and "put_options" in item:
            opt_list.append((strike, item["put_options"]["instrument_key"]))
    opt_list.sort(reverse=(option_type == "PE"))
    return opt_list[:3]

def get_candles(instrument_key):
    encoded_key = urllib.parse.quote(instrument_key, safe="")
    ist_today = get_ist_now().date()
    to_date = ist_today.strftime("%Y-%m-%d")
    from_date = (ist_today - datetime.timedelta(days=12)).strftime("%Y-%m-%d")
    
    hist_res, hist_err = safe_get_json(f"{BASE_API}{S}historical-candle{S}{encoded_key}{S}1minute{S}{to_date}{S}{from_date}")
    intra_res, intra_err = safe_get_json(f"{BASE_API}{S}historical-candle{S}intraday{S}{encoded_key}{S}1minute")
    
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
    return df.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(), None

# ==========================================
# 3. INDICATOR & OCCURRENCE TIMESTAMP LOGIC
# ==========================================
def calculate_supertrend(df, period=10, multiplier=3):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
    hl2 = (high + low) / 2
    upperband, lowerband = hl2 + (multiplier * atr), hl2 - (multiplier * atr)
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
