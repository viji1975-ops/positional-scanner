import io
import zipfile
import requests
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="NSE & BSE Bhavcopy Pro Terminal", layout="wide")
st.title("📈 NSE + BSE Multi-Day Bhavcopy & Multi-Strike Options Scanner")

# --- BUILT-IN FALLBACK SECTOR DICTIONARY ---
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

@st.cache_data(ttl=86400)
def get_sector_mapping():
    records = [{"TckrSymb": k, "Sector": v} for k, v in BUILTIN_SECTORS.items()]
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get("https://niftyindices.com", headers=headers, timeout=5)
        if res.status_code == 200 and "Symbol" in res.text:
            df_500 = pd.read_csv(io.StringIO(res.text))
            df_500.columns = df_500.columns.str.strip()
            live_records = [
                {"TckrSymb": str(row['Symbol']).strip(), "Sector": str(row['Industry']).strip()}
                for _, row in df_500.dropna(subset=['Symbol', 'Industry']).iterrows()
            ]
            if live_records:
                records = live_records + records
    except Exception:
        pass
    return pd.DataFrame(records).drop_duplicates(subset=['TckrSymb'], keep='first')

def extract_dataframes_from_uploads(uploaded_files):
    extracted_dfs = []
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
                            extracted_dfs.append(df)
        elif fname.endswith(".csv"):
            df = pd.read_csv(f, low_memory=False)
            df.columns = df.columns.str.strip()
            extracted_dfs.append(df)
    return extracted_dfs

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
    st.sidebar.success(f"✅ Custom Sectors Loaded ({len(sec_df)} stocks)")
else:
    sec_df = get_sector_mapping()
    st.sidebar.success(f"✅ Sector Mapping Active ({len(sec_df)} stocks)")

def process_all_uploads(bse_uploads, nse_uploads):
    eq_list = []
    fo_list = []

    if bse_uploads:
        for df in extract_dataframes_from_uploads(bse_uploads):
            df['Src_Tag'] = 'BSE'
            if 'SctySrs' in df.columns:
                df = df[df['SctySrs'].isin(['A', 'B', 'X', 'T', 'EQ', 'BE'])]
            eq_list.append(df)

    if nse_uploads:
        for df in extract_dataframes_from_uploads(nse_uploads):
            if 'OptnTp' in df.columns or ('FinInstrmTp' in df.columns and df['FinInstrmTp'].isin(['STF', 'STO', 'IDF', 'IDO']).any()):
                fo_list.append(df)
            else:
                df['Src_Tag'] = 'NSE'
                if 'SctySrs' in df.columns:
                    df = df[df['SctySrs'].isin(['EQ', 'BE'])]
                eq_list.append(df)

    combined_fo = pd.DataFrame()
    if fo_list:
        combined_fo = pd.concat(fo_list, ignore_index=True)
        combined_fo['TradDt'] = pd.to_datetime(combined_fo['TradDt']).dt.strftime('%Y-%m-%d')
        combined_fo['XpryDt'] = pd.to_datetime(combined_fo['XpryDt']).dt.strftime('%Y-%m-%d')

    # Build Equity DataFrame (or fallback to Near-Month Stock Futures if only F&O files were uploaded)
    if eq_list:
        raw_eq = pd.concat(eq_list, ignore_index=True)
        raw_eq['TradDt'] = pd.to_datetime(raw_eq['TradDt']).dt.strftime('%Y-%m-%d')

        if 'ISIN' in raw_eq.columns:
            nse_rows = raw_eq[raw_eq['Src_Tag'] == 'NSE']
            if not nse_rows.empty:
                nse_map = nse_rows[['ISIN', 'TckrSymb']].drop_duplicates('ISIN')
                isin_to_sym = dict(zip(nse_map['ISIN'], nse_map['TckrSymb']))
                raw_eq['Unified_Symbol'] = raw_eq['ISIN'].map(isin_to_sym).fillna(raw_eq['TckrSymb'])
            else:
                raw_eq['Unified_Symbol'] = raw_eq['TckrSymb']
        else:
            raw_eq['Unified_Symbol'] = raw_eq['TckrSymb']

        grouped_eq = raw_eq.groupby(['TradDt', 'Unified_Symbol'], as_index=False).agg(
            Open=('OpnPric', 'first'),
            High=('HghPric', 'max'),
            Low=('LwPric', 'min'),
            Close=('ClsPric', 'first'),
            Prev_Close=('PrvsClsgPric', 'first'),
            Total_Vol=('TtlTradgVol', 'sum'),
            Total_Turnover=('TtlTrfVal', 'sum'),
            Exchanges=('Src_Tag', lambda x: '+'.join(sorted(set(x.dropna()))))
        )
    elif not combined_fo.empty and 'FinInstrmTp' in combined_fo.columns:
        # Fallback: Use Near-Month Stock Futures (STF) when only NSE F&O Bhavcopy is uploaded
        stf = combined_fo[combined_fo['FinInstrmTp'] == 'STF'].copy()
        stf = stf.sort_values(['TradDt', 'TckrSymb', 'XpryDt'])
        near_stf = stf.drop_duplicates(subset=['TradDt', 'TckrSymb'], keep='first')
        grouped_eq = pd.DataFrame({
            'TradDt': near_stf['TradDt'],
            'Unified_Symbol': near_stf['TckrSymb'],
            'Open': near_stf['OpnPric'],
            'High': near_stf['HghPric'],
            'Low': near_stf['LwPric'],
            'Close': near_stf['ClsPric'],
            'Prev_Close': near_stf['PrvsClsgPric'],
            'Total_Vol': near_stf['TtlTradgVol'],
            'Total_Turnover': near_stf['TtlTrfVal'],
            'Exchanges': 'NSE-FO (Fut)'
        })
    else:
        grouped_eq = pd.DataFrame()

