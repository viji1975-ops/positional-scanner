import io
import zipfile
import numpy as np
import pandas as pd
import streamlit as st

# Page configuration
st.set_page_config(page_title="NSE/BSE OI & Gap Scanner", layout="wide")
st.title("📊 NSE & BSE Bhavcopy OI + Fyers Live Gap Scanner")

# ==========================================
# INDEX CONFIGURATION (NSE & BSE F&O INDICES)
# ==========================================
INDEX_CONFIG = {
    "NIFTY": {
        "bhav_symbols": ["NIFTY"],
        "step_size": 50,
        "fyers_symbol": "NSE:NIFTY50-INDEX",
        "default_spot": 25850.0,
    },
    "BANKNIFTY": {
        "bhav_symbols": ["BANKNIFTY"],
        "step_size": 100,
        "fyers_symbol": "NSE:NIFTYBANK-INDEX",
        "default_spot": 53500.0,
    },
    "FINNIFTY": {
        "bhav_symbols": ["FINNIFTY"],
        "step_size": 50,
        "fyers_symbol": "NSE:FINNIFTY-INDEX",
        "default_spot": 24500.0,
    },
    "MIDCPNIFTY": {
        "bhav_symbols": ["MIDCPNIFTY"],
        "step_size": 25,
        "fyers_symbol": "NSE:MIDCPNIFTY-INDEX",
        "default_spot": 12800.0,
    },
    "NIFTYNXT50": {
        "bhav_symbols": ["NIFTYNXT50"],
        "step_size": 100,
        "fyers_symbol": "NSE:NIFTYNXT50-INDEX",
        "default_spot": 71000.0,
    },
    "SENSEX": {
        "bhav_symbols": ["SENSEX", "BSX"],
        "step_size": 100,
        "fyers_symbol": "BSE:SENSEX-INDEX",
        "default_spot": 84350.0,
    },
    "BANKEX": {
        "bhav_symbols": ["BANKEX", "BKX"],
        "step_size": 100,
        "fyers_symbol": "BSE:BANKEX-INDEX",
        "default_spot": 72000.0,
    },
}

# ==========================================
# SIDEBAR: SETTINGS & FYERS API INPUTS
# ==========================================
st.sidebar.header("1. Index & Broker Settings")
index_choice = st.sidebar.selectbox("Select Index", list(INDEX_CONFIG.keys()))
selected_cfg = INDEX_CONFIG[index_choice]
step_size = selected_cfg["step_size"]

use_fyers = st.sidebar.checkbox("Fetch Live Spot from Fyers API", value=False)
fyers_client_id = st.sidebar.text_input("Fyers App ID (Client ID)", type="password")
fyers_access_token = st.sidebar.text_input("Fyers Access Token", type="password")

manual_spot = st.sidebar.number_input(
    "Or Enter Simulated / Live Open Price",
    value=selected_cfg["default_spot"],
    step=float(step_size),
)

# ==========================================
# 2. MULTI-FILE BHAVCOPY UPLOADER (.ZIP & .CSV)
# ==========================================
st.header("2. Upload 20–25 NSE (.zip) or BSE (.csv) UDiFF Bhavcopies")
uploaded_files = st.file_uploader(
    "Drag and drop NSE Bhavcopy (.zip) or BSE Bhavcopy (.csv) files here",
    type=["zip", "csv"],
    accept_multiple_files=True,
)


def read_bhavcopy_file(uploaded_file):
    """Reads either a CSV directly (BSE) or extracts the CSV inside a ZIP (NSE)."""
    filename = uploaded_file.name.lower()
    if filename.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(uploaded_file.read())) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                return None
            with zf.open(csv_names[0]) as csv_file:
                return pd.read_csv(csv_file)
    else:
        return pd.read_csv(uploaded_file)


def process_bhavcopies(files, valid_symbols):
    df_list = []

    for file in files[-25:]:
        try:
            df = read_bhavcopy_file(file)
            if df is None:
                st.warning(f"Skipping {file.name}: No CSV found inside archive.")
                continue

            df.columns = df.columns.str.strip()

            if "TckrSymb" not in df.columns or "FinInstrmTp" not in df.columns:
                st.warning(f"Skipping {file.name}: Missing UDiFF columns (TckrSymb / FinInstrmTp).")
                continue

            df["TckrSymb"] = df["TckrSymb"].astype(str).str.strip()
            df["FinInstrmTp"] = df["FinInstrmTp"].astype(str).str.strip()

            filtered = df[
                (df["TckrSymb"].isin(valid_symbols))
                & (df["FinInstrmTp"].isin(["OPTIDX", "IO"]))
            ].copy()

            if not filtered.empty:
                df_list.append(filtered)
        except Exception as e:
            st.warning(f"Error reading {file.name}: {e}")

    if not df_list:
        return None, None, None

    master_df = pd.concat(df_list, ignore_index=True)
    master_df["TradDt"] = pd.to_datetime(master_df["TradDt"])
    master_df["XpryDt"] = pd.to_datetime(master_df["XpryDt"])
    master_df["OptnTp"] = master_df["OptnTp"].astype(str).str.strip()

    latest_date = master_df["TradDt"].max()
    nearest_expiry = master_df[master_df["TradDt"] == latest_date]["XpryDt"].min()
    expiry_df = master_df[master_df["XpryDt"] == nearest_expiry].sort_values("TradDt")

    return expiry_df, latest_date, nearest_expiry


def get_fyers_live_price(client_id, token, fyers_symbol):
    from fyers_apiv3 import fyersModel

    fyers = fyersModel.FyersModel(client_id=client_id, token=token, is_async=False)
    response = fyers.quotes(data={"symbols": fyers_symbol})
    if response.get("s") == "ok" and response.get("d"):
        return response["d"][0]["v"]["lp"]
    else:
        raise Exception(f"Fyers API Error: {response}")


# ==========================================
# 3. RUN ANALYSIS & RENDER UI OUTPUT
# ==========================================
if uploaded_files:
    with st.spinner(f"Extracting and analyzing {len(uploaded_files)} Bhavcopy file(s) for {index_choice}..."):
        expiry_df, latest_date, nearest_expiry = process_bhavcopies(
            uploaded_files, selected_cfg["bhav_symbols"]
        )

    if expiry_df is None or expiry_df.empty:
        st.error(
            f"No valid **{index_choice}** options data found in the uploaded files. "
            f"Verify that your files match the selected exchange (NSE `.zip` vs BSE `.csv`)."
        )
    else:
        latest_eod = expiry_df[expiry_df["TradDt"] == latest_date].copy()
        ce_df = latest_eod[latest_eod["OptnTp"] == "CE"].set_index("StrkPric")
        pe_df = latest_eod[latest_eod["OptnTp"] == "PE"].set_index("StrkPric")

        total_pe_oi = pe_df["OpnIntrst"].sum()
        total_ce_oi = ce_df["OpnIntrst"].sum()
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0

        major_call_wall = ce_df["OpnIntrst"].idxmax()
        major_put_wall = pe_df["OpnIntrst"].idxmax()

        # Trapped Call Writers (Top 25% OI addition on latest EOD)
        trapped_ce = ce_df[
            ce_df["ChngInOpnIntrst"] > ce_df["ChngInOpnIntrst"].quantile(0.75)
        ].sort_values(by="OpnIntrst", ascending=False)
        trapped_strikes = trapped_ce.index.tolist()[:5]

        # Determine Live / Open Price
        live_price = manual_spot
        if use_fyers and fyers_client_id and fyers_access_token:
            try:
                live_price = get_fyers_live_price(
                    fyers_client_id, fyers_access_token, selected_cfg["fyers_symbol"]
                )
                st.sidebar.success(f"Live Fyers {index_choice}: {live_price}")
            except Exception as e:
                st.sidebar.error(str(e))

        # Display Key Metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Latest EOD Date", latest_date.strftime("%d %b %Y"))
        col2.metric("Nearest Expiry", nearest_expiry.strftime("%d %b %Y"))
        col3.metric("EOD Put-Call Ratio (PCR)", pcr)
        col4.metric(f"{index_choice} Live / Open", live_price)

        st.divider()

        # Gap-Up Squeeze Check
        breached = [s for s in trapped_strikes if live_price > s]
        if breached:
            atm_strike = round(live_price / step_size) * step_size
            effective_strike = atm_strike - step_size
            st.success(
                f"🚀 **SHORT SQUEEZE ALERT ({index_choice}):** Open price ({live_price}) breached trapped Call strikes: {breached}. "
                f"**Most Effective Strike to Watch:** `{int(effective_strike)} CE`"
            )
        else:
            st.info(
                f"No major trapped Call walls breached yet for **{index_choice}**. "
                f"Major Resistance Wall is at **{int(major_call_wall)} CE** | Major Support at **{int(major_put_wall)} PE**."
            )

        # Display Top Call & Put Strikes Side-by-Side
        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"Top Trapped {index_choice} Call (CE) Strikes")
            st.dataframe(trapped_ce[["ClsPric", "OpnIntrst", "ChngInOpnIntrst"]].head(10))
        with c2:
            st.subheader(f"Top {index_choice} Put (PE) Support Strikes")
            st.dataframe(
                pe_df[["ClsPric", "OpnIntrst", "ChngInOpnIntrst"]]
                .sort_values(by="OpnIntrst", ascending=False)
                .head(10)
            )
else:
    st.info("👈 Upload your NSE Bhavcopy (.zip) or BSE Bhavcopy (.csv) files above to generate the OI & Strike report.")
