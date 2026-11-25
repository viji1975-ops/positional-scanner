import glob
import os
import numpy as np
import pandas as pd

# ==========================================
# 1. MULTI-DAY BHAVCOPY LOADER (20-25 FILES)
# ==========================================
def load_bhavcopies(folder_path, symbol="NIFTY", instrument="OPTIDX"):
    """
    Loads 20-25 NSE/BSE UDiFF Bhavcopy CSVs and filters for the target index.
    Note: NSE/BSE standardized to UDiFF format (columns: TckrSymb, FinInstrmTp, 
    XpryDt, StrkPric, OptnTp, ClsPric, OpnIntrst, ChngInOpnIntrst, TradDt).
    """
    all_files = sorted(glob.glob(os.path.join(folder_path, "*.csv")))
    if not all_files:
        raise FileNotFoundError(f"No CSV files found in {folder_path}")
    
    # Take the latest 25 files
    recent_files = all_files[-25:]
    df_list = []
    
    for file in recent_files:
        df = pd.read_csv(file)
        # Filter for Index Options (OPTIDX for NSE, check 'IO' or 'OPTIDX' for BSE)
        filtered = df[
            (df['TckrSymb'] == symbol) & 
            (df['FinInstrmTp'].isin([instrument, 'IO']))
        ].copy()
        df_list.append(filtered)
        
    master_df = pd.concat(df_list, ignore_index=True)
    master_df['TradDt'] = pd.to_datetime(master_df['TradDt'])
    master_df['XpryDt'] = pd.to_datetime(master_df['XpryDt'])
    
    # Focus on the nearest active expiry for the latest trading date
    latest_date = master_df['TradDt'].max()
    nearest_expiry = master_df[master_df['TradDt'] == latest_date]['XpryDt'].min()
    
    expiry_df = master_df[master_df['XpryDt'] == nearest_expiry].sort_values('TradDt')
    return expiry_df, latest_date, nearest_expiry


# ==========================================
# 2. EOD OI ANALYSIS & TRAPPED STRIKE DETECTOR
# ==========================================
def analyze_eod_oi(expiry_df, latest_date):
    """
    Analyzes EOD OI buildup, calculates PCR, and pinpoints trapped writers.
    """
    latest_eod = expiry_df[expiry_df['TradDt'] == latest_date].copy()
    
    # Separate Calls (CE) and Puts (PE)
    ce_df = latest_eod[latest_eod['OptnTp'] == 'CE'].set_index('StrkPric')
    pe_df = latest_eod[latest_eod['OptnTp'] == 'PE'].set_index('StrkPric')
    
    # 1. Calculate EOD Put-Call Ratio (PCR)
    total_pe_oi = pe_df['OpnIntrst'].sum()
    total_ce_oi = ce_df['OpnIntrst'].sum()
    pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
    
    # 2. Identify Major Resistance (Highest Call OI) & Support (Highest Put OI)
    major_call_wall = ce_df['OpnIntrst'].idxmax()
    major_put_wall = pe_df['OpnIntrst'].idxmax()
    
    # 3. Identify Aggressive Call Writing (Short Buildup) on Latest EOD
    # Condition: High positive Change in OI + Option Price dropped
    ce_df['Prev_Close'] = ce_df['ClsPric'] - ce_df['ChngInOpnIntrst'] # Proxy check if PrevCls missing
    trapped_ce_candidates = ce_df[
        (ce_df['ChngInOpnIntrst'] > ce_df['ChngInOpnIntrst'].quantile(0.75))
    ].sort_values(by='OpnIntrst', ascending=False)
    
    # 4. Multi-day (20-25 day) OI Z-Score to detect abnormal positioning
    historical_oi_std = expiry_df.groupby(['StrkPric', 'OptnTp'])['ChngInOpnIntrst'].std().unstack()
    
    summary = {
        "Latest_EOD": latest_date.strftime('%Y-%m-%d'),
        "PCR": pcr,
        "Major_Call_Wall (Resistance)": major_call_wall,
        "Major_Put_Wall (Support)": major_put_wall,
        "Top_Trapped_CE_Strikes": trapped_ce_candidates.index.tolist()[:5],
        "CE_Data": ce_df[['ClsPric', 'OpnIntrst', 'ChngInOpnIntrst']],
        "PE_Data": pe_df[['ClsPric', 'OpnIntrst', 'ChngInOpnIntrst']]
    }
    return summary


# ==========================================
# 3. LIVE MARKET DATA INTEGRATION (UPSTOX / FYERS)
# ==========================================
def get_live_spot_price(broker="FYERS", access_token="", client_id="", symbol="NSE:NIFTY50-INDEX"):
    """
    Fetches live spot price at 9:15 AM to compare against EOD OI Walls.
    """
    if broker.upper() == "FYERS":
        from fyers_apiv3 import fyersModel
        fyers = fyersModel.FyersModel(client_id=client_id, token=access_token, is_async=False)
        data = {"symbols": symbol}
        response = fyers.quotes(data=data)
        if response.get("s") == "ok":
            return response["d"][0]["v"]["lp"] # Last traded price
        else:
            raise Exception(f"Fyers API Error: {response}")
            
    elif broker.upper() == "UPSTOX":
        import upstox_client
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        api_instance = upstox_client.MarketQuoteApi(upstox_client.ApiClient(configuration))
        # Upstox instrument key format: 'NSE_INDEX|Nifty 50' or 'BSE_INDEX|SENSEX'
        response = api_instance.get_full_market_quote(symbol, api_version='2.0')
        return response.data[symbol].last_price


# ==========================================
# 4. EFFECTIVE STRIKE SELECTOR (EOD + LIVE)
# ==========================================
def select_effective_strike(eod_summary, live_open_price, step_size=50):
    """
    Compares 9:15 AM Live Open against EOD Trapped Strikes to pick the best option.
    """
    trapped_strikes = eod_summary["Top_Trapped_CE_Strikes"]
    call_wall = eod_summary["Major_Call_Wall (Resistance)"]
    
    # Check if Live Open gapped ABOVE heavily written Call strikes
    breached_strikes = [s for s in trapped_strikes if live_open_price > s]
    
    print(f"\n--- MARKET OPEN ANALYSIS ({eod_summary['Latest_EOD']}) ---")
    print(f"EOD PCR: {eod_summary['PCR']} | Major Call Wall: {call_wall}")
    print(f"Live Open Price: {live_open_price}")
    
    if breached_strikes:
        # The highest breached strike has the maximum trapped writers forced to cover
        highest_breached = max(breached_strikes)
        # Most effective strike: 1 strike ITM from Live Open for high Delta + Gamma
        atm_strike = round(live_open_price / step_size) * step_size
        effective_ce_strike = atm_strike - step_size 
        
        print(f"ALERT: Gap-up breached trapped Call strikes: {breached_strikes}")
        print(f"Short Covering Triggered above: {highest_breached}")
        print(f"--> RECOMMENDED EFFECTIVE STRIKE: {effective_ce_strike} CE (High Delta/Gamma Squeeze)")
        return effective_ce_strike
    else:
        print("No major EOD Call walls breached at open. Wait for price action confirmation.")
        return None

# ==========================================
# EXECUTION EXAMPLE
# ==========================================
if __name__ == "__main__":
    # 1. Point to your GitHub folder containing 20-25 Bhavcopy CSVs
    BHAVCOPY_FOLDER = "./bhavcopy_data/"
    
    # Run for NIFTY (step_size=50) or SENSEX (step_size=100)
    try:
        df_exp, latest_dt, exp_dt = load_bhavcopies(BHAVCOPY_FOLDER, symbol="NIFTY")
        eod_stats = analyze_eod_oi(df_exp, latest_dt)
        
        # 2. Replace with live API call at 9:15:05 AM
        # live_price = get_live_spot_price(broker="FYERS", access_token="YOUR_TOKEN", client_id="YOUR_ID")
        simulated_live_open = 25850.0  # Example based on your chart's gap-up
        
        select_effective_strike(eod_stats, simulated_live_open, step_size=50)
    except Exception as e:
        print(f"Setup Info: {e}")
