import streamlit as st
import pandas as pd
from datetime import datetime
import io

st.set_page_config(page_title="EOD Option Squeeze Scanner", layout="wide")
st.title("📊 EOD Option Squeeze & Straddle Scanner")
st.caption("Upload your daily EOD Option CSV to generate your Evening Prep Card, ATM Straddle Breakeven, and Excel report.")

# Sidebar settings
min_premium = st.sidebar.number_input("Minimum Option Premium (₹)", value=80.0, step=10.0)

# Streamlit Web File Uploader (Replaces tkinter)
uploaded_file = st.file_uploader("Upload your daily EOD Option CSV file", type=["csv"])

if uploaded_file is not None:
    # 1. Load and clean EOD CSV data
    df = pd.read_csv(uploaded_file)
    numeric_cols = ['Strike', 'Close', 'Chg%', 'Volume', 'Cr', 'OI', 'OI_Chg']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    index_name = str(df['Index'].iloc[0])
    expiry_date = str(df['Expiry'].iloc[0])

    # 2. Automated ATM Straddle Breakeven Calculation
    ce_df = df[df['Type'] == 'CE'][['Strike', 'Close']].rename(columns={'Close': 'CE_Close'})
    pe_df = df[df['Type'] == 'PE'][['Strike', 'Close']].rename(columns={'Close': 'PE_Close'})
    straddle_df = pd.merge(ce_df, pe_df, on='Strike')

    if not straddle_df.empty:
        straddle_df['Diff'] = (straddle_df['CE_Close'] - straddle_df['PE_Close']).abs()
        atm_row = straddle_df.sort_values(by='Diff').iloc[0]
        atm_strike = int(atm_row['Strike'])
        ce_prem = atm_row['CE_Close']
        pe_prem = atm_row['PE_Close']
        straddle_pts = ce_prem + pe_prem
        upper_be = atm_strike + straddle_pts
        lower_be = atm_strike - straddle_pts
    else:
        atm_strike = ce_prem = pe_prem = straddle_pts = upper_be = lower_be = 0

    straddle_summary = pd.DataFrame([{
        "Index": index_name,
        "Expiry": expiry_date,
        "ATM_Strike": atm_strike,
        "ATM_CE_Close": f"₹{ce_prem:.2f}",
        "ATM_PE_Close": f"₹{pe_prem:.2f}",
        "Straddle_Points": f"{straddle_pts:.2f}",
        "Upper_Straddle_Target": f"{upper_be:.2f}",
        "Lower_Straddle_Target": f"{lower_be:.2f}"
    }])

    st.subheader(f"🎯 ATM Straddle Breakeven — {index_name} (Expiry: {expiry_date})")
    st.dataframe(straddle_summary, use_container_width=True, hide_index=True)

    # 3. Filter Top 10 Institutional Turnover (Cr) & Liquid Strikes
    top_institutional = df.sort_values(by='Cr', ascending=False).head(10).copy()
    liquid = top_institutional[top_institutional['Close'] >= min_premium].copy()
    liquid['Squeeze_Score'] = liquid['OI_Chg'] + (liquid['OI'] * 0.25)

    def get_top_candidate(opt_type, is_writing):
        if is_writing:
            subset = liquid[(liquid['Type'] == opt_type) & (liquid['Chg%'] < 0) & (liquid['OI_Chg'] > 0)]
        else:
            subset = liquid[(liquid['Type'] == opt_type) & (liquid['Chg%'] > 0) & (liquid['OI_Chg'] > 0)]
        return None if subset.empty else subset.sort_values(by='Squeeze_Score', ascending=False).iloc[0]

    candidates = [
        ("#1 Bullish Short Squeeze (CE Write)", get_top_candidate('CE', True), "CE", True),
        ("#1 Bearish Short Squeeze (PE Write)", get_top_candidate('PE', True), "PE", True),
        ("#1 Bearish Long Squeeze (CE Buy)",   get_top_candidate('CE', False), "CE", False),
        ("#1 Bullish Long Squeeze (PE Buy)",   get_top_candidate('PE', False), "PE", False),
    ]

    prep_rows = []
    for role, row, opt_type, is_writing in candidates:
        if row is not None:
            strike = int(row['Strike'])
            close_p = row['Close']
            if is_writing:
                be = strike + close_p if opt_type == "CE" else strike - close_p
                direction = "Calls" if opt_type == "CE" else "Puts"
                trigger = f"Buy {direction} if 5m close > ₹{close_p:.2f} (Seller BE: {be:.1f})"
            else:
                side = "downside" if opt_type == "CE" else "upside"
                trigger = f"Confirms {side} if 5m close < ₹{close_p:.2f}"
            prep_rows.append({
                "Role": role,
                "Strike": f"{strike} {opt_type}",
                "EOD_Close": f"₹{close_p:.2f}",
                "OI_Chg_Lakhs": f"+{row['OI_Chg']/100000:.2f}L",
                "Total_OI_Lakhs": f"{row['OI']/100000:.2f}L",
                "Turnover_Cr": f"₹{row['Cr']/100:.0f} Cr",
                "Next_Day_Trigger": trigger
            })
        else:
            prep_rows.append({
                "Role": role, "Strike": "None", "EOD_Close": "-",
                "OI_Chg_Lakhs": "-", "Total_OI_Lakhs": "-", "Turnover_Cr": "-",
                "Next_Day_Trigger": "No dominant signal in top liquid rows"
            })

    prep_df = pd.DataFrame(prep_rows)

    st.subheader("⚡ Evening Squeeze Prep Card")
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
            file_name=f"{index_name}_Prep_Card_{date_tag}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with col2:
        st.download_button(
            label="⬇️ Download Prep Card CSV (.csv)",
            data=prep_df.to_csv(index=False).encode('utf-8'),
            file_name=f"{index_name}_Prep_Card_{date_tag}.csv",
            mime="text/csv"
        )
