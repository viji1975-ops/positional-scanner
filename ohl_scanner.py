import streamlit as st
import requests
import pandas as pd
import gzip
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="NSE F&O OHL Ultimate Scanner Pro", layout="wide")

# ==========================================
# 1. SIDEBAR CONFIGURATION
# ==========================================
st.sidebar.header("🔑 Upstox Configuration")
access_token = st.sidebar.text_input("Daily Upstox Access Token", type="password").strip()
tolerance_pct = st.sidebar.number_input("OHL Tolerance (%)", min_value=0.0, max_value=1.0, value=0.0, step=0.05) / 100
pattern_filter = st.sidebar.multiselect(
    "Filter Patterns",
    ["Open=Low", "Open=High"],
    default=["Open=Low", "Open=High"]
)
status_filter = st.sidebar.multiselect(
    "Filter Status",
    ["Active", "Breached ❌"],
    default=["Active", "Breached ❌"]
)

BASE_URL = "https://upstox.com"
INSTRUMENTS_URL = "https://upstox.com"

# ==========================================
# 2. AUTO-FETCH ALL NSE F&O STOCKS
# ==========================================
@st.cache_data(ttl=86400)
def get_all_fno_stocks() -> dict:
    """Downloads Upstox NSE instrument master and maps all F&O underlying stocks to NSE_EQ keys."""
    try:
        resp = requests.get(INSTRUMENTS_URL, timeout=20)
        resp.raise_for_status()
        decompressed = gzip.decompress(resp.content)
        instruments = json.loads(decompressed.decode("utf-8"))

        # Find all unique underlying symbols present in NSE_FO (Futures & Options)
        fno_underlyings = set()
        for item in instruments:
            if item.get("segment") == "NSE_FO" and item.get("instrument_type") in ("FUT", "CE", "PE"):
                underlying = item.get("underlying_symbol") or item.get("name")
                if underlying:
                    fno_underlyings.add(underlying.strip())

        # Map those underlying symbols to their Equity (NSE_EQ) instrument_key
        fno_eq_map = {}
        for item in instruments:
            if item.get("segment") == "NSE_EQ" and item.get("instrument_type") == "EQ":
                sym = item.get("trading_symbol", "").strip()
                if sym in fno_underlyings:
                    fno_eq_map[f"NSE:{sym}"] = item.get("instrument_key")

        return dict(sorted(fno_eq_map.items()))
    except Exception as e:
        st.error(f"Failed to fetch NSE F&O instrument list: {e}")
        return {}

# ==========================================
# 3. FETCH CANDLES (LIVE OR LAST TRADING DAY)
# ==========================================
def scan_single_stock(symbol: str, inst_key: str, token: str, tol: float):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    encoded_key = inst_key.replace("|", "%7C")
    
    candles = []
    session_mode = "Live Intraday"
    
    # Step A: Try Today's Live Intraday 15m Candles
    try:
        intra_url = f"{BASE_URL}/intraday/{encoded_key}/minutes/15"
        r_intra = requests.get(intra_url, headers=headers, timeout=8)
        if r_intra.status_code == 401:
            return {"error": "401"}
        if r_intra.status_code == 200:
            candles = r_intra.json().get("data", {}).get("candles", [])
    except Exception:
        pass

    # Step B: If market closed / intraday empty, fallback to Historical 15m Candles (Last 7 days)
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    hist_url = f"{BASE_URL}/{encoded_key}/minutes/15/{to_date}/{from_date}"
    
    hist_candles = []
    try:
        r_hist = requests.get(hist_url, headers=headers, timeout=10)
        if r_hist.status_code == 401:
            return {"error": "401"}
        if r_hist.status_code == 200:
            hist_candles = r_hist.json().get("data", {}).get("candles", [])
    except Exception:
        pass

    # Use Historical Last Trading Day if Live Intraday is empty
    if not candles:
        if not hist_candles:
            return None
        session_mode = "Last Trading Day"
        # Extract the most recent trading date from the latest historical candle timestamp
        latest_date_str = hist_candles[:10]  # e.g., "2026-11-23"
        candles = [c for c in hist_candles if c.startswith(latest_date_str)]

    if not candles:
        return None

    # Upstox returns newest candle first; reverse so index 0 is 09:15 AM
    candles = list(reversed(candles))
    session_date = candles[:10]

    # First 15-min candle (09:15 - 09:30 AM)
    first_c = candles
    o = float(first_c)
    h = float(first_c)
    l = float(first_c)
    v = float(first_c)
    c = float(candles[-1])

    is_ol = (abs(o - l) <= o * tol) and (h > o)
    is_oh = (abs(o - h) <= o * tol) and (l < o)

    if not (is_ol or is_oh):
        return None

    # Compute 20-period average 15m volume from historical candles (excluding today's first candle)
    past_vols = [float(x) for x in hist_candles[1:21]] if len(hist_candles) > 1 else []
    avg_vol = (sum(past_vols) / len(past_vols)) if past_vols else 0.0
    v_mult = (v / avg_vol) if avg_vol > 0 else 1.0
    power = "🔥 Ultra" if v_mult > 3.0 else ("⚡ Strong" if v_mult > 1.5 else "⚠️ Weak")

    candle_range = h - l
    status = "Active"
    rev_tgt = "N/A"

    if is_ol:
        pattern = "Open=Low"
        t1, t2 = o + candle_range, o + (2.0 * candle_range)
        sl = l
        if c < o:
            status = "Breached ❌"
            rev_tgt = f"{o - (2.0 * candle_range):.1f}"
            sl = h
    else:
        pattern = "Open=High"
        t1, t2 = o - candle_range, o - (2.0 * candle_range)
        sl = h
        if c > o:
            status = "Breached ❌"
            rev_tgt = f"{o + (2.0 * candle_range):.1f}"
            sl = l

    return {
        "session_mode": session_mode,
        "session_date": session_date,
        "row": {
            "Symbol": symbol,
            "Pattern": pattern,
            "Status": status,
            "Open": round(o, 2),
            "LTP / Close": round(c, 2),
            "Normal Tgt (1:1 | 1:2)": f"{t1:.1f} | {t2:.1f}",
            "Rev Target": rev_tgt,
            "Stop Loss": round(sl, 1),
            "Vol Mult": round(v_mult, 2),
            "Power": power
        }
    }

# ==========================================
# 4. MAIN DASHBOARD UI
# ==========================================
st.title("📊 NSE All F&O — OHL Ultimate Scanner Pro")

if not access_token:
    st.info("👈 Paste your daily Upstox Access Token in the left sidebar to scan all NSE F&O stocks.")
    st.stop()

fno_stocks = get_all_fno_stocks()
if not fno_stocks:
    st.warning("Could not load F&O stock list. Click Refresh to retry.")
    st.stop()

col1, col2, col3 = st.columns([1, 2, 2])
with col1:
    st.button("🔄 Refresh Scan")
with col2:
    st.metric("Total F&O Stocks Scanned", len(fno_stocks))
with col3:
    status_placeholder = st.empty()

progress = st.progress(0)
results = []
detected_mode = "Checking..."
detected_date = ""
unauthorized = False

# Parallel execution (15 workers) scans ~200 F&O stocks in ~4 seconds
with ThreadPoolExecutor(max_workers=15) as executor:
    futures = {
        executor.submit(scan_single_stock, sym, key, access_token, tolerance_pct): sym
        for sym, key in fno_stocks.items()
    }
    completed = 0
    total = len(futures)
    for future in as_completed(futures):
        completed += 1
        progress.progress(completed / total)
        res = future.result()
        if res:
            if res.get("error") == "401":
                unauthorized = True
                break
            detected_mode = res["session_mode"]
            detected_date = res["session_date"]
            results.append(res["row"])

progress.empty()

if unauthorized:
    st.error("❌ Unauthorized (401): Your Upstox daily token is invalid or expired.")
    st.stop()

if detected_date:
    status_placeholder.info(f"📅 **Session:** {detected_mode} ({detected_date})")

if results:
    df = pd.DataFrame(results)
    # Apply Sidebar Filters
    df = df[df["Pattern"].isin(pattern_filter) & df["Status"].isin(status_filter)]
    # Sort highest volume multiplier on top
    df = df.sort_values(by="Vol Mult", ascending=False).reset_index(drop=True)
    df["Volume"] = df["Vol Mult"].apply(lambda x: f"{x:.2f}x")
    df = df.drop(columns=["Vol Mult"])

    st.dataframe(df, use_container_width=True, hide_index=True)

    # CSV Download Button
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download F&O Scanner Results (CSV)",
        data=csv_data,
        file_name=f"nse_fno_ohl_{detected_date or datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv"
    )
else:
    st.warning("No F&O stocks matched Open=High or Open=Low for the last trading session.")
