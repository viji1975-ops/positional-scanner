import os
import io
import time
import zipfile
import hashlib
import requests
import pandas as pd
import streamlit as st
from urllib.parse import urlparse, parse_qs, quote
from datetime import datetime, timedelta

st.set_page_config(page_title="Fyers NSE Indices & BSE SENSEX Institutional + OHOL Scanner", layout="wide")

# --- Sidebar: Fyers API v3 Login & Index Filters ---
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
        f"&response_type=code&state=idxscanner"
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
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        try:
            resp = requests.post(
                validate_url,
                headers=headers,
                json={"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code},
                timeout=12
            )
            if resp.status_code != 200 or not resp.text.strip():
                st.sidebar.error(f"Fyers Auth Error (HTTP {resp.status_code}): Click Step 1 again for a fresh auth_code.")
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
st.sidebar.header("⚙️ Index & Option Filters")

selected_indices = st.sidebar.multiselect(
    "Indices to Monitor",
    ("NIFTY 50", "SENSEX", "BANK NIFTY", "FIN NIFTY", "MIDCAP NIFTY", "BANKEX"),
    default=("NIFTY 50", "SENSEX", "BANK NIFTY", "FIN NIFTY", "MIDCAP NIFTY", "BANKEX")
)
strike_range = st.sidebar.slider("Option Strike Scan Depth (± Strikes from ATM)", min_value=2, max_value=8, value=5)
opt_pattern_filter = st.sidebar.selectbox(
    "Option Strike Filter",
    ("All Option OHOL (Open=Low & Open=High)", "Option Open=Low Only (Buying Momentum)", "Option Open=High Only (Writing Decay)")
)
orb_timeframe = st.sidebar.radio(
    "ORB Confirmation Window",
    ("5-Min ORB (9:15–9:20 AM)", "15-Min ORB (9:15–9:30 AM)")
)
only_orb_confirmed = st.sidebar.checkbox("✅ Show Only ORB Confirmed Setups", value=False)
only_dual_locked = st.sidebar.checkbox("🔥 Show Only Dual-Strike Locked (CE O=L + PE O=H)", value=False)
auto_refresh = st.sidebar.checkbox("⚡ Fast Auto-Refresh Every 30s", value=False)

INDEX_CONFIG = {
    "NIFTY 50": {"fyers": "NSE:NIFTY50-INDEX", "step": 50, "lot": 75, "csv_sym": "NIFTY"},
    "SENSEX": {"fyers": "BSE:SENSEX-INDEX", "step": 100, "lot": 20, "csv_sym": "SENSEX"},
    "BANK NIFTY": {"fyers": "NSE:NIFTYBANK-INDEX", "step": 100, "lot": 30, "csv_sym": "BANKNIFTY"},
    "FIN NIFTY": {"fyers": "NSE:FINNIFTY-INDEX", "step": 50, "lot": 65, "csv_sym": "FINNIFTY"},
    "MIDCAP NIFTY": {"fyers": "NSE:MIDCPNIFTY-INDEX", "step": 25, "lot": 120, "csv_sym": "MIDCPNIFTY"},
    "BANKEX": {"fyers": "BSE:BANKEX-INDEX", "step": 100, "lot": 30, "csv_sym": "BANKEX"},
}

def is_exact_ohol(open_p, high_p, low_p):
    o, h, l = round(float(open_p), 2), round(float(high_p), 2), round(float(low_p), 2)
    if o <= 0 or h == l:
        return False, False
    return (o == h), (o == l)

@st.cache_data(ttl=3600, show_spinner=False)
def get_index_option_chains_v3(auth_token, active_indices, depth):
    """Fetches exact nearest-expiry ±N option symbols and expiry dates directly from Fyers Option Chain API v3."""
    if not auth_token or len(auth_token.split(":", 1).pop()) < 50:
        return {}, {}

    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    url_oc = "https://" + "api-t1." + "fyers.in" + "/data/options-chain-v3"

    opt_meta = {}
    expiry_dates = {}

    for idx_name in active_indices:
        cfg = INDEX_CONFIG[idx_name]
        f_sym = cfg["fyers"]
        step = cfg["step"]
        try:
            res = requests.get(url_oc, headers=headers, params={"symbol": f_sym, "strikecount": max(depth + 2, 8)}, timeout=10).json()
            if res.get("s") != "ok":
                continue
            data = res.get("data", {})
            exp_list = data.get("expiryData", ())
            if exp_list:
                expiry_dates[cfg["csv_sym"]] = exp_list.__getitem__(0).get("date", "")

            chains = data.get("optionsChain", ())
            spot_item = next((c for c in chains if c.get("option_type") == ""), None)
            spot_ltp = float(spot_item.get("ltp", 0)) if spot_item else 0.0
            atm = round(spot_ltp / step) * step if spot_ltp > 0 else 0

            for item in chains:
                o_type = item.get("option_type", "")
                o_sym = item.get("symbol", "")
                st_val = float(item.get("strike_price", 0))
                if o_type in ("CE", "PE") and o_sym and st_val > 0:
                    offset = int(round((st_val - atm) / step)) if atm > 0 else 0
                    if abs(offset) <= depth:
                        opt_meta[o_sym] = {
                            "idx_name": idx_name,
                            "csv_sym": cfg["csv_sym"],
                            "strike": int(st_val),
                            "opt_type": o_type,
                            "offset": offset,
                            "expiry": expiry_dates.get(cfg["csv_sym"], "")
                        }
        except Exception:
            continue

    return opt_meta, expiry_dates

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

@st.cache_data(ttl=900, show_spinner=False)
def fetch_fyers_daily_atr(fyers_symbol, auth_token):
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
    url = "https://" + "api-t1." + "fyers.in" + "/data/history"
    headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    params = {"symbol": fyers_symbol, "resolution": "D", "date_format": "1", "range_from": from_date, "range_to": to_date, "cont_flag": "1"}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=8)
        payload = res.json()
        candles = payload.get("candles", ())
        if payload.get("s") == "ok" and len(candles) >= 15:
            df = pd.DataFrame(candles, columns=("epoch", "open", "high", "low", "close", "volume"))
            df["prev_close"] = df["close"].shift(1)
            df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
            return round(float(df["tr"].tail(14).mean()), 1), float(df.iloc[-2]["high"]), float(df.iloc[-2]["low"])
    except Exception:
        pass
    return 150.0, 0.0, 0.0
def parse_index_bhavcopies(uploaded_files, allowed_syms):
    """Reads multiple NSE or BSE UDiFF F&O Bhavcopy (.csv or .zip) files filtered to Indices."""
    frames = []
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
            df = df[df["TckrSymb"].isin(allowed_syms)]
            if not df.empty:
                frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)

def analyze_index_institutional(df_bhav):
    """Detects abnormal Index Futures OI buildup, Option Writing Walls, and saves cross-tags."""
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

    st.session_state["idx_bhav_df"] = df_bhav

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

        last_r, prev_r = grp.iloc[-1], grp.iloc[-2]
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
        if abs(price_chg_pct) <= 0.5 and oi_chg > 0 and oi_spike_ratio >= 1.8:
            footprint, score, is_high_prob = "🕵️ Silent Accumulation (Flat Index + Huge OI)", 5, True
        elif price_chg_pct > 0.4 and oi_chg > 0 and (oi_spike_ratio >= 1.5 or vol_spike_ratio >= 1.5):
            footprint, score, is_high_prob = "🟢 Institutional Long Buildup", 4, True
        elif price_chg_pct < -0.4 and oi_chg > 0 and (oi_spike_ratio >= 1.5 or vol_spike_ratio >= 1.5):
            footprint, score, is_high_prob = "🔴 Institutional Short Buildup", 4, True
        elif (f_ol or f_oh) and oi_spike_ratio >= 1.5:
            footprint, score, is_high_prob = f"🎯 Fut OHOL + {oi_spike_ratio}x OI Spike", 4, True
        elif price_chg_pct > 0.6 and oi_chg < 0:
            footprint, score = "⚡ Aggressive Short Covering", 2
        elif price_chg_pct < -0.6 and oi_chg < 0:
            footprint, score = "⚠️ Long Unwinding", 2
        else:
            footprint, score = "Normal Flow", 1

        if footprint != "Normal Flow":
            footprint_lookup[sym] = {"badge": f"{footprint} ({oi_spike_ratio}x OI)", "is_high_prob": is_high_prob}

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
            "Index": sym,
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

    st.session_state["idx_bhav_footprints"] = footprint_lookup
    df_out = pd.DataFrame(results)
    if not df_out.empty:
        df_out = df_out.sort_values(by=["_score", "_oi_spike"], ascending=[False, False]).drop(columns=["_score", "_oi_spike"])
    return df_out, latest_dt, len(all_dates)
def check_idx_bhavcopy_option_alignment(idx_name, atm_strike, is_oh, replay_date_str):
    """Checks ±5 strike CE/PE O=L/O=H from uploaded Bhavcopies on historical replay dates."""
    df_bhav = st.session_state.get("idx_bhav_df")
    if df_bhav is None or df_bhav.empty:
        return "Upload Bhavcopy for Expiry"

    cfg = INDEX_CONFIG[idx_name]
    csv_sym = cfg["csv_sym"]
    step = cfg["step"]

    day_opts = df_bhav[
        (df_bhav["TradDt"] == replay_date_str)
        & (df_bhav["TckrSymb"] == csv_sym)
        & (df_bhav["FinInstrmTp"].isin(("IDO", "STO")))
        & (df_bhav["XpryDt"] >= replay_date_str)
    ]
    if day_opts.empty:
        return "No Bhavcopy Data for Date"

    nearest_exp = day_opts["XpryDt"].min()
    exp_opts = day_opts[day_opts["XpryDt"] == nearest_exp]

    triple_strikes, primary_ol, opposite_oh = [], [], []
    offsets = sorted(range(-5, 6), key=lambda o: abs(o))

    for offset in offsets:
        st_val = int(round(atm_strike + (offset * step)))
        ce_rows = exp_opts[(exp_opts["StrkPric"].round(0) == st_val) & (exp_opts["OptnTp"] == "CE")]
        pe_rows = exp_opts[(exp_opts["StrkPric"].round(0) == st_val) & (exp_opts["OptnTp"] == "PE")]
        if ce_rows.empty or pe_rows.empty:
            continue

        ce_r, pe_r = ce_rows.iloc.__getitem__(0), pe_rows.iloc.__getitem__(0)
        ce_oh, ce_ol = is_exact_ohol(ce_r["OpnPric"], ce_r["HghPric"], ce_r["LwPric"])
        pe_oh, pe_ol = is_exact_ohol(pe_r["OpnPric"], pe_r["HghPric"], pe_r["LwPric"])

        if not is_oh:
            if ce_ol and pe_oh: triple_strikes.append(str(st_val))
            if ce_ol: primary_ol.append(f"{st_val} CE")
            if pe_oh: opposite_oh.append(f"{st_val} PE")
        else:
            if pe_ol and ce_oh: triple_strikes.append(str(st_val))
            if pe_ol: primary_ol.append(f"{st_val} PE")
            if ce_oh: opposite_oh.append(f"{st_val} CE")

        if triple_strikes:
            break

    exp_tag = f"[Exp: {nearest_exp}]"
    if triple_strikes:
        return f"🔥 TRIPLE @ {triple_strikes.__getitem__(0)} {exp_tag}"
    elif primary_ol and opposite_oh:
        return f"🔥 SPLIT ({primary_ol.__getitem__(0)} O=L | {opposite_oh.__getitem__(0)} O=H) {exp_tag}"
    elif primary_ol:
        return f"⚡ {primary_ol.__getitem__(0)} O=L {exp_tag}"
    elif opposite_oh:
        return f"⚡ {opposite_oh.__getitem__(0)} O=H {exp_tag}"
    return f"Spot Only {exp_tag}"

def scan_indices_and_options(auth_token, active_indices, depth, orb_mins, idx_lots):
    if not auth_token or len(auth_token.split(":", 1).pop()) < 50 or not active_indices:
        return {}, pd.DataFrame(), pd.DataFrame(), "Log in to Fyers in the left sidebar", {}

    headers = {"Authorization": auth_token, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    url_quotes = "https://" + "api-t1." + "fyers.in" + "/data/quotes"
    today_str = datetime.now().strftime("%Y-%m-%d")
    bhav_map = st.session_state.get("idx_bhav_footprints", {})

    idx_fyers_syms = ",".join(INDEX_CONFIG[k]["fyers"] for k in active_indices)
    fyers_to_name = {INDEX_CONFIG[k]["fyers"]: k for k in active_indices}
    spot_quotes = {}

    try:
        res = requests.get(url_quotes, headers=headers, params={"symbols": idx_fyers_syms}, timeout=10)
        if res.status_code in (401, 403):
            return {}, pd.DataFrame(), pd.DataFrame(), "Token expired (HTTP 401)", {}
        payload = res.json()
        if payload.get("s") != "ok":
            return {}, pd.DataFrame(), pd.DataFrame(), payload.get("message", "Fyers API error"), {}

        for item in payload.get("d", ()):
            idx_name = fyers_to_name.get(item.get("n", ""))
            v = item.get("v", {})
            if idx_name and float(v.get("open_price", 0)) > 0:
                spot_quotes[idx_name] = {
                    "open": float(v.get("open_price", 0)),
                    "high": float(v.get("high_price", 0)),
                    "low": float(v.get("low_price", 0)),
                    "ltp": float(v.get("lp", 0)),
                    "chp": float(v.get("chp", 0)),
                }
    except Exception as e:
        return {}, pd.DataFrame(), pd.DataFrame(), str(e), {}

    if not spot_quotes:
        return {}, pd.DataFrame(), pd.DataFrame(), "Market Closed / Pre-Open", {}

    opt_meta, expiry_dates = get_index_option_chains_v3(auth_token, tuple(active_indices), depth)
    unique_opt_syms = sorted(opt_meta.keys())

    opt_quotes = {}
    for i in range(0, len(unique_opt_syms), 50):
        batch = unique_opt_syms[i:i + 50]
        try:
            r_opt = requests.get(url_quotes, headers=headers, params={"symbols": ",".join(batch)}, timeout=10).json()
            if r_opt.get("s") == "ok":
                for item in r_opt.get("d", ()):
                    v = item.get("v", {})
                    if float(v.get("open_price", 0)) > 0:
                        opt_quotes[item.get("n", "")] = {
                            "open": float(v.get("open_price", 0)),
                            "high": float(v.get("high_price", 0)),
                            "low": float(v.get("low_price", 0)),
                            "ltp": float(v.get("lp", 0)),
                            "vol": float(v.get("volume", 0)),
                            "atp": float(v.get("atp", 0)),
                        }
        except Exception:
            continue

    strike_states = {}
    for o_sym, oq in opt_quotes.items():
        meta = opt_meta[o_sym]
        oh, ol = is_exact_ohol(oq["open"], oq["high"], oq["low"])
        strike_states[(meta["idx_name"], meta["strike"], meta["opt_type"])] = (oh, ol)

    spot_rows = []
    for idx_name, sq in spot_quotes.items():
        is_oh, is_ol = is_exact_ohol(sq["open"], sq["high"], sq["low"])
        if not (is_oh or is_ol):
            continue

        cfg = INDEX_CONFIG[idx_name]
        f_sym = cfg["fyers"]
        atr_14, pdh, pdl = fetch_fyers_daily_atr(f_sym, auth_token)
        orb = fetch_fyers_orb(f_sym, today_str, orb_mins, auth_token)

        orb_ok = False
        if orb:
            lvl = orb["orb_low"] if is_oh else orb["orb_high"]
            orb_ok = (sq["ltp"] < lvl) if is_oh else (sq["ltp"] > lvl)
            orb_txt = f"✅ {orb_mins}m {'Broken (<' if is_oh else 'Breakout (>'}{lvl:.1f})" if orb_ok else f"⏳ Inside ({'>' if is_oh else '<'}{lvl:.1f})"
        else:
            orb_txt = "⏳ Pending ORB"

        if only_orb_confirmed and not orb_ok:
            continue

        step = cfg["step"]
        atm = int(round(sq["ltp"] / step) * step)
        itm = (atm + step) if is_oh else (atm - step)
        suffix = "PE" if is_oh else "CE"
        risk_u = atr_14 * 0.5
        t1 = round(sq["open"] - risk_u, 1) if is_oh else round(sq["open"] + risk_u, 1)
        t2 = round(sq["open"] - risk_u * 2, 1) if is_oh else round(sq["open"] + risk_u * 2, 1)
        lvl_tag = "Above PDH 🟢" if sq["ltp"] > pdh else ("Below PDL 🔴" if sq["ltp"] < pdl else "Inside Prev Day")
        bhav_badge = bhav_map.get(cfg["csv_sym"], {}).get("badge", "—")

        spot_rows.append({
            "Index": idx_name,
            "Spot Pattern": f"Open=High ({sq['open']:.2f})" if is_oh else f"Open=Low ({sq['open']:.2f})",
            "🏦 Bhavcopy Signal": bhav_badge,
            "ORB Confirm": orb_txt,
            "Spot LTP": f"{sq['ltp']:.2f}",
            "ATM | 1-ITM Option": f"{atm} {suffix} | {itm} {suffix}",
            "Lot Size": idx_lots.get(idx_name, cfg["lot"]),
            "Spot Tgt (1:1|1:2)": f"{t1} | {t2}",
            "PDH/PDL": lvl_tag,
            "_orb_ok": orb_ok
        })

    df_spot = pd.DataFrame(spot_rows)
    if not df_spot.empty:
        df_spot = df_spot.sort_values(by=["_orb_ok"], ascending=[False]).drop(columns=["_orb_ok"])

    opt_rows = []
    for o_sym, oq in opt_quotes.items():
        oh, ol = is_exact_ohol(oq["open"], oq["high"], oq["low"])
        if not (oh or ol):
            continue
        if "Open=Low Only" in opt_pattern_filter and not ol:
            continue
        if "Open=High Only" in opt_pattern_filter and not oh:
            continue

        meta = opt_meta[o_sym]
        idx_name = meta["idx_name"]
        st_val = meta["strike"]
        opt_type = meta["opt_type"]
        opp_type = "PE" if opt_type == "CE" else "CE"
        opp_oh, opp_ol = strike_states.get((idx_name, st_val, opp_type), (False, False))

        if ol and opp_oh:
            lock_badge, rank = f"🔥 DUAL LOCKED ({st_val} {opp_type} is O=H)", 3
        elif oh and opp_ol:
            lock_badge, rank = f"🔥 DUAL LOCKED ({st_val} {opp_type} is O=L)", 3
        else:
            lock_badge, rank = "Single Strike OHOL", 1

        if only_dual_locked and rank < 3:
            continue

        orb = fetch_fyers_orb(o_sym, today_str, orb_mins, auth_token)
        orb_ok = False
        if orb:
            if ol:
                lvl = orb["orb_high"]
                orb_ok = oq["ltp"] > lvl
                orb_txt = f"✅ {orb_mins}m Breakout (>{lvl:.1f})" if orb_ok else f"⏳ Inside (<{lvl:.1f})"
            else:
                lvl = orb["orb_low"]
                orb_ok = oq["ltp"] < lvl
                orb_txt = f"✅ {orb_mins}m Broken (<{lvl:.1f})" if orb_ok else f"⏳ Inside (>{lvl:.1f})"
        else:
            orb_txt = "⏳ Pending ORB"

        if only_orb_confirmed and not orb_ok:
            continue

        atp = oq["atp"]
        if atp > 0:
            vwap_txt = (f"✅ Above VWAP ({atp:.1f})" if oq["ltp"] > atp else f"⚠️ Below VWAP ({atp:.1f})") if ol else (f"✅ Below VWAP ({atp:.1f})" if oq["ltp"] < atp else f"⚠️ Above VWAP ({atp:.1f})")
        else:
            vwap_txt = "—"

        moneyness = "ATM" if meta["offset"] == 0 else f"{meta['offset']:+d} Strike"
        action_bias = "🟢 BUY Option Momentum" if ol else "🔴 WRITE / Decay Option"
        t1_opt = round(oq["open"] * 1.25, 1) if ol else round(oq["open"] * 0.70, 1)
        t2_opt = round(oq["open"] * 1.50, 1) if ol else round(oq["open"] * 0.45, 1)
        bhav_badge = bhav_map.get(meta["csv_sym"], {}).get("badge", "—")

        opt_rows.append({
            "Index": idx_name,
            "Option Contract": f"{st_val} {opt_type} ({moneyness})",
            "Expiry": meta["expiry"],
            "Option Pattern": f"Open=Low ({oq['open']:.2f})" if ol else f"Open=High ({oq['open']:.2f})",
            "Dual-Strike Confirmation": lock_badge,
            "🏦 Bhavcopy Signal": bhav_badge,
            "Option ORB Confirm": orb_txt,
            "VWAP Align": vwap_txt,
            "Option LTP (₹)": f"{oq['ltp']:.2f}",
            "Bias": action_bias,
            "Opt Tgt (1:1|1:2)": f"{t1_opt} | {t2_opt}",
            "Lot Size": idx_lots.get(idx_name, INDEX_CONFIG[idx_name]["lot"]),
            "_rank": rank,
            "_orb_ok": orb_ok,
            "_abs_off": abs(meta["offset"])
        })

    df_opts = pd.DataFrame(opt_rows)
    if not df_opts.empty:
        df_opts = df_opts.sort_values(by=["_rank", "_orb_ok", "_abs_off"], ascending=[False, False, True]).drop(columns=["_rank", "_orb_ok", "_abs_off"])

    return spot_quotes, df_spot, df_opts, f"100% Fyers Live Feed ({len(unique_opt_syms)} Option Strikes Scanned)", expiry_dates
def run_index_morning_replay(active_indices, replay_date_str, orb_minutes, replay_cutoff, auth_token, idx_lots):
    """Replays NSE Indices & BSE SENSEX as of 9:20 AM, 9:30 AM, or Full EOD."""
    candles_for_orb = 1 if orb_minutes == 5 else 3
    cutoff_bars = 1 if "09:20" in replay_cutoff else (3 if "09:30" in replay_cutoff else 75)
    rows = []
    progress = st.progress(0, text=f"Replaying {replay_date_str} as of {replay_cutoff}...")

    for i, idx_name in enumerate(active_indices):
        progress.progress((i + 1) / len(active_indices), text=f"Replaying {idx_name}...")
        cfg = INDEX_CONFIG[idx_name]
        f_sym = cfg["fyers"]
        step = cfg["step"]

        url = "https://" + "api-t1." + "fyers.in" + "/data/history"
        headers = {"Authorization": auth_token, "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
        end_dt = datetime.strptime(replay_date_str, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=45)
        try:
            res = requests.get(url, headers=headers, params={"symbol": f_sym, "resolution": "D", "date_format": "1", "range_from": start_dt.strftime("%Y-%m-%d"), "range_to": replay_date_str, "cont_flag": "1"}, timeout=10).json()
            candles = res.get("candles", ())
            if res.get("s") != "ok" or len(candles) < 15:
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
            atr_14 = round(float(hist_prior["tr"].tail(14).mean()), 1)
            pdh, pdl = float(prev_r["high"]), float(prev_r["low"])

            day_5m = fetch_fyers_5m_day(f_sym, replay_date_str, auth_token)
            if day_5m is None or len(day_5m) < cutoff_bars:
                continue

            morning_slice = day_5m.iloc[:cutoff_bars]
            after_slice = day_5m.iloc[cutoff_bars:]

            open_p = float(morning_slice["open"].iloc.__getitem__(0))
            snap_high = float(morning_slice["high"].max())
            snap_low = float(morning_slice["low"].min())
            snap_ltp = float(morning_slice["close"].iloc[-1])

            is_oh, is_ol = is_exact_ohol(open_p, snap_high, snap_low)
            if not (is_oh or is_ol):
                continue

            risk_u = atr_14 * 0.5
            t1 = round(open_p - risk_u, 1) if is_oh else round(open_p + risk_u, 1)
            t2 = round(open_p - risk_u * 2, 1) if is_oh else round(open_p + risk_u * 2, 1)

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

            full_high = snap_high if after_slice.empty else max(snap_high, float(after_slice["high"].max()))
            full_low = snap_low if after_slice.empty else min(snap_low, float(after_slice["low"].min()))
            final_close = snap_ltp if after_slice.empty else float(after_slice["close"].iloc[-1])

            if is_oh:
                outcome = "❌ Reversed / SL Hit" if full_high > open_p else ("🎯 1:2 Target Hit" if full_low <= t2 else ("✅ 1:1 Target Hit" if full_low <= t1 else ("🟢 Held Below Open" if final_close < open_p else "⏱️ Flat at Open")))
            else:
                outcome = "❌ Reversed / SL Hit" if full_low < open_p else ("🎯 1:2 Target Hit" if full_high >= t2 else ("✅ 1:1 Target Hit" if full_high >= t1 else ("🟢 Held Above Open" if final_close > open_p else "⏱️ Flat at Open")))

            atm = int(round(snap_ltp / step) * step)
            itm = (atm + step) if is_oh else (atm - step)
            suffix = "PE" if is_oh else "CE"
            opt_align_txt = check_idx_bhavcopy_option_alignment(idx_name, atm, is_oh, replay_date_str)
            lvl_tag = "Above PDH 🟢" if snap_ltp > pdh else ("Below PDL 🔴" if snap_ltp < pdl else "Inside Prev Day")

            rows.append({
                "Index": idx_name,
                "Pattern": f"Open=High ({open_p:.2f})" if is_oh else f"Open=Low ({open_p:.2f})",
                "Option O=L/O=H Align": opt_align_txt,
                f"ORB @ {replay_cutoff[:8]}": orb_text,
                "Later Day Outcome": outcome,
                f"Price @ {replay_cutoff[:8]}": f"{snap_ltp:.2f}",
                "ATM | 1-ITM Option": f"{atm} {suffix} | {itm} {suffix}",
                "Lot Size": idx_lots.get(idx_name, cfg["lot"]),
                "Spot Tgt (1:1|1:2)": f"{t1} | {t2}",
                "PDH/PDL": lvl_tag
            })
        except Exception:
            continue

    progress.empty()
    return pd.DataFrame(rows)
