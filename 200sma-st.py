import calendar
import datetime
import urllib.parse
import requests
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Upstox 200 SMA + SuperTrend Scanner", layout="wide")
st.title("📈 Upstox Live Intraday Scanner (5m: 200 SMA + SuperTrend)")

# ==========================================
# 1. SIDEBAR CONTROLS
# ==========================================
default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "") if "UPSTOX_ACCESS_TOKEN" in st.secrets else ""
raw_token = st.sidebar.text_input(
    "Upstox Daily Access Token", 
    value=default_token, 
    type="password",
    help="Paste your daily Upstox Access Token here"
)
access_token = raw_token.strip()

auto_refresh = st.sidebar.checkbox("⏱️ Auto-Refresh Every 60s (Market Hours)", value=True)

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

# ==========================================
# 2. EXPIRY & API HELPER FUNCTIONS
# ==========================================
def get_ist_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)

def is_market_hours(ist_dt):
    if ist_dt.weekday() >= 5:  # Saturday / Sunday
        return False
    t = ist_dt.time()
    return datetime.time(9, 15) <= t <= datetime.time(15, 30)

def get_last_weekday_of_month(year, month, target_weekday):
    _, last_day = calendar.monthrange(year, month)
    d = datetime.date(year, month, last_day)
    while d.weekday() != target_weekday:
        d -= datetime.timedelta(days=1)
    return d

def get_candidate_expiries(index_name):
    ist_today = get_ist_now().date()
    candidates = []
    if index_name == "NIFTY":
        for offset in range(0, 8):
            d = ist_today + datetime.timedelta(days=offset)
            if d.weekday() < 5:
                candidates.append(d.strftime("%Y-%m-%d"))
    else:
        for m_offset in (0, 1):
            m = ist_today.month + m_offset
            y = ist_today.year + (1 if m > 12 else 0)
            m = m if m <= 12 else 1
            for wd in (1, 3, 2):
                d = get_last_weekday_of_month(y, m, wd)
                if d >= ist_today:
                    candidates.append(d.strftime("%Y-%m-%d"))
    seen = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered

def safe_get_json(url, params=None):
    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=15, allow_redirects=False)
        if res.status_code in (301, 302, 307, 308):
            return None, f"HTTP {res.status_code} Redirect blocked"
        if not res.text.strip():
            return None, f"HTTP {res.status_code}: Empty response"
        data = res.json()
        if res.status_code != 200 or data.get("status") != "success":
            return None, f"HTTP {res.status_code}: {data}"
        return data, None
    except Exception as e:
        return None, str(e)

def get_valid_chain_and_strikes(index_name, index_key, spot_price, option_type="CE"):
    """Fetches ATM and +1/+2 OTM strikes for either CE (bullish) or PE (bearish)."""
    url = f"{BASE_API}{S}option{S}chain"
    candidates = get_candidate_expiries(index_name)
    last_err = "No active option chain found"
    
    for exp in candidates:
        data, err = safe_get_json(url, params={"instrument_key": index_key, "expiry_date": exp})
        if err:
            last_err = err
        if data and data.get("data"):
            opt_list = []
            for item in data["data"]:
                strike = float(item["strike_price"])
                if option_type == "CE" and strike >= spot_price - 100 and "call_options" in item:
                    opt_list.append((strike, item["call_options"]["instrument_key"]))
                elif option_type == "PE" and strike <= spot_price + 100 and "put_options" in item:
                    opt_list.append((strike, item["put_options"]["instrument_key"]))
                    
            if option_type == "CE":
                opt_list.sort()  # Ascending strikes: ATM, OTM1, OTM2
            else:
                opt_list.sort(reverse=True)  # Descending strikes for PE: ATM, OTM1, OTM2
                
            if opt_list:
                return exp, opt_list[:3], None
                
    fallback_exp = next(iter(candidates), "-")
    return fallback_exp, [], f"{last_err} (Tried: {', '.join(candidates)})"

def get_candles(instrument_key):
    encoded_key = urllib.parse.quote(instrument_key, safe="")
    ist_today = get_ist_now().date()
    to_date = ist_today.strftime("%Y-%m-%d")
    from_date = (ist_today - datetime.timedelta(days=15)).strftime("%Y-%m-%d")
    
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

# ==========================================
# 3. INDICATOR & OCCURRENCE TIMESTAMP LOGIC
# ==========================================
def calculate_supertrend(df, period=10, multiplier=3):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=1, adjust=False).mean()
    
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

def find_occurrence_timestamp(df, condition_series):
    """Finds the exact timestamp when the current True streak began."""
    if not bool(condition_series.iloc[-1]):
        return "-"
    # Walk backwards to find when condition first became True continuously
    start_ts = df.index[-1]
    for idx in range(len(condition_series) - 1, -1, -1):
        if bool(condition_series.iloc[idx]):
            start_ts = df.index[idx]
        else:
            break
    return start_ts.strftime("%d-%b %H:%M")

def evaluate_setup(df, check_bearish=False):
    """
    For Indices: checks Bullish (Close > 200 SMA & ST == 1) AND Bearish (Close < 200 SMA & ST == -1).
    For Options (CE/PE): always checks Bullish momentum (Option Close > 200 SMA & ST == 1).
    """
    if df is None or len(df) < 15:
        return "NONE", "-", {"close": "-", "sma200": "-", "st": "No Trades Yet"}

    df["SMA_200"] = df["close"].rolling(window=200, min_periods=20).mean()
    df["ST_DIR"] = calculate_supertrend(df, period=10, multiplier=3)
    
    bull_cond = (df["close"] > df["SMA_200"]) & (df["ST_DIR"] == 1)
    bear_cond = (df["close"] < df["SMA_200"]) & (df["ST_DIR"] == -1)
    
    latest = df.iloc[-1]
    close_price = float(latest["close"])
    sma_200 = float(latest["SMA_200"])
    st_bull = latest["ST_DIR"] == 1
    
    info = {
        "close": round(close_price, 2),
        "sma200": round(sma_200, 2),
        "st": "🟢 Bullish" if st_bull else "🔴 Bearish"
    }
    
    if bool(bull_cond.iloc[-1]):
        occ_time = find_occurrence_timestamp(df, bull_cond)
        return "BULLISH", occ_time, info
        
    if check_bearish and bool(bear_cond.iloc[-1]):
        occ_time = find_occurrence_timestamp(df, bear_cond)
        return "BEARISH", occ_time, info
        
    return "NONE", "-", info

# ==========================================
# 4. AUTO-REFRESH FRAGMENT (60s IN MARKET HOURS)
# ==========================================
ist_now = get_ist_now()
market_open = is_market_hours(ist_now)
refresh_interval = 60 if (auto_refresh and market_open) else None

@st.fragment(run_every=refresh_interval)
def render_live_scanner():
    now_ist = get_ist_now()
    status_badge = "🟢 LIVE AUTO-REFRESH (60s)" if (auto_refresh and is_market_hours(now_ist)) else "⏸️ MANUAL / MARKET CLOSED"
