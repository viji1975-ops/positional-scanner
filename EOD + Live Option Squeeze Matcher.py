import streamlit as st
import pandas as pd
import requests, gzip, json, io
from datetime import datetime

st.set_page_config(page_title="EOD + Live Option Squeeze Matcher", layout="wide")
st.title("📊 EOD + Live Market Option Squeeze Matcher")

@st.cache_data(ttl=86400)
def load_upstox_master():
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip, deflate"}
    # Try Upstox official NSE CSV.gz master (reliable and fast)
    url = "https://upstox.com"
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    raw_bytes = gzip.decompress(resp.content) if resp.content[:2] == b'\x1f\x8b' else resp.content
    mdf = pd.read_csv(io.BytesIO(raw_bytes))

    eq_map, exp_map = {}, {}
    # Map Equity & Index instrument keys
    eq_rows = mdf[(mdf['exchange'] == 'NSE_EQ') & (mdf['instrument_type'] == 'EQUITY')]
    for _, r in eq_rows.iterrows():
        eq_map[str(r['tradingsymbol']).upper().strip()] = str(r['instrument_key']).strip()

    idx_rows = mdf[mdf['exchange'] == 'NSE_INDEX']
    for _, r in idx_rows.iterrows():
        sym = str(r['tradingsymbol']).upper().strip()
        if sym in ("NIFTY", "NIFTY 50"): eq_map["NIFTY"] = str(r['instrument_key']).strip()
        elif sym in ("BANKNIFTY", "NIFTY BANK"): eq_map["BANKNIFTY"] = str(r['instrument_key']).strip()
        elif sym in ("FINNIFTY", "NIFTY FIN SERVICE"): eq_map["FINNIFTY"] = str(r['instrument_key']).strip()

    # Map active F&O expiry dates per underlying symbol
    fo_rows = mdf[(mdf['exchange'] == 'NSE_FO') & (mdf['instrument_type'].isin(['OPTSTK', 'OPTIDX']))]
    for _, r in fo_rows.iterrows():
        tsym = str(r['tradingsymbol']).upper().strip()
        exp = str(r['expiry']).strip()
        # Extract underlying prefix before digits in tradingsymbol (e.g. DIXON26NOV13000CE -> DIXON)
        und = ''.join([c for c in tsym.split('2')[0] if c.isalpha()]) if '2' in tsym else ""
        if und and exp:
            exp_map.setdefault(und, set()).add(exp)

    return eq_map, {k: sorted(list(v)) for k, v in exp_map.items()}

def resolve_fyers_sym(t):
    t = t.upper().strip()
    return {"NIFTY": "NSE:NIFTY50-INDEX", "NIFTY50": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "FINNIFTY": "NSE:FINNIFTY-INDEX"}.get(t, f"NSE:{t}-EQ")

def standardize_columns(df):
    df.columns = [str(c).strip() for c in df.columns]
    aliases = {
        'Index': ['index', 'symbol', 'stock', 'underlying', 'ticker'],
        'Expiry': ['expiry', 'expiry date', 'expiry_date', 'expiry_dt', 'exp'],
        'Type': ['type', 'option type', 'option_type', 'option_typ', 'opt_type'],
        'Strike': ['strike', 'strike price', 'strike_price', 'strike_pr'],
        'Close': ['close', 'ltp', 'close price', 'close_price', 'last price'],
        'Chg%': ['chg%', 'change%', '%chg', 'change %', 'pchange'],
        'Cr': ['cr', 'turnover', 'turnover (cr)', 'value', 'value (cr)'],
        'OI': ['oi', 'open int', 'open_int', 'open interest'],
        'OI_Chg': ['oi_chg', 'chg in oi', 'chg_in_oi', 'change in oi'],
        'OI_Action': ['oi_action', 'oi action', 'action', 'buildup']
    }
    rmap, used = {}, set()
    for std, al in aliases.items():
        for col in df.columns:
            if col not in used and col.lower() in al:
                rmap[col], used = std, used | {col}
                break
    return df.rename(columns=rmap)

def fetch_fyers(cid, tok, ticker):
    from fyers_apiv3 import fyersModel
    fsym = resolve_fyers_sym(ticker)
    resp = fyersModel.FyersModel(client_id=cid, token=tok, is_async=False, log_path="").optionchain(data={"symbol": fsym, "strikecount": 30, "timestamp": ""})
    if resp.get("s") != "ok": raise ValueError(resp.get("message", "Fyers API Error"))
    rows, spot = [], 0
    for i in resp["data"]["optionsChain"]:
        if i.get("option_type") == "": spot = i.get("ltp", 0)
        elif i.get("option_type") in ("CE", "PE"):
            rows.append({"Strike": float(i["strike_price"]), "Type": i["option_type"], "Live_LTP": float(i.get("ltp", 0)), "Live_OI": float(i.get("oi", 0))})
    return pd.DataFrame(rows), spot, fsym

def fetch_upstox(tok, ticker, man_exp=""):
    eq_map, exp_map = load_upstox_master()
    t = ticker.upper().strip()
    ikey = eq_map.get(t)
    if not ikey: raise ValueError(f"Ticker '{t}' not found in Upstox NSE master.")
    
    # If manual expiry is provided use it; otherwise fetch available contracts directly from Upstox API
    exp = man_exp.strip()
    if not exp:
        c_resp = requests.get(
            "https://upstox.com",
            headers={"Accept": "application/json", "Authorization": f"Bearer {tok}"},
            params={"instrument_key": ikey},
            timeout=10
        ).json()
        if c_resp.get("status") == "success" and c_resp.get("data"):
            exps = sorted(list({item["expiry"] for item in c_resp["data"] if item.get("expiry") >= datetime.now().strftime("%Y-%m-%d")}))
            exp = exps[0] if exps else ""
        if not exp:
            valid_exps = [e for e in exp_map.get(t, []) if e >= datetime.now().strftime("%Y-%m-%d")]
            exp = valid_exps[0] if valid_exps else ""

    resp = requests.get("https://upstox.com", headers={"Accept": "application/json", "Authorization": f"Bearer {tok}"}, params={"instrument_key": ikey, "expiry_date": exp}, timeout=10).json()
    if resp.get("status") != "success": raise ValueError(resp.get("errors", "Upstox API Error"))
    rows, spot = [], 0
    for i in resp.get("data", []):
        if not spot: spot = float(i.get("underlying_spot_price", 0))
        for sk, ot in [("call_options", "CE"), ("put_options", "PE")]:
            mkt = i.get(sk, {}).get("market_data", {})
            if mkt: rows.append({"Strike": float(i["strike_price"]), "Type": ot, "Live_LTP": float(mkt.get("ltp", 0)), "Live_OI": float(mkt.get("oi", 0))})
    return pd.DataFrame(rows), spot, f"{ikey} ({exp})"
# --- END OF PART 1 ---
# --- START OF PART 2 ---
st.sidebar.header("Scanner & Broker Settings")
asset_type = st.sidebar.radio("Instrument Type", ["F&O Stock", "Index"], index=0)
min_premium = st.sidebar.number_input("Minimum Option Premium (₹)", value=10.0 if asset_type == "F&O Stock" else 80.0, step=5.0)
live_broker = st.sidebar.selectbox("Live Market Feed", ["None (EOD CSV Only)", "Fyers API v3", "Upstox API v2"])
f_cid = st.sidebar.text_input("Fyers App ID") if live_broker == "Fyers API v3" else ""
f_tok = st.sidebar.text_input("Fyers Access Token", type="password") if live_broker == "Fyers API v3" else ""
u_tok = st.sidebar.text_input("Upstox Access Token", type="password") if live_broker == "Upstox API v2" else ""

c1, c2, c3 = st.columns([2, 1.5, 1])
uploaded_file = c1.file_uploader("1. Upload EOD Option CSV", type=["csv"])
stock_box = c2.text_input("2. Stock / Index Name (Auto-connects Live)", placeholder="e.g. BAJAJFINSV, RELIANCE, NIFTY")
manual_exp = c3.text_input("Expiry (Optional YYYY-MM-DD)", placeholder="Auto-detects")

if uploaded_file is not None:
    df = standardize_columns(pd.read_csv(uploaded_file))
    for col in ['Strike', 'Close', 'Chg%', 'Cr', 'OI', 'OI_Chg']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('%', '').str.strip(), errors='coerce')
    df['Type'] = df['Type'].astype(str).str.strip().str.upper().replace({'CALL': 'CE', 'PUT': 'PE'})
    if 'OI_Action' in df.columns: df['OI_Action'] = df['OI_Action'].astype(str).str.strip().str.upper()

    symbol_name = stock_box.strip().upper() or (str(df['Index'].dropna().head(1).item()).strip().upper() if 'Index' in df.columns and not df['Index'].dropna().empty else uploaded_file.name.removesuffix('.csv'))

    live_df, spot_price, res_info = pd.DataFrame(), 0, ""
    if live_broker != "None (EOD CSV Only)" and symbol_name:
        if st.button(f"🔄 Refresh Live Market ({symbol_name})"): st.rerun()
        try:
            if live_broker == "Fyers API v3" and f_cid and f_tok: live_df, spot_price, res_info = fetch_fyers(f_cid, f_tok, symbol_name)
            elif live_broker == "Upstox API v2" and u_tok: live_df, spot_price, res_info = fetch_upstox(u_tok, symbol_name, manual_exp)
        except Exception as e: st.error(f"Live API Error: {e}")

    if not live_df.empty:
        st.success(f"✅ Live Connected: **{symbol_name}** (`{res_info}`) | Spot: **₹{spot_price:.2f}** | {datetime.now().strftime('%H:%M:%S')}")
        df = pd.merge(df, live_df, on=['Strike', 'Type'], how='left')

    straddle_df = pd.merge(df[df['Type']=='CE'][['Strike','Close']].rename(columns={'Close':'CE'}), df[df['Type']=='PE'][['Strike','Close']].rename(columns={'Close':'PE'}), on='Strike').dropna()
    if not straddle_df.empty:
        straddle_df['Diff'] = (straddle_df['CE'] - straddle_df['PE']).abs()
        atm = straddle_df.sort_values('Diff').head(1).squeeze()
        atm_s, ce_p, pe_p = float(atm['Strike']), float(atm['CE']), float(atm['PE'])
        pts = ce_p + pe_p
    else: atm_s = ce_p = pe_p = pts = 0

    straddle_summary = pd.DataFrame([{"Symbol": symbol_name, "ATM_Strike": int(atm_s) if atm_s==int(atm_s) else atm_s, "ATM_CE": f"₹{ce_p:.2f}", "ATM_PE": f"₹{pe_p:.2f}", "Straddle_Pts": f"{pts:.2f}", "Upper_BE": f"{atm_s+pts:.2f}", "Lower_BE": f"{atm_s-pts:.2f}"}])
    st.subheader(f"🎯 EOD ATM Straddle — {symbol_name}")
    st.dataframe(straddle_summary, use_container_width=True, hide_index=True)

    rank_col = 'Cr' if 'Cr' in df.columns and df['Cr'].notna().any() else 'OI'
    top_inst = df[df['Close'] >= min_premium].sort_values(rank_col, ascending=False).head(15).copy()
    top_inst['Score'] = top_inst['OI_Chg'] + (top_inst['OI'] * 0.25)
    has_chg = 'Chg%' in top_inst.columns and top_inst['Chg%'].notna().any()
    has_sl = 'OI_Action' in top_inst.columns and top_inst['OI_Action'].str.contains('SHORT|LONG|WRIT|BUY', regex=True, na=False).any()

    def get_cand(ot, is_w):
        b = top_inst[(top_inst['Type'] == ot) & (top_inst['OI_Chg'] > 0)]
        if b.empty: return None
        if has_sl: sub = b[b['OI_Action'].str.contains('SHORT|WRIT|SB', regex=True, na=False)] if is_w else b[b['OI_Action'].str.contains('LONG|BUY|LB', regex=True, na=False)]
        elif has_chg: sub = b[b['Chg%'] < 0] if is_w else b[b['Chg%'] > 0]
        else: sub = (b[b['Strike'] >= atm_s] if is_w else b[b['Strike'] < atm_s]) if ot == 'CE' else (b[b['Strike'] <= atm_s] if is_w else b[b['Strike'] > atm_s])
        return None if sub.empty else sub.sort_values('Score', ascending=False).head(1).to_dict('records').pop()

    prep_rows = []
    for role, row, ot, is_w in [("#1 Bullish Short Squeeze (CE Write)", get_cand('CE', True), "CE", True), ("#1 Bearish Short Squeeze (PE Write)", get_cand('PE', True), "PE", True), ("#1 Bearish Long Squeeze (CE Buy)", get_cand('CE', False), "CE", False), ("#1 Bullish Long Squeeze (PE Buy)", get_cand('PE', False), "PE", False)]:
        if row:
            sv, cp, ltp = float(row['Strike']), float(row['Close']), row.get('Live_LTP')
            status = ("🚨 TRIGGERED (>EOD)" if ltp > cp else "⏳ Below") if (pd.notna(ltp) and ltp > 0 and is_w) else (("🚨 TRIGGERED (<EOD)" if ltp < cp else "⏳ Above") if (pd.notna(ltp) and ltp > 0) else "Waiting Live")
            trig = f"Buy {'Calls' if ot=='CE' else 'Puts'} > ₹{cp:.2f}" if is_w else f"Confirms {'down' if ot=='CE' else 'up'} < ₹{cp:.2f}"
            prep_rows.append({"Role": role, "Strike": f"{int(sv) if sv==int(sv) else sv} {ot}", "EOD_Close": f"₹{cp:.2f}", "Live_LTP": f"₹{ltp:.2f}" if pd.notna(ltp) else "-", "Live_Status": status, "OI_Chg": f"+{row['OI_Chg']/100000:.2f}L", "Trigger": trig})
        else:
            prep_rows.append({"Role": role, "Strike": "None", "EOD_Close": "-", "Live_LTP": "-", "Live_Status": "-", "OI_Chg": "-", "Trigger": "No signal"})

    prep_df = pd.DataFrame(prep_rows)
    st.subheader(f"⚡ EOD Prep Card vs. Live Market — {symbol_name}")
    st.dataframe(prep_df, use_container_width=True, hide_index=True)

    if not live_df.empty:
        st.subheader(f"📡 Live Multi-Strike Squeeze Radar (All Strikes) — {symbol_name}")
        rad = df[df['Live_LTP'].notna() & (df['Live_LTP'] >= min_premium)].copy()
        rad['Vs_EOD_%'] = ((rad['Live_LTP'] - rad['Close']) / rad['Close'] * 100).round(2)
        rad['OI_Diff'] = rad['Live_OI'] - rad['OI']
        rad['Signal'] = rad.apply(lambda r: "🔥 LIVE BULLISH SHORT SQUEEZE" if (r['Type']=='CE' and r['Vs_EOD_%']>5 and r['OI_Diff']<0) else ("🔻 LIVE BEARISH SHORT SQUEEZE" if (r['Type']=='PE' and r['Vs_EOD_%']>5 and r['OI_Diff']<0) else ("⚠️ LIVE BEARISH LONG TRAP" if (r['Type']=='CE' and r['Vs_EOD_%']<-5 and r['Live_OI']>r['OI']) else ("🚀 LIVE BULLISH LONG TRAP" if (r['Type']=='PE' and r['Vs_EOD_%']<-5 and r['Live_OI']>r['OI']) else "Normal"))), axis=1)
        act = rad[rad['Signal'] != "Normal"].sort_values('Live_OI', ascending=False)
        st.dataframe(act[['Strike', 'Type', 'Close', 'Live_LTP', 'Vs_EOD_%', 'OI', 'Live_OI', 'Signal']], use_container_width=True, hide_index=True) if not act.empty else st.info("No >5% multi-strike squeeze divergences right now.")

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        prep_df.to_excel(w, sheet_name="Prep_Card", index=False)
        straddle_summary.to_excel(w, sheet_name="Straddle", index=False)
    b1, b2 = st.columns(2)
    b1.download_button("⬇️ Download Excel (.xlsx)", buf.getvalue(), f"{symbol_name}_Prep.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    b2.download_button("⬇️ Download CSV (.csv)", prep_df.to_csv(index=False).encode('utf-8'), f"{symbol_name}_Prep.csv", "text/csv")
# --- END OF PART 2 ---
