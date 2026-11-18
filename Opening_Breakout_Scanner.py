import streamlit as st
import pandas as pd
import requests
import os
import json
import gzip
import time
import zipfile
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
st.set_page_config(page_title="Opening Breakout & Positional Scanner", layout="wide")

st.markdown(
    "<style>.block-container{padding-top:1rem !important;padding-bottom:1rem !important;} "
    "h1{font-size:1.8rem !important;margin-bottom:0.2rem !important;} "
    "h3{font-size:1.05rem !important;} "
    "div[data-testid='stDataFrame']{font-weight:600 !important;}</style>",
    unsafe_allow_html=True,
)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
TOKEN_FILE = os.path.join(DATA_DIR, "token.json")
NSE_JSON_PATH = "NSE.json"
NSE_GZ_PATH = "NSE.json.gz"
BSE_JSON_PATH = "BSE.json"
BSE_GZ_PATH = "BSE.json.gz"
FILES = {
    "Monthly": os.path.join(DATA_DIR, "monthly.csv"),
    "Weekly": os.path.join(DATA_DIR, "weekly.csv"),
    "Intraday": os.path.join(DATA_DIR, "intraday.csv"),
}

WEEKLY_INDICES = {"NIFTY", "SENSEX"}
MONTHLY_INDICES = {"BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
ALL_INDICES = WEEKLY_INDICES | MONTHLY_INDICES


def get_ist_now():
    return datetime.now(IST)


def load_saved_token():
    if "UPSTOX_ACCESS_TOKEN" in st.secrets and st.secrets["UPSTOX_ACCESS_TOKEN"].strip():
        return st.secrets["UPSTOX_ACCESS_TOKEN"].strip()
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == get_ist_now().strftime("%Y-%m-%d"):
                    return data.get("token", "").strip()
        except Exception:
            pass
    return ""


def extract_and_save_bhavcopy(uploaded_file, save_path):
    if uploaded_file is None:
        return pd.read_csv(save_path) if os.path.exists(save_path) else None
    if uploaded_file.name.lower().endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as z:
            csv_name = next(f for f in z.namelist() if f.lower().endswith(".csv"))
            with z.open(csv_name) as f:
                df = pd.read_csv(f)
    else:
        df = pd.read_csv(uploaded_file)
    df.to_csv(save_path, index=False)
    return df


def save_uploaded_instrument_files(uploaded_files):
    if not uploaded_files:
        return []
    saved_names = []
    for uploaded_file in uploaded_files:
        fname = uploaded_file.name.lower()
        if "bse" in fname:
            target = BSE_GZ_PATH if fname.endswith(".gz") else BSE_JSON_PATH
            other = BSE_JSON_PATH if fname.endswith(".gz") else BSE_GZ_PATH
        else:
            target = NSE_GZ_PATH if fname.endswith(".gz") else NSE_JSON_PATH
            other = NSE_JSON_PATH if fname.endswith(".gz") else NSE_GZ_PATH
        if os.path.exists(other):
            os.remove(other)
        with open(target, "wb") as f_out:
            f_out.write(uploaded_file.getbuffer())
        saved_names.append(uploaded_file.name)
    st.cache_data.clear()
    return saved_names


@st.cache_data
def load_nse_json_fast():
    rows = []
    sources = [
        (NSE_GZ_PATH, True, "NSE_FO"),
        (NSE_JSON_PATH, False, "NSE_FO"),
        (BSE_GZ_PATH, True, "BSE_FO"),
        (BSE_JSON_PATH, False, "BSE_FO"),
    ]
    loaded_segs = set()
    for path, is_gz, target_seg in sources:
        if target_seg in loaded_segs:
            continue
        if os.path.exists(path) and os.path.getsize(path) > 10000:
            try:
                if is_gz:
                    with gzip.open(path, "rt", encoding="utf-8") as f:
                        raw_list = json.load(f)
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        raw_list = json.load(f)
                for item in raw_list:
                    if item.get("segment") == target_seg and item.get("instrument_type") in ("CE", "PE"):
                        u_sym = str(
                            item.get("underlying_symbol")
                            or item.get("asset_symbol")
                            or item.get("name", "")
                        ).strip()
                        if target_seg == "BSE_FO" and u_sym != "SENSEX":
                            continue
                        rows.append(
                            {
                                "underlying_symbol": u_sym,
                                "strike_price": float(item["strike_price"]),
                                "instrument_type": item["instrument_type"],
                                "expiry": item["expiry"],
                                "instrument_key": item["instrument_key"],
                            }
                        )
                loaded_segs.add(target_seg)
            except Exception as e:
                st.error(f"Error reading {path}: {e}")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Convert epoch ms to IST before normalizing so expiry date never shifts by 1 day
    df["expiry_dt"] = (
        pd.to_datetime(df["expiry"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Kolkata")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    return df


def parse_bhavcopy_by_group(df_bhav, df_json, group_mode, is_intraday=False):
    if df_bhav is None or df_json.empty:
        return pd.DataFrame(), None
    df_bhav = df_bhav.copy()
    if "FinInstrmNm" in df_bhav.columns and "TckrSymb" not in df_bhav.columns:
        df_bhav = df_bhav.rename(columns={"FinInstrmNm": "TckrSymb"})
    df_bhav["TckrSymb"] = df_bhav["TckrSymb"].astype(str).str.strip()

    today = get_ist_now().replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

    futures = df_bhav[df_bhav["FinInstrmTp"].isin(["STF", "IDF"])].copy()
    futures["XpryDt"] = pd.to_datetime(futures["XpryDt"]).dt.normalize()
    futures = futures[futures["XpryDt"] >= today].sort_values("XpryDt")
    if futures.empty:
        return pd.DataFrame(), None

    near_fut = (
        futures.groupby("TckrSymb", as_index=False)
        .first()[["TckrSymb", "ClsPric", "XpryDt"]]
        .rename(columns={"ClsPric": "RefPrice", "XpryDt": "MonthlyExpiry"})
    )

    options = df_bhav[df_bhav["OptnTp"].isin(["CE", "PE"])].copy()
    options["XpryDt"] = pd.to_datetime(options["XpryDt"]).dt.normalize()
    # CRITICAL FIX: Exclude expired option contracts (e.g., 17-Nov-2026)
    options = options[options["XpryDt"] >= today]

    if group_mode == "WEEKLY_IDX":
        options = options[options["TckrSymb"].isin(WEEKLY_INDICES)]
        max_dist_pct = 0.025
    elif group_mode == "MONTHLY_IDX":
        options = options[options["TckrSymb"].isin(MONTHLY_INDICES)]
        max_dist_pct = 0.03
    else:
        options = options[~options["TckrSymb"].isin(ALL_INDICES)]
        max_dist_pct = 0.05

    merged = pd.merge(options, near_fut, on="TckrSymb")
    if merged.empty:
        return pd.DataFrame(), None

    if group_mode == "WEEKLY_IDX":
        # Picks nearest active expiry per index (23-Nov-2026 for NIFTY, 19-Nov-2026 for SENSEX)
        min_opt_exp = merged.groupby("TckrSymb")["XpryDt"].transform("min")
        merged = merged[merged["XpryDt"] == min_opt_exp]
    else:
        merged = merged[merged["XpryDt"] == merged["MonthlyExpiry"]]

    merged["DistPct"] = abs(merged["StrkPric"] - merged["RefPrice"]) / merged["RefPrice"]
    merged = merged[merged["DistPct"] <= max_dist_pct].copy()
    merged["StrkPric"] = merged["StrkPric"].astype(float)

    df_json = df_json.copy()
    df_json["strike_price"] = df_json["strike_price"].astype(float)

    result = pd.merge(
        merged,
        df_json,
        left_on=["TckrSymb", "StrkPric", "OptnTp", "XpryDt"],
        right_on=["underlying_symbol", "strike_price", "instrument_type", "expiry_dt"],
        how="inner",
    )
    if result.empty:
        return pd.DataFrame(), None

    result = result.drop_duplicates(subset=["instrument_key"]).copy()
    if is_intraday:
        result["Trigger"] = result["ClsPric"] + (result["HghPric"] - result["LwPric"]) * 1.1 / 2
    else:
        result["Trigger"] = result["ClsPric"] * 2

    exp_label = ", ".join(sorted(result["XpryDt"].dt.strftime("%d-%b-%Y").unique().tolist()))
    out = result[["TckrSymb", "StrkPric", "OptnTp", "Trigger", "instrument_key"]].rename(
        columns={"TckrSymb": "Symbol", "StrkPric": "StrikePrice"}
    )
    return out, exp_label


def fetch_ltp_v3(instrument_keys, token):
    if not token or not instrument_keys:
        return {}
    host = ".".join(["api", "upstox", "com"])
    url = f"https://{host}/v3/market-quote/ltp"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    ltp_map = {}
    batches = [instrument_keys[i : i + 50] for i in range(0, len(instrument_keys), 50)]
    for batch in batches:
        try:
            resp = requests.get(url, headers=headers, params={"instrument_key": ",".join(batch)}, timeout=15)
            body = resp.text.strip() if resp.text else ""
            if resp.status_code == 200 and body.startswith("{"):
                data = json.loads(body)
                if data.get("status") == "success":
                    for k, d in data.get("data", {}).items():
                        price = float(d.get("last_price") or 0.0)
                        if d.get("instrument_token"):
                            ltp_map[d["instrument_token"]] = price
                        ltp_map[k] = price
            time.sleep(0.12)
        except Exception:
            pass
    return ltp_map


def render_scanner_tables(df_tab, raw_loaded, exp_label, ltp_map, confluence_keys=None):
    if not raw_loaded:
        st.info("Upload the corresponding Bhavcopy file in the sidebar to view this timeframe.")
        return
    if df_tab.empty:
        st.warning("No matching active contracts found. Ensure today's NSE.json.gz / BSE.json.gz is uploaded.")
        return
    df_view = df_tab.copy()
