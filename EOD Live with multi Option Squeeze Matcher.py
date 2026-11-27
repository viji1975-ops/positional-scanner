import streamlit as st
import pandas as pd
import requests, hashlib, io, calendar, time
from datetime import datetime, date

st.set_page_config(page_title="EOD + Live Option Squeeze Matcher", layout="wide")
st.title("📊 EOD + Live Market Option Squeeze Matcher")

UPSTOX_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50", "BANKNIFTY": "NSE_INDEX|Nifty Bank", "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT", "DIXON": "NSE_EQ|INE935N01020", "RELIANCE": "NSE_EQ|INE002A01018",
    "HDFCBANK": "NSE_EQ|INE040A01034", "ICICIBANK": "NSE_EQ|INE090A01021", "INFY": "NSE_EQ|INE009A01021",
    "TCS": "NSE_EQ|INE467B01029", "SBIN": "NSE_EQ|INE062A01020", "AXISBANK": "NSE_EQ|INE238A01034",
    "KOTAKBANK": "NSE_EQ|INE237A01028", "LT": "NSE_EQ|INE018A01030", "BHARTIARTL": "NSE_EQ|INE397D01024",
    "BAJFINANCE": "NSE_EQ|INE296A01024", "BAJAJFINSV": "NSE_EQ|INE918I01026", "MARUTI": "NSE_EQ|INE585B01010",
    "TATAMOTORS": "NSE_EQ|INE155A01022", "TATASTEEL": "NSE_EQ|INE081A01020", "SUNPHARMA": "NSE_EQ|INE044A01036",
    "M&M": "NSE_EQ|INE101A01026", "NTPC": "NSE_EQ|INE733E01010", "ITC": "NSE_EQ|INE154A01025",
    "TRENT": "NSE_EQ|INE849A01020", "BEL": "NSE_EQ|INE263A01024", "HAL": "NSE_EQ|INE066F01020",
    "TITAN": "NSE_EQ|INE280A01028", "ADANIENT": "NSE_EQ|INE423A01024", "ADANIPORTS": "NSE_EQ|INE742F01042"
}

def get_default_monthly_expiry():
    today = date.today()
    y, m = today.year, today.month
    last_day = calendar.monthrange(y, m)[1]
    d = date(y, m, last_day)
    while d.weekday() != 3:
        d = date(y, m, d.day - 1)
    if d < today:
        m = 1 if m == 12 else m + 1
        y = y + 1 if m == 1 else y
        last_day = calendar.monthrange(y, m)[1]
        d = date(y, m, last_day)
        while d.weekday() != 3:
            d = date(y, m, d.day - 1)
    return d.strftime("%Y-%m-%d")

def resolve_fyers_sym(t):
    t = t.upper().strip()
    special_map = {
        "NIFTY": "NSE:NIFTY50-INDEX",
        "NIFTY50": "NSE:NIFTY50-INDEX",
        "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
        "FINNIFTY": "NSE:FINNIFTY-INDEX",
        "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX",
        "SENSEX": "BSE:SENSEX-INDEX",
        "BANKEX": "BSE:BANKEX-INDEX"
    }
    if ":" in t:
        return t
    return special_map.get(t, f"NSE:{t}-EQ")

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

def generate_fyers_token_from_url(app_id, secret_key, redirect_url_or_code):
    raw = redirect_url_or_code.strip()
    auth_code = raw.split("auth_code=")[-1].split("&").pop(0) if "auth_code=" in raw else raw
    app_hash = hashlib.sha256(f"{app_id.strip()}:{secret_key.strip()}".encode()).hexdigest()
    api_url = "https://" + "api-t1.fyers.in/api/v3/validate-authcode"
    r = requests.post(api_url, json={"grant_type": "authorization_code", "appIdHash": app_hash, "code": auth_code}, timeout=10)
    if not r.text.strip():
        raise ValueError(f"Fyers HTTP {r.status_code}: Auth code expired. Login again for a fresh URL.")
    res = r.json()
    if res.get("s") == "ok" and res.get("access_token"):
        return res["access_token"]
    raise ValueError(res.get("message", f"Fyers Error: {res}"))

def fetch_fyers(cid, tok, ticker, strike_count=30):
    from fyers_apiv3 import fyersModel
    clean_tok = tok.split(":")[-1].strip()
    fsym = resolve_fyers_sym(ticker)
    fyers = fyersModel.FyersModel(client_id=cid.strip(), token=clean_tok, is_async=False, log_path="")
    resp = fyers.optionchain(data={"symbol": fsym, "strikecount": strike_count, "timestamp": ""})
    if resp.get("s") != "ok":
        raise ValueError(f"{resp.get('message', 'Fyers API Error')}")
    rows, spot, spot_chg = [], 0, 0
    for i in resp["data"]["optionsChain"]:
        if i.get("option_type") == "":
            spot = float(i.get("ltp", 0))
            spot_chg = float(i.get("ltpchp", 0))
        elif i.get("option_type") in ("CE", "PE"):
            rows.append({
                "Strike": float(i["strike_price"]), "Type": i["option_type"],
                "Live_LTP": float(i.get("ltp", 0)), "Live_Chg%": float(i.get("ltpchp", 0)),
                "Live_OI": float(i.get("oi", 0)), "Live_OI_Chg": float(i.get("oich", 0))
            })
    return pd.DataFrame(rows), spot, spot_chg, fsym

def fetch_upstox(tok, ticker, man_exp=""):
    clean_tok = tok.strip()
    t = ticker.upper().strip()
    ikey = t if "|" in t else UPSTOX_KEYS.get(t)
    if not ikey:
        raise ValueError(f"Ticker '{t}' not in quick list. Enter Upstox key (e.g. NSE_EQ|INE...) in Stock box.")
    exp = man_exp.strip() or get_default_monthly_expiry()
    chain_url = "https://" + "://upstox.com"
    r = requests.get(chain_url, headers={"Accept": "application/json", "Authorization": f"Bearer {clean_tok}"}, params={"instrument_key": ikey, "expiry_date": exp}, timeout=10)
    if r.status_code != 200 or not r.text.strip():
        raise ValueError(f"Upstox Chain Error (HTTP {r.status_code}) for {ikey} on {exp}: {r.text[:150]}")
    resp = r.json()
    if resp.get("status") != "success":
        raise ValueError(resp.get("errors", "Upstox API Error"))
    rows, spot = [], 0
    for i in resp.get("data", []):
        if not spot: spot = float(i.get("underlying_spot_price", 0))
        for sk, ot in [("call_options", "CE"), ("put_options", "PE")]:
            mkt = i.get(sk, {}).get("market_data", {})
            if mkt:
                ltp = float(mkt.get("ltp", 0))
                prev_c = float(mkt.get("close_price", ltp) or ltp)
                oi = float(mkt.get("oi", 0))
                prev_oi = float(mkt.get("prev_oi", oi))
                rows.append({
                    "Strike": float(i["strike_price"]), "Type": ot,
                    "Live_LTP": ltp, "Live_Chg%": round(((ltp - prev_c) / prev_c * 100) if prev_c else 0, 2),
                    "Live_OI": oi, "Live_OI_Chg": oi - prev_oi
                })
    return pd.DataFrame(rows), spot, 0.0, f"{ikey} ({exp})"
# --- END OF PART 1 ---
# --- START OF PART 2 ---
st.sidebar.header("Scanner & Broker Settings")
asset_type = st.sidebar.radio("Instrument Type", ["F&O Stock", "Index"], index=0)
min_premium = st.sidebar.number_input("Minimum Option Premium (₹)", value=10.0 if asset_type == "F&O Stock" else 80.0, step=5.0)
live_broker = st.sidebar.selectbox("Live Market Feed", ["Fyers API v3", "Upstox API v2", "None (EOD CSV Only)"], index=0)

f_cid = f_tok = u_tok = ""
if live_broker == "Fyers API v3":
    f_cid = st.sidebar.text_input("Fyers App ID", value="D2B1MP5NVR-100")
    f_tok = st.sidebar.text_input("Fyers Access Token (starts with eyJ...)", type="password")
    with st.sidebar.expander("🔑 Generate Fyers Token Here", expanded=False):
        f_sec = st.text_input("Fyers Secret Key", type="password")
        f_red = st.text_input("Redirect URI (Must match Fyers App)", value="https://127.0.0.1")
        if f_cid and f_red:
            l_url = "https://" + f"api-t1.fyers.in/api/v3/generate-authcode?client_id={f_cid.strip()}&redirect_uri={f_red.strip()}&response_type=code&state=sample"
            st.caption("Step 1: Copy & open this URL in a new tab:")
            st.code(l_url)
        p_url = st.text_input("Step 2: Paste Redirected URL here")
        if st.button("Step 3: Get Access Token") and f_sec and p_url:
            try:
                gt = generate_fyers_token_from_url(f_cid, f_sec, p_url)
                st.success("✅ Copy token below & paste into Fyers Access Token box above:")
                st.code(gt)
            except Exception as e:
                st.error(f"Token Error: {e}")
elif live_broker == "Upstox API v2":
    u_tok = st.sidebar.text_input("Upstox Access Token", type="password")

tab1, tab2 = st.tabs(["📊 Single Stock EOD + Live Matcher", "📋 Multi-Stock Watchlist Radar (Fyers)"])

# ================= TAB 1: SINGLE STOCK EOD + LIVE MATCHER =================
with tab1:
    c1, c2, c3 = st.columns([2, 1.5, 1])
    uploaded_file = c1.file_uploader("1. Upload EOD Option CSV", type=["csv"])
    stock_box = c2.text_input("2. Stock / Index Name (Auto-connects Live)", placeholder="e.g. DIXON, RELIANCE, NIFTY")
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
                if live_broker == "Fyers API v3" and f_cid and f_tok: live_df, spot_price, _, res_info = fetch_fyers(f_cid, f_tok, symbol_name)
                elif live_broker == "Upstox API v2" and u_tok: live_df, spot_price, _, res_info = fetch_upstox(u_tok, symbol_name, manual_exp)
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
            if not act.empty:
                st.dataframe(act[['Strike', 'Type', 'Close', 'Live_LTP', 'Vs_EOD_%', 'OI', 'Live_OI', 'Signal']], use_container_width=True, hide_index=True)
            else:
                st.info("No >5% multi-strike squeeze divergences right now.")

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine='openpyxl') as w:
            prep_df.to_excel(w, sheet_name="Prep_Card", index=False)
            straddle_summary.to_excel(w, sheet_name="Straddle", index=False)
        b1, b2 = st.columns(2)
        b1.download_button("⬇️ Download Excel (.xlsx)", buf.getvalue(), f"{symbol_name}_Prep.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        b2.download_button("⬇️ Download CSV (.csv)", prep_df.to_csv(index=False).encode('utf-8'), f"{symbol_name}_Prep.csv", "text/csv")

# ================= TAB 2: MULTI-STOCK WATCHLIST RADAR =================
with tab2:
    st.subheader("📋 Multi-Stock Live Option Squeeze Radar (Fyers API v3)")
    st.caption("Select an F&O Sector Preset or customize your ticker list to scan for simultaneous Short Squeezes & Long Traps.")

    SECTOR_PRESETS = {
        "Custom / My Watchlist": "NIFTY, BANKNIFTY, SENSEX, DIXON, RELIANCE, TRENT, HAL, BEL, HDFCBANK, ICICIBANK, BAJFINANCE",
        "Indices (NSE & BSE)": "NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY, BANKEX",
        "Banking & Financials": "HDFCBANK, ICICIBANK, SBIN, AXISBANK, KOTAKBANK, INDUSINDBK, BAJFINANCE, BAJAJFINSV, PFC, RECLTD",
        "Defence, PSU & Infra": "HAL, BEL, MAZDOCK, BDL, NTPC, POWERGRID, ONGC, COALINDIA, LT, ADANIPORTS",
        "IT & Telecom": "TCS, INFY, HCLTECH, WIPRO, TECHM, LTIM, PERSISTENT, COFORGE, BHARTIARTL",
        "Auto & EV": "MARUTI, TATAMOTORS, M&M, BAJAJ-AUTO, EICHERMOT, HEROMOTOCO, TVSMOTOR, ASHOKLEY",
        "High-Beta Momentum": "DIXON, TRENT, ZOMATO, CHOLAFIN, TVSMOTOR, POLYCAB, HAVELLS, VOLTAS, TITAN, ADANIENT"
    }

    selected_preset = st.selectbox("🎯 Choose F&O Sector Preset", list(SECTOR_PRESETS.keys()), index=0)
    wl_input = st.text_area(
        "Active Tickers to Scan (Edit or add any NSE F&O stock)",
        value=SECTOR_PRESETS[selected_preset],
        height=70
    )
    if st.button("🚀 Scan Entire Watchlist Live"):
        if not f_cid or not f_tok:
            st.error("⚠️ Please select **Fyers API v3** in the left sidebar and enter your **App ID** and **Access Token** first.")       
        else:
            tickers = [t.strip().upper() for t in wl_input.split(",") if t.strip()]
            wl_rows = []
            prog = st.progress(0)
            for idx, tk in enumerate(tickers):
                try:
                    wdf, w_spot, w_chg, _ = fetch_fyers(f_cid, f_tok, tk, strike_count=15)
                    if not wdf.empty:
                        liq = wdf[wdf['Live_LTP'] >= min_premium].copy()
                        ce_sq = liq[(liq['Type']=='CE') & (liq['Live_Chg%']>5) & (liq['Live_OI_Chg']<0)].sort_values('Live_OI', ascending=False)
                        pe_sq = liq[(liq['Type']=='PE') & (liq['Live_Chg%']>5) & (liq['Live_OI_Chg']<0)].sort_values('Live_OI', ascending=False)
                        ce_tr = liq[(liq['Type']=='CE') & (liq['Live_Chg%']<-5) & (liq['Live_OI_Chg']>0)].sort_values('Live_OI', ascending=False)
                        pe_tr = liq[(liq['Type']=='PE') & (liq['Live_Chg%']<-5) & (liq['Live_OI_Chg']>0)].sort_values('Live_OI', ascending=False)

                        r_cs = ce_sq.head(1).squeeze() if not ce_sq.empty else None
                        r_ps = pe_sq.head(1).squeeze() if not pe_sq.empty else None
                        r_pt = pe_tr.head(1).squeeze() if not pe_tr.empty else None
                        r_ct = ce_tr.head(1).squeeze() if not ce_tr.empty else None

                        bull_sq_txt = f"{int(r_cs['Strike'])} CE (+{r_cs['Live_Chg%']:.1f}%)" if r_cs is not None else "-"
                        bear_sq_txt = f"{int(r_ps['Strike'])} PE (+{r_ps['Live_Chg%']:.1f}%)" if r_ps is not None else "-"
                        bull_tr_txt = f"{int(r_pt['Strike'])} PE ({r_pt['Live_Chg%']:.1f}%)" if r_pt is not None else "-"
                        bear_tr_txt = f"{int(r_ct['Strike'])} CE ({r_ct['Live_Chg%']:.1f}%)" if r_ct is not None else "-"

                        bull_pts = (1 if r_cs is not None else 0) + (1 if r_pt is not None else 0)
                        bear_pts = (1 if r_ps is not None else 0) + (1 if r_ct is not None else 0)
                        if bull_pts == 2 and bear_pts == 0: bias = "🔥 STRONG BULLISH SQUEEZE"
                        elif bear_pts == 2 and bull_pts == 0: bias = "🔻 STRONG BEARISH SQUEEZE"
                        elif bull_pts > bear_pts: bias = "📈 Mild Bullish"
                        elif bear_pts > bull_pts: bias = "📉 Mild Bearish"
                        else: bias = "⚖️ Neutral / Choppy"

                        wl_rows.append({
                            "Symbol": tk, "Spot_LTP": f"₹{w_spot:.2f}", "Spot_Chg%": f"{w_chg:+.2f}%",
                            "Squeeze_Bias": bias, "Bullish_Short_Squeeze (CE)": bull_sq_txt,
                            "Bullish_Long_Trap (PE)": bull_tr_txt, "Bearish_Short_Squeeze (PE)": bear_sq_txt,
                            "Bearish_Long_Trap (CE)": bear_tr_txt
                        })
                except Exception as ex:
                    wl_rows.append({"Symbol": tk, "Spot_LTP": "Error", "Spot_Chg%": "-", "Squeeze_Bias": str(ex)[:45], "Bullish_Short_Squeeze (CE)": "-", "Bullish_Long_Trap (PE)": "-", "Bearish_Short_Squeeze (PE)": "-", "Bearish_Long_Trap (CE)": "-"})
                prog.progress((idx + 1) / len(tickers))
                time.sleep(0.15)

            if wl_rows:
                wl_res_df = pd.DataFrame(wl_rows)
                st.dataframe(wl_res_df, use_container_width=True, hide_index=True)
                st.download_button("⬇️ Download Watchlist Scan (.csv)", wl_res_df.to_csv(index=False).encode('utf-8'), f"Watchlist_Squeeze_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv", "text/csv")
# --- END OF PART 2 ---
