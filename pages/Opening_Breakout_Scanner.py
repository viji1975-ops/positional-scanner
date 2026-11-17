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
BSE_JSON_PATH = "BSE.json"
FILES = {"Monthly": os.path.join(DATA_DIR, "monthly.csv"), "Weekly": os.path.join(DATA_DIR, "weekly.csv"), "Intraday": os.path.join(DATA_DIR, "intraday.csv")}
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

def get_ist_now():
    return datetime.now(IST)

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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=30)
        if resp.status_code == 200:
            with open(out_path, "wb") as f_out:
                with gzip.GzipFile(fileobj=resp.raw) as f_in:
                    shutil.copyfileobj(f_in, f_out)
            with open(out_path, "r", encoding="utf-8", errors="ignore") as check_f:
                first_char = check_f.read(5).lstrip()
                if first_char.startswith("[") or first_char.startswith("{"):
                    return True
            os.remove(out_path)
    except Exception:
        if os.path.exists(out_path):
            os.remove(out_path)
    return False

@st.cache_data(ttl=3600)
def load_instrument_masters():
    dfs = []
    for path, seg in [(NSE_JSON_PATH, "NSE_FO"), (BSE_JSON_PATH, "BSE_FO")]:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            try:
                df_part = pd.read_json(path)
                if "segment" in df_part.columns:
                    df_part = df_part[df_part["segment"] == seg]
                if seg == "BSE_FO" and "underlying_symbol" in df_part.columns:
                    df_part = df_part[df_part["underlying_symbol"] == "SENSEX"]
                df_part["expiry_dt"] = pd.to_datetime(df_part["expiry"], unit="ms").dt.normalize()
                dfs.append(df_part)
            except Exception:
                continue
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def extract_csv_bytes(uploaded_file):
    if uploaded_file.name.lower().endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.lower().endswith(".csv"))
            with z.open(csv_name) as f:
                return pd.read_csv(f)
    return pd.read_csv(uploaded_file)

def resolve_keys_via_search_api(merged_df, token):
    """Maps options to Upstox instrument_keys via v2/instruments/search when local JSON isn't present."""
    if not token or merged_df.empty:
        return pd.DataFrame()
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    url = "https://upstox.com"
    unique_pairs = merged_df[["TckrSymb", "XpryDt"]].drop_duplicates().head(60)
    mapping_rows = []
    for _, row in unique_pairs.iterrows():
        sym = str(row["TckrSymb"]).strip()
        exp_dt = pd.to_datetime(row["XpryDt"])
        exp_str = exp_dt.strftime("%Y-%m-%d")
        exch = "BSE" if sym == "SENSEX" else "NSE"
        try:
            resp = requests.get(url, headers=headers, params={"query": sym, "exchanges": exch, "segments": "FO", "expiry": exp_str, "records": 50}, timeout=8)
            if resp.status_code == 200 and resp.json().get("status") == "success":
                for item in resp.json().get("data", []):
                    u_sym = str(item.get("underlying_symbol") or item.get("asset_symbol") or item.get("name", "")).strip()
                    if u_sym == sym and item.get("instrument_type") in ["CE", "PE"]:
                        mapping_rows.append({"TckrSymb": sym, "XpryDt": exp_dt.normalize(), "StrkPric": float(item["strike_price"]), "OptnTp": item["instrument_type"], "instrument_key": item["instrument_key"]})
        except Exception:
            continue
    if not mapping_rows:
        return pd.DataFrame()
    map_df = pd.DataFrame(mapping_rows).drop_duplicates(subset=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"])
    return pd.merge(merged_df, map_df, on=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"], how="inner")

def parse_bhavcopy_multi_strike(df_bhav, df_json, token, is_index=True):
    if "FinInstrmNm" in df_bhav.columns and "TckrSymb" not in df_bhav.columns:
        df_bhav = df_bhav.rename(columns={"FinInstrmNm": "TckrSymb"})
    today = get_ist_now().replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    futures = df_bhav[df_bhav["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    futures["XpryDt"] = pd.to_datetime(futures["XpryDt"])
    futures = futures[futures["XpryDt"] >= today].sort_values("XpryDt")
    if futures.empty:
        return pd.DataFrame()
    near_fut = futures.groupby("TckrSymb", as_index=False).first()[["TckrSymb", "ClsPric", "XpryDt"]].rename(columns={"ClsPric": "RefPrice", "XpryDt": "TargetExpiry"})
    options = df_bhav[df_bhav["OptnTp"].isin(["CE", "PE"])].copy()
    options["XpryDt"] = pd.to_datetime(options["XpryDt"])
    options = options[options["TckrSymb"].isin(INDEX_SYMBOLS)] if is_index else options[~options["TckrSymb"].isin(INDEX_SYMBOLS)]
    max_dist_pct = 0.02 if is_index else 0.04
    merged = pd.merge(options, near_fut, on="TckrSymb")
    merged = merged[merged["XpryDt"] == merged["TargetExpiry"]]
    merged["DistPct"] = abs(merged["StrkPric"] - merged["RefPrice"]) / merged["RefPrice"]
    merged = merged[merged["DistPct"] <= max_dist_pct].copy()
    merged["XpryDt"] = merged["XpryDt"].dt.normalize()
    if not df_json.empty:
        result = pd.merge(merged, df_json, left_on=["TckrSymb", "StrkPric", "OptnTp", "XpryDt"], right_on=["underlying_symbol", "strike_price", "instrument_type", "expiry_dt"], how="inner")
    else:
        result = resolve_keys_via_search_api(merged, token)
    if result.empty:
        return pd.DataFrame()
    result["Camarilla_R4"] = result["ClsPric"] + (result["HghPric"] - result["LwPric"]) * 1.1 / 2
    result["Positional_Trigger"] = result["ClsPric"] * 2
    return result[["TckrSymb", "XpryDt", "StrkPric", "OptnTp", "RefPrice", "ClsPric", "Camarilla_R4", "Positional_Trigger", "instrument_key"]]

def fetch_ltp_v3(instrument_keys, token):
    if not token or not instrument_keys:
        return {}
    url = "https://upstox.com"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    ltp_map = {}
    batches = [instrument_keys[i:i + 50] for i in range(0, len(instrument_keys), 50)]
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
    st.header("Instrument Masters")
    if st.button("🔄 Update NSE & BSE (SENSEX) JSON", use_container_width=True):
        with st.spinner("Updating NSE.json and BSE.json..."):
            ok_nse = download_json_gz("https://upstox.com", NSE_JSON_PATH)
            ok_bse = download_json_gz("https://upstox.com", BSE_JSON_PATH)
            st.cache_data.clear()
            if ok_nse:
                st.success("NSE.json updated!")
            else:
                st.info("Using Upstox Search API automatically for NSE.")
            if ok_bse:
                st.success("BSE.json (SENSEX) updated!")
            else:
                st.info("Using Upstox Search API automatically for SENSEX.")
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

df_json = load_instrument_masters()
df_i_raw = extract_csv_bytes(up_i) if up_i else (pd.read_csv(FILES["Intraday"]) if os.path.exists(FILES["Intraday"]) else None)
