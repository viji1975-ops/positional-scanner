import streamlit as st
import pandas as pd
import numpy as np
import requests
import zipfile
import gzip
import io

st.set_page_config(page_title="Opening Breakout Scanner", layout="wide")
st.title("🔥 Opening Breakout & Confluence Scanner")

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

# --- HELPER FUNCTIONS ---
def load_bhavcopy_zip(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return None
    if uploaded_file.name.endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_files = [f for f in z.namelist() if f.endswith(".csv")]
            with z.open(csv_files[0]) as f:
                df = pd.read_csv(f)
    else:
        df = pd.read_csv(uploaded_file)

    # Normalize BSE column names if SENSEX BSE Bhavcopy is uploaded
    if "FinInstrmNm" in df.columns and "TckrSymb" not in df.columns:
        df.rename(columns={"FinInstrmNm": "TckrSymb"}, inplace=True)

    df = df[df["OptnTp"].isin(["CE", "PE"])].copy()
    df["key"] = (
        df["TckrSymb"].astype(str).str.strip() + "_" +
        df["XpryDt"].astype(str).str.strip() + "_" +
        df["StrkPric"].astype(float).astype(str) + "_" +
        df["OptnTp"].astype(str).str.strip()
    )
    df["Trigger"] = pd.to_numeric(df["ClsPric"], errors="coerce")
    df["EOD_OI"] = pd.to_numeric(df["OpnIntrst"], errors="coerce")
    df["Spot_Ref"] = pd.to_numeric(df.get("UndrlygPric", 0), errors="coerce")
    return df[["key", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "Trigger", "EOD_OI", "Spot_Ref"]]


def download_upstox_instruments_df(access_token: str) -> pd.DataFrame:
    """Fetches Upstox instrument master reliably via Upstox CDN or API."""
    urls = [
        "https://upstox.com",
        "https://upstox.com"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {access_token}"
    }
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                raw = resp.content
                if raw[:2] == b"\x1f\x8b":
                    text = gzip.decompress(raw).decode("utf-8")
                else:
                    text = raw.decode("utf-8")
                if text.lstrip().startswith("[") or text.lstrip().startswith("{"):
                    return pd.read_json(io.StringIO(text))
        except Exception:
            continue
    raise RuntimeError("Unable to download Upstox Instrument JSON. Please verify your Access Token or try again.")


@st.cache_data(ttl=3600)
def get_upstox_instrument_map(access_token: str) -> dict:
    df = download_upstox_instruments_df(access_token)
    
    # Keep NSE_FO and BSE_FO (for SENSEX)
    fo_df = df[df["segment"].isin(["NSE_FO", "BSE_FO"])].copy()
    fo_df = fo_df[fo_df["instrument_type"].isin(["CE", "PE"])].copy()
    
    fo_df["expiry_dt"] = pd.to_datetime(fo_df["expiry"], unit="ms").dt.strftime("%Y-%m-%d")
    fo_df["key"] = (
        fo_df["name"].astype(str).str.strip() + "_" +
        fo_df["expiry_dt"] + "_" +
        fo_df["strike_price"].astype(float).astype(str) + "_" +
        fo_df["instrument_type"].astype(str).str.strip()
    )
    return dict(zip(fo_df["key"], fo_df["instrument_key"]))


def fetch_live_quotes(access_token: str, key_to_inst: dict, target_keys: list) -> pd.DataFrame:
    inst_to_key = {v: k for k, v in key_to_inst.items() if k in set(target_keys)}
    inst_keys = list(inst_to_key.keys())
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    url = "https://upstox.com"
    records = []

    for i in range(0, len(inst_keys), 500):
        batch = ",".join(inst_keys[i:i+500])
        resp = requests.get(url, headers=headers, params={"instrument_key": batch}).json()
        if resp.get("status") == "success":
            for inst_key, data in resp["data"].items():
                depth = data.get("depth", {})
                buy_list = depth.get("buy", [])
                sell_list = depth.get("sell", [])
                best_bid = buy_list[0].get("price", 0) if buy_list else 0
                best_ask = sell_list[0].get("price", 0) if sell_list else 0
                records.append({
                    "key": inst_to_key.get(inst_key),
                    "ltp": data.get("last_price", 0),
                    "volume": data.get("volume", 0),
                    "live_oi": data.get("oi", 0),
                    "bid": best_bid,
                    "ask": best_ask
                })
    return pd.DataFrame(records)


# --- SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.header("Configuration")
    access_token = st.text_input("Upstox Access Token", type="password")
    
    st.header("Upload Bhavcopy Files")
    daily_file = st.file_uploader("1. Intraday / Previous Day Bhavcopy", type=["csv", "zip"])
    weekly_file = st.file_uploader("2. Weekly Bhavcopy (Optional)", type=["csv", "zip"])
    monthly_file = st.file_uploader("3. Monthly Bhavcopy (Optional)", type=["csv", "zip"])

# --- MAIN UI CONTROLS ---
col1, col2, col3 = st.columns(3)
with col1:
    segment = st.radio(
        "Segment Focus",
        ["Index Options (NIFTY / BANKNIFTY / SENSEX)", "Stock Options (NSE F&O)"],
        horizontal=True
    )
with col2:
    require_confluence = st.checkbox("Require Multi-Timeframe Confluence (Weekly + Monthly)", value=True)
with col3:
    refresh_btn = st.button("⚡ Refresh Live Quotes", use_container_width=True)

if daily_file and access_token:
    daily_df = load_bhavcopy_zip(daily_file)
    weekly_df = load_bhavcopy_zip(weekly_file)
    monthly_df = load_bhavcopy_zip(monthly_file)

    is_index = "Index" in segment
    if is_index:
        sub_df = daily_df[daily_df["TckrSymb"].isin(INDEX_SYMBOLS)].copy()
        max_dist, min_vol, max_spread = 0.02, 5000, 0.015
    else:
        sub_df = daily_df[~daily_df["TckrSymb"].isin(INDEX_SYMBOLS)].copy()
        max_dist, min_vol, max_spread = 0.05, 300, 0.03

    # Pre-filter by Strike Distance before calling Upstox API to save quota & speed up refresh
    if (sub_df["Spot_Ref"] > 0).any():
        sub_df["Dist_Pct"] = abs(sub_df["StrkPric"] - sub_df["Spot_Ref"]) / sub_df["Spot_Ref"]
        sub_df = sub_df[sub_df["Dist_Pct"] <= max_dist]

    if refresh_btn or "live_quotes" not in st.session_state:
        with st.spinner("Fetching live Upstox quotes..."):
            inst_map = get_upstox_instrument_map(access_token)
            st.session_state["live_quotes"] = fetch_live_quotes(access_token, inst_map, sub_df["key"].tolist())

    live_df = st.session_state.get("live_quotes", pd.DataFrame())

    if not live_df.empty:
        merged = pd.merge(sub_df, live_df, on="key", how="inner")
        merged.rename(columns={"Trigger": "Daily_Trigger"}, inplace=True)

        merged["Spread_Pct"] = (merged["ask"] - merged["bid"]) / merged["ltp"].replace(0, np.nan)
        merged = merged[
            (merged["volume"] >= min_vol) &
            (merged["Spread_Pct"] <= max_spread) &
            (merged["live_oi"] > merged["EOD_OI"]) &
            (merged["ltp"] > merged["Daily_Trigger"])
        ]

        if weekly_df is not None:
            wk = weekly_df[["key", "Trigger"]].rename(columns={"Trigger": "Weekly_Trigger"})
            merged = pd.merge(merged, wk, on="key", how="left")
            if require_confluence:
                merged = merged[merged["ltp"] > merged["Weekly_Trigger"]]

        if monthly_df is not None and not is_index:
            mo = monthly_df[["key", "Trigger"]].rename(columns={"Trigger": "Monthly_Trigger"})
            merged = pd.merge(merged, mo, on="key", how="left")
            if require_confluence:
                merged = merged[merged["ltp"] > merged["Monthly_Trigger"]]

        merged["Change_%"] = ((merged["ltp"] - merged["Daily_Trigger"]) / merged["Daily_Trigger"]) * 100
        merged = merged.sort_values(by="Change_%", ascending=False)

        display_cols = ["TckrSymb", "XpryDt", "StrkPric", "Daily_Trigger", "ltp", "Change_%", "volume", "live_oi"]
        if "Weekly_Trigger" in merged.columns:
            display_cols.insert(4, "Weekly_Trigger")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Calls (CE)")
            ce_df = merged[merged["OptnTp"] == "CE"]
            st.dataframe(ce_df[display_cols].style.format({"Change_%": "{:.2f}%"}), use_container_width=True)
        with c2:
            st.subheader("Puts (PE)")
            pe_df = merged[merged["OptnTp"] == "PE"]
            st.dataframe(pe_df[display_cols].style.format({"Change_%": "{:.2f}%"}), use_container_width=True)
    else:
        st.warning("No matching live quotes returned. Check if your Upstox Access Token is active or if market hours are closed.")
else:
    st.info("Enter your Upstox Access Token and upload at least the Intraday/Daily Bhavcopy in the sidebar to begin.")
