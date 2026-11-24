import os
import gzip
import json
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

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

FALLBACK_FNO_STOCKS = {
    "NSE_EQ|INE002A01018": "NSE:RELIANCE", "NSE_EQ|INE467B01029": "NSE:TCS",
    "NSE_EQ|INE040A01034": "NSE:HDFCBANK", "NSE_EQ|INE090A01021": "NSE:ICICIBANK",
    "NSE_EQ|INE397D01024": "NSE:BHARTIARTL", "NSE_EQ|INE062A01020": "NSE:SBIN",
    "NSE_EQ|INE009A01021": "NSE:INFY", "NSE_EQ|INE154A01025": "NSE:ITC",
    "NSE_EQ|INE018A01030": "NSE:LT", "NSE_EQ|INE030A01027": "NSE:HINDUNILVR",
    "NSE_EQ|INE238A01034": "NSE:AXISBANK", "NSE_EQ|INE237A01028": "NSE:KOTAKBANK",
    "NSE_EQ|INE296A01024": "NSE:BAJFINANCE", "NSE_EQ|INE585B01010": "NSE:MARUTI",
    "NSE_EQ|INE044A01036": "NSE:SUNPHARMA", "NSE_EQ|INE280A01028": "NSE:TITAN",
    "NSE_EQ|INE752E01010": "NSE:POWERGRID", "NSE_EQ|INE733E01010": "NSE:NTPC",
    "NSE_EQ|INE481G01011": "NSE:ULTRACEMCO", "NSE_EQ|INE155A01022": "NSE:TATAMOTORS",
    "NSE_EQ|INE081A01020": "NSE:TATASTEEL", "NSE_EQ|INE101A01026": "NSE:M&M",
    "NSE_EQ|INE860A01027": "NSE:HCLTECH", "NSE_EQ|INE021A01026": "NSE:ASIANPAINT",
    "NSE_EQ|INE918I01026": "NSE:BAJAJFINSV", "NSE_EQ|INE423A01024": "NSE:ADANIENT",
    "NSE_EQ|INE742F01042": "NSE:ADANIPORTS", "NSE_EQ|INE522F01014": "NSE:COALINDIA",
    "NSE_EQ|INE075A01022": "NSE:WIPRO", "NSE_EQ|INE019A01038": "NSE:JSWSTEEL",
    "NSE_EQ|INE038A01020": "NSE:HINDALCO", "NSE_EQ|INE047A01021": "NSE:GRASIM",
    "NSE_EQ|INE066A01021": "NSE:EICHERMOT", "NSE_EQ|INE917I01010": "NSE:BAJAJ-AUTO",
    "NSE_EQ|INE121A01024": "NSE:CHOLAFIN", "NSE_EQ|INE361B01024": "NSE:DIVISLAB",
    "NSE_EQ|INE089A01023": "NSE:DRREDDY", "NSE_EQ|INE059A01026": "NSE:CIPLA",
    "NSE_EQ|INE669C01036": "NSE:TECHM", "NSE_EQ|INE216A01030": "NSE:BRITANNIA",
    "NSE_EQ|INE028A01039": "NSE:BANKBARODA", "NSE_EQ|INE160A01022": "NSE:PNB",
    "NSE_EQ|INE476A01022": "NSE:CANBK", "NSE_EQ|INE095A01012": "NSE:INDUSINDBK",
    "NSE_EQ|INE263A01024": "NSE:BEL", "NSE_EQ|INE066F01020": "NSE:HAL",
    "NSE_EQ|INE003A01024": "NSE:SIEMENS", "NSE_EQ|INE117A01022": "NSE:ABB",
    "NSE_EQ|INE129A01019": "NSE:GAIL", "NSE_EQ|INE213A01029": "NSE:ONGC",
    "NSE_EQ|INE242A01010": "NSE:IOC", "NSE_EQ|INE029A01011": "NSE:BPCL",
    "NSE_EQ|INE094A01015": "NSE:HINDPETRO", "NSE_EQ|INE848E01016": "NSE:NHPC",
    "NSE_EQ|INE134E01011": "NSE:PFC", "NSE_EQ|INE020B01018": "NSE:RECLTD",
    "NSE_EQ|INE115A01026": "NSE:LICHSGFIN", "NSE_EQ|INE774D01024": "NSE:M&MFIN",
    "NSE_EQ|INE721A01013": "NSE:SHRIRAMFIN", "NSE_EQ|INE498L01015": "NSE:LTF",
    "NSE_EQ|INE148I01020": "NSE:SAMVARDHANA", "NSE_EQ|INE775A01035": "NSE:MOTHERSON",
    "NSE_EQ|INE208A01029": "NSE:ASHOKLEY", "NSE_EQ|INE158A01026": "NSE:HEROMOTOCO",
    "NSE_EQ|INE494B01023": "NSE:TVSMOTOR", "NSE_EQ|INE323A01026": "NSE:BOSCHLTD",
    "NSE_EQ|INE298A01020": "NSE:CUMMINSIND", "NSE_EQ|INE465A01025": "NSE:BHARATFORG",
    "NSE_EQ|INE646L01027": "NSE:INDIGO", "NSE_EQ|INE883A01011": "NSE:MRF",
    "NSE_EQ|INE001A01036": "NSE:APOLLOTYRE", "NSE_EQ|INE765G01017": "NSE:ICICIGI",
    "NSE_EQ|INE726G01019": "NSE:ICICIPRULI", "NSE_EQ|INE123W01016": "NSE:SBILIFE",
    "NSE_EQ|INE795G01014": "NSE:HDFCLIFE", "NSE_EQ|INE127D01025": "NSE:HDFCAMC",
    "NSE_EQ|INE572E01012": "NSE:PNBHOUSING", "NSE_EQ|INE414G01012": "NSE:MUTHOOTFIN",
    "NSE_EQ|INE522D01027": "NSE:MANAPPURAM", "NSE_EQ|INE301A01014": "NSE:RAYMOND",
    "NSE_EQ|INE849A01020": "NSE:TRENT", "NSE_EQ|INE192R01011": "NSE:DMART",
    "NSE_EQ|INE271C01023": "NSE:DLF", "NSE_EQ|INE484J01027": "NSE:GODREJPROP",
    "NSE_EQ|INE093I01010": "NSE:OBEROIRLTY", "NSE_EQ|INE811K01011": "NSE:PRESTIGE",
    "NSE_EQ|INE669E01016": "NSE:IDEA", "NSE_EQ|INE121J01017": "NSE:INDUSTOWER",
    "NSE_EQ|INE256A01028": "NSE:ZEEL", "NSE_EQ|INE424H01027": "NSE:SUNTV",
    "NSE_EQ|INE335Y01020": "NSE:IRCTC", "NSE_EQ|INE111A01025": "NSE:CONCOR",
    "NSE_EQ|INE070A01015": "NSE:SHREECEM", "NSE_EQ|INE079A01024": "NSE:AMBUJACEM",
    "NSE_EQ|INE012A01025": "NSE:ACC", "NSE_EQ|INE439A01020": "NSE:DALBHARAT",
    "NSE_EQ|INE245A01021": "NSE:TATAPOWER", "NSE_EQ|INE814H01011": "NSE:ADANIPOWER",
    "NSE_EQ|INE364U01010": "NSE:ADANIGREEN", "NSE_EQ|INE931S01010": "NSE:ADANIENSOL",
    "NSE_EQ|INE399L01023": "NSE:ATGL", "NSE_EQ|INE406A01037": "NSE:AUROPHARMA",
    "NSE_EQ|INE326A01037": "NSE:LUPIN", "NSE_EQ|INE053F01010": "NSE:IRFC",
    "NSE_EQ|INE415G01027": "NSE:RVNL", "NSE_EQ|INE053A01029": "NSE:INDHOTEL",
    "NSE_EQ|INE437A01024": "NSE:APOLLOHOSP", "NSE_EQ|INE027H01010": "NSE:MAXHEALTH",
    "NSE_EQ|INE685A01028": "NSE:TORNTPHARM", "NSE_EQ|INE010B01027": "NSE:ZYDUSLIFE",
    "NSE_EQ|INE540L01014": "NSE:ALKEM", "NSE_EQ|INE376G01013": "NSE:BIOCON",
    "NSE_EQ|INE935N01020": "NSE:DIXON", "NSE_EQ|INE176B01034": "NSE:HAVELLS",
    "NSE_EQ|INE226A01021": "NSE:VOLTAS", "NSE_EQ|INE299U01018": "NSE:CROMPTON",
    "NSE_EQ|INE455K01017": "NSE:POLYCAB", "NSE_EQ|INE545U01014": "NSE:BANDHANBNK",
    "NSE_EQ|INE092T01019": "NSE:IDFCFIRSTB", "NSE_EQ|INE171A01029": "NSE:FEDERALBNK",
    "NSE_EQ|INE949L01017": "NSE:AUBANK", "NSE_EQ|INE976G01028": "NSE:RBLBANK",
    "NSE_EQ|INE016A01026": "NSE:DABUR", "NSE_EQ|INE196A01026": "NSE:MARICO",
    "NSE_EQ|INE102D01028": "NSE:GODREJCP", "NSE_EQ|INE259A01022": "NSE:COLPAL",
    "NSE_EQ|INE239A01016": "NSE:NESTLEIND", "NSE_EQ|INE192A01025": "NSE:TATACONSUM",
    "NSE_EQ|INE686F01025": "NSE:UBL", "NSE_EQ|INE854D01024": "NSE:UNITDSPR",
    "NSE_EQ|INE180A01020": "NSE:MFSL", "NSE_EQ|INE591G01017": "NSE:COFORGE",
    "NSE_EQ|INE214T01019": "NSE:LTIM", "NSE_EQ|INE356A01018": "NSE:MPHASIS",
    "NSE_EQ|INE262H01013": "NSE:PERSISTENT", "NSE_EQ|INE068V01023": "NSE:GLAND",
    "NSE_EQ|INE758T01015": "NSE:ZOMATO", "NSE_EQ|INE749A01030": "NSE:JINDALSTEL",
    "NSE_EQ|INE114A01011": "NSE:SAIL", "NSE_EQ|INE584A01023": "NSE:NMDC",
    "NSE_EQ|INE205A01025": "NSE:VEDL", "NSE_EQ|INE120A01034": "NSE:CARBORUNIV",
    "NSE_EQ|INE007A01025": "NSE:CRISIL", "NSE_EQ|INE306R01017": "NSE:INTELLECT",
    "NSE_EQ|INE274J01014": "NSE:JSWENERGY", "NSE_EQ|INE881D01027": "NSE:OFSS",
    "NSE_EQ|INE769A01020": "NSE:AARTIIND", "NSE_EQ|INE054A01027": "NSE:VIPIND",
    "NSE_EQ|INE603J01030": "NSE:PIIND", "NSE_EQ|INE628A01036": "NSE:UPL",
    "NSE_EQ|INE067A01029": "NSE:CGPOWER", "NSE_EQ|INE257A01026": "NSE:BHEL",
    "NSE_EQ|INE177H01021": "NSE:GODREJIND", "NSE_EQ|INE463V01026": "NSE:ANANDRATHI",
}

@st.cache_data(ttl=43200)
def get_all_fno_stocks():
    """Downloads Upstox NSE instrument master, falling back to built-in NSE F&O list if CDN blocks cloud IP."""
    urls = [
        "https://upstox.com",
        "https://upstox.com",
    ]
    cdn_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://upstox.com/",
    }

    for url in urls:
        try:
            res = requests.get(url, headers=cdn_headers, timeout=15)
            if res.status_code != 200:
                continue
            if res.content[:2] == b"\x1f\x8b":
                raw_data = gzip.decompress(res.content).decode("utf-8")
            else:
                raw_data = res.text
            if raw_data.lstrip().startswith("["):
                instruments = json.loads(raw_data)
                fno_equities = {}
                for item in instruments:
                    if item.get("segment") == "NSE_FO":
                        u_key = item.get("underlying_key", "")
                        u_sym = item.get("underlying_symbol", "")
                        u_type = item.get("underlying_type", "")
                        if u_key.startswith("NSE_EQ|") and u_type == "EQUITY" and u_sym:
                            fno_equities[u_key] = f"NSE:{u_sym}"
                if fno_equities:
                    return dict(sorted(fno_equities.items(), key=lambda x: x))
        except Exception:
            continue

    return dict(sorted(FALLBACK_FNO_STOCKS.items(), key=lambda x: x))

@st.cache_data(ttl=900, show_spinner=False)
def _fetch_candle_v3(encoded_key, to_date, from_date, token):
    """Fetches daily candles using Upstox V3 Historical Candle API."""
    url = f"https://upstox.com{encoded_key}/days/1/{to_date}/{from_date}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}"
    }
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code != 200:
        return {"_error": f"HTTP {res.status_code}: {res.text[:150]}"}
    return res.json()

def get_historical_stats(instrument_key, token):
    """Computes 14-day ATR, 20-day Avg Vol, PDH/PDL, and latest candle from Upstox V3."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    encoded_key = quote(instrument_key.strip(), safe="")

    try:
        payload = _fetch_candle_v3(encoded_key, to_date, from_date, token)
    except Exception:
        return None

    if not payload or "_error" in payload:
        return None

    candles = payload.get("data", {}).get("candles", [])
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

def enrich_from_quote(item):
    key, symbol, open_p, ltp, curr_vol, is_open_high = item
    stats = get_historical_stats(key, ACCESS_TOKEN)
    if not stats:
        return None
    return build_row(symbol, open_p, ltp, curr_vol, is_open_high, stats)

def scan_via_candle(kv):
    key, symbol = kv
    stats = get_historical_stats(key, ACCESS_TOKEN)
    if not stats:
        return None, None
    lc = stats["last_candle"]
    candle_date = str(lc["time"])[:10]

    open_p = lc["open"]
    high_p = lc["high"]
    low_p = lc["low"]
    ltp = lc["close"]
    curr_vol = lc["volume"]

    is_open_high, is_open_low = is_exact_ohol(open_p, high_p, low_p)

    if is_open_high and "Open=Low Only" in pattern_filter:
        return None, candle_date
    if is_open_low and "Open=High Only" in pattern_filter:
        return None, candle_date

    if is_open_high or is_open_low:
        return build_row(symbol, open_p, ltp, curr_vol, is_open_high, stats), candle_date
    return None, candle_date

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

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = [r for r in executor.map(enrich_from_quote, candidates) if r is not None]

    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            candle_outputs = list(executor.map(scan_via_candle, list(fno_dict.items())))

        session_dates = [d for _, d in candle_outputs if d is not None]
        results = [r for r, _ in candle_outputs if r is not None]
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
