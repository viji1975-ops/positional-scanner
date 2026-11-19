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

with st.sidebar.form("scanner_settings_form"):
    st.header("🔑 API & Scanner Settings")
    ACCESS_TOKEN = st.text_input("Upstox Access Token", type="password")
    STRIKE_RANGE = st.slider("Strike Range (ATM +/- N)", 1, 10, 5)
    MIN_5M_VOLUME = st.number_input("Min 09:15 5-Min Option Volume", min_value=0, value=700, step=100)

    st.divider()
    st.header("📁 Instrument File (Optional Fallback)")
    UPLOADED_FILE = st.file_uploader("Upload NSE.csv / NSE.json.gz", type=["csv", "json", "gz"])

    st.divider()
    st.header("📲 Telegram Alerts (Optional)")
    ENABLE_TELEGRAM = st.checkbox("Enable Telegram Alerts", value=False)
    TG_BOT_TOKEN = st.text_input("Telegram Bot Token", type="password")
    TG_CHAT_ID = st.text_input("Telegram Chat ID")
    ONLY_HIGHLIGHT_ALERTS = st.checkbox("Alert Only on 🔥 Triple-Confirmation", value=True)

    st.divider()
    AUTO_REFRESH = st.checkbox("Auto-Refresh Every 60 Seconds", value=False)
    SUBMIT_BTN = st.form_submit_button("🚀 Apply & Run Scan", type="primary")

if "sent_alerts" not in st.session_state:
    st.session_state.sent_alerts = set()

def send_telegram_message(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        return
    p1 = "https://" + "api." + "telegram." + "org"
    p2 = "/bot" + bot_token + "/sendMessage"
    try:
        requests.post(p1 + p2, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
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

    if 'asset_symbol' in opts.columns and opts['asset_symbol'].notna().any():
        opts['under_sym'] = opts['asset_symbol']
    elif 'underlying_symbol' in opts.columns and opts['underlying_symbol'].notna().any():
        opts['under_sym'] = opts['underlying_symbol']
    else:
        opts['under_sym'] = opts['name']

    opts['min_exp'] = opts.groupby('under_sym')['expiry'].transform('min')
    opts = opts[opts['expiry'] == opts['min_exp']].copy()

    fno_symbols = opts['under_sym'].dropna().unique()
    eqs = df[(df['segment'] == 'NSE_EQ') & (df['trading_symbol'].isin(fno_symbols))].copy()
    return eqs, opts

@st.cache_data(ttl=14400)
def download_upstox_instruments(today_str):
    p1 = "https://" + "assets." + "upstox." + "com"
    p2 = "/market-quote/instruments/exchange/NSE.json.gz"
    res = requests.get(p1 + p2, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    res.raise_for_status()
    raw = res.content
    text = gzip.decompress(raw).decode("utf-8") if raw[:2] == b'\x1f\x8b' else raw.decode("utf-8")
    df = pd.DataFrame(json.loads(text)) if text.strip().startswith("[") else pd.read_csv(StringIO(text))
    return parse_instrument_df(df)

def load_instruments(uploaded_file, today_str):
    if uploaded_file is not None:
        uploaded_file.seek(0)
        raw = uploaded_file.read()
        text = gzip.decompress(raw).decode("utf-8") if raw[:2] == b'\x1f\x8b' else raw.decode("utf-8")
        df = pd.DataFrame(json.loads(text)) if text.strip().startswith("[") else pd.read_csv(StringIO(text))
        return parse_instrument_df(df)
    return download_upstox_instruments(today_str)


@st.cache_data(ttl=21600, show_spinner=False)
def cached_0915_5m_candle(instrument_key, token_stripped, today_str):
    """Fetches and caches today's 09:15-09:19 5-min candle with automatic HTTP 429 retry and daily reset."""
    encoded_key = quote(instrument_key, safe="")
    p1 = "https://" + "api." + "upstox." + "com"
    p2 = "/v2/historical-candle/intraday/" + encoded_key + "/1minute"
    url = p1 + p2
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token_stripped}

    for attempt in range(3):
        try:
            time.sleep(0.06)
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue
            if res.status_code != 200:
                return None, f"HTTP {res.status_code}: {res.text[:100]}"

            data = res.json()
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                return None, "Empty candles list"

            target_times = ("T09:15:", "T09:16:", "T09:17:", "T09:18:", "T09:19:")
            highs, lows, vols, timed_bars = [], [], [], []

            for c in candles:
                ts, o, h, l, cl, vol, *_ = c
                if any(t in str(ts) for t in target_times):
                    timed_bars.append((str(ts), float(o), float(cl)))
                    highs.append(float(h))
                    lows.append(float(l))
                    vols.append(int(vol))

            if not timed_bars:
                return None, "No 09:15-09:19 candles found"

            timed_bars.sort(key=lambda item: item)
            open_ts, open_915, _ = next(iter(timed_bars))
            _, _, close_919 = next(iter(reversed(timed_bars)))

            return {
                "time": open_ts,
                "open": open_915,
                "high": max(highs),
                "low": min(lows),
                "close": close_919,
                "volume": sum(vols)
            }, None
        except Exception as e:
            if attempt == 2:
                return None, str(e)
            time.sleep(1.0)
    return None, "HTTP 429 Rate Limit persisted after retries"

def fetch_0915_batch(instrument_keys, token, today_str, max_workers=4):
    """Fetches 09:15 AM 5-minute candles safely within Upstox rate limits."""
    candle_map = {}
    sample_error = None
    tok = token.strip()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(cached_0915_5m_candle, k, tok, today_str): k for k in instrument_keys}
        for fut in as_completed(futures):
            k = futures[fut]
            val, err = fut.result()
            if val is not None:
                candle_map[k] = val
            elif err and not sample_error:
                sample_error = err
    if sample_error:
        st.warning(f"API Notice: {sample_error}")
    return candle_map

def fetch_live_ltp_batch(instrument_keys, token):
    """Fetches live LTP for all matched instruments in 1 single batch API call."""
    if not instrument_keys:
        return {}
    ltp_map = {}
    p1 = "https://" + "api." + "upstox." + "com"
    p2 = "/v2/market-quote/ltp"
    url = p1 + p2
    headers = {"Accept": "application/json", "Authorization": "Bearer " + token.strip()}
    unique_keys = list(set(instrument_keys))
    for i in range(0, len(unique_keys), 450):
        batch = unique_keys[i:i+450]
        try:
            res = requests.get(url, headers=headers, params={"instrument_key": ",".join(batch)}, timeout=10).json()
            if res.get("status") == "success":
                for k, v in res["data"].items():
                    ltp_map[k.replace(":", "|")] = v.get("last_price", 0)
        except Exception:
            pass
    return ltp_map

def run_scanner(token, strike_range, min_vol, uploaded_file):
    today_ist = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m-%d")
    eqs, opts = load_instruments(uploaded_file, today_ist)

    eq_candles = fetch_0915_batch(eqs['instrument_key'].tolist(), token, today_ist)
    if not eq_candles:
        return pd.DataFrame(), len(eqs), 0, 0

    candidates, opt_keys = [], set()
    for _, row in eqs.iterrows():
        sym, ekey = row['trading_symbol'], row['instrument_key']
        c = eq_candles.get(ekey)
        if not c or c['open'] == 0:
            continue

        is_ol = (c['open'] == c['low']) and (c['close'] > c['open'])
        is_oh = (c['open'] == c['high']) and (c['close'] < c['open'])

        if is_ol or is_oh:
            s_opts = opts[opts['under_sym'] == sym]
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
                    ck = next(iter(ce['instrument_key']))
                    pk = next(iter(pe['instrument_key']))
                    diff = strikes.index(st_val) - idx
                    pairs.append({"strike": st_val, "m": "ATM" if diff == 0 else f"ATM{diff:+d}", "ck": ck, "pk": pk})
                    opt_keys.update([ck, pk])
            if pairs:
                candidates.append({"sym": sym, "ekey": ekey, "c": c, "ol": is_ol, "oh": is_oh, "pairs": pairs})

    if not candidates:
        return pd.DataFrame(), len(eqs), len(eq_candles), 0

    opt_candles = fetch_0915_batch(list(opt_keys), token, today_ist)

    matched_raw = []
    keys_for_ltp = []

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
                matched_raw.append((prio, sig, triple, item, p, eq_c, ce_c, pe_c))
                keys_for_ltp.extend([item['ekey'], p['ck'], p['pk']])

    ltp_map = fetch_live_ltp_batch(keys_for_ltp, token)

    results = []
    for prio, sig, triple, item, p, eq_c, ce_c, pe_c in matched_raw:
        s_lbl = f"{p['strike']} ({p['m']})"
        eq_ltp = ltp_map.get(item['ekey'], eq_c['close'])
        ce_ltp = ltp_map.get(p['ck'], ce_c['close'])
        pe_ltp = ltp_map.get(p['pk'], pe_c['close'])

        results.append(dict(
            Priority=prio, Signal=sig, Stock=item['sym'], Strike=s_lbl,
            EQ_5m_Open=eq_c['open'], EQ_5m_Close=eq_c['close'], EQ_Live_LTP=eq_ltp,
            CE_5m_Open=ce_c['open'], CE_5m_Close=ce_c['close'], CE_Live_LTP=ce_ltp, CE_5m_Vol=ce_c['volume'],
            PE_5m_Open=pe_c['open'], PE_5m_Close=pe_c['close'], PE_Live_LTP=pe_ltp, PE_5m_Vol=pe_c['volume']
        ))

        if ENABLE_TELEGRAM and (not ONLY_HIGHLIGHT_ALERTS or triple):
            aid = f"{today_ist}_{item['sym']}_{p['strike']}_{sig}"
            if aid not in st.session_state.sent_alerts:
                msg = (
                    f"<b>{sig} (09:15 5m Candle)</b>\n"
                    f"📌 <b>{item['sym']}</b> | 🎯 <b>{s_lbl}</b>\n"
                    f"📈 CE 5m: {ce_c['open']} -> {ce_c['close']} (LTP: {ce_ltp})\n"
                    f"📉 PE 5m: {pe_c['open']} -> {pe_c['close']} (LTP: {pe_ltp})"
                )
                send_telegram_message(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                st.session_state.sent_alerts.add(aid)

    if not results:
        return pd.DataFrame(), len(eqs), len(eq_candles), len(candidates)
    df_out = pd.DataFrame(results).sort_values(by=["Priority", "Stock", "Strike"]).drop(columns=["Priority"])
    return df_out, len(eqs), len(eq_candles), len(candidates)

def highlight_rows(row):
    if "HIGHLIGHT BULLISH" in row["Signal"]:
        return ["background-color: #1b4332; color: white; font-weight: bold"] * len(row)
    if "HIGHLIGHT BEARISH" in row["Signal"]:
        return ["background-color: #590d22; color: white; font-weight: bold"] * len(row)
    return [""] * len(row)

if not ACCESS_TOKEN:
    st.info("👈 Paste your **Upstox Access Token** in the left sidebar and click **🚀 Apply & Run Scan**.")
else:
    c1, c2 = st.columns(2)
    with c1:
        st.button("🔄 Refresh Live LTP & Scan", type="primary")
    with c2:
        if st.button("🗑️ Clear Alert History"):
            st.session_state.sent_alerts.clear()
            st.toast("Alert history cleared!")

    try:
        df_res, total_fno, fetched_cnt, eq_match_count = run_scanner(ACCESS_TOKEN, STRIKE_RANGE, MIN_5M_VOLUME, UPLOADED_FILE)
        st.caption(
            f"Last scanned: {pd.Timestamp.now(tz='Asia/Kolkata').strftime('%I:%M:%S %p IST')} | "
            f"F&O Stocks Loaded: **{total_fno}** | Candles Fetched: **{fetched_cnt}** | "
            f"Matching 09:15 5m O=L/O=H: **{eq_match_count}**"
        )
        if not df_res.empty:
            st.dataframe(df_res.style.apply(highlight_rows, axis=1), use_container_width=True, hide_index=True)
        else:
            st.warning("No matching 09:15 AM 5-min OHL setups found.")
    except Exception as e:
        st.error(f"Scanner Error: {e}")

    if AUTO_REFRESH:
        time.sleep(60)
        st.rerun()

