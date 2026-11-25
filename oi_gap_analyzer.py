import streamlit as st
import pandas as pd
import numpy as np

# Page configuration
st.set_page_config(page_title="NSE/BSE OI & Gap Scanner", layout="wide")
st.title("📊 NSE & BSE Bhavcopy OI + Fyers Live Gap Scanner")

# ==========================================
# SIDEBAR: SETTINGS & FYERS API INPUTS
# ==========================================
st.sidebar.header("1. Index & Broker Settings")
index_choice = st.sidebar.selectbox("Select Index", ["NIFTY", "SENSEX"])
step_size = 50 if index_choice == "NIFTY" else 100

use_fyers = st.sidebar.checkbox("Fetch Live Spot from Fyers API", value=False)
fyers_client_id = st.sidebar.text_input("Fyers App ID (Client ID)", type="password")
fyers_access_token = st.sidebar.text_input("Fyers Access Token", type="password")

manual_spot = st.sidebar.number_input(
    "Or Enter Simulated / Live Open Price",
    value=25850.0 if index_choice == "NIFTY" else 84350.0,
    step=10.0
)

# ==========================================
# 1. MULTI-FILE BHAVCOPY UPLOADER (20-25 FILES)
# ==========================================
st.header("2. Upload 20–25 NSE/BSE UDiFF Bhavcopy CSVs")
uploaded_files = st.file_uploader(
    "Drag and drop your daily Bhavcopy CSV files here",
    type=["csv"],
    accept_multiple_files=True
)

def process_bhavcopies(files, symbol):
    df_list = []
    # Map possible BSE/NSE ticker names
    valid_symbols = ["NIFTY"] if symbol == "NIFTY" else ["SENSEX", "BSX"]
    
    for file in files[-25:]:
        df = pd.read_csv(file)
        df.columns = df.columns.str.strip()
        
        if 'TckrSymb' not in df.columns or 'FinInstrmTp' not in df.columns:
            st.warning(f"Skipping {file.name}: Missing UDiFF columns (TckrSymb / FinInstrmTp).")
            continue
            
        filtered = df[
            (df['TckrSymb'].isin(valid_symbols)) &
            (df['FinInstrmTp'].isin(['OPTIDX', 'IO']))
        ].copy()
        df_list.append(filtered)
        
    if not df_list:
        return None, None, None
        
    master_df = pd.concat(df_list, ignore_index=True)
    master_df['TradDt'] = pd.to_datetime(master_df['TradDt'])
    master_df['XpryDt'] = pd.to_datetime(master_df['XpryDt'])
    
    latest_date = master_df['TradDt'].max()
    nearest_expiry = master_df[master_df['TradDt'] == latest_date]['XpryDt'].min()
    expiry_df = master_df[master_df['XpryDt'] == nearest_expiry].sort_values('TradDt')
    
    return expiry_df, latest_date, nearest_expiry

def get_fyers_live_price(client_id, token, symbol):
    from fyers_apiv3 import fyersModel
    fyers = fyersModel.FyersModel(client_id=client_id, token=token, is_async=False)
    fyers_symbol = "NSE:NIFTY50-INDEX" if symbol == "NIFTY" else "BSE:SENSEX-INDEX"
    response = fyers.quotes(data={"symbols": fyers_symbol})
    if response.get("s") == "ok":
        return response["d"][0]["v"]["lp"]
    else:
        raise Exception(f"Fyers Error: {response}")

# ==========================================
# 3. RUN ANALYSIS & RENDER UI OUTPUT
# ==========================================
if uploaded_files:
    with st.spinner("Analyzing Bhavcopy Open Interest..."):
        expiry_df, latest_date, nearest_expiry = process_bhavcopies(uploaded_files, index_choice)
        
    if expiry_df is None or expiry_df.empty:
        st.error(f"No valid {index_choice} options data found in the uploaded CSVs.")
    else:
        latest_eod = expiry_df[expiry_df['TradDt'] == latest_date].copy()
        ce_df = latest_eod[latest_eod['OptnTp'] == 'CE'].set_index('StrkPric')
        pe_df = latest_eod[latest_eod['OptnTp'] == 'PE'].set_index('StrkPric')
        
        total_pe_oi = pe_df['OpnIntrst'].sum()
        total_ce_oi = ce_df['OpnIntrst'].sum()
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        
        major_call_wall = ce_df['OpnIntrst'].idxmax()
        major_put_wall = pe_df['OpnIntrst'].idxmax()
        
        # Trapped Call Writers (Top 25% OI addition on latest EOD)
        trapped_ce = ce_df[
            ce_df['ChngInOpnIntrst'] > ce_df['ChngInOpnIntrst'].quantile(0.75)
        ].sort_values(by='OpnIntrst', ascending=False)
        trapped_strikes = trapped_ce.index.tolist()[:5]
        
        # Determine Live / Open Price
        live_price = manual_spot
        if use_fyers and fyers_client_id and fyers_access_token:
            try:
                live_price = get_fyers_live_price(fyers_client_id, fyers_access_token, index_choice)
                st.sidebar.success(f"Live Fyers Price: {live_price}")
            except Exception as e:
                st.sidebar.error(str(e))
                
        # Display Key Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Latest EOD Date", latest_date.strftime('%d %b %Y'))
        col2.metric("Nearest Expiry", nearest_expiry.strftime('%d %b %Y'))
        col3.metric("EOD Put-Call Ratio (PCR)", pcr)
        col4.metric("Live / Target Open", live_price)
        
        st.divider()
        
        # Gap-Up Squeeze Check
        breached = [s for s in trapped_strikes if live_price > s]
        if breached:
            atm_strike = round(live_price / step_size) * step_size
            effective_strike = atm_strike - step_size
            st.success(
                f"🚀 **SHORT SQUEEZE ALERT:** Open price ({live_price}) breached trapped Call strikes: {breached}. "
                f"**Most Effective Strike to Watch:** `{effective_strike} CE`"
            )
        else:
            st.info(f"No major trapped Call walls breached yet. Major Resistance Wall is at **{major_call_wall} CE**.")
            
        # Display Top Call & Put Strikes Side-by-Side
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Top Trapped Call (CE) Strikes")
            st.dataframe(trapped_ce[['ClsPric', 'OpnIntrst', 'ChngInOpnIntrst']].head(10))
        with c2:
            st.subheader("Top Put (PE) Support Strikes")
            st.dataframe(pe_df[['ClsPric', 'OpnIntrst', 'ChngInOpnIntrst']].sort_values(by='OpnIntrst', ascending=False).head(10))
else:
    st.info("👈 Upload your NSE or BSE Bhavcopy CSV files above to generate the OI & Strike report.")
