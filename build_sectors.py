import pandas as pd
import requests
import io

headers = {"User-Agent": "Mozilla/5.0"}
all_records = []

# 1. Primary Source: Nifty 500 (Covers Large, Mid, and Smallcap stocks with official Industry tags)
nifty500_url = "https://niftyindices.com"
try:
    res = requests.get(nifty500_url, headers=headers, timeout=15)
    df_500 = pd.read_csv(io.StringIO(res.text))
    df_500.columns = df_500.columns.str.strip()
    if 'Symbol' in df_500.columns and 'Industry' in df_500.columns:
        for _, row in df_500.dropna(subset=['Symbol', 'Industry']).iterrows():
            all_records.append({
                "TckrSymb": str(row['Symbol']).strip(),
                "Sector": str(row['Industry']).strip()
            })
        print(f"Loaded {len(all_records)} stocks from Nifty 500.")
except Exception as e:
    print(f"Nifty 500 fetch warning: {e}")

# 2. Supplement with Thematic / Sectoral Indices for any remaining symbols
sector_urls = {
    "Information Technology": "https://niftyindices.com",
    "Financial Services": "https://niftyindices.com",
    "Healthcare": "https://niftyindices.com",
    "Automobile and Auto Components": "https://niftyindices.com",
    "Fast Moving Consumer Goods": "https://niftyindices.com",
    "Metals & Mining": "https://niftyindices.com",
    "Oil Gas & Consumable Fuels": "https://niftyindices.com",
    "Realty": "https://niftyindices.com",
    "Media Entertainment & Publication": "https://niftyindices.com"
}

for sector, url in sector_urls.items():
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(res.text))
        df.columns = df.columns.str.strip()
        for sym in df['Symbol'].dropna():
            all_records.append({"TckrSymb": str(sym).strip(), "Sector": sector})
    except Exception:
        pass

mapping_df = pd.DataFrame(all_records).drop_duplicates(subset=['TckrSymb'], keep='first')
mapping_df.to_csv("sector_mapping.csv", index=False)
print(f"Successfully generated sector_mapping.csv with {len(mapping_df)} unique stocks!")
