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
st.set_page_config(page_title="Opening Breakout & Positional Scanner", layout="wide")

st.markdown("<style>.block-container{padding-top:1rem !important;padding-bottom:1rem !important;} h1{font-size:1.8rem !important;margin-bottom:0.2rem !important;} h3{font-size:1.05rem !important;} div[data-testid='stDataFrame']{font-weight:600 !important;}</style>", unsafe_allow_html=True)

DATA_DIR = "data"
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
NSE_JSON_PATH = "NSE.json"
NSE_GZ_PATH = "NSE.json.gz"
BSE_JSON_PATH = "BSE.json"
BSE_GZ_PATH = "BSE.json.gz"
FILES = {"Monthly": os.path.join(DATA_DIR, "monthly.csv"), "Weekly": os.path.join(DATA_DIR, "weekly.csv"), "Intraday": os.path.join(DATA_DIR, "intraday.csv")}

WEEKLY_INDICES = {"NIFTY", "SENSEX"}
MONTHLY_INDICES = {"BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
ALL_INDICES = WEEKLY_INDICES | MONTHLY_INDICES

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
    sources = [(NSE_GZ_PATH, True, "NSE_FO"), (NSE_JSON_PATH, False, "NSE_FO"), (BSE_GZ_PATH, True, "BSE_FO"), (BSE_JSON_PATH, False, "BSE_FO")]
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
                        rows.append({"underlying_symbol": u_sym, "strike_price": float(item["strike_price"]), "instrument_type": item["instrument_type"], "expiry": item["expiry"], "instrument_key": item["instrument_key"]})
                loaded_segs.add(target_seg)
            except Exception as e:
                st.error(f"Error reading {path}: {e}")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["expiry_dt"] = pd.to_datetime(df["expiry"], unit="ms").dt.normalize()
    return df

def parse_bhavcopy_by_group(df_bhav, df_json, group_mode, is_intraday=False):
    if df_bhav is None or df_json.empty:
        return pd.DataFrame(), None
    df_bhav = df_bhav.copy()
    if "FinInstrmNm" in df_bhav.columns and "TckrSymb" not in df_bhav.columns:
        df_bhav = df_bhav.rename(columns={"FinInstrmNm": "TckrSymb"})
    df_bhav["TckrSymb"] = df_bhav["TckrSymb"].astype(str).str.strip()
    futures = df_bhav[df_bhav["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    futures["XpryDt"] = pd.to_datetime(futures["XpryDt"])
    today = get_ist_now().replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    futures = futures[futures["XpryDt"] >= today].sort_values("XpryDt")
    if futures.empty:
        return pd.DataFrame(), None
    near_fut = futures.groupby("TckrSymb", as_index=False).first()[["TckrSymb", "ClsPric", "XpryDt"]].rename(columns={"ClsPric": "RefPrice", "XpryDt": "MonthlyExpiry"})
    options = df_bhav[df_bhav["OptnTp"].isin(["CE", "PE"])].copy()
    options["XpryDt"] = pd.to_datetime(options["XpryDt"])
    if group_mode == "WEEKLY_IDX":
        options = options[options["TckrSymb"].isin(WEEKLY_INDICES)]
        max_dist_pct = 0.025
    elif group_mode == "MONTHLY_IDX":
        options = options[options["TckrSymb"].isin(MONTHLY_INDICES)]
        max_dist_pct = 0.03
    else:
        options = options[~options["TckrSymb"].isin(ALL_INDICES)]
        max_dist_pct = 0.05
    merged = pd.merge(options, near_fut, on="TckrSymb")
    if group_mode == "WEEKLY_IDX":
        min_opt_exp = merged.groupby("TckrSymb")["XpryDt"].transform("min")
        merged = merged[merged["XpryDt"] == min_opt_exp]
    else:
        merged = merged[merged["XpryDt"] == merged["MonthlyExpiry"]]
    merged["DistPct"] = abs(merged["StrkPric"] - merged["RefPrice"]) / merged["RefPrice"]
    merged = merged[merged["DistPct"] <= max_dist_pct].copy()
    merged["XpryDt"] = merged["XpryDt"].dt.normalize()
    merged["StrkPric"] = merged["StrkPric"].astype(float)
    df_json = df_json.copy()
    df_json["strike_price"] = df_json["strike_price"].astype(float)
    result = pd.merge(merged, df_json, left_on=["TckrSymb", "StrkPric", "OptnTp", "XpryDt"], right_on=["underlying_symbol", "strike_price", "instrument_type", "expiry_dt"], how="inner")
    if result.empty:
        return pd.DataFrame(), None
    result = result.drop_duplicates(subset=["instrument_key"]).copy()
    if is_intraday:
        result["Trigger"] = result["ClsPric"] + (result["HghPric"] - result["LwPric"]) * 1.1 / 2
    else:
        result["Trigger"] = result["ClsPric"] * 2
    exp_label = ", ".join(sorted(result["XpryDt"].dt.strftime("%d-%b-%Y").unique().tolist()))
    out = result[["TckrSymb", "StrkPric", "OptnTp", "Trigger", "instrument_key"]].rename(columns={"TckrSymb": "Symbol", "StrkPric": "StrikePrice"})
    return out, exp_label

def fetch_ltp_v3(instrument_keys, token):
    if not token or not instrument_keys:
        return {}
    host = ".".join(["api", "upstox", "com"])
    url = f"https://{host}/v3/market-quote/ltp"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    ltp_map = {}
    batches = [instrument_keys[i:i + 50] for i in range(0, len(instrument_keys), 50)]
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
            time.sleep(0.12)
        except Exception:
            pass
    return ltp_map

def render_scanner_tables(df_tab, exp_label, ltp_map, confluence_keys=None):
    if df_tab.empty:
        st.info("Upload the corresponding Bhavcopy file in the sidebar to view this timeframe.")
        return
    df_view = df_tab.copy()
    if confluence_keys is not None:
        df_view = df_view[df_view["instrument_key"].isin(confluence_keys)]
    df_view["ltp"] = df_view["instrument_key"].map(ltp_map).fillna(0.0)
    df_view["change %"] = df_view.apply(lambda r: (r["ltp"] / r["Trigger"] * 100) if (r["Trigger"] > 0 and r["ltp"] > 0) else 0.0, axis=1)
    df_view = df_view.sort_values(by="change %", ascending=False)
    if exp_label:
        st.info(f"📅 Displaying Expiry: **{exp_label}**")
    st.caption(f"Last Updated: {get_ist_now().strftime('%H:%M:%S')} IST")
    def style_pct(val):
        if isinstance(val, (int, float)):
            if val >= 100:
                return "background-color: darkgreen; color: white"
            elif val >= 90:
                return "background-color: lightgreen; color: black"
        return ""
    show_cols = ["Symbol", "StrikePrice", "Trigger", "ltp", "change %"]
    fmt = {"StrikePrice": "{:.2f}", "Trigger": "{:.2f}", "ltp": "{:.2f}", "change %": "{:.2f}%"}
    col_ce, col_pe = st.columns(2)
    with col_ce:
        st.subheader("Calls (CE)")
        ce_df = df_view[df_view["OptnTp"] == "CE"][show_cols]
        st.dataframe(ce_df.style.map(style_pct, subset=["change %"]).format(fmt), hide_index=True, use_container_width=True, height=850)
    with col_pe:
        st.subheader("Puts (PE)")
        pe_df = df_view[df_view["OptnTp"] == "PE"][show_cols]
        st.dataframe(pe_df.style.map(style_pct, subset=["change %"]).format(fmt), hide_index=True, use_container_width=True, height=850)

with st.sidebar:
    st.header("Configuration")
    access_token = st.text_input("Upstox Access Token", value=load_saved_token(), type="password")
    st.markdown("---")
    st.markdown("---")
    st.header("Instrument Master (NSE/BSE)")
    up_json = st.file_uploader("Upload NSE.json.gz / BSE.json.gz", type=["json", "gz"], key="ob_json")
    if up_json is not None:
        save_uploaded_instrument_file(up_json)
        st.success(f"Loaded {up_json.name}!")
    st.markdown("---")
    st.header("Bhavcopy Files")
    up_m = st.file_uploader("1. Monthly Bhavcopy", type=["zip", "csv"], key="ob_m")
    up_w = st.file_uploader("2. Weekly Bhavcopy", type=["zip", "csv"], key="ob_w")
    up_i = st.file_uploader("3. Intraday / Prev Day Bhavcopy", type=["zip", "csv"], key="ob_i")

st.title("🔥 Opening Breakout & Positional Scanner")

c_seg, c_conf, c_ref = st.columns([3, 1.3, 0.9])
with c_seg:
    segment_choice = st.radio("Select Segment", ["NIFTY / SENSEX (Weekly Expiry)", "BANKNIFTY / FINNIFTY / MIDCPNIFTY (Monthly Expiry)", "Stock Options (NSE F&O Monthly)"], horizontal=True, label_visibility="collapsed")
with c_conf:
    confluence_only = st.checkbox("Multi-Timeframe Confluence Only", value=False)
with c_ref:
    refresh_btn = st.button("⚡ Refresh LTP", use_container_width=True)

df_json = load_nse_json_fast()
df_m_raw = extract_csv_bytes(up_m) if up_m else (pd.read_csv(FILES["Monthly"]) if os.path.exists(FILES["Monthly"]) else None)
df_w_raw = extract_csv_bytes(up_w) if up_w else (pd.read_csv(FILES["Weekly"]) if os.path.exists(FILES["Weekly"]) else None)
df_i_raw = extract_csv_bytes(up_i) if up_i else (pd.read_csv(FILES["Intraday"]) if os.path.exists(FILES["Intraday"]) else None)

if df_json.empty:
    st.warning("Upload NSE.json.gz (and BSE.json.gz for SENSEX) in the sidebar to begin.")
elif not access_token:
    st.warning("Enter your Upstox Access Token in the sidebar to begin.")
else:
    if "NIFTY / SENSEX" in segment_choice:
        group_mode = "WEEKLY_IDX"
    elif "BANKNIFTY" in segment_choice:
        group_mode = "MONTHLY_IDX"
    else:
        group_mode = "STOCKS"

    df_m_parsed, exp_m = parse_bhavcopy_by_group(df_m_raw, df_json, group_mode, is_intraday=False) if group_mode != "WEEKLY_IDX" else (pd.DataFrame(), None)
    df_w_parsed, exp_w = parse_bhavcopy_by_group(df_w_raw, df_json, group_mode, is_intraday=False)
    df_i_parsed, exp_i = parse_bhavcopy_by_group(df_i_raw, df_json, group_mode, is_intraday=True)

    all_keys = set()
    for d in [df_m_parsed, df_w_parsed, df_i_parsed]:
        if not d.empty:
            all_keys.update(d["instrument_key"].dropna().unique().tolist())

    cache_id = f"ltp_v3_{group_mode}"
    if refresh_btn or cache_id not in st.session_state or not st.session_state[cache_id]:
        if all_keys:
            with st.spinner(f"Fetching live quotes for {len(all_keys)} contracts..."):
                st.session_state[cache_id] = fetch_ltp_v3(list(all_keys), access_token)

    ltp_map = st.session_state.get(cache_id, {})

    confluence_keys = None
    if confluence_only and ltp_map:
        valid_sets = []
        for d in ([df_w_parsed, df_i_parsed] if group_mode == "WEEKLY_IDX" else [df_m_parsed, df_w_parsed, df_i_parsed]):
            if not d.empty:
                temp = d.copy()
                temp["ltp"] = temp["instrument_key"].map(ltp_map).fillna(0.0)
                valid_sets.append(set(temp[temp["ltp"] >= temp["Trigger"] * 0.9]["instrument_key"]))
        if valid_sets:
            confluence_keys = set.intersection(*valid_sets)

    if group_mode == "WEEKLY_IDX":
        tab_w, tab_i = st.tabs(["Weekly", "Intraday"])
        with tab_w:
            render_scanner_tables(df_w_parsed, exp_w, ltp_map, confluence_keys)
        with tab_i:
            render_scanner_tables(df_i_parsed, exp_i, ltp_map, confluence_keys)
    else:
        tab_m, tab_w, tab_i = st.tabs(["Monthly", "Weekly", "Intraday"])
        with tab_m:
            render_scanner_tables(df_m_parsed, exp_m, ltp_map, confluence_keys)
        with tab_w:
            render_scanner_tables(df_w_parsed, exp_w, ltp_map, confluence_keys)
        with tab_i:
            render_scanner_tables(df_i_parsed, exp_i, ltp_map, confluence_keys)
