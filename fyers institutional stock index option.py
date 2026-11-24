import os
import time
import hashlib
import requests
import pandas as pd
import streamlit as st
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Fyers NSE/BSE Indices & F&O Triple-Aligned OHOL Scanner", layout="wide")

# --- Sidebar: Built-in Fyers v3 Login & Scanner Filters ---
st.sidebar.header("🔑 Fyers API v3 Login")

default_fyers_id = st.secrets.get("FYERS_APP_ID", os.getenv("FYERS_APP_ID", "D2B1MP5NVR-100")).strip()
default_secret = st.secrets.get("FYERS_SECRET_ID", os.getenv("FYERS_SECRET_ID", "")).strip()
redirect_uri = "https://127.0.0.1"

FYERS_APP_ID = st.sidebar.text_input("Fyers App ID", value=default_fyers_id).strip()
FYERS_SECRET_ID = st.sidebar.text_input(
    "Fyers Secret ID",
    value=default_secret,
    type="password",
    placeholder="Paste Secret ID from Fyers dashboard"
).strip()

if "fyers_jwt_token" not in st.session_state:
    st.session_state["fyers_jwt_token"] = st.secrets.get("FYERS_ACCESS_TOKEN", os.getenv("FYERS_ACCESS_TOKEN", "")).strip()

if FYERS_APP_ID:
    fyers_host = "https://" + "api-t1." + "fyers.in" + "/api/v3/generate-authcode"
    login_url = (
        f"{fyers_host}"
        f"?client_id={quote(FYERS_APP_ID)}"
        f"&redirect_uri={quote(redirect_uri, safe='')}"
        f"&response_type=code&state=scanner"
    )
    st.sidebar.markdown(f"**Step 1:** [👉 Click Here to Login to Fyers]({login_url})")

redirected_input = st.sidebar.text_input(
    "Step 2: Paste Redirected URL (or auth_code)",
    value="",
    placeholder="Paste full https://127.0.0?... URL here"
).strip()

if redirected_input and FYERS_APP_ID and FYERS_SECRET_ID:
    auth_code = redirected_input
    if "auth_code=" in redirected_input:
        parsed = parse_qs(urlparse(redirected_input).query)
        code_list = parsed.get("auth_code")
        auth_code = code_list.pop(0) if code_list else ""

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
                st.sidebar.error(f"Fyers Auth Error (HTTP {resp.status_code}): Click Step 1 again for a fresh auth_code & check Secret ID.")
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

manual_jwt = st.sidebar.text_input("Or Paste JWT Token Directly (eyJ...)", value="", type="password").strip()
if manual_jwt:
    st.session_state["fyers_jwt_token"] = manual_jwt

FYERS_TOKEN = f"{FYERS_APP_ID}:{st.session_state['fyers_jwt_token']}" if (FYERS_APP_ID and st.session_state["fyers_jwt_token"]) else ""

if FYERS_TOKEN:
    st.sidebar.success("🟢 Fyers Connected & Ready")
else:
    st.sidebar.warning("⚠️ Enter Secret ID & complete Step 1 + Step 2 above")

st.sidebar.divider()
st.sidebar.header("⚙️ Scanner & ORB Filters")
pattern_filter = st.sidebar.selectbox(
    "Show Exact Patterns",
    ("All (Open=High & Open=Low)", "Open=High Only (Bearish)", "Open=Low Only (Bullish)")
)
orb_timeframe = st.sidebar.radio(
    "ORB Confirmation Window",
    ("15-Min ORB (9:15–9:30 AM)", "5-Min ORB (9:15–9:20 AM)")
)
only_orb_confirmed = st.sidebar.checkbox("✅ Show Only ORB Confirmed Setups", value=False)
only_option_aligned = st.sidebar.checkbox("🔥 Show Only Option O=L/O=H Aligned", value=False)
auto_refresh = st.sidebar.checkbox("🔄 Auto-Refresh Every 60s", value=False)

INDEX_CONFIG = {
    "NIFTY 50": {"fyers": "NSE:NIFTY50-INDEX", "step": 50, "lot": 75, "csv_sym": "NIFTY"},
    "BANK NIFTY": {"fyers": "NSE:NIFTYBANK-INDEX", "step": 100, "lot": 30, "csv_sym": "BANKNIFTY"},
    "FIN NIFTY": {"fyers": "NSE:FINNIFTY-INDEX", "step": 50, "lot": 65, "csv_sym": "FINNIFTY"},
    "MIDCAP NIFTY": {"fyers": "NSE:MIDCPNIFTY-INDEX", "step": 25, "lot": 120, "csv_sym": "MIDCPNIFTY"},
    "SENSEX": {"fyers": "BSE:SENSEX-INDEX", "step": 100, "lot": 20, "csv_sym": "SENSEX"},
    "BANKEX": {"fyers": "BSE:BANKEX-INDEX", "step": 100, "lot": 30, "csv_sym": "BANKEX"},
}

FNO_SYMBOLS = (
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
)

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
@st.cache_data(ttl=21600, show_spinner=False)
def get_fyers_masters():
    """Fetches stock lot sizes, index lot sizes, and nearest-expiry option contracts from Fyers CSV masters."""
    stock_lots = dict(DEFAULT_LOT_SIZES)
    idx_lots = {k: v["lot"] for k, v in INDEX_CONFIG.items()}
    csv_to_idx = {v["csv_sym"]: k for k, v in INDEX_CONFIG.items()}
    opt_raw = {}
    now_epoch = int(time.time()) - 3600

    for csv_url in ("https://fyers.in", "https://fyers.in"):
        try:
            res = requests.get(csv_url, timeout=15)
            if res.status_code != 200:
                continue
            for line in res.text.splitlines():
                cols = line.split(",")
                if len(cols) < 17:
                    continue
                inst_type = cols.__getitem__(2).strip()
                if inst_type not in ("OPTSTK", "OPTIDX"):
                    continue
                lot_val = int(float(cols.__getitem__(3).strip()))
                expiry_ts = int(float(cols.__getitem__(8).strip()))
                fyers_sym = cols.__getitem__(9).strip()
                u_sym = cols.__getitem__(13).strip()
                strike = round(float(cols.__getitem__(15).strip()), 2)
                opt_type = cols.__getitem__(16).strip()

                if inst_type == "OPTSTK" and u_sym in stock_lots and lot_val > 0:
                    stock_lots[u_sym] = lot_val
                elif inst_type == "OPTIDX" and u_sym in csv_to_idx and lot_val > 0:
                    idx_lots[csv_to_idx[u_sym]] = lot_val

                if expiry_ts >= now_epoch and opt_type in ("CE", "PE"):
                    opt_raw.setdefault(u_sym, []).append((expiry_ts, strike, opt_type, fyers_sym))
        except Exception:
            continue

    nearest_opts = {}
    for u_sym, contracts in opt_raw.items():
        min_exp = min(c.__getitem__(0) for c in contracts)
        nearest_opts[u_sym] = {(c.__getitem__(1), c.__getitem__(2)): c.__getitem__(3) for c in contracts if c.__getitem__(0) == min_exp}

    return stock_lots, idx_lots, nearest_opts

def get_stock_strike_step(ltp):
    if ltp < 100: return 1
    elif ltp < 250: return 2.5
    elif ltp < 500: return 5
    elif ltp < 1000: return 10
    elif ltp < 2500: return 20
    elif ltp < 5000: return 50
    elif ltp < 15000: return 100
    return 250

def get_option_strikes(ltp, is_open_high):
    step = get_stock_strike_step(ltp)
    atm = round(ltp / step) * step
    itm = (atm + step) if is_open_high else (atm - step)
    opt_type = "PE" if is_open_high else "CE"
    fmt = lambda x: f"{int(x)}" if x == int(x) else f"{x:.1f}"
    return f"{fmt(atm)} {opt_type} | {fmt(itm)} {opt_type}", round(float(atm), 2)

def get_index_option_strikes(idx_name, ltp, is_open_high):
    step = INDEX_CONFIG[idx_name]["step"]
    atm = round(ltp / step) * step
    itm = (atm + step) if is_open_high else (atm - step)
    opt_type = "PE" if is_open_high else "CE"
    return f"{int(atm)} {opt_type} | {int(itm)} {opt_type}", round(float(atm), 2)

def is_exact_ohol(open_p, high_p, low_p):
    o, h, l = round(float(open_p), 2), round(float(high_p), 2), round(float(low_p), 2)
    if o <= 0 or h == l:
        return False, False
    return (o == h), (o == l)

def check_option_alignment(matched_records, auth_token, nearest_opts):
    """
    Scans ATM -5 to ATM +5 strikes (11 strikes x CE/PE) for matched stocks and indices.
    Returns dict: key_id -> {'badge': str, 'rank': int}
    """
    if not matched_records or not auth_token:
        return {}

    sym_strike_map = {}
    all_opt_syms = []

    for rec in matched_records:
        key_id = rec["key_id"]
        csv_sym = rec["csv_sym"]
        atm = round(float(rec["atm_strike"]), 2)
        step = INDEX_CONFIG[key_id]["step"] if key_id in INDEX_CONFIG else get_stock_strike_step(atm)
        contracts = nearest_opts.get(csv_sym, {})

        strike_pairs = []
        for offset in range(-5, 6):
            st_val = round(atm + (offset * step), 2)
            ce_sym = contracts.get((st_val, "CE"))
            pe_sym = contracts.get((st_val, "PE"))
            if ce_sym or pe_sym:
                strike_pairs.append((offset, st_val, ce_sym, pe_sym))
                if ce_sym:
                    all_opt_syms.append(ce_sym)
                if pe_sym:
                    all_opt_syms.append(pe_sym)

        if strike_pairs:
            sym_strike_map[key_id] = (strike_pairs, rec["is_oh"])

    if not all_opt_syms:
        return {}

    headers = {
        "Authorization": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    opt_quotes = {}
    unique_syms = sorted(set(all_opt_syms))

    for i in range(0, len(unique_syms), 50):
        batch = unique_syms[i:i + 50]
        try:
            res = requests.get(
                "https://" + "api-t1." + "fyers.in" + "/data/quotes",
                headers=headers,
                params={"symbols": ",".join(batch)},
                timeout=10
            )
            payload = res.json()
            if payload.get("s") == "ok":
                for item in payload.get("d", ()):
                    v = item.get("v", {})
                    if float(v.get("open_price", 0)) > 0:
                        opt_quotes[item.get("n", "")] = (
                            float(v.get("open_price", 0)),
                            float(v.get("high_price", 0)),
                            float(v.get("low_price", 0))
                        )
        except Exception:
            continue

    fmt_st = lambda x: f"{int(x)}" if x == int(x) else f"{x:.1f}"
    results = {}

    for key_id, (strike_pairs, is_oh) in sym_strike_map.items():
        # Sort by closest strike to ATM first (offset 0, then +/-1, +/-2...)
        strike_pairs.sort(key=lambda x: abs(x.__getitem__(0)))

        triple_strikes = []
        primary_ol_strikes = []
        opposite_oh_strikes = []

        for offset, st_val, ce_sym, pe_sym in strike_pairs:
            ce_ohl = opt_quotes.get(ce_sym)
            pe_ohl = opt_quotes.get(pe_sym)
            ce_oh, ce_ol = is_exact_ohol(ce_ohl.__getitem__(0), ce_ohl.__getitem__(1), ce_ohl.__getitem__(2)) if ce_ohl else (False, False)
            pe_oh, pe_ol = is_exact_ohol(pe_ohl.__getitem__(0), pe_ohl.__getitem__(1), pe_ohl.__getitem__(2)) if pe_ohl else (False, False)

            if not is_oh:
                # Bullish Spot (Open=Low): want CE Open=Low and PE Open=High
                if ce_ol and pe_oh:
                    triple_strikes.append(fmt_st(st_val))
                if ce_ol:
                    primary_ol_strikes.append(f"{fmt_st(st_val)} CE")
                if pe_oh:
                    opposite_oh_strikes.append(f"{fmt_st(st_val)} PE")
            else:
                # Bearish Spot (Open=High): want PE Open=Low and CE Open=High
                if pe_ol and ce_oh:
                    triple_strikes.append(fmt_st(st_val))
                if pe_ol:
                    primary_ol_strikes.append(f"{fmt_st(st_val)} PE")
                if ce_oh:
                    opposite_oh_strikes.append(f"{fmt_st(st_val)} CE")

        if triple_strikes:
            results[key_id] = {"badge": f"🔥 TRIPLE @ {triple_strikes.__getitem__(0)}", "rank": 3}
        elif primary_ol_strikes and opposite_oh_strikes:
            results[key_id] = {"badge": f"🔥 SPLIT ({primary_ol_strikes.__getitem__(0)} O=L | {opposite_oh_strikes.__getitem__(0)} O=H)", "rank": 3}
        elif primary_ol_strikes:
            results[key_id] = {"badge": f"⚡ {primary_ol_strikes.__getitem__(0)} Open=Low", "rank": 2}
        elif opposite_oh_strikes:
            results[key_id] = {"badge": f"⚡ {opposite_oh_strikes.__getitem__(0)} Open=High", "rank": 2}
        else:
            results[key_id] = {"badge": "Spot Only", "rank": 1}

    return results

@st.cache_data(ttl=900, show_spinner=False)
def fetch_fyers_daily_stats(fyers_symbol, auth_token):
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    params = {"symbol": fyers_symbol, "resolution": "D", "date_format": "1", "range_from": from_date, "range_to": to_date, "cont_flag": "1"}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        payload = res.json()
        candles = payload.get("candles", ())
        if payload.get("s") != "ok" or len(candles) < 5:
            return None

        df = pd.DataFrame(candles, columns=("epoch", "open", "high", "low", "close", "volume"))
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
def fetch_fyers_orb(fyers_symbol, target_date, orb_minutes, auth_token):
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    params = {
        "symbol": fyers_symbol,
        "resolution": "5",
        "date_format": "0",
        "range_from": str(int(dt_obj.timestamp()) - 86400),
        "range_to": str(int(dt_obj.timestamp()) + 86400),
        "cont_flag": "1"
    }
    candles_needed = 1 if orb_minutes == 5 else 3
    try:
        res = requests.get(url, headers=headers, params=params, timeout=8)
        payload = res.json()
        candles = payload.get("candles", ())
        if payload.get("s") == "ok" and len(candles) >= candles_needed:
            df = pd.DataFrame(candles, columns=("epoch", "open", "high", "low", "close", "volume"))
            df["date_str"] = pd.to_datetime(df["epoch"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
            day_df = df[df["date_str"] == df["date_str"].iloc[-1]]
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
    url = "https://" + "api-t1." + "fyers.in" + "/data/quotes"
    headers = {"Authorization": auth_token, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
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
                last_err = f"HTTP {res.status_code}"
                continue
            payload = res.json()
            if payload.get("s") != "ok":
                last_err = payload.get("message", "Fyers API error")
                continue

            for item in payload.get("d", ()):
                v = item.get("v", {})
                clean_sym = item.get("n", "").replace("NSE:", "").replace("-EQ", "")
                if clean_sym and v.get("open_price", 0) > 0:
                    quotes_by_sym[clean_sym] = {
                        "open": float(v.get("open_price", 0)),
                        "high": float(v.get("high_price", 0)),
                        "low": float(v.get("low_price", 0)),
                        "ltp": float(v.get("lp", 0)),
                        "vol": float(v.get("volume", 0)),
                        "atp": float(v.get("atp", 0)),
                    }
        except Exception as e:
            last_err = str(e)
        time.sleep(0.15)

    if not quotes_by_sym:
        return None, last_err or "Market closed / open=0"
    return quotes_by_sym, None

def scan_live_indices(auth_token, orb_mins, idx_lots, nearest_opts):
    if not auth_token or len(auth_token.split(":", 1).pop()) < 50:
        return pd.DataFrame(), {}

    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    fyers_syms = ",".join(v["fyers"] for v in INDEX_CONFIG.values())
    fyers_to_name = {v["fyers"]: k for k, v in INDEX_CONFIG.items()}
    today_str = datetime.now().strftime("%Y-%m-%d")

    live_summary = {}
    matched_idx = []

    try:
        res = requests.get("https://" + "api-t1." + "fyers.in" + "/data/quotes", headers=headers, params={"symbols": fyers_syms}, timeout=10)
        payload = res.json()
        if payload.get("s") != "ok":
            return pd.DataFrame(), {}

        for item in payload.get("d", ()):
            f_sym = item.get("n", "")
            idx_name = fyers_to_name.get(f_sym)
            v = item.get("v", {})
            open_p, high_p, low_p, ltp, chp = float(v.get("open_price", 0)), float(v.get("high_price", 0)), float(v.get("low_price", 0)), float(v.get("lp", 0)), float(v.get("chp", 0))
            if not idx_name or open_p <= 0:
                continue

            live_summary[idx_name] = {"open": open_p, "high": high_p, "low": low_p, "ltp": ltp, "chp": chp}
            is_oh, is_ol = is_exact_ohol(open_p, high_p, low_p)
            if not (is_oh or is_ol):
                continue
            if "Open=Low Only" in pattern_filter and is_oh:
                continue
            if "Open=High Only" in pattern_filter and is_ol:
                continue

            opt_str, atm_strike = get_index_option_strikes(idx_name, ltp, is_oh)
            matched_idx.append({
                "key_id": idx_name,
                "csv_sym": INDEX_CONFIG[idx_name]["csv_sym"],
                "fyers_sym": f_sym,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "ltp": ltp,
                "is_oh": is_oh,
                "opt_str": opt_str,
                "atm_strike": atm_strike
            })
    except Exception:
        return pd.DataFrame(), {}

    if not matched_idx:
        return pd.DataFrame(), live_summary

    opt_align_map = check_option_alignment(matched_idx, auth_token, nearest_opts)
    bhav_map = st.session_state.get("bhav_footprints", {})
    rows = []

    for m in matched_idx:
        idx_name = m["key_id"]
        stats = fetch_fyers_daily_stats(m["fyers_sym"], auth_token)
        if not stats:
            continue
        orb = fetch_fyers_orb(m["fyers_sym"], today_str, orb_mins, auth_token)

        orb_ok = False
        if orb:
            if m["is_oh"]:
                lvl = orb["orb_low"]
                orb_ok = m["ltp"] < lvl
                orb_text = f"✅ {orb_mins}m Broken (<{lvl:.1f})" if orb_ok else f"⏳ Inside (>{lvl:.1f})"
            else:
                lvl = orb["orb_high"]
                orb_ok = m["ltp"] > lvl
                orb_text = f"✅ {orb_mins}m Breakout (>{lvl:.1f})" if orb_ok else f"⏳ Inside (<{lvl:.1f})"
        else:
            orb_text = "⏳ Pending ORB"

        align_info = opt_align_map.get(idx_name, {"badge": "Spot Only", "rank": 1})
        bhav_info = bhav_map.get(m["csv_sym"], {})
        bhav_badge = bhav_info.get("badge", "—")
        bhav_rank = 2 if bhav_info.get("is_high_prob") else (1 if bhav_badge != "—" else 0)

        if only_orb_confirmed and not orb_ok:
            continue
        if only_option_aligned and align_info["rank"] < 2:
            continue

        risk_unit = stats["atr"] * 0.5
        lvl_tag = "Above PDH 🟢" if m["ltp"] > stats["pdh"] else ("Below PDL 🔴" if m["ltp"] < stats["pdl"] else "Inside Prev Day")
        if m["is_oh"]:
            pat = f"Open=High ({m['open']:.2f})"
            status = "Active" if m["ltp"] <= m["open"] else "Reversed"
            t1, t2 = round(m["open"] - risk_unit, 1), round(m["open"] - risk_unit * 2, 1)
            rev_tgt = str(round(m["open"] + risk_unit, 1)) if status == "Reversed" else "N/A"
        else:
            pat = f"Open=Low ({m['open']:.2f})"
            status = "Active" if m["ltp"] >= m["open"] else "Reversed"
            t1, t2 = round(m["open"] + risk_unit, 1), round(m["open"] + risk_unit * 2, 1)
            rev_tgt = str(round(m["open"] - risk_unit, 1)) if status == "Reversed" else "N/A"

        rows.append({
            "Index": idx_name,
            "Pattern": pat,
            "Option O=L/O=H Align": align_info["badge"],
            "🏦 Bhavcopy Signal": bhav_badge,
            "ORB Confirm": orb_text,
            "Status": status,
            "Price": f"{m['ltp']:.2f}",
            "ATM | 1-ITM Option": m["opt_str"],
            "Lot Size": idx_lots.get(idx_name, INDEX_CONFIG[idx_name]["lot"]),
            "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
            "Rev Target": rev_tgt,
            "PDH/PDL": lvl_tag,
            "_bhav_rank": bhav_rank,
            "_align_rank": align_info["rank"],
            "_orb_ok": orb_ok
        })

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_bhav_rank", "_align_rank", "_orb_ok"], ascending=[False, False, False]).drop(columns=["_bhav_rank", "_align_rank", "_orb_ok"])
    return df_out, live_summary

def run_pure_fyers_scanner(stock_lots, nearest_opts):
    symbols = sorted(set(FNO_SYMBOLS))
    total_fno = len(symbols)
    if not FYERS_TOKEN:
        return pd.DataFrame(), "Paste your Fyers AppID & JWT Access Token in the sidebar", total_fno

    token_part = FYERS_TOKEN.split(":", 1).pop()
    if len(token_part) < 50:
        return pd.DataFrame(), "Invalid token length — paste full Fyers JWT Access Token (eyJ...)", total_fno

    orb_mins = 5 if "5-Min" in orb_timeframe else 15
    today_str = datetime.now().strftime("%Y-%m-%d")

    live_quotes, quote_note = fetch_fyers_live_quotes(symbols, FYERS_TOKEN)
    if quote_note and "401" in quote_note:
        st.error("🔒 Fyers Token Expired or Invalid (HTTP 401). Generate a fresh daily Fyers JWT token.")
        return pd.DataFrame(), quote_note, total_fno

    matched_items = []
    target_session_date = today_str
    is_live_mode = bool(live_quotes)

    if is_live_mode:
        source_note = "Fyers API v3 Live Feed (100% Fyers Data)"
        ohol_live = []
        for sym, q in live_quotes.items():
            is_oh, is_ol = is_exact_ohol(q["open"], q["high"], q["low"])
            if is_oh or is_ol:
                ohol_live.append((sym, q["open"], q["ltp"], q["vol"], q.get("atp", 0), is_oh))

        def enrich_live(item):
            time.sleep(0.2)
            sym, open_p, ltp, vol, atp, is_oh = item
            stats = fetch_fyers_daily_stats(f"NSE:{sym}-EQ", FYERS_TOKEN)
            if not stats:
                return None
            orb = fetch_fyers_orb(f"NSE:{sym}-EQ", today_str, orb_mins, FYERS_TOKEN)
            return (sym, open_p, ltp, vol, atp, is_oh, stats, orb)

        with ThreadPoolExecutor(max_workers=4) as ex:
            matched_items = [r for r in ex.map(enrich_live, ohol_live) if r is not None]
    else:
        def scan_fyers_history(sym):
            time.sleep(0.08)
            stats = fetch_fyers_daily_stats(f"NSE:{sym}-EQ", FYERS_TOKEN)
            if not stats:
                return None
            is_oh, is_ol = is_exact_ohol(stats["open"], stats["high"], stats["low"])
            if not (is_oh or is_ol):
                return None
            orb = fetch_fyers_orb(f"NSE:{sym}-EQ", stats["date"], orb_mins, FYERS_TOKEN)
            return (sym, stats["open"], stats["ltp"], stats["vol"], 0.0, is_oh, stats, orb)

        with ThreadPoolExecutor(max_workers=4) as ex:
            matched_items = [r for r in ex.map(scan_fyers_history, symbols) if r is not None]

        if matched_items:
            target_session_date = matched_items.__getitem__(0).__getitem__(6).get("date", today_str)
        source_note = f"Fyers History API v3 — Last Session ({target_session_date} | {quote_note})"

    opt_check_records = []
    for sym, open_p, ltp, curr_vol, atp, is_oh, stats, orb in matched_items:
        _, atm_strike = get_option_strikes(ltp, is_oh)
        opt_check_records.append({"key_id": sym, "csv_sym": sym, "atm_strike": atm_strike, "is_oh": is_oh})

    opt_align_map = check_option_alignment(opt_check_records, FYERS_TOKEN, nearest_opts) if is_live_mode else {}
    bhav_map = st.session_state.get("bhav_footprints", {})

    rows = []
    for sym, open_p, ltp, curr_vol, atp, is_oh, stats, orb in matched_items:
        if "Open=Low Only" in pattern_filter and is_oh:
            continue
        if "Open=High Only" in pattern_filter and not is_oh:
            continue

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

        align_info = opt_align_map.get(sym, {"badge": "Spot Only" if is_live_mode else "Live Only", "rank": 1})
        bhav_info = bhav_map.get(sym, {})
        bhav_badge = bhav_info.get("badge", "—")
        bhav_rank = 2 if bhav_info.get("is_high_prob") else (1 if bhav_badge != "—" else 0)

        if only_orb_confirmed and not orb_ok:
            continue
        if only_option_aligned and align_info["rank"] < 2:
            continue

        if atp > 0:
            if is_oh:
                vwap_txt = f"✅ Below VWAP ({atp:.1f})" if ltp < atp else f"⚠️ Above VWAP ({atp:.1f})"
            else:
                vwap_txt = f"✅ Above VWAP ({atp:.1f})" if ltp > atp else f"⚠️ Below VWAP ({atp:.1f})"
        else:
            vwap_txt = "—"

        risk_unit = stats["atr"] * 0.5
        vol_ratio = round(curr_vol / stats["avg_vol"], 2) if stats["avg_vol"] > 0 else 0
        power, p_rank = ("🔥 Ultra", 3) if vol_ratio >= 4.0 else (("⚡ Strong", 2) if vol_ratio >= 2.0 else ("Normal", 1))
        lvl_tag = "Above PDH 🟢" if ltp > stats["pdh"] else ("Below PDL 🔴" if ltp < stats["pdl"] else "Inside Prev Day")
        opt_str, _ = get_option_strikes(ltp, is_oh)

        if is_oh:
            pat = f"Open=High ({open_p:.2f})"
            status = "Active" if ltp <= open_p else "Reversed"
            t1, t2 = round(open_p - risk_unit, 1), round(open_p - risk_unit * 2, 1)
        else:
            pat = f"Open=Low ({open_p:.2f})"
            status = "Active" if ltp >= open_p else "Reversed"
            t1, t2 = round(open_p + risk_unit, 1), round(open_p + risk_unit * 2, 1)

        rows.append({
            "Symbol": f"NSE:{sym}",
            "Pattern": pat,
            "Option O=L/O=H Align": align_info["badge"],
            "🏦 Bhavcopy Signal": bhav_badge,
            "ORB Confirm": orb_text,
            "VWAP Align": vwap_txt,
            "Status": status,
            "Price (₹)": f"{ltp:.2f}",
            "ATM | 1-ITM Option": opt_str,
            "Lot Size": stock_lots.get(sym) or DEFAULT_LOT_SIZES.get(sym, 0),
            "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
            "PDH/PDL": lvl_tag,
            "Volume": f"{vol_ratio}x",
            "Power": power,
            "_bhav_rank": bhav_rank,
            "_align_rank": align_info["rank"],
            "_orb_ok": orb_ok,
            "_vol_ratio": vol_ratio,
            "_power_rank": p_rank
        })

    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_bhav_rank", "_align_rank", "_orb_ok", "_power_rank", "_vol_ratio"], ascending=[False, False, False, False, False])
        df_out = df_out.drop(columns=["_bhav_rank", "_align_rank", "_orb_ok", "_vol_ratio", "_power_rank"])

    return df_out, source_note, total_fno

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_fyers_5m_day(fyers_symbol, target_date_str, auth_token):
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    dt_obj = datetime.strptime(target_date_str, "%Y-%m-%d")
    params = {
        "symbol": fyers_symbol,
        "resolution": "5",
        "date_format": "0",
        "range_from": str(int(dt_obj.timestamp()) - 86400),
        "range_to": str(int(dt_obj.timestamp()) + 86400),
        "cont_flag": "1"
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        payload = res.json()
        candles = payload.get("candles", ())
        if payload.get("s") == "ok" and candles:
            df = pd.DataFrame(candles, columns=("epoch", "open", "high", "low", "close", "volume"))
            df["date_str"] = pd.to_datetime(df["epoch"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
            day_df = df[df["date_str"] == target_date_str].reset_index(drop=True)
            if not day_df.empty:
                return day_df
    except Exception:
        pass
    return None
def check_historical_option_alignment(matched_records, replay_date_str, auth_token, nearest_opts):
    """Checks ±5 strike CE/PE Open=Low / Open=High on replay_date_str for active-expiry contracts."""
    if not matched_records or not auth_token:
        return {}

    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    from_dt = (datetime.strptime(replay_date_str, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    fmt_st = lambda x: f"{int(x)}" if x == int(x) else f"{x:.1f}"
    results = {}

    for rec in matched_records:
        key_id = rec["key_id"]
        csv_sym = rec["csv_sym"]
        atm = round(float(rec["atm_strike"]), 2)
        step = INDEX_CONFIG[key_id]["step"] if key_id in INDEX_CONFIG else get_stock_strike_step(atm)
        contracts = nearest_opts.get(csv_sym, {})

        if not contracts:
            results[key_id] = {"badge": "Expired Contract", "rank": 1}
            continue

        triple_strikes = []
        primary_ol_strikes = []
        opposite_oh_strikes = []
        found_any_candle = False

        # Check closest strikes first (0, +/-1, +/-2, +/-3, +/-4, +/-5)
        offsets = sorted(range(-5, 6), key=lambda o: abs(o))
        for offset in offsets:
            st_val = round(atm + (offset * step), 2)
            ce_sym = contracts.get((st_val, "CE"))
            pe_sym = contracts.get((st_val, "PE"))
            if not (ce_sym and pe_sym):
                continue

            ce_oh, ce_ol, pe_oh, pe_ol = False, False, False, False
            for opt_s, side in ((ce_sym, "CE"), (pe_sym, "PE")):
                try:
                    time.sleep(0.06)
                    res = requests.get(
                        url,
                        headers=headers,
                        params={"symbol": opt_s, "resolution": "D", "date_format": "1", "range_from": from_dt, "range_to": replay_date_str, "cont_flag": "1"},
                        timeout=8
                    ).json()
                    candles = res.get("candles", ())
                    if res.get("s") == "ok" and candles:
                        last_c = candles[-1]
                        c_date = datetime.fromtimestamp(int(last_c.__getitem__(0))).strftime("%Y-%m-%d")
                        if c_date == replay_date_str:
                            found_any_candle = True
                            oh_f, ol_f = is_exact_ohol(last_c.__getitem__(1), last_c.__getitem__(2), last_c.__getitem__(3))
                            if side == "CE":
                                ce_oh, ce_ol = oh_f, ol_f
                            else:
                                pe_oh, pe_ol = oh_f, ol_f
                except Exception:
                    continue

            if not rec["is_oh"]:
                if ce_ol and pe_oh:
                    triple_strikes.append(fmt_st(st_val))
                if ce_ol:
                    primary_ol_strikes.append(f"{fmt_st(st_val)} CE")
                if pe_oh:
                    opposite_oh_strikes.append(f"{fmt_st(st_val)} PE")
            else:
                if pe_ol and ce_oh:
                    triple_strikes.append(fmt_st(st_val))
                if pe_ol:
                    primary_ol_strikes.append(f"{fmt_st(st_val)} PE")
                if ce_oh:
                    opposite_oh_strikes.append(f"{fmt_st(st_val)} CE")

            # Stop early once a clean Triple match is found closest to ATM
            if triple_strikes:
                break

        if not found_any_candle:
            results[key_id] = {"badge": "Expired Contract", "rank": 1}
        elif triple_strikes:
            results[key_id] = {"badge": f"🔥 TRIPLE @ {triple_strikes.__getitem__(0)}", "rank": 3}
        elif primary_ol_strikes and opposite_oh_strikes:
            results[key_id] = {"badge": f"🔥 SPLIT ({primary_ol_strikes.__getitem__(0)} O=L | {opposite_oh_strikes.__getitem__(0)} O=H)", "rank": 3}
        elif primary_ol_strikes:
            results[key_id] = {"badge": f"⚡ {primary_ol_strikes.__getitem__(0)} Open=Low", "rank": 2}
        elif opposite_oh_strikes:
            results[key_id] = {"badge": f"⚡ {opposite_oh_strikes.__getitem__(0)} Open=High", "rank": 2}
        else:
            results[key_id] = {"badge": "Spot Only", "rank": 1}

    return results

def run_date_replay(items_list, replay_date_str, orb_minutes, replay_cutoff, auth_token, stock_lots, idx_lots, nearest_opts):
    """
    replay_cutoff: '09:20 AM (1st 5m Candle)', '09:30 AM (First 3 Candles)', or '03:30 PM (Full EOD)'
    Reconstructs the exact dashboard visible at that morning timestamp without survivorship bias.
    """
    candles_for_orb = 1 if orb_minutes == 5 else 3
    cutoff_bars = 1 if "09:20" in replay_cutoff else (3 if "09:30" in replay_cutoff else 75)
    is_morning_sim = cutoff_bars < 75

    matched_raw = []
    progress = st.progress(0, text=f"Replaying {replay_date_str} as of {replay_cutoff}...")

    for idx, label in enumerate(items_list):
        progress.progress((idx + 1) / len(items_list), text=f"Scanning {label} ({idx+1}/{len(items_list)})...")
        time.sleep(0.08)

        is_index = label in INDEX_CONFIG
        fyers_sym = INDEX_CONFIG[label]["fyers"] if is_index else f"NSE:{label}-EQ"
        csv_sym = INDEX_CONFIG[label]["csv_sym"] if is_index else label
        display_sym = f"🏛️ {label}" if is_index else f"NSE:{label}"

        url = "https://" + "api-t1." + "fyers.in" + "/data/history"
        headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        end_dt = datetime.strptime(replay_date_str, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=45)
        params = {"symbol": fyers_sym, "resolution": "D", "date_format": "1", "range_from": start_dt.strftime("%Y-%m-%d"), "range_to": replay_date_str, "cont_flag": "1"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            payload = res.json()
            candles = payload.get("candles", ())
            if payload.get("s") != "ok" or len(candles) < 15:
                continue

            df_d = pd.DataFrame(candles, columns=("epoch", "open", "high", "low", "close", "volume"))
            df_d["date_str"] = pd.to_datetime(df_d["epoch"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.strftime("%Y-%m-%d")
            df_d = df_d[df_d["date_str"] <= replay_date_str].reset_index(drop=True)
            if len(df_d) < 15 or df_d["date_str"].iloc[-1] != replay_date_str:
                continue

            prev_r = df_d.iloc[-2]
            hist_prior = df_d.iloc[:-1].copy()
            hist_prior["prev_close"] = hist_prior["close"].shift(1)
            hist_prior["tr"] = hist_prior[["high", "prev_close"]].max(axis=1) - hist_prior[["low", "prev_close"]].min(axis=1)
            atr_14 = round(float(hist_prior["tr"].tail(14).mean()), 2)
            avg_vol_20 = float(hist_prior["volume"].tail(20).mean())
            pdh, pdl = float(prev_r["high"]), float(prev_r["low"])

            day_5m = fetch_fyers_5m_day(fyers_sym, replay_date_str, auth_token)
            if day_5m is None or len(day_5m) < cutoff_bars:
                continue

            # Slice intraday candles ONLY up to the chosen morning snapshot time
            morning_slice = day_5m.iloc[:cutoff_bars]
            after_slice = day_5m.iloc[cutoff_bars:]

            open_p = float(morning_slice["open"].iloc.__getitem__(0))
            snap_high = float(morning_slice["high"].max())
            snap_low = float(morning_slice["low"].min())
            snap_ltp = float(morning_slice["close"].iloc[-1])
            snap_vol = float(morning_slice["volume"].sum())

            is_oh, is_ol = is_exact_ohol(open_p, snap_high, snap_low)
            if not (is_oh or is_ol):
                continue

            risk_unit = atr_14 * 0.5
            t1 = round(open_p - risk_unit, 1) if is_oh else round(open_p + risk_unit, 1)
            t2 = round(open_p - risk_unit * 2, 1) if is_oh else round(open_p + risk_unit * 2, 1)

            # Evaluate ORB status AS OF the chosen snapshot time
            orb_ok = False
            if len(morning_slice) >= candles_for_orb:
                orb_bars = morning_slice.iloc[:candles_for_orb]
                orb_h, orb_l = float(orb_bars["high"].max()), float(orb_bars["low"].min())
                if is_oh:
                    orb_ok = snap_low < orb_l
                    orb_text = f"✅ {orb_minutes}m Broken (<{orb_l:.1f})" if orb_ok else f"⏳ Inside (>{orb_l:.1f})"
                else:
                    orb_ok = snap_high > orb_h
                    orb_text = f"✅ {orb_minutes}m Breakout (>{orb_h:.1f})" if orb_ok else f"⏳ Inside (<{orb_h:.1f})"
            else:
                orb_text = f"⏳ Wait {orb_minutes}m Candle"

            # Evaluate what happened AFTER the morning snapshot through 3:30 PM
            if after_slice.empty:
                full_high, full_low, final_close = snap_high, snap_low, snap_ltp
            else:
                full_high = max(snap_high, float(after_slice["high"].max()))
                full_low = min(snap_low, float(after_slice["low"].min()))
                final_close = float(after_slice["close"].iloc[-1])

            if is_oh:
                if full_high > open_p:
                    outcome = "❌ Reversed / SL Hit"
                elif full_low <= t2:
                    outcome = "🎯 1:2 Target Hit"
                elif full_low <= t1:
                    outcome = "✅ 1:1 Target Hit"
                else:
                    outcome = "🟢 Held Below Open" if final_close < open_p else "⏱️ Flat at Open"
            else:
                if full_low < open_p:
                    outcome = "❌ Reversed / SL Hit"
                elif full_high >= t2:
                    outcome = "🎯 1:2 Target Hit"
                elif full_high >= t1:
                    outcome = "✅ 1:1 Target Hit"
                else:
                    outcome = "🟢 Held Above Open" if final_close > open_p else "⏱️ Flat at Open"

            if is_index:
                vol_txt, power, p_rank, vol_ratio = "Index", "🏛️ Index", 4, 999.0
                opt_str, atm_strike = get_index_option_strikes(label, snap_ltp, is_oh)
                lot_val = idx_lots.get(label, INDEX_CONFIG[label]["lot"])
            else:
                # Annualize/scale morning volume or show exact morning volume ratio
                vol_ratio = round(snap_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 0
                vol_txt = f"{vol_ratio}x"
                power, p_rank = ("🔥 Ultra", 3) if vol_ratio >= 0.40 and is_morning_sim else (("⚡ Strong", 2) if vol_ratio >= 0.20 and is_morning_sim else ("Normal", 1))
                opt_str, atm_strike = get_option_strikes(snap_ltp, is_oh)
                lot_val = stock_lots.get(label) or DEFAULT_LOT_SIZES.get(label, 0)

            lvl_tag = "Above PDH 🟢" if snap_ltp > pdh else ("Below PDL 🔴" if snap_ltp < pdl else "Inside Prev Day")

            matched_raw.append({
                "key_id": label,
                "csv_sym": csv_sym,
                "atm_strike": atm_strike,
                "is_oh": is_oh,
                "display_sym": display_sym,
                "open_p": open_p,
                "snap_ltp": snap_ltp,
                "orb_text": orb_text,
                "orb_ok": orb_ok,
                "outcome": outcome,
                "opt_str": opt_str,
                "lot_val": lot_val,
                "t1": t1,
                "t2": t2,
                "lvl_tag": lvl_tag,
                "vol_txt": vol_txt,
                "vol_ratio": vol_ratio,
                "power": power,
                "p_rank": p_rank
            })
        except Exception:
            continue

    if matched_raw:
        progress.progress(1.0, text="Checking ±5 option strikes (CE/PE) & matching historical expiry...")
        opt_align_map = check_historical_option_alignment(matched_raw, replay_date_str, auth_token, nearest_opts)
        for rec in matched_raw:
            if opt_align_map.get(rec["key_id"], {}).get("badge") == "Expired Contract":
                bhav_res = check_bhavcopy_option_alignment(rec, replay_date_str)
                if bhav_res:
                    opt_align_map[rec["key_id"]] = bhav_res
                else:
                    opt_align_map[rec["key_id"]] = {"badge": "Upload Bhavcopy for Expiry", "rank": 1}
    else:
        opt_align_map = {}

    rows = []
    for m in matched_raw:
        align_info = opt_align_map.get(m["key_id"], {"badge": "Spot Only", "rank": 1})
        rows.append({
            "Symbol": m["display_sym"],
            "Pattern": f"Open=High ({m['open_p']:.2f})" if m["is_oh"] else f"Open=Low ({m['open_p']:.2f})",
            "Option O=L/O=H Align": align_info["badge"],
            f"ORB @ {replay_cutoff[:8]}": m["orb_text"],
            "Later Day Outcome": m["outcome"],
            f"Price @ {replay_cutoff[:8]}": f"{m['snap_ltp']:.2f}",
            "ATM | 1-ITM Option": m["opt_str"],
            "Lot Size": m["lot_val"],
            "Normal Tgt (1:1|1:2)": f"{m['t1']} | {m['t2']}",
            "PDH/PDL": m["lvl_tag"],
            "Vol Ratio": m["vol_txt"],
            "Power": m["power"],
            "_align_rank": align_info["rank"],
            "_orb_ok": m["orb_ok"],
            "_vol_ratio": m["vol_ratio"],
            "_power_rank": m["p_rank"]
        })

    progress.empty()
    df_out = pd.DataFrame(rows)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_power_rank", "_align_rank", "_orb_ok", "_vol_ratio"], ascending=[False, False, False, False])
        df_out = df_out.drop(columns=["_align_rank", "_orb_ok", "_vol_ratio", "_power_rank"])
    return df_out

def style_align_badge(val):
    s = str(val)
    if "🔥 TRIPLE" in s:
        return "background-color: #d500f9; color: white; font-weight: bold;"
    elif "⚡" in s:
        return "color: #ffd54f; font-weight: bold;"
    return "color: #9e9e9e;"

def style_scanner_table(df):
    return (
        df.style
        .map(lambda v: "color: #ff5252; font-weight: bold;" if "Open=High" in str(v) else "color: #4caf50; font-weight: bold;", subset=["Pattern"])
        .map(style_align_badge, subset=["Option O=L/O=H Align"])
        .map(lambda v: "color: #00e676; font-weight: bold;" if "✅" in str(v) else "color: #ffb74d;", subset=["ORB Confirm"])
        .map(lambda v: "color: #00e676;" if "✅" in str(v) else ("color: #ff9800;" if "⚠️" in str(v) else ""), subset=["VWAP Align"])
        .map(lambda v: "color: #4caf50; font-weight: bold;" if v == "Active" else "color: #ff9800; font-weight: bold;", subset=["Status"])
        .map(lambda _: "color: #ffd54f; font-weight: bold;", subset=["ATM | 1-ITM Option"])
        .map(lambda _: "color: #00bcd4; font-weight: bold;", subset=["Normal Tgt (1:1|1:2)"])
        .map(lambda v: "background-color: #9c27b0; color: white; font-weight: bold;" if "Ultra" in str(v) else ("background-color: #2196f3; color: white; font-weight: bold;" if "Strong" in str(v) else ""), subset=["Power"])
    )
import zipfile
import io

def parse_udiff_bhavcopies(uploaded_files, filter_sensex_only=False):
    """Reads multiple NSE or BSE UDiFF F&O Bhavcopy (.csv or .zip) files into a unified DataFrame."""
    frames = []
    allowed_nse = set(FNO_SYMBOLS) | {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}

    for f in uploaded_files:
        try:
            raw_bytes = f.read()
            if f.name.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                    if not csv_names:
                        continue
                    df = pd.read_csv(zf.open(csv_names.__getitem__(0)), low_memory=False)
            else:
                df = pd.read_csv(io.BytesIO(raw_bytes), low_memory=False)

            df.columns = [c.strip() for c in df.columns]
            if "TckrSymb" not in df.columns or "TradDt" not in df.columns:
                continue

            df["TckrSymb"] = df["TckrSymb"].astype(str).str.strip().str.upper()
            if filter_sensex_only:
                df = df[df["TckrSymb"] == "SENSEX"]
            else:
                df = df[df["TckrSymb"].isin(allowed_nse)]

            if not df.empty:
                frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

def analyze_institutional_activity(df_bhav):
    """Detects abnormal Futures OI buildup, Long/Short positioning, and Option Writing Walls."""
    if df_bhav.empty:
        return pd.DataFrame(), "", 0

    num_cols = ("OpnPric", "HghPric", "LwPric", "ClsPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "StrkPric")
    for col in num_cols:
        if col in df_bhav.columns:
            df_bhav[col] = pd.to_numeric(df_bhav[col], errors="coerce").fillna(0.0)

    df_bhav["TradDt"] = pd.to_datetime(df_bhav["TradDt"]).dt.strftime("%Y-%m-%d")
    df_bhav["XpryDt"] = pd.to_datetime(df_bhav["XpryDt"]).dt.strftime("%Y-%m-%d")
    all_dates = sorted(df_bhav["TradDt"].unique())
    latest_dt = all_dates[-1]

    # Save full normalized Bhavcopy DataFrame for historical backtest option-chain lookup
    st.session_state["bhav_df"] = df_bhav

    fut_df = df_bhav[df_bhav["FinInstrmTp"].isin(("IDF", "STF"))].copy()
    fut_df = fut_df.sort_values("XpryDt").groupby(["TradDt", "TckrSymb"], as_index=False).first()

    opt_latest = df_bhav[(df_bhav["TradDt"] == latest_dt) & (df_bhav["FinInstrmTp"].isin(("IDO", "STO")))].copy()
    nearest_exp_map = opt_latest.groupby("TckrSymb")["XpryDt"].min().to_dict()
    opt_latest = opt_latest[opt_latest["XpryDt"] == opt_latest["TckrSymb"].map(nearest_exp_map)]

    results = []
    footprint_lookup = {}

    for sym, grp in fut_df.groupby("TckrSymb"):
        grp = grp.sort_values("TradDt").reset_index(drop=True)
        if grp["TradDt"].iloc[-1] != latest_dt or len(grp) < 3:
            continue

        last_r = grp.iloc[-1]
        prev_r = grp.iloc[-2]
        price_chg_pct = round(((last_r["ClsPric"] - prev_r["ClsPric"]) / prev_r["ClsPric"]) * 100, 2) if prev_r["ClsPric"] > 0 else 0.0
        oi_chg = float(last_r["ChngInOpnIntrst"])
        oi_chg_pct = round((oi_chg / prev_r["OpnIntrst"]) * 100, 2) if prev_r["OpnIntrst"] > 0 else 0.0

        prior_grp = grp.iloc[:-1]
        avg_abs_oi_chg = prior_grp["ChngInOpnIntrst"].abs().mean()
        avg_vol = prior_grp["TtlTradgVol"].mean()

        oi_spike_ratio = round(abs(oi_chg) / avg_abs_oi_chg, 2) if avg_abs_oi_chg > 0 else 0.0
        vol_spike_ratio = round(last_r["TtlTradgVol"] / avg_vol, 2) if avg_vol > 0 else 0.0

        f_oh, f_ol = is_exact_ohol(last_r["OpnPric"], last_r["HghPric"], last_r["LwPric"])
        fut_ohol = "Fut Open=Low 🟢" if f_ol else ("Fut Open=High 🔴" if f_oh else "—")

        is_high_prob = False
        if abs(price_chg_pct) <= 0.6 and oi_chg > 0 and oi_spike_ratio >= 2.0:
            footprint = "🕵️ Silent Accumulation (Flat Price + Huge OI)"
            score = 5
            is_high_prob = True
        elif price_chg_pct > 0.5 and oi_chg > 0 and (oi_spike_ratio >= 1.8 or vol_spike_ratio >= 1.8):
            footprint = "🟢 Institutional Long Buildup"
            score = 4
            is_high_prob = True
        elif price_chg_pct < -0.5 and oi_chg > 0 and (oi_spike_ratio >= 1.8 or vol_spike_ratio >= 1.8):
            footprint = "🔴 Institutional Short Buildup"
            score = 4
            is_high_prob = True
        elif (f_ol or f_oh) and oi_spike_ratio >= 2.0:
            footprint = f"🎯 Fut OHOL + {oi_spike_ratio}x OI Spike"
            score = 4
            is_high_prob = True
        elif price_chg_pct > 0.8 and oi_chg < 0 and oi_spike_ratio >= 1.8:
            footprint = "⚡ Aggressive Short Covering"
            score = 2
        elif price_chg_pct < -0.8 and oi_chg < 0 and oi_spike_ratio >= 1.8:
            footprint = "⚠️ Long Unwinding"
            score = 2
        else:
            footprint = "Normal Flow"
            score = 1

        if footprint != "Normal Flow":
            footprint_lookup[sym] = {"badge": f"{footprint} ({oi_spike_ratio}x OI)", "is_high_prob": is_high_prob, "date": latest_dt}

        sym_opts = opt_latest[opt_latest["TckrSymb"] == sym]
        ce_opts = sym_opts[sym_opts["OptnTp"] == "CE"]
        pe_opts = sym_opts[sym_opts["OptnTp"] == "PE"]

        call_wall, put_wall = "—", "—"
        if not ce_opts.empty:
            top_ce = ce_opts.loc[ce_opts["ChngInOpnIntrst"].idxmax()]
            if top_ce["ChngInOpnIntrst"] > 0:
                call_wall = f"{int(top_ce['StrkPric'])} CE (+{int(top_ce['ChngInOpnIntrst']):,})"
        if not pe_opts.empty:
            top_pe = pe_opts.loc[pe_opts["ChngInOpnIntrst"].idxmax()]
            if top_pe["ChngInOpnIntrst"] > 0:
                put_wall = f"{int(top_pe['StrkPric'])} PE (+{int(top_pe['ChngInOpnIntrst']):,})"

        results.append({
            "Symbol": sym,
            "Institutional Footprint": footprint,
            "High Prob": is_high_prob,
            "Fut Close": f"{last_r['ClsPric']:.2f}",
            "Price Chg (%)": f"{price_chg_pct:+.2f}%",
            "OI Chg (%)": f"{oi_chg_pct:+.2f}%",
            "OI Spike": f"{oi_spike_ratio}x",
            "Vol Spike": f"{vol_spike_ratio}x",
            "Fut OHOL": fut_ohol,
            "Max Call Wall (+OI)": call_wall,
            "Max Put Wall (+OI)": put_wall,
            "_score": score,
            "_oi_spike": oi_spike_ratio
        })

    # Save cross-tagging lookup into session_state so Live Scanner displays it automatically
    st.session_state["bhav_footprints"] = footprint_lookup

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_score", "_oi_spike"], ascending=[False, False]).drop(columns=["_score", "_oi_spike"])
    return df_out, latest_dt, len(all_dates)

def check_bhavcopy_option_alignment(rec, replay_date_str):
    """Fallback for expired backtest dates: checks ±5 strike CE/PE O=L/O=H from uploaded Bhavcopies."""
    df_bhav = st.session_state.get("bhav_df")
    if df_bhav is None or df_bhav.empty:
        return None

    csv_sym = rec["csv_sym"]
    day_opts = df_bhav[
        (df_bhav["TradDt"] == replay_date_str)
        & (df_bhav["TckrSymb"] == csv_sym)
        & (df_bhav["FinInstrmTp"].isin(("IDO", "STO")))
        & (df_bhav["XpryDt"] >= replay_date_str)
    ]
    if day_opts.empty:
        return None

    # Select the corresponding nearest expiry date active on replay_date_str
    nearest_exp = day_opts["XpryDt"].min()
    exp_opts = day_opts[day_opts["XpryDt"] == nearest_exp]

    key_id = rec["key_id"]
    atm = round(float(rec["atm_strike"]), 2)
    step = INDEX_CONFIG[key_id]["step"] if key_id in INDEX_CONFIG else get_stock_strike_step(atm)
    fmt_st = lambda x: f"{int(x)}" if x == int(x) else f"{x:.1f}"

    triple_strikes, primary_ol, opposite_oh = [], [], []
    offsets = sorted(range(-5, 6), key=lambda o: abs(o))

    for offset in offsets:
        st_val = round(atm + (offset * step), 2)
        ce_rows = exp_opts[(exp_opts["StrkPric"].round(2) == st_val) & (exp_opts["OptnTp"] == "CE")]
        pe_rows = exp_opts[(exp_opts["StrkPric"].round(2) == st_val) & (exp_opts["OptnTp"] == "PE")]
        if ce_rows.empty or pe_rows.empty:
            continue

        ce_r, pe_r = ce_rows.iloc[0], pe_rows.iloc[0]
        ce_oh, ce_ol = is_exact_ohol(ce_r["OpnPric"], ce_r["HghPric"], ce_r["LwPric"])
        pe_oh, pe_ol = is_exact_ohol(pe_r["OpnPric"], pe_r["HghPric"], pe_r["LwPric"])

        if not rec["is_oh"]:
            if ce_ol and pe_oh:
                triple_strikes.append(fmt_st(st_val))
            if ce_ol:
                primary_ol.append(f"{fmt_st(st_val)} CE")
            if pe_oh:
                opposite_oh.append(f"{fmt_st(st_val)} PE")
        else:
            if pe_ol and ce_oh:
                triple_strikes.append(fmt_st(st_val))
            if pe_ol:
                primary_ol.append(f"{fmt_st(st_val)} PE")
            if ce_oh:
                opposite_oh.append(f"{fmt_st(st_val)} CE")

        if triple_strikes:
            break

    exp_tag = f"[Exp: {nearest_exp}]"
    if triple_strikes:
        return {"badge": f"🔥 TRIPLE @ {triple_strikes.__getitem__(0)} {exp_tag}", "rank": 3}
    elif primary_ol and opposite_oh:
        return {"badge": f"🔥 SPLIT ({primary_ol.__getitem__(0)} O=L | {opposite_oh.__getitem__(0)} O=H) {exp_tag}", "rank": 3}
    elif primary_ol:
        return {"badge": f"⚡ {primary_ol.__getitem__(0)} O=L {exp_tag}", "rank": 2}
    elif opposite_oh:
        return {"badge": f"⚡ {opposite_oh.__getitem__(0)} O=H {exp_tag}", "rank": 2}
    return {"badge": f"Spot Only {exp_tag}", "rank": 1}


    # 1. Futures Institutional Activity (Nearest Expiry per Symbol per Date)
    fut_df = df_bhav[df_bhav["FinInstrmTp"].isin(("IDF", "STF"))].copy()
    fut_df = fut_df.sort_values("XpryDt").groupby(["TradDt", "TckrSymb"], as_index=False).first()

    # 2. Options Institutional Writing Walls on Latest Date (Nearest Active Expiry)
    opt_latest = df_bhav[(df_bhav["TradDt"] == latest_dt) & (df_bhav["FinInstrmTp"].isin(("IDO", "STO")))].copy()
    nearest_exp_map = opt_latest.groupby("TckrSymb")["XpryDt"].min().to_dict()
    opt_latest = opt_latest[opt_latest["XpryDt"] == opt_latest["TckrSymb"].map(nearest_exp_map)]

    results = []
    for sym, grp in fut_df.groupby("TckrSymb"):
        grp = grp.sort_values("TradDt").reset_index(drop=True)
        if grp["TradDt"].iloc[-1] != latest_dt or len(grp) < 3:
            continue

        last_r = grp.iloc[-1]
        prev_r = grp.iloc[-2]
        price_chg_pct = round(((last_r["ClsPric"] - prev_r["ClsPric"]) / prev_r["ClsPric"]) * 100, 2) if prev_r["ClsPric"] > 0 else 0.0
        oi_chg = float(last_r["ChngInOpnIntrst"])
        oi_chg_pct = round((oi_chg / prev_r["OpnIntrst"]) * 100, 2) if prev_r["OpnIntrst"] > 0 else 0.0

        prior_grp = grp.iloc[:-1]
        avg_abs_oi_chg = prior_grp["ChngInOpnIntrst"].abs().mean()
        avg_vol = prior_grp["TtlTradgVol"].mean()

        oi_spike_ratio = round(abs(oi_chg) / avg_abs_oi_chg, 2) if avg_abs_oi_chg > 0 else 0.0
        vol_spike_ratio = round(last_r["TtlTradgVol"] / avg_vol, 2) if avg_vol > 0 else 0.0

        # Classify Institutional Footprint
        if abs(price_chg_pct) <= 0.6 and oi_chg > 0 and oi_spike_ratio >= 2.0:
            footprint = "🕵️ Silent Accumulation (Flat Price + Huge OI)"
            score = 4
        elif price_chg_pct > 0.5 and oi_chg > 0 and (oi_spike_ratio >= 1.8 or vol_spike_ratio >= 1.8):
            footprint = "🟢 Institutional Long Buildup"
            score = 3
        elif price_chg_pct < -0.5 and oi_chg > 0 and (oi_spike_ratio >= 1.8 or vol_spike_ratio >= 1.8):
            footprint = "🔴 Institutional Short Buildup"
            score = 3
        elif price_chg_pct > 0.8 and oi_chg < 0 and oi_spike_ratio >= 1.8:
            footprint = "⚡ Aggressive Short Covering"
            score = 2
        elif price_chg_pct < -0.8 and oi_chg < 0 and oi_spike_ratio >= 1.8:
            footprint = "⚠️ Long Unwinding"
            score = 2
        else:
            footprint = "Normal Flow"
            score = 1

        # Option Writing Walls & Option Open=Low / Open=High on Latest Date
        sym_opts = opt_latest[opt_latest["TckrSymb"] == sym]
        ce_opts = sym_opts[sym_opts["OptnTp"] == "CE"]
        pe_opts = sym_opts[sym_opts["OptnTp"] == "PE"]

        call_wall = "—"
        put_wall = "—"
        opt_ohol_note = "—"

        if not ce_opts.empty:
            top_ce = ce_opts.loc[ce_opts["ChngInOpnIntrst"].idxmax()]
            if top_ce["ChngInOpnIntrst"] > 0:
                call_wall = f"{int(top_ce['StrkPric'])} CE (+{int(top_ce['ChngInOpnIntrst']):,})"
        if not pe_opts.empty:
            top_pe = pe_opts.loc[pe_opts["ChngInOpnIntrst"].idxmax()]
            if top_pe["ChngInOpnIntrst"] > 0:
                put_wall = f"{int(top_pe['StrkPric'])} PE (+{int(top_pe['ChngInOpnIntrst']):,})"

        # Check if Futures itself had Exact Open=High or Open=Low on latest date
        f_oh, f_ol = is_exact_ohol(last_r["OpnPric"], last_r["HghPric"], last_r["LwPric"])
        fut_ohol = "Fut Open=Low 🟢" if f_ol else ("Fut Open=High 🔴" if f_oh else "—")

        results.append({
            "Symbol": sym,
            "Institutional Footprint": footprint,
            "Fut Close": f"{last_r['ClsPric']:.2f}",
            "Price Chg (%)": f"{price_chg_pct:+.2f}%",
            "OI Chg (%)": f"{oi_chg_pct:+.2f}%",
            "OI Spike": f"{oi_spike_ratio}x",
            "Vol Spike": f"{vol_spike_ratio}x",
            "Fut OHOL": fut_ohol,
            "Max Call Wall (+OI)": call_wall,
            "Max Put Wall (+OI)": put_wall,
            "_score": score,
            "_oi_spike": oi_spike_ratio
        })

    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_score", "_oi_spike"], ascending=[False, False]).drop(columns=["_score", "_oi_spike"])
    return df_out, latest_dt, len(all_dates)

# --- Main App UI ---
st.subheader("📊 Fyers NSE/BSE Indices & F&O Triple-Aligned Open=High / Open=Low Scanner")

stock_lots, idx_lots, nearest_opts = get_fyers_masters()
tab_live, tab_bt, tab_inst = st.tabs(("📡 Live Intraday Scanner", "📈 Strategy Backtester", "🏦 Institutional Bhavcopy Radar"))

with tab_live:
    col_btn, col_info = st.columns((1, 5))
    with col_btn:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()

    orb_mins_live = 5 if "5-Min" in orb_timeframe else 15
    with st.spinner("Scanning Indices, Option Chains & 148 F&O Stocks..."):
        df_idx, idx_summary = scan_live_indices(FYERS_TOKEN, orb_mins_live, idx_lots, nearest_opts)
        df_results, source_note, total_fno = run_pure_fyers_scanner(stock_lots, nearest_opts)

    with col_info:
        st.caption(f"Scanned **6 Indices + {total_fno} F&O Stocks** | Mode: **{source_note}**")

    if idx_summary:
        n50, snx, bnk = idx_summary.get("NIFTY 50", {}), idx_summary.get("SENSEX", {}), idx_summary.get("BANK NIFTY", {})
        i1, i2, i3 = st.columns(3)
        if n50: i1.metric("NIFTY 50", f"{n50['ltp']:.2f}", f"{n50['chp']:.2f}% (Open: {n50['open']:.2f})")
        if snx: i2.metric("BSE SENSEX", f"{snx['ltp']:.2f}", f"{snx['chp']:.2f}% (Open: {snx['open']:.2f})")
        if bnk: i3.metric("BANK NIFTY", f"{bnk['ltp']:.2f}", f"{bnk['chp']:.2f}% (Open: {bnk['open']:.2f})")

    if not df_idx.empty:
        st.markdown("#### 🏛️ Indices Exact (0.00%) Open=High / Open=Low + Option Chain Alignment")
        styled_idx = (
            df_idx.style
            .map(lambda v: "color: #ff5252; font-weight: bold;" if "Open=High" in str(v) else "color: #4caf50; font-weight: bold;", subset=["Pattern"])
            .map(style_align_badge, subset=["Option O=L/O=H Align"])
            .map(lambda v: "color: #00e676; font-weight: bold;" if "✅" in str(v) else "color: #ffb74d;", subset=["ORB Confirm"])
            .map(lambda v: "color: #4caf50; font-weight: bold;" if v == "Active" else "color: #ff9800; font-weight: bold;", subset=["Status"])
            .map(lambda _: "color: #ffd54f; font-weight: bold;", subset=["ATM | 1-ITM Option"])
            .map(lambda _: "color: #00bcd4; font-weight: bold;", subset=["Normal Tgt (1:1|1:2)"])
        )
        st.dataframe(styled_idx, use_container_width=True, hide_index=True)
    elif FYERS_TOKEN:
        st.info("🏛️ Indices Check: None of the 6 indices currently hold an exact 0.00% Open=High or Open=Low.")

    st.markdown("#### 📈 NSE F&O Stocks Exact (0.00%) Open=High / Open=Low + Option Chain Alignment")
    if not df_results.empty:
        triple_c = df_results["Option O=L/O=H Align"].str.contains("🔥 TRIPLE").sum()
        orb_c = df_results["ORB Confirm"].str.contains("✅").sum()
        bull_c = df_results["Pattern"].str.contains("Open=Low").sum()
        bear_c = df_results["Pattern"].str.contains("Open=High").sum()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Exact Matches", len(df_results))
        m2.metric("🔥 Triple Option-Aligned", int(triple_c))
        m3.metric("✅ ORB Confirmed", int(orb_c))
        m4.metric("🟢 O=L | 🔴 O=H", f"{int(bull_c)} | {int(bear_c)}")

        st.dataframe(style_scanner_table(df_results), use_container_width=True, hide_index=True, height=520)
        st.download_button(
            "📥 Download Live Watchlist (CSV)",
            data=df_results.to_csv(index=False).encode("utf-8"),
            file_name=f"fyers_ohol_live_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv"
        )
    elif FYERS_TOKEN:
        st.info("No F&O stocks matched your current filters right now.")

with tab_bt:
    st.markdown("Replay any past date as of **9:20 AM**, **9:30 AM**, or **Full EOD** to see the exact morning dashboard and subsequent outcome.")
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        selected_date = st.date_input("Select Historical Date", value=datetime.now().date() - timedelta(days=1), max_value=datetime.now().date())
    with b2:
        replay_cutoff = st.selectbox(
            "Snapshot Time (IST)",
            ("09:30 AM (First 3 Candles)", "09:20 AM (1st 5m Candle)", "03:30 PM (Full EOD)")
        )
    with b3:
        bt_universe = st.selectbox("Scan Universe", ("All 148 F&O Stocks + 6 Indices (~16s)", "Indices Only (Nifty, Sensex, BankNifty, FinNifty, Midcap, Bankex — ~1s)", "Top 40 Liquid F&O + 6 Indices (~6s)"))
    with b4:
        bt_orb = st.selectbox("ORB Confirmation", (5, 15), format_func=lambda m: f"{m}-Min ORB")

    if st.button("▶️ Replay Morning / Date Snapshot", type="primary"):
        if not FYERS_TOKEN:
            st.warning("⚠️ Please log in to Fyers in the left sidebar first.")
        else:
            date_str = selected_date.strftime("%Y-%m-%d")
            idx_list = list(INDEX_CONFIG.keys())
            test_items = idx_list if "Indices Only" in bt_universe else (idx_list + sorted(set(FNO_SYMBOLS))[:40] if "Top 40" in bt_universe else idx_list + sorted(set(FNO_SYMBOLS)))
            df_replay = run_date_replay(test_items, date_str, bt_orb, replay_cutoff, FYERS_TOKEN, stock_lots, idx_lots, nearest_opts)

            if df_replay.empty:
                st.info(f"No exact 0.00% Open=High or Open=Low matches found on **{date_str}** at **{replay_cutoff}**.")
            else:
                orb_col = f"ORB @ {replay_cutoff[:8]}"
                bull_c = df_replay["Pattern"].str.contains("Open=Low").sum()
                bear_c = df_replay["Pattern"].str.contains("Open=High").sum()
                tgt_c = df_replay["Later Day Outcome"].str.contains("Target Hit").sum()
                sl_c = df_replay["Later Day Outcome"].str.contains("Reversed / SL Hit").sum()

                k1, k2, k3, k4 = st.columns(4)
                k1.metric(f"Matches @ {replay_cutoff[:8]}", len(df_replay))
                k2.metric("🟢 O=L | 🔴 O=H", f"{int(bull_c)} | {int(bear_c)}")
                k3.metric("🎯 Later Target Hit", int(tgt_c))
                k4.metric("❌ Later SL / Reversed", int(sl_c))

                styled_replay = (
                    df_replay.style
                    .map(lambda v: "color: #ff5252; font-weight: bold;" if "Open=High" in str(v) else "color: #4caf50; font-weight: bold;", subset=["Pattern"])
                    .map(style_align_badge, subset=["Option O=L/O=H Align"])
                    .map(lambda v: "color: #00e676; font-weight: bold;" if "✅" in str(v) else "color: #ffb74d;", subset=[orb_col])
                    .map(lambda v: "color: #00e676; font-weight: bold;" if "Target Hit" in str(v) or "Held" in str(v) else "color: #ff5252; font-weight: bold;", subset=["Later Day Outcome"])
                    .map(lambda _: "color: #ffd54f; font-weight: bold;", subset=["ATM | 1-ITM Option"])
                    .map(lambda _: "color: #00bcd4; font-weight: bold;", subset=["Normal Tgt (1:1|1:2)"])
                    .map(lambda v: "background-color: #6a1b9a; color: white; font-weight: bold;" if "Index" in str(v) else ("background-color: #9c27b0; color: white; font-weight: bold;" if "Ultra" in str(v) else ("background-color: #2196f3; color: white; font-weight: bold;" if "Strong" in str(v) else "")), subset=["Power"])
                )
                st.dataframe(styled_replay, use_container_width=True, hide_index=True, height=560)
                st.download_button(
                    f"📥 Download {date_str} ({replay_cutoff[:8]}) Replay.csv",
                    data=df_replay.to_csv(index=False).encode("utf-8"),
                    file_name=f"fyers_morning_replay_{date_str}_{replay_cutoff[:5].replace(':', '')}.csv",
                    mime="text/csv"
                )

with tab_inst:
    st.markdown("Upload **20–25 days of NSE & BSE F&O UDiFF Bhavcopy files (`.csv` or `.zip`)** to detect mid-cycle **Silent Institutional Accumulation**, **Long/Short Buildups**, and **Option Writing Walls**.")

    u1, u2 = st.columns(2)
    with u1:
        nse_files = st.file_uploader(
            "📂 Upload NSE F&O Bhavcopies (NSE Indices + F&O Stocks)",
            type=("csv", "zip"),
            accept_multiple_files=True,
            key="nse_bhav_uploader"
        )
    with u2:
        bse_files = st.file_uploader(
            "📂 Upload BSE F&O Bhavcopies (Filters BSE SENSEX Only)",
            type=("csv", "zip"),
            accept_multiple_files=True,
            key="bse_bhav_uploader"
        )

    only_unusual = st.checkbox("🕵️ Show Only Unusual Institutional Activity (Hide Normal Flow)", value=True)

    if nse_files or bse_files:
        combined_frames = []
        if nse_files:
            df_nse = parse_udiff_bhavcopies(nse_files, filter_sensex_only=False)
            if not df_nse.empty:
                combined_frames.append(df_nse)
        if bse_files:
            df_bse = parse_udiff_bhavcopies(bse_files, filter_sensex_only=True)
            if not df_bse.empty:
                combined_frames.append(df_bse)

        if not combined_frames:
            st.warning("⚠️ Could not find valid NSE F&O or BSE SENSEX records in the uploaded files. Ensure they are UDiFF F&O Bhavcopy files.")
        else:
            df_all_bhav = pd.concat(combined_frames, ignore_index=True)
            df_inst, latest_bhav_dt, days_loaded = analyze_institutional_activity(df_all_bhav)

            if only_unusual and not df_inst.empty:
                df_inst = df_inst[df_inst["Institutional Footprint"] != "Normal Flow"]

            st.caption(f"Analyzed **{days_loaded} Trading Days** | Latest Bhavcopy Date: **{latest_bhav_dt}** | Unusual Setups Found: **{len(df_inst)}**")

            if not df_inst.empty:
                df_high_prob = df_inst[df_inst["High Prob"] == True].drop(columns=["High Prob"])
                df_display_all = df_inst.drop(columns=["High Prob"])

                silent_c = df_display_all["Institutional Footprint"].str.contains("Silent Accumulation").sum()
                long_c = df_display_all["Institutional Footprint"].str.contains("Long Buildup|Short Covering").sum()
                short_c = df_display_all["Institutional Footprint"].str.contains("Short Buildup|Long Unwinding").sum()

                ic1, ic2, ic3, ic4 = st.columns(4)
                ic1.metric("Total Institutional Alerts", len(df_display_all))
                ic2.metric("🎯 Tier-1 High-Prob Setups", len(df_high_prob))
                ic3.metric("🟢 Bullish Buildup", int(long_c))
                ic4.metric("🔴 Bearish Buildup", int(short_c))

                def style_inst(val):
                    s = str(val)
                    if "Silent Accumulation" in s or "Fut OHOL" in s:
                        return "background-color: #d500f9; color: white; font-weight: bold;"
                    elif "Long Buildup" in s or "Short Covering" in s:
                        return "color: #00e676; font-weight: bold;"
                    elif "Short Buildup" in s or "Long Unwinding" in s:
                        return "color: #ff5252; font-weight: bold;"
                    return ""

                if not df_high_prob.empty:
                    st.markdown(f"#### 🎯 High-Probability Institutional Footprints ({len(df_high_prob)} Tier-1 Setups — Auto-Cross-Tagged to Live Scanner)")
                    styled_hp = (
                        df_high_prob.style
                        .map(style_inst, subset=["Institutional Footprint"])
                        .map(lambda v: "color: #00e676; font-weight: bold;" if "Open=Low" in str(v) else ("color: #ff5252; font-weight: bold;" if "Open=High" in str(v) else ""), subset=["Fut OHOL"])
                    )
                    st.dataframe(styled_hp, use_container_width=True, hide_index=True)
                    st.divider()

                st.markdown("#### 📋 All Unusual Institutional Activity")
                styled_inst = (
                    df_display_all.style
                    .map(style_inst, subset=["Institutional Footprint"])
                    .map(lambda v: "color: #00e676; font-weight: bold;" if "Open=Low" in str(v) else ("color: #ff5252; font-weight: bold;" if "Open=High" in str(v) else ""), subset=["Fut OHOL"])
                )
                st.dataframe(styled_inst, use_container_width=True, hide_index=True, height=520)
                st.download_button(
                    f"📥 Download Institutional Activity ({latest_bhav_dt}).csv",
                    data=df_display_all.to_csv(index=False).encode("utf-8"),
                    file_name=f"institutional_bhavcopy_{latest_bhav_dt}.csv",
                    mime="text/csv"
                )

            else:
                st.info("No unusual institutional OI/Volume spikes found on the latest uploaded date (try unchecking 'Show Only Unusual Institutional Activity' to inspect all symbols).")
    else:
        st.info("Upload 5 to 25 days of NSE F&O Bhavcopy files on the left and/or BSE F&O Bhavcopy files on the right (supports bulk multi-select of `.csv` or `.zip` files).")

if auto_refresh and FYERS_TOKEN:
    time.sleep(60)
    st.rerun()
