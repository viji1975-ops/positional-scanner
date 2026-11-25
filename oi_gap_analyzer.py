import glob
import io
import os
import urllib.parse
import pandas as pd
import streamlit as st
from bhavcopy_analytics import (
    parse_bhav_master,
    render_bhavcopy_section,
    render_confluence_tab,
    render_live_institutional,
    render_multi_index_radar,
)

st.set_page_config(page_title="NSE/BSE OI & Gap Scanner", layout="wide")
st.title("📊 NSE & BSE 3-Mode OI & Institutional Scanner (Live • EOD • Combined)")

INDEX_CONFIG = {
    "NIFTY": {"syms": ["NIFTY"], "step": 50, "lot": 75, "fyers": "NSE:NIFTY50-INDEX", "spot": 25720.0},
    "BANKNIFTY": {"syms": ["BANKNIFTY"], "step": 100, "lot": 30, "fyers": "NSE:NIFTYBANK-INDEX", "spot": 63350.0},
    "FINNIFTY": {"syms": ["FINNIFTY"], "step": 50, "lot": 65, "fyers": "NSE:FINNIFTY-INDEX", "spot": 24500.0},
    "MIDCPNIFTY": {"syms": ["MIDCPNIFTY"], "step": 25, "lot": 120, "fyers": "NSE:MIDCPNIFTY-INDEX", "spot": 12800.0},
    "NIFTYNXT50": {"syms": ["NIFTYNXT50"], "step": 100, "lot": 25, "fyers": "NSE:NIFTYNXT50-INDEX", "spot": 71000.0},
    "SENSEX": {"syms": ["SENSEX", "BSX"], "step": 100, "lot": 20, "fyers": "BSE:SENSEX-INDEX", "spot": 84350.0},
    "BANKEX": {"syms": ["BANKEX", "BKX"], "step": 100, "lot": 30, "fyers": "BSE:BANKEX-INDEX", "spot": 72000.0},
}

if "fyers_token" not in st.session_state:
    st.session_state["fyers_token"] = ""

st.sidebar.header("1. Index & Broker Settings")
idx = st.sidebar.selectbox("Select Index", list(INDEX_CONFIG.keys()))
cfg = INDEX_CONFIG[idx]
step, lot_size = cfg["step"], cfg["lot"]

use_fyers = st.sidebar.checkbox("Fetch Live Spot & Option Chain (Fyers)", value=True)
client_id = st.sidebar.text_input("Fyers App ID (Client ID)", placeholder="e.g. XC4XXXXM-100")

with st.sidebar.expander("🔑 Generate Today's Fyers Access Token"):
    secret_id = st.text_input("Fyers Secret ID", type="password")
    redir_uri = st.text_input("Redirect URI", value="https://127.0.0.1")
    if client_id and secret_id:
        from fyers_apiv3 import fyersModel
        sess = fyersModel.SessionModel(
            client_id=client_id.strip(),
            secret_key=secret_id.strip(),
            redirect_uri=redir_uri.strip(),
            response_type="code",
            grant_type="authorization_code",
        )
        st.markdown(f"1. [Click here to Login to Fyers]({sess.generate_authcode()})")
        redir_url = st.text_input("2. Paste full redirected URL here:")
        if st.button("Generate Access Token") and redir_url:
            try:
                parsed = urllib.parse.urlparse(redir_url.strip())
                q = urllib.parse.parse_qs(parsed.query)
                code = next(iter(q["auth_code"])) if "auth_code" in q else redir_url.strip()
                sess.set_token(code.strip())
                resp = sess.generate_token()
                if "access_token" in resp:
                    st.session_state["fyers_token"] = resp["access_token"]
                    st.success("Token applied!")
                else:
                    st.error(f"Error: {resp}")
            except Exception as e:
                st.error(f"Failed: {e}")

token = st.sidebar.text_input("Fyers Access Token (Daily JWT)", value=st.session_state["fyers_token"], type="password")
manual_spot = st.sidebar.number_input("Simulated / Fallback Spot Price", value=cfg["spot"], step=float(step))
skip_expired = st.sidebar.checkbox("Auto-Skip Expired Contracts (Bhavcopy)", value=True)

def get_fyers_live_chain(cid, tok, sym):
    from fyers_apiv3 import fyersModel
    fyers = fyersModel.FyersModel(client_id=cid.strip(), token=tok.strip(), is_async=False)
    q_res = fyers.quotes(data={"symbols": sym})
    spot = next(iter(q_res["d"]))["v"]["lp"] if q_res.get("s") == "ok" and q_res.get("d") else None
    oc_res = fyers.optionchain(data={"symbol": sym, "strikecount": 12, "timestamp": ""})
    chain_rows = oc_res.get("data", {}).get("optionsChain", []) if oc_res.get("s") == "ok" else []
    return spot, chain_rows

live_price, live_chain = manual_spot, []
if use_fyers and client_id and token:
    try:
        f_spot, live_chain = get_fyers_live_chain(client_id, token, cfg["fyers"])
        if f_spot:
            live_price = f_spot
            st.sidebar.success(f"Live {idx}: {live_price}")
    except Exception as e:
        st.sidebar.error(f"Fyers Live Error: {e}")
if use_fyers and client_id and token:
    if st.button("📡 Scan All 7 Indices (Multi-Index Squeeze & Institutional Radar)"):
        if use_fyers and client_id and token:
    with st.expander("📡 Multi-Index Squeeze & Institutional Radar (With Time-Slot Snapshots)", expanded=True):
        render_multi_index_radar(INDEX_CONFIG, client_id, token)

with st.expander("📁 EOD Data Loader (20–25 Bhavcopy Files + Optional Participant OI CSV)", expanded=True):
    col_a, col_b = st.columns([2, 1])
    with col_a:
        mode = st.radio("Bhavcopy Source", ["Upload Files Manually", "Auto-Load from GitHub Folder (./bhavcopy_data)"], horizontal=True)
        files = []
        if mode == "Upload Files Manually":
            uploaded = st.file_uploader("Select 20–25 NSE (.zip) or BSE (.csv) Bhavcopies", type=["zip", "csv"], accept_multiple_files=True)
            if uploaded:
                files = uploaded
        else:
            paths = sorted(glob.glob("bhavcopy_data/*.zip") + glob.glob("bhavcopy_data/*.csv"))
            if paths:
                st.success(f"Loaded {len(paths[-25:])} file(s) from ./bhavcopy_data/")
                for p in paths[-25:]:
                    with open(p, "rb") as fp:
                        buf = io.BytesIO(fp.read())
                        buf.name = os.path.basename(p)
                        files.append(buf)
    with col_b:
        part_csv = st.file_uploader("Optional: NSE Participant OI CSV (fao_participant_oi_*.csv)", type=["csv"])

eod_master = parse_bhav_master(files, cfg["syms"]) if files else None

tab_live, tab_eod, tab_both = st.tabs([
    "⚡ 1. Live Market & Institutional Footprint",
    "📁 2. EOD Bhavcopy & FII Positioning",
    "🎯 3. Combined (EOD + Live Confluence)",
])

ce_live, pe_live = pd.DataFrame(), pd.DataFrame()
call_sq, put_sq = False, False
atm = round(live_price / step) * step

with tab_live:
    if live_chain:
        lc_df = pd.DataFrame(live_chain)
        lc_df = lc_df[lc_df["option_type"].isin(["CE", "PE"])].copy()
        lc_df["prev_eod_oi"] = lc_df["oi"] - lc_df["oich"]

        ce_live = lc_df[lc_df["option_type"] == "CE"].set_index("strike_price")
        pe_live = lc_df[lc_df["option_type"] == "PE"].set_index("strike_price")

        live_pcr = round(pe_live["oi"].sum() / ce_live["oi"].sum(), 2) if ce_live["oi"].sum() > 0 else 0
        res_wall, sup_wall = ce_live["oi"].idxmax(), pe_live["oi"].idxmax()

        trapped_ce = ce_live[(ce_live["prev_eod_oi"] > ce_live["prev_eod_oi"].median()) & (ce_live.index < live_price) & (ce_live["oich"] < 0)].sort_values(by="oich")
        trapped_pe = pe_live[(pe_live["prev_eod_oi"] > pe_live["prev_eod_oi"].median()) & (pe_live.index > live_price) & (pe_live["oich"] < 0)].sort_values(by="oich")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Live {idx} Spot", live_price)
        m2.metric("Live Intraday PCR", live_pcr)
        m3.metric("Live Call Wall", f"{int(res_wall)} CE")
        m4.metric("Live Put Wall", f"{int(sup_wall)} PE")

        if not trapped_ce.empty:
            call_sq = True
            st.success(f"🚀 LIVE CALL SQUEEZE ({idx}): Unwinding confirmed at {trapped_ce.index.tolist()[:4]}. Best Strike: **{int(atm - step)} CE**")
        if not trapped_pe.empty and live_pcr < 0.85:
            put_sq = True
            st.error(f"🔻 LIVE PUT SQUEEZE ({idx}): Unwinding confirmed at {trapped_pe.index.tolist()[:4]}. Best Strike: **{int(atm + step)} PE**")
        if not call_sq and not put_sq:
            st.info(f"No confirmed live squeeze. Resistance: **{int(res_wall)} CE** | Support: **{int(sup_wall)} PE**")

        c1, c2 = st.columns(2)
        cols = [c for c in ["ltp", "prev_eod_oi", "oi", "oich", "volume"] if c in lc_df.columns]
        with c1:
            st.subheader(f"Live {idx} Call (CE) Option Chain")
            st.dataframe(ce_live[cols].sort_index())
        with c2:
            st.subheader(f"Live {idx} Put (PE) Option Chain")
            st.dataframe(pe_live[cols].sort_index())

        render_live_institutional(lc_df, lot_size)
    else:
        st.info("Enter your Fyers App ID and Access Token in the sidebar to view live intraday & institutional analysis.")

with tab_eod:
    if eod_master is not None:
        render_bhavcopy_section(eod_master, idx, live_price, skip_expired, part_csv)
    else:
        st.info("Upload 20–25 NSE (.zip) or BSE (.csv) Bhavcopies above to view EOD positional & institutional analysis.")

with tab_both:
    render_confluence_tab(eod_master, ce_live, pe_live, idx, live_price, step, skip_expired, call_sq, put_sq)
