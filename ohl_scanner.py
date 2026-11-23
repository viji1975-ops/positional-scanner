import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="NSE OHL Ultimate Scanner Pro", layout="wide")

# ==========================================
# 1. SIDEBAR CONFIGURATION
# ==========================================
st.sidebar.header("🔑 Upstox Configuration")
access_token = st.sidebar.text_input("Daily Upstox Access Token", type="password")
tolerance_pct = st.sidebar.number_input("OHL Tolerance (%)", min_value=0.0, max_value=1.0, value=0.0, step=0.05) / 100

WATCHLIST = {
    "NSE:RELIANCE":  "NSE_EQ|INE002A01018",
    "NSE:HDFCBANK":  "NSE_EQ|INE040A01034",
    "NSE:ICICIBANK": "NSE_EQ|INE090A01021",
    "NSE:INFY":      "NSE_EQ|INE009A01021",
    "NSE:TCS":       "NSE_EQ|INE467B01029",
    "NSE:VEDL":      "NSE_EQ|INE205A01025",
    "NSE:SBIN":      "NSE_EQ|INE062A01020",
    "NSE:TATAMOTORS":"NSE_EQ|INE155A01022",
    "NSE:AXISBANK":  "NSE_EQ|INE238A01034",
    "NSE:BHARTIARTL":"NSE_EQ|INE397D01024",
}

# ==========================================
# 2. CACHED API FUNCTIONS
# ==========================================
@st.cache_data(ttl=3600)
def get_20d_avg_15m_volume(instrument_key: str, token: str) -> float:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    encoded_key = instrument_key.replace("|", "%7C")
    
    url = f"https://upstox.com{encoded_key}/minutes/15/{to_date}/{from_date}"
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return 0.0
        
    candles = resp.json().get("data", {}).get("candles", [])
    if not candles:
        return 0.0
        
    df = pd.DataFrame(candles, columns=["ts", "o", "h", "l", "c", "v", "oi"])
    return float(df["v"].head(20).mean())

def get_intraday_candles(instrument_key: str, token: str):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    encoded_key = instrument_key.replace("|", "%7C")
    url = f"https://upstox.comintraday/{encoded_key}/minutes/15"
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        return None, resp.status_code
        
    candles = resp.json().get("data", {}).get("candles", [])
    if not candles:
        return None, 200
        
    candles.reverse()  # Index 0 becomes 09:15 AM candle
    return candles, 200

# ==========================================
# 3. DASHBOARD UI & SCANNER LOGIC
# ==========================================
st.title("📊 NSE OHL Ultimate Scanner Pro")

if not access_token:
    st.info("👈 Paste your daily Upstox Access Token in the left sidebar to run the scanner.")
    st.stop()

col1, col2 = st.columns([1, 4])
with col1:
    st.button("🔄 Refresh Now")
with col2:
    st.caption(f"Last Checked: {datetime.now().strftime('%H:%M:%S')} (Server Time)")

rows = []
progress = st.progress(0)
total = len(WATCHLIST)

for idx, (symbol, inst_key) in enumerate(WATCHLIST.items()):
    progress.progress((idx + 1) / total)
    candles, status_code = get_intraday_candles(inst_key, access_token)
    
    if status_code == 401:
        st.error("❌ Unauthorized: Your Upstox daily token is invalid or expired.")
        st.stop()
    if not candles:
        continue

    # Upstox candle format: [0:ts, 1:open, 2:high, 3:low, 4:close, 5:volume, 6:oi]
    first_candle = candles[0]
    o, h, l, v = float(first_candle[1]), float(first_candle[2]), float(first_candle[3]), float(first_candle[5])
    c = float(candles[-1][4])

    is_ol = (abs(o - l) <= o * tolerance_pct) and (h > o)
    is_oh = (abs(o - h) <= o * tolerance_pct) and (l < o)

    if not (is_ol or is_oh):
        continue

    avg_vol = get_20d_avg_15m_volume(inst_key, access_token)
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

    rows.append({
        "Symbol": symbol,
        "Pattern": pattern,
        "Status": status,
        "LTP": round(c, 2),
        "Normal Tgt (1:1 | 1:2)": f"{t1:.1f} | {t2:.1f}",
        "Rev Target": rev_tgt,
        "Stop Loss": round(sl, 1),
        "Volume": f"{v_mult:.2f}x",
        "Power": power
    })

progress.empty()

if rows:
    df_results = pd.DataFrame(rows)
    st.dataframe(df_results, use_container_width=True, hide_index=True)
else:
    st.warning("No Open=High or Open=Low setups matched right now (or market intraday data is empty).")
