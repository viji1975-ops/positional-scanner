import streamlit as st
import requests
import pandas as pd
import gzip
import json
import time
from io import StringIO

st.set_page_config(page_title="Upstox Live OHL Multi-Strike Scanner", layout="wide")
st.title("📊 Upstox Live Open=Low / Open=High Option Scanner")

st.sidebar.header("🔑 API & Scanner Settings")
ACCESS_TOKEN = st.sidebar.text_input("Upstox Access Token", type="password")
STRIKE_RANGE = st.sidebar.slider("Strike Range (ATM +/- N)", 1, 10, 5)
MIN_OPTION_VOLUME = st.sidebar.number_input("Minimum Option Volume", 0, value=1000, step=500)

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


def fetch_full_quotes_batch(instrument_keys, token):
    quote_map = {}
    url = "https://upstox.com"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}
    for i in range(0, len(instrument_keys), 450):
        batch = instrument_keys[i:i+450]
        res = requests.get(url, headers=headers, params={"instrument_key": ",".join(batch)}, timeout=15).json()
        if res.get("status") == "success":
            for key, val in res["data"].items():
                quote_map[key.replace(":", "|")] = {
                    "ohlc": val.get("ohlc", {}),
                    "ltp": val.get("last_price", 0),
                    "volume": val.get("volume", 0)
                }
        else:
            st.error(f"Upstox API Error: {res}")
            break
    return quote_map

def run_scanner(token, strike_range, min_vol, uploaded_file):
    eqs, opts = load_instruments(uploaded_file)
    eq_quotes = fetch_full_quotes_batch(eqs['instrument_key'].tolist(), token)
    if not eq_quotes:
        return pd.DataFrame()

    candidates, opt_keys = [], set()
    for _, row in eqs.iterrows():
        sym, ekey = row['trading_symbol'], row['instrument_key']
        q = eq_quotes.get(ekey)
        if not q or not q['ohlc'] or q['ohlc'].get('open', 0) == 0:
            continue
        ohlc, ltp = q['ohlc'], q['ltp']
        is_ol = (ohlc['open'] == ohlc['low']) and (ltp > ohlc['open'])
        is_oh = (ohlc['open'] == ohlc['high']) and (ltp < ohlc['open'])

        if is_ol or is_oh:
            s_opts = opts[opts['name'] == sym]
            if s_opts.empty:
                continue
            strikes = sorted(s_opts['strike_price'].dropna().unique())
            atm = min(strikes, key=lambda x: abs(x - ohlc['open']))
            idx = strikes.index(atm)
            sel = strikes[max(0, idx - strike_range):min(len(strikes), idx + strike_range + 1)]

            pairs = []
            for st_val in sel:
                ce = s_opts[(s_opts['strike_price'] == st_val) & (s_opts['instrument_type'] == 'CE')]
                pe = s_opts[(s_opts['strike_price'] == st_val) & (s_opts['instrument_type'] == 'PE')]
                if not ce.empty and not pe.empty:
                    ck, pk = ce['instrument_key'].values, pe['instrument_key'].values 
                    diff = strikes.index(st_val) - idx
                    pairs.append({"strike": st_val, "m": "ATM" if diff == 0 else f"ATM{diff:+d}", "ck": ck, "pk": pk})
                    opt_keys.update([ck, pk])
            if pairs:
                candidates.append({"sym": sym, "ohlc": ohlc, "ltp": ltp, "ol": is_ol, "oh": is_oh, "pairs": pairs})

    if not candidates:
        return pd.DataFrame()

    opt_quotes = fetch_full_quotes_batch(list(opt_keys), token)
    results = []
    for item in candidates:
        for p in item['pairs']:
            cd, pd_val = opt_quotes.get(p['ck']), opt_quotes.get(p['pk'])
            if not cd or not pd_val or cd['volume'] < min_vol or pd_val['volume'] < min_vol:
                continue
            co, po = cd['ohlc'], pd_val['ohlc']
            if not co or not po or co.get('open', 0) == 0 or po.get('open', 0) == 0:
                continue

            ce_ol = (co['open'] == co['low']) and (cd['ltp'] > co['open'])
            ce_oh = (co['open'] == co['high']) and (cd['ltp'] < co['open'])
            pe_ol = (po['open'] == po['low']) and (pd_val['ltp'] > po['open'])
            pe_oh = (po['open'] == po['high']) and (pd_val['ltp'] < po['open'])

            sig, prio, triple = None, 99, False
            if item['ol'] and ce_ol:
                sig = "🔥 HIGHLIGHT BULLISH (EQ O=L | CE O=L | PE O=H)" if pe_oh else "✅ BULLISH (EQ O=L | CE O=L)"
                prio, triple = (1, True) if pe_oh else (3, False)
            elif item['oh'] and pe_ol:
                sig = "🔥 HIGHLIGHT BEARISH (EQ O=H | PE O=L | CE O=H)" if ce_oh else "🔻 BEARISH (EQ O=H | PE O=L)"
                prio, triple = (2, True) if ce_oh else (4, False)

            if sig:
                s_lbl = f"{p['strike']} ({p['m']})"
                row_dict = dict(
                    Priority=prio, Signal=sig, Stock=item['sym'], Strike=s_lbl,
                    EQ_Open=item['ohlc']['open'], EQ_LTP=item['ltp'],
                    CE_Open=co['open'], CE_LTP=cd['ltp'], CE_Vol=cd['volume'],
                    PE_Open=po['open'], PE_LTP=pd_val['ltp'], PE_Vol=pd_val['volume']
                )
                results.append(row_dict)

                if ENABLE_TELEGRAM and (not ONLY_HIGHLIGHT_ALERTS or triple):
                    aid = f"{item['sym']}_{p['strike']}_{sig}"
                    if aid not in st.session_state.sent_alerts:
                        msg = f"<b>{sig}</b>\n📌 <b>{item['sym']}</b> | 🎯 <b>{s_lbl}</b>\n📈 CE: {co['open']} -> {cd['ltp']}\n📉 PE: {po['open']} -> {pd_val['ltp']}"
                        send_telegram_message(TG_BOT_TOKEN, TG_CHAT_ID, msg)
                        st.session_state.sent_alerts.add(aid)

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values(by=["Priority", "Stock", "Strike"]).drop(columns=["Priority"])

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

    with st.spinner("Scanning F&O stocks and ATM ±5 option strikes..."):
        try:
            df_res = run_scanner(ACCESS_TOKEN, STRIKE_RANGE, MIN_OPTION_VOLUME, UPLOADED_FILE)
            st.caption(f"Last scanned: {pd.Timestamp.now(tz='Asia/Kolkata').strftime('%I:%M:%S %p IST')}")
            if not df_res.empty:
                st.dataframe(df_res.style.apply(highlight_rows, axis=1), use_container_width=True, hide_index=True)
            else:
                st.warning("No matching OHL setups right now. Try lowering Minimum Option Volume to 0.")
        except Exception as e:
            st.error(f"Scanner Error: {e}")

    if AUTO_REFRESH:
        time.sleep(60)
        st.rerun()
