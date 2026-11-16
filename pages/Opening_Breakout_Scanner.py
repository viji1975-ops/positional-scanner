import streamlit as st
import pandas as pd
import requests
import os
import json
import gzip
import shutil
import zipfile
import concurrent.futures
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.now(IST)

st.set_page_config(page_title="Opening Breakout Scanner", layout="wide")
st.title("🔥 Opening Breakout & Confluence Scanner")

DATA_DIR = "data"
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
NSE_JSON_PATH = "NSE.json"
BSE_JSON_PATH = "BSE.json"

FILES = {
    "Monthly": os.path.join(DATA_DIR, "monthly.csv"),
    "Weekly": os.path.join(DATA_DIR, "weekly.csv"),
    "Intraday": os.path.join(DATA_DIR, "intraday.csv"),
}

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}


def load_saved_token():
    if "UPSTOX_ACCESS_TOKEN" in st.secrets and st.secrets["UPSTOX_ACCESS_TOKEN"].strip():
        return st.secrets["UPSTOX_ACCESS_TOKEN"]
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == get_ist_now().strftime("%Y-%m-%d"):
                    return data.get("token", "")
        except Exception:
            pass
    return ""


def download_json_gz(url, out_path):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, stream=True, timeout=30)
    if resp.status_code == 200:
        with open(out_path, "wb") as f_out:
            with gzip.GzipFile(fileobj=resp.raw) as f_in:
                shutil.copyfileobj(f_in, f_out)
        return True
    return False


@st.cache_data(ttl=3600)
def load_instrument_masters():
    dfs = []
    if os.path.exists(NSE_JSON_PATH):
        df_nse = pd.read_json(NSE_JSON_PATH)
        if "segment" in df_nse.columns:
            df_nse = df_nse[df_nse["segment"] == "NSE_FO"]
        df_nse["expiry_dt"] = pd.to_datetime(df_nse["expiry"], unit="ms").dt.normalize()
        dfs.append(df_nse)

    if os.path.exists(BSE_JSON_PATH):
        df_bse = pd.read_json(BSE_JSON_PATH)
        if "segment" in df_bse.columns:
            df_bse = df_bse[(df_bse["segment"] == "BSE_FO") & (df_bse["underlying_symbol"] == "SENSEX")]
        df_bse["expiry_dt"] = pd.to_datetime(df_bse["expiry"], unit="ms").dt.normalize()
        dfs.append(df_bse)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def extract_csv_bytes(uploaded_file):
    if uploaded_file.name.lower().endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.lower().endswith(".csv"))
            with z.open(csv_name) as f:
                return pd.read_csv(f)
    return pd.read_csv(uploaded_file)


def parse_bhavcopy_multi_strike(df_bhav, df_json, is_index=True):
    """Extracts near-ATM option strikes (ATM to OTM-3 for Indices, ATM to OTM-1 for Stocks)."""
    if "FinInstrmNm" in df_bhav.columns and "TckrSymb" not in df_bhav.columns:
        df_bhav = df_bhav.rename(columns={"FinInstrmNm": "TckrSymb"})

    ist_now = get_ist_now()
    today = ist_now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)

    # Get Underlying Spot / Futures reference price
    futures = df_bhav[df_bhav["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    futures["XpryDt"] = pd.to_datetime(futures["XpryDt"])
    futures = futures[futures["XpryDt"] >= today].sort_values("XpryDt")
    if futures.empty:
        return pd.DataFrame()

    # Nearest expiry per symbol
    near_fut = futures.groupby("TckrSymb", as_index=False).first()[["TckrSymb", "ClsPric", "XpryDt"]]
    near_fut = near_fut.rename(columns={"ClsPric": "RefPrice", "XpryDt": "TargetExpiry"})

    options = df_bhav[df_bhav["OptnTp"].isin(["CE", "PE"])].copy()
    options["XpryDt"] = pd.to_datetime(options["XpryDt"])

    if is_index:
        options = options[options["TckrSymb"].isin(INDEX_SYMBOLS)]
        max_dist_pct = 0.02   # +/- 2% around spot/futures (ATM to OTM-3)
    else:
        options = options[~options["TckrSymb"].isin(INDEX_SYMBOLS)]
        max_dist_pct = 0.04   # +/- 4% around spot/futures (ATM to OTM-1)

    merged = pd.merge(options, near_fut, on="TckrSymb")
    merged = merged[merged["XpryDt"] == merged["TargetExpiry"]]

    # Filter strike distance from reference price
    merged["DistPct"] = abs(merged["StrkPric"] - merged["RefPrice"]) / merged["RefPrice"]
    merged = merged[merged["DistPct"] <= max_dist_pct].copy()
    merged["XpryDt"] = merged["XpryDt"].dt.normalize()

    # Exact merge logic from your working app.py
    result = pd.merge(
        merged,
        df_json,
        left_on=["TckrSymb", "StrkPric", "OptnTp", "XpryDt"],
        right_on=["underlying_symbol", "strike_price", "instrument_type", "expiry_dt"],
        how="inner",
    )

    if result.empty:
        return pd.DataFrame()

    # Camarilla R4 + Trigger calculation
    result["Camarilla_R4"] = result["ClsPric"] + (result["HghPric"] - result["LwPric"]) * 1.1 / 2
    result["Positional_Trigger"] = result["ClsPric"] * 2
    result["EOD_OI"] = pd.to_numeric(result.get("OpnIntrst", 0), errors="coerce").fillna(0)

    return result[[
        "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "RefPrice",
        "ClsPric", "Camarilla_R4", "Positional_Trigger", "EOD_OI", "instrument_key"
    ]]


def fetch_ltp_v3(instrument_keys, token):
    """Uses your exact working Upstox v3 LTP batch fetcher."""
    if not token or not instrument_keys:
        return {}

    url = "https://upstox.com"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    batch_size = 50
    ltp_map = {}
    batches = [instrument_keys[i:i + batch_size] for i in range(0, len(instrument_keys), batch_size)]

    def fetch_batch(batch):
        params = {"instrument_key": ",".join(batch)}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    out = {}
                    for _, details in data.get("data", {}).items():
                        inst_token = details.get("instrument_token")
                        last_price = details.get("last_price")
                        if inst_token is not None:
                            out[inst_token] = last_price
                    return out
        except Exception:
            pass
        return {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_batch, b) for b in batches]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                ltp_map.update(res)
    return ltp_map


# --- SIDEBAR ---
with st.sidebar:
    st.header("Configuration")
    saved_tok = load_saved_token()
    access_token = st.text_input("Upstox Access Token", value=saved_tok, type="password")

    st.markdown("---")
    st.header("Instrument Masters")
    if st.button("🔄 Update NSE & BSE (SENSEX) JSON", use_container_width=True):
        with st.spinner("Updating NSE.json and BSE.json..."):
            ok_nse = download_json_gz("https://upstox.com", NSE_JSON_PATH)
            ok_bse = download_json_gz("https://upstox.com", BSE_JSON_PATH)
            st.cache_data.clear()
            if ok_nse:
                st.success("NSE.json updated!")
            if ok_bse:
                st.success("BSE.json (SENSEX) updated!")

    st.markdown("---")
    st.header("Bhavcopy Files")
    st.caption("Automatically uses files uploaded in main app, or upload new ones below:")
    up_i = st.file_uploader("Intraday / Prev Day Bhavcopy", type=["zip", "csv"], key="ob_i")
    up_w = st.file_uploader("Weekly Bhavcopy (Optional)", type=["zip", "csv"], key="ob_w")
    up_m = st.file_uploader("Monthly Bhavcopy (Optional)", type=["zip", "csv"], key="ob_m")

# --- MAIN CONTROLS ---
c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
with c1:
    segment = st.radio(
        "Segment Focus",
        ["Index Options (NIFTY / BANKNIFTY / SENSEX)", "Stock Options (NSE F&O)"],
        horizontal=True,
    )
with c2:
    trigger_mode = st.selectbox("Trigger Baseline", ["Camarilla R4 (Intraday)", "2x Previous Close (Positional)"])
with c3:
    require_confluence = st.checkbox("Require Weekly/Monthly Alignment", value=False)
with c4:
    refresh_btn = st.button("⚡ Refresh LTP", use_container_width=True)

df_json = load_instrument_masters()

if df_json.empty:
    st.error("NSE.json not found. Click '🔄 Update NSE & BSE (SENSEX) JSON' in the sidebar.")
else:
    # Load from uploader or existing saved files in data/
    df_i_raw = extract_csv_bytes(up_i) if up_i else (pd.read_csv(FILES["Intraday"]) if os.path.exists(FILES["Intraday"]) else None)
    df_w_raw = extract_csv_bytes(up_w) if up_w else (pd.read_csv(FILES["Weekly"]) if os.path.exists(FILES["Weekly"]) else None)
    df_m_raw = extract_csv_bytes(up_m) if up_m else (pd.read_csv(FILES["Monthly"]) if os.path.exists(FILES["Monthly"]) else None)

    if df_i_raw is None:
        st.info("Upload your Intraday / Previous Day Bhavcopy in the sidebar (or in the main app page) to begin.")
    else:
        is_index = "Index" in segment
        daily_df = parse_bhavcopy_multi_strike(df_i_raw, df_json, is_index=is_index)

        if daily_df.empty:
            st.warning("No matching contracts found for this segment. If scanning SENSEX, click '🔄 Update NSE & BSE (SENSEX) JSON' in the sidebar.")
        else:
