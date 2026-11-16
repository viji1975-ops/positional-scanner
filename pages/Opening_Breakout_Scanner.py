import streamlit as st
import pandas as pd
import numpy as np
import requests
import zipfile
import os

st.set_page_config(page_title="Opening Breakout Scanner", layout="wide")
st.title("🔥 Opening Breakout & Confluence Scanner")

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}


def load_bhavcopy_zip(uploaded_file):
    if uploaded_file is None:
        return None
    if uploaded_file.name.endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.endswith(".csv"))
            with z.open(csv_name) as f:
                df = pd.read_csv(f)
    else:
        df = pd.read_csv(uploaded_file)

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


def resolve_instrument_keys_via_api(access_token, sub_df):
    """Maps Bhavcopy contracts to Upstox instrument_keys using local repo file or Upstox v2 Search API."""
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    url = "https://upstox.com"
    key_to_inst = {}

    if os.path.exists("NSE.json.gz"):
        local_df = pd.read_json("NSE.json.gz", compression="gzip")
        fo_df = local_df[local_df["segment"].isin(["NSE_FO", "BSE_FO"])].copy()
        fo_df = fo_df[fo_df["instrument_type"].isin(["CE", "PE"])].copy()
        fo_df["expiry_dt"] = pd.to_datetime(fo_df["expiry"], unit="ms").dt.strftime("%Y-%m-%d")
        fo_df["key"] = (
            fo_df["name"].astype(str).str.strip() + "_" +
            fo_df["expiry_dt"] + "_" +
            fo_df["strike_price"].astype(float).astype(str) + "_" +
            fo_df["instrument_type"].astype(str).str.strip()
        )
        key_to_inst.update(dict(zip(fo_df["key"], fo_df["instrument_key"])))

    missing_df = sub_df[~sub_df["key"].isin(key_to_inst.keys())]
    unique_pairs = missing_df[["TckrSymb", "XpryDt"]].drop_duplicates()

    for _, row in unique_pairs.iterrows():
        sym = str(row["TckrSymb"]).strip()
        exp = str(row["XpryDt"]).strip()
        exch = "BSE" if sym == "SENSEX" else "NSE"
        params = {
            "query": sym,
            "exchanges": exch,
            "segments": "FO",
            "expiry": exp,
            "records": 30
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10).json()
            if resp.get("status") == "success":
                for item in resp.get("data", []):
                    if item.get("name", "").strip() == sym and item.get("instrument_type") in ["CE", "PE"]:
                        k = f"{sym}_{exp}_{float(item['strike_price'])}_{item['instrument_type']}"
                        key_to_inst[k] = item["instrument_key"]
        except Exception:
            continue

    return key_to_inst


def fetch_live_quotes(access_token, key_to_inst, target_keys):
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
                buy_item = next(iter(depth.get("buy", [])), {})
                sell_item = next(iter(depth.get("sell", [])), {})
                best_bid = buy_item.get("price", 0)
                best_ask = sell_item.get("price", 0)
                records.append({
                    "key": inst_to_key.get(inst_key),
                    "ltp": data.get("last_price", 0),
                    "volume": data.get("volume", 0),
                    "live_oi": data.get("oi", 0),
                    "bid": best_bid,
                    "ask": best_ask
                })
    return pd.DataFrame(records)


with st.sidebar:
    st.header("Configuration")
    access_token = st.text_input("Upstox Access Token", type="password")

    st.header("Upload Bhavcopy Files")
    daily_file = st.file_uploader("1. Intraday / Previous Day Bhavcopy", type=["csv", "zip"])
    weekly_file = st.file_uploader("2. Weekly Bhavcopy (Optional)", type=["csv", "zip"])
    monthly_file = st.file_uploader("3. Monthly Bhavcopy (Optional)", type=["csv", "zip"])

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

    if (sub_df["Spot_Ref"] > 0).any():
        sub_df["Dist_Pct"] = abs(sub_df["StrkPric"] - sub_df["Spot_Ref"]) / sub_df["Spot_Ref"]
        sub_df = sub_df[sub_df["Dist_Pct"] <= max_dist]

    if refresh_btn or "live_quotes" not in st.session_state:
        with st.spinner("Resolving contracts & fetching live Upstox quotes..."):
            inst_map = resolve_instrument_keys_via_api(access_token, sub_df)
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
