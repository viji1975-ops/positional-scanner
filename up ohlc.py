import os
import gzip
import json
import time
import requests
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="NSE F&O Exact OHOL + ORB + Options Scanner", layout="wide")

# --- Sidebar: Broker API Settings & Filters ---
st.sidebar.header("🔑 Broker API Settings")
broker_choice = st.sidebar.radio("Live Data Source", ["Fyers API v3 (Recommended)", "Upstox API v2"])

FYERS_APP_ID = ""
FYERS_TOKEN = ""
UPSTOX_TOKEN = ""

if "Fyers" in broker_choice:
    default_fyers_id = st.secrets.get("FYERS_APP_ID", os.getenv("FYERS_APP_ID", "")).strip()
    default_fyers_tok = st.secrets.get("FYERS_ACCESS_TOKEN", os.getenv("FYERS_ACCESS_TOKEN", "")).strip()

    FYERS_APP_ID = st.sidebar.text_input(
        "Fyers App ID (e.g. XXXXX-100)",
        value=default_fyers_id,
        placeholder="Leave blank if pasting AppID:Token below"
    ).strip()

    fyers_input = st.sidebar.text_input(
        "Paste Daily Fyers Access Token",
        value="",
        type="password",
        placeholder="Paste full JWT Access Token (eyJ...)..."
    ).strip()

    raw_fyers = fyers_input if fyers_input else default_fyers_tok
    if raw_fyers:
        if ":" in raw_fyers:
            FYERS_TOKEN = raw_fyers
            st.sidebar.success("✅ Fyers AppID:Token ready")
        elif FYERS_APP_ID:
            FYERS_TOKEN = f"{FYERS_APP_ID}:{raw_fyers}"
            st.sidebar.success("✅ Fyers Token combined with App ID")
        else:
            st.sidebar.warning("⚠️ Enter your Fyers App ID above (e.g. XXXXX-100)")
    else:
        st.sidebar.info("ℹ️ Paste Fyers JWT token for live market ticks (shows last session when closed)")
else:
    default_upstox = st.secrets.get("UPSTOX_ACCESS_TOKEN", os.getenv("UPSTOX_ACCESS_TOKEN", "")).strip()
    upstox_input = st.sidebar.text_input(
        "Paste Daily Upstox Access Token",
        value="",
        type="password",
        placeholder="Paste today's Upstox token..."
    ).strip()
    UPSTOX_TOKEN = upstox_input if upstox_input else default_upstox
    if UPSTOX_TOKEN:
        st.sidebar.success("✅ Upstox Token ready")
    else:
        st.sidebar.info("ℹ️ Paste Upstox token for live quotes")

st.sidebar.divider()
st.sidebar.header("⚙️ Scanner & ORB Filters")
pattern_filter = st.sidebar.selectbox(
    "Show Exact Patterns",
    ["All (Open=High & Open=Low)", "Open=High Only (Bearish)", "Open=Low Only (Bullish)"]
)
orb_timeframe = st.sidebar.radio(
    "ORB Confirmation Window",
    ["15-Min ORB (9:15–9:30 AM)", "5-Min ORB (9:15–9:20 AM)"]
)
only_orb_confirmed = st.sidebar.checkbox("Show Only ORB Confirmed Setups", value=False)
auto_refresh = st.sidebar.checkbox("🔄 Auto-Refresh Every 60s", value=False)

FNO_STOCKS = {
    "NSE_EQ|INE002A01018": "RELIANCE", "NSE_EQ|INE467B01029": "TCS",
    "NSE_EQ|INE040A01034": "HDFCBANK", "NSE_EQ|INE090A01021": "ICICIBANK",
    "NSE_EQ|INE397D01024": "BHARTIARTL", "NSE_EQ|INE062A01020": "SBIN",
    "NSE_EQ|INE009A01021": "INFY", "NSE_EQ|INE154A01025": "ITC",
    "NSE_EQ|INE018A01030": "LT", "NSE_EQ|INE030A01027": "HINDUNILVR",
    "NSE_EQ|INE238A01034": "AXISBANK", "NSE_EQ|INE237A01028": "KOTAKBANK",
    "NSE_EQ|INE296A01024": "BAJFINANCE", "NSE_EQ|INE585B01010": "MARUTI",
    "NSE_EQ|INE044A01036": "SUNPHARMA", "NSE_EQ|INE280A01028": "TITAN",
    "NSE_EQ|INE752E01010": "POWERGRID", "NSE_EQ|INE733E01010": "NTPC",
    "NSE_EQ|INE481G01011": "ULTRACEMCO", "NSE_EQ|INE155A01022": "TATAMOTORS",
    "NSE_EQ|INE081A01020": "TATASTEEL", "NSE_EQ|INE101A01026": "M&M",
    "NSE_EQ|INE860A01027": "HCLTECH", "NSE_EQ|INE021A01026": "ASIANPAINT",
    "NSE_EQ|INE918I01026": "BAJAJFINSV", "NSE_EQ|INE423A01024": "ADANIENT",
    "NSE_EQ|INE742F01042": "ADANIPORTS", "NSE_EQ|INE522F01014": "COALINDIA",
    "NSE_EQ|INE075A01022": "WIPRO", "NSE_EQ|INE019A01038": "JSWSTEEL",
    "NSE_EQ|INE038A01020": "HINDALCO", "NSE_EQ|INE047A01021": "GRASIM",
    "NSE_EQ|INE066A01021": "EICHERMOT", "NSE_EQ|INE917I01010": "BAJAJ-AUTO",
    "NSE_EQ|INE121A01024": "CHOLAFIN", "NSE_EQ|INE361B01024": "DIVISLAB",
    "NSE_EQ|INE089A01023": "DRREDDY", "NSE_EQ|INE059A01026": "CIPLA",
    "NSE_EQ|INE669C01036": "TECHM", "NSE_EQ|INE216A01030": "BRITANNIA",
    "NSE_EQ|INE028A01039": "BANKBARODA", "NSE_EQ|INE160A01022": "PNB",
    "NSE_EQ|INE476A01022": "CANBK", "NSE_EQ|INE095A01012": "INDUSINDBK",
    "NSE_EQ|INE263A01024": "BEL", "NSE_EQ|INE066F01020": "HAL",
    "NSE_EQ|INE003A01024": "SIEMENS", "NSE_EQ|INE117A01022": "ABB",
    "NSE_EQ|INE129A01019": "GAIL", "NSE_EQ|INE213A01029": "ONGC",
    "NSE_EQ|INE242A01010": "IOC", "NSE_EQ|INE029A01011": "BPCL",
    "NSE_EQ|INE094A01015": "HINDPETRO", "NSE_EQ|INE848E01016": "NHPC",
    "NSE_EQ|INE134E01011": "PFC", "NSE_EQ|INE020B01018": "RECLTD",
    "NSE_EQ|INE115A01026": "LICHSGFIN", "NSE_EQ|INE774D01024": "M&MFIN",
    "NSE_EQ|INE721A01013": "SHRIRAMFIN", "NSE_EQ|INE498L01015": "LTF",
    "NSE_EQ|INE148I01020": "MOTHERSON", "NSE_EQ|INE208A01029": "ASHOKLEY",
    "NSE_EQ|INE158A01026": "HEROMOTOCO", "NSE_EQ|INE494B01023": "TVSMOTOR",
    "NSE_EQ|INE323A01026": "BOSCHLTD", "NSE_EQ|INE298A01020": "CUMMINSIND",
    "NSE_EQ|INE465A01025": "BHARATFORG", "NSE_EQ|INE646L01027": "INDIGO",
    "NSE_EQ|INE883A01011": "MRF", "NSE_EQ|INE001A01036": "APOLLOTYRE",
    "NSE_EQ|INE765G01017": "ICICIGI", "NSE_EQ|INE726G01019": "ICICIPRULI",
    "NSE_EQ|INE123W01016": "SBILIFE", "NSE_EQ|INE795G01014": "HDFCLIFE",
    "NSE_EQ|INE127D01025": "HDFCAMC", "NSE_EQ|INE572E01012": "PNBHOUSING",
    "NSE_EQ|INE414G01012": "MUTHOOTFIN", "NSE_EQ|INE522D01027": "MANAPPURAM",
    "NSE_EQ|INE301A01014": "RAYMOND", "NSE_EQ|INE849A01020": "TRENT",
    "NSE_EQ|INE192R01011": "DMART", "NSE_EQ|INE271C01023": "DLF",
    "NSE_EQ|INE484J01027": "GODREJPROP", "NSE_EQ|INE093I01010": "OBEROIRLTY",
    "NSE_EQ|INE811K01011": "PRESTIGE", "NSE_EQ|INE669E01016": "IDEA",
    "NSE_EQ|INE121J01017": "INDUSTOWER", "NSE_EQ|INE256A01028": "ZEEL",
    "NSE_EQ|INE424H01027": "SUNTV", "NSE_EQ|INE335Y01020": "IRCTC",
    "NSE_EQ|INE111A01025": "CONCOR", "NSE_EQ|INE070A01015": "SHREECEM",
    "NSE_EQ|INE079A01024": "AMBUJACEM", "NSE_EQ|INE012A01025": "ACC",
    "NSE_EQ|INE439A01020": "DALBHARAT", "NSE_EQ|INE245A01021": "TATAPOWER",
    "NSE_EQ|INE814H01011": "ADANIPOWER", "NSE_EQ|INE364U01010": "ADANIGREEN",
    "NSE_EQ|INE931S01010": "ADANIENSOL", "NSE_EQ|INE399L01023": "ATGL",
    "NSE_EQ|INE406A01037": "AUROPHARMA", "NSE_EQ|INE326A01037": "LUPIN",
    "NSE_EQ|INE053F01010": "IRFC", "NSE_EQ|INE415G01027": "RVNL",
    "NSE_EQ|INE053A01029": "INDHOTEL", "NSE_EQ|INE437A01024": "APOLLOHOSP",
    "NSE_EQ|INE027H01010": "MAXHEALTH", "NSE_EQ|INE685A01028": "TORNTPHARM",
    "NSE_EQ|INE010B01027": "ZYDUSLIFE", "NSE_EQ|INE540L01014": "ALKEM",
    "NSE_EQ|INE376G01013": "BIOCON", "NSE_EQ|INE935N01020": "DIXON",
    "NSE_EQ|INE176B01034": "HAVELLS", "NSE_EQ|INE226A01021": "VOLTAS",
    "NSE_EQ|INE299U01018": "CROMPTON", "NSE_EQ|INE455K01017": "POLYCAB",
    "NSE_EQ|INE545U01014": "BANDHANBNK", "NSE_EQ|INE092T01019": "IDFCFIRSTB",
    "NSE_EQ|INE171A01029": "FEDERALBNK", "NSE_EQ|INE949L01017": "AUBANK",
    "NSE_EQ|INE976G01028": "RBLBANK", "NSE_EQ|INE016A01026": "DABUR",
    "NSE_EQ|INE196A01026": "MARICO", "NSE_EQ|INE102D01028": "GODREJCP",
    "NSE_EQ|INE259A01022": "COLPAL", "NSE_EQ|INE239A01016": "NESTLEIND",
    "NSE_EQ|INE192A01025": "TATACONSUM", "NSE_EQ|INE686F01025": "UBL",
    "NSE_EQ|INE854D01024": "UNITDSPR", "NSE_EQ|INE180A01020": "MFSL",
    "NSE_EQ|INE591G01017": "COFORGE", "NSE_EQ|INE214T01019": "LTIM",
    "NSE_EQ|INE356A01018": "MPHASIS", "NSE_EQ|INE262H01013": "PERSISTENT",
    "NSE_EQ|INE068V01023": "GLAND", "NSE_EQ|INE749A01030": "JINDALSTEL",
    "NSE_EQ|INE114A01011": "SAIL", "NSE_EQ|INE584A01023": "NMDC",
    "NSE_EQ|INE205A01025": "VEDL", "NSE_EQ|INE274J01014": "JSWENERGY",
    "NSE_EQ|INE881D01027": "OFSS", "NSE_EQ|INE769A01020": "AARTIIND",
    "NSE_EQ|INE603J01030": "PIIND", "NSE_EQ|INE628A01036": "UPL",
    "NSE_EQ|INE067A01029": "CGPOWER", "NSE_EQ|INE257A01026": "BHEL",
    "NSE_EQ|INE177H01021": "GODREJIND", "NSE_EQ|INE463V01026": "ANANDRATHI",
}

DEFAULT_LOT_SIZES = {
    "RELIANCE": 500, "TCS": 175, "HDFCBANK": 550, "ICICIBANK": 700, "BHARTIARTL": 475,
    "SBIN": 750, "INFY": 400, "ITC": 1600, "LT": 150, "HINDUNILVR": 300,
    "AXISBANK": 625, "KOTAKBANK": 400, "BAJFINANCE": 750, "MARUTI": 50, "SUNPHARMA": 350,
    "TITAN": 175, "POWERGRID": 1800, "NTPC": 1500, "ULTRACEMCO": 50, "TATAMOTORS": 550,
    "TATASTEEL": 5500, "M&M": 350, "HCLTECH": 350, "ASIANPAINT": 250, "BAJAJFINSV": 500,
    "ADANIENT": 300, "ADANIPORTS": 400, "COALINDIA": 1350, "WIPRO": 3000, "JSWSTEEL": 675,
    "HINDALCO": 1400, "GRASIM": 250, "EICHERMOT": 175, "BAJAJ-AUTO": 75, "CHOLAFIN": 625,
    "DIVISLAB": 100, "DRREDDY": 625, "CIPLA": 325, "TECHM": 600, "BRITANNIA": 100,
    "BANKBARODA": 2925, "PNB": 8000, "CANBK": 6750, "INDUSINDBK": 500, "BEL": 2850,
    "HAL": 150, "SIEMENS": 75, "ABB": 125, "GAIL": 3150, "ONGC": 2250,
    "IOC": 4875, "BPCL": 1800, "HINDPETRO": 2025, "NHPC": 6400, "PFC": 1300,
    "RECLTD": 1250, "LICHSGFIN": 1000, "M&MFIN": 2000, "SHRIRAMFIN": 150, "LTF": 4462,
    "MOTHERSON": 4250, "ASHOKLEY": 2500, "HEROMOTOCO": 150, "TVSMOTOR": 350, "BOSCHLTD": 25,
    "CUMMINSIND": 300, "BHARATFORG": 500, "INDIGO": 150, "MRF": 5, "APOLLOTYRE": 1700,
    "ICICIGI": 325, "ICICIPRULI": 750, "SBILIFE": 375, "HDFCLIFE": 1100, "HDFCAMC": 150,
    "PNBHOUSING": 650, "MUTHOOTFIN": 275, "MANAPPURAM": 3000, "RAYMOND": 375, "TRENT": 100,
    "DMART": 150, "DLF": 825, "GODREJPROP": 225, "OBEROIRLTY": 350, "PRESTIGE": 325,
    "IDEA": 40000, "INDUSTOWER": 1700, "ZEEL": 4500, "SUNTV": 750, "IRCTC": 875,
    "CONCOR": 1000, "SHREECEM": 25, "AMBUJACEM": 1050, "ACC": 300, "DALBHARAT": 275,
    "TATAPOWER": 1350, "ADANIPOWER": 1000, "ADANIGREEN": 600, "ADANIENSOL": 675, "ATGL": 800,
    "AUROPHARMA": 550, "LUPIN": 425, "IRFC": 4250, "RVNL": 1375, "INDHOTEL": 1000,
}
@st.cache_data(ttl=43200, show_spinner=False)
def get_live_lot_sizes():
    """Fetches current NSE F&O lot sizes from Fyers public symbol master, falling back to DEFAULT_LOT_SIZES."""
    lot_map = dict(DEFAULT_LOT_SIZES)
    try:
        res = requests.get("https://fyers.in", timeout=12)
        if res.status_code == 200 and "OPTSTK" in res.text:
            for line in res.text.splitlines():
                cols = line.split(",")
                if len(cols) > 13 and cols[13].strip():
                    u_sym = cols[13].strip()
                    lot_val = int(float(cols[3].strip()))
                    if u_sym in lot_map and lot_val > 0:
                        lot_map[u_sym] = lot_val
    except Exception:
        pass
    return lot_map

def get_option_strikes(ltp, is_open_high):
    """Computes NSE ATM and 1-step ITM option strikes (PE for Open=High, CE for Open=Low)."""
    if ltp < 100:
        step = 1
    elif ltp < 250:
        step = 2.5
    elif ltp < 500:
        step = 5
    elif ltp < 1000:
        step = 10
    elif ltp < 2500:
        step = 20
    elif ltp < 5000:
        step = 50
    elif ltp < 15000:
        step = 100
    else:
        step = 250

    atm = round(ltp / step) * step
    if is_open_high:
        itm = atm + step
        opt_type = "PE"
    else:
        itm = atm - step
        opt_type = "CE"

    fmt = lambda x: f"{int(x)}" if x == int(x) else f"{x:.1f}"
    return f"{fmt(atm)} {opt_type} | {fmt(itm)} {opt_type}"

def is_exact_ohol(open_p, high_p, low_p):
    o = round(float(open_p), 2)
    h = round(float(high_p), 2)
    l = round(float(low_p), 2)
    if o <= 0 or h == l:
        return False, False
    return (o == h), (o == l)

@st.cache_data(ttl=120, show_spinner=False)
def get_orb_status_map(matched_symbols_tuple, orb_minutes):
    """Fetches 5m intraday candles for matched symbols to check 5m or 15m ORB breakout/breakdown."""
    if not matched_symbols_tuple:
        return {}
    tickers = [f"{s}.NS" for s in matched_symbols_tuple]
    raw = yf.download(tickers, period="2d", interval="5m", group_by="ticker", progress=False, threads=True)
    if raw.empty:
        return {}

    candles_needed = 1 if orb_minutes == 5 else 3
    orb_map = {}

    for sym in matched_symbols_tuple:
        try:
            df = raw[f"{sym}.NS"].dropna() if len(matched_symbols_tuple) > 1 else raw.dropna()
            if df.empty:
                continue
            last_day = df.index[-1].date()
            day_df = df[df.index.date == last_day]
            if len(day_df) < candles_needed:
                continue

            orb_slice = day_df.iloc[:candles_needed]
            orb_high = float(orb_slice["High"].max())
            orb_low = float(orb_slice["Low"].min())
            latest_close = float(day_df.iloc[-1]["Close"])

            orb_map[sym] = {
                "orb_high": orb_high,
                "orb_low": orb_low,
                "latest_close": latest_close,
            }
        except Exception:
            continue

    return orb_map

def format_orb_signal(sym, is_open_high, ltp, orb_map, orb_minutes):
    info = orb_map.get(sym)
    if not info:
        return "⏳ Pending ORB", False

    price_to_check = ltp if ltp > 0 else info["latest_close"]
    if is_open_high:
        lvl = info["orb_low"]
        if price_to_check < lvl:
            return f"✅ {orb_minutes}m Broken (<{lvl:.1f})", True
        return f"⏳ Inside (>{lvl:.1f})", False
    else:
        lvl = info["orb_high"]
        if price_to_check > lvl:
            return f"✅ {orb_minutes}m Breakout (>{lvl:.1f})", True
        return f"⏳ Inside (<{lvl:.1f})", False

def build_row(symbol, open_p, ltp, curr_vol, is_open_high, atr, avg_vol, pdh, pdl, orb_text, orb_ok, lot_size):
    risk_unit = atr * 0.5
    vol_ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0

    if vol_ratio >= 4.0:
        power, power_rank = "🔥 Ultra", 3
    elif vol_ratio >= 2.0:
        power, power_rank = "⚡ Strong", 2
    else:
        power, power_rank = "Normal", 1

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
        "Symbol": f"NSE:{symbol}",
        "Pattern": pattern,
        "ORB Confirm": orb_text,
        "Status": status,
        "Price (₹)": f"{ltp:.2f}",
        "ATM | 1-ITM Option": get_option_strikes(ltp, is_open_high),
        "Lot Size": lot_size,
        "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
        "Rev Target": rev_tgt,
        "PDH/PDL": level_tag,
        "Volume": f"{vol_ratio}x",
        "Power": power,
        "_orb_ok": orb_ok,
        "_vol_ratio": vol_ratio,
        "_power_rank": power_rank
    }

@st.cache_data(ttl=600, show_spinner=False)
def get_baseline_stats(symbols_tuple):
    tickers = [f"{s}.NS" for s in symbols_tuple]
    raw = yf.download(tickers, period="35d", interval="1d", group_by="ticker", progress=False, threads=True)
    if raw.empty:
        return {}, "No Data"

    stats_map = {}
    last_date = ""

    for sym in symbols_tuple:
        try:
            df = raw[f"{sym}.NS"].dropna().copy()
            if len(df) < 15:
                continue
            if not last_date:
                last_date = str(df.index[-1])[:10]

            df["prev_close"] = df["Close"].shift(1)
            df["tr"] = df[["High", "prev_close"]].max(axis=1) - df[["Low", "prev_close"]].min(axis=1)
            atr_14 = round(float(df["tr"].tail(14).mean()), 2)
            avg_vol_20 = float(df["Volume"].tail(20).mean())

            last_row, prev_row = df.iloc[-1], df.iloc[-2]
            stats_map[sym] = {
                "open": float(last_row["Open"]),
                "high": float(last_row["High"]),
                "low": float(last_row["Low"]),
                "ltp": float(last_row["Close"]),
                "vol": float(last_row["Volume"]),
                "atr": atr_14,
                "avg_vol": avg_vol_20,
                "pdh": float(prev_row["High"]),
                "pdl": float(prev_row["Low"]),
            }
        except Exception:
            continue

    return stats_map, last_date

def fetch_fyers_live(symbols, fyers_auth_token):
    if not fyers_auth_token:
        return None, "No Fyers token entered"
    token_part = fyers_auth_token.split(":", 1)[-1]
    if len(token_part) < 50:
        return None, "Paste full Fyers JWT Access Token (eyJ...), not Client ID"

    url = "https://fyers.in"
    headers = {"Authorization": fyers_auth_token}
    quotes_by_sym = {}

    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]
        fyers_syms = ",".join(f"NSE:{s}-EQ" for s in batch)
        try:
            res = requests.get(url, headers=headers, params={"symbols": fyers_syms}, timeout=12)
            if res.status_code in (401, 403):
                return None, f"Token expired or invalid (HTTP {res.status_code})"
            if res.status_code != 200 or not res.text.strip():
                return None, f"Market closed / Fyers offline (HTTP {res.status_code})"
            payload = res.json()
            if payload.get("s") != "ok":
                return None, payload.get("message", "Fyers API error")

            for item in payload.get("d", []):
                v = item.get("v", {})
                clean_sym = item.get("n", "").replace("NSE:", "").replace("-EQ", "")
                if clean_sym and v.get("open_price", 0) > 0:
                    quotes_by_sym[clean_sym] = {
                        "open": float(v.get("open_price", 0)),
                        "high": float(v.get("high_price", 0)),
                        "low": float(v.get("low_price", 0)),
                        "ltp": float(v.get("lp", 0)),
                        "vol": float(v.get("volume", 0)),
                    }
        except Exception as e:
            return None, f"Fyers offline: {e}"
        time.sleep(0.1)

    if not quotes_by_sym:
        return None, "Market closed / open=0"
    return quotes_by_sym, None

def fetch_upstox_live(fno_dict, upstox_token):
    if not upstox_token:
        return None, "No Upstox token entered"

    url = "https://upstox.com"
    headers = {"Accept": "application/json", "Api-Version": "2.0", "Authorization": f"Bearer {upstox_token}"}
    keys = list(fno_dict.keys())
    quotes_by_sym = {}

    for i in range(0, len(keys), 50):
        batch = keys[i:i + 50]
        try:
            res = requests.get(url, headers=headers, params={"instrument_key": ",".join(batch)}, timeout=10)
            if res.status_code != 200 or not res.text.strip():
                return None, f"Market closed / HTTP {res.status_code}"
            payload = res.json()
            if payload.get("status") != "success":
                return None, "API error"
            for q_data in payload.get("data", {}).values():
                sym = fno_dict.get(q_data.get("instrument_token", ""))
                ohlc = q_data.get("ohlc", {})
                if sym and ohlc.get("open", 0) > 0:
                    quotes_by_sym[sym] = {
                        "open": float(ohlc.get("open", 0)),
                        "high": float(ohlc.get("high", 0)),
                        "low": float(ohlc.get("low", 0)),
                        "ltp": float(q_data.get("last_price", 0)),
                        "vol": float(q_data.get("volume", 0)),
                    }
        except Exception as e:
            return None, str(e)

    if not quotes_by_sym:
        return None, "Market closed / open=0"
    return quotes_by_sym, None

def run_scanner():
    symbols = tuple(sorted(FNO_STOCKS.values()))
    total_fno = len(symbols)
    stats_map, last_date = get_baseline_stats(symbols)
    lot_map = get_live_lot_sizes()
    orb_mins = 5 if "5-Min" in orb_timeframe else 15

    if "Fyers" in broker_choice:
        live_quotes, api_note = fetch_fyers_live(symbols, FYERS_TOKEN)
        broker_label = "Fyers API v3"
    else:
        live_quotes, api_note = fetch_upstox_live(FNO_STOCKS, UPSTOX_TOKEN)
        broker_label = "Upstox API v2"

    matched_candidates = []
    if live_quotes:
        source_note = f"{broker_label} Live Feed (Exact Match)"
        for sym, q in live_quotes.items():
            st_info = stats_map.get(sym)
            if not st_info:
                continue
            is_open_high, is_open_low = is_exact_ohol(q["open"], q["high"], q["low"])
            if is_open_high or is_open_low:
                matched_candidates.append((sym, q["open"], q["ltp"], q["vol"], is_open_high, st_info))
    else:
        source_note = f"Last Trading Session ({last_date} — Exact Match | {broker_label}: {api_note})"
        for sym, st_info in stats_map.items():
            is_open_high, is_open_low = is_exact_ohol(st_info["open"], st_info["high"], st_info["low"])
            if is_open_high or is_open_low:
                matched_candidates.append((sym, st_info["open"], st_info["ltp"], st_info["vol"], is_open_high, st_info))

    matched_syms = tuple(sorted(set(m[0] for m in matched_candidates)))
    orb_map = get_orb_status_map(matched_syms, orb_mins)

    raw_rows = []
    for sym, open_p, ltp, curr_vol, is_open_high, st_info in matched_candidates:
        orb_text, orb_ok = format_orb_signal(sym, is_open_high, ltp, orb_map, orb_mins)
        lot_size = lot_map.get(sym, 0)
        raw_rows.append(build_row(
            sym, open_p, ltp, curr_vol, is_open_high,
            st_info["atr"], st_info["avg_vol"], st_info["pdh"], st_info["pdl"],
            orb_text, orb_ok, lot_size
        ))

    filtered = []
    for r in raw_rows:
        if "Open=Low Only" in pattern_filter and "Open=High" in r["Pattern"]:
            continue
        if "Open=High Only" in pattern_filter and "Open=Low" in r["Pattern"]:
            continue
        if only_orb_confirmed and not r["_orb_ok"]:
            continue
        filtered.append(r)

    df_out = pd.DataFrame(filtered)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_orb_ok", "_power_rank", "_vol_ratio"], ascending=[False, False, False])
        df_out = df_out.drop(columns=["_orb_ok", "_vol_ratio", "_power_rank"])

    return df_out, source_note, total_fno

def style_scanner_table(df):
    def highlight_pattern(val):
        if "Open=High" in str(val):
            return "color: #ff5252; font-weight: bold;"
        elif "Open=Low" in str(val):
            return "color: #4caf50; font-weight: bold;"
        return ""

    def highlight_orb(val):
        if "✅" in str(val):
            return "color: #00e676; font-weight: bold;"
        return "color: #ffb74d;"

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
        .map(highlight_orb, subset=["ORB Confirm"])
        .map(highlight_status, subset=["Status"])
        .map(lambda _: "color: #ffd54f; font-weight: bold;", subset=["ATM | 1-ITM Option"])
        .map(lambda _: "color: #00bcd4; font-weight: bold;", subset=["Normal Tgt (1:1|1:2)"])
        .map(highlight_power, subset=["Power"])
    )

# --- Main App UI ---
st.subheader("📊 NSE F&O Exact Open=High / Open=Low + ORB & Options Scanner")

col_btn, col_info = st.columns([1, 5])
with col_btn:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Scanning NSE F&O stocks, ORB levels & Option strikes..."):
    df_results, source_note, total_fno = run_scanner()

with col_info:
    st.caption(f"Scanned **{total_fno} F&O Stocks** | Mode: **{source_note}**")

if not df_results.empty:
    bull_count = df_results["Pattern"].str.contains("Open=Low").sum()
    bear_count = df_results["Pattern"].str.contains("Open=High").sum()
    orb_count = df_results["ORB Confirm"].str.contains("✅").sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Exact Matches", len(df_results))
    m2.metric("🟢 Open=Low (Bullish)", int(bull_count))
    m3.metric("🔴 Open=High (Bearish)", int(bear_count))
    m4.metric("✅ ORB Confirmed", int(orb_count))

    st.dataframe(style_scanner_table(df_results), use_container_width=True, hide_index=True, height=560)
else:
    st.info("No F&O stocks matched your current filters in this session.")

if auto_refresh:
    time.sleep(60)
    st.rerun()
