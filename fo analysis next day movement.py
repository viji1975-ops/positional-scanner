import glob
import importlib
import numpy as np
import pandas as pd
import streamlit as st
import scanner_engine

importlib.reload(scanner_engine)

st.set_page_config(page_title="NSE F&O Positional & Option Buying Scanner", layout="wide")
st.title("📈 NSE F&O Positional Scanner & Next-Day Option Predictor")
DATA_FOLDER = "data/daily_fo_bhavcopy/*.*"

st.sidebar.header("⚙️ Filter Mode")
strict_mode = st.sidebar.checkbox("🔥 Strict / High-Conviction Mode", value=False)
if strict_mode: st.sidebar.success("Active: Coil <= 1.0% | 3D OI >= 15% | Massive OI >= 30% | Score >= 6 | PCR >= 1.30 / <= 0.60")
else: st.sidebar.info("Active: Standard Mode (Coil <= 2.5% | 3D OI >= 5% | Massive OI >= 20% | Score >= 4 | PCR >= 1.25 / <= 0.65)")

repo_files = [f for f in glob.glob(DATA_FOLDER) if f.lower().endswith((".csv", ".zip"))]
uploaded_files = st.file_uploader(f"Upload New Daily Bhavcopy ZIP/CSV (Auto-merges with {len(repo_files)} saved repo files)", type=["csv", "zip"], accept_multiple_files=True)
raw_sources = list(repo_files) + (list(uploaded_files) if uploaded_files else [])
dfs = [d for d in [scanner_engine.load_fo_bhavcopy(f) for f in raw_sources] if not d.empty]
if not dfs: st.info("Upload 2 or more NSE F&O Bhavcopy ZIP/CSV files above (or save them in GitHub's data/daily_fo_bhavcopy/ folder)."); st.stop()

all_df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["INSTRUMENT", "SYMBOL", "DATE", "EXPIRY", "STRIKE", "OPTION_TYP"])
latest_date = all_df["DATE"].max()
massive_pct = 30 if strict_mode else 20
NUM_KEYS = {"OI_SCORE", "PREM", "SCORE", "PCR", "MAX_PAIN", "NET_PE_CHG", "NET_CE_CHG"}
ALL_KEYS = ["OI_SCORE", "SENTIMENT", "TOP_CE", "TOP_PE", "ACTION", "STRIKE", "PREM", "SCORE", "REASON", "PCR", "MAX_PAIN", "PUT_FLOOR", "CALL_WALL", "NET_PE_CHG", "NET_CE_CHG", "INST_BIAS", "BREAKOUT_RADAR", "BREAKOUT_LEVEL", "RADAR_NOTES"]

def prep_table(inst_fut, inst_opt, is_index=False):
    f_df = all_df[all_df["INSTRUMENT"] == inst_fut].sort_values(["SYMBOL", "DATE", "EXPIRY"]).drop_duplicates(subset=["SYMBOL", "DATE"]).copy()
    g_c, g_o = f_df.groupby("SYMBOL")["CLOSE"], f_df.groupby("SYMBOL")["OPEN_INT"]
    for col_n, lag in [("1D_CHG_%", 1), ("3D_CHG_%", 3), ("5D_CHG_%", 5), ("20D_CHG_%", 20), ("22D_CHG_%", 22)]: f_df[col_n] = (f_df["CLOSE"] - g_c.shift(lag)) / g_c.shift(lag) * 100
    f_df["FUT_OI_CHG_%"] = (f_df["OPEN_INT"] - g_o.shift(1)) / g_o.shift(1) * 100
    f_df["3D_OI_CHG_%"] = (f_df["OPEN_INT"] - g_o.shift(3)) / g_o.shift(3) * 100
    lat_f = f_df[f_df["DATE"] == latest_date].reset_index(drop=True)
    o_df = all_df[(all_df["INSTRUMENT"] == inst_opt) & (all_df["DATE"] == latest_date) & (all_df["OPEN_INT"] > 0)].copy()
    if is_index:
        nifty_exp = o_df[o_df["SYMBOL"] == "NIFTY"]["EXPIRY"].min()
        other_o = o_df[o_df["SYMBOL"] != "NIFTY"].copy()
        other_o["YM"] = other_o["EXPIRY"].dt.to_period("M")
        monthly_exp = other_o.groupby(["SYMBOL", "YM"])["EXPIRY"].transform("max")
        other_m = other_o[other_o["EXPIRY"] == monthly_exp]
        near_other = other_m.sort_values("EXPIRY").drop_duplicates("SYMBOL").set_index("SYMBOL")["EXPIRY"]
        o_df = pd.concat([o_df[(o_df["SYMBOL"] == "NIFTY") & (o_df["EXPIRY"] == nifty_exp)], other_m[other_m["EXPIRY"] == other_m["SYMBOL"].map(near_other)]], ignore_index=True)
    else:
        near_exp = o_df.sort_values("EXPIRY").drop_duplicates("SYMBOL").set_index("SYMBOL")["EXPIRY"]
        o_df = o_df[o_df["EXPIRY"] == o_df["SYMBOL"].map(near_exp)].copy()
    o_df["PREV_OI"] = o_df["OPEN_INT"] - o_df["CHG_IN_OI"]
    o_df["OI_CHG_%"] = np.where(o_df["PREV_OI"] > 0, (o_df["CHG_IN_OI"] / o_df["PREV_OI"]) * 100, 0.0)
    o_df["OI_ACTION"] = "Neutral"
    o_df.loc[o_df["OI_CHG_%"] >= 5, "OI_ACTION"] = "Addition"
    o_df.loc[(o_df["OI_CHG_%"] >= massive_pct) | ((o_df["PREV_OI"] <= 0) & (o_df["CHG_IN_OI"] > 0)), "OI_ACTION"] = "Massive Addition"
    o_df.loc[o_df["OI_CHG_%"] <= -5, "OI_ACTION"] = "Windup"
    o_df.loc[o_df["OI_CHG_%"] <= -massive_pct, "OI_ACTION"] = "Massive Windup"
    res = [scanner_engine.analyze_all_metrics(r, o_df[o_df["SYMBOL"] == r["SYMBOL"]], strict_mode) for _, r in lat_f.iterrows()]
    for k in ALL_KEYS:
        default_val = 0.0 if k in NUM_KEYS else "-"
        lat_f[k] = [(d or {}).get(k, default_val) for d in res]
    return lat_f, o_df

stock_fut, stock_opt = prep_table("FUTSTK", "OPTSTK", is_index=False)
idx_fut, idx_opt = prep_table("FUTIDX", "OPTIDX", is_index=True)

st.info(f"📅 Data Up To: {latest_date.strftime('%d %b %Y')} | Trading Days: {all_df['DATE'].nunique()} (Saved Repo: {len(repo_files)}) | Stocks: {len(stock_fut)} | Indices: {len(idx_fut)}")
segment = st.radio("Select Market Segment to View All 4 Analysis Tabs:", ["🏢 F&O Stocks (218)", "📈 Indices (NIFTY Weekly / BANKNIFTY & Others Monthly)"], horizontal=True)
active_fut, active_opt = (idx_fut, idx_opt) if "Indices" in segment else (stock_fut, stock_opt)

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Next-Day Option Buying", "📊 EOD Movers & Sentiment", "🏛️ Institutional Bias & Strikes", "🚀 Breakout & 3D Radar"])

c1, c2 = tab1.columns(2)
c1.markdown("### 🟢 Next-Day CALL Buying (BUY CE)")
c1.dataframe(active_fut[active_fut["ACTION"] == "🟢 BUY CALL (CE)"].sort_values(by=["SCORE", "1D_CHG_%"], ascending=False)[["SYMBOL", "CLOSE", "HIGH", "STRIKE", "PREM", "SCORE", "REASON"]], use_container_width=True, hide_index=True)
c2.markdown("### 🔴 Next-Day PUT Buying (BUY PE)")
c2.dataframe(active_fut[active_fut["ACTION"] == "🔴 BUY PUT (PE)"].sort_values(by=["SCORE", "1D_CHG_%"], ascending=[True, True])[["SYMBOL", "CLOSE", "LOW", "STRIKE", "PREM", "SCORE", "REASON"]], use_container_width=True, hide_index=True)

col1, col2 = tab2.columns(2)
col1.markdown("### 🟢 Top Gainers (1D %)")
col1.dataframe(active_fut.nlargest(8, "1D_CHG_%")[["SYMBOL", "CLOSE", "1D_CHG_%", "3D_CHG_%", "5D_CHG_%", "22D_CHG_%", "SENTIMENT"]], use_container_width=True, hide_index=True)
col2.markdown("### 🔴 Top Losers (1D %)")
col2.dataframe(active_fut.nsmallest(8, "1D_CHG_%")[["SYMBOL", "CLOSE", "1D_CHG_%", "3D_CHG_%", "5D_CHG_%", "22D_CHG_%", "SENTIMENT"]], use_container_width=True, hide_index=True)
s_filt = tab2.multiselect("Filter by EOD Auto-Sentiment", ["STRONG BULLISH", "BULLISH", "STRONG BEARISH", "BEARISH", "REVERSAL WATCH", "NEUTRAL / SIDEWAYS"], default=["STRONG BULLISH", "STRONG BEARISH", "REVERSAL WATCH", "BULLISH", "BEARISH", "NEUTRAL / SIDEWAYS"])
tab2.dataframe(active_fut[active_fut["SENTIMENT"].isin(s_filt)].sort_values(by="1D_CHG_%", ascending=False, na_position="last")[["SYMBOL", "SENTIMENT", "OI_SCORE", "CLOSE", "1D_CHG_%", "3D_CHG_%", "5D_CHG_%", "20D_CHG_%", "22D_CHG_%", "TOP_CE", "TOP_PE"]], use_container_width=True, hide_index=True)

tab3.markdown("### 🏛️ Overall Institutional Bias (PCR, Max Pain & OI Walls)")
b_filt = tab3.multiselect("Filter Institutional Bias", sorted(active_fut["INST_BIAS"].unique()), default=sorted(active_fut["INST_BIAS"].unique()))
tab3.dataframe(active_fut[active_fut["INST_BIAS"].isin(b_filt)].sort_values(by="PCR", ascending=False)[["SYMBOL", "CLOSE", "1D_CHG_%", "INST_BIAS", "PCR", "MAX_PAIN", "PUT_FLOOR", "CALL_WALL", "NET_PE_CHG", "NET_CE_CHG"]], use_container_width=True, hide_index=True)
tab3.divider()
sel = tab3.selectbox("🔍 Drill Down Into Strike-Level Option Chain", sorted(active_fut["SYMBOL"].unique()))
sr = next(iter(active_fut[active_fut["SYMBOL"] == sel].to_dict("records")))
m1, m2, m3, m4 = tab3.columns(4)
m1.metric("Institutional Bias", next(iter(str(sr["INST_BIAS"]).split(" (")), str(sr["INST_BIAS"])), f"PCR: {sr['PCR']}")
m2.metric("Max Pain Strike", f"{float(sr['MAX_PAIN']):g}", f"Spot: {sr['CLOSE']}")
m3.metric("Strongest Put Floor", str(sr["PUT_FLOOR"]), f"Net PE OI: {float(sr['NET_PE_CHG']):+,.0f}")
m4.metric("Strongest Call Wall", str(sr["CALL_WALL"]), f"Net CE OI: {float(sr['NET_CE_CHG']):+,.0f}")
only_act = tab3.checkbox("Show only Addition / Windup strikes (>= 5% OI change)", value=False)
active_opt["ABS_CHG"] = active_opt["CHG_IN_OI"].abs()
st_df = active_opt[active_opt["SYMBOL"] == sel].sort_values(by="ABS_CHG", ascending=False)
if only_act: st_df = st_df[st_df["OI_ACTION"] != "Neutral"]
tab3.dataframe(st_df[["STRIKE", "OPTION_TYP", "CLOSE", "PREV_OI", "OPEN_INT", "CHG_IN_OI", "OI_CHG_%", "OI_ACTION"]], use_container_width=True, hide_index=True)

tab4.markdown("### 🚀 Advance Breakout & Multi-Day (3D) Institutional Accumulation Radar")
active_radar = active_fut[active_fut["BREAKOUT_RADAR"] != "⚪ NO COIL"].sort_values(by="3D_OI_CHG_%", ascending=False, na_position="last")
tab4.dataframe(active_radar[["SYMBOL", "BREAKOUT_RADAR", "BREAKOUT_LEVEL", "CLOSE", "1D_CHG_%", "3D_CHG_%", "3D_OI_CHG_%", "PCR", "RADAR_NOTES"]], use_container_width=True, hide_index=True)
