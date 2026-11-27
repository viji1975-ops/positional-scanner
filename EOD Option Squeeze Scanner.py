import streamlit as st
import pandas as pd
from datetime import datetime
import io

st.set_page_config(page_title="EOD Option Squeeze Scanner", layout="wide")
st.title("📊 EOD Option Squeeze & Straddle Scanner")
st.caption("Supports both Index CSVs and F&O Stock Option CSV exports (including NSE Bhavcopy / OI Action formats).")

def standardize_columns(df):
    df.columns = [str(c).strip() for c in df.columns]
    
    col_aliases = {
        'Index': ['index', 'symbol', 'stock', 'underlying', 'ticker', 'instrument'],
        'Expiry': ['expiry', 'expiry date', 'expiry_date', 'expiry_dt', 'exp'],
        'Type': ['type', 'option type', 'option_type', 'option_typ', 'opt_type', 'ce/pe'],
        'Strike': ['strike', 'strike price', 'strike_price', 'strike_pr'],
        'Close': ['close', 'ltp', 'close price', 'close_price', 'last price', 'settle_pr'],
        'Chg%': ['chg%', 'change%', '%chg', 'change %', 'pchange', 'pct_chg'],
        'Volume': ['volume', 'vol', 'contracts', 'no. of contracts', 'traded qty'],
        'Cr': ['cr', 'turnover', 'turnover (cr)', 'value', 'value (cr)', 'turnover_cr', 'val_inlakh'],
        'OI': ['oi', 'open int', 'open_int', 'open interest', 'open_interest'],
        'OI_Chg': ['oi_chg', 'chg in oi', 'chg_in_oi', 'change in oi', 'oi change', 'oi_change'],
        'OI_Action': ['oi_action', 'oi action', 'action', 'buildup']
    }
    
    rename_map = {}
    used_cols = set()
    for standard_name, aliases in col_aliases.items():
        for col in df.columns:
            if col not in used_cols and col.lower() in aliases:
                rename_map[col] = standard_name
                used_cols.add(col)
                break
                
    return df.rename(columns=rename_map)

# Sidebar settings
st.sidebar.header("Scanner Settings")
asset_type = st.sidebar.radio("Instrument Type", ["F&O Stock", "Index"], index=0)
default_prem = 10.0 if asset_type == "F&O Stock" else 80.0
min_premium = st.sidebar.number_input(
    "Minimum Option Premium (₹)", 
    value=default_prem, 
    step=5.0,
    help="F&O Stocks typically have lower premiums (₹5–₹40) than Indices (₹80+)."
)

uploaded_file = st.file_uploader("Upload your daily EOD Option CSV file", type=["csv"])

if uploaded_file is not None:
    raw_df = pd.read_csv(uploaded_file)
    df = standardize_columns(raw_df.copy())

    # Core required columns present in both formats
    required_cols = ['Strike', 'Type', 'Close', 'OI', 'OI_Chg']
    missing_cols = [c for c in required_cols if c not in df.columns]
    
    if missing_cols:
        st.error(f"❌ Missing expected columns: **{', '.join(missing_cols)}**")
        st.write("**Columns found in your uploaded CSV:**", list(raw_df.columns))
        st.stop()

    # Clean numeric columns
    numeric_cols = ['Strike', 'Close', 'Chg%', 'Volume', 'Cr', 'OI', 'OI_Chg']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(',', '', regex=False)
                .str.replace('%', '', regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Clean Type & OI_Action columns
    df['Type'] = df['Type'].astype(str).str.strip().str.upper().replace({'CALL': 'CE', 'PUT': 'PE'})
    if 'OI_Action' in df.columns:
        df['OI_Action'] = df['OI_Action'].astype(str).str.strip().str.upper()

    # Extract Symbol/Index name and Expiry safely from columns or filename
    if 'Index' in df.columns and not df['Index'].dropna().empty:
        symbol_name = str(df['Index'].dropna().iloc).strip()
    else:
        # Clean filename fallback (e.g., '2026-11-26_RELIANCE_export.csv' -> 'RELIANCE' or clean stem)
        symbol_name = uploaded_file.name.rsplit('.', 1)
        
    expiry_date = str(df['Expiry'].dropna().iloc).strip() if 'Expiry' in df.columns and not df['Expiry'].dropna().empty else "Current Expiry"

    # 2. Automated ATM Straddle Breakeven Calculation
    ce_df = df[df['Type'] == 'CE'][['Strike', 'Close']].rename(columns={'Close': 'CE_Close'}).dropna()
    pe_df = df[df['Type'] == 'PE'][['Strike', 'Close']].rename(columns={'Close': 'PE_Close'}).dropna()
    straddle_df = pd.merge(ce_df, pe_df, on='Strike')

    if not straddle_df.empty:
        straddle_df['Diff'] = (straddle_df['CE_Close'] - straddle_df['PE_Close']).abs()
        atm_row = straddle_df.sort_values(by='Diff').iloc
        atm_strike = atm_row['Strike']
        atm_strike_display = int(atm_strike) if atm_strike == int(atm_strike) else round(atm_strike, 2)
        ce_prem = atm_row['CE_Close']
        pe_prem = atm_row['PE_Close']
        straddle_pts = ce_prem + pe_prem
        upper_be = atm_strike + straddle_pts
        lower_be = atm_strike - straddle_pts
    else:
        atm_strike_display = ce_prem = pe_prem = straddle_pts = upper_be = lower_be = 0

    straddle_summary = pd.DataFrame([{
        "Symbol": symbol_name,
        "Expiry": expiry_date,
        "ATM_Strike": atm_strike_display,
        "ATM_CE_Close": f"₹{ce_prem:.2f}",
        "ATM_PE_Close": f"₹{pe_prem:.2f}",
        "Straddle_Points": f"{straddle_pts:.2f}",
        "Upper_Straddle_Target": f"{upper_be:.2f}",
        "Lower_Straddle_Target": f"{lower_be:.2f}"
    }])

    st.subheader(f"🎯 ATM Straddle Breakeven — {symbol_name} ({expiry_date})")
    st.dataframe(straddle_summary, use_container_width=True, hide_index=True)

    # 3. Filter Top 10 Institutional Activity (Rank by 'Cr' if available, else by 'OI')
    has_turnover = 'Cr' in df.columns and df['Cr'].notna().any()
    rank_col = 'Cr' if has_turnover else 'OI'
    
    top_institutional = df.sort_values(by=rank_col, ascending=False).head(10).copy()
    liquid = top_institutional[top_institutional['Close'] >= min_premium].copy()
    liquid['Squeeze_Score'] = liquid['OI_Chg'] + (liquid['OI'] * 0.25)

    def get_top_candidate(opt_type, is_writing):
        base = liquid[(liquid['Type'] == opt_type) & (liquid['OI_Chg'] > 0)]
        if base.empty:
            return None
            
        # Use OI_Action if present (e.g., F&O Stock CSV), otherwise use Chg% (Index CSV)
        if 'OI_Action' in base.columns and base['OI_Action'].notna().any():
            target_keyword = 'SHORT' if is_writing else 'LONG'
            subset = base[base['OI_Action'].str.contains(target_keyword, na=False)]
        elif 'Chg%' in base.columns and base['Chg%'].notna().any():
            subset = base[base['Chg%'] < 0] if is_writing else base[base['Chg%'] > 0]
        else:
            subset = pd.DataFrame()
            
        return None if subset.empty else subset.sort_values(by='Squeeze_Score', ascending=False).iloc

    candidates = [
        ("#1 Bullish Short Squeeze (CE Write)", get_top_candidate('CE', True), "CE", True),
        ("#1 Bearish Short Squeeze (PE Write)", get_top_candidate('PE', True), "PE", True),
        ("#1 Bearish Long Squeeze (CE Buy)",   get_top_candidate('CE', False), "CE", False),
        ("#1 Bullish Long Squeeze (PE Buy)",   get_top_candidate('PE', False), "PE", False),
    ]

    prep_rows = []
    for role, row, opt_type, is_writing in candidates:
        if row is not None:
            strike_val = row['Strike']
            strike_disp = int(strike_val) if strike_val == int(strike_val) else round(strike_val, 2)
            close_p = row['Close']
            if is_writing:
                be = strike_val + close_p if opt_type == "CE" else strike_val - close_p
                direction = "Calls" if opt_type == "CE" else "Puts"
                trigger = f"Buy {direction} if 5m close > ₹{close_p:.2f} (Seller BE: {be:.1f})"
            else:
                side = "downside" if opt_type == "CE" else "upside"
                trigger = f"Confirms {side} if 5m close < ₹{close_p:.2f}"
                
            activity_metric = f"₹{row['Cr']/100:.0f} Cr" if has_turnover else str(row.get('OI_Action', 'Active OI'))
            
            prep_rows.append({
                "Role": role,
                "Strike": f"{strike_disp} {opt_type}",
                "EOD_Close": f"₹{close_p:.2f}",
                "OI_Chg_Lakhs": f"+{row['OI_Chg']/100000:.2f}L",
                "Total_OI_Lakhs": f"{row['OI']/100000:.2f}L",
                "Turnover / Action": activity_metric,
                "Next_Day_Trigger": trigger
            })
        else:
            prep_rows.append({
                "Role": role, "Strike": "None", "EOD_Close": "-",
                "OI_Chg_Lakhs": "-", "Total_OI_Lakhs": "-", "Turnover / Action": "-",
                "Next_Day_Trigger": "No dominant signal in top liquid rows"
            })

    prep_df = pd.DataFrame(prep_rows)

    st.subheader(f"⚡ Evening Squeeze Prep Card — {symbol_name}")
    st.dataframe(prep_df, use_container_width=True, hide_index=True)

    st.info("**Golden Execution Rule:** Wait until **9:30 AM**. Enter ONLY when a Short Squeeze triggers (`> Close`) at the **exact same time** the opposite side's Long Squeeze or Support breaks (`< Close`).")

    # 4. Export Clean 3-Sheet Excel (.xlsx) & CSV Download Buttons
    date_tag = datetime.now().strftime("%Y-%m-%d")
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        prep_df.to_excel(writer, sheet_name="Evening_Prep_Card", index=False)
        straddle_summary.to_excel(writer, sheet_name="ATM_Straddle_Math", index=False)
        top_institutional.to_excel(writer, sheet_name="Top_10_Institutional", index=False)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="⬇️ Download 3-Sheet Excel Report (.xlsx)",
            data=excel_buffer.getvalue(),
            file_name=f"{symbol_name}_Prep_Card_{date_tag}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with col2:
        st.download_button(
            label="⬇️ Download Prep Card CSV (.csv)",
