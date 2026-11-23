import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="NSE F&O OHL Ultimate Scanner Pro", layout="wide")

# ==========================================
# 1. SIDEBAR CONFIGURATION
# ==========================================
st.sidebar.header("🔑 Upstox Configuration")
access_token = st.sidebar.text_input("Daily Upstox Access Token", type="password").strip()
tolerance_pct = st.sidebar.number_input("OHL Tolerance (%)", min_value=0.0, max_value=1.0, value=0.0, step=0.05) / 100
pattern_filter = st.sidebar.multiselect("Filter Patterns", ["Open=Low", "Open=High"], default=["Open=Low", "Open=High"])
status_filter = st.sidebar.multiselect("Filter Status", ["Active", "Breached ❌"], default=["Active", "Breached ❌"])

BASE_URL = "https://upstox.com"

FNO_RAW = """
AARTIIND:INE769A01020 ABB:INE117A01022 ABBOTINDIA:INE358A01014 ABCAPITAL:INE674K01013
ABFRL:INE647O01011 ACC:INE012A01025 ADANIENSOL:INE931S01010 ADANIENT:INE423A01024
ADANIGREEN:INE364U01010 ADANIPORTS:INE742F01042 ALKEM:INE540L01014 AMBUJACEM:INE079A01024
ANGELONE:INE732I01013 APLAPOLLO:INE702C01027 APOLLOHOSP:INE437A01024 APOLLOTYRE:INE438A01022
ASHOKLEY:INE208A01029 ASIANPAINT:INE021A01026 ASTRAL:INE006I01046 ATUL:INE100A01010
AUBANK:INE949L01017 AUROPHARMA:INE406A01037 AXISBANK:INE238A01034 BAJAJ-AUTO:INE917I01010
BAJAJFINSV:INE918I01026 BAJFINANCE:INE296A01024 BALKRISIND:INE787D01026 BANDHANBNK:INE545U01014
BANKBARODA:INE028A01039 BANKINDIA:INE084A01016 BATAINDIA:INE176A01028 BEL:INE263A01024
BERGEPAINT:INE463A01038 BHARATFORG:INE465A01025 BHARTIARTL:INE397D01024 BHEL:INE257A01026
BIOCON:INE376G01013 BOSCHLTD:INE323A01026 BPCL:INE029A01011 BRITANNIA:INE216A01030
BSE:INE118H01025 BSOFT:INE836A01035 CAMS:INE596I01012 CANBK:INE476A01022
CANFINHOME:INE477A01020 CDSL:INE736A01011 CESC:INE486A01021 CGPOWER:INE067A01029
CHAMBLFERT:INE085A01013 CHOLAFIN:INE121A01024 CIPLA:INE059A01026 COALINDIA:INE522F01014
COFORGE:INE591G01017 COLPAL:INE259A01022 CONCOR:INE111A01025 COROMANDEL:INE169A01031
CROMPTON:INE299U01018 CUB:INE491A01021 CUMMINSIND:INE298A01020 CYIENT:INE136B01020
DABUR:INE016A01026 DALBHARAT:INE00R701025 DEEPAKNTR:INE288B01029 DELHIVERY:INE148O01028
DIVISLAB:INE361B01024 DIXON:INE935N01020 DLF:INE271C01023 DMART:INE192R01011
DRREDDY:INE089A01031 EICHERMOT:INE066A01021 ESCORTS:INE042A01014 EXIDEIND:INE302A01020
FEDERALBNK:INE171A01029 GAIL:INE129A01019 GLENMARK:INE935A01035 GMRAIRPORT:INE776C01039
GNFC:INE113A01013 GODREJCP:INE102D01028 GODREJPROP:INE484J01027 GRANULES:INE101D01020
GRASIM:INE047A01021 GUJGASLTD:INE844O01030 HAL:INE066F01020 HAVELLS:INE176B01034
HCLTECH:INE860A01027 HDFCAMC:INE127D01025 HDFCBANK:INE040A01034 HDFCLIFE:INE795G01014
HEROMOTOCO:INE158A01026 HFCL:INE548A01028 HINDALCO:INE038A01020 HINDCOPPER:INE531E01026
HINDPETRO:INE094A01015 HINDUNILVR:INE030A01027 HUDCO:INE031A01017 ICICIBANK:INE090A01021
ICICIGI:INE765G01017 ICICIPRULI:INE726G01019 IDEA:INE669E01016 IDFCFIRSTB:INE092T01019
IEX:INE022Q01020 IGL:INE203G01027 INDHOTEL:INE053A01029 INDIACEM:INE383A01012
INDIAMART:INE933S01016 INDIANB:INE562A01011 INDIGO:INE646L01027 INDUSINDBK:INE095A01012
INDUSTOWER:INE121J01017 INFY:INE009A01021 IOC:INE242A01010 IPCALAB:INE571A01038
IRB:INE821I01022 IRCTC:INE335Y01020 IRFC:INE053F01010 ITC:INE154A01025
JINDALSTEL:INE749A01030 JIOFIN:INE758E01017 JKCEMENT:INE823G01014 JSL:INE220G01021
JSWENERGY:INE121E01018 JSWSTEEL:INE019A01038 JUBLFOOD:INE797F01020 KALYANKJIL:INE303R01014
KEI:INE878B01027 KOTAKBANK:INE237A01028 KPITTECH:INE04I401011 LALPATHLAB:INE600L01024
LAURUSLABS:INE947Q01028 LICHSGFIN:INE115A01026 LICI:INE0J1Y01017 LODHA:INE670K01029
LT:INE018A01030 LTF:INE498L01015 LTIM:INE214T01019 LTTS:INE010V01017
LUPIN:INE326A01037 M&M:INE101A01026 M&MFIN:INE774D01024 MANAPPURAM:INE522D01027
MARICO:INE196A01026 MARUTI:INE585B01010 MAXHEALTH:INE027H01010 MCX:INE745G01035
METROPOLIS:INE112L01020 MFSL:INE180A01020 MGL:INE002S01010 MOTHERSON:INE775A01035
MPHASIS:INE356A01018 MRF:INE883A01011 MUTHOOTFIN:INE414G01012 NATIONALUM:INE139A01034
NAUKRI:INE663F01024 NAVINFLUOR:INE048G01026 NCC:INE868B01028 NESTLEIND:INE239A01024
NHPC:INE848E01016 NMDC:INE584A01023 NTPC:INE733E01010 NYKAA:INE388Y01029
OBEROIRLTY:INE093I01010 OFSS:INE881D01027 OIL:INE274J01014 ONGC:INE213A01029
PAGEIND:INE761H01022 PAYTM:INE982J01020 PEL:INE140A01024 PERSISTENT:INE262H01021
PETRONET:INE347G01014 PFC:INE134E01011 PIDILITIND:INE318A01026 PIIND:INE603J01030
PNB:INE160A01022 POLICYBZR:INE417T01026 POLYCAB:INE455K01017 POONAWALLA:INE511C01022
POWERGRID:INE752E01010 PRESTIGE:INE811K01011 PVRINOX:INE191H01014 RAMCOCEM:INE331A01037
RBLBANK:INE976G01028 RECLTD:INE020B01018 RELIANCE:INE002A01018 SAIL:INE114A01011
SBICARD:INE018E01016 SBILIFE:INE123W01016 SBIN:INE062A01020 SHREECEM:INE070A01015
SHRIRAMFIN:INE721A01047 SIEMENS:INE003A01024 SJVN:INE002L01015 SOLARINDS:INE343H01029
SONACOMS:INE073K01018 SRF:INE647A01010 SUNPHARMA:INE044A01036 SUNTV:INE424H01027
SUPREMEIND:INE195A01028 SYNGENE:INE398R01022 TATACHEM:INE092A01019 TATACOMM:INE151A01013
TATACONSUM:INE192A01025 TATAELXSI:INE670A01012 TATAMOTORS:INE155A01022 TATAPOWER:INE245A01021
TATASTEEL:INE081A01020 TCS:INE467B01029 TECHM:INE669C01036 TIINDIA:INE974X01010
TITAGARH:INE615H01020 TITAN:INE280A01028 TORNTPHARM:INE685A01028 TORNTPOWER:INE813H01021
TRENT:INE849A01020 TVSMOTOR:INE494B01023 UBL:INE686F01025 ULTRACEMCO:INE481G01011
UNIONBANK:INE692A01016 UNITDSPR:INE854D01024 UPL:INE628A01036 VBL:INE200M01039
VEDL:INE205A01025 VOLTAS:INE226A01021 WIPRO:INE075A01022 YESBANK:INE528G01035
ZOMATO:INE758T01015 ZYDUSLIFE:INE010B01027
"""

ALL_FNO_STOCKS = {}
for item in FNO_RAW.split():
    if ":" in item:
        sym, isin = item.split(":")
        ALL_FNO_STOCKS[f"NSE:{sym}"] = f"NSE_EQ|{isin}"

# ==========================================
# 2. FETCH CANDLES (LIVE OR LAST TRADING DAY)
# ==========================================
# ==========================================
# 2. FETCH CANDLES (V3 + V2 FALLBACK + DIAGNOSTICS)
# ==========================================
def scan_single_stock(symbol: str, inst_key: str, token: str, tol: float):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    encoded_key = inst_key.replace("|", "%7C")
    
    # Use IST date (UTC + 5:30) so server timezone never shifts the date
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    to_date = ist_now.strftime("%Y-%m-%d")
    from_date = (ist_now - timedelta(days=30)).strftime("%Y-%m-%d")

    candles = []
    session_mode = "Live Intraday"
    debug_err = ""

    # 1. Try V3 Intraday 15m
    try:
        r_intra = requests.get(f"{BASE_URL}/intraday/{encoded_key}/minutes/15", headers=headers, timeout=8)
        if r_intra.status_code == 401:
            return {"error": "401"}
        if r_intra.status_code == 200:
            candles = r_intra.json().get("data", {}).get("candles", [])
    except Exception as e:
        debug_err = str(e)

    # 2. Fetch V3 Historical 15m (with automatic V2 fallback)
    hist_candles = []
    try:
        r_hist = requests.get(f"{BASE_URL}/{encoded_key}/minutes/15/{to_date}/{from_date}", headers=headers, timeout=10)
        if r_hist.status_code == 401:
            return {"error": "401"}
        if r_hist.status_code == 200:
            hist_candles = r_hist.json().get("data", {}).get("candles", [])
        else:
            # Fallback to Upstox V2 Historical endpoint
            v2_url = f"https://upstox.com{encoded_key}/15minute/{to_date}/{from_date}"
            r_v2 = requests.get(v2_url, headers=headers, timeout=10)
            if r_v2.status_code == 200:
                hist_candles = r_v2.json().get("data", {}).get("candles", [])
            else:
                debug_err = f"HTTP {r_hist.status_code}: {r_hist.text[:120]}"
    except Exception as e:
        debug_err = str(e)

    # 3. If market closed/holiday (intraday empty), extract Last Trading Day from historical candles
    if not candles:
        if not hist_candles:
            return {"debug_err": debug_err} if debug_err else None
        session_mode = "Last Trading Day"
        latest_ts, *_ = next(iter(hist_candles))
        latest_date_str = str(latest_ts).split("T").pop(0)
        candles = [c for c in hist_candles if str(next(iter(c))).startswith(latest_date_str)]

    if not candles:
        return None

    # Sort chronologically (09:15 AM first, 03:15 PM last)
    candles = sorted(candles, key=lambda x: str(next(iter(x))))
    first_c = next(iter(candles))
    last_c = candles.pop()

    ts_first, o, h, l, _, v, _ = first_c
    _, _, _, _, c, _, _ = last_c
    o, h, l, v, c = float(o), float(h), float(l), float(v), float(c)
    session_date = str(ts_first).split("T").pop(0)

    is_ol = (abs(o - l) <= o * tol) and (h > o)
    is_oh = (abs(o - h) <= o * tol) and (l < o)

    if not (is_ol or is_oh):
        return {"session_mode": session_mode, "session_date": session_date, "matched": False}

    # 20-period average 15m volume
    past_vols = []
    for idx_v, item in enumerate(hist_candles):
        if 1 <= idx_v <= 20:
            _, _, _, _, _, item_v, _ = item
            past_vols.append(float(item_v))

    avg_vol = (sum(past_vols) / len(past_vols)) if past_vols else 0.0
    v_mult = (v / avg_vol) if avg_vol > 0 else 1.0
    power = "🔥 Ultra" if v_mult > 3.0 else ("⚡ Strong" if v_mult > 1.5 else "⚠️ Weak")

    candle_range = h - l
    status = "Active"
    rev_tgt = "N/A"

    if is_ol:
        pattern = "Open=Low"
        t1, t2 = o + candle_range, o + (2.0 * candle_range)
        sl = l
        if c < o:
            status = "Breached ❌"
            rev_tgt = f"{o - (2.0 * candle_range):.1f}"
            sl = h
    else:
        pattern = "Open=High"
        t1, t2 = o - candle_range, o - (2.0 * candle_range)
        sl = h
        if c > o:
            status = "Breached ❌"
            rev_tgt = f"{o + (2.0 * candle_range):.1f}"
            sl = l

    return {
        "session_mode": session_mode,
        "session_date": session_date,
        "matched": True,
        "row": {
            "Symbol": symbol,
            "Pattern": pattern,
            "Status": status,
            "Open": round(o, 2),
            "LTP / Close": round(c, 2),
            "Normal Tgt (1:1 | 1:2)": f"{t1:.1f} | {t2:.1f}",
            "Rev Target": rev_tgt,
            "Stop Loss": round(sl, 1),
            "Vol Mult": round(v_mult, 2),
            "Power": power
        }
    }

# ==========================================
# 3. MAIN DASHBOARD UI
# ==========================================
st.title("📊 NSE All F&O — OHL Ultimate Scanner Pro")

if not access_token:
    st.info("👈 Paste your daily Upstox Access Token in the left sidebar to scan all NSE F&O stocks.")
    st.stop()

col1, col2, col3 = st.columns(3)
with col1:
    st.button("🔄 Refresh Scan")
with col2:
    st.metric("F&O Stocks Scanned", len(ALL_FNO_STOCKS))
with col3:
    status_placeholder = st.empty()

progress = st.progress(0)
results = []
detected_mode = "Checking..."
detected_date = ""
unauthorized = False

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(scan_single_stock, sym, key, access_token, tolerance_pct): sym for sym, key in ALL_FNO_STOCKS.items()}
    completed = 0
    total = len(futures)
    for future in as_completed(futures):
        completed += 1
        progress.progress(completed / total)
        res = future.result()
        if res:
            if res.get("error") == "401":
                unauthorized = True
                break
            if res.get("debug_err"):
                last_api_error = res["debug_err"]
            if res.get("session_date"):
                detected_mode = res["session_mode"]
                detected_date = res["session_date"]
            if res.get("matched"):
                results.append(res["row"])


progress.empty()

if unauthorized:
    st.error("❌ Unauthorized (401): Your Upstox daily token is invalid or expired.")
    st.stop()

if detected_date:
    status_placeholder.info(f"📅 **Session:** {detected_mode} ({detected_date})")

if results:
    df = pd.DataFrame(results)
    df = df[df["Pattern"].isin(pattern_filter) & df["Status"].isin(status_filter)]
    df = df.sort_values(by="Vol Mult", ascending=False).reset_index(drop=True)
    df["Volume"] = df["Vol Mult"].apply(lambda x: f"{x:.2f}x")
    df = df.drop(columns=["Vol Mult"])
    st.dataframe(df, use_container_width=True, hide_index=True)

    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", data=csv_data, file_name=f"nse_fno_ohl_{detected_date}.csv", mime="text/csv")
else:
    st.warning("No F&O stocks matched Open=High or Open=Low for the last trading session.")
