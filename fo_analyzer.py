import glob
import os
import numpy as np
import pandas as pd

DATA_FOLDER = "data/daily_fo_bhavcopy/*.csv"
OUTPUT_FOLDER = "outputs"


def load_fo_bhavcopy(file_path):
  df = pd.read_csv(file_path)
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
  else:
    return "Neutral"


def compute_stock_sentiment(sym_opts, price_chg_1d):
  """
    Scores top active strikes for a symbol to produce an OI score and Sentiment tag.
    Bullish (+) = Call Windup (-CE OI) & Put Addition (+PE OI)
    Bearish (-) = Put Windup (-PE OI) & Call Addition (+CE OI)
    """
  if sym_opts.empty or pd.isna(price_chg_1d):
    return 0, "NEUTRAL / SIDEWAYS", "None", "None"

  # Focus on top 3 Call strikes and top 3 Put strikes by absolute OI change
  ce_opts = sym_opts[sym_opts["OPTION_TYP"] == "CE"].copy()
  pe_opts = sym_opts[sym_opts["OPTION_TYP"] == "PE"].copy()

  top_ce = ce_opts.reindex(
      ce_opts["CHG_IN_OI"].abs().sort_values(ascending=False).index
  ).head(3)
  top_pe = pe_opts.reindex(
      pe_opts["CHG_IN_OI"].abs().sort_values(ascending=False).index
  ).head(3)

  oi_score = 0

  # Score Call strikes (Windup = Bullish +, Addition = Bearish -)
  for _, r in top_ce.iterrows():
    action = r["OI_ACTION"]
    if action == "Massive Windup":
      oi_score += 2
    elif action == "Windup":
      oi_score += 1
    elif action == "Massive Addition":
      oi_score -= 2
    elif action == "Addition":
      oi_score -= 1

  # Score Put strikes (Addition = Bullish +, Windup = Bearish -)
  for _, r in top_pe.iterrows():
    action = r["OI_ACTION"]
    if action == "Massive Addition":
      oi_score += 2
    elif action == "Addition":
      oi_score += 1
    elif action == "Massive Windup":
      oi_score -= 2
    elif action == "Windup":
      oi_score -= 1

  # Summary strings of dominant strike signals
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

  # Combine Price Direction + OI Score into Final Sentiment Tag
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
    if abs(oi_score) >= 3:
      sentiment = "REVERSAL WATCH"
    else:
      sentiment = "NEUTRAL / SIDEWAYS"

  return oi_score, sentiment, ce_summary, pe_summary


def run_analysis():
  files = glob.glob(DATA_FOLDER)
  if not files:
    print("No F&O Bhavcopy files found in data/daily_fo_bhavcopy/.")
    return

  os.makedirs(OUTPUT_FOLDER, exist_ok=True)
  all_df = pd.concat([load_fo_bhavcopy(f) for f in files], ignore_index=True)
  all_df = all_df.drop_duplicates(
      subset=["INSTRUMENT", "SYMBOL", "DATE", "EXPIRY", "STRIKE", "OPTION_TYP"]
  )

  # 1. PRICE MOVEMENT ANALYSIS (Near-Month Stock Futures)
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

  # 2. OPTION STRIKE ADDITION & WINDUP ANALYSIS (Latest Date, Nearest Expiry)
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

  # 3. APPLY AUTO-SENTIMENT TAGGING TO EVERY STOCK
  oi_scores = []
  sentiments = []
  ce_signals = []
  pe_signals = []

  for _, row in latest_fut.iterrows():
    sym = row["SYMBOL"]
    sym_opts = opt_df[opt_df["SYMBOL"] == sym]
    score, sent, ce_sig, pe_sig = compute_stock_sentiment(
        sym_opts, row["1D_CHG_%"]
    )
    oi_scores.append(score)
    sentiments.append(sent)
    ce_signals.append(ce_sig)
    pe_signals.append(pe_sig)

  latest_fut["OI_SCORE"] = oi_scores
  latest_fut["SENTIMENT"] = sentiments
  latest_fut["TOP_CE_SIGNALS"] = ce_signals
  latest_fut["TOP_PE_SIGNALS"] = pe_signals

  # Save full reports to outputs/
  date_str = latest_date.strftime("%Y%m%d")
  latest_fut.sort_values(by="1D_CHG_%", ascending=False).to_csv(
      f"{OUTPUT_FOLDER}/price_movers_sentiment_{date_str}.csv", index=False
  )
  opt_report = opt_df[opt_df["OI_ACTION"] != "Neutral"].sort_values(
      by="CHG_IN_OI", key=abs, ascending=False
  )
  opt_report.to_csv(
      f"{OUTPUT_FOLDER}/option_oi_signals_{date_str}.csv", index=False
  )

  # 4. PRINT SUMMARY BY SENTIMENT CATEGORY
  print(f"\n=== F&O AUTO-SENTIMENT REPORT ({latest_date.strftime('%Y-%m-%d')}) ===")

  for tag in [
      "STRONG BULLISH",
      "STRONG BEARISH",
      "REVERSAL WATCH",
      "BULLISH",
      "BEARISH",
  ]:
    subset = latest_fut[latest_fut["SENTIMENT"] == tag].sort_values(
        by="1D_CHG_%", key=abs, ascending=False
    )
    print(f"\n--- {tag} ({len(subset)} stocks) ---")
    if subset.empty:
      print("   None")
    else:
      for _, r in subset.head(10).iterrows():
        print(
            f"► {r['SYMBOL']:<12} | Close: {r['CLOSE']:>8.2f} | 1D:"
            f" {r['1D_CHG_%']:>6.2f}% | 5D: {r['5D_CHG_%']:>6.2f}% | 22D:"
            f" {r['22D_CHG_%']:>6.2f}% | OI Score: {r['OI_SCORE']:+d}"
        )
        print(
            f"   CE: {r['TOP_CE_SIGNALS']}  ||  PE: {r['TOP_PE_SIGNALS']}"
        )


if __name__ == "__main__":
  run_analysis()
