import streamlit as st
import requests
import pandas as pd
import io
import re
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
INSTRUMENTS_CSV_URL = "https://upstox.com"

# ==========================================
# 2. AUTO-FETCH ALL NSE F&O STOCKS (FIXED)
# ==========================================
@st.cache_data(ttl=86400)
def get_all_fno_stocks() -> tuple:
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(INSTRUMENTS_CSV_URL, headers=headers, timeout=25)
        resp.raise_for_status()
        df_inst = pd.read_csv(io.BytesIO(resp.content), compression="gzip", low_memory=False)
        
        # Normalize column names to lowercase
        df_inst.columns = [c.strip().lower() for c in df_inst.columns]
        
        # Identify segment/exchange column
        seg_col = "segment" if "segment" in df_inst.columns else "exchange"
        sym_col = "tradingsymbol" if "tradingsymbol" in df_inst.columns else "trading_symbol"
        
        # 1. Extract all underlying stock symbols from NSE_FO
        fo_df = df_inst[df_inst[seg_col].astype(str).str.contains("NSE_FO", na=False)]
        fno_symbols = set()
        
        if "underlying_symbol" in fo_df.columns:
            fno_symbols.update(fo_df["underlying_symbol"].dropna().astype(str).str.strip())
            
        # Also parse root symbol from tradingsymbol (e.g., RELIANCE26NOVFUT -> RELIANCE)
        for ts in fo_df[sym_col].dropna().astype(str):
            m = re.match(r"^([A-Z&-]+?)(?:\d{2}|\s)", ts.strip())
            if m:
                fno_symbols.add(m.group(1))
                
        # Remove index symbols so only stocks remain
        index_names = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
        fno_symbols = fno_symbols - index_names

        # 2. Map those F&O symbols to their NSE_EQ Equity instrument_key
        eq_df = df_inst[
            (df_inst[seg_col].astype(str) == "NSE_EQ") &
            (df_inst["instrument_type"].astype(str).isin(["EQ", "EQUITY"]))
        ]
        
        fno_eq_map = {}
        for _, row in eq_df.iterrows():
            sym = str(row[sym_col]).strip()
            if sym in fno_symbols:
                fno_eq_map[f"NSE:{sym}"] = str(row["instrument_key"]).strip()

        return dict(sorted(fno_eq_map.items())), "OK"
    except Exception as e:
        return {}, str(e)

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

    # Step B: Fetch Historical 15m Candles (Last 35 days)
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

    # Fallback to Last Trading Day if Live Intraday is empty
    if not candles:
        if not hist_candles:
            return None
        session_mode = "Last Trading Day"
        latest_candle = next(iter(hist_candles))
        latest_ts, *_ = latest_candle
        latest_date_str = str(latest_ts).split("T").pop(0)
        candles = [c for c in hist_candles if str(next(iter(c))).startswith(latest_date_str)]

    if not candles:
        return None

    # Reverse so index 0 is 09:15 AM candle
    candles = list(reversed(candles))
    first_c = next(iter(candles))
    last_c = candles.pop()

    # Unpack Upstox candle tuple: (timestamp, open, high, low, close, volume, oi)
    ts_first, o, h, l, _, v, _ = first_c
    _, _, _, _, c, _, _ = last_c

    o, h, l, v, c = float(o), float(h), float(l), float(v), float(c)
    session_date = str(ts_first).split("T").pop(0)

    is_ol = (abs(o - l) <= o * tol) and (h > o)
    is_oh = (abs(o - h) <= o * tol) and (l < o)

    if not (is_ol or is_oh):
        return None

    # 20-period average 15m volume
    past_vols = []
    for idx_v, item in enumerate(hist_candles):
        if 1 <= idx_v <= 20:
            _, _, _, _, _, item_v, _ = item
            past_vols.append(float(item_v))

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

fno_stocks, load_status = get_all_fno_stocks()

if not fno_stocks:
    st.error(f"Could not load F&O master list from Upstox: {load_status}")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔄 Refresh Scan"):
        st.cache_data.clear()
with col2:
    st.metric("F&O Stocks Loaded", len(fno_stocks))
with col3:
    status_placeholder = st.empty()

progress = st.progress(0)
results = []
detected_mode = "Checking..."
detected_date = ""
unauthorized = False

with ThreadPoolExecutor(max_workers=20) as executor:
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
    df = df[df["Pattern"].isin(pattern_filter) & df["Status"].isin(status_filter)]
    df = df.sort_values(by="Vol Mult", ascending=False).reset_index(drop=True)
    df["Volume"] = df["Vol Mult"].apply(lambda x: f"{x:.2f}x")
    df = df.drop(columns=["Vol Mult"])

    st.dataframe(df, use_container_width=True, hide_index=True)

    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download F&O Scanner Results (CSV)",
        data=csv_data,
        file_name=f"nse_fno_ohl_{detected_date or datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv"
    )
else:
    st.warning("No F&O stocks matched Open=High or Open=Low for the last trading session.")
