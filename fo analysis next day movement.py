import glob
import os
import zipfile
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="NSE F&O Positional & Option Buying Scanner", layout="wide"
)

DATA_FOLDER = "data/daily_fo_bhavcopy/*.*"


def load_fo_bhavcopy(file_obj):
  filename = getattr(file_obj, "name", str(file_obj))
  try:
    if filename.lower().endswith(".zip"):
      with zipfile.ZipFile(file_obj) as z:
        csv_files = [f for f in z.namelist() if f.lower().endswith(".csv")]
        if not csv_files:
          st.warning(f"No CSV found inside {filename}")
          return pd.DataFrame()
        target_csv = next(iter(csv_files))
        with z.open(target_csv) as f:
          df = pd.read_csv(f)
    else:
      df = pd.read_csv(file_obj)
  except Exception as e:
    st.error(f"Error reading {filename}: {e}")
    return pd.DataFrame()

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
        "HghPric",
        "LwPric",
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
        "HIGH",
        "LOW",
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
        "HIGH",
        "LOW",
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
        "HIGH",
        "LOW",
        "CLOSE",
        "OPEN_INT",
        "CHG_IN_OI",
        "VOLUME",
    ]
  else:
    st.error(f"Unrecognized columns in {filename}: {list(df.columns)[:10]}")
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
  if pct_oi_chg >= 20:
    return "Massive Addition"
  elif pct_oi_chg >= 5:
    return "Addition"
  elif pct_oi_chg <= -20:
    return "Massive Windup"
  elif pct_oi_chg <= -5:
    return "Windup"
  return "Neutral"


def compute_eod_sentiment(sym_opts, price_chg_1d):
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
  for _, r in top_ce.iterrows():
    if r["OI_ACTION"] == "Massive Windup":
      oi_score += 2
    elif r["OI_ACTION"] == "Windup":
      oi_score += 1
    elif r["OI_ACTION"] == "Massive Addition":
      oi_score -= 2
    elif r["OI_ACTION"] == "Addition":
      oi_score -= 1

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


def evaluate_next_day_setup(fut_row, sym_opts):
  price_chg = fut_row["1D_CHG_%"]
  fut_oi_chg = fut_row["FUT_OI_CHG_%"]
  spot = fut_row["CLOSE"]

  if sym_opts.empty or pd.isna(price_chg):
    return "NO SETUP", "-", 0.0, 0, "Upload 2+ days for Next-Day signal"

  near_opts = sym_opts[
      (sym_opts["STRIKE"] >= spot * 0.94)
      & (sym_opts["STRIKE"] <= spot * 1.06)
      & (sym_opts["VOLUME"] > 0)
  ].copy()

  if near_opts.empty:
    return "NO SETUP", "-", 0.0, 0, "Illiquid Strikes"

  ce_near = near_opts[near_opts["OPTION_TYP"] == "CE"].copy()
  pe_near = near_opts[near_opts["OPTION_TYP"] == "PE"].copy()

  ce_windup = ce_near[ce_near["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum()
  pe_add = pe_near[pe_near["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()
  pe_windup = pe_near[pe_near["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum()
  ce_add = ce_near[ce_near["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()

  score = 0
  reasons = []

  if 0.4 <= price_chg <= 5.5:
    score += 2
    if pd.notna(fut_oi_chg) and fut_oi_chg > 2.0:
      score += 2
      reasons.append(f"Fut Long Buildup (OI +{fut_oi_chg:.1f}%)")
    else:
      reasons.append(f"Bullish Momentum (+{price_chg:.1f}%)")
  elif -5.5 <= price_chg <= -0.4:
    score -= 2
    if pd.notna(fut_oi_chg) and fut_oi_chg > 2.0:
      score -= 2
      reasons.append(f"Fut Short Buildup (OI +{fut_oi_chg:.1f}%)")
    else:
      reasons.append(f"Bearish Momentum ({price_chg:.1f}%)")
  elif abs(price_chg) > 5.5:
    return (
        "EXHAUSTED (SKIP)",
        "-",
        0.0,
        0,
        f"Already moved {price_chg:.1f}% today",
    )

  if abs(ce_windup) > abs(ce_add) and abs(ce_windup) > 0:
    score += 2
    reasons.append("CE Writers Unwinding")
  if pe_add > abs(pe_windup) and pe_add > 0:
    score += 2
    reasons.append("PE Support Added")

  if abs(pe_windup) > abs(pe_add) and abs(pe_windup) > 0:
    score -= 2
    reasons.append("PE Writers Unwinding")
  if ce_add > abs(ce_windup) and ce_add > 0:
    score -= 2
    reasons.append("CE Resistance Added")

  if score >= 4 and not ce_near.empty:
    trapped_ce = ce_near[ce_near["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI")
    if not trapped_ce.empty:
      best_row = trapped_ce.head(1).squeeze()
      strike_note = f"Trapped CE ({best_row['OI_CHG_%']:.0f}% OI)"
    else:
      ce_near["DIST"] = (ce_near["STRIKE"] - spot).abs()
      best_row = ce_near.sort_values("DIST").head(1).squeeze()
      strike_note = "ATM CE"

    strike_str = f"{best_row['STRIKE']:g} CE"
    return (
        "🟢 BUY CALL (CE)",
        strike_str,
        float(best_row["CLOSE"]),
        score,
        " + ".join(reasons) + f" | {strike_note}",
    )

  elif score <= -4 and not pe_near.empty:
    trapped_pe = pe_near[pe_near["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI")
    if not trapped_pe.empty:
      best_row = trapped_pe.head(1).squeeze()
      strike_note = f"Trapped PE ({best_row['OI_CHG_%']:.0f}% OI)"
    else:
      pe_near["DIST"] = (pe_near["STRIKE"] - spot).abs()
      best_row = pe_near.sort_values("DIST").head(1).squeeze()
      strike_note = "ATM PE"

    strike_str = f"{best_row['STRIKE']:g} PE"
    return (
        "🔴 BUY PUT (PE)",
        strike_str,
        float(best_row["CLOSE"]),
        score,
        " + ".join(reasons) + f" | {strike_note}",
    )

  return "NEUTRAL / WAIT", "-", 0.0, score, "No clear next-day edge"


# --- STREAMLIT UI ---
st.title("📈 NSE F&O Positional Scanner & Next-Day Option Predictor")

uploaded_files = st.file_uploader(
    "Upload Daily NSE F&O Bhavcopy ZIP or CSV files (2 to 25+ days)",
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
      "Upload 2 or more NSE F&O Bhavcopy ZIP/CSV files above (or push them to"
      " `data/daily_fo_bhavcopy/` in GitHub) to view the scanner."
  )
  st.stop()

all_df = pd.concat(dfs, ignore_index=True)
all_df = all_df.drop_duplicates(
    subset=["INSTRUMENT", "SYMBOL", "DATE", "EXPIRY", "STRIKE", "OPTION_TYP"]
)

# 1. Futures Price & Multi-Timeframe Returns
fut_df = all_df[all_df["INSTRUMENT"] == "FUTSTK"].copy()
fut_df = fut_df.sort_values(["SYMBOL", "DATE", "EXPIRY"]).drop_duplicates(
    subset=["SYMBOL", "DATE"]
)

grouped = fut_df.groupby("SYMBOL")
fut_df["1D_CHG_%"] = grouped["CLOSE"].pct_change(1) * 100
fut_df["5D_CHG_%"] = grouped["CLOSE"].pct_change(5) * 100
fut_df["20D_CHG_%"] = grouped["CLOSE"].pct_change(20) * 100
fut_df["22D_CHG_%"] = grouped["CLOSE"].pct_change(22) * 100
