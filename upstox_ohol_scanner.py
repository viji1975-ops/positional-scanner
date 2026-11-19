import streamlit as st
import requests
import pandas as pd
import gzip
import json
import time
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

st.set_page_config(page_title="Upstox 09:15 AM 5-Min OHL Scanner", layout="wide")
st.title("📊 Upstox 09:15 AM (First 5-Min Candle) OHL Option Scanner")

st.sidebar.header("🔑 API & Scanner Settings")
ACCESS_TOKEN = st.sidebar.text_input("Upstox Access Token", type="password")
STRIKE_RANGE = st.sidebar.slider("Strike Range (ATM +/- N)", 1, 10, 5)
MIN_5M_VOLUME = st.sidebar.number_input("Min 09:15 5-Min Option Volume", min_value=0, value=500, step=100)

st.sidebar.divider()
st.sidebar.header("📁 Instrument File (Optional Fallback)")
UPLOADED_FILE = st.sidebar.file_uploader("Upload NSE.csv / NSE.json.gz", type=["csv", "json", "gz"])

st.sidebar.divider()
st.sidebar.header("📲 Telegram Alerts (Optional)")
ENABLE_TELEGRAM = st.sidebar.checkbox("Enable Telegram Alerts", value=False)
TG_BOT_TOKEN = st.sidebar.text_input("Telegram Bot Token", type="password")
TG_CHAT_ID = st.sidebar.text_input("Telegram Chat ID")
ONLY_HIGHLIGHT_ALERTS = st.sidebar.checkbox("Alert Only on 🔥 Triple-Confirmation", value=True)

st.sidebar.divider()
AUTO_REFRESH = st.sidebar.checkbox("Auto-Refresh Every 60 Seconds", value=False)

if "sent_alerts" not in st.session_state:
    st.session_state.sent_alerts = set()

def send_telegram_message(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        return
    url = f"https://telegram.org{bot_token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        st.sidebar.error(f"Telegram Error: {e}")

def parse_instrument_df(df):
    if 'exchange' in df.columns and 'segment' not in df.columns:
        df['segment'] = df['exchange']
    if 'tradingsymbol' in df.columns and 'trading_symbol' not in df.columns:
        df['trading_symbol'] = df['tradingsymbol']
    if 'strike' in df.columns and 'strike_price' not in df.columns:
        df['strike_price'] = df['strike']

    opts = df[(df['segment'] == 'NSE_FO') & (df['instrument_type'].isin(['CE', 'PE']))].copy()
    opts['strike_price'] = pd.to_numeric(opts['strike_price'], errors='coerce')
    opts = opts[opts['expiry'] == opts['expiry'].min()]
    fno_symbols = opts['name'].dropna().unique()
    eqs = df[(df['segment'] == 'NSE_EQ') & (df['trading_symbol'].isin(fno_symbols))].copy()
    return eqs, opts

@st.cache_data(ttl=14400)
def download_upstox_instruments():
    url = "https://upstox.com"
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    res.raise_for_status()
    raw = res.content
    text = gzip.decompress(raw).decode("utf-8") if raw[:2] == b'\x1f\x8b' else raw.decode("utf-8")
    return parse_instrument_df(pd.read_csv(StringIO(text)))

def load_instruments(uploaded_file):
    if uploaded_file is not None:
        raw = uploaded_file.read()
        text = gzip.decompress(raw).decode("utf-8") if raw[:2] == b'\x1f\x8b' else raw.decode("utf-8")
        df = pd.DataFrame(json.loads(text)) if text.strip().startswith("[") else pd.read_csv(StringIO(text))
        return parse_instrument_df(df)
    return download_upstox_instruments()


def fetch_0915_5m_candle(instrument_key, token):
    """Fetches the 09:15 AM 5-minute candle using Upstox V3 Intraday API."""
    encoded_key = quote(instrument_key, safe="")
    url = f"https://upstox.com{encoded_key}/minutes/5"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return instrument_key, None
        data = res.json()
        candles = data.get("data", {}).get("candles", [])
        if not candles:
            return instrument_key, None

        # Candles are sorted newest-first; the 09:15 AM candle is the last element or contains '09:15'
        first_candle = None
        for c in reversed(candles):
            if "09:15" in str(c):
                first_candle = c
                break
        if first_candle is None:
            first_candle = candles[-1]

        latest_ltp = candles

        return instrument_key, {
            "time": str(first_candle),
            "open": float(first_candle),
            "high": float(first_candle),
            "low": float(first_candle),
            "close": float(first_candle),
            "volume": int(first_candle),
            "ltp": float(latest_ltp)
        }
    except Exception:
        return instrument_key, None

def fetch_0915_batch(instrument_keys, token, max_workers=10):
    """Fetches 09:15 AM 5-minute candles in parallel across multiple threads."""
    candle_map = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_0915_5m_candle, k, token) for k in instrument_keys]
        for fut in as_completed(futures):
            k, val = fut.result()
            if val is not None:
                candle_map[k] = val
    return candle_map

def run_scanner(token, strike_range, min_vol, uploaded_file):
    eqs, opts = load_instruments(uploaded_file)

    # Step 1: Fetch 09:15 AM 5-minute candle for all F&O equities
    eq_candles = fetch_0915_batch(eqs['instrument_key'].tolist(), token)
    if not eq_candles:
        st.error("Could not fetch 5-min candles from Upstox V3 API. Check if Access Token is valid.")
        return pd.DataFrame(), 0

    candidates, opt_keys = [], set()
    for _, row in eqs.iterrows():
        sym, ekey = row['trading_symbol'], row['instrument_key']
        c = eq_candles.get(ekey)
        if not c or c['open'] == 0:
            continue

        # Check 09:15 AM 5-min candle Open == Low (bullish) or Open == High (bearish)
        is_ol = (c['open'] == c['low']) and (c['close'] > c['open'])
        is_oh = (c['open'] == c['high']) and (c['close'] < c['open'])

        if is_ol or is_oh:
            s_opts = opts[opts['name'] == sym]
            if s_opts.empty:
                continue
            strikes = sorted(s_opts['strike_price'].dropna().unique())
            atm = min(strikes, key=lambda x: abs(x - c['open']))
            idx = strikes.index(atm)
            sel = strikes[max(0, idx - strike_range):min(len(strikes), idx + strike_range + 1)]

            pairs = []
            for st_val in sel:
                ce = s_opts[(s_opts['strike_price'] == st_val) & (s_opts['instrument_type'] == 'CE')]
                pe = s_opts[(s_opts['strike_price'] == st_val) & (s_opts['instrument_type'] == 'PE')]
                if not ce.empty and not pe.empty:
                    ck = ce['instrument_key'].tolist()
                    pk = pe['instrument_key'].tolist()
                    diff = strikes.index(st_val) - idx
                    pairs.append({"strike": st_val, "m": "ATM" if diff == 0 else f"ATM{diff:+d}", "ck": ck, "pk": pk})
                    opt_keys.update([ck, pk])
            if pairs:
                candidates.append({"sym": sym, "c": c, "ol": is_ol, "oh": is_oh, "pairs": pairs})

    if not candidates:
        return pd.DataFrame(), 0

    # Step 2: Fetch 09:15 AM 5-minute candle for matched option strikes
    opt_candles = fetch_0915_batch(list(opt_keys), token)
    results = []
    for item in candidates:
        eq_c = item['c']
        for p in item['pairs']:
            ce_c, pe_c = opt_candles.get(p['ck']), opt_candles.get(p['pk'])
            if not ce_c or not pe_c:
                continue
            if ce_c['volume'] < min_vol or pe_c['volume'] < min_vol:
                continue
            if ce_c['open'] == 0 or pe_c['open'] == 0:
                continue

            # Check 09:15 AM 5-min candle conditions on CE and PE
            ce_ol = (ce_c['open'] == ce_c['low']) and (ce_c['close'] > ce_c['open'])
            ce_oh = (ce_c['open'] == ce_c['high']) and (ce_c['close'] < ce_c['open'])
            pe_ol = (pe_c['open'] == pe_c['low']) and (pe_c['close'] > pe_c['open'])
            pe_oh = (pe_c['open'] == pe_c['high']) and (pe_c['close'] < pe_c['open'])

            sig, prio, triple = None, 99, False
            if item['ol'] and ce_ol:
                sig = "🔥 HIGHLIGHT BULLISH (EQ O=L | CE O=L | PE O=H)" if pe_oh else "✅ BULLISH (EQ O=L | CE O=L)"
                prio, triple = (1, True) if pe_oh else (3, False)
            elif item['oh'] and pe_ol:
                sig = "🔥 HIGHLIGHT BEARISH (EQ O=H | PE O=L | CE O=H)" if ce_oh else "🔻 BEARISH (EQ O=H | PE O=L)"
                prio, triple = (2, True) if ce_oh else (4, False)

            if sig:
                s_lbl = f"{p['strike']} ({p['m']})"
                results.append(dict(
                    Priority=prio, Signal=sig, Stock=item['sym'], Strike=s_lbl,
                    EQ_5m_Open=eq_c['open'], EQ_5m_Close=eq_c['close'], EQ_Live_LTP=eq_c['ltp'],
                    CE_5m_Open=ce_c['open'], CE_5m_Close=ce_c['close'], CE_Live_LTP=ce_c['ltp'], CE_5m_Vol=ce_c['volume'],
                    PE_5m_Open=pe_c['open'], PE_5m_Close=pe_c['close'], PE_Live_LTP=pe_c['ltp'], PE_5m_Vol=pe_c['volume']
                ))

                if ENABLE_TELEGRAM and (not ONLY_HIGHLIGHT_ALERTS or triple):
                    aid = f"{item['sym']}_{p['strike']}_{sig}"
                    if aid not in st.session_state.sent_alerts:
                        msg = (
                            f"<b>{sig} (09:15 5m Candle)</b>\n"
                            f"📌 <b>{item['sym']}</b> | 🎯 <b>{s_lbl}</b>\n"
                            f"📈 CE 5m: {ce_c['open']} -> {ce_c['close']} (LTP: {ce_c['ltp']})\n"
                            f"📉 PE 5m: {pe_c['open']} -> {pe_c['close']} (LTP: {pe_c['ltp']})"
                        )
                        send_telegram_message(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                        st.session_state.sent_alerts.add(aid)

    if not results:
        return pd.DataFrame(), len(candidates)
    df_out = pd.DataFrame(results).sort_values(by=["Priority", "Stock", "Strike"]).drop(columns=["Priority"])
    return df_out, len(candidates)

def highlight_rows(row):
    if "HIGHLIGHT BULLISH" in row["Signal"]:
        return ["background-color: #1b4332; color: white; font-weight: bold"] * len(row)
    if "HIGHLIGHT BEARISH" in row["Signal"]:
        return ["background-color: #590d22; color: white; font-weight: bold"] * len(row)
    return [""] * len(row)

if not ACCESS_TOKEN:
    st.info("👈 Paste your **Upstox Access Token** in the left sidebar and press **Enter**.")
else:
    c1, c2 = st.columns(2)
    with c1:
        st.button("🔄 Refresh Scan", type="primary")
    with c2:
        if st.button("🗑️ Clear Alert History"):
            st.session_state.sent_alerts.clear()
            st.toast("Alert history cleared!")

    with st.spinner("Checking 09:15 AM 5-minute candles across F&O stocks and ATM ±5 strikes..."):
        try:
            df_res, eq_match_count = run_scanner(ACCESS_TOKEN, STRIKE_RANGE, MIN_5M_VOLUME, UPLOADED_FILE)
            st.caption(
                f"Last scanned: {pd.Timestamp.now(tz='Asia/Kolkata').strftime('%I:%M:%S %p IST')} | "
                f"F&O Stocks matching 09:15 5m O=L/O=H: **{eq_match_count}**"
            )
            if not df_res.empty:
                st.dataframe(df_res.style.apply(highlight_rows, axis=1), use_container_width=True, hide_index=True)
            else:
                st.warning("No matching 09:15 AM 5-min OHL setups found. Try lowering Min 09:15 5-Min Option Volume to 0.")
        except Exception as e:
            st.error(f"Scanner Error: {e}")

    if AUTO_REFRESH:
        time.sleep(60)
        st.rerun()


    if AUTO_REFRESH:
        time.sleep(60)
        st.rerun()
