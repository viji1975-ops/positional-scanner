import glob
import os
import zipfile
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="F&O Positional Scanner", layout="wide")

DATA_FOLDER = "data/daily_fo_bhavcopy/*.*"


def load_fo_bhavcopy(file_obj):
  """Loads either a raw .csv or compressed .zip NSE F&O Bhavcopy file."""
  filename = getattr(file_obj, "name", str(file_obj))
  if filename.lower().endswith(".zip"):
    with zipfile.ZipFile(file_obj) as z:
      csv_files = [f for f in z.namelist() if f.lower().endswith(".csv")]
      if not csv_files:
        return pd.DataFrame()
      with z.open(csv_files[0]) as f:
        df = pd.read_csv(f)
  else:
    df = pd.read_csv(file_obj)

  df.columns = [c.strip() for c in df.columns]

  # New NSE UDiFF F&O Bhavcopy Format
  if "TckrSymb" in df.columns:
    df = df[df["FinInstrmTp"].isin(["STF", "STO"])].copy()
    df["INSTRUMENT"] = df["FinInstrmTp"].map(
        {"STF": "FUTSTK", "STO": "OPTSTK"}
    )
    df = df[[
        "INSTRUMENT",
        "TckrSymb",
        "TradDt",
        "XpryDt",
        "StrkPric",
        "OptnTp",
        "ClsPric",
        "OpnIntrst",
        "ChngInOpnIntrst",
        "TtlTradgVol",
    ]].copy()
    df.columns = [
        "INSTRUMENT",
        "SYMBOL",
        "DATE",
        "EXPIRY",
        "STRIKE",
        "OPTION_TYP",
        "CLOSE",
        "OPEN_INT",
        "CHG_IN_OI",
        "VOLUME",
    ]

  # Legacy NSE F&O Bhavcopy Format
  elif "INSTRUMENT" in df.columns:
    df = df[df["INSTRUMENT"].isin(["FUTSTK", "OPTSTK"])].copy()
    df = df[[
        "INSTRUMENT",
        "SYMBOL",
        "TIMESTAMP",
        "EXPIRY_DT",
        "STRIKE_PR",
        "OPTION_TYP",
        "CLOSE",
        "OPEN_INT",
        "CHG_IN_OI",
        "CONTRACTS",
    ]].copy()
    df.columns = [
        "INSTRUMENT",
        "SYMBOL",
        "DATE",
        "EXPIRY",
        "STRIKE",
        "OPTION_TYP",
        "CLOSE",
        "OPEN_INT",
        "CHG_IN_OI",
        "VOLUME",
    ]
  else:
    return pd.DataFrame()

  df["DATE"] = pd.to_datetime(df["DATE"])
  df["EXPIRY"] = pd.to_datetime(df["EXPIRY"])
  df["STRIKE"] = pd.to_numeric(df["STRIKE"], errors="coerce").fillna(0)
  return df


def classify_oi_action(row):
  prev_oi = row["OPEN_INT"] - row["CHG_IN_OI"]
  if prev_oi <= 0:
    return "Massive Addition" if row["CHG_IN_OI"] > 0 else "Neutral"

  pct_oi_chg = (row["CHG_IN_OI"] / prev_oi) * 100
  if pct_oi_chg >= 25:
    return "Massive Addition"
  elif pct_oi_chg >= 5:
    return "Addition"
  elif pct_oi_chg <= -25:
    return "Massive Windup"
  elif pct_oi_chg <= -5:
    return "Windup"
  return "Neutral"


def compute_stock_sentiment(sym_opts, price_chg_1d):
  if sym_opts.empty or pd.isna(price_chg_1d):
    return 0, "NEUTRAL / SIDEWAYS", "None", "None"

  ce_opts = sym_opts[sym_opts["OPTION_TYP"] == "CE"].copy()
  pe_opts = sym_opts[sym_opts["OPTION_TYP"] == "PE"].copy()

  top_ce = ce_opts.reindex(
      ce_opts["CHG_IN_OI"].abs().sort_values(ascending=False).index
  ).head(3)
  top_pe = pe_opts.reindex(
      pe_opts["CHG_IN_OI"].abs().sort_values(ascending=False).index
  ).head(3)

  oi_score = 0
  # Call Windup = Bullish (+), Call Addition = Bearish (-)
  for _, r in top_ce.iterrows():
    if r["OI_ACTION"] == "Massive Windup":
      oi_score += 2
    elif r["OI_ACTION"] == "Windup":
      oi_score += 1
    elif r["OI_ACTION"] == "Massive Addition":
      oi_score -= 2
    elif r["OI_ACTION"] == "Addition":
      oi_score -= 1

  # Put Addition = Bullish (+), Put Windup = Bearish (-)
  for _, r in top_pe.iterrows():
    if r["OI_ACTION"] == "Massive Addition":
      oi_score += 2
    elif r["OI_ACTION"] == "Addition":
      oi_score += 1
    elif r["OI_ACTION"] == "Massive Windup":
      oi_score -= 2
    elif r["OI_ACTION"] == "Windup":
      oi_score -= 1

  ce_summary = (
      ", ".join([
          f"{int(r['STRIKE'])}CE ({r['OI_ACTION']})"
          for _, r in top_ce.iterrows()
          if r["OI_ACTION"] != "Neutral"
      ])
      or "Neutral"
  )

  pe_summary = (
      ", ".join([
          f"{int(r['STRIKE'])}PE ({r['OI_ACTION']})"
          for _, r in top_pe.iterrows()
          if r["OI_ACTION"] != "Neutral"
      ])
      or "Neutral"
  )

  if price_chg_1d > 0.5:
    if oi_score >= 3:
      sentiment = "STRONG BULLISH"
    elif oi_score >= 1:
      sentiment = "BULLISH"
    elif oi_score <= -2:
      sentiment = "REVERSAL WATCH"
    else:
      sentiment = "NEUTRAL / SIDEWAYS"
  elif price_chg_1d < -0.5:
    if oi_score <= -3:
      sentiment = "STRONG BEARISH"
    elif oi_score <= -1:
      sentiment = "BEARISH"
    elif oi_score >= 2:
      sentiment = "REVERSAL WATCH"
    else:
      sentiment = "NEUTRAL / SIDEWAYS"
  else:
    sentiment = (
        "REVERSAL WATCH" if abs(oi_score) >= 3 else "NEUTRAL / SIDEWAYS"
    )

  return oi_score, sentiment, ce_summary, pe_summary


# --- STREAMLIT UI ---
st.title("📊 NSE F&O Positional & Option OI Scanner")

uploaded_files = st.file_uploader(
    "Upload Daily NSE F&O Bhavcopy ZIP or CSV files (1 to 25+ days)",
    type=["csv", "zip"],
    accept_multiple_files=True,
)

repo_files = [
    f
    for f in glob.glob(DATA_FOLDER)
    if f.lower().endswith((".csv", ".zip"))
]
dfs = []

if uploaded_files:
  for f in uploaded_files:
    parsed = load_fo_bhavcopy(f)
    if not parsed.empty:
      dfs.append(parsed)
elif repo_files:
  for f in repo_files:
    parsed = load_fo_bhavcopy(f)
    if not parsed.empty:
      dfs.append(parsed)

if not dfs:
  st.info(
      "Upload one or more NSE F&O Bhavcopy ZIP/CSV files above (or push them to"
      " `data/daily_fo_bhavcopy/` in GitHub) to view the scanner."
  )
  st.stop()

all_df = pd.concat(dfs, ignore_index=True)
all_df = all_df.drop_duplicates(
    subset=["INSTRUMENT", "SYMBOL", "DATE", "EXPIRY", "STRIKE", "OPTION_TYP"]
)

# 1. Price Movements (Near-Month Stock Futures)
fut_df = all_df[all_df["INSTRUMENT"] == "FUTSTK"].copy()
fut_df = fut_df.sort_values(["SYMBOL", "DATE", "EXPIRY"]).drop_duplicates(
    subset=["SYMBOL", "DATE"]
)

grouped = fut_df.groupby("SYMBOL")["CLOSE"]
fut_df["1D_CHG_%"] = grouped.pct_change(1) * 100
fut_df["5D_CHG_%"] = grouped.pct_change(5) * 100
fut_df["20D_CHG_%"] = grouped.pct_change(20) * 100
fut_df["22D_CHG_%"] = grouped.pct_change(22) * 100

latest_date = all_df["DATE"].max()
latest_fut = fut_df[fut_df["DATE"] == latest_date].copy()

# 2. Option OI Analysis (Latest Date, Nearest Expiry)
opt_df = all_df[
    (all_df["INSTRUMENT"] == "OPTSTK") & (all_df["DATE"] == latest_date)
].copy()
near_expiry = opt_df.groupby("SYMBOL")["EXPIRY"].min().reset_index()
opt_df = opt_df.merge(near_expiry, on=["SYMBOL", "EXPIRY"])
opt_df = opt_df[opt_df["OPEN_INT"] > 0].copy()
opt_df["PREV_OI"] = opt_df["OPEN_INT"] - opt_df["CHG_IN_OI"]
opt_df["OI_CHG_%"] = np.where(
    opt_df["PREV_OI"] > 0, (opt_df["CHG_IN_OI"] / opt_df["PREV_OI"]) * 100, 0
)
opt_df["OI_ACTION"] = opt_df.apply(classify_oi_action, axis=1)

# 3. Sentiment Scoring
results = [
    compute_stock_sentiment(
        opt_df[opt_df["SYMBOL"] == row["SYMBOL"]], row["1D_CHG_%"]
    )
    for _, row in latest_fut.iterrows()
]
latest_fut["OI_SCORE"] = [r[0] for r in results]
latest_fut["SENTIMENT"] = [r[1] for r in results]
latest_fut["TOP_CE_SIGNALS"] = [r[2] for r in results]
latest_fut["TOP_PE_SIGNALS"] = [r[3] for r in results]

st.subheader(
    f"Market Snapshot: {latest_date.strftime('%d %b %Y')} | Files Loaded:"
    f" {all_df['DATE'].nunique()} trading days"
)

# Top Gainers & Losers Heatmap Cards
col1, col2 = st.columns(2)
with col1:
  st.markdown("### 🟢 Top Gainers (1D %)")
  gainers = latest_fut.nlargest(8, "1D_CHG_%")
  g_cols = st.columns(4)
  for idx, (_, r) in enumerate(gainers.iterrows()):
    with g_cols[idx % 4]:
      st.metric(
          r["SYMBOL"],
          f"{r['CLOSE']:.1f}",
          f"{r['1D_CHG_%']:.2f}%" if pd.notna(r["1D_CHG_%"]) else "N/A",
      )

with col2:
  st.markdown("### 🔴 Top Losers (1D %)")
  losers = latest_fut.nsmallest(8, "1D_CHG_%")
  l_cols = st.columns(4)
  for idx, (_, r) in enumerate(losers.iterrows()):
    with l_cols[idx % 4]:
      st.metric(
          r["SYMBOL"],
          f"{r['CLOSE']:.1f}",
          f"{r['1D_CHG_%']:.2f}%" if pd.notna(r["1D_CHG_%"]) else "N/A",
      )

st.divider()

# Filterable Sentiment Table
sentiment_filter = st.multiselect(
    "Filter by Auto-Sentiment",
    options=[
        "STRONG BULLISH",
        "BULLISH",
        "STRONG BEARISH",
        "BEARISH",
        "REVERSAL WATCH",
        "NEUTRAL / SIDEWAYS",
    ],
    default=[
        "STRONG BULLISH",
        "STRONG BEARISH",
        "REVERSAL WATCH",
        "BULLISH",
        "BEARISH",
        "NEUTRAL / SIDEWAYS",
    ],
)

display_cols = [
    "SYMBOL",
    "SENTIMENT",
    "OI_SCORE",
    "CLOSE",
    "1D_CHG_%",
    "5D_CHG_%",
    "20D_CHG_%",
    "22D_CHG_%",
    "TOP_CE_SIGNALS",
    "TOP_PE_SIGNALS",
]
filtered_df = latest_fut[
    latest_fut["SENTIMENT"].isin(sentiment_filter)
].sort_values(by="1D_CHG_%", ascending=False, na_position="last")

st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)

# Download CSV Button
csv_export = filtered_df[display_cols].to_csv(index=False).encode("utf-8")
st.download_button(
    label="📥 Download Sentiment Report (CSV)",
    data=csv_export,
    file_name=f"fo_sentiment_{latest_date.strftime('%Y%m%d')}.csv",
    mime="text/csv",
)

st.divider()

# Strike-level Drilldown
st.subheader("🔍 Strike-Level Addition & Windup Explorer")
selected_stock = st.selectbox(
    "Select Stock", sorted(latest_fut["SYMBOL"].unique())
)
stock_strikes = opt_df[
    (opt_df["SYMBOL"] == selected_stock) & (opt_df["OI_ACTION"] != "Neutral")
].sort_values(by="CHG_IN_OI", key=abs, ascending=False)

st.dataframe(
    stock_strikes[[
        "STRIKE",
        "OPTION_TYP",
        "CLOSE",
        "PREV_OI",
        "OPEN_INT",
        "CHG_IN_OI",
        "OI_CHG_%",
        "OI_ACTION",
    ]],
    use_container_width=True,
    hide_index=True,
