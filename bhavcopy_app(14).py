import zipfile
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="NSE & BSE Bhavcopy Scanner", layout="wide")
st.title("📈 NSE + BSE + all  indicies Multi-Day Bhavcopy & Multi-Strike Options Scanner")

SECTORS = {
    "HDFCBANK": "Banking & Finance", "ICICIBANK": "Banking & Finance", "SBIN": "Banking & Finance",
    "KOTAKBANK": "Banking & Finance", "AXISBANK": "Banking & Finance", "INDUSINDBK": "Banking & Finance",
    "BANKBARODA": "Banking & Finance", "PNB": "Banking & Finance", "CANBK": "Banking & Finance",
    "UNIONBANK": "Banking & Finance", "INDIANB": "Banking & Finance", "BANKINDIA": "Banking & Finance",
    "FEDERALBNK": "Banking & Finance", "IDFCFIRSTB": "Banking & Finance", "BANDHANBNK": "Banking & Finance",
    "AUBANK": "Banking & Finance", "RBLBANK": "Banking & Finance", "BAJFINANCE": "Banking & Finance",
    "BAJAJFINSV": "Banking & Finance", "JIOFIN": "Banking & Finance", "CHOLAFIN": "Banking & Finance",
    "SHRIRAMFIN": "Banking & Finance", "MUTHOOTFIN": "Banking & Finance", "MANAPPURAM": "Banking & Finance",
    "PFC": "Banking & Finance", "RECLTD": "Banking & Finance", "IREDA": "Banking & Finance",
    "IRFC": "Banking & Finance", "SBILIFE": "Banking & Finance", "HDFCLIFE": "Banking & Finance",
    "ICICIPRULI": "Banking & Finance", "ICICIGI": "Banking & Finance", "SBICARD": "Banking & Finance",
    "ABCAPITAL": "Banking & Finance", "LTF": "Banking & Finance", "M&MFIN": "Banking & Finance",
    "LICHSGFIN": "Banking & Finance", "CANFINHOME": "Banking & Finance", "POONAWALLA": "Banking & Finance",
    "PEL": "Banking & Finance", "BSE": "Banking & Finance", "MCX": "Banking & Finance",
    "CDSL": "Banking & Finance", "ANGELONE": "Banking & Finance", "CAMS": "Banking & Finance",
    "HDFCAMC": "Banking & Finance", "NAM-INDIA": "Banking & Finance", "MFSL": "Banking & Finance",
    "TCS": "IT & Tech", "INFY": "IT & Tech", "HCLTECH": "IT & Tech", "WIPRO": "IT & Tech",
    "TECHM": "IT & Tech", "LTIM": "IT & Tech", "PERSISTENT": "IT & Tech", "COFORGE": "IT & Tech",
    "MPHASIS": "IT & Tech", "KPITTECH": "IT & Tech", "LTTS": "IT & Tech", "TATAELXSI": "IT & Tech",
    "OFSS": "IT & Tech", "CYIENT": "IT & Tech", "BSOFT": "IT & Tech", "SONATSOFTW": "IT & Tech",
    "NAUKRI": "IT & Tech", "ZOMATO": "IT & Tech", "ETERNAL": "IT & Tech", "SWIGGY": "IT & Tech",
    "PAYTM": "IT & Tech", "POLICYBZR": "IT & Tech", "DELHIVERY": "IT & Tech", "NYKAA": "IT & Tech",
    "RELIANCE": "Energy & Power", "ONGC": "Energy & Power", "NTPC": "Energy & Power",
    "POWERGRID": "Energy & Power", "COALINDIA": "Energy & Power", "BPCL": "Energy & Power",
    "IOC": "Energy & Power", "HINDPETRO": "Energy & Power", "GAIL": "Energy & Power",
    "PETRONET": "Energy & Power", "IGL": "Energy & Power", "MGL": "Energy & Power",
    "GUJGASLTD": "Energy & Power", "TATAPOWER": "Energy & Power", "ADANIPOWER": "Energy & Power",
    "ADANIGREEN": "Energy & Power", "ADANIENSOL": "Energy & Power", "JSWENERGY": "Energy & Power",
    "NHPC": "Energy & Power", "SJVN": "Energy & Power", "TORNTPOWER": "Energy & Power",
    "CESC": "Energy & Power", "IEX": "Energy & Power", "OIL": "Energy & Power",
    "MARUTI": "Auto & Ancillaries", "TATAMOTORS": "Auto & Ancillaries", "M&M": "Auto & Ancillaries",
    "BAJAJ-AUTO": "Auto & Ancillaries", "EICHERMOT": "Auto & Ancillaries", "HEROMOTOCO": "Auto & Ancillaries",
    "TVSMOTOR": "Auto & Ancillaries", "ASHOKLEY": "Auto & Ancillaries", "ESCORTS": "Auto & Ancillaries",
    "BHARATFORG": "Auto & Ancillaries", "MOTHERSON": "Auto & Ancillaries", "BOSCHLTD": "Auto & Ancillaries",
    "MRF": "Auto & Ancillaries", "BALKRISIND": "Auto & Ancillaries", "APOLLOTYRE": "Auto & Ancillaries",
    "EXIDEIND": "Auto & Ancillaries", "ARE&M": "Auto & Ancillaries", "SONACOMS": "Auto & Ancillaries",
    "TIINDIA": "Auto & Ancillaries", "UNOMINDA": "Auto & Ancillaries", "SUNDRMFAST": "Auto & Ancillaries",
    "SUNPHARMA": "Pharma & Healthcare", "CIPLA": "Pharma & Healthcare", "DRREDDY": "Pharma & Healthcare",
    "DIVISLAB": "Pharma & Healthcare", "APOLLOHOSP": "Pharma & Healthcare", "LUPIN": "Pharma & Healthcare",
    "AUROPHARMA": "Pharma & Healthcare", "TORNTPHARM": "Pharma & Healthcare", "ZYDUSLIFE": "Pharma & Healthcare",
    "ALKEM": "Pharma & Healthcare", "BIOCON": "Pharma & Healthcare", "MAXHEALTH": "Pharma & Healthcare",
    "FORTIS": "Pharma & Healthcare", "MANKIND": "Pharma & Healthcare", "GLENMARK": "Pharma & Healthcare",
    "IPCALAB": "Pharma & Healthcare", "LAURUSLABS": "Pharma & Healthcare", "GRANULES": "Pharma & Healthcare",
    "SYNGENE": "Pharma & Healthcare", "LALPATHLAB": "Pharma & Healthcare", "METROPOLIS": "Pharma & Healthcare",
    "HINDUNILVR": "FMCG & Retail", "ITC": "FMCG & Retail", "NESTLEIND": "FMCG & Retail",
    "BRITANNIA": "FMCG & Retail", "TATACONSUM": "FMCG & Retail", "GODREJCP": "FMCG & Retail",
    "DABUR": "FMCG & Retail", "MARICO": "FMCG & Retail", "VBL": "FMCG & Retail",
    "COLPAL": "FMCG & Retail", "UNITDSPR": "FMCG & Retail", "UBL": "FMCG & Retail",
    "JUBLFOOD": "FMCG & Retail", "DEVYANI": "FMCG & Retail", "WESTLIFE": "FMCG & Retail",
    "DMART": "FMCG & Retail", "TRENT": "FMCG & Retail", "ABFRL": "FMCG & Retail",
    "PAGEIND": "FMCG & Retail", "BATAINDIA": "FMCG & Retail", "TITAN": "FMCG & Retail",
    "KALYANKJIL": "FMCG & Retail", "INDHOTEL": "FMCG & Retail",
    "TATASTEEL": "Metals & Chemicals", "JSWSTEEL": "Metals & Chemicals", "HINDALCO": "Metals & Chemicals",
    "VEDL": "Metals & Chemicals", "JINDALSTEL": "Metals & Chemicals", "NMDC": "Metals & Chemicals",
    "SAIL": "Metals & Chemicals", "NATIONALUM": "Metals & Chemicals", "HINDZINC": "Metals & Chemicals",
    "HINDCOPPER": "Metals & Chemicals", "APLAPOLLO": "Metals & Chemicals", "JSL": "Metals & Chemicals",
    "PIDILITIND": "Metals & Chemicals", "SRF": "Metals & Chemicals", "PIIND": "Metals & Chemicals",
    "UPL": "Metals & Chemicals", "DEEPAKNTR": "Metals & Chemicals", "NAVINFLUOR": "Metals & Chemicals",
    "TATACHEM": "Metals & Chemicals", "AARTIIND": "Metals & Chemicals", "ATUL": "Metals & Chemicals",
    "CHAMBLFERT": "Metals & Chemicals", "COROMANDEL": "Metals & Chemicals", "GNFC": "Metals & Chemicals",
    "LT": "Defence, Infra & Cap Goods", "HAL": "Defence, Infra & Cap Goods", "BEL": "Defence, Infra & Cap Goods",
    "BHEL": "Defence, Infra & Cap Goods", "MAZDOCK": "Defence, Infra & Cap Goods",
    "COCHINSHIP": "Defence, Infra & Cap Goods", "DATAPATTNS": "Defence, Infra & Cap Goods",
    "BDL": "Defence, Infra & Cap Goods", "SOLARINDS": "Defence, Infra & Cap Goods",
    "SIEMENS": "Defence, Infra & Cap Goods", "ABB": "Defence, Infra & Cap Goods",
    "CUMMINSIND": "Defence, Infra & Cap Goods", "CGPOWER": "Defence, Infra & Cap Goods",
    "THERMAX": "Defence, Infra & Cap Goods", "ASTRAL": "Defence, Infra & Cap Goods",
    "SUPREMEIND": "Defence, Infra & Cap Goods", "POLYCAB": "Defence, Infra & Cap Goods",
    "KEI": "Defence, Infra & Cap Goods", "HAVELLS": "Defence, Infra & Cap Goods",
    "VOLTAS": "Defence, Infra & Cap Goods", "BLUESTARCO": "Defence, Infra & Cap Goods",
    "AMBER": "Defence, Infra & Cap Goods", "DIXON": "Defence, Infra & Cap Goods",
    "CROMPTON": "Defence, Infra & Cap Goods", "WHIRLPOOL": "Defence, Infra & Cap Goods",
    "ADANIPORTS": "Defence, Infra & Cap Goods", "ADANIENT": "Defence, Infra & Cap Goods",
    "INDIGO": "Defence, Infra & Cap Goods", "IRCTC": "Defence, Infra & Cap Goods",
    "CONCOR": "Defence, Infra & Cap Goods", "RVNL": "Defence, Infra & Cap Goods",
    "GMRAIRPORT": "Defence, Infra & Cap Goods", "NCC": "Defence, Infra & Cap Goods",
    "ULTRACEMCO": "Cement & Realty", "GRASIM": "Cement & Realty", "AMBUJACEM": "Cement & Realty",
    "ACC": "Cement & Realty", "SHREECEM": "Cement & Realty", "DALBHARAT": "Cement & Realty",
    "JKCEMENT": "Cement & Realty", "RAMCOCEM": "Cement & Realty", "INDIACEM": "Cement & Realty",
    "ASIANPAINT": "Cement & Realty", "BERGEPAINT": "Cement & Realty",
    "DLF": "Cement & Realty", "LODHA": "Cement & Realty", "GODREJPROP": "Cement & Realty",
    "OBEROIRLTY": "Cement & Realty", "PRESTIGE": "Cement & Realty", "PHOENIXLTD": "Cement & Realty",
    "BHARTIARTL": "Telecom & Media", "INDUSTOWER": "Telecom & Media", "IDEA": "Telecom & Media",
    "TATACOMM": "Telecom & Media", "HFCL": "Telecom & Media", "ITI": "Telecom & Media",
    "ZEEL": "Telecom & Media", "SUNTV": "Telecom & Media", "PVRINOX": "Telecom & Media"
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
            if "OptnTp" in df.columns or ("FinInstrmTp" in df.columns and df["FinInstrmTp"].astype(str).isin(["STF", "STO", "IDF", "IDO"]).any()):
                if "FinInstrmTp" in df.columns:
                    df = df[df["FinInstrmTp"].astype(str).isin(["STF", "STO", "IDF", "IDO"])]
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

def get_strikes(day_fo, sym, spot, opt_tp, high_px=None, low_px=None, trade_dt=None):
    if day_fo.empty:
        return {"At-The-Money": "Upload F&O", "1-Step Out-Of-The-Money": "Upload F&O", "Highest OI Buildup Strike": "Upload F&O", "OI_Wall": "N/A", "Gamma_Watch": "—", "PCR": np.nan, "Next_Target": np.nan}
    opts = day_fo[(day_fo["TckrSymb"].astype(str).str.strip() == sym) & (day_fo["OptnTp"].astype(str).str.strip() == opt_tp)].copy()
    if opts.empty:
        return {"At-The-Money": "Non-F&O", "1-Step Out-Of-The-Money": "Non-F&O", "Highest OI Buildup Strike": "Non-F&O", "OI_Wall": "Non-F&O", "Gamma_Watch": "—", "PCR": np.nan, "Next_Target": np.nan}
    exp = opts["XpryDt"].min()
    sub = opts[opts["XpryDt"] == exp].sort_values("StrkPric").reset_index(drop=True)
    all_e = day_fo[(day_fo["TckrSymb"].astype(str).str.strip() == sym) & (day_fo["XpryDt"] == exp)]
    ce_oi = all_e[all_e["OptnTp"] == "CE"]["OpnIntrst"].sum()
    pe_oi = all_e[all_e["OptnTp"] == "PE"]["OpnIntrst"].sum()
    pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else np.nan
    atm_i = (sub["StrkPric"] - spot).abs().idxmin()
    otm_i = min(atm_i + 1, len(sub) - 1) if opt_tp == "CE" else max(atm_i - 1, 0)
    oi_i = sub["ChngInOpnIntrst"].idxmax()
    wall_i = sub["OpnIntrst"].idxmax()
    fmt = lambda r: f"{int(r['StrkPric']) if float(r['StrkPric']).is_integer() else r['StrkPric']} {opt_tp} @ ₹{r['ClsPric']:.2f}"
    raw_wall = float(sub.loc[wall_i, "StrkPric"])
    wall_strike = int(raw_wall) if raw_wall.is_integer() else raw_wall

    # Gamma Blast Watch: Expiry week (<= 4 days) + Spot within 1.5% of OI_Wall strike
    is_index = sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"]
    gamma_window = 2 if is_index else 4
    dist_pct = abs(spot - raw_wall) / spot if spot > 0 else 1.0
    dte = (pd.to_datetime(exp) - pd.to_datetime(trade_dt)).days if trade_dt else 99
    if dte <= 4 and dist_pct <= 0.015:
        gamma_flag = f"⚡ Gamma Blast Watch ({dte}d)"
    elif dist_pct <= 0.015:
        gamma_flag = f"🎯 Near OI Wall ({dist_pct*100:.1f}%)"
    else:
        gamma_flag = "—"

    target_px = np.nan
    if high_px is not None and low_px is not None:
        piv = (high_px + low_px + spot) / 3.0
        target_px = round((2 * piv - low_px) if opt_tp == "CE" else (2 * piv - high_px), 2)

    return {
        "At-The-Money": fmt(sub.loc[atm_i]),
        "1-Step Out-Of-The-Money": fmt(sub.loc[otm_i]),
        "Highest OI Buildup Strike": f"{fmt(sub.loc[oi_i])} ({int(sub.loc[oi_i]['ChngInOpnIntrst']):+,} OI)",
        "OI_Wall": f"{wall_strike} {opt_tp}",
        "Gamma_Watch": gamma_flag,
        "PCR": pcr,
        "Next_Target": target_px
    }


    # Classic Floor Pivot R1 (for CE) / S1 (for PE) target
    target_px = np.nan
    if high_px is not None and low_px is not None:
        piv = (high_px + low_px + spot) / 3.0
        target_px = round((2 * piv - low_px) if opt_tp == "CE" else (2 * piv - high_px), 2)

    return {
        "At-The-Money": fmt(sub.loc[atm_i]),
        "1-Step Out-Of-The-Money": fmt(sub.loc[otm_i]),
        "Highest OI Buildup Strike": f"{fmt(sub.loc[oi_i])} ({int(sub.loc[oi_i]['ChngInOpnIntrst']):+,} OI)",
        "OI_Wall": f"{wall_strike} {opt_tp}",
        "PCR": pcr,
        "Next_Target": target_px
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
        segment = st.radio(
            "🧭 Select Market Segment",
            ["📊 Stocks", "🏛️ Indices (NIFTY / BANKNIFTY / FINNIFTY / MIDCPNIFTY)"],
            horizontal=True
        )

        if segment.startswith("🏛️ Indices"):
            st.subheader(f"🏛️ F&O Indices EOD & Weekly Gamma Scanner ({dt})")
            if not d_fo.empty and "FinInstrmTp" in d_fo.columns:
                idx_futs = d_fo[d_fo["FinInstrmTp"] == "IDF"].copy()
                if not idx_futs.empty:
                    idx_futs["TckrSymb"] = idx_futs["TckrSymb"].astype(str).str.strip()
                    near_idx = idx_futs.sort_values(["TckrSymb", "XpryDt"]).drop_duplicates("TckrSymb", keep="first").copy()
                    near_idx["Chg%"] = ((near_idx["ClsPric"] - near_idx["PrvsClsgPric"]) / near_idx["PrvsClsgPric"]) * 100
                    near_idx["OI_Signal"] = np.where(
                        (near_idx["Chg%"] > 0) & (near_idx["ChngInOpnIntrst"] > 0), "🟢 Long Buildup",
                        np.where((near_idx["Chg%"] < 0) & (near_idx["ChngInOpnIntrst"] > 0), "🔴 Short Buildup",
                        np.where(near_idx["Chg%"] > 0, "🟡 Short Covering", "🟠 Long Unwinding"))
                    )

                    st.markdown("**1️⃣ Index Futures EOD Summary**")
                    st.dataframe(
                        near_idx[["TckrSymb", "XpryDt", "ClsPric", "Chg%", "TtlTradgVol", "OpnIntrst", "ChngInOpnIntrst", "OI_Signal"]].rename(
                            columns={"TckrSymb": "Index", "XpryDt": "Fut_Expiry", "ClsPric": "Close", "TtlTradgVol": "Volume", "OpnIntrst": "OI", "ChngInOpnIntrst": "OI_Chg"}
                        ),
                        use_container_width=True,
                        hide_index=True
                    )

                    st.success("🟢 Index CALL (CE) Strikes, OI Walls & Gamma Watch (Nearest Expiry)")
                    ce_rows = []
                    for _, r in near_idx.iterrows():
                        info = get_strikes(d_fo, r["TckrSymb"], r["ClsPric"], "CE", r["HghPric"], r["LwPric"], dt)
                        ce_rows.append({"Index": r["TckrSymb"], "Close": r["ClsPric"], "Chg%": round(r["Chg%"], 2), "OI_Signal": r["OI_Signal"], **info})
                    st.dataframe(pd.DataFrame(ce_rows), use_container_width=True, hide_index=True)

                    st.error("🔴 Index PUT (PE) Strikes, OI Walls & Gamma Watch (Nearest Expiry)")
                    pe_rows = []
                    for _, r in near_idx.iterrows():
                        info = get_strikes(d_fo, r["TckrSymb"], r["ClsPric"], "PE", r["HghPric"], r["LwPric"], dt)
                        pe_rows.append({"Index": r["TckrSymb"], "Close": r["ClsPric"], "Chg%": round(r["Chg%"], 2), "OI_Signal": r["OI_Signal"], **info})
                    st.dataframe(pd.DataFrame(pe_rows), use_container_width=True, hide_index=True)
                    # 3. Inspect Specific Strikes for Selected Index
                    st.divider()
                    st.subheader(f"🔎 Inspect Specific Index Strikes ({dt})")
                    sel_idx = st.selectbox("Select Index to Inspect Option Chain Strikes", near_idx["TckrSymb"].tolist(), key=f"idx_pick_{dt}")
                    idx_opts = d_fo[(d_fo["TckrSymb"].astype(str).str.strip() == sel_idx) & (d_fo["OptnTp"].isin(["CE", "PE"]))].copy()
                    if not idx_opts.empty:
                        near_exp_i = idx_opts["XpryDt"].min()
                        chain = idx_opts[idx_opts["XpryDt"] == near_exp_i].copy()
                        chain["Strk_Int"] = chain["StrkPric"].apply(lambda x: int(x) if float(x).is_integer() else round(float(x), 2))
                        spot_val = float(near_idx.loc[near_idx["TckrSymb"] == sel_idx, "ClsPric"].values.tolist().pop(0))

                        # Auto-select 3 strikes closest to spot by default
                        all_strikes_list = sorted(chain["Strk_Int"].unique())
                        closest_3 = sorted(all_strikes_list, key=lambda s: abs(s - spot_val))[:3]
                        picked_strikes = st.multiselect(
                            f"Select Strikes for {sel_idx} (Expiry: {near_exp_i} | Spot: {spot_val})",
                            options=all_strikes_list,
                            default=sorted(closest_3),
                            key=f"strikes_{sel_idx}_{dt}"
                        )
                        if picked_strikes:
                            sub_chain = chain[chain["Strk_Int"].isin(picked_strikes)].sort_values(["Strk_Int", "OptnTp"]).copy()
                            sub_chain["Chg%"] = np.where(sub_chain["PrvsClsgPric"] > 0, ((sub_chain["ClsPric"] - sub_chain["PrvsClsgPric"]) / sub_chain["PrvsClsgPric"]) * 100, 0.0)
                            sub_chain["Cr"] = sub_chain["TtlTrfVal"] / 1e7
                            st.dataframe(
                                sub_chain[["TckrSymb", "Strk_Int", "OptnTp", "ClsPric", "Chg%", "TtlTradgVol", "Cr", "OpnIntrst", "ChngInOpnIntrst"]].rename(
                                    columns={"TckrSymb": "Index", "Strk_Int": "Strike", "OptnTp": "Type", "ClsPric": "Close", "TtlTradgVol": "Volume", "OpnIntrst": "OI", "ChngInOpnIntrst": "OI_Chg"}
                                ),
                                use_container_width=True,
                                hide_index=True
                            )

                    # 4. Institutional Turnover & High-OI Activity Across ALL NSE Indices
                    st.divider()
                    st.subheader(f"🏦 Institutional Turnover & OI Activity in Index Strikes ({dt})")
                    all_ido = d_fo[
                        (d_fo["FinInstrmTp"] == "IDO") & 
                        (d_fo["OptnTp"].isin(["CE", "PE"]))
                    ].copy()

                    if not all_ido.empty:
                        all_ido["TckrSymb"] = all_ido["TckrSymb"].astype(str).str.strip()
                        all_ido["Cr"] = all_ido["TtlTrfVal"] / 1e7
                        all_ido["Chg%"] = np.where(
                            all_ido["PrvsClsgPric"] > 0,
                            ((all_ido["ClsPric"] - all_ido["PrvsClsgPric"]) / all_ido["PrvsClsgPric"]) * 100,
                            0.0
                        )
                        all_ido["Strk_Int"] = all_ido["StrkPric"].apply(
                            lambda x: int(x) if float(x).is_integer() else round(float(x), 2)
                        )
                        all_ido["Activity"] = np.where(
                            (all_ido["Chg%"] > 0) & (all_ido["ChngInOpnIntrst"] > 0), "🟢 Option Buying",
                            np.where((all_ido["Chg%"] < 0) & (all_ido["ChngInOpnIntrst"] > 0), "🔴 Option Writing",
                            np.where(all_ido["Chg%"] > 0, "🟡 Short Covering", "🟠 Long Unwinding"))
                        )

                        # Filter & Per-Index Controls so NIFTY doesn't crowd out other indices
                        avail_indices = sorted(all_ido["TckrSymb"].unique())
                        f_col1, f_col2 = st.columns([3, 1])
                        sel_inst_indices = f_col1.multiselect(
                            "Filter Indices",
                            options=avail_indices,
                            default=avail_indices,
                            key=f"inst_idx_filter_{dt}"
                        )
                        top_n_per_idx = f_col2.number_input(
                            "Top Strikes per Index",
                            min_value=3,
                            max_value=20,
                            value=5,
                            step=1,
                            key=f"top_n_idx_{dt}"
                        )

                        filtered_ido = all_ido[all_ido["TckrSymb"].isin(sel_inst_indices)].copy()

                        # Pick Top N strikes by Turnover (Cr) FOR EACH INDEX separately
                        top_inst_strikes = (
                            filtered_ido.sort_values(["TckrSymb", "Cr"], ascending=[True, False])
                            .groupby("TckrSymb", as_index=False)
                            .head(int(top_n_per_idx))
                            [["TckrSymb", "XpryDt", "Strk_Int", "OptnTp", "ClsPric", "Chg%", "TtlTradgVol", "Cr", "OpnIntrst", "ChngInOpnIntrst", "Activity"]]
                            .rename(
                                columns={
                                    "TckrSymb": "Index",
                                    "XpryDt": "Expiry",
                                    "Strk_Int": "Strike",
                                    "OptnTp": "Type",
                                    "ClsPric": "Close",
                                    "TtlTradgVol": "Volume",
                                    "OpnIntrst": "OI",
                                    "ChngInOpnIntrst": "OI_Chg"
                                }
                            )
                        )
                        st.dataframe(top_inst_strikes, use_container_width=True, hide_index=True)
                    else:
                        st.info("No Index Options (IDO) data found for the selected date.")

                else:
                    st.warning("No Index Futures (IDF) rows found in the uploaded F&O Bhavcopy for this date.")
            else:
                st.warning("Please upload NSE F&O Bhavcopy files to view Index setups.")
            st.stop()

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

        st.subheader("🏭 Sector Performance (Select a Sector Below to View Stocks)")
        sec_tbl = d_eq.groupby("Sector", as_index=False).agg(
            Avg_Chg=("Chg%", "mean"),
            Turnover_Cr=("Cr", "sum"),
            Adv=("Chg%", lambda x: (x > 0).sum()),
            Dec=("Chg%", lambda x: (x < 0).sum())
        ).sort_values("Avg_Chg", ascending=False)

        sec_avg_map = dict(zip(sec_tbl["Sector"], sec_tbl["Avg_Chg"]))
        d_eq["Sec_Chg"] = d_eq["Sector"].map(sec_avg_map).fillna(0)
        d_eq["Sector_Check"] = np.where(
            ((d_eq["Chg%"] > 0) & (d_eq["Sec_Chg"] >= 0.3)) | ((d_eq["Chg%"] < 0) & (d_eq["Sec_Chg"] <= -0.3)),
            "✅ Sector Aligned",
            "⚠️ Counter-Trend"
        )

        ev = st.dataframe(sec_tbl, on_select="rerun", selection_mode="single-row", use_container_width=True, hide_index=True)
        
        # Works via left checkbox click OR direct dropdown selection
        selected_rows = ev.selection.rows if ev and hasattr(ev, "selection") else []
        default_sec = sec_tbl.iloc[selected_rows[0]]["Sector"] if len(selected_rows) > 0 else sec_tbl.iloc[0]["Sector"]
        chosen = st.selectbox("🔍 Drill-Down: View Constituent Stocks in Sector", sec_tbl["Sector"].tolist(), index=sec_tbl["Sector"].tolist().index(default_sec))
        
        st.markdown(f"**📌 Stocks in {chosen} (Sorted by % Change)**")
        st.dataframe(
            d_eq[d_eq["Sector"] == chosen].sort_values("Chg%", ascending=False)[["Sym", "Exch", "Close", "Chg%", "Vol_Spike", "Cr", "OI_Signal"]],
            use_container_width=True,
            hide_index=True
        )

        st.divider()
        st.subheader("🎯 Next-Day High-Probability Setups (CE / PE Strikes)")

        # Calculate 5-Day Range Compression for Pre-Breakout Coiling Detection
        eq_df["Range%"] = ((eq_df["High"] - eq_df["Low"]) / eq_df["Close"]) * 100
        eq_df["Avg_Range_5D"] = eq_df.groupby("Sym")["Range%"].transform(lambda x: x.rolling(5, min_periods=1).mean())
        d_eq["Range%"] = ((d_eq["High"] - d_eq["Low"]) / d_eq["Close"]) * 100
        d_eq["Range_Ratio"] = d_eq["Range%"] / eq_df.loc[d_eq.index, "Avg_Range_5D"]
        liq = d_eq[d_eq["Cr"] >= 5.0] if not d_eq[d_eq["Cr"] >= 5.0].empty else d_eq

        # --- MODE 1: PRE-BREAKOUT COILING (Catches Dry-Up Coils & OI Accumulation Before Breakout) ---
        st.markdown("### 🧲 Mode 1: Pre-Breakout Coiling / Early Accumulation (Before Big Move)")
        st.caption("Ranks tightest price compression (NR4/Coil) + positive Futures OI buildup before expansion")

        eq_df["Range%"] = ((eq_df["High"] - eq_df["Low"]) / eq_df["Close"]) * 100
        eq_df["Avg_Range_5D"] = eq_df.groupby("Sym")["Range%"].transform(lambda x: x.rolling(5, min_periods=1).mean())
        d_eq["Range%"] = ((d_eq["High"] - d_eq["Low"]) / d_eq["Close"]) * 100
        d_eq["Range_Ratio"] = d_eq["Range%"] / eq_df.loc[d_eq.index, "Avg_Range_5D"]
        liq = d_eq[d_eq["Cr"] >= 5.0] if not d_eq[d_eq["Cr"] >= 5.0].empty else d_eq

        coil_bull = liq[
            (liq["Chg%"].between(0.8, 3.2)) &
            (liq["Range_Ratio"] <= 1.05) &
            (liq["Vol_Spike"].between(0.70, 1.49)) &
            (liq["CLV"] >= 0.70) &
            (liq["OI_Signal"] == "🟢 Long Buildup")
        ].nlargest(10, "CLV").reset_index(drop=True)

        coil_bear = liq[
            (liq["Chg%"].between(-3.2, -0.8)) &
            (liq["Range_Ratio"] <= 1.05) &
            (liq["Vol_Spike"].between(0.70, 1.49)) &
            (liq["CLV"] <= 0.30) &
            (liq["OI_Signal"] == "🔴 Short Buildup")
        ].nsmallest(10, "CLV").reset_index(drop=True)

        c_b1, c_b2 = st.columns(2)
        with c_b1:
            st.success("🟢 Early Bullish Coil (Watch for CE Breakout)")
            if not coil_bull.empty:
                strikes_c_bull = pd.DataFrame([
                    get_strikes(d_fo, r["Sym"], r["Close"], "CE", r["High"], r["Low"], dt)
                    for _, r in coil_bull.iterrows()
                ])
                st.dataframe(
                    pd.concat([coil_bull[["Sym", "Close", "Chg%", "Range_Ratio", "Vol_Spike", "OI_Signal", "Sector_Check"]], strikes_c_bull], axis=1),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No tight bullish coils detected today.")

        with c_b2:
            st.error("🔴 Early Bearish Coil (Watch for PE Breakdown)")
            if not coil_bear.empty:
                strikes_c_bear = pd.DataFrame([
                    get_strikes(d_fo, r["Sym"], r["Close"], "PE", r["High"], r["Low"], dt)
                    for _, r in coil_bear.iterrows()
                ])
                st.dataframe(
                    pd.concat([coil_bear[["Sym", "Close", "Chg%", "Range_Ratio", "Vol_Spike", "OI_Signal", "Sector_Check"]], strikes_c_bear], axis=1),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No tight bearish coils detected today.")

        
        # --- MODE 2: MOMENTUM CONTINUATION (Your Existing Filter) ---
        st.markdown("### 🚀 Mode 2: Momentum Continuation (Strong Breakout Follow-Through)")
        bull = liq[(liq["Chg%"] >= 1.5) & (liq["Vol_Spike"] >= 1.5) & (liq["CLV"] >= 0.75)].nlargest(8, "Vol_Spike").reset_index(drop=True)
        bear = liq[(liq["Chg%"] <= -1.5) & (liq["Vol_Spike"] >= 1.5) & (liq["CLV"] <= 0.25)].nlargest(8, "Vol_Spike").reset_index(drop=True)

        st.success("🟢 Momentum BUY (CE)")
        if not bull.empty:
            strikes_bull = pd.DataFrame([
                get_strikes(d_fo, r["Sym"], r["Close"], "CE", r["High"], r["Low"], dt)
                for _, r in bull.iterrows()
            ])
            st.dataframe(
                pd.concat([bull[["Sym", "Close", "Chg%", "Vol_Spike", "OI_Signal", "Sector_Check"]], strikes_bull], axis=1),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No bullish momentum breakouts detected today.")

        st.error("🔴 Momentum SELL (PE)")
        if not bear.empty:
            strikes_bear = pd.DataFrame([
                get_strikes(d_fo, r["Sym"], r["Close"], "PE", r["High"], r["Low"], dt)
                for _, r in bear.iterrows()
            ])
            st.dataframe(
                pd.concat([bear[["Sym", "Close", "Chg%", "Vol_Spike", "OI_Signal", "Sector_Check"]], strikes_bear], axis=1),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No bearish momentum breakdowns detected today.")
            
        # --- PASTE THE NEW STOCK INSPECTOR RIGHT HERE (AT 8 SPACES INDENTATION) ---
        all_syms = sorted(d_eq["Sym"].unique())
        auto_picks = (coil_bull["Sym"].tolist() + bull["Sym"].tolist())[:3]
        default_list = [s for s in auto_picks if s in all_syms]
        inspect_syms = st.multiselect(
            f"🔎 Inspect Specific Stocks on {dt}",
            options=all_syms,
            default=default_list,
            key=f"inspect_{dt}"
        )
        if inspect_syms:
            st.dataframe(
                d_eq[d_eq["Sym"].isin(inspect_syms)][["Sym", "TradDt", "Close", "Chg%", "Range_Ratio", "Vol_Spike", "CLV", "OI_Signal"]],
                use_container_width=True,
                hide_index=True
            )

        st.subheader("🏦 Institutional Turnover & Volume Spikes")
        st.dataframe(liq[(liq["Vol_Spike"] >= 2.0) & (liq["Cr"] >= 50)].sort_values("Cr", ascending=False).head(15)[["Sym", "Sector", "Close", "Chg%", "Vol_Spike", "Cr", "OI_Signal"]], use_container_width=True)
        # --- INSTITUTIONAL TURNOVER & OI ACTIVITY IN F&O STOCK STRIKES ---
        st.divider()
        st.subheader(f"🏦 Institutional Turnover & OI Activity in F&O Stock Strikes ({dt})")
        if not d_fo.empty and "FinInstrmTp" in d_fo.columns and "OptnTp" in d_fo.columns:
            all_sto = d_fo[
                (d_fo["FinInstrmTp"].astype(str).str.strip() == "STO") &
                (d_fo["OptnTp"].astype(str).str.strip().isin(["CE", "PE"]))
            ].copy()

            if not all_sto.empty:
                all_sto["TckrSymb"] = all_sto["TckrSymb"].astype(str).str.strip()
                all_sto["Sector"] = all_sto["TckrSymb"].map(sec_map).fillna("Other / F&O")
                all_sto["Cr"] = all_sto["TtlTrfVal"] / 1e7
                all_sto["Chg%"] = np.where(
                    all_sto["PrvsClsgPric"] > 0,
                    ((all_sto["ClsPric"] - all_sto["PrvsClsgPric"]) / all_sto["PrvsClsgPric"]) * 100,
                    0.0
                )
                all_sto["Strk_Int"] = all_sto["StrkPric"].apply(
                    lambda x: int(x) if float(x).is_integer() else round(float(x), 2)
                )
                all_sto["Activity"] = np.where(
                    (all_sto["Chg%"] > 0) & (all_sto["ChngInOpnIntrst"] > 0), "🟢 Option Buying",
                    np.where((all_sto["Chg%"] < 0) & (all_sto["ChngInOpnIntrst"] > 0), "🔴 Option Writing",
                    np.where(all_sto["Chg%"] > 0, "🟡 Short Covering", "🟠 Long Unwinding"))
                )

                # Row 1: Sector Filter & Activity Filter
                f1, f2 = st.columns(2)
                avail_sectors = sorted(all_sto["Sector"].unique())
                sel_sto_sectors = f1.multiselect(
                    "Filter by Sector",
                    options=avail_sectors,
                    default=avail_sectors,
                    key=f"inst_stk_sec_{dt}"
                )
                activity_opts = ["🟢 Option Buying", "🔴 Option Writing", "🟡 Short Covering", "🟠 Long Unwinding"]
                sel_sto_activity = f2.multiselect(
                    "Filter by Activity Signal",
                    options=activity_opts,
                    default=activity_opts,
                    key=f"inst_stk_act_{dt}"
                )

                # Apply Sector & Activity filters first
                filtered_sto = all_sto[
                    (all_sto["Sector"].isin(sel_sto_sectors)) &
                    (all_sto["Activity"].isin(sel_sto_activity))
                ].copy()

                # Row 2: Specific Stock Filter & Per-Stock Limits
                s_col1, s_col2, s_col3 = st.columns([3, 1, 1])
                avail_fo_stocks = sorted(filtered_sto["TckrSymb"].unique())
                sel_fo_stocks = s_col1.multiselect(
                    "Filter F&O Stocks (Leave empty for Top Active Stocks)",
                    options=avail_fo_stocks,
                    default=[],
                    key=f"inst_stk_filter_{dt}"
                )
                top_n_stocks = s_col2.number_input(
                    "Top Active Stocks",
                    min_value=5,
                    max_value=50,
                    value=15,
                    step=5,
                    key=f"top_n_fo_stk_{dt}"
                )
                top_n_stk_strikes = s_col3.number_input(
                    "Top Strikes / Stock",
                    min_value=1,
                    max_value=10,
                    value=2,
                    step=1,
                    key=f"top_n_stk_strk_{dt}"
                )

                if not filtered_sto.empty:
                    if sel_fo_stocks:
                        final_sto = filtered_sto[filtered_sto["TckrSymb"].isin(sel_fo_stocks)].copy()
                    else:
                        top_syms_by_cr = (
                            filtered_sto.groupby("TckrSymb")["Cr"]
                            .sum()
                            .nlargest(int(top_n_stocks))
                            .index.tolist()
                        )
                        final_sto = filtered_sto[filtered_sto["TckrSymb"].isin(top_syms_by_cr)].copy()

                    top_sto_strikes = (
                        final_sto.sort_values(["TckrSymb", "Cr"], ascending=[True, False])
                        .groupby("TckrSymb", as_index=False)
                        .head(int(top_n_stk_strikes))
                        [["TckrSymb", "Sector", "XpryDt", "Strk_Int", "OptnTp", "ClsPric", "Chg%", "TtlTradgVol", "Cr", "OpnIntrst", "ChngInOpnIntrst", "Activity"]]
                        .rename(
                            columns={
                                "TckrSymb": "Stock",
                                "XpryDt": "Expiry",
                                "Strk_Int": "Strike",
                                "OptnTp": "Type",
                                "ClsPric": "Close",
                                "TtlTradgVol": "Volume",
                                "OpnIntrst": "OI",
                                "ChngInOpnIntrst": "OI_Chg"
                            }
                        )
                    )
                    st.dataframe(top_sto_strikes, use_container_width=True, hide_index=True)
                else:
                    st.warning("No Stock Option strikes match the selected Sector and Activity filters.")
            else:
                st.info("No Stock Options (STO) data found for the selected date.")
        else:
            st.info("Upload NSE F&O Bhavcopy files to view Stock Option strike activity.")
else:
    st.info("Upload files above to start.")
        # --- SECTION 5: OPTION CHAIN WALLS, MAX PAIN & EXPIRY RISK ---
    st.divider()
    st.subheader("🧱 F&O Option Walls, Max Pain & Expiry Risk (Selected Date)")
    if not d_fo.empty and "OptnTp" in d_fo.columns:
        wall_rows = []
        top_fo_syms = liq.nlargest(20, "Cr")["Sym"].tolist()
        for sym in top_fo_syms:
            sub_opt = d_fo[(d_fo["TckrSymb"].astype(str).str.strip() == sym) & (d_fo["OptnTp"].isin(["CE", "PE"]))].copy()
            if sub_opt.empty:
                continue
            near_exp = sub_opt["XpryDt"].min()
            exp_df = sub_opt[sub_opt["XpryDt"] == near_exp]
            dte = (pd.to_datetime(near_exp) - pd.to_datetime(dt)).days

            ce_df = exp_df[exp_df["OptnTp"] == "CE"]
            pe_df = exp_df[exp_df["OptnTp"] == "PE"]
            if ce_df.empty or pe_df.empty:
                continue

            res_strike = ce_df.loc[ce_df["OpnIntrst"].idxmax(), "StrkPric"]
            sup_strike = pe_df.loc[pe_df["OpnIntrst"].idxmax(), "StrkPric"]

            # Max Pain calculation
            strikes = sorted(exp_df["StrkPric"].unique())
            min_pain, max_pain_strike = float("inf"), strikes
            for s in strikes:
                ce_loss = ((s - ce_df["StrkPric"]).clip(lower=0) * ce_df["OpnIntrst"]).sum()
                pe_loss = ((pe_df["StrkPric"] - s).clip(lower=0) * pe_df["OpnIntrst"]).sum()
                if (ce_loss + pe_loss) < min_pain:
                    min_pain = ce_loss + pe_loss
                    max_pain_strike = s

            spot_px = d_eq.loc[d_eq["Sym"] == sym, "Close"].values
            wall_rows.append({
                "Sym": sym,
                "Spot": spot_px,
                "Support_Wall (Max PE OI)": sup_strike,
                "Resistance_Wall (Max CE OI)": res_strike,
                "Max_Pain": max_pain_strike,
                "Days_to_Expiry": dte,
                "Theta_Alert": "⚠️ High Decay (Use ATM)" if dte <= 4 else "✅ Safe Time Value"
            })
        if wall_rows:
            st.dataframe(pd.DataFrame(wall_rows), use_container_width=True, hide_index=True)

    # --- SECTION 6: MULTI-DAY CUMULATIVE TREND (ALL UPLOADED DATES) ---
    st.divider()
    all_dates = sorted(eq_df["TradDt"].unique())
    if len(all_dates) > 1:
        st.subheader(f"📆 Full-Period Positional Trend ({all_dates} to {all_dates[-1]})")
        first_dt, last_dt = all_dates, all_dates[-1]
        start_px = eq_df[eq_df["TradDt"] == first_dt][["Sym", "Close"]].rename(columns={"Close": "Start_Close"})
        end_px = eq_df[eq_df["TradDt"] == last_dt][["Sym", "Sector", "Close"]].rename(columns={"Close": "End_Close"})
        avg_vol = eq_df.groupby("Sym", as_index=False)["Vol_Spike"].mean().rename(columns={"Vol_Spike": "Avg_Vol_Spike"})

        period_df = end_px.merge(start_px, on="Sym").merge(avg_vol, on="Sym")
        period_df["Period_Return%"] = ((period_df["End_Close"] - period_df["Start_Close"]) / period_df["Start_Close"]) * 100

        p1, p2 = st.columns(2)
        with p1:
            st.markdown("**🏆 Top 10 Positional Gainers (Full Window)**")
            st.dataframe(period_df.nlargest(10, "Period_Return%")[["Sym", "Sector", "Start_Close", "End_Close", "Period_Return%", "Avg_Vol_Spike"]], use_container_width=True, hide_index=True)
        with p2:
            st.markdown("**📉 Top 10 Positional Losers (Full Window)**")
            st.dataframe(period_df.nsmallest(10, "Period_Return%")[["Sym", "Sector", "Start_Close", "End_Close", "Period_Return%", "Avg_Vol_Spike"]], use_container_width=True, hide_index=True)
