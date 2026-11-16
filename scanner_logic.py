import pandas as pd
import numpy as np

INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

def prepare_bhavcopy_triggers(df: pd.DataFrame, trigger_col: str = "ClsPric") -> pd.DataFrame:
    """
    Standardizes NSE UDiFF Bhavcopy columns and extracts the trigger baseline.
    Common NSE UDiFF columns: TckrSymb, XpryDt, StrkPric, OptnTp, ClsPric, OpnIntrst, UndrlygPric
    """
    df = df.copy()
    # Filter only Index and Stock Options (exclude Futures)
    df = df[df["OptnTp"].isin(["CE", "PE"])].copy()
    
    # Create a unique composite key for merging across timeframes
    df["key"] = (
        df["TckrSymb"].astype(str).str.strip() + "_" +
        df["XpryDt"].astype(str).str.strip() + "_" +
        df["StrkPric"].astype(float).astype(str) + "_" +
        df["OptnTp"].astype(str).str.strip()
    )
    
    df["Trigger"] = pd.to_numeric(df[trigger_col], errors="coerce")
    df["EOD_OI"] = pd.to_numeric(df["OpnIntrst"], errors="coerce")
    df["Spot_Ref"] = pd.to_numeric(df["UndrlygPric"], errors="coerce")
    
    return df[["key", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "Trigger", "EOD_OI", "Spot_Ref"]]


def apply_scanner_filters(
    live_df: pd.DataFrame,
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame = None,
    monthly_df: pd.DataFrame = None,
    instrument_category: str = "INDEX",  # "INDEX" or "STOCK"
    require_confluence: bool = True
) -> pd.DataFrame:
    """
    Merges live Upstox quotes with Daily, Weekly, and Monthly Bhavcopy triggers
    and applies tailored liquidity and strike-distance filters.
    
    Expected live_df columns: ['key', 'ltp', 'volume', 'live_oi', 'bid', 'ask']
    """
    # 1. Merge Live Data with Daily (Intraday) Trigger
    merged = pd.merge(daily_df, live_df, on="key", how="inner")
    merged.rename(columns={"Trigger": "Daily_Trigger"}, inplace=True)

    # 2. Separate Index vs Stock universe
    if instrument_category == "INDEX":
        merged = merged[merged["TckrSymb"].isin(INDEX_SYMBOLS)].copy()
        max_strike_dist = 0.02      # +/- 2% from spot (ATM to OTM-3)
        min_volume = 5000           # Minimum contracts traded
        max_spread_pct = 0.015      # Max 1.5% bid-ask spread
    else:
        merged = merged[~merged["TckrSymb"].isin(INDEX_SYMBOLS)].copy()
        max_strike_dist = 0.05      # +/- 5% from spot (ATM to OTM-1)
        min_volume = 300            # Minimum contracts traded
        max_spread_pct = 0.03       # Max 3.0% bid-ask spread

    # 3. Strike Distance Filter (eliminates deep OTM false spikes)
    merged["Strike_Dist_Pct"] = abs(merged["StrkPric"] - merged["Spot_Ref"]) / merged["Spot_Ref"]
    merged = merged[merged["Strike_Dist_Pct"] <= max_strike_dist]

    # 4. Liquidity, Spread & Open Interest Filters
    merged["Spread_Pct"] = (merged["ask"] - merged["bid"]) / merged["ltp"].replace(0, np.nan)
    merged = merged[
        (merged["volume"] >= min_volume) &
        (merged["Spread_Pct"] <= max_spread_pct) &
        (merged["live_oi"] > merged["EOD_OI"]) &      # Fresh OI buildup
        (merged["ltp"] > merged["Daily_Trigger"])     # Above Daily Trigger
    ]

    # 5. Merge Weekly and Monthly Triggers for Multi-Timeframe Confluence
    if weekly_df is not None:
        wk = weekly_df[["key", "Trigger"]].rename(columns={"Trigger": "Weekly_Trigger"})
        merged = pd.merge(merged, wk, on="key", how="left")
        if require_confluence:
            merged = merged[merged["ltp"] > merged["Weekly_Trigger"]]

    if monthly_df is not None and instrument_category == "STOCK":
        mo = monthly_df[["key", "Trigger"]].rename(columns={"Trigger": "Monthly_Trigger"})
        merged = pd.merge(merged, mo, on="key", how="left")
        if require_confluence:
            merged = merged[merged["ltp"] > merged["Monthly_Trigger"]]

    # 6. Calculate Percentage Change over Daily Trigger
    merged["Change_%"] = ((merged["ltp"] - merged["Daily_Trigger"]) / merged["Daily_Trigger"]) * 100
    merged = merged.sort_values(by="Change_%", ascending=False)

    return merged
