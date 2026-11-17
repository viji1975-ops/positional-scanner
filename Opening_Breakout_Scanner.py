import streamlit as st
import pandas as pd
import requests
import os
import json
import zipfile
import concurrent.futures
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
st.set_page_config(page_title="Opening Breakout Scanner", layout="wide")
st.title("🔥 Opening Breakout & Confluence Scanner")

DATA_DIR = "data"
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
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

@st.cache_data(ttl=3600)
def load_instrument_masters():
    dfs = []
    for path, seg in [("NSE.json", "NSE_FO"), ("NSE.json.gz", "NSE_FO"), ("BSE.json", "BSE_FO"), ("BSE.json.gz", "BSE_FO")]:
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            try:
                df_part = pd.read_json(path, compression="gzip") if path.endswith(".gz") else pd.read_json(path)
                if "segment" in df_part.columns:
                    df_part = df_part[df_part["segment"] == seg]
                if seg == "BSE_FO" and "underlying_symbol" in df_part.columns:
                    df_part = df_part[df_part["underlying_symbol"] == "SENSEX"]
                df_part["expiry_dt"] = pd.to_datetime(df_part["expiry"], unit="ms").dt.normalize()
                dfs.append(df_part)
            except Exception:
                continue
    return pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["instrument_key"]) if dfs else pd.DataFrame()

def extract_csv_bytes(uploaded_file):
    if uploaded_file.name.lower().endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.lower().endswith(".csv"))
            with z.open(csv_name) as f:
                return pd.read_csv(f)
    return pd.read_csv(uploaded_file)

def resolve_keys_via_search_api(merged_df, token):
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
            resp = requests.get(url, headers=headers, params={"query": sym, "exchanges": exch, "segments": "FO", "expiry": exp_str, "records": 100}, timeout=8)
            if resp.status_code == 200 and resp.json().get("status") == "success":
                for item in resp.json().get("data", []):
                    tsym = str(item.get("trading_symbol", "")).strip()
                    u_sym = str(item.get("underlying_symbol") or item.get("asset_symbol") or item.get("name", "")).strip()
                    if (u_sym == sym or tsym.startswith(sym + " ")) and item.get("instrument_type") in ["CE", "PE"]:
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
    merged["StrkPric"] = merged["StrkPric"].astype(float)
    result = pd.DataFrame()
    if not df_json.empty:
        df_json = df_json.copy()
        df_json["strike_price"] = df_json["strike_price"].astype(float)
        result = pd.merge(merged, df_json, left_on=["TckrSymb", "StrkPric", "OptnTp", "XpryDt"], right_on=["underlying_symbol", "strike_price", "instrument_type", "expiry_dt"], how="inner")
    need_api = result.empty or (is_index and "SENSEX" in merged["TckrSymb"].values and "SENSEX" not in result["TckrSymb"].values)
    if need_api:
        api_res = resolve_keys_via_search_api(merged, token)
        if not api_res.empty:
            result = pd.concat([result, api_res], ignore_index=True).drop_duplicates(subset=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"])
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
df_w_raw = extract_csv_bytes(up_w) if up_w else (pd.read_csv(FILES["Weekly"]) if os.path.exists(FILES["Weekly"]) else None)
df_m_raw = extract_csv_bytes(up_m) if up_m else (pd.read_csv(FILES["Monthly"]) if os.path.exists(FILES["Monthly"]) else None)

if df_i_raw is None:
    st.info("Upload your Intraday / Previous Day Bhavcopy in the sidebar to begin.")
elif not access_token:
    st.warning("Enter your Upstox Access Token in the sidebar to begin.")
else:
    is_index = "Index" in segment
    with st.spinner("Matching contracts & fetching live LTP..."):
        daily_df = parse_bhavcopy_multi_strike(df_i_raw, df_json, access_token, is_index=is_index)
    if daily_df.empty:
        st.warning("No matching contracts found. Make sure your Bhavcopy file is an NSE/BSE F&O Bhavcopy with future expiry dates.")
    else:
        daily_df["Daily_Trigger"] = daily_df["Camarilla_R4"] if "Camarilla" in trigger_mode else daily_df["Positional_Trigger"]
               if df_w_raw is not None:
            wk_df = parse_bhavcopy_multi_strike(df_w_raw, df_json, access_token, is_index=is_index)
            if not wk_df.empty:
                daily_df = pd.merge(daily_df, wk_df[["instrument_key", "Positional_Trigger"]].rename(columns={"Positional_Trigger": "Weekly_Trigger"}), on="instrument_key", how="left")
        if df_m_raw is not None:
            mo_df = parse_bhavcopy_multi_strike(df_m_raw, df_json, access_token, is_index=is_index)
            if not mo_df.empty:
                daily_df = pd.merge(daily_df, mo_df[["instrument_key", "Positional_Trigger"]].rename(columns={"Positional_Trigger": "Monthly_Trigger"}), on="instrument_key", how="left")

