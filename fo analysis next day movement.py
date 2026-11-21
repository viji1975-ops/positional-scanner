import glob
import zipfile
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="NSE F&O Positional & Option Buying Scanner", layout="wide")
st.title("📈 NSE F&O Positional Scanner & Next-Day Option Predictor")

DATA_FOLDER = "data/daily_fo_bhavcopy/*.*"


def load_fo_bhavcopy(file_obj):
    filename = getattr(file_obj, "name", str(file_obj))
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(file_obj) as z:
            csv_files = [f for f in z.namelist() if f.lower().endswith(".csv")]
            if not csv_files:
                st.warning(f"No CSV inside {filename}")
                return pd.DataFrame()
            with z.open(next(iter(csv_files))) as f:
                df = pd.read_csv(f, low_memory=False)
    else:
        df = pd.read_csv(file_obj, low_memory=False)

    # Normalize all column names to UPPERCASE for case-insensitive matching
    df.columns = [c.strip().upper() for c in df.columns]

    # New NSE UDiFF F&O Bhavcopy Format (any casing)
    if "TCKRSYMB" in df.columns:
        inst_col = "FININSTRMTP"
        df[inst_col] = df[inst_col].astype(str).str.strip().str.upper()
        df = df[df[inst_col].isin(["STF", "STO", "FUTSTK", "OPTSTK"])].copy()
        out = pd.DataFrame()
        out["INSTRUMENT"] = df[inst_col].map({"STF": "FUTSTK", "FUTSTK": "FUTSTK", "STO": "OPTSTK", "OPTSTK": "OPTSTK"})
        out["SYMBOL"] = df["TCKRSYMB"].astype(str).str.strip()
        out["DATE"] = pd.to_datetime(df["TRADDT"], format="mixed", errors="coerce")
        out["EXPIRY"] = pd.to_datetime(df["XPRYDT"], format="mixed", errors="coerce")
        out["STRIKE"] = pd.to_numeric(df["STRKPRIC"], errors="coerce").fillna(0)
        out["OPTION_TYP"] = df["OPTNTP"].fillna("XX").astype(str).str.strip().str.upper()
        out["CLOSE"] = pd.to_numeric(df["CLSPRIC"], errors="coerce")
        out["HIGH"] = pd.to_numeric(df["HGHPRIC"] if "HGHPRIC" in df.columns else df["CLSPRIC"], errors="coerce")
        out["LOW"] = pd.to_numeric(df["LWPRIC"] if "LWPRIC" in df.columns else df["CLSPRIC"], errors="coerce")
        out["OPEN_INT"] = pd.to_numeric(df["OPNINTRST"], errors="coerce").fillna(0)
        out["CHG_IN_OI"] = pd.to_numeric(df["CHNGINOPNINTRST"], errors="coerce").fillna(0)
        vol_col = "TTLTRADGVOL" if "TTLTRADGVOL" in df.columns else ("TTLTRFVAL" if "TTLTRFVAL" in df.columns else None)
        out["VOLUME"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(1) if vol_col else 1
        cleaned = out.dropna(subset=["DATE", "EXPIRY", "CLOSE"])
        if cleaned.empty:
            st.warning(f"{filename}: Matched TCKRSYMB, but 0 rows after filtering. Unique FININSTRMTP values: {df[inst_col].unique()[:10]}")
        return cleaned

    # Legacy NSE F&O Bhavcopy Format
    if "INSTRUMENT" in df.columns:
        df["INSTRUMENT"] = df["INSTRUMENT"].astype(str).str.strip().str.upper()
        df = df[df["INSTRUMENT"].isin(["FUTSTK", "OPTSTK"])].copy()
        out = pd.DataFrame()
        out["INSTRUMENT"] = df["INSTRUMENT"]
        out["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        out["DATE"] = pd.to_datetime(df["TIMESTAMP"], format="mixed", errors="coerce")
        out["EXPIRY"] = pd.to_datetime(df["EXPIRY_DT"], format="mixed", errors="coerce")
        out["STRIKE"] = pd.to_numeric(df["STRIKE_PR"], errors="coerce").fillna(0)
        out["OPTION_TYP"] = df["OPTION_TYP"].fillna("XX").astype(str).str.strip().str.upper()
        out["CLOSE"] = pd.to_numeric(df["CLOSE"], errors="coerce")
        out["HIGH"] = pd.to_numeric(df["HIGH"] if "HIGH" in df.columns else df["CLOSE"], errors="coerce")
        out["LOW"] = pd.to_numeric(df["LOW"] if "LOW" in df.columns else df["CLOSE"], errors="coerce")
        out["OPEN_INT"] = pd.to_numeric(df["OPEN_INT"], errors="coerce").fillna(0)
        out["CHG_IN_OI"] = pd.to_numeric(df["CHG_IN_OI"], errors="coerce").fillna(0)
        out["VOLUME"] = pd.to_numeric(df["CONTRACTS"], errors="coerce").fillna(0)
        return out.dropna(subset=["DATE", "EXPIRY", "CLOSE"])

    st.error(f"Unrecognized columns in {filename}: {list(df.columns)}")
    return pd.DataFrame()


def classify_oi_action(row):
    prev_oi = row["OPEN_INT"] - row["CHG_IN_OI"]
    if prev_oi <= 0: return "Massive Addition" if row["CHG_IN_OI"] > 0 else "Neutral"
    pct = (row["CHG_IN_OI"] / prev_oi) * 100
    if pct >= 20: return "Massive Addition"
    if pct >= 5: return "Addition"
    if pct <= -20: return "Massive Windup"
    if pct <= -5: return "Windup"
    return "Neutral"


def compute_eod_sentiment(sym_opts, price_chg_1d):
    if sym_opts.empty or pd.isna(price_chg_1d): return 0, "NEUTRAL / SIDEWAYS", "None", "None"
    ce_opts = sym_opts[sym_opts["OPTION_TYP"] == "CE"].copy()
    pe_opts = sym_opts[sym_opts["OPTION_TYP"] == "PE"].copy()
    top_ce = ce_opts.reindex(ce_opts["CHG_IN_OI"].abs().sort_values(ascending=False).index).head(3)
    top_pe = pe_opts.reindex(pe_opts["CHG_IN_OI"].abs().sort_values(ascending=False).index).head(3)

    ce_map = {"Massive Windup": 2, "Windup": 1, "Massive Addition": -2, "Addition": -1}
    pe_map = {"Massive Addition": 2, "Addition": 1, "Massive Windup": -2, "Windup": -1}
    oi_score = sum(ce_map.get(x, 0) for x in top_ce["OI_ACTION"]) + sum(pe_map.get(x, 0) for x in top_pe["OI_ACTION"])

    ce_list = [f"{int(r['STRIKE'])}CE ({r['OI_ACTION']})" for _, r in top_ce.iterrows() if r["OI_ACTION"] != "Neutral"]
    pe_list = [f"{int(r['STRIKE'])}PE ({r['OI_ACTION']})" for _, r in top_pe.iterrows() if r["OI_ACTION"] != "Neutral"]
    ce_summary = ", ".join(ce_list) if ce_list else "Neutral"
    pe_summary = ", ".join(pe_list) if pe_list else "Neutral"

    sentiment = "NEUTRAL / SIDEWAYS"
    if price_chg_1d > 0.5: sentiment = "STRONG BULLISH" if oi_score >= 3 else ("BULLISH" if oi_score >= 1 else ("REVERSAL WATCH" if oi_score <= -2 else "NEUTRAL / SIDEWAYS"))
    elif price_chg_1d < -0.5: sentiment = "STRONG BEARISH" if oi_score <= -3 else ("BEARISH" if oi_score <= -1 else ("REVERSAL WATCH" if oi_score >= 2 else "NEUTRAL / SIDEWAYS"))
    elif abs(oi_score) >= 3: sentiment = "REVERSAL WATCH"

    return oi_score, sentiment, ce_summary, pe_summary


def evaluate_next_day_setup(fut_row, sym_opts):
    price_chg = fut_row["1D_CHG_%"]
    fut_oi_chg = fut_row["FUT_OI_CHG_%"]
    spot = fut_row["CLOSE"]

    if sym_opts.empty or pd.isna(price_chg): return "NO SETUP", "-", 0.0, 0, "Upload 2+ days for Next-Day signal"
    near_opts = sym_opts[(sym_opts["STRIKE"] >= spot * 0.94) & (sym_opts["STRIKE"] <= spot * 1.06) & (sym_opts["VOLUME"] > 0)].copy()
    if near_opts.empty: return "NO SETUP", "-", 0.0, 0, "Illiquid Strikes"
    if abs(price_chg) > 5.5: return "EXHAUSTED (SKIP)", "-", 0.0, 0, f"Already moved {price_chg:.1f}% today"

    ce_near = near_opts[near_opts["OPTION_TYP"] == "CE"].copy()
    pe_near = near_opts[near_opts["OPTION_TYP"] == "PE"].copy()
    ce_windup = ce_near[ce_near["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum()
    pe_add = pe_near[pe_near["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()
    pe_windup = pe_near[pe_near["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum()
    ce_add = ce_near[ce_near["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()

    score = 0
    reasons = []
    if 0.4 <= price_chg <= 5.5:
        score += 4 if (pd.notna(fut_oi_chg) and fut_oi_chg > 2.0) else 2
        reasons.append(f"Fut Long Buildup (OI +{fut_oi_chg:.1f}%)" if (pd.notna(fut_oi_chg) and fut_oi_chg > 2.0) else f"Bullish Momentum (+{price_chg:.1f}%)")
    elif -5.5 <= price_chg <= -0.4:
        score -= 4 if (pd.notna(fut_oi_chg) and fut_oi_chg > 2.0) else 2
        reasons.append(f"Fut Short Buildup (OI +{fut_oi_chg:.1f}%)" if (pd.notna(fut_oi_chg) and fut_oi_chg > 2.0) else f"Bearish Momentum ({price_chg:.1f}%)")

    if abs(ce_windup) > abs(ce_add) and abs(ce_windup) > 0: score += 2; reasons.append("CE Writers Unwinding")
    if pe_add > abs(pe_windup) and pe_add > 0: score += 2; reasons.append("PE Support Added")
    if abs(pe_windup) > abs(pe_add) and abs(pe_windup) > 0: score -= 2; reasons.append("PE Writers Unwinding")
    if ce_add > abs(ce_windup) and ce_add > 0: score -= 2; reasons.append("CE Resistance Added")

    if score >= 4 and not ce_near.empty:
        trapped_ce = ce_near[ce_near["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI")
        ce_near["DIST"] = (ce_near["STRIKE"] - spot).abs()
        best_row = trapped_ce.head(1).squeeze() if not trapped_ce.empty else ce_near.sort_values("DIST").head(1).squeeze()
        strike_note = f"Trapped CE ({best_row['OI_CHG_%']:.0f}% OI)" if not trapped_ce.empty else "ATM CE"
        return "🟢 BUY CALL (CE)", f"{best_row['STRIKE']:g} CE", float(best_row["CLOSE"]), score, " + ".join(reasons) + f" | {strike_note}"

    if score <= -4 and not pe_near.empty:
        trapped_pe = pe_near[pe_near["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI")
        pe_near["DIST"] = (pe_near["STRIKE"] - spot).abs()
        best_row = trapped_pe.head(1).squeeze() if not trapped_pe.empty else pe_near.sort_values("DIST").head(1).squeeze()
        strike_note = f"Trapped PE ({best_row['OI_CHG_%']:.0f}% OI)" if not trapped_pe.empty else "ATM PE"
        return "🔴 BUY PUT (PE)", f"{best_row['STRIKE']:g} PE", float(best_row["CLOSE"]), score, " + ".join(reasons) + f" | {strike_note}"

    return "NEUTRAL / WAIT", "-", 0.0, score, "No clear next-day edge"


uploaded_files = st.file_uploader("Upload Daily NSE F&O Bhavcopy ZIP or CSV files (2 to 25+ days)", type=["csv", "zip"], accept_multiple_files=True)
repo_files = [f for f in glob.glob(DATA_FOLDER) if f.lower().endswith((".csv", ".zip"))]
raw_sources = uploaded_files if uploaded_files else repo_files
dfs = [d for d in [load_fo_bhavcopy(f) for f in raw_sources] if not d.empty]

if not dfs: st.info("Upload 2 or more NSE F&O Bhavcopy ZIP/CSV files above (or push them to data/daily_fo_bhavcopy/ in GitHub) to view the scanner."); st.stop()

all_df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["INSTRUMENT", "SYMBOL", "DATE", "EXPIRY", "STRIKE", "OPTION_TYP"])
