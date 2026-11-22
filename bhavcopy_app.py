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

KEEP = [
    "TradDt", "TckrSymb", "SctySrs", "ISIN", "FinInstrmTp", "XpryDt", "StrkPric", "OptnTp",
    "OpnPric", "HghPric", "LwPric", "ClsPric", "PrvsClsgPric", "TtlTradgVol", "TtlTrfVal",
    "OpnIntrst", "ChngInOpnIntrst"
]

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
