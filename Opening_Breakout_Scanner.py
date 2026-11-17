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
st.set_page_config(page_title="Opening Breakout Scanner", layout="wide")
st.title("🔥 Opening Breakout & Confluence Scanner")

DATA_DIR = "data"
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
NSE_JSON_PATH = "NSE.json"
NSE_GZ_PATH = "NSE.json.gz"
FILES = {"Monthly": os.path.join(DATA_DIR, "monthly.csv"), "Weekly": os.path.join(DATA_DIR, "weekly.csv"), "Intraday": os.path.join(DATA_DIR, "intraday.csv")}
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

def get_ist_now():
    return datetime.now(IST)

def load_saved_token():
    if "UPSTOX_ACCESS_TOKEN" in st.secrets and st.secrets["UPSTOX_ACCESS_TOKEN"].strip():
        return st.secrets["UPSTOX_ACCESS_TOKEN"].strip()
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == get_ist_now().strftime("%Y-%m-%d"):
                    return data.get("token", "").strip()
        except Exception:
            pass
    return ""

def extract_csv_bytes(uploaded_file):
    if uploaded_file.name.lower().endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.lower().endswith(".csv"))
            with z.open(csv_name) as f:
                return pd.read_csv(f)
    return pd.read_csv(uploaded_file)

@st.cache_data
def load_nse_json_exact():
    """Uses the exact load_nse_json() logic from your working app.py, restoring from NSE.json.gz if needed."""
    if (not os.path.exists(NSE_JSON_PATH) or os.path.getsize(NSE_JSON_PATH) < 50000) and os.path.exists(NSE_GZ_PATH):
        try:
            with gzip.open(NSE_GZ_PATH, "rb") as f_in:
                with open(NSE_JSON_PATH, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except Exception:
            pass

    if os.path.exists(NSE_JSON_PATH) and os.path.getsize(NSE_JSON_PATH) > 50000:
        try:
            df = pd.read_json(NSE_JSON_PATH)
            if "segment" in df.columns:
                df = df[df["segment"] == "NSE_FO"]
            df["expiry_dt"] = pd.to_datetime(df["expiry"], unit="ms").dt.normalize()
            return df
        except Exception as e:
            st.error(f"Error loading NSE.json: {e}")
    return pd.DataFrame()

def fetch_sensex_contracts(token):
    if not token:
        return pd.DataFrame()
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    try:
        resp = requests.get("https://upstox.com", headers=headers, params={"instrument_key": "BSE_INDEX|SENSEX"}, timeout=10)
        if resp.status_code == 200 and resp.json().get("status") == "success":
            rows = []
            for item in resp.json().get("data", []):
                if item.get("instrument_type") in ["CE", "PE"]:
                    rows.append({
                        "underlying_symbol": "SENSEX",
                        "expiry_dt": pd.to_datetime(item["expiry"]).normalize(),
                        "strike_price": float(item["strike_price"]),
                        "instrument_type": item["instrument_type"],
                        "instrument_key": item["instrument_key"],
                    })
            return pd.DataFrame(rows)
    except Exception:
        pass
    return pd.DataFrame()

def parse_bhavcopy_multi_strike(df_bhav, df_json, is_index=True):
    df_bhav = df_bhav.copy()
    if "FinInstrmNm" in df_bhav.columns and "TckrSymb" not in df_bhav.columns:
        df_bhav = df_bhav.rename(columns={"FinInstrmNm": "TckrSymb"})
    df_bhav["TckrSymb"] = df_bhav["TckrSymb"].astype(str).str.strip()

    futures = df_bhav[df_bhav["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    futures["XpryDt"] = pd.to_datetime(futures["XpryDt"])
    ist_now = get_ist_now()
    today = ist_now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    futures = futures[futures["XpryDt"] >= today].sort_values("XpryDt")
    if futures.empty:
        return pd.DataFrame(), "No future expiries found in uploaded Bhavcopy."

    near_fut = futures.groupby("TckrSymb", as_index=False).first()[["TckrSymb", "ClsPric", "XpryDt"]].rename(columns={"ClsPric": "RefPrice", "XpryDt": "TargetExpiry"})

    options = df_bhav[df_bhav["OptnTp"].isin(["CE", "PE"])].copy()
    options["XpryDt"] = pd.to_datetime(options["XpryDt"])
    options = options[options["TckrSymb"].isin(INDEX_SYMBOLS)] if is_index else options[~options["TckrSymb"].isin(INDEX_SYMBOLS)]
    max_dist_pct = 0.025 if is_index else 0.05

    merged = pd.merge(options, near_fut, on="TckrSymb")
    if not is_index:
        merged = merged[merged["XpryDt"] == merged["TargetExpiry"]]
    else:
        min_opt_exp = merged.groupby("TckrSymb")["XpryDt"].transform("min")
        merged = merged[merged["XpryDt"] == min_opt_exp]

    merged["DistPct"] = abs(merged["StrkPric"] - merged["RefPrice"]) / merged["RefPrice"]
    merged = merged[merged["DistPct"] <= max_dist_pct].copy()
    merged["XpryDt"] = merged["XpryDt"].dt.normalize()
    merged["StrkPric"] = merged["StrkPric"].astype(float)

    df_json = df_json.copy()
    df_json["strike_price"] = df_json["strike_price"].astype(float)
    result = pd.merge(
        merged,
        df_json,
        left_on=["TckrSymb", "StrkPric", "OptnTp", "XpryDt"],
        right_on=["underlying_symbol", "strike_price", "instrument_type", "expiry_dt"],
        how="inner",
    )

    if result.empty:
        return pd.DataFrame(), "No matching contracts found between Bhavcopy and NSE.json."

    result = result.drop_duplicates(subset=["instrument_key"])
    result["Camarilla_R4"] = result["ClsPric"] + (result["HghPric"] - result["LwPric"]) * 1.1 / 2
    result["Positional_Trigger"] = result["ClsPric"] * 2
    return result[["TckrSymb", "XpryDt", "StrkPric", "OptnTp", "RefPrice", "ClsPric", "Camarilla_R4", "Positional_Trigger", "instrument_key"]], "OK"

def fetch_ltp_v3(instrument_keys, token):
    if not token or not instrument_keys:
        return {}
    url = "https://upstox.com"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    batch_size = 50
    ltp_map = {}
    batches = [instrument_keys[i:i + batch_size] for i in range(0, len(instrument_keys), batch_size)]

    def fetch_batch(batch):
        try:
            resp = requests.get(url, headers=headers, params={"instrument_key": ",".join(batch)}, timeout=10)
            if resp.status_code == 200 and resp.json().get("status") == "success":
                return {d["instrument_token"]: d["last_price"] for d in resp.json().get("data", {}).values() if d.get("instrument_token") is not None}
        except Exception:
            pass
        return {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for res in executor.map(fetch_batch, batches):
            ltp_map.update(res)
    return ltp_map

with st.sidebar:
    st.header("Configuration")
    access_token = st.text_input("Upstox Access Token", value=load_saved_token(), type="password")
    st.markdown("---")
    st.header("Bhavcopy Files")
    up_i = st.file_uploader("Intraday / Prev Day Bhavcopy", type=["zip", "csv"], key="ob_i")
    up_w = st.file_uploader("Weekly Bhavcopy (Optional)", type=["zip", "csv"], key="ob_w")
    up_m = st.file_uploader("Monthly Bhavcopy (Optional)", type=["zip", "csv"], key="ob_m")

c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
with c1:
    segment = st.radio("Segment Focus", ["Index Options (NIFTY / BANKNIFTY / SENSEX)", "Stock Options (NSE F&O)"], horizontal=True)
with c2:
    trigger_mode = st.selectbox("Trigger Baseline", ["Camarilla R4 (Intraday)", "2x Previous Close (Positional)"])
with c3:
    require_confluence = st.checkbox("Require Weekly/Monthly Alignment", value=False)
with c4:
    refresh_btn = st.button("⚡ Refresh LTP", use_container_width=True)

df_json = load_nse_json_exact()
if "Index" in segment and access_token:
    sensex_df = fetch_sensex_contracts(access_token)
    if not sensex_df.empty:
        df_json = pd.concat([df_json, sensex_df], ignore_index=True)

df_i_raw = extract_csv_bytes(up_i) if up_i else (pd.read_csv(FILES["Intraday"]) if os.path.exists(FILES["Intraday"]) else None)
df_w_raw = extract_csv_bytes(up_w) if up_w else (pd.read_csv(FILES["Weekly"]) if os.path.exists(FILES["Weekly"]) else None)
df_m_raw = extract_csv_bytes(up_m) if up_m else (pd.read_csv(FILES["Monthly"]) if os.path.exists(FILES["Monthly"]) else None)

if df_json.empty:
    st.error("NSE.json / NSE.json.gz not found in repository.")
elif df_i_raw is None:
    st.info("Upload your Intraday / Previous Day Bhavcopy in the sidebar to begin.")
elif not access_token:
    st.warning("Enter your Upstox Access Token in the sidebar to begin.")
else:
    is_index = "Index" in segment
    daily_df, status_msg = parse_bhavcopy_multi_strike(df_i_raw, df_json, is_index=is_index)

    if daily_df.empty:
        st.warning(f"No matching contracts found: {status_msg}")
    else:
        daily_df["Daily_Trigger"] = daily_df["Camarilla_R4"] if "Camarilla" in trigger_mode else daily_df["Positional_Trigger"]
        if df_w_raw is not None:
            wk_df, _ = parse_bhavcopy_multi_strike(df_w_raw, df_json, is_index=is_index)
            if not wk_df.empty:
                wk_sub = wk_df[["instrument_key", "Positional_Trigger"]].rename(columns={"Positional_Trigger": "Weekly_Trigger"})
                daily_df = pd.merge(daily_df, wk_sub, on="instrument_key", how="left")
        if df_m_raw is not None:
            mo_df, _ = parse_bhavcopy_multi_strike(df_m_raw, df_json, is_index=is_index)
            if not mo_df.empty:
