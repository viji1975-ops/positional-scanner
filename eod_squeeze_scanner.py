import pandas as pd
from datetime import datetime
import os
import tkinter as tk
from tkinter import filedialog

def select_csv_file():
    """Opens a native file upload dialog to pick your EOD CSV file."""
    root = tk.Tk()
    root.withdraw()  # Hide the empty main tkinter window
    root.attributes('-topmost', True)  # Bring the file dialog to the front
    file_path = filedialog.askopenfilename(
        title="Select your daily EOD Option CSV file",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
    )
    root.destroy()
    return file_path

def generate_evening_report(csv_filepath, output_folder="reports", min_premium=80.0):
    if not csv_filepath:
        print("No file selected. Exiting.")
        return

    # 1. Load and clean EOD CSV data
    df = pd.read_csv(csv_filepath)
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

    # 4. Export Clean Excel (.xlsx) and CSV (.csv) Reports
    os.makedirs(output_folder, exist_ok=True)
    date_tag = datetime.now().strftime("%Y-%m-%d")
    excel_path = os.path.join(output_folder, f"{index_name}_Prep_Card_{date_tag}.xlsx")
    csv_path = os.path.join(output_folder, f"{index_name}_Prep_Card_{date_tag}.csv")

    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        prep_df.to_excel(writer, sheet_name="Evening_Prep_Card", index=False)
        straddle_summary.to_excel(writer, sheet_name="ATM_Straddle_Math", index=False)
        top_institutional.to_excel(writer, sheet_name="Top_10_Institutional", index=False)

    prep_df.to_csv(csv_path, index=False)

    # 5. Print Summary to Console
    print("\n" + "="*95)
    print(f" ATM STRADDLE BREAKEVEN — {index_name} (Expiry: {expiry_date})")
    print("="*95)
    print(straddle_summary.to_string(index=False))
    print("\n" + "="*95)
    print(f" EVENING SQUEEZE PREP CARD")
    print("="*95)
    print(prep_df.to_string(index=False))
    print("="*95)
    print(f"Saved Excel report to: {excel_path}")
    print(f"Saved CSV report to:   {csv_path}\n")

if __name__ == "__main__":
    print("Opening file picker to select your EOD CSV file...")
    uploaded_csv = select_csv_file()
    generate_evening_report(uploaded_csv, output_folder="reports", min_premium=80.0)
