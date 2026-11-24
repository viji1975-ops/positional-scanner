import os
import time
import hashlib
import requests
import pandas as pd
import streamlit as st
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Fyers NSE F&O Exact OHOL + ORB Scanner", layout="wide")

# --- Sidebar: Built-in Fyers v3 Login & Token Generator ---
st.sidebar.header("🔑 Fyers API v3 Login")

default_fyers_id = st.secrets.get("FYERS_APP_ID", os.getenv("FYERS_APP_ID", "D2B1MP5NVR-100")).strip()
default_secret = st.secrets.get("FYERS_SECRET_ID", os.getenv("FYERS_SECRET_ID", "")).strip()
redirect_uri = "https://127.0.0.1"

FYERS_APP_ID = st.sidebar.text_input("Fyers App ID", value=default_fyers_id).strip()
FYERS_SECRET_ID = st.sidebar.text_input("Fyers Secret ID", value=default_secret, type="password", placeholder="Paste Secret ID from Fyers dashboard").strip()

if "fyers_jwt_token" not in st.session_state:
    st.session_state["fyers_jwt_token"] = st.secrets.get("FYERS_ACCESS_TOKEN", os.getenv("FYERS_ACCESS_TOKEN", "")).strip()

# Step 1: Generate Login Link
if FYERS_APP_ID:
    fyers_host = "https://" + "api-t1." + "fyers.in" + "/api/v3/generate-authcode"
    login_url = (
        f"{fyers_host}"
        f"?client_id={quote(FYERS_APP_ID)}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        f"&response_type=code&state=scanner"
    )
    st.sidebar.markdown(f"**Step 1:** [👉 Click Here to Login to Fyers]({login_url})")

# Step 2: Paste the redirected URL (https://127.0.0...)
redirected_input = st.sidebar.text_input(
    "Step 2: Paste Redirected URL (or auth_code)",
    value="",
    placeholder="Paste full https://127.0.0?... URL here"
).strip()

if redirected_input and FYERS_APP_ID and FYERS_SECRET_ID:
    auth_code = redirected_input
    if "auth_code=" in redirected_input:
        parsed = parse_qs(urlparse(redirected_input).query)
        auth_code = parsed.get("auth_code", [""])[0]

    if auth_code and st.session_state.get("last_used_auth_code") != auth_code:
        app_id_hash = hashlib.sha256(f"{FYERS_APP_ID}:{FYERS_SECRET_ID}".encode()).hexdigest()
        validate_url = "https://" + "api-t1." + "fyers.in" + "/api/v3/validate-authcode"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        try:
            resp = requests.post(
                validate_url,
                headers=headers,
                json={"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code},
                timeout=12
            )
            if resp.status_code != 200 or not resp.text.strip():
                st.sidebar.error(f"Fyers Auth Error (HTTP {resp.status_code}): Click Step 1 again for a fresh auth_code (expires in 60s) & check Secret ID.")
            else:
                res = resp.json()
                if res.get("s") == "ok" and res.get("access_token"):
                    st.session_state["fyers_jwt_token"] = res["access_token"]
                    st.session_state["last_used_auth_code"] = auth_code
                    st.sidebar.success("✅ Daily Fyers JWT Token Generated!")
                else:
                    st.sidebar.error(f"Token Error: {res.get('message', res)}")
        except Exception as e:
            st.sidebar.error(f"Connection Error: {e}")

# Optional manual paste box if you already have the eyJ... token
manual_jwt = st.sidebar.text_input("Or Paste JWT Token Directly (eyJ...)", value="", type="password").strip()
if manual_jwt:
    st.session_state["fyers_jwt_token"] = manual_jwt

FYERS_TOKEN = f"{FYERS_APP_ID}:{st.session_state['fyers_jwt_token']}" if (FYERS_APP_ID and st.session_state["fyers_jwt_token"]) else ""

if FYERS_TOKEN:
    st.sidebar.success("🟢 Fyers Connected & Ready")
else:
    st.sidebar.warning("⚠️ Enter Secret ID & complete Step 1 + Step 2 above")

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

FNO_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "SBIN", "INFY", "ITC",
    "LT", "HINDUNILVR", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "MARUTI", "SUNPHARMA",
    "TITAN", "POWERGRID", "NTPC", "ULTRACEMCO", "TATAMOTORS", "TATASTEEL", "M&M",
    "HCLTECH", "ASIANPAINT", "BAJAJFINSV", "ADANIENT", "ADANIPORTS", "COALINDIA",
    "WIPRO", "JSWSTEEL", "HINDALCO", "GRASIM", "EICHERMOT", "BAJAJ-AUTO", "CHOLAFIN",
    "DIVISLAB", "DRREDDY", "CIPLA", "TECHM", "BRITANNIA", "BANKBARODA", "PNB",
    "CANBK", "INDUSINDBK", "BEL", "HAL", "SIEMENS", "ABB", "GAIL", "ONGC",
    "IOC", "BPCL", "HINDPETRO", "NHPC", "PFC", "RECLTD", "LICHSGFIN", "M&MFIN",
    "SHRIRAMFIN", "LTF", "MOTHERSON", "ASHOKLEY", "HEROMOTOCO", "TVSMOTOR", "BOSCHLTD",
    "CUMMINSIND", "BHARATFORG", "INDIGO", "MRF", "APOLLOTYRE", "ICICIGI", "ICICIPRULI",
    "SBILIFE", "HDFCLIFE", "HDFCAMC", "PNBHOUSING", "MUTHOOTFIN", "MANAPPURAM", "RAYMOND",
    "TRENT", "DMART", "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "IDEA",
    "INDUSTOWER", "ZEEL", "SUNTV", "IRCTC", "CONCOR", "SHREECEM", "AMBUJACEM",
    "ACC", "DALBHARAT", "TATAPOWER", "ADANIPOWER", "ADANIGREEN", "ADANIENSOL", "ATGL",
    "AUROPHARMA", "LUPIN", "IRFC", "RVNL", "INDHOTEL", "APOLLOHOSP", "MAXHEALTH",
    "TORNTPHARM", "ZYDUSLIFE", "ALKEM", "BIOCON", "DIXON", "HAVELLS", "VOLTAS",
    "CROMPTON", "POLYCAB", "BANDHANBNK", "IDFCFIRSTB", "FEDERALBNK", "AUBANK", "RBLBANK",
    "DABUR", "MARICO", "GODREJCP", "COLPAL", "NESTLEIND", "TATACONSUM", "UBL",
    "UNITDSPR", "MFSL", "COFORGE", "LTIM", "MPHASIS", "PERSISTENT", "GLAND",
    "JINDALSTEL", "SAIL", "NMDC", "VEDL", "JSWENERGY", "OFSS", "AARTIIND",
    "PIIND", "UPL", "CGPOWER", "BHEL", "GODREJIND", "ANANDRATHI"
]

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
    "APOLLOHOSP": 125, "MAXHEALTH": 525, "TORNTPHARM": 250, "ZYDUSLIFE": 900, "ALKEM": 125,
    "BIOCON": 2500, "DIXON": 50, "HAVELLS": 500, "VOLTAS": 375, "CROMPTON": 1800,
    "POLYCAB": 125, "BANDHANBNK": 3600, "IDFCFIRSTB": 7500, "FEDERALBNK": 5000, "AUBANK": 1000,
    "RBLBANK": 3175, "DABUR": 1250, "MARICO": 1200, "GODREJCP": 500, "COLPAL": 225,
    "NESTLEIND": 250, "TATACONSUM": 550, "UBL": 400, "UNITDSPR": 350, "MFSL": 400,
    "COFORGE": 75, "LTIM": 150, "MPHASIS": 275, "PERSISTENT": 100, "GLAND": 300,
    "JINDALSTEL": 625, "SAIL": 4700, "NMDC": 6750, "VEDL": 1150, "JSWENERGY": 1000,
    "OFSS": 75, "AARTIIND": 1325, "PIIND": 175, "UPL": 1355, "CGPOWER": 850,
    "BHEL": 2625, "GODREJIND": 500, "ANANDRATHI": 150
}
@st.cache_data(ttl=43200, show_spinner=False)
def get_fyers_lot_sizes():
    """Fetches current NSE F&O lot sizes directly from Fyers symbol master."""
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
    if ltp < 100: step = 1
    elif ltp < 250: step = 2.5
    elif ltp < 500: step = 5
    elif ltp < 1000: step = 10
    elif ltp < 2500: step = 20
    elif ltp < 5000: step = 50
    elif ltp < 15000: step = 100
    else: step = 250

    atm = round(ltp / step) * step
    itm = (atm + step) if is_open_high else (atm - step)
    opt_type = "PE" if is_open_high else "CE"
    fmt = lambda x: f"{int(x)}" if x == int(x) else f"{x:.1f}"
    return f"{fmt(atm)} {opt_type} | {fmt(itm)} {opt_type}"

def is_exact_ohol(open_p, high_p, low_p):
    o, h, l = round(float(open_p), 2), round(float(high_p), 2), round(float(low_p), 2)
    if o <= 0 or h == l:
        return False, False
    return (o == h), (o == l)

@st.cache_data(ttl=900, show_spinner=False)
def fetch_fyers_daily_stats(sym, auth_token):
    """Fetches 45-day daily candles from Fyers History API v3."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {
        "Authorization": auth_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    params = {
        "symbol": f"NSE:{sym}-EQ",
        "resolution": "D",
        "date_format": "1",
        "range_from": from_date,
        "range_to": to_date,
        "cont_flag": "1"
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        payload = res.json()
        candles = payload.get("candles", [])
        if payload.get("s") != "ok" or len(candles) < 5:
            return None

        df = pd.DataFrame(candles, columns=["epoch", "open", "high", "low", "close", "volume"])
        df["prev_close"] = df["close"].shift(1)
        df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)

        last_row, prev_row = df.iloc[-1], df.iloc[-2]
        last_dt = datetime.fromtimestamp(int(last_row["epoch"])).strftime("%Y-%m-%d")
        return {
            "date": last_dt,
            "open": float(last_row["open"]),
            "high": float(last_row["high"]),
            "low": float(last_row["low"]),
            "ltp": float(last_row["close"]),
            "vol": float(last_row["volume"]),
            "atr": round(float(df["tr"].tail(14).mean()), 2),
            "avg_vol": float(df["volume"].tail(20).mean()),
            "pdh": float(prev_row["high"]),
            "pdl": float(prev_row["low"]),
        }
    except Exception:
        return None

@st.cache_data(ttl=60, show_spinner=False)
def fetch_fyers_orb(sym, target_date, orb_minutes, auth_token):
    """Fetches real-time 5-minute intraday candles from Fyers History API v3 for 5m/15m ORB."""
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {
        "Authorization": auth_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    start_epoch = int(dt_obj.timestamp()) - 86400
    end_epoch = int(dt_obj.timestamp()) + 86400

    params = {
        "symbol": f"NSE:{sym}-EQ",
        "resolution": "5",
        "date_format": "0",
        "range_from": str(start_epoch),
        "range_to": str(end_epoch),
        "cont_flag": "1"
    }
    candles_needed = 1 if orb_minutes == 5 else 3
    try:
        res = requests.get(url, headers=headers, params=params, timeout=8)
        payload = res.json()
        candles = payload.get("candles", [])
        if payload.get("s") == "ok" and len(candles) >= candles_needed:
            df = pd.DataFrame(candles, columns=["epoch", "open", "high", "low", "close", "volume"])
            df["date_str"] = pd.to_datetime(df["epoch"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
            latest_day = df["date_str"].iloc[-1]
            day_df = df[df["date_str"] == latest_day]

            if len(day_df) >= candles_needed:
                orb_slice = day_df.head(candles_needed)
                return {
                    "orb_high": float(orb_slice["high"].max()),
                    "orb_low": float(orb_slice["low"].min()),
                    "latest_close": float(day_df["close"].iloc[-1]),
                }
    except Exception:
        pass
    return None

def fetch_fyers_live_quotes(symbols, auth_token):
    """Fetches real-time batch quotes from Fyers Data API v3."""
    url = "https://" + "api-t1." + "fyers.in" + "/data/quotes"
    headers = {
        "Authorization": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    quotes_by_sym = {}
    last_err = None

    for i in range(0, len(symbols), 50):
        batch = symbols[i:i + 50]
        fyers_syms = ",".join(f"NSE:{s}-EQ" for s in batch)
        try:
            res = requests.get(url, headers=headers, params={"symbols": fyers_syms}, timeout=12)
            if res.status_code in (401, 403):
                return None, f"Token expired or invalid (HTTP {res.status_code})"
            if res.status_code != 200 or not res.text.strip():
                last_err = f"HTTP {res.status_code} (empty body)"
                continue
            payload = res.json()
            if payload.get("s") != "ok":
                last_err = payload.get("message", "Fyers API error")
                continue

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
            last_err = str(e)
        time.sleep(0.15)

    if not quotes_by_sym:
        return None, last_err or "No open prices returned"
    return quotes_by_sym, None

def run_pure_fyers_scanner():
    symbols = sorted(set(FNO_SYMBOLS))
    total_fno = len(symbols)
    if not FYERS_TOKEN:
        return pd.DataFrame(), "Paste your Fyers AppID & JWT Access Token in the sidebar", total_fno

    token_part = FYERS_TOKEN.split(":", 1)[-1]
    if len(token_part) < 50:
        return pd.DataFrame(), "Invalid token length — paste full Fyers JWT Access Token (eyJ...)", total_fno

    lot_map = get_fyers_lot_sizes()
    orb_mins = 5 if "5-Min" in orb_timeframe else 15
    today_str = datetime.now().strftime("%Y-%m-%d")

    live_quotes, quote_note = fetch_fyers_live_quotes(symbols, FYERS_TOKEN)
    if quote_note and "401" in quote_note:
        st.error("🔒 Fyers Token Expired or Invalid (HTTP 401). Generate a fresh daily Fyers JWT token.")
        return pd.DataFrame(), quote_note, total_fno

    matched_items = []
    target_session_date = today_str

    # 1. Live Market Path (Fyers Live Quotes + Fyers History for matched OHOL stocks)
    if live_quotes:
        source_note = "Fyers API v3 Live Feed (100% Fyers Data)"
        ohol_live = []
        for sym, q in live_quotes.items():
            is_oh, is_ol = is_exact_ohol(q["open"], q["high"], q["low"])
            if is_oh or is_ol:
                ohol_live.append((sym, q["open"], q["ltp"], q["vol"], is_oh))

        def enrich_live(item):
            time.sleep(0.2)
            sym, open_p, ltp, vol, is_oh = item
            stats = fetch_fyers_daily_stats(sym, FYERS_TOKEN)
            if not stats:
                return None
            orb = fetch_fyers_orb(sym, today_str, orb_mins, FYERS_TOKEN)
            return (sym, open_p, ltp, vol, is_oh, stats, orb)

        with ThreadPoolExecutor(max_workers=4) as ex:
            matched_items = [r for r in ex.map(enrich_live, ohol_live) if r is not None]

    # 2. Holiday / Closed Market Path (100% Fyers Daily & 5m Historical Candles)
    else:
        def scan_fyers_history(sym):
            time.sleep(0.08)
            stats = fetch_fyers_daily_stats(sym, FYERS_TOKEN)
            if not stats:
                return None
            is_oh, is_ol = is_exact_ohol(stats["open"], stats["high"], stats["low"])
            if not (is_oh or is_ol):
                return None
            orb = fetch_fyers_orb(sym, stats["date"], orb_mins, FYERS_TOKEN)
            return (sym, stats["open"], stats["ltp"], stats["vol"], is_oh, stats, orb)

        with ThreadPoolExecutor(max_workers=4) as ex:
            matched_items = [r for r in ex.map(scan_fyers_history, symbols) if r is not None]

        if matched_items:
            target_session_date = matched_items[0][5]["date"]
        source_note = f"Fyers History API v3 — Last Session ({target_session_date} | {quote_note})"

    rows = []
    for sym, open_p, ltp, curr_vol, is_oh, stats, orb in matched_items:
        if "Open=Low Only" in pattern_filter and is_oh:
            continue
        if "Open=High Only" in pattern_filter and not is_oh:
            continue

        # ORB Evaluation
        orb_ok = False
        if orb:
            chk_p = ltp if ltp > 0 else orb["latest_close"]
            if is_oh:
                lvl = orb["orb_low"]
                orb_ok = chk_p < lvl
                orb_text = f"✅ {orb_mins}m Broken (<{lvl:.1f})" if orb_ok else f"⏳ Inside (>{lvl:.1f})"
            else:
                lvl = orb["orb_high"]
                orb_ok = chk_p > lvl
                orb_text = f"✅ {orb_mins}m Breakout (>{lvl:.1f})" if orb_ok else f"⏳ Inside (<{lvl:.1f})"
        else:
            orb_text = "⏳ Pending ORB"

        if only_orb_confirmed and not orb_ok:
            continue

        risk_unit = stats["atr"] * 0.5
        vol_ratio = round(curr_vol / stats["avg_vol"], 2) if stats["avg_vol"] > 0 else 0
        power, p_rank = ("🔥 Ultra", 3) if vol_ratio >= 4.0 else (("⚡ Strong", 2) if vol_ratio >= 2.0 else ("Normal", 1))
        lvl_tag = "Above PDH 🟢" if ltp > stats["pdh"] else ("Below PDL 🔴" if ltp < stats["pdl"] else "Inside Prev Day")

        if is_oh:
            pat = f"Open=High ({open_p:.2f})"
            status = "Active" if ltp <= open_p else "Reversed"
            t1, t2 = round(open_p - risk_unit, 1), round(open_p - risk_unit * 2, 1)
            rev_tgt = str(round(open_p + risk_unit, 1)) if status == "Reversed" else "N/A"
        else:
            pat = f"Open=Low ({open_p:.2f})"
            status = "Active" if ltp >= open_p else "Reversed"
            t1, t2 = round(open_p + risk_unit, 1), round(open_p + risk_unit * 2, 1)
            rev_tgt = str(round(open_p - risk_unit, 1)) if status == "Reversed" else "N/A"

        rows.append({
            "Symbol": f"NSE:{sym}",
            "Pattern": pat,
            "ORB Confirm": orb_text,
            "Status": status,
            "Price (₹)": f"{ltp:.2f}",
            "ATM | 1-ITM Option": get_option_strikes(ltp, is_oh),
            "Lot Size": lot_map.get(sym) or DEFAULT_LOT_SIZES.get(sym, 0),
            "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
            "Rev Target": rev_tgt,
            "PDH/PDL": lvl_tag,
            "Volume": f"{vol_ratio}x",
            "Power": power,
            "_orb_ok": orb_ok,
            "_vol_ratio": vol_ratio,
            "_power_rank": p_rank
        })

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_orb_ok", "_power_rank", "_vol_ratio"], ascending=[False, False, False])
        df_out = df_out.drop(columns=["_orb_ok", "_vol_ratio", "_power_rank"])

    return df_out, source_note, total_fno

def style_scanner_table(df):
    return (
        df.style
        .map(lambda v: "color: #ff5252; font-weight: bold;" if "Open=High" in str(v) else "color: #4caf50; font-weight: bold;", subset=["Pattern"])
        .map(lambda v: "color: #00e676; font-weight: bold;" if "✅" in str(v) else "color: #ffb74d;", subset=["ORB Confirm"])
        .map(lambda v: "color: #4caf50; font-weight: bold;" if v == "Active" else "color: #ff9800; font-weight: bold;", subset=["Status"])
        .map(lambda _: "color: #ffd54f; font-weight: bold;", subset=["ATM | 1-ITM Option"])
        .map(lambda _: "color: #00bcd4; font-weight: bold;", subset=["Normal Tgt (1:1|1:2)"])
        .map(lambda v: "background-color: #9c27b0; color: white; font-weight: bold;" if "Ultra" in str(v) else ("background-color: #2196f3; color: white; font-weight: bold;" if "Strong" in str(v) else ""), subset=["Power"])
    )

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_fyers_5m_range(sym, days_back, auth_token):
    """Fetches up to 60 days of 5-minute intraday candles from Fyers API v3."""
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {
        "Authorization": auth_token,
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days_back)
    params = {
        "symbol": f"NSE:{sym}-EQ",
        "resolution": "5",
        "date_format": "0",
        "range_from": str(int(from_dt.timestamp())),
        "range_to": str(int(to_dt.timestamp())),
        "cont_flag": "1"
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=12)
        payload = res.json()
        candles = payload.get("candles", [])
        if payload.get("s") == "ok" and len(candles) > 50:
            df = pd.DataFrame(candles, columns=["epoch", "open", "high", "low", "close", "volume"])
            df["dt"] = pd.to_datetime(df["epoch"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
            df["date"] = df["dt"].dt.strftime("%Y-%m-%d")
            return df
    except Exception:
        pass
    return None

def run_ohol_backtest(symbols_list, days_back, orb_minutes, target_rr, auth_token):
    """Simulates Open=High/Low + ORB intraday trades across historical 5m candles."""
    trades = []
    candles_for_orb = 1 if orb_minutes == 5 else 3
    progress_bar = st.progress(0, text="Running Fyers historical backtest...")

    for idx, sym in enumerate(symbols_list):
        progress_bar.progress((idx + 1) / len(symbols_list), text=f"Backtesting {sym} ({idx+1}/{len(symbols_list)})...")
        time.sleep(0.12)  # Stay safely within Fyers API rate limits
        df = fetch_fyers_5m_range(sym, days_back, auth_token)
        if df is None or df.empty:
            continue

        # Build daily ATR-14 from grouped 5m bars
        daily = df.groupby("date").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
        daily["prev_close"] = daily["close"].shift(1)
        daily["tr"] = daily[["high", "prev_close"]].max(axis=1) - daily[["low", "prev_close"]].min(axis=1)
        daily["atr14"] = daily["tr"].rolling(14).mean().shift(1)  # Prior day's ATR-14 (no lookahead bias)
        atr_lookup = dict(zip(daily["date"], daily["atr14"]))

        for dt_str, day_df in df.groupby("date"):
            atr = atr_lookup.get(dt_str)
            if pd.isna(atr) or len(day_df) <= candles_for_orb + 2:
                continue

            day_df = day_df.reset_index(drop=True)
            first_bar = day_df.iloc[0]
            open_p = round(float(first_bar["open"]), 2)
            first_h = round(float(first_bar["high"]), 2)
            first_l = round(float(first_bar["low"]), 2)

            # Check exact Open=High or Open=Low on opening bar
            is_oh = (open_p == first_h) and (first_h != first_l)
            is_ol = (open_p == first_l) and (first_h != first_l)
            if not (is_oh or is_ol):
                continue

            orb_slice = day_df.iloc[:candles_for_orb]
            orb_high = float(orb_slice["high"].max())
            orb_low = float(orb_slice["low"].min())
            risk_unit = (atr * 0.5) * target_rr

            entry_price = None
            entry_time = None
            outcome = None
            exit_price = None

            # Replay remaining intraday candles up to 3:15 PM (bar index 71)
            trade_bars = day_df.iloc[candles_for_orb:72]
            for _, bar in trade_bars.iterrows():
                b_high = float(bar["high"])
                b_low = float(bar["low"])
                b_close = float(bar["close"])
                b_time = bar["dt"].strftime("%H:%M")

                if is_oh:
                    if entry_price is None:
                        if b_high > open_p:
                            break  # Invalidated before ORB trigger
                        if b_low < orb_low:
                            entry_price = round(orb_low, 2)
                            entry_time = b_time
                            sl_price = round(open_p * 1.0005, 2)
                            tgt_price = round(entry_price - risk_unit, 2)
                    else:
                        if b_high >= sl_price:
                            outcome, exit_price = "SL Hit ❌", sl_price
                            break
                        if b_low <= tgt_price:
                            outcome, exit_price = "Target Hit ✅", tgt_price
                            break
                else:
                    if entry_price is None:
                        if b_low < open_p:
                            break  # Invalidated before ORB trigger
                        if b_high > orb_high:
                            entry_price = round(orb_high, 2)
                            entry_time = b_time
                            sl_price = round(open_p * 0.9995, 2)
                            tgt_price = round(entry_price + risk_unit, 2)
                    else:
                        if b_low <= sl_price:
                            outcome, exit_price = "SL Hit ❌", sl_price
                            break
                        if b_high >= tgt_price:
                            outcome, exit_price = "Target Hit ✅", tgt_price
                            break

            if entry_price is not None:
                if outcome is None:
                    outcome = "3:15 PM Exit ⏱️"
                    exit_price = round(float(trade_bars.iloc[-1]["close"]), 2)

                pnl_pct = ((entry_price - exit_price) / entry_price * 100) if is_oh else ((exit_price - entry_price) / entry_price * 100)
                trades.append({
                    "Date": dt_str,
                    "Symbol": f"NSE:{sym}",
                    "Setup": "Open=High (Short)" if is_oh else "Open=Low (Long)",
                    "Entry Time": entry_time,
                    "Entry (₹)": entry_price,
                    "Exit (₹)": exit_price,
                    "Result": outcome,
                    "Return (%)": round(pnl_pct, 2)
                })

    progress_bar.empty()
    return pd.DataFrame(trades)

# --- Main App UI ---
st.subheader("📊 Fyers Pure NSE F&O Exact Open=High / Open=Low + ORB Scanner")

tab_live, tab_bt = st.tabs(("📡 Live Intraday Scanner", "📈 Strategy Backtester"))

with tab_live:
    col_btn, col_info = st.columns((1, 5))
    with col_btn:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()

    with st.spinner("Fetching 100% Fyers API v3 data..."):
        df_results, source_note, total_fno = run_pure_fyers_scanner()

    with col_info:
        st.caption(f"Scanned **{total_fno} F&O Stocks** | Mode: **{source_note}**")

    if not df_results.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Exact Matches", len(df_results))
        m2.metric("🟢 Open=Low (Bullish)", int(df_results["Pattern"].str.contains("Open=Low").sum()))
        m3.metric("🔴 Open=High (Bearish)", int(df_results["Pattern"].str.contains("Open=High").sum()))
        m4.metric("✅ ORB Confirmed", int(df_results["ORB Confirm"].str.contains("✅").sum()))
        st.dataframe(style_scanner_table(df_results), use_container_width=True, hide_index=True, height=560)
    elif FYERS_TOKEN:
        st.info("No F&O stocks matched your current filters right now.")

with tab_bt:
    st.markdown("Test how **Exact Open=High / Open=Low + ORB** performed over past trading days using **Fyers 5-Min Historical Data**.")
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        bt_universe = st.selectbox("Stock Universe", ("Top 30 Liquid F&O (Fast ~6s)", "All 148 F&O Stocks (~25s)"))
    with b2:
        bt_days = st.selectbox("Lookback Period", (15, 30, 60), index=1, format_func=lambda d: f"Last {d} Calendar Days")
    with b3:
        bt_orb = st.selectbox("ORB Confirmation", (5, 15), format_func=lambda m: f"{m}-Min ORB")
    with b4:
        bt_rr = st.selectbox("Target Multiple", (1.0, 1.5, 2.0), format_func=lambda r: f"1:{r} ATR Target")

    if st.button("▶️ Run Fyers Backtest", type="primary"):
        if not FYERS_TOKEN:
            st.warning("⚠️ Please log in to Fyers in the left sidebar first.")
        else:
            test_syms = sorted(set(FNO_SYMBOLS))[:30] if "Top 30" in bt_universe else sorted(set(FNO_SYMBOLS))
            df_bt = run_ohol_backtest(test_syms, bt_days, bt_orb, bt_rr, FYERS_TOKEN)

            if df_bt.empty:
                st.info("No triggered trades found in this period.")
            else:
                df_bt = df_bt.sort_values(by=["Date", "Entry Time"], ascending=[False, True])
                wins = (df_bt["Return (%)"] > 0).sum()
                total_t = len(df_bt)
                win_rate = round((wins / total_t) * 100, 1)
                avg_ret = round(df_bt["Return (%)"].mean(), 2)
                net_ret = round(df_bt["Return (%)"].sum(), 2)

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Total Triggered Trades", total_t)
                k2.metric("Win Rate (%)", f"{win_rate}%")
                k3.metric("Avg Return / Trade", f"{avg_ret}%")
                k4.metric("Cumulative Return (Unleveraged)", f"{net_ret}%")

                st.dataframe(df_bt, use_container_width=True, hide_index=True, height=500)

if auto_refresh and FYERS_TOKEN:
    time.sleep(60)
    st.rerun()
