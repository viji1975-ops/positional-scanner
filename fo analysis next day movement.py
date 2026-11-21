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
            if not csv_files: return pd.DataFrame()
            with z.open(next(iter(csv_files))) as f: df = pd.read_csv(f, low_memory=False)
    else:
        df = pd.read_csv(file_obj, low_memory=False)

    df.columns = [c.strip().upper() for c in df.columns]

    if "TCKRSYMB" in df.columns:
        inst_col = "FININSTRMTP"
        df[inst_col] = df[inst_col].astype(str).str.strip().str.upper()
        df = df[df[inst_col].isin(["STF", "STO", "FUTSTK", "OPTSTK"])].copy()
        out = pd.DataFrame()
        out["INSTRUMENT"] = df[inst_col].map({"STF": "FUTSTK", "FUTSTK": "FUTSTK", "STO": "OPTSTK", "OPTSTK": "OPTSTK"})
        out["SYMBOL"] = df["TCKRSYMB"].astype(str).str.strip()
        out["DATE"] = pd.to_datetime(df["TRADDT"], errors="coerce")
        out["EXPIRY"] = pd.to_datetime(df["XPRYDT"], errors="coerce")
        out["STRIKE"] = pd.to_numeric(df["STRKPRIC"], errors="coerce").fillna(0.0).astype(float)
        out["OPTION_TYP"] = df["OPTNTP"].fillna("XX").astype(str).str.strip().str.upper()
        out["CLOSE"] = pd.to_numeric(df["CLSPRIC"], errors="coerce").astype(float)
        out["HIGH"] = pd.to_numeric(df["HGHPRIC"] if "HGHPRIC" in df.columns else df["CLSPRIC"], errors="coerce").astype(float)
        out["LOW"] = pd.to_numeric(df["LWPRIC"] if "LWPRIC" in df.columns else df["CLSPRIC"], errors="coerce").astype(float)
        out["OPEN_INT"] = pd.to_numeric(df["OPNINTRST"], errors="coerce").fillna(0.0).astype(float)
        out["CHG_IN_OI"] = pd.to_numeric(df["CHNGINOPNINTRST"], errors="coerce").fillna(0.0).astype(float)
        vol_col = "TTLTRADGVOL" if "TTLTRADGVOL" in df.columns else ("TTLTRFVAL" if "TTLTRFVAL" in df.columns else None)
        out["VOLUME"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(1.0).astype(float) if vol_col else 1.0
        return out.dropna(subset=["DATE", "EXPIRY", "CLOSE"])

    if "INSTRUMENT" in df.columns:
        df["INSTRUMENT"] = df["INSTRUMENT"].astype(str).str.strip().str.upper()
        df = df[df["INSTRUMENT"].isin(["FUTSTK", "OPTSTK"])].copy()
        out = pd.DataFrame()
        out["INSTRUMENT"] = df["INSTRUMENT"]
        out["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        out["DATE"] = pd.to_datetime(df["TIMESTAMP"], errors="coerce")
        out["EXPIRY"] = pd.to_datetime(df["EXPIRY_DT"], errors="coerce")
        out["STRIKE"] = pd.to_numeric(df["STRIKE_PR"], errors="coerce").fillna(0.0).astype(float)
        out["OPTION_TYP"] = df["OPTION_TYP"].fillna("XX").astype(str).str.strip().str.upper()
        out["CLOSE"] = pd.to_numeric(df["CLOSE"], errors="coerce").astype(float)
        out["HIGH"] = pd.to_numeric(df["HIGH"] if "HIGH" in df.columns else df["CLOSE"], errors="coerce").astype(float)
        out["LOW"] = pd.to_numeric(df["LOW"] if "LOW" in df.columns else df["CLOSE"], errors="coerce").astype(float)
        out["OPEN_INT"] = pd.to_numeric(df["OPEN_INT"], errors="coerce").fillna(0.0).astype(float)
        out["CHG_IN_OI"] = pd.to_numeric(df["CHG_IN_OI"], errors="coerce").fillna(0.0).astype(float)
        out["VOLUME"] = pd.to_numeric(df["CONTRACTS"], errors="coerce").fillna(0.0).astype(float)
        return out.dropna(subset=["DATE", "EXPIRY", "CLOSE"])

    return pd.DataFrame()


def compute_institutional_profile(sym_opts, price_chg_1d):
    if sym_opts.empty:
        return {"PCR": 0.0, "MAX_PAIN": 0.0, "PUT_FLOOR": "-", "CALL_WALL": "-", "NET_PE_CHG": 0.0, "NET_CE_CHG": 0.0, "INST_BIAS": "NO DATA"}
    ce = sym_opts[sym_opts["OPTION_TYP"] == "CE"]
    pe = sym_opts[sym_opts["OPTION_TYP"] == "PE"]
    tot_ce_oi, tot_pe_oi = ce["OPEN_INT"].sum(), pe["OPEN_INT"].sum()
    pcr = round(tot_pe_oi / tot_ce_oi, 2) if tot_ce_oi > 0 else 0.0
    net_ce_chg, net_pe_chg = ce["CHG_IN_OI"].sum(), pe["CHG_IN_OI"].sum()

    put_floor = f"{next(iter(pe.sort_values('OPEN_INT', ascending=False).to_dict('records')))['STRIKE']:g} PE" if not pe.empty else "-"
    call_wall = f"{next(iter(ce.sort_values('OPEN_INT', ascending=False).to_dict('records')))['STRIKE']:g} CE" if not ce.empty else "-"

    strikes = sorted(sym_opts["STRIKE"].unique())
    max_pain = strikes[0] if strikes else 0.0
    if strikes:
        ce_g = ce.groupby("STRIKE")["OPEN_INT"].sum()
        pe_g = pe.groupby("STRIKE")["OPEN_INT"].sum()
        best_pain = None
        for s in strikes:
            c_loss = sum((s - k) * v for k, v in ce_g.items() if s > k)
            p_loss = sum((k - s) * v for k, v in pe_g.items() if s < k)
            tot_loss = c_loss + p_loss
            if best_pain is None or tot_loss < best_pain:
                best_pain, max_pain = tot_loss, s

    if pcr >= 1.25 and net_pe_chg > net_ce_chg: bias = "🟢 STRONG BULLISH (Heavy Put Writing)"
    elif pcr >= 0.95 and net_pe_chg > 0 and net_ce_chg <= 0: bias = "🟢 BULLISH (Put Add + Call Unwind)"
    elif pcr <= 0.65 and net_ce_chg > net_pe_chg: bias = "🔴 STRONG BEARISH (Heavy Call Writing)"
    elif pcr <= 0.85 and net_ce_chg > 0 and net_pe_chg <= 0: bias = "🔴 BEARISH (Call Add + Put Unwind)"
    elif net_ce_chg > 0 and net_pe_chg > 0: bias = "🟡 RANGEBOUND (Short Strangle)"
    else: bias = "⚪ NEUTRAL / MIXED"

    return {"PCR": pcr, "MAX_PAIN": float(max_pain), "PUT_FLOOR": put_floor, "CALL_WALL": call_wall, "NET_PE_CHG": float(net_pe_chg), "NET_CE_CHG": float(net_ce_chg), "INST_BIAS": bias}


def compute_eod_sentiment(sym_opts, price_chg_1d):
    if sym_opts.empty or pd.isna(price_chg_1d):
        return {"OI_SCORE": 0, "SENTIMENT": "NEUTRAL / SIDEWAYS", "TOP_CE_SIGNALS": "None", "TOP_PE_SIGNALS": "None"}
    ce_opts = sym_opts[sym_opts["OPTION_TYP"] == "CE"].copy()
    pe_opts = sym_opts[sym_opts["OPTION_TYP"] == "PE"].copy()
    ce_opts["ABS_OI"] = ce_opts["CHG_IN_OI"].abs()
    pe_opts["ABS_OI"] = pe_opts["CHG_IN_OI"].abs()
    top_ce = ce_opts.sort_values("ABS_OI", ascending=False).head(3)
    top_pe = pe_opts.sort_values("ABS_OI", ascending=False).head(3)

    ce_map = {"Massive Windup": 2, "Windup": 1, "Massive Addition": -2, "Addition": -1}
    pe_map = {"Massive Addition": 2, "Addition": 1, "Massive Windup": -2, "Windup": -1}
    oi_score = int(sum(ce_map.get(x, 0) for x in top_ce["OI_ACTION"]) + sum(pe_map.get(x, 0) for x in top_pe["OI_ACTION"]))

    ce_list = [f"{int(r['STRIKE'])}CE ({r['OI_ACTION']})" for _, r in top_ce.iterrows() if r["OI_ACTION"] != "Neutral"]
    pe_list = [f"{int(r['STRIKE'])}PE ({r['OI_ACTION']})" for _, r in top_pe.iterrows() if r["OI_ACTION"] != "Neutral"]
    ce_summary = ", ".join(ce_list) if ce_list else "Neutral"
    pe_summary = ", ".join(pe_list) if pe_list else "Neutral"

    sentiment = "NEUTRAL / SIDEWAYS"
    if price_chg_1d > 0.5: sentiment = "STRONG BULLISH" if oi_score >= 3 else ("BULLISH" if oi_score >= 1 else ("REVERSAL WATCH" if oi_score <= -2 else "NEUTRAL / SIDEWAYS"))
    elif price_chg_1d < -0.5: sentiment = "STRONG BEARISH" if oi_score <= -3 else ("BEARISH" if oi_score <= -1 else ("REVERSAL WATCH" if oi_score >= 2 else "NEUTRAL / SIDEWAYS"))
    elif abs(oi_score) >= 3: sentiment = "REVERSAL WATCH"

    return {"OI_SCORE": oi_score, "SENTIMENT": sentiment, "TOP_CE_SIGNALS": ce_summary, "TOP_PE_SIGNALS": pe_summary}


def evaluate_next_day_setup(fut_row, sym_opts):
    price_chg, fut_oi_chg, spot = fut_row["1D_CHG_%"], fut_row["FUT_OI_CHG_%"], fut_row["CLOSE"]
    if sym_opts.empty or pd.isna(price_chg):
        return {"NEXT_DAY_ACTION": "NO SETUP", "BEST_STRIKE": "-", "EOD_PREMIUM": 0.0, "CONVICTION_SCORE": 0, "SETUP_REASON": "Upload 2+ days for Next-Day signal"}
    near_opts = sym_opts[(sym_opts["STRIKE"] >= spot * 0.94) & (sym_opts["STRIKE"] <= spot * 1.06) & (sym_opts["VOLUME"] > 0)].copy()
    if near_opts.empty:
        return {"NEXT_DAY_ACTION": "NO SETUP", "BEST_STRIKE": "-", "EOD_PREMIUM": 0.0, "CONVICTION_SCORE": 0, "SETUP_REASON": "Illiquid Strikes"}
    if abs(price_chg) > 5.5:
        return {"NEXT_DAY_ACTION": "EXHAUSTED (SKIP)", "BEST_STRIKE": "-", "EOD_PREMIUM": 0.0, "CONVICTION_SCORE": 0, "SETUP_REASON": f"Already moved {price_chg:.1f}% today"}

    ce_near, pe_near = near_opts[near_opts["OPTION_TYP"] == "CE"].copy(), near_opts[near_opts["OPTION_TYP"] == "PE"].copy()
    ce_windup, pe_add = ce_near[ce_near["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum(), pe_near[pe_near["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()
    pe_windup, ce_add = pe_near[pe_near["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum(), ce_near[ce_near["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()

    score, reasons = 0, []
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
        best_row = next(iter((trapped_ce if not trapped_ce.empty else ce_near.sort_values("DIST")).to_dict("records")))
        return {"NEXT_DAY_ACTION": "🟢 BUY CALL (CE)", "BEST_STRIKE": f"{best_row['STRIKE']:g} CE", "EOD_PREMIUM": float(best_row["CLOSE"]), "CONVICTION_SCORE": int(score), "SETUP_REASON": " + ".join(reasons)}

    if score <= -4 and not pe_near.empty:
        trapped_pe = pe_near[pe_near["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI")
        pe_near["DIST"] = (pe_near["STRIKE"] - spot).abs()
        best_row = next(iter((trapped_pe if not trapped_pe.empty else pe_near.sort_values("DIST")).to_dict("records")))
        return {"NEXT_DAY_ACTION": "🔴 BUY PUT (PE)", "BEST_STRIKE": f"{best_row['STRIKE']:g} PE", "EOD_PREMIUM": float(best_row["CLOSE"]), "CONVICTION_SCORE": int(score), "SETUP_REASON": " + ".join(reasons)}

    return {"NEXT_DAY_ACTION": "NEUTRAL / WAIT", "BEST_STRIKE": "-", "EOD_PREMIUM": 0.0, "CONVICTION_SCORE": int(score), "SETUP_REASON": "No clear next-day edge"}


uploaded_files = st.file_uploader("Upload Daily NSE F&O Bhavcopy ZIP or CSV files (2 to 25+ days)", type=["csv", "zip"], accept_multiple_files=True)
raw_sources = uploaded_files if uploaded_files else [f for f in glob.glob(DATA_FOLDER) if f.lower().endswith((".csv", ".zip"))]
dfs = [d for d in [load_fo_bhavcopy(f) for f in raw_sources] if not d.empty]
if not dfs: st.info("Upload 2 or more NSE F&O Bhavcopy ZIP/CSV files above to view the scanner."); st.stop()

all_df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["INSTRUMENT", "SYMBOL", "DATE", "EXPIRY", "STRIKE", "OPTION_TYP"])
fut_df = all_df[all_df["INSTRUMENT"] == "FUTSTK"].sort_values(["SYMBOL", "DATE", "EXPIRY"]).drop_duplicates(subset=["SYMBOL", "DATE"]).copy()
g_close, g_oi = fut_df.groupby("SYMBOL")["CLOSE"], fut_df.groupby("SYMBOL")["OPEN_INT"]
for col_n, lag in [("1D_CHG_%", 1), ("5D_CHG_%", 5), ("20D_CHG_%", 20), ("22D_CHG_%", 22)]: fut_df[col_n] = (fut_df["CLOSE"] - g_close.shift(lag)) / g_close.shift(lag) * 100
fut_df["FUT_OI_CHG_%"] = (fut_df["OPEN_INT"] - g_oi.shift(1)) / g_oi.shift(1) * 100

latest_date = all_df["DATE"].max()
latest_fut = fut_df[fut_df["DATE"] == latest_date].reset_index(drop=True)
opt_df = all_df[(all_df["INSTRUMENT"] == "OPTSTK") & (all_df["DATE"] == latest_date)].copy()
near_exp_map = opt_df.sort_values("EXPIRY").drop_duplicates("SYMBOL").set_index("SYMBOL")["EXPIRY"]
opt_df = opt_df[(opt_df["EXPIRY"] == opt_df["SYMBOL"].map(near_exp_map)) & (opt_df["OPEN_INT"] > 0)].copy()
opt_df["PREV_OI"] = opt_df["OPEN_INT"] - opt_df["CHG_IN_OI"]
opt_df["OI_CHG_%"] = np.where(opt_df["PREV_OI"] > 0, (opt_df["CHG_IN_OI"] / opt_df["PREV_OI"]) * 100, 0.0)
opt_df["OI_ACTION"] = "Neutral"
opt_df.loc[opt_df["OI_CHG_%"] >= 5, "OI_ACTION"] = "Addition"
opt_df.loc[(opt_df["OI_CHG_%"] >= 20) | ((opt_df["PREV_OI"] <= 0) & (opt_df["CHG_IN_OI"] > 0)), "OI_ACTION"] = "Massive Addition"
opt_df.loc[opt_df["OI_CHG_%"] <= -5, "OI_ACTION"] = "Windup"
opt_df.loc[opt_df["OI_CHG_%"] <= -20, "OI_ACTION"] = "Massive Windup"

eod_list = [compute_eod_sentiment(opt_df[opt_df["SYMBOL"] == r["SYMBOL"]], r["1D_CHG_%"]) for _, r in latest_fut.iterrows()]
nd_list = [evaluate_next_day_setup(r, opt_df[opt_df["SYMBOL"] == r["SYMBOL"]]) for _, r in latest_fut.iterrows()]
inst_list = [compute_institutional_profile(opt_df[opt_df["SYMBOL"] == r["SYMBOL"]], r["1D_CHG_%"]) for _, r in latest_fut.iterrows()]
for k in ["OI_SCORE", "SENTIMENT", "TOP_CE_SIGNALS", "TOP_PE_SIGNALS"]: latest_fut[k] = [d[k] for d in eod_list]
for k in ["NEXT_DAY_ACTION", "BEST_STRIKE", "EOD_PREMIUM", "CONVICTION_SCORE", "SETUP_REASON"]: latest_fut[k] = [d[k] for d in nd_list]
for k in ["PCR", "MAX_PAIN", "PUT_FLOOR", "CALL_WALL", "NET_PE_CHG", "NET_CE_CHG", "INST_BIAS"]: latest_fut[k] = [d[k] for d in inst_list]

st.info(f"📅 Data Up To: {latest_date.strftime('%d %b %Y')} | Trading Days: {all_df['DATE'].nunique()} | Futures: {len(latest_fut)} | Options: {len(opt_df)}")
tab1, tab2, tab3 = st.tabs(["🎯 Next-Day Option Buying Predictor", "📊 EOD Movers & Auto-Sentiment", "🏛️ Institutional Bias & Strike Explorer"])

c1, c2 = tab1.columns(2)
c1.markdown("### 🟢 Next-Day CALL Buying (BUY CE)")
c1.dataframe(latest_fut[latest_fut["NEXT_DAY_ACTION"] == "🟢 BUY CALL (CE)"].sort_values(by=["CONVICTION_SCORE", "1D_CHG_%"], ascending=False)[["SYMBOL", "CLOSE", "HIGH", "BEST_STRIKE", "EOD_PREMIUM", "CONVICTION_SCORE", "SETUP_REASON"]], use_container_width=True, hide_index=True)
c2.markdown("### 🔴 Next-Day PUT Buying (BUY PE)")
c2.dataframe(latest_fut[latest_fut["NEXT_DAY_ACTION"] == "🔴 BUY PUT (PE)"].sort_values(by=["CONVICTION_SCORE", "1D_CHG_%"], ascending=[True, True])[["SYMBOL", "CLOSE", "LOW", "BEST_STRIKE", "EOD_PREMIUM", "CONVICTION_SCORE", "SETUP_REASON"]], use_container_width=True, hide_index=True)

col1, col2 = tab2.columns(2)
col1.markdown("### 🟢 Top Gainers (1D %)")
col1.dataframe(latest_fut.nlargest(8, "1D_CHG_%")[["SYMBOL", "CLOSE", "1D_CHG_%", "5D_CHG_%", "22D_CHG_%", "SENTIMENT"]], use_container_width=True, hide_index=True)
col2.markdown("### 🔴 Top Losers (1D %)")
col2.dataframe(latest_fut.nsmallest(8, "1D_CHG_%")[["SYMBOL", "CLOSE", "1D_CHG_%", "5D_CHG_%", "22D_CHG_%", "SENTIMENT"]], use_container_width=True, hide_index=True)
sentiment_filter = tab2.multiselect("Filter by EOD Auto-Sentiment", options=["STRONG BULLISH", "BULLISH", "STRONG BEARISH", "BEARISH", "REVERSAL WATCH", "NEUTRAL / SIDEWAYS"], default=["STRONG BULLISH", "STRONG BEARISH", "REVERSAL WATCH", "BULLISH", "BEARISH", "NEUTRAL / SIDEWAYS"])
