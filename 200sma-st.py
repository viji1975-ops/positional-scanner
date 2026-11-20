import calendar
import datetime
import urllib.parse
import requests
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Upstox 200 SMA + SuperTrend Scanner", layout="wide")
st.title("📈 Upstox Live Intraday Scanner (5m: 200 SMA + SuperTrend)")

default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "") if "UPSTOX_ACCESS_TOKEN" in st.secrets else ""
raw_token = st.sidebar.text_input("Upstox Daily Access Token", value=default_token, type="password")
access_token = raw_token.strip()

auto_refresh = st.sidebar.checkbox("⏱️ Auto-Refresh Every 60s (Market Hours)", value=True)
if st.sidebar.button("🔄 Refresh / Run Scan Now", type="primary"):
    st.rerun()

if not access_token:
    st.warning("⚠️ Please enter your Upstox Access Token in the left sidebar to start scanning.")
    st.stop()

HEADERS = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
S = chr(47)
HOST = "a" + "p" + "i" + "." + "upstox.com"
BASE_API = "https:" + S + S + HOST + S + "v2"

INDICES = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT"
}

def get_ist_now():
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=5, minutes=30)

def is_market_hours(ist_dt):
    return ist_dt.weekday() < 5 and datetime.time(9, 15) <= ist_dt.time() <= datetime.time(15, 30)

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

def get_strikes_from_chain(chain_data, spot_price, option_type="CE"):
    opt_list = []
    for item in chain_data:
        strike = float(item["strike_price"])
        if option_type == "CE" and strike >= spot_price - 100 and "call_options" in item:
            opt_list.append((strike, item["call_options"]["instrument_key"]))
        elif option_type == "PE" and strike <= spot_price + 100 and "put_options" in item:
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

def evaluate_setup(df, check_bearish=False):
    if df is None or len(df) < 15:
        return "NONE", "-", {"close": "-", "sma200": "-", "st": "No Trades Yet"}

    df["SMA_200"] = df["close"].rolling(window=200, min_periods=20).mean()
    df["ST_DIR"] = calculate_supertrend(df, period=10, multiplier=3)
    bull_cond = (df["close"] > df["SMA_200"]) & (df["ST_DIR"] == 1)
    bear_cond = (df["close"] < df["SMA_200"]) & (df["ST_DIR"] == -1)
    
    latest = df.iloc[-1]
    close_price, sma_200, st_bull = float(latest["close"]), float(latest["SMA_200"]), (latest["ST_DIR"] == 1)
    info = {"close": round(close_price, 2), "sma200": round(sma_200, 2), "st": "🟢 Bullish" if st_bull else "🔴 Bearish"}
    
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
index_rows, matched_indices = [], []

for name, inst_key in INDICES.items():
    df_index, err = get_candles(inst_key)
    if df_index is None:
        st.error(f"❌ {name}: {err}")
        continue
    signal_dir, idx_occ_time, idx_info = evaluate_setup(df_index, check_bearish=True)
    spot_price = idx_info["close"] if isinstance(idx_info["close"], float) else float(df_index["close"].iloc[-1])
    expiry, chain_data, opt_err = fetch_option_chain_cached(name, inst_key, access_token[:10])
    opt_type = "PE" if signal_dir == "BEARISH" else "CE"
    
    index_rows.append({
        "Index": name, "Expiry": expiry, "Close": idx_info["close"], "200 SMA": idx_info["sma200"],
        "SuperTrend (10,3)": idx_info["st"], "Setup Status": STATUS_MAP.get(signal_dir, "⏳ Waiting (Mixed)"),
        "Signal Since (IST)": idx_occ_time
    })
    if signal_dir in ("BULLISH", "BEARISH"):
        matched_indices.append((name, spot_price, expiry, chain_data, opt_err, opt_type))

st.subheader("1. Index Status (5-Minute Timeframe)")
if index_rows:
    st.dataframe(pd.DataFrame(index_rows), use_container_width=True, hide_index=True)

st.subheader("2. Matching Call (CE) & Put (PE) Options Status")
option_rows = []
for name, spot_price, expiry, chain_data, opt_err, opt_type in matched_indices:
    if opt_err:
        st.warning(f"⚠️ {name} Option Chain: {opt_err}")
    for strike, opt_key in get_strikes_from_chain(chain_data, spot_price, option_type=opt_type):
        df_opt, _ = get_candles(opt_key)
        opt_dir, opt_occ_time, opt_info = evaluate_setup(df_opt, check_bearish=False)
        opt_aligned = (opt_dir == "BULLISH")
        option_rows.append({
            "Index": name,
            "Direction": "🟢 CALL (CE)" if opt_type == "CE" else "🔴 PUT (PE)",
            "Contract": f"{int(strike)} {opt_type}",
            "Expiry": expiry,
            "Opt Close": opt_info["close"],
            "Opt 200 SMA": opt_info["sma200"],
            "Opt SuperTrend": opt_info["st"],
            "Signal": f"🚀 CONFIRMED BUY {opt_type}" if opt_aligned else f"⏳ {opt_type} Not Aligned",
            "Opt Signal Since (IST)": opt_occ_time
        })

if option_rows:
    st.dataframe(pd.DataFrame(option_rows), use_container_width=True, hide_index=True)
else:
    st.info("No matching CE/PE options aligned right now.")
