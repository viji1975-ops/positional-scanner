import io
import requests
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="NSE & BSE Bhavcopy Pro Terminal", layout="wide")
st.title("📈 NSE + BSE Multi-Day Bhavcopy & Multi-Strike Options Scanner")

# --- AUTO-FETCH SECTOR MAPPING (NO SEPARATE SCRIPT NEEDED) ---
@st.cache_data(ttl=86400)
def fetch_live_sector_mapping():
    headers = {"User-Agent": "Mozilla/5.0"}
    all_records = []

    # 1. Primary Source: Nifty 500 Industry Mapping
    try:
        res = requests.get("https://niftyindices.com", headers=headers, timeout=10)
        df_500 = pd.read_csv(io.StringIO(res.text))
        df_500.columns = df_500.columns.str.strip()
        if 'Symbol' in df_500.columns and 'Industry' in df_500.columns:
            for _, row in df_500.dropna(subset=['Symbol', 'Industry']).iterrows():
                all_records.append({"TckrSymb": str(row['Symbol']).strip(), "Sector": str(row['Industry']).strip()})
    except Exception:
        pass

    # 2. Supplement with Official Sectoral Indices
    sector_urls = {
        "Information Technology": "https://niftyindices.com",
        "Financial Services": "https://niftyindices.com",
        "Healthcare": "https://niftyindices.com",
        "Automobile and Auto Components": "https://niftyindices.com",
        "Fast Moving Consumer Goods": "https://niftyindices.com",
        "Metals & Mining": "https://niftyindices.com",
        "Oil Gas & Consumable Fuels": "https://niftyindices.com",
        "Realty": "https://niftyindices.com",
        "Media Entertainment & Publication": "https://niftyindices.com"
    }
    for sector, url in sector_urls.items():
        try:
            res = requests.get(url, headers=headers, timeout=8)
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = df.columns.str.strip()
            for sym in df['Symbol'].dropna():
                all_records.append({"TckrSymb": str(sym).strip(), "Sector": sector})
        except Exception:
            pass

    if not all_records:
        return pd.DataFrame(columns=["TckrSymb", "Sector"])
    return pd.DataFrame(all_records).drop_duplicates(subset=['TckrSymb'], keep='first')

# --- SIDEBAR UPLOADS ---
st.sidebar.header("1. Upload Bhavcopy Files")
eq_files = st.sidebar.file_uploader(
    "Upload NSE & BSE Equity Bhavcopies (20–22 CSVs)", 
    type=["csv"], 
    accept_multiple_files=True
)
fo_files = st.sidebar.file_uploader(
    "Upload F&O Bhavcopies (20–22 CSVs)", 
    type=["csv"], 
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
    sec_df = fetch_live_sector_mapping()
    if not sec_df.empty:
        st.sidebar.success(f"✅ Auto-Loaded Nifty Sectors ({len(sec_df)} stocks)")
    else:
        st.sidebar.warning("⚠️ Could not reach Nifty server. Upload a Sector CSV manually if needed.")

@st.cache_data
def parse_equity_files(files):
    dfs = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = df.columns.str.strip()
        if 'SctySrs' in df.columns:
            df = df[df['SctySrs'].isin(['EQ', 'BE', 'A', 'B', 'X', 'T'])]
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    
    raw = pd.concat(dfs, ignore_index=True)
    raw['TradDt'] = pd.to_datetime(raw['TradDt']).dt.strftime('%Y-%m-%d')
    
    if 'ISIN' in raw.columns and 'Src' in raw.columns:
        nse_map = raw[raw['Src'] == 'NSE'][['ISIN', 'TckrSymb']].drop_duplicates('ISIN')
        isin_to_sym = dict(zip(nse_map['ISIN'], nse_map['TckrSymb']))
        raw['Unified_Symbol'] = raw['ISIN'].map(isin_to_sym).fillna(raw['TckrSymb'])
    else:
        raw['Unified_Symbol'] = raw['TckrSymb']

    grouped = raw.groupby(['TradDt', 'Unified_Symbol'], as_index=False).agg(
        Open=('OpnPric', 'first'),
        High=('HghPric', 'max'),
        Low=('LwPric', 'min'),
        Close=('ClsPric', 'first'),
        Prev_Close=('PrvsClsgPric', 'first'),
        Total_Vol=('TtlTradgVol', 'sum'),
        Total_Turnover=('TtlTrfVal', 'sum'),
        Exchanges=('Src', lambda x: '+'.join(sorted(set(x.dropna())))) if 'Src' in raw.columns else ('Unified_Symbol', lambda x: 'NSE/BSE')
    )
    return grouped

@st.cache_data
def parse_fo_files(files):
    dfs = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = df.columns.str.strip()
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    fo = pd.concat(dfs, ignore_index=True)
    fo['TradDt'] = pd.to_datetime(fo['TradDt']).dt.strftime('%Y-%m-%d')
    fo['XpryDt'] = pd.to_datetime(fo['XpryDt']).dt.strftime('%Y-%m-%d')
    return fo

def format_strike(val):
    return int(val) if float(val).is_integer() else round(float(val), 2)

def get_all_three_strikes(day_fo, symbol, spot, opt_type):
    if day_fo.empty:
        return "Upload F&O", "Upload F&O", "Upload F&O", np.nan
    
    opts = day_fo[(day_fo['TckrSymb'] == symbol) & (day_fo['OptnTp'] == opt_type)].copy()
    if opts.empty:
        return "Non-F&O", "Non-F&O", "Non-F&O", np.nan
    
    nearest_exp = opts['XpryDt'].min()
    exp_opts = opts[opts['XpryDt'] == nearest_exp].sort_values('StrkPric').reset_index(drop=True)
    
    all_exp = day_fo[(day_fo['TckrSymb'] == symbol) & (day_fo['XpryDt'] == nearest_exp)]
    ce_oi = all_exp[all_exp['OptnTp'] == 'CE']['OpnIntrst'].sum()
    pe_oi = all_exp[all_exp['OptnTp'] == 'PE']['OpnIntrst'].sum()
    pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else np.nan

    # 1. At-The-Money
    exp_opts['Dist'] = (exp_opts['StrkPric'] - spot).abs()
    atm_idx = exp_opts['Dist'].idxmin()
    atm_row = exp_opts.loc[atm_idx]
    atm_str = f"{format_strike(atm_row['StrkPric'])} {opt_type} @ ₹{atm_row['ClsPric']:.2f}"

    # 2. 1-Step Out-Of-The-Money
    if opt_type == 'CE':
        otm_idx = atm_idx + 1 if (atm_idx + 1) < len(exp_opts) else atm_idx
    else:
        otm_idx = atm_idx - 1 if (atm_idx - 1) >= 0 else atm_idx
    otm_row = exp_opts.loc[otm_idx]
    otm_str = f"{format_strike(otm_row['StrkPric'])} {opt_type} @ ₹{otm_row['ClsPric']:.2f}"

    # 3. Highest OI Buildup Strike
    max_oi_idx = exp_opts['ChngInOpnIntrst'].idxmax()
    oi_row = exp_opts.loc[max_oi_idx]
    oi_chg = int(oi_row['ChngInOpnIntrst'])
    oi_str = f"{format_strike(oi_row['StrkPric'])} {opt_type} @ ₹{oi_row['ClsPric']:.2f} ({oi_chg:+,} OI)"

    return atm_str, otm_str, oi_str, pcr

if eq_files:
    eq_df = parse_equity_files(eq_files)
    
    eq_df = eq_df.sort_values(['Unified_Symbol', 'TradDt'])
    eq_df['Pct_Change'] = ((eq_df['Close'] - eq_df['Prev_Close']) / eq_df['Prev_Close']) * 100
    eq_df['Avg_Vol_5D'] = eq_df.groupby('Unified_Symbol')['Total_Vol'].transform(lambda x: x.rolling(5, min_periods=1).mean())
    eq_df['Vol_Spike'] = eq_df['Total_Vol'] / eq_df['Avg_Vol_5D']
    eq_df['Turnover_Cr'] = eq_df['Total_Turnover'] / 1e7
    
    eq_df['CLV'] = np.where(
        (eq_df['High'] - eq_df['Low']) > 0,
        (eq_df['Close'] - eq_df['Low']) / (eq_df['High'] - eq_df['Low']),
        0.5
    )

    if not sec_df.empty:
        eq_df = eq_df.merge(sec_df, left_on='Unified_Symbol', right_on='TckrSymb', how='left')
        eq_df['Sector'] = eq_df['Sector'].fillna('Other / Smallcap')
    else:
        eq_df['Sector'] = 'Unclassified'

    dates = sorted(eq_df['TradDt'].unique(), reverse=True)
    selected_date = st.selectbox("📅 Select Analysis Date", dates)
    day_eq = eq_df[eq_df['TradDt'] == selected_date].copy()

    fo_df = parse_fo_files(fo_files) if fo_files else pd.DataFrame()
    day_fo = fo_df[fo_df['TradDt'] == selected_date] if not fo_df.empty else pd.DataFrame()

    if not day_fo.empty:
        futs = day_fo[day_fo['FinInstrmTp'].isin(['STF', 'IDF'])].copy()
        if not futs.empty:
            fut_agg = futs.groupby('TckrSymb', as_index=False).agg(
                Fut_OI=('OpnIntrst', 'sum'),
                Fut_OI_Chg=('ChngInOpnIntrst', 'sum')
            )
            day_eq = day_eq.merge(fut_agg, left_on='Unified_Symbol', right_on='TckrSymb', how='left')
            
            def classify_oi(row):
                if pd.isna(row['Fut_OI_Chg']): return "Cash Only"
                if row['Pct_Change'] > 0 and row['Fut_OI_Chg'] > 0: return "🟢 Long Buildup"
                if row['Pct_Change'] < 0 and row['Fut_OI_Chg'] > 0: return "🔴 Short Buildup"
                if row['Pct_Change'] > 0 and row['Fut_OI_Chg'] < 0: return "🟡 Short Covering"
                return "🟠 Long Unwinding"
            
            day_eq['OI_Signal'] = day_eq.apply(classify_oi, axis=1)
        else:
            day_eq['OI_Signal'] = "N/A"
    else:
        day_eq['OI_Signal'] = "Upload F&O CSV"

    # --- SECTION 1: TOP 10 GAINERS & LOSERS ---
    st.subheader(f"🔥 Top 10 Movers ({selected_date}) — Consolidated NSE + BSE")
    liquid_eq = day_eq[day_eq['Turnover_Cr'] >= 5.0]
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🚀 Top 10 Gainers**")
        gainers = liquid_eq.nlargest(10, 'Pct_Change')[['Unified_Symbol', 'Exchanges', 'Close', 'Pct_Change', 'Vol_Spike', 'OI_Signal']]
        st.dataframe(gainers.style.format({'Close': '₹{:.2f}', 'Pct_Change': '+{:.2f}%', 'Vol_Spike': '{:.1f}x'}), use_container_width=True)
    with c2:
        st.markdown("**🔻 Top 10 Losers**")
