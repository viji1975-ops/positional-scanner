import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# Fetch Upstox Access Token from GitHub Secrets / Environment
ACCESS_TOKEN = os.getenv("UPSTOX_ACCESS_TOKEN")

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {ACCESS_TOKEN}"
}

# Sample Nifty 50 / High-Liquidity F&O Instrument Keys (Expand as needed)
INSTRUMENTS = {
    "NSE_EQ|INE467B01029": "NSE:TCS",
    "NSE_EQ|INE002A01018": "NSE:RELIANCE",
    "NSE_EQ|INE040A01034": "NSE:HDFCBANK",
    "NSE_EQ|INE090A01021": "NSE:ICICIBANK",
    "NSE_EQ|INE208A01029": "NSE:ASHOKLEY",
    "NSE_EQ|INE463V01026": "NSE:ANANDRATHI",
}

def get_historical_stats(instrument_key):
    """Fetches 20 days of daily candles to calculate 14-day ATR and 20-day Avg Volume."""
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d")
    url = f"https://upstox.com{instrument_key}/day/{to_date}/{from_date}"
    
    resp = requests.get(url, headers=HEADERS).json()
    candles = resp.get("data", {}).get("candles", [])
    
    if len(candles) < 15:
        return None, None

    # Upstox candle format: [timestamp, open, high, low, close, volume, oi]
    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume", "oi"])
    df = df.iloc[::-1].reset_index(drop=True)  # Sort oldest to newest

    # Calculate 14-day ATR
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "prev_close"]].max(axis=1) - df[["low", "prev_close"]].min(axis=1)
    atr_14 = df["tr"].tail(14).mean()

    # Calculate 20-day Average Volume
    avg_vol_20 = df["volume"].tail(20).mean()
    
    return round(atr_14, 2), avg_vol_20

def scan_ohol():
    keys_param = ",".join(INSTRUMENTS.keys())
    url = f"https://upstox.com{keys_param}"
    
    response = requests.get(url, headers=HEADERS).json()
    if response.get("status") != "success":
        print("Error fetching Upstox quotes:", response)
        return

    quotes = response.get("data", {})
    results = []

    for key, symbol in INSTRUMENTS.items():
        # Upstox keys in response use ':' instead of '|'
        resp_key = key.replace("|", ":")
        data = quotes.get(resp_key)
        if not data:
            continue

        ohlc = data.get("ohlc", {})
        open_p = ohlc.get("open", 0)
        high_p = ohlc.get("high", 0)
        low_p = ohlc.get("low", 0)
        ltp = data.get("last_price", 0)
        curr_vol = data.get("volume", 0)

        if open_p == 0:
            continue

        # Allow a tiny 0.05% tick tolerance for real-world market noise
        tolerance = open_p * 0.0005
        is_open_high = abs(open_p - high_p) <= tolerance
        is_open_low = abs(open_p - low_p) <= tolerance

        if not (is_open_high or is_open_low):
            continue

        atr, avg_vol = get_historical_stats(key)
        if not atr or not avg_vol:
            continue

        # Risk unit = 50% of Daily ATR for intraday targets
        risk_unit = atr * 0.5
        vol_ratio = round(curr_vol / avg_vol, 2) if avg_vol > 0 else 0

        # Power Badge Logic
        if vol_ratio >= 4.0:
            power = "🔥 Ultra"
        elif vol_ratio >= 2.0:
            power = "⚡ Strong"
        else:
            power = "Normal"

        # Pattern, Status & Target Calculation
        if is_open_high:
            pattern = f"Open=High ({open_p:.2f})"
            status = "Active" if ltp <= open_p else "Reversed"
            t1 = round(open_p - risk_unit, 1)
            t2 = round(open_p - (risk_unit * 2), 1)
            rev_tgt = round(open_p + risk_unit, 1) if status == "Reversed" else "N/A"
        else:
            pattern = f"Open=Low ({open_p:.2f})"
            status = "Active" if ltp >= open_p else "Reversed"
            t1 = round(open_p + risk_unit, 1)
            t2 = round(open_p + (risk_unit * 2), 1)
            rev_tgt = round(open_p - risk_unit, 1) if status == "Reversed" else "N/A"

        results.append({
            "Symbol": symbol,
            "Pattern": pattern,
            "Status": status,
            "Price (₹)": f"{ltp:.2f}",
            "Normal Tgt (1:1|1:2)": f"{t1} | {t2}",
            "Rev Target": rev_tgt,
            "Volume": f"{vol_ratio}x",
            "Power": power
        })

    df_out = pd.DataFrame(results)
    if df_out.empty:
        print("No Open=High or Open=Low setups found right now.")
    else:
        print(df_out.to_string(index=False))
        generate_html_dashboard(df_out)

def generate_html_dashboard(df):
    """Generates a dark-themed HTML table matching your screenshot for GitHub Pages."""
    html = f"""
    <html>
    <head>
        <meta http-equiv="refresh" content="60">
        <style>
            body {{ background-color: #1e1e24; color: #ffffff; font-family: Arial, sans-serif; padding: 20px; }}
            table {{ width: 100%; border-collapse: collapse; text-align: center; }}
            th {{ background-color: #6c727f; padding: 10px; font-size: 14px; }}
            td {{ background-color: #3a3d46; padding: 10px; border-bottom: 1px solid #4e525d; font-weight: bold; }}
            .bearish {{ color: #ff5252; }}
            .bullish {{ color: #4caf50; }}
            .active {{ color: #4caf50; }}
            .tgt {{ color: #00bcd4; }}
            .ultra {{ background-color: #9c27b0; color: white; }}
            .strong {{ background-color: #2196f3; color: white; }}
        </style>
    </head>
    <body>
        <h3>Intraday OHOL Scanner (Updated: {datetime.now().strftime('%H:%M:%S IST')})</h3>
        <table>
            <tr>{"".join(f"<th>{col}</th>" for col in df.columns)}</tr>
    """
    for _, row in df.iterrows():
        pat_class = "bearish" if "High" in row["Pattern"] else "bullish"
        pow_class = "ultra" if "Ultra" in row["Power"] else ("strong" if "Strong" in row["Power"] else "")
        html += f"""
            <tr>
                <td>{row['Symbol']}</td>
                <td class="{pat_class}">{row['Pattern']}</td>
                <td class="active">{row['Status']}</td>
                <td>{row['Price (₹)']}</td>
                <td class="tgt">{row['Normal Tgt (1:1|1:2)']}</td>
                <td>{row['Rev Target']}</td>
                <td>{row['Volume']}</td>
                <td class="{pow_class}">{row['Power']}</td>
            </tr>
        """
    html += "</table></body></html>"
    with open("index.html", "w") as f:
        f.write(html)

if __name__ == "__main__":
    scan_ohol()
