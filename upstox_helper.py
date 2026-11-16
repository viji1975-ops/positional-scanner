import requests
import pandas as pd

def get_upstox_instruments():
    """Downloads and combines NSE_FO and BSE_FO instrument masters for Upstox API."""
    nse_url = "https://upstox.com"
    bse_url = "https://upstox.com"
    
    nse_df = pd.read_json(nse_url, compression="gzip")
    bse_df = pd.read_json(bse_url, compression="gzip")
    
    nse_fo = nse_df[nse_df["segment"] == "NSE_FO"]
    bse_fo = bse_df[(bse_df["segment"] == "BSE_FO") & (bse_df["name"] == "SENSEX")]
    
    combined = pd.concat([nse_fo, bse_fo], ignore_index=True)
    # Build matching composite key: Symbol_Expiry_Strike_OptionType
    combined["expiry_dt"] = pd.to_datetime(combined["expiry"], unit="ms").dt.strftime("%Y-%m-%d")
    combined["key"] = (
        combined["name"].str.strip() + "_" +
        combined["expiry_dt"] + "_" +
        combined["strike_price"].astype(float).astype(str) + "_" +
        combined["instrument_type"].str.strip()
    )
    return combined[["key", "instrument_key"]]


def fetch_upstox_full_quotes(access_token: str, instrument_keys: list) -> pd.DataFrame:
    """
    Uses Upstox Full Market Quote v2 endpoint to fetch LTP, Volume, OI, and Depth (Bid/Ask).
    Batches requests in chunks of 500 instruments.
    """
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    url = "https://upstox.com"
    records = []

    for i in range(0, len(instrument_keys), 500):
        batch = ",".join(instrument_keys[i:i+500])
        resp = requests.get(url, headers=headers, params={"instrument_key": batch}).json()
        
        if resp.get("status") == "success":
            for inst_key, data in resp["data"].items():
                depth = data.get("depth", {})
                best_bid = depth.get("buy", [{}])[0].get("price", 0)
                best_ask = depth.get("sell", [{}])[0].get("price", 0)
                records.append({
                    "instrument_key": inst_key,
                    "ltp": data.get("last_price", 0),
                    "volume": data.get("volume", 0),
                    "live_oi": data.get("oi", 0),
                    "bid": best_bid,
                    "ask": best_ask
                })
    return pd.DataFrame(records)
