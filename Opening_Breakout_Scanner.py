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
FILES = {"Monthly": os.path.join(DATA_DIR, "monthly.csv"), "Weekly": os.path.join(DATA_DIR, "weekly.csv"), "Intraday": os.path.join(DATA_DIR, "intraday.csv")}
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}
INDEX_UNDERLYING_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
}

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

def extract_csv_bytes(uploaded_file):
    if uploaded_file.name.lower().endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.lower().endswith(".csv"))
            with z.open(csv_name) as f:
                return pd.read_csv(f)
    return pd.read_csv(uploaded_file)

@st.cache_data(ttl=3600)
def get_all_fo_instruments():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    sources = [
        ("https://upstox.com", "NSE_FO", "NSE_cache.json"),
        ("https://upstox.com", "BSE_FO", "BSE_cache.json"),
    ]
    dfs = []
    for url, seg, local_path in sources:
        try:
            if not os.path.exists(local_path) or os.path.getsize(local_path) < 50000:
                resp = requests.get(url, headers=headers, stream=True, timeout=30)
                if resp.status_code == 200:
                    with open(local_path, "wb") as f_out:
                        with gzip.GzipFile(fileobj=resp.raw) as f_in:
                            shutil.copyfileobj(f_in, f_out)
            if os.path.exists(local_path) and os.path.getsize(local_path) > 50000:
                df_part = pd.read_json(local_path)
                df_part = df_part[(df_part["segment"] == seg) & (df_part["instrument_type"].isin(["CE", "PE"]))].copy()
                if seg == "BSE_FO":
                    df_part = df_part[df_part["underlying_symbol"] == "SENSEX"]
                df_part["expiry_dt"] = pd.to_datetime(df_part["expiry"], unit="ms").dt.normalize()
                dfs.append(df_part[["underlying_symbol", "strike_price", "instrument_type", "expiry_dt", "instrument_key"]])
        except Exception:
            continue
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def fetch_index_contracts_api(token):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    url = "https://upstox.com"
    rows = []
    last_err = ""
    for sym, u_key in INDEX_UNDERLYING_KEYS.items():
        try:
            resp = requests.get(url, headers=headers, params={"instrument_key": u_key}, timeout=10)
            if resp.status_code == 200 and resp.json().get("status") == "success":
                for item in resp.json().get("data", []):
                    if item.get("instrument_type") in ["CE", "PE"]:
                        rows.append({
                            "TckrSymb": sym,
                            "XpryDt": pd.to_datetime(item["expiry"]).normalize(),
                            "StrkPric": float(item["strike_price"]),
                            "OptnTp": item["instrument_type"],
                            "instrument_key": item["instrument_key"],
                        })
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            last_err = str(e)
    return pd.DataFrame(rows), last_err

def parse_bhavcopy_multi_strike(df_bhav, token, is_index=True):
    df_bhav = df_bhav.copy()
    if "FinInstrmNm" in df_bhav.columns and "TckrSymb" not in df_bhav.columns:
        df_bhav = df_bhav.rename(columns={"FinInstrmNm": "TckrSymb"})
    df_bhav["TckrSymb"] = df_bhav["TckrSymb"].astype(str).str.strip()

    futures = df_bhav[df_bhav["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    futures["XpryDt"] = pd.to_datetime(futures["XpryDt"])
    futures = futures.sort_values("XpryDt")
    if futures.empty:
        return pd.DataFrame(), "No STF/IDF futures rows found in Bhavcopy."

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

    if merged.empty:
        return pd.DataFrame(), "No near-ATM options left after strike distance filter."

    master_df = get_all_fo_instruments()
    if not master_df.empty:
        master_df["strike_price"] = master_df["strike_price"].astype(float)
        result = pd.merge(
            merged,
            master_df,
            left_on=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"],
            right_on=["underlying_symbol", "expiry_dt", "strike_price", "instrument_type"],
            how="inner",
        )
    elif is_index:
        contract_df, api_err = fetch_index_contracts_api(token)
        if contract_df.empty:
            return pd.DataFrame(), f"Upstox API returned 0 contracts ({api_err}). Check if Access Token is valid."
        result = pd.merge(merged, contract_df, on=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"], how="inner")
    else:
        return pd.DataFrame(), "Could not load NSE.json.gz instrument master for Stock Options. Switch to Index Options or check internet access."

    if result.empty:
        bhav_exps = sorted(merged["XpryDt"].dt.strftime("%Y-%m-%d").unique().tolist())[:3]
        return pd.DataFrame(), f"Expiry mismatch for Bhavcopy dates {bhav_exps}. Upload yesterday's F&O Bhavcopy."

    result = result.drop_duplicates(subset=["instrument_key"])
    result["Camarilla_R4"] = result["ClsPric"] + (result["HghPric"] - result["LwPric"]) * 1.1 / 2
    result["Positional_Trigger"] = result["ClsPric"] * 2
    return result[["TckrSymb", "XpryDt", "StrkPric", "OptnTp", "RefPrice", "ClsPric", "Camarilla_R4", "Positional_Trigger", "instrument_key"]], "OK"

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

df_i_raw = extract_csv_bytes(up_i) if up_i else (pd.read_csv(FILES["Intraday"]) if os.path.exists(FILES["Intraday"]) else None)
df_w_raw = extract_csv_bytes(up_w) if up_w else (pd.read_csv(FILES["Weekly"]) if os.path.exists(FILES["Weekly"]) else None)
