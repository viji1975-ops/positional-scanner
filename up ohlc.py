import os
import gzip
import json
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Upstox F&O OHOL Scanner", layout="wide")

# --- Sidebar: Token & Scanner Filters ---
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
pattern_filter = st.sidebar.selectbox("Show Patterns", ["All (Open=High & Open=Low)", "Open=High Only (Bearish)", "Open=Low Only (Bullish)"])
tolerance_pct = st.sidebar.slider("Open=High/Low Tolerance (%)", min_value=0.00, max_value=0.15, value=0.02, step=0.01, help="0.00% = exact match; 0.02% allows minor 1-tick noise.")

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

@st.cache_data(ttl=43200)
def get_all_fno_stocks():
    """Downloads Upstox NSE instrument master and extracts all unique F&O equity underlyings."""
    url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
    res = requests.get(url, timeout=20)
    res.raise_for_status()
    
    raw_data = gzip.decompress(res.content).decode("utf-8")
    instruments = json.loads(raw_data)
    
    fno_equities = {}
    for item in instruments:
        if item.get("segment") == "NSE_FO":
            u_key = item.get("underlying_key", "")
            u_sym = item.get("underlying_symbol", "")
            u_type = item.get("underlying_type", "")
            # Keep only NSE Equity stocks (excludes NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)
            if u_key.startswith("NSE_EQ|") and u_type == "EQUITY" and u_sym:
                fno_equities[u_key] = f"NSE:{u_sym}"
                
    return dict(sorted(fno_equities.items(), key=lambda x: x[1]))

@st.cache_data(ttl=1800)
def get_historical_stats(instrument_key, token):
    """Fetches daily candles to compute 14-day ATR, 20-day Avg Vol, and latest completed candle."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    
    url = f"https://upstox.com{instrument_key.strip()}/day/{to_date}/{from_date}"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200 or not res.text.strip():
            return None, None, None
        candles = res.json().get("data", {}).get("candles", [])
    except Exception:
        return None, None, None
    
    if len(candles) < 15:
        return None, None, None

    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume", "oi"])
    df = df.iloc[::-1].reset_index(drop=True)

    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
    atr_14 = round(df["tr"].tail(14).mean(), 2)
    avg_vol_20 = df["volume"].tail(20).mean()
    last_candle = df.iloc[-1].to_dict()
    
    return atr_14, avg_vol_20, last_candle

def fetch_batched_quotes(instrument_keys):
    """Fetches live/last-session quotes for all F&O stocks in batches of 100."""
    url = "https://upstox.com"
    all_quotes = {}
    batch_size = 100

    for i in range(0, len(instrument_keys), batch_size):
        batch = instrument_keys[i:i + batch_size]
        params = {"instrument_key": ",".join(batch)}
        res = requests.get(url, headers=HEADERS, params=params, timeout=15)
        
        if res.status_code == 401:
            return None, "🔒 Token Expired or Invalid (HTTP 401). Please generate a fresh Upstox token and paste it in the sidebar."
        elif res.status_code != 200 or not res.text.strip():
            return None, f"Upstox API Error (HTTP {res.status_code}): {res.text[:250]}"
            
        data = res.json()
        if data.get("status") != "success":
            return None, f"Upstox API Error: {data}"
            
        all_quotes.update(data.get("data", {}))
        
    return all_quotes, None

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
    if err:
        st.error(err)
        return pd.DataFrame(), "", total_fno

    candidates = []
    data_source_note = "Live / Last Session Quote"
    tol_multiplier = tolerance_pct / 100.0

    # Stage 1: Filter all F&O quotes for Open=High or Open=Low
    for key, symbol in fno_dict.items():
        resp_key = key.replace("|", ":")
        data = quotes.get(resp_key, {})
        ohlc = data.get("ohlc", {})

        open_p = ohlc.get("open", 0)
        high_p = ohlc.get("high", 0)
        low_p = ohlc.get("low", 0)
        ltp = data.get("last_price", 0)
        curr_vol = data.get("volume", 0)

        if open_p == 0:
            continue

        tolerance = open_p * tol_multiplier
        is_open_high = abs(open_p - high_p) <= tolerance
        is_open_low = abs(open_p - low_p) <= tolerance

        # Avoid flagging flat/illiquid stocks where Open == High == Low
        if is_open_high and is_open_low:
            continue

        if is_open_high and "Open=Low Only" in pattern_filter:
            continue
        if is_open_low and "Open=High Only" in pattern_filter:
            continue

        if is_open_high or is_open_low:
            candidates.append({
                "key": key,
                "symbol": symbol,
                "open": open_p,
                "ltp": ltp,
                "vol": curr_vol,
                "is_open_high": is_open_high
            })

    # Stage 2: Fetch ATR & 20-Day Avg Volume in parallel ONLY for matched candidates
    results = []
    def enrich_candidate(item):
        atr, avg_vol, _ = get_historical_stats(item["key"], ACCESS_TOKEN)
        if not atr or not avg_vol:
            return None

        open_p = item["open"]
        ltp = item["ltp"]
        risk_unit = atr * 0.5
        vol_ratio = round(item["vol"] / avg_vol, 2) if avg_vol > 0 else 0

        if vol_ratio >= 4.0:
            power = "🔥 Ultra"
            power_rank = 3
        elif vol_ratio >= 2.0:
            power = "⚡ Strong"
            power_rank = 2
        else:
            power = "Normal"
            power_rank = 1

        if item["is_open_high"]:
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
            "Symbol": item["symbol"],
            "Pattern": pattern,
            "Status": status,
            "Price (₹)": f"{ltp:.2f}",
            "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
            "Rev Target": rev_tgt,
            "Volume": f"{vol_ratio}x",
            "Power": power,
            "_vol_ratio": vol_ratio,
            "_power_rank": power_rank
        }

    with ThreadPoolExecutor(max_workers=6) as executor:
        enriched = list(executor.map(enrich_candidate, candidates))

    results = [r for r in enriched if r is not None]
    df_out = pd.DataFrame(results)

    if not df_out.empty:
        # Sort highest volume momentum setups to the top
        df_out = df_out.sort_values(by=["_power_rank", "_vol_ratio"], ascending=[False, False])
        df_out = df_out.drop(columns=["_vol_ratio", "_power_rank"])

    return df_out, data_source_note, total_fno

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
st.title("📊 NSE F&O Open=High / Open=Low Scanner")

if st.button("🔄 Refresh Scanner"):
    st.rerun()

with st.spinner("Scanning all NSE F&O stocks..."):
    df_results, source_note, total_fno = scan_all_fno()

if total_fno > 0:
    st.caption(f"Scanned **{total_fno} NSE F&O Stocks** | Matches Found: **{len(df_results)}** | Mode: **{source_note}**")

if not df_results.empty:
    st.dataframe(style_scanner_table(df_results), use_container_width=True, hide_index=True)
elif ACCESS_TOKEN:
    st.info("No F&O stocks matched Open=High or Open=Low right now (if it is 9:00–9:15 AM IST pre-open, check again at 9:16 AM IST).")

