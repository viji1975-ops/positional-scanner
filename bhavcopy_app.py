import zipfile
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="NSE & BSE Bhavcopy Pro Terminal", layout="wide")
st.title("📈 NSE + BSE Multi-Day Bhavcopy & Multi-Strike Options Scanner")

BUILTIN_SECTORS = {
    "HDFCBANK": "Banking & Finance", "ICICIBANK": "Banking & Finance", "SBIN": "Banking & Finance",
    "KOTAKBANK": "Banking & Finance", "AXISBANK": "Banking & Finance", "INDUSINDBK": "Banking & Finance",
    "BANKBARODA": "Banking & Finance", "PNB": "Banking & Finance", "CANBK": "Banking & Finance",
    "BAJFINANCE": "Banking & Finance", "BAJAJFINSV": "Banking & Finance", "JIOFIN": "Banking & Finance",
    "CHOLAFIN": "Banking & Finance", "SHRIRAMFIN": "Banking & Finance", "MUTHOOTFIN": "Banking & Finance",
    "PFC": "Banking & Finance", "RECLTD": "Banking & Finance", "SBILIFE": "Banking & Finance",
    "HDFCLIFE": "Banking & Finance", "ICICIPRULI": "Banking & Finance", "BAJAJHLDNG": "Banking & Finance",
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT", "TECHM": "IT",
    "LTIM": "IT", "PERSISTENT": "IT", "COFORGE": "IT", "MPHASIS": "IT", "KPITTECH": "IT",
    "TATAELXSI": "IT", "OFSS": "IT", "LTTS": "IT",
    "RELIANCE": "Energy & Oil", "ONGC": "Energy & Oil", "NTPC": "Energy & Oil", "POWERGRID": "Energy & Oil",
    "COALINDIA": "Energy & Oil", "BPCL": "Energy & Oil", "IOC": "Energy & Oil", "HINDPETRO": "Energy & Oil",
    "GAIL": "Energy & Oil", "TATAPOWER": "Energy & Oil", "ADANIPOWER": "Energy & Oil", "ADANIGREEN": "Energy & Oil",
    "JSWENERGY": "Energy & Oil", "NHPC": "Energy & Oil", "SJVN": "Energy & Oil",
    "MARUTI": "Auto", "TATAMOTORS": "Auto", "M&M": "Auto", "BAJAJ-AUTO": "Auto",
    "EICHERMOT": "Auto", "HEROMOTOCO": "Auto", "TVSMOTOR": "Auto", "ASHOKLEY": "Auto",
    "BHARATFORG": "Auto", "MOTHERSON": "Auto", "BOSCHLTD": "Auto", "MRF": "Auto", "BALKRISIND": "Auto",
    "SUNPHARMA": "Pharma & Healthcare", "CIPLA": "Pharma & Healthcare", "DRREDDY": "Pharma & Healthcare",
    "DIVISLAB": "Pharma & Healthcare", "APOLLOHOSP": "Pharma & Healthcare", "LUPIN": "Pharma & Healthcare",
    "AUROPHARMA": "Pharma & Healthcare", "TORNTPHARM": "Pharma & Healthcare", "ZYDUSLIFE": "Pharma & Healthcare",
    "ALKEM": "Pharma & Healthcare", "BIOCON": "Pharma & Healthcare", "MAXHEALTH": "Pharma & Healthcare",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG", "GODREJCP": "FMCG", "DABUR": "FMCG", "MARICO": "FMCG",
    "VBL": "FMCG", "COLPAL": "FMCG", "UNITDSPR": "FMCG", "UBL": "FMCG",
    "TATASTEEL": "Metals & Mining", "JSWSTEEL": "Metals & Mining", "HINDALCO": "Metals & Mining",
    "VEDL": "Metals & Mining", "JINDALSTEL": "Metals & Mining", "NMDC": "Metals & Mining",
    "SAIL": "Metals & Mining", "NATIONALUM": "Metals & Mining", "HINDZINC": "Metals & Mining",
    "LT": "Infra & Capital Goods", "SIEMENS": "Infra & Capital Goods", "ABB": "Infra & Capital Goods",
    "HAL": "Infra & Capital Goods", "BEL": "Infra & Capital Goods", "BHEL": "Infra & Capital Goods",
    "ADANIPORTS": "Infra & Capital Goods", "INDIGO": "Infra & Capital Goods", "IRCTC": "Infra & Capital Goods",
    "RVNL": "Infra & Capital Goods", "IRFC": "Infra & Capital Goods", "MAZDOCK": "Infra & Capital Goods",
    "ULTRACEMCO": "Cement & Realty", "GRASIM": "Cement & Realty", "AMBUJACEM": "Cement & Realty",
    "SHREECEM": "Cement & Realty", "DLF": "Cement & Realty", "LODHA": "Cement & Realty",
    "GODREJPROP": "Cement & Realty", "OBEROIRLTY": "Cement & Realty", "PRESTIGE": "Cement & Realty",
    "BHARTIARTL": "Telecom & Media", "INDUSTOWER": "Telecom & Media", "IDEA": "Telecom & Media",
    "ZEEL": "Telecom & Media", "SUNTV": "Telecom & Media", "TITAN": "Consumer Durables",
    "ASIANPAINT": "Consumer Durables", "PIDILITIND": "Consumer Durables", "HAVELLS": "Consumer Durables",
    "TRENT": "Consumer Durables", "DMART": "Consumer Durables", "DIXON": "Consumer Durables",
    "POLYCAB": "Consumer Durables", "VOLTAS": "Consumer Durables"
}

def extract_dataframes_from_uploads(uploaded_files):
    extracted = []
    for f in uploaded_files:
        f.seek(0)
        fname = f.name.lower()
        if fname.endswith(".zip"):
            with zipfile.ZipFile(f) as z:
                for inner_name in z.namelist():
                    if inner_name.lower().endswith(".csv") and not inner_name.startswith("__MACOSX"):
                        with z.open(inner_name) as csv_file:
                            df = pd.read_csv(csv_file, low_memory=False)
                            df.columns = df.columns.str.strip()
                            extracted.append((inner_name, df))
        elif fname.endswith(".csv"):
            df = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
            extracted.append((f.name, df))
    return extracted

# --- SIDEBAR UPLOADS ---
st.sidebar.header("1. Upload Bhavcopy Files")
bse_files = st.sidebar.file_uploader(
    "Upload BSE Bhavcopy Files (.csv or .zip)",
    type=["csv", "zip"],
    accept_multiple_files=True
)
nse_files = st.sidebar.file_uploader(
    "Upload NSE Bhavcopy Files — Equity & F&O (.csv or .zip)",
    type=["csv", "zip"],
    accept_multiple_files=True
)

st.sidebar.divider()
st.sidebar.header("2. Sector Database")
custom_sector_file = st.sidebar.file_uploader("Optional: Upload Custom Sector CSV", type=["csv"])

if custom_sector_file is not None:
    sec_df = pd.read_csv(custom_sector_file)
    sec_df.columns = sec_df.columns.str.strip()
else:
    sec_df = pd.DataFrame(list(BUILTIN_SECTORS.items()), columns=["TckrSymb", "Sector"])
st.sidebar.success(f"✅ Sector Mapping Ready ({len(sec_df)} stocks)")

def normalize_legacy_or_udiff(df):
    col_map = {
        "SYMBOL": "TckrSymb", "SC_NAME": "TckrSymb",
        "SERIES": "SctySrs", "SC_GROUP": "SctySrs",
        "OPEN": "OpnPric", "HIGH": "HghPric", "LOW": "LwPric", "CLOSE": "ClsPric",
        "PREVCLOSE": "PrvsClsgPric", "TOTTRDQTY": "TtlTradgVol", "NO_OF_SHRS": "TtlTradgVol",
        "TOTTRDVAL": "TtlTrfVal", "NET_TURNOV": "TtlTrfVal",
        "TIMESTAMP": "TradDt", "EXPIRY_DT": "XpryDt",
        "STRIKE_PR": "StrkPric", "OPTION_TYP": "OptnTp",
        "OPEN_INT": "OpnIntrst", "CHG_IN_OI": "ChngInOpnIntrst",
        "INSTRUMENT": "FinInstrmTp"
    }
    rename_dict = {k: v for k, v in col_map.items() if k in df.columns and v not in df.columns}
    return df.rename(columns=rename_dict)

def process_all_uploads(bse_uploads, nse_uploads):
    eq_list = []
    fo_list = []
    debug_info = []

    if bse_uploads:
        for name, df in extract_dataframes_from_uploads(bse_uploads):
            df = normalize_legacy_or_udiff(df)
            debug_info.append(f"BSE: `{name}` ({len(df)} rows)")
            df["Src_Tag"] = "BSE"
            if "SctySrs" in df.columns:
                df = df[df["SctySrs"].astype(str).str.strip().isin(["A", "B", "X", "T", "EQ", "BE"])]
            eq_list.append(df)

    if nse_uploads:
        for name, df in extract_dataframes_from_uploads(nse_uploads):
            df = normalize_legacy_or_udiff(df)
            debug_info.append(f"NSE: `{name}` ({len(df)} rows)")
            is_fo = ("OptnTp" in df.columns) or (
                "FinInstrmTp" in df.columns and df["FinInstrmTp"].astype(str).isin(["STF", "STO", "IDF", "IDO", "FUTSTK", "OPTSTK", "FUTIDX", "OPTIDX"]).any()
            )
            if is_fo:
                fo_list.append(df)
            else:
                df["Src_Tag"] = "NSE"
                if "SctySrs" in df.columns:
                    df = df[df["SctySrs"].astype(str).str.strip().isin(["EQ", "BE"])]
                eq_list.append(df)

    combined_fo = pd.DataFrame()
    if fo_list:
        combined_fo = pd.concat(fo_list, ignore_index=True)
        combined_fo["TradDt"] = pd.to_datetime(combined_fo["TradDt"], format="mixed").dt.strftime("%Y-%m-%d")
        if "XpryDt" in combined_fo.columns:
            combined_fo["XpryDt"] = pd.to_datetime(combined_fo["XpryDt"], format="mixed").dt.strftime("%Y-%m-%d")

    if eq_list:
        raw_eq = pd.concat(eq_list, ignore_index=True)
        raw_eq["TradDt"] = pd.to_datetime(raw_eq["TradDt"], format="mixed").dt.strftime("%Y-%m-%d")
        raw_eq["TckrSymb"] = raw_eq["TckrSymb"].astype(str).str.strip()

        if "ISIN" in raw_eq.columns:
            nse_rows = raw_eq[raw_eq["Src_Tag"] == "NSE"]
            if not nse_rows.empty:
                nse_map = nse_rows[["ISIN", "TckrSymb"]].drop_duplicates("ISIN")
                isin_to_sym = dict(zip(nse_map["ISIN"], nse_map["TckrSymb"]))
                raw_eq["Unified_Symbol"] = raw_eq["ISIN"].map(isin_to_sym).fillna(raw_eq["TckrSymb"])
            else:
                raw_eq["Unified_Symbol"] = raw_eq["TckrSymb"]
        else:
            raw_eq["Unified_Symbol"] = raw_eq["TckrSymb"]

        grouped_eq = raw_eq.groupby(["TradDt", "Unified_Symbol"], as_index=False).agg(
            Open=("OpnPric", "first"),
            High=("HghPric", "max"),
            Low=("LwPric", "min"),
            Close=("ClsPric", "first"),
            Prev_Close=("PrvsClsgPric", "first"),
            Total_Vol=("TtlTradgVol", "sum"),
            Total_Turnover=("TtlTrfVal", "sum"),
            Exchanges=("Src_Tag", lambda x: "+".join(sorted(set(x.dropna()))))
        )
    elif not combined_fo.empty and "FinInstrmTp" in combined_fo.columns:
        stf = combined_fo[combined_fo["FinInstrmTp"].astype(str).isin(["STF", "FUTSTK"])].copy()
        stf = stf.sort_values(["TradDt", "TckrSymb", "XpryDt"])
        near_stf = stf.drop_duplicates(subset=["TradDt", "TckrSymb"], keep="first").copy()
        grouped_eq = pd.DataFrame()
        grouped_eq["TradDt"] = near_stf["TradDt"].values
        grouped_eq["Unified_Symbol"] = near_stf["TckrSymb"].astype(str).str.strip().values
        grouped_eq["Open"] = near_stf["OpnPric"].values
        grouped_eq["High"] = near_stf["HghPric"].values
