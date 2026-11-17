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

def fetch_stock_contracts_api(merged_df, token):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    url = "https://upstox.com"
    unique_syms = merged_df["TckrSymb"].drop_duplicates().head(40).tolist()
    rows = []
    last_err = ""
    for sym in unique_syms:
        try:
            resp = requests.get(url, headers=headers, params={"query": sym, "exchanges": "NSE", "segments": "FO", "records": 100}, timeout=8)
            if resp.status_code == 200 and resp.json().get("status") == "success":
                for item in resp.json().get("data", []):
                    tsym = str(item.get("trading_symbol", "")).strip()
                    if tsym.startswith(sym + " ") and item.get("instrument_type") in ["CE", "PE"]:
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

    contract_df, api_err = fetch_index_contracts_api(token) if is_index else fetch_stock_contracts_api(merged, token)
    if contract_df.empty:
        return pd.DataFrame(), f"Upstox API returned 0 contracts ({api_err}). Check if Access Token is valid."

    contract_df = contract_df.drop_duplicates(subset=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"])
    result = pd.merge(merged, contract_df, on=["TckrSymb", "XpryDt", "StrkPric", "OptnTp"], how="inner")
    if result.empty:
        bhav_exps = sorted(merged["XpryDt"].dt.strftime("%Y-%m-%d").unique().tolist())[:3]
        api_exps = sorted(contract_df["XpryDt"].dt.strftime("%Y-%m-%d").unique().tolist())[:3]
        return pd.DataFrame(), f"Expiry mismatch: Bhavcopy expiries {bhav_exps} vs Upstox live expiries {api_exps}. Upload the latest trading day's Bhavcopy."

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
df_m_raw = extract_csv_bytes(up_m) if up_m else (pd.read_csv(FILES["Monthly"]) if os.path.exists(FILES["Monthly"]) else None)

if df_i_raw is None:
    st.info("Upload your Intraday / Previous Day Bhavcopy in the sidebar to begin.")
elif not access_token:
    st.warning("Enter your Upstox Access Token in the sidebar to begin.")
else:
    is_index = "Index" in segment
    with st.spinner("Matching contracts & fetching live LTP..."):
        daily_df, status_msg = parse_bhavcopy_multi_strike(df_i_raw, access_token, is_index=is_index)
    if daily_df.empty:
        st.warning(f"No matching contracts found: {status_msg}")
    else:
        daily_df["Daily_Trigger"] = daily_df["Camarilla_R4"] if "Camarilla" in trigger_mode else daily_df["Positional_Trigger"]
        if df_w_raw is not None:
            wk_df, _ = parse_bhavcopy_multi_strike(df_w_raw, access_token, is_index=is_index)
            if not wk_df.empty:
                daily_df = pd.merge(daily_df, wk_df[["instrument_key", "Positional_Trigger"]].rename(columns={"Positional_Trigger": "Weekly_Trigger"}), on="instrument_key", how="left")
        if df_m_raw is not None:
            mo_df, _ = parse_bhavcopy_multi_strike(df_m_raw, access_token, is_index=is_index)
            if not mo_df.empty:
                daily_df = pd.merge(daily_df, mo_df[["instrument_key", "Positional_Trigger"]].rename(columns={"Positional_Trigger": "Monthly_Trigger"}), on="instrument_key", how="left")
        keys = daily_df["instrument_key"].dropna().unique().tolist()
        cache_id = f"v3_ltp_{segment}"
        if refresh_btn or cache_id not in st.session_state or not st.session_state[cache_id]:
            with st.spinner(f"Fetching live LTP for {len(keys)} contracts..."):
                st.session_state[cache_id] = fetch_ltp_v3(keys, access_token)
        ltp_map = st.session_state.get(cache_id, {})
        daily_df["ltp"] = daily_df["instrument_key"].map(ltp_map).fillna(0.0)
        st.caption(f"✅ Matched {len(keys)} contracts | Received {len(ltp_map)} live quotes from Upstox")
        daily_df["Change_%"] = daily_df.apply(lambda r: (r["ltp"] / r["Daily_Trigger"] * 100) if (r["Daily_Trigger"] > 0 and r["ltp"] > 0) else 0.0, axis=1)
        filtered = daily_df.copy()
        if require_confluence:
            if "Weekly_Trigger" in filtered.columns:
                filtered = filtered[filtered["ltp"] >= filtered["Weekly_Trigger"] * 0.9]
            if "Monthly_Trigger" in filtered.columns and not is_index:
                filtered = filtered[filtered["ltp"] >= filtered["Monthly_Trigger"] * 0.9]
        filtered = filtered.sort_values(by="Change_%", ascending=False)
        show_cols = ["TckrSymb", "StrkPric", "Daily_Trigger", "ltp", "Change_%"]
        if "Weekly_Trigger" in filtered.columns:
            show_cols.insert(3, "Weekly_Trigger")
        if "Monthly_Trigger" in filtered.columns:
            show_cols.insert(3, "Monthly_Trigger")
        def style_pct(val):
            if isinstance(val, (int, float)):
                if val >= 100:
                    return "background-color: darkgreen; color: white"
                elif val >= 90:
                    return "background-color: lightgreen; color: black"
            return ""
        fmt = {c: "{:.2f}" for c in show_cols if c not in ["TckrSymb", "Change_%"]}
        fmt["Change_%"] = "{:.2f}%"
        col_ce, col_pe = st.columns(2)
        with col_ce:
            st.subheader("Calls (CE)")
            st.dataframe(filtered[filtered["OptnTp"] == "CE"][show_cols].style.map(style_pct, subset=["Change_%"]).format(fmt), hide_index=True, use_container_width=True, height=900)
        with col_pe:
            st.subheader("Puts (PE)")
            st.dataframe(filtered[filtered["OptnTp"] == "PE"][show_cols].style.map(style_pct, subset=["Change_%"]).format(fmt), hide_index=True, use_container_width=True, height=900)

