import zipfile
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="NSE & BSE Bhavcopy Scanner", layout="wide")
st.title("📈 NSE + BSE Multi-Day Bhavcopy & Multi-Strike Options Scanner")

SECTORS = {
    "HDFCBANK": "Banking & Finance", "ICICIBANK": "Banking & Finance", "SBIN": "Banking & Finance",
    "KOTAKBANK": "Banking & Finance", "AXISBANK": "Banking & Finance", "INDUSINDBK": "Banking & Finance",
    "BANKBARODA": "Banking & Finance", "PNB": "Banking & Finance", "CANBK": "Banking & Finance",
    "BAJFINANCE": "Banking & Finance", "BAJAJFINSV": "Banking & Finance", "JIOFIN": "Banking & Finance",
    "CHOLAFIN": "Banking & Finance", "SHRIRAMFIN": "Banking & Finance", "PFC": "Banking & Finance",
    "RECLTD": "Banking & Finance", "SBILIFE": "Banking & Finance", "HDFCLIFE": "Banking & Finance",
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT",
    "LTIM": "IT", "PERSISTENT": "IT", "COFORGE": "IT", "MPHASIS": "IT", "KPITTECH": "IT",
    "RELIANCE": "Energy & Oil", "ONGC": "Energy & Oil", "NTPC": "Energy & Oil", "POWERGRID": "Energy & Oil",
    "COALINDIA": "Energy & Oil", "BPCL": "Energy & Oil", "IOC": "Energy & Oil", "GAIL": "Energy & Oil",
    "TATAPOWER": "Energy & Oil", "ADANIPOWER": "Energy & Oil", "ADANIGREEN": "Energy & Oil",
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto",
    "EICHERMOT": "Auto", "HEROMOTOCO": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto", "BHARATFORG": "Auto",
    "SUNPHARMA": "Pharma & Healthcare", "CIPLA": "Pharma & Healthcare", "DRREDDY": "Pharma & Healthcare",
    "DIVISLAB": "Pharma & Healthcare", "APOLLOHOSP": "Pharma & Healthcare", "LUPIN": "Pharma & Healthcare",
    "AUROPHARMA": "Pharma & Healthcare", "TORNTPHARM": "Pharma & Healthcare", "ZYDUSLIFE": "Pharma & Healthcare",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG", "GODREJCP": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG", "VBL": "FMCG",
    "TATASTEEL": "Metals & Mining", "JSWSTEEL": "Metals & Mining", "HINDALCO": "Metals & Mining",
    "VEDL": "Metals & Mining", "JINDALSTEL": "Metals & Mining", "NMDC": "Metals & Mining", "SAIL": "Metals & Mining",
    "LT": "Infra & Capital Goods", "SIEMENS": "Infra & Capital Goods", "ABB": "Infra & Capital Goods",
    "HAL": "Infra & Capital Goods", "BEL": "Infra & Capital Goods", "BHEL": "Infra & Capital Goods",
    "ADANIPORTS": "Infra & Capital Goods", "INDIGO": "Infra & Capital Goods", "IRCTC": "Infra & Capital Goods",
    "ULTRACEMCO": "Cement & Realty", "GRASIM": "Cement & Realty", "AMBUJACEM": "Cement & Realty",
    "DLF": "Cement & Realty", "LODHA": "Cement & Realty", "GODREJPROP": "Cement & Realty",
    "BHARTIARTL": "Telecom & Media", "INDUSTOWER": "Telecom & Media", "IDEA": "Telecom & Media",
    "TITAN": "Consumer Durables", "ASIANPAINT": "Consumer Durables", "TRENT": "Consumer Durables",
    "DMART": "Consumer Durables", "DIXON": "Consumer Durables", "POLYCAB": "Consumer Durables"
}

KEEP = ["TradDt", "TckrSymb", "SctySrs", "ISIN", "FinInstrmTp", "XpryDt", "StrkPric", "OptnTp",
        "OpnPric", "HghPric", "LwPric", "ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal", "OpnIntrst", "ChngInOpnIntrst"]

def read_upload(file_obj, name):
    res = []
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(file_obj) as z:
            for inner in z.namelist():
                if inner.lower().endswith(".csv") and not inner.startswith("__MACOSX"):
                    with z.open(inner) as f:
                        df = pd.read_csv(f, low_memory=False)
                        df.columns = df.columns.str.strip()
                        res.append(df[[c for c in KEEP if c in df.columns]].copy())
    elif name.lower().endswith(".csv"):
        df = pd.read_csv(file_obj, low_memory=False)
        df.columns = df.columns.str.strip()
        res.append(df[[c for c in KEEP if c in df.columns]].copy())
    return res

@st.cache_data(show_spinner=False)
def load_all(bse_blobs, nse_blobs):
    eq_list, fo_list = [], []
    for name, raw in bse_blobs:
        for df in read_upload(pd.io.common.BytesIO(raw), name):
            df["Src"] = "BSE"
            if "SctySrs" in df.columns:
                df = df[df["SctySrs"].astype(str).str.strip().isin(["A", "B", "X", "T", "EQ", "BE"])]
            eq_list.append(df)
    for name, raw in nse_blobs:
        for df in read_upload(pd.io.common.BytesIO(raw), name):
            if "OptnTp" in df.columns or ("FinInstrmTp" in df.columns and df["FinInstrmTp"].astype(str).isin(["STF", "STO"]).any()):
                if "FinInstrmTp" in df.columns:
                    df = df[df["FinInstrmTp"].astype(str).isin(["STF", "STO"])]
                fo_list.append(df)
            else:
                df["Src"] = "NSE"
                if "SctySrs" in df.columns:
                    df = df[df["SctySrs"].astype(str).str.strip().isin(["EQ", "BE"])]
                eq_list.append(df)

    fo_df = pd.concat(fo_list, ignore_index=True) if fo_list else pd.DataFrame()
    if not fo_df.empty:
        fo_df["TradDt"] = pd.to_datetime(fo_df["TradDt"], format="mixed").dt.strftime("%Y-%m-%d")
        fo_df["XpryDt"] = pd.to_datetime(fo_df["XpryDt"], format="mixed").dt.strftime("%Y-%m-%d")

    if eq_list:
        raw_eq = pd.concat(eq_list, ignore_index=True)
        raw_eq["TradDt"] = pd.to_datetime(raw_eq["TradDt"], format="mixed").dt.strftime("%Y-%m-%d")
        raw_eq["TckrSymb"] = raw_eq["TckrSymb"].astype(str).str.strip()
        if "ISIN" in raw_eq.columns and not raw_eq[raw_eq["Src"] == "NSE"].empty:
            m = raw_eq[raw_eq["Src"] == "NSE"][["ISIN", "TckrSymb"]].drop_duplicates("ISIN")
            raw_eq["Sym"] = raw_eq["ISIN"].map(dict(zip(m["ISIN"], m["TckrSymb"]))).fillna(raw_eq["TckrSymb"])
        else:
            raw_eq["Sym"] = raw_eq["TckrSymb"]
        eq_df = raw_eq.groupby(["TradDt", "Sym"], as_index=False).agg(
            High=("HghPric", "max"), Low=("LwPric", "min"), Close=("ClsPric", "first"),
            Prev=("PrvsClsgPric", "first"), Vol=("TtlTradgVol", "sum"), Val=("TtlTrfVal", "sum"),
            Exch=("Src", lambda x: "+".join(sorted(set(x))))
        )
    elif not fo_df.empty:
        stf = fo_df[fo_df["FinInstrmTp"] == "STF"].sort_values(["TradDt", "TckrSymb", "XpryDt"]).drop_duplicates(["TradDt", "TckrSymb"])
        eq_df = pd.DataFrame({
            "TradDt": stf["TradDt"].values, "Sym": stf["TckrSymb"].astype(str).str.strip().values,
            "High": stf["HghPric"].values, "Low": stf["LwPric"].values, "Close": stf["ClsPric"].values,
            "Prev": stf["PrvsClsgPric"].values, "Vol": stf["TtlTradgVol"].values, "Val": stf["TtlTrfVal"].values, "Exch": "NSE-FO"
        })
    else:
        eq_df = pd.DataFrame()
    return eq_df, fo_df

def get_strikes(day_fo, sym, spot, opt_tp):
    if day_fo.empty:
        return {"At-The-Money": "Upload F&O", "1-Step Out-Of-The-Money": "Upload F&O", "Highest OI Buildup Strike": "Upload F&O", "PCR": np.nan}
    opts = day_fo[(day_fo["TckrSymb"].astype(str).str.strip() == sym) & (day_fo["OptnTp"].astype(str).str.strip() == opt_tp)].copy()
    if opts.empty:
        return {"At-The-Money": "Non-F&O", "1-Step Out-Of-The-Money": "Non-F&O", "Highest OI Buildup Strike": "Non-F&O", "PCR": np.nan}
    exp = opts["XpryDt"].min()
    sub = opts[opts["XpryDt"] == exp].sort_values("StrkPric").reset_index(drop=True)
    all_e = day_fo[(day_fo["TckrSymb"].astype(str).str.strip() == sym) & (day_fo["XpryDt"] == exp)]
    ce_oi = all_e[all_e["OptnTp"] == "CE"]["OpnIntrst"].sum()
    pe_oi = all_e[all_e["OptnTp"] == "PE"]["OpnIntrst"].sum()
    pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else np.nan
    atm_i = (sub["StrkPric"] - spot).abs().idxmin()
    otm_i = min(atm_i + 1, len(sub) - 1) if opt_tp == "CE" else max(atm_i - 1, 0)
    oi_i = sub["ChngInOpnIntrst"].idxmax()
    fmt = lambda r: f"{int(r['StrkPric']) if float(r['StrkPric']).is_integer() else r['StrkPric']} {opt_tp} @ ₹{r['ClsPric']:.2f}"
    return {
        "At-The-Money": fmt(sub.loc[atm_i]),
        "1-Step Out-Of-The-Money": fmt(sub.loc[otm_i]),
        "Highest OI Buildup Strike": f"{fmt(sub.loc[oi_i])} ({int(sub.loc[oi_i]['ChngInOpnIntrst']):+,} OI)",
        "PCR": pcr
    }

c1, c2, c3 = st.columns(3)
bse_files = c1.file_uploader("1. Upload BSE Bhavcopy (.csv/.zip)", type=["csv", "zip"], accept_multiple_files=True)
nse_files = c2.file_uploader("2. Upload NSE Bhavcopy Equity & F&O (.csv/.zip)", type=["csv", "zip"], accept_multiple_files=True)
sec_file = c3.file_uploader("3. Optional Sector CSV", type=["csv"])

sec_map = dict(zip(pd.read_csv(sec_file)["TckrSymb"], pd.read_csv(sec_file)["Sector"])) if sec_file else SECTORS

if bse_files or nse_files:
    eq_df, fo_df = load_all(tuple((f.name, f.getvalue()) for f in bse_files), tuple((f.name, f.getvalue()) for f in nse_files))
    if not eq_df.empty:
        eq_df = eq_df.sort_values(["Sym", "TradDt"])
        eq_df["Chg%"] = ((eq_df["Close"] - eq_df["Prev"]) / eq_df["Prev"]) * 100
        eq_df["Vol_Spike"] = eq_df["Vol"] / eq_df.groupby("Sym")["Vol"].transform(lambda x: x.rolling(5, min_periods=1).mean())
        eq_df["Cr"] = eq_df["Val"] / 1e7
        eq_df["CLV"] = np.where((eq_df["High"] - eq_df["Low"]) > 0, (eq_df["Close"] - eq_df["Low"]) / (eq_df["High"] - eq_df["Low"]), 0.5)
        eq_df["Sector"] = eq_df["Sym"].map(sec_map).fillna("Other / F&O")

        dt = st.selectbox("📅 Select Date", sorted(eq_df["TradDt"].unique(), reverse=True))
        d_eq = eq_df[eq_df["TradDt"] == dt].copy()
        d_fo = fo_df[fo_df["TradDt"] == dt] if not fo_df.empty else pd.DataFrame()

        if not d_fo.empty and "FinInstrmTp" in d_fo.columns:
            futs = d_fo[d_fo["FinInstrmTp"] == "STF"].groupby("TckrSymb", as_index=False)["ChngInOpnIntrst"].sum()
            d_eq = d_eq.merge(futs, left_on="Sym", right_on="TckrSymb", how="left")


            d_eq["OI_Signal"] = np.where(d_eq["ChngInOpnIntrst"].isna(), "Cash",
                np.where((d_eq["Chg%"] > 0) & (d_eq["ChngInOpnIntrst"] > 0), "🟢 Long Buildup",
                np.where((d_eq["Chg%"] < 0) & (d_eq["ChngInOpnIntrst"] > 0), "🔴 Short Buildup",
                np.where(d_eq["Chg%"] > 0, "🟡 Short Covering", "🟠 Long Unwinding"))))
        else:
            d_eq["OI_Signal"] = "N/A"

        liq = d_eq[d_eq["Cr"] >= 5.0] if not d_eq[d_eq["Cr"] >= 5.0].empty else d_eq
        st.subheader(f"🔥 Top 10 Gainers & Losers ({dt})")
        g_col, l_col = st.columns(2)
        g_col.dataframe(liq.nlargest(10, "Chg%")[["Sym", "Exch", "Close", "Chg%", "Vol_Spike", "OI_Signal"]], use_container_width=True)
        l_col.dataframe(liq.nsmallest(10, "Chg%")[["Sym", "Exch", "Close", "Chg%", "Vol_Spike", "OI_Signal"]], use_container_width=True)

        st.subheader("🏭 Sector Performance (Click row to view stocks)")
        sec_tbl = d_eq.groupby("Sector", as_index=False).agg(Avg_Chg=("Chg%", "mean"), Turnover_Cr=("Cr", "sum"), Adv=("Chg%", lambda x: (x > 0).sum()), Dec=("Chg%", lambda x: (x < 0).sum())).sort_values("Avg_Chg", ascending=False)
        ev = st.dataframe(sec_tbl, on_select="rerun", selection_mode="single-row", use_container_width=True)
        if ev.selection.rows:
            chosen = sec_tbl.iloc[ev.selection.rows.pop()]["Sector"]
            st.markdown(f"**Stocks in {chosen}**")
            st.dataframe(d_eq[d_eq["Sector"] == chosen].sort_values("Chg%", ascending=False)[["Sym", "Exch", "Close", "Chg%", "Vol_Spike", "Cr", "OI_Signal"]], use_container_width=True)

        st.subheader("🎯 Next-Day High-Probability Setups (CE / PE Strikes)")
        bull = liq[(liq["Chg%"] >= 1.5) & (liq["Vol_Spike"] >= 1.5) & (liq["CLV"] >= 0.75)].nlargest(8, "Vol_Spike").reset_index(drop=True)
        bear = liq[(liq["Chg%"] <= -1.5) & (liq["Vol_Spike"] >= 1.5) & (liq["CLV"] <= 0.25)].nlargest(8, "Vol_Spike").reset_index(drop=True)

        st.success("🟢 Next-Day BUY (CE)")
        if not bull.empty:
            st.dataframe(pd.concat([bull[["Sym", "Close", "Chg%", "Vol_Spike", "OI_Signal"]], pd.DataFrame([get_strikes(d_fo, r["Sym"], r["Close"], "CE") for _, r in bull.iterrows()])], axis=1), use_container_width=True)
        st.error("🔴 Next-Day SELL (PE)")
        if not bear.empty:
            st.dataframe(pd.concat([bear[["Sym", "Close", "Chg%", "Vol_Spike", "OI_Signal"]], pd.DataFrame([get_strikes(d_fo, r["Sym"], r["Close"], "PE") for _, r in bear.iterrows()])], axis=1), use_container_width=True)

        st.subheader("🏦 Institutional Turnover & Volume Spikes")
        st.dataframe(liq[(liq["Vol_Spike"] >= 2.0) & (liq["Cr"] >= 50)].sort_values("Cr", ascending=False).head(15)[["Sym", "Sector", "Close", "Chg%", "Vol_Spike", "Cr", "OI_Signal"]], use_container_width=True)
else:
    st.info("Upload files above to start.")
