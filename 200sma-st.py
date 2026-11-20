import os
import time
import datetime
import requests
import numpy as np
import pandas as pd
import streamlit as st

# ==========================================
# 1. CONFIGURATION
# ==========================================
ACCESS_TOKEN = st.secrets.get("UPSTOX_ACCESS_TOKEN", os.getenv("UPSTOX_ACCESS_TOKEN", ""))

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

INDICES = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT"
}

# ==========================================
# 2. PURE PANDAS / NUMPY INDICATORS
# ==========================================
def calculate_supertrend(df, period=10, multiplier=3):
    """Calculates SuperTrend direction (1 = Bullish, -1 = Bearish) without pandas_ta."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    # True Range & ATR (Wilder's smoothing)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    
    hl2 = (high + low) / 2
    upperband = hl2 + (multiplier * atr)
    lowerband = hl2 - (multiplier * atr)
    
    in_uptrend = [True] * len(df)
    
    for i in range(1, len(df)):
        if close.iloc[i] > upperband.iloc[i - 1]:
            in_uptrend[i] = True
        elif close.iloc[i] < lowerband.iloc[i - 1]:
            in_uptrend[i] = False
        else:
            in_uptrend[i] = in_uptrend[i - 1]
            if in_uptrend[i] and lowerband.iloc[i] < lowerband.iloc[i - 1]:
                lowerband.iloc[i] = lowerband.iloc[i - 1]
            if not in_uptrend[i] and upperband.iloc[i] > upperband.iloc[i - 1]:
                upperband.iloc[i] = upperband.iloc[i - 1]
                
    return pd.Series(np.where(in_uptrend, 1, -1), index=df.index)

def check_bullish_setup(df):
    """Checks if Close > 200 SMA and Close > SuperTrend(10,3)."""
    if df is None or len(df) < 205:
        return False, {}

    df["SMA_200"] = df["close"].rolling(window=200).mean()
    df["ST_DIR"] = calculate_supertrend(df, period=10, multiplier=3)
    
    latest = df.iloc[-1]
    close_price = latest["close"]
    
    above_sma = close_price > latest["SMA_200"]
    above_st = latest["ST_DIR"] == 1
    
    is_bullish = bool(above_sma and above_st)
    details = {
        "close": round(float(close_price), 2),
        "sma200": round(float(latest["SMA_200"]), 2),
        "supertrend_bullish": bool(above_st)
    }
    return is_bullish, details
