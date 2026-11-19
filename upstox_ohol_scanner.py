import streamlit as st
import requests
import pandas as pd
import gzip
import json
import time

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(page_title="Upstox Live OHL Multi-Strike Scanner", layout="wide")
st.title("📊 Upstox Live Open=Low / Open=High Option Scanner")

# ==========================================
# SIDEBAR CONTROLS
# ==========================================
st.sidebar.header("🔑 API & Scanner Settings")
ACCESS_TOKEN = st.sidebar.text_input("Upstox Access Token", type="password", help="Paste your daily Upstox API access token here")
STRIKE_RANGE = st.sidebar.slider("Strike Range (ATM +/- N)", min_value=1, max_value=10, value=5)
MIN_OPTION_VOLUME = st.sidebar.number_input("Minimum Option Volume", min_value=0, value=1000, step=500)

st.sidebar.divider()
st.sidebar.header("📁 Instrument File (Optional Fallback)")
UPLOADED_FILE = st.sidebar.file_uploader(
    "Upload Upstox NSE.csv / NSE.json.gz (Only if auto-fetch fails)",
    type=["csv", "json", "gz"]
)

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

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def send_telegram_message(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        return
    url = f"https://telegram.org{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        st.sidebar.error(f"Telegram Error: {e}")

def parse_instrument_df(df):
    """Normalizes Upstox CSV or JSON dataframe into F&O equities and nearest-expiry options."""
    # Handle CSV column naming differences if user uploads NSE.csv
    if 'exchange' in df.columns and 'segment' not in df.columns:
        df['segment'] = df['exchange']
    if 'tradingsymbol' in df.columns and 'trading_symbol' not in df.columns:
        df['trading_symbol'] = df['tradingsymbol']
    if 'strike' in df.columns and 'strike_price' not in df.columns:
        df['strike_price'] = df['strike']

    opts = df[(df['segment'] == 'NSE_FO') & (df['instrument_type'].isin(['CE', 'PE']))].copy()
    opts['strike_price'] = pd.to_numeric(opts['strike_price'], errors='coerce')
    nearest_expiry = opts['expiry'].min()
    opts = opts[opts['expiry'] == nearest_expiry]

    fno_symbols = opts['name'].dropna().unique()
    eqs = df[(df['segment'] == 'NSE_EQ') & (df['trading_symbol'].isin(fno_symbols))].copy()
    return eqs, opts

@st.cache_data(ttl=14400)
def download_upstox_instruments():
    """Downloads Upstox daily NSE CSV.gz master file (more reliable on cloud servers)."""
    url = "https://upstox.com"
    dl_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    res = requests.get(url, headers=dl_headers, timeout=30)
    res.raise_for_status()
    raw_bytes = res.content

    if raw_bytes[:2] == b'\x1f\x8b':
        csv_text = gzip.decompress(raw_bytes).decode("utf-8")
    else:
        csv_text = raw_bytes.decode("utf-8")

    from io import StringIO
    df = pd.read_csv(StringIO(csv_text))
    return parse_instrument_df(df)

def load_instruments(uploaded_file):
    if uploaded_file is not None:
        raw_bytes = uploaded_file.read()
        if raw_bytes[:2] == b'\x1f\x8b':
            text_data = gzip.decompress(raw_bytes).decode("utf-8")
        else:
            text_data = raw_bytes.decode("utf-8")

        if text_data.strip().startswith("["):
            df = pd.DataFrame(json.loads(text_data))
        else:
            from io import StringIO
            df = pd.read_csv(StringIO(text_data))
        return parse_instrument_df(df)
    return download_upstox_instruments()

def fetch_full_quotes_batch(instrument_keys, token):
    quote_map = {}
    url = "https://upstox.com"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token.strip()}"
    }

    for i in range(0, len(instrument_keys), 450):
        batch = instrument_keys[i:i+450]
        params = {"instrument_key": ",".join(batch)}
        res = requests.get(url, headers=headers, params=params, timeout=15).json()

        if res.get("status") == "success":
            for key, val in res["data"].items():
                norm_key = key.replace(":", "|")
                quote_map[norm_key] = {
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

    eq_keys = eqs['instrument_key'].tolist()
    eq_quotes = fetch_full_quotes_batch(eq_keys, token)

    if not eq_quotes:
        return pd.DataFrame()

    candidates = []
    option_keys_to_fetch = set()

    for _, row in eqs.iterrows():
        sym = row['trading_symbol']
        ekey = row['instrument_key']
        q_data = eq_quotes.get(ekey)

        if not q_data or not q_data['ohlc']:
            continue

        ohlc = q_data['ohlc']
        ltp = q_data['ltp']
        if ohlc.get('open', 0) == 0:
            continue

        is_eq_ol = (ohlc['open'] == ohlc['low']) and (ltp > ohlc['open'])
        is_eq_oh = (ohlc['open'] == ohlc['high']) and (ltp < ohlc['open'])

        if is_eq_ol or is_eq_oh:
            sym_opts = opts[opts['name'] == sym].copy()
            if sym_opts.empty:
                continue

            unique_strikes = sorted(sym_opts['strike_price'].dropna().unique())
            atm_strike = min(unique_strikes, key=lambda x: abs(x - ohlc['open']))
            atm_idx = unique_strikes.index(atm_strike)

            start_idx = max(0, atm_idx - strike_range)
            end_idx = min(len(unique_strikes), atm_idx + strike_range + 1)
            selected_strikes = unique_strikes[start_idx:end_idx]

            strike_pairs = []
            for strike in selected_strikes:
                ce_row = sym_opts[(sym_opts['strike_price'] == strike) & (sym_opts['instrument_type'] == 'CE')]
                pe_row = sym_opts[(sym_opts['strike_price'] == strike) & (sym_opts['instrument_type'] == 'PE')]

                if not ce_row.empty and not pe_row.empty:
                    ce_key = ce_row.iloc[0]['instrument_key']
                    pe_key = pe_row.iloc[0]['instrument_key']
                    step_diff = unique_strikes.index(strike) - atm_idx
                    moneyness = "ATM" if step_diff == 0 else f"ATM{step_diff:+d}"

                    strike_pairs.append({
                        "strike": strike,
                        "moneyness": moneyness,
                        "ce_key": ce_key,
                        "pe_key": pe_key
                    })
                    option_keys_to_fetch.update([ce_key, pe_key])

            if strike_pairs:
                candidates.append({
                    "symbol": sym,
                    "eq_ohlc": ohlc,
                    "eq_ltp": ltp,
                    "is_eq_ol": is_eq_ol,
                    "is_eq_oh": is_eq_oh,
                    "strike_pairs": strike_pairs
                })

    if not candidates:
        return pd.DataFrame()

    opt_quotes = fetch_full_quotes_batch(list(option_keys_to_fetch), token)

    results = []
    for item in candidates:
        for pair in item['strike_pairs']:
            ce_data = opt_quotes.get(pair['ce_key'])
            pe_data = opt_quotes.get(pair['pe_key'])

            if not ce_data or not pe_data:
                continue

            if ce_data['volume'] < min_vol or pe_data['volume'] < min_vol:
                continue

            ce_o = ce_data['ohlc']
            pe_o = pe_data['ohlc']
            if not ce_o or not pe_o or ce_o.get('open', 0) == 0 or pe_o.get('open', 0) == 0:
                continue

            ce_ol = (ce_o['open'] == ce_o['low']) and (ce_data['ltp'] > ce_o['open'])
            ce_oh = (ce_o['open'] == ce_o['high']) and (ce_data['ltp'] < ce_o['open'])
            pe_ol = (pe_o['open'] == pe_o['low']) and (pe_data['ltp'] > pe_o['open'])
            pe_oh = (pe_o['open'] == pe_o['high']) and (pe_data['ltp'] < pe_o['open'])

            signal = None
            priority = 99
            is_triple = False

            if item['is_eq_ol'] and ce_ol:
                if pe_oh:
                    signal = "🔥 HIGHLIGHT BULLISH (EQ O=L | CE O=L | PE O=H)"
                    priority = 1
                    is_triple = True
                else:
                    signal = "✅ BULLISH (EQ O=L | CE O=L)"
                    priority = 3

            elif item['is_eq_oh'] and pe_ol:
                if ce_oh:
                    signal = "🔥 HIGHLIGHT BEARISH (EQ O=H | PE O=L | CE O=H)"
                    priority = 2
                    is_triple = True
                else:
                    signal = "🔻 BEARISH (EQ O=H | PE O=L)"
                    priority = 4

            if signal:
                strike_label = f"{pair['strike']} ({pair['moneyness']})"
                results.append({
                    "Priority": priority,
                    "Signal": signal,
                    "Stock": item['symbol'],
