import streamlit as st
import pandas as pd
import requests
import os
import json
import gzip
import time
import zipfile
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
st.set_page_config(page_title="Opening Breakout Scanner", layout="wide")
st.title("🔥 Opening Breakout & Confluence Scanner")

DATA_DIR = "data"
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
NSE_JSON_PATH = "NSE.json"
NSE_GZ_PATH = "NSE.json.gz"
BSE_JSON_PATH = "BSE.json"
BSE_GZ_PATH = "BSE.json.gz"
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

def save_uploaded_instrument_file(uploaded_file):
    if uploaded_file is None:
        return
    fname = uploaded_file.name.lower()
    if "bse" in fname:
        target = BSE_GZ_PATH if fname.endswith(".gz") else BSE_JSON_PATH
    else:
        target = NSE_GZ_PATH if fname.endswith(".gz") else NSE_JSON_PATH
    with open(target, "wb") as f_out:
        f_out.write(uploaded_file.getbuffer())
    st.cache_data.clear()

@st.cache_data
def load_nse_json_fast():
    rows = []
    sources = [
        (NSE_GZ_PATH, True, "NSE_FO"),
        (NSE_JSON_PATH, False, "NSE_FO"),
        (BSE_GZ_PATH, True, "BSE_FO"),
        (BSE_JSON_PATH, False, "BSE_FO"),
    ]
    loaded_segs = set()
    for path, is_gz, target_seg in sources:
        if target_seg in loaded_segs:
            continue
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            try:
                if is_gz:
                    with gzip.open(path, "rt", encoding="utf-8") as f:
                        raw_list = json.load(f)
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        raw_list = json.load(f)

                for item in raw_list:
                    if item.get("segment") == target_seg and item.get("instrument_type") in ("CE", "PE"):
                        u_sym = str(item.get("underlying_symbol") or item.get("asset_symbol") or item.get("name", "")).strip()
                        if target_seg == "BSE_FO" and u_sym != "SENSEX":
                            continue
                        rows.append({
                            "underlying_symbol": u_sym,
                            "strike_price": float(item["strike_price"]),
                            "instrument_type": item["instrument_type"],
                            "expiry": item["expiry"],
                            "instrument_key": item["instrument_key"],
                        })
                loaded_segs.add(target_seg)
            except Exception as e:
                st.error(f"Error reading {path}: {e}")

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["expiry_dt"] = pd.to_datetime(df["expiry"], unit="ms").dt.normalize()
    return df

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
        return pd.DataFrame(), "No future expiries (>= today) found in uploaded Bhavcopy."

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
    url = "https://" + "://upstox.com" + "/v3/market-quote/ltp"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    ltp_map = {}
    batches = [instrument_keys[i:i + 50] for i in range(0, len(instrument_keys), 50)]
    last_error = None

    for batch in batches:
        try:
            resp = requests.get(url, headers=headers, params={"instrument_key": ",".join(batch)}, timeout=15)
            body = resp.text.strip() if resp.text else ""
            if resp.status_code == 200 and body.startswith("{"):
                data = json.loads(body)
                if data.get("status") == "success":
                    for k, d in data.get("data", {}).items():
                        price = float(d.get("last_price") or 0.0)
                        if d.get("instrument_token"):
                            ltp_map[d["instrument_token"]] = price
                        ltp_map[k] = price
                else:
                    last_error = f"API Error: {data}"
            else:
                last_error = f"HTTP {resp.status_code} | Body: {body[:120] or 'EMPTY'} | Key: {batch}"
            time.sleep(0.15)
        except Exception as e:
            last_error = f"Exception: {e}"

    if not ltp_map and last_error:
        st.error(last_error)
    return ltp_map

with st.sidebar:
    st.header("Configuration")
    access_token = st.text_input("Upstox Access Token", value=load_saved_token(), type="password")
    st.markdown("---")
    st.header("Instrument Master (NSE/BSE)")
    up_json = st.file_uploader("Upload NSE.json.gz / BSE.json.gz", type=["json", "gz"], key="ob_json")
    if up_json is not None:
        save_uploaded_instrument_file(up_json)
        st.success(f"Loaded {up_json.name}!")
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

df_json = load_nse_json_fast()
df_i_raw = extract_csv_bytes(up_i) if up_i else (pd.read_csv(FILES["Intraday"]) if os.path.exists(FILES["Intraday"]) else None)
df_w_raw = extract_csv_bytes(up_w) if up_w else (pd.read_csv(FILES["Weekly"]) if os.path.exists(FILES["Weekly"]) else None)
df_m_raw = extract_csv_bytes(up_m) if up_m else (pd.read_csv(FILES["Monthly"]) if os.path.exists(FILES["Monthly"]) else None)

if df_json.empty:
    st.warning("Upload NSE.json.gz (and optionally BSE.json.gz) in the sidebar under 'Instrument Master (NSE/BSE)' to begin.")
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
                mo_sub = mo_df[["instrument_key", "Positional_Trigger"]].rename(columns={"Positional_Trigger": "Monthly_Trigger"})
                daily_df = pd.merge(daily_df, mo_sub, on="instrument_key", how="left")

        keys = daily_df["instrument_key"].dropna().unique().tolist()
        cache_id = f"v3_ltp_{segment}"
        if refresh_btn or cache_id not in st.session_state or not st.session_state[cache_id]:
            with st.spinner(f"Fetching live LTP for {len(keys)} contracts..."):
                st.session_state[cache_id] = fetch_ltp_v3(keys, access_token)
        ltp_map = st.session_state.get(cache_id, {})
        daily_df["ltp"] = daily_df["instrument_key"].map(ltp_map).fillna(0.0)
        st.success(f"✅ Matched {len(keys)} contracts | Received {len(ltp_map)} live quotes from Upstox")

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

