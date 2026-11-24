import os
import gzip
import json
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Upstox Exact OHOL Scanner", layout="wide")

# --- Sidebar: Token & Scanner Controls ---
st.sidebar.header("🔑 Upstox API Settings")
default_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()

user_token = st.sidebar.text_input(
    "Paste Daily Access Token",
    value="",
    type="password",
    placeholder="Paste today's Upstox token here...",
    help="Upstox tokens expire daily at 3:30 AM IST. Paste your fresh morning token here."
)

ACCESS_TOKEN = user_token.strip() if user_token.strip() else default_token

if user_token.strip():
    st.sidebar.success("✅ Using token pasted in sidebar")
elif default_token:
    st.sidebar.info("ℹ️ Using token from Streamlit Secrets")
else:
    st.sidebar.warning("⚠️ No token found. Paste your token above.")

st.sidebar.divider()
st.sidebar.header("⚙️ Scanner Filters")
pattern_filter = st.sidebar.selectbox(
    "Show Exact Patterns",
    ["All (Open=High & Open=Low)", "Open=High Only (Bearish)", "Open=Low Only (Bullish)"]
)
auto_refresh = st.sidebar.checkbox("🔄 Auto-Refresh Every 60s", value=False)

HEADERS = {
    "Accept": "application/json",
    "Api-Version": "2.0",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

@st.cache_data(ttl=43200)
def get_all_fno_stocks():
    """Downloads Upstox NSE instrument master and extracts all unique F&O equity underlyings."""
    urls = [
        "https://upstox.com",
        "https://upstox.com",
    ]
    cdn_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Encoding": "gzip, deflate",
    }

    instruments = None
    for url in urls:
        try:
            res = requests.get(url, headers=cdn_headers, timeout=25)
            if res.status_code != 200:
                continue
            if res.content[:2] == b"\x1f\x8b":
                raw_data = gzip.decompress(res.content).decode("utf-8")
            else:
                raw_data = res.text
            if raw_data.lstrip().startswith("["):
                instruments = json.loads(raw_data)
                break
        except Exception:
            continue

    if not instruments:
        raise RuntimeError("Upstox CDN temporarily blocked the master file download. Click 'Refresh Scanner' in a few seconds.")

    fno_equities = {}
    for item in instruments:
        if item.get("segment") == "NSE_FO":
            u_key = item.get("underlying_key", "")
            u_sym = item.get("underlying_symbol", "")
            u_type = item.get("underlying_type", "")
            if u_key.startswith("NSE_EQ|") and u_type == "EQUITY" and u_sym:
                fno_equities[u_key] = f"NSE:{u_sym}"

    return dict(sorted(fno_equities.items(), key=lambda x: x))

@st.cache_data(ttl=900)
def get_historical_stats(instrument_key, token):
    """Fetches daily candles to compute 14-day ATR, 20-day Avg Vol, PDH/PDL, and latest candle."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")

    url = f"https://upstox.com{instrument_key.strip()}/day/{to_date}/{from_date}"
    headers = {
        "Accept": "application/json",
        "Api-Version": "2.0",
        "Authorization": f"Bearer {token}"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        payload = res.json()
        candles = payload.get("data", {}).get("candles", [])
    except Exception:
        return None

    if len(candles) < 15:
        return None

    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume", "oi"])
    df = df.iloc[::-1].reset_index(drop=True)  # Oldest to newest

    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
    atr_14 = round(df["tr"].tail(14).mean(), 2)
    avg_vol_20 = df["volume"].tail(20).mean()

    last_candle = df.iloc[-1].to_dict()
    prev_candle = df.iloc[-2].to_dict()

    return {
        "atr": atr_14,
        "avg_vol": avg_vol_20,
        "last_candle": last_candle,
        "pdh": prev_candle["high"],
        "pdl": prev_candle["low"]
    }

def fetch_batched_quotes(instrument_keys):
    """Fetches quotes in batches of 50 with safe JSON parsing."""
    url = "https://upstox.com"
    all_quotes = {}
    batch_size = 50

    for i in range(0, len(instrument_keys), batch_size):
        batch = instrument_keys[i:i + batch_size]
        params = {"instrument_key": ",".join(batch)}
        try:
            res = requests.get(url, headers=HEADERS, params=params, timeout=15)
        except requests.RequestException as e:
            return None, f"Network error: {e}"

        if res.status_code == 401:
            return None, "🔒 Token Expired or Invalid (HTTP 401). Please generate a fresh Upstox token and paste it in the sidebar."
        if res.status_code != 200:
            return None, f"HTTP {res.status_code}"

        try:
            data = res.json()
        except Exception:
            return None, "NON_JSON"

        if data.get("status") != "success":
            return None, f"API Error: {data}"

        all_quotes.update(data.get("data", {}))
        time.sleep(0.15)

    return all_quotes, None

def build_row(symbol, open_p, ltp, curr_vol, is_open_high, stats):
    """Builds a formatted result row with ATR targets, Volume Power, and PDH/PDL status."""
    atr = stats["atr"]
    avg_vol = stats["avg_vol"]
    pdh = stats["pdh"]
    pdl = stats["pdl"]

    risk_unit = atr * 0.5
    vol_ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0

    if vol_ratio >= 4.0:
        power = "🔥 Ultra"
        power_rank = 3
    elif vol_ratio >= 2.0:
        power = "⚡ Strong"
        power_rank = 2
    else:
        power = "Normal"
        power_rank = 1

    if ltp > pdh:
        level_tag = "Above PDH 🟢"
    elif ltp < pdl:
        level_tag = "Below PDL 🔴"
    else:
        level_tag = "Inside Prev Day"

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

    return {
        "Symbol": symbol,
        "Pattern": pattern,
        "Status": status,
        "Price (₹)": f"{ltp:.2f}",
        "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
        "Rev Target": rev_tgt,
        "PDH/PDL": level_tag,
        "Volume": f"{vol_ratio}x",
        "Power": power,
        "_vol_ratio": vol_ratio,
        "_power_rank": power_rank
    }

def is_exact_ohol(open_p, high_p, low_p):
    """Checks for exact Open=High or Open=Low to 2 decimal places (NSE paise precision)."""
    o = round(float(open_p), 2)
    h = round(float(high_p), 2)
    l = round(float(low_p), 2)
    if o <= 0 or h == l:
        return False, False
    return (o == h), (o == l)

def scan_all_fno():
    if not ACCESS_TOKEN:
        st.warning("👈 Please paste your daily Upstox Access Token in the left sidebar to start scanning.")
        return pd.DataFrame(), "", 0

    try:
        fno_dict = get_all_fno_stocks()
    except Exception as e:
        st.error(f"Failed to download NSE F&O instrument list: {e}")
        return pd.DataFrame(), "", 0

    total_fno = len(fno_dict)
    quotes, err = fetch_batched_quotes(list(fno_dict.keys()))

    if err and "401" in err:
        st.error(err)
        return pd.DataFrame(), "", total_fno

    # Map quotes by instrument_token ('NSE_EQ|INE...')
    quotes_by_token = {}
    if quotes:
        for q_data in quotes.values():
            inst_token = q_data.get("instrument_token")
            if inst_token:
                quotes_by_token[inst_token] = q_data

    has_live_open = any(
        q.get("ohlc", {}).get("open", 0) > 0 for q in quotes_by_token.values()
    )

    results = []
    source_note = "Live / Last Session Quote (Exact Match)"

    # Primary Path: Batch Quotes API
    if has_live_open:
        candidates = []
        for key, symbol in fno_dict.items():
            data = quotes_by_token.get(key, {})
            ohlc = data.get("ohlc", {})

            open_p = ohlc.get("open", 0)
            high_p = ohlc.get("high", 0)
            low_p = ohlc.get("low", 0)
            ltp = data.get("last_price", 0)
            curr_vol = data.get("volume", 0)

            is_open_high, is_open_low = is_exact_ohol(open_p, high_p, low_p)

            if is_open_high and "Open=Low Only" in pattern_filter:
                continue
            if is_open_low and "Open=High Only" in pattern_filter:
                continue

            if is_open_high or is_open_low:
                candidates.append((key, symbol, open_p, ltp, curr_vol, is_open_high))

        def enrich_from_quote(item):
            key, symbol, open_p, ltp, curr_vol, is_open_high = item
            stats = get_historical_stats(key, ACCESS_TOKEN)
            if not stats:
                return None
            return build_row(symbol, open_p, ltp, curr_vol, is_open_high, stats)

                with ThreadPoolExecutor(max_workers=6) as executor:
            results = [r for r in executor.map(enrich_from_quote, candidates) if r is not None]

    # Fallback Path: Historical Daily Candle (if pre-open reset has open == 0)
    else:
        session_dates = []
        def scan_via_candle(kv):
            key, symbol = kv
            stats = get_historical_stats(key, ACCESS_TOKEN)
            if not stats:
                return None
            lc = stats["last_candle"]
            session_dates.append(str(lc["time"])[:10])

            open_p = lc["open"]
            high_p = lc["high"]
            low_p = lc["low"]
            ltp = lc["close"]
            curr_vol = lc["volume"]

            is_open_high, is_open_low = is_exact_ohol(open_p, high_p, low_p)

            if is_open_high and "Open=Low Only" in pattern_filter:
                return None
            if is_open_low and "Open=High Only" in pattern_filter:
                return None

            if is_open_high or is_open_low:
                return build_row(symbol, open_p, ltp, curr_vol, is_open_high, stats)
            return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = [r for r in executor.map(scan_via_candle, list(fno_dict.items())) if r is not None]

        last_date = max(session_dates) if session_dates else "Last Trading Day"
        source_note = f"Last Trading Session ({last_date} — Exact Match)"

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_power_rank", "_vol_ratio"], ascending=[False, False])
        df_out = df_out.drop(columns=["_vol_ratio", "_power_rank"])

    return df_out, source_note, total_fno

def style_scanner_table(df):
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
st.title("📊 NSE F&O Exact Open=High / Open=Low Scanner")

if st.button("🔄 Refresh Scanner"):
    st.rerun()

with st.spinner("Scanning all NSE F&O stocks for exact Open=High / Open=Low..."):
    df_results, source_note, total_fno = scan_all_fno()

if total_fno > 0:
    st.caption(f"Scanned **{total_fno} NSE F&O Stocks** | Exact Matches Found: **{len(df_results)}** | Mode: **{source_note}**")

if not df_results.empty:
    st.dataframe(style_scanner_table(df_results), use_container_width=True, hide_index=True)
elif ACCESS_TOKEN:
    st.info("No F&O stocks had an exact Open=High or Open=Low in this session.")

if auto_refresh and ACCESS_TOKEN:
    time.sleep(60)
    st.rerun()
