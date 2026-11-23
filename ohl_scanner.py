import os
import time
from datetime import datetime, timedelta
import requests
import pandas as pd
from rich.console import Console
from rich.table import Table

# ==========================================
# 1. CONFIGURATION & WATCHLIST
# ==========================================
# Reads token from GitHub Secrets / Environment Variable, or fallback to string
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN", "PASTE_YOUR_DAILY_TOKEN_HERE")

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# Expandable Watchlist (Symbol: Upstox Instrument Key)
# You can download the full NSE instrument JSON from Upstox to add 100+ stocks
WATCHLIST = {
    "NSE:RELIANCE":  "NSE_EQ|INE002A01018",
    "NSE:HDFCBANK":  "NSE_EQ|INE040A01034",
    "NSE:ICICIBANK": "NSE_EQ|INE090A01021",
    "NSE:INFY":      "NSE_EQ|INE009A01021",
    "NSE:TCS":       "NSE_EQ|INE467B01029",
    "NSE:VEDL":      "NSE_EQ|INE205A01025",
    "NSE:SBIN":      "NSE_EQ|INE062A01020",
    "NSE:TATAMOTORS":"NSE_EQ|INE155A01022",
    "NSE:AXISBANK":  "NSE_EQ|INE238A01034",
    "NSE:BHARTIARTL":"NSE_EQ|INE397D01024",
}

# Tolerance for Open==Low / Open==High (0.0 for strict match like Pine Script)
TOLERANCE_PCT = 0.00  

console = Console()

# ==========================================
# 2. DATA FETCHING FUNCTIONS (UPSTOX V3/V2)
# ==========================================
def get_20d_avg_15m_volume(instrument_key: str) -> float:
    """Fetches past 30 days of 15-min candles to compute 20-period SMA volume."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    encoded_key = instrument_key.replace("|", "%7C")
    
    url = f"https://api.upstox.com/v3/historical-candle/{encoded_key}/minutes/15/{to_date}/{from_date}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    
    if resp.status_code != 200:
        return 0.0
        
    candles = resp.json().get("data", {}).get("candles", [])
    if not candles:
        return 0.0
        
    # Upstox candle format: [timestamp, open, high, low, close, volume, oi]
    df = pd.DataFrame(candles, columns=["ts", "o", "h", "l", "c", "v", "oi"])
    # Take last 20 completed 15-min candles
    return float(df["v"].head(20).mean())

def get_intraday_candles(instrument_key: str):
    """Fetches today's 15-minute intraday candles."""
    encoded_key = instrument_key.replace("|", "%7C")
    url = f"https://api.upstox.com/v3/historical-candle/intraday/{encoded_key}/minutes/15"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    
    if resp.status_code != 200:
        return None
        
    candles = resp.json().get("data", {}).get("candles", [])
    if not candles:
        return None
        
    # Upstox returns newest candle first; reverse so index 0 is 09:15 AM
    candles.reverse()
    return candles

# ==========================================
# 3. CORE SCANNER ENGINE (PINE SCRIPT LOGIC)
# ==========================================
def run_scanner():
    console.clear()
    console.print(f"[bold cyan]NSE OHL Ultimate Scanner Pro[/bold cyan] | Last Updated: {datetime.now().strftime('%H:%M:%S IST')}\n")
    
    table = Table(show_header=True, header_style="bold white on grey23")
    table.add_column("Symbol", style="bold white")
    table.add_column("Pattern")
    table.add_column("Status")
    table.add_column("Normal Tgt (1:1 | 1:2)", style="cyan")
    table.add_column("Rev Target")
    table.add_column("Stop Loss", style="red")
    table.add_column("Volume", justify="right")
    table.add_column("Power", justify="center")

    results_for_csv = []

    for symbol, inst_key in WATCHLIST.items():
        candles = get_intraday_candles(inst_key)
        if not candles:
            continue

        # First 15-min candle of the day (09:15 AM - 09:30 AM)
        first_candle = candles[0]
        o = float(first_candle[1])
        h = float(first_candle[2])
        l = float(first_candle[3])
        v = float(first_candle[5])
        
        # Latest closing price from most recent candle
        c = float(candles[-1][4])

        # OHL Pattern Detection
        is_ol = (abs(o - l) <= o * TOLERANCE_PCT) and (h > o)
        is_oh = (abs(o - h) <= o * TOLERANCE_PCT) and (l < o)

        if not (is_ol or is_oh):
            continue

        # Volume Multiplier & Power Rating
        avg_vol = get_20d_avg_15m_volume(inst_key)
        v_mult = (v / avg_vol) if avg_vol > 0 else 1.0

        if v_mult > 3.0:
            power_txt = "[bold white on purple] 🔥 Ultra [/bold white on purple]"
            power_raw = "Ultra"
        elif v_mult > 1.5:
            power_txt = "[bold white on blue] ⚡ Strong [/bold white on blue]"
            power_raw = "Strong"
        else:
            power_txt = "[bold black on yellow] ⚠️ Weak [/bold black on yellow]"
            power_raw = "Weak"

        candle_range = h - l
        status_txt = "[green]Active[/green]"
        status_raw = "Active"
        rev_tgt_txt = "[grey50]N/A[/grey50]"
        rev_raw = "N/A"

        if is_ol:
            pat_txt = "[green]Open=Low[/green]"
            pat_raw = "Open=Low"
            t1 = o + candle_range
            t2 = o + (2.0 * candle_range)
            sl = l
            norm_tgt = f"{t1:.1f} | {t2:.1f}"

            if c < o:
                rev_val = o - (2.0 * candle_range)
                status_txt = "[magenta]Breached ❌[/magenta]"
                status_raw = "Breached"
                rev_tgt_txt = f"[magenta]{rev_val:.1f}[/magenta]"
                rev_raw = f"{rev_val:.1f}"
                sl = h  # Reversal stop loss

        elif is_oh:
            pat_txt = "[red]Open=High[/red]"
            pat_raw = "Open=High"
            t1 = o - candle_range
            t2 = o - (2.0 * candle_range)
            sl = h
            norm_tgt = f"{t1:.1f} | {t2:.1f}"

            if c > o:
                rev_val = o + (2.0 * candle_range)
                status_txt = "[orange1]Breached ❌[/orange1]"
                status_raw = "Breached"
                rev_tgt_txt = f"[orange1]{rev_val:.1f}[/orange1]"
                rev_raw = f"{rev_val:.1f}"
                sl = l  # Reversal stop loss

        table.add_row(
            symbol,
            pat_txt,
            status_txt,
            norm_tgt,
            rev_tgt_txt,
            f"{sl:.1f}",
            f"{v_mult:.2f}x",
            power_txt
        )

        results_for_csv.append({
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Symbol": symbol,
            "Pattern": pat_raw,
            "Status": status_raw,
            "LTP": c,
            "Targets_1_2": norm_tgt,
            "Rev_Target": rev_raw,
            "Stop_Loss": round(sl, 1),
            "Vol_Mult": round(v_mult, 2),
            "Power": power_raw
        })

    console.print(table)
    
    if results_for_csv:
        filename = f"ohl_signals_{datetime.now().strftime('%Y-%m-%d')}.csv"
        pd.DataFrame(results_for_csv).to_csv(filename, index=False)
        console.print(f"\n[dim]Saved snapshot to {filename}[/dim]")

if __name__ == "__main__":
    # Runs every 60 seconds during market hours
    while True:
        try:
            run_scanner()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        time.sleep(60)
