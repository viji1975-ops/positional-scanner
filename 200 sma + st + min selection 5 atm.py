import calendar
from concurrent.futures import ThreadPoolExecutor
import datetime
import operator
import urllib.parse
import requests
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Upstox SMA + SuperTrend Scanner", layout="wide")

ALL_INDICES = {"NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank", "FINNIFTY": "NSE_INDEX|Nifty Fin Service", "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT", "SENSEX": "BSE_INDEX|SENSEX", "BANKEX": "BSE_INDEX|BANKEX"}

default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "") if "UPSTOX_ACCESS_TOKEN" in st.secrets else ""
raw_token = st.sidebar.text_input("Upstox Daily Access Token", value=default_token, type="password")
access_token = raw_token.strip()

selected_names = st.sidebar.multiselect("📊 Select Indices to Scan", options=list(ALL_INDICES.keys()), default=list(ALL_INDICES.keys()))

with st.sidebar.expander("⚙️ Indicator & Strike Settings", expanded=False):
    timeframe = st.selectbox("Candle Timeframe", options=("3min", "5min", "15min"), index=1)
    sma_period = st.number_input("SMA Period", min_value=10, max_value=500, value=200, step=10)
    st_period = st.number_input("SuperTrend ATR Period", min_value=2, max_value=50, value=10, step=1)
    st_multiplier = st.number_input("SuperTrend Multiplier", min_value=0.5, max_value=10.0, value=3.0, step=0.5)
    strikes_per_index = st.selectbox("Strikes per Index", options=(3, 5), index=1)

auto_refresh = st.sidebar.checkbox("⏱️ Auto-Refresh Every 60s (Market Hours)", value=True)
if st.sidebar.button("🔄 Refresh / Run Scan Now", type="primary"):
    st.rerun()

st.title(f"📈 Upstox Live Intraday Scanner ({timeframe}: {sma_period} SMA + SuperTrend)")

if not access_token:
    st.warning("⚠️ Please enter your Upstox Access Token in the left sidebar to start scanning.")
    st.stop()

if not selected_names:
    st.info("ℹ️ Please select at least one index from the sidebar to scan.")
    st.stop()

INDICES = {name: ALL_INDICES[name] for name in selected_names}

HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
S = chr(47)
HOST = "a" + "p" + "i" + "." + "upstox.com"
BASE_API = "https:" + S + S + HOST + S + "v2"


def get_ist_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)


def is_market_hours(ist_dt):
    return ist_dt.weekday() < 5 and datetime.time(9, 15) <= ist_dt.time() <= datetime.time(15, 30)


def get_candidate_expiries(index_name):
    ist_today = get_ist_now().date()
    candidates = []
    if index_name in ("NIFTY", "SENSEX"):
        for offset in range(0, 8):
            d = ist_today + datetime.timedelta(days=offset)
            if d.weekday() < 5:
                candidates.append(d.strftime("%Y-%m-%d"))
    else:
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
def fetch_option_chain_cached(index_name, index_key, token_prefix):
    url = f"{BASE_API}{S}option{S}chain"
    candidates = get_candidate_expiries(index_name)
    last_err = "No active option chain found"
    for exp in candidates:
        data, err = safe_get_json(url, params={"instrument_key": index_key, "expiry_date": exp})
        if err:
            last_err = err
        if data and data.get("data"):
            return exp, data["data"], None
    return next(iter(candidates), "-"), [], f"{last_err} (Tried: {', '.join(candidates)})"


def get_strikes_from_chain(chain_data, spot_price, option_type="CE", total_strikes=5):
    all_opts = []
    for item in chain_data:
        strike = float(item.get("strike_price", 0))
        if option_type == "CE" and "call_options" in item:
            all_opts.append((strike, item.get("call_options").get("instrument_key")))
        elif option_type == "PE" and "put_options" in item:
            all_opts.append((strike, item.get("put_options").get("instrument_key")))
    all_opts.sort(key=operator.itemgetter(0))
    if not all_opts:
        return []
    strikes_only = tuple(map(operator.itemgetter(0), all_opts))
    atm_idx = min(range(len(strikes_only)), key=lambda i: abs(strikes_only[i] - spot_price))
    half = total_strikes // 2
    if option_type == "CE":
        start = max(0, atm_idx - half)
        return all_opts[start:start + total_strikes]
    else:
        end = min(len(all_opts), atm_idx + half + 1)
        return list(reversed(all_opts[max(0, end - total_strikes):end]))


def get_candles(instrument_key, tf="5min"):
    encoded_key = urllib.parse.quote(instrument_key, safe="")
    ist_today = get_ist_now().date()
    to_date = ist_today.strftime("%Y-%m-%d")
    from_date = (ist_today - datetime.timedelta(days=12)).strftime("%Y-%m-%d")
    hist_res, hist_err = safe_get_json(f"{BASE_API}{S}historical-candle{S}{encoded_key}{S}1minute{S}{to_date}{S}{from_date}")
    intra_res, intra_err = safe_get_json(f"{BASE_API}{S}historical-candle{S}intraday{S}{encoded_key}{S}1minute")
    candles = []
    if hist_res and hist_res.get("data", {}).get("candles"):
        candles.extend(hist_res.get("data").get("candles"))
    if intra_res and intra_res.get("data", {}).get("candles"):
        candles.extend(intra_res.get("data").get("candles"))
    if not candles:
        return None, hist_err or intra_err or "0 candles returned by Upstox API"
    df = pd.DataFrame(candles, columns=("timestamp", "open", "high", "low", "close", "volume", "oi"))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates(subset=("timestamp",)).sort_values("timestamp").set_index("timestamp")
    resampled = df.resample(tf).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return resampled, None


def calculate_supertrend(df, period=10, multiplier=3.0):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat((high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()), axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, min_periods=1, adjust=False).mean()
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
                upperband.iloc[i] = upperband.iloc[i - 1]
    return pd.Series(np.where(in_uptrend, 1, -1), index=df.index)


def find_occurrence_timestamp(df, condition_series):
    if not bool(condition_series.iloc[-1]):
        return "-"
    start_ts = df.index[-1]
    for idx in range(len(condition_series) - 1, -1, -1):
        if bool(condition_series.iloc[idx]):
            start_ts = df.index[idx]
        else:
            break
    return start_ts.strftime("%d-%b %H:%M")


def evaluate_setup(df, sma_len=200, st_len=10, st_mult=3.0, check_bearish=False):
    if df is None or len(df) < 15:
        candle_count = 0 if df is None else len(df)
        return "NONE", "-", {"close": "-", "sma": "-", "st": f"Insufficient Candles ({candle_count})"}
    df["SMA"] = df["close"].rolling(window=sma_len, min_periods=min(20, sma_len)).mean()
    df["ST_DIR"] = calculate_supertrend(df, period=st_len, multiplier=st_mult)
    bull_cond = (df["close"] > df["SMA"]) & (df["ST_DIR"] == 1)
    bear_cond = (df["close"] < df["SMA"]) & (df["ST_DIR"] == -1)
    latest = df.iloc[-1]
    close_price, sma_val, st_bull = float(latest["close"]), float(latest["SMA"]), (latest["ST_DIR"] == 1)
    info = {"close": round(close_price, 2), "sma": round(sma_val, 2), "st": "🟢 Bullish" if st_bull else "🔴 Bearish"}
    if bool(bull_cond.iloc[-1]):
        return "BULLISH", find_occurrence_timestamp(df, bull_cond), info
    if check_bearish and bool(bear_cond.iloc[-1]):
        return "BEARISH", find_occurrence_timestamp(df, bear_cond), info
    return "NONE", "-", info


now_ist = get_ist_now()
live_mode = auto_refresh and is_market_hours(now_ist)
if live_mode:
    st_autorefresh(interval=60 * 1000, key="live_market_scanner_refresh")

st.caption(f"Last scanned: **{now_ist.strftime('%Y-%m-%d %H:%M:%S')} IST** | Mode: **{'🟢 LIVE AUTO-REFRESH (60s)' if live_mode else '⏸️ MANUAL / MARKET CLOSED'}**")

STATUS_MAP = {"BULLISH": "🟢 BULLISH (Look for CE)", "BEARISH": "🔴 BEARISH (Look for PE)"}
index_rows = []
matched_indices = []

for name, inst_key in INDICES.items():
    df_index, err = get_candles(inst_key, tf=timeframe)
    if df_index is None:
        st.error(f"❌ {name}: {err}")
        continue
    signal_dir, idx_occ_time, idx_info = evaluate_setup(df_index, sma_len=sma_period, st_len=st_period, st_mult=st_multiplier, check_bearish=True)
