import glob
import io
import os
import urllib.parse
import pandas as pd
import streamlit as st
from bhavcopy_analytics import render_bhavcopy_section

st.set_page_config(page_title="NSE/BSE OI & Gap Scanner", layout="wide")
st.title("📊 NSE & BSE Live Option Chain + 25-Day Bhavcopy OI Scanner")

INDEX_CONFIG = {
    "NIFTY": {"syms": ["NIFTY"], "step": 50, "fyers": "NSE:NIFTY50-INDEX", "spot": 25660.0},
    "BANKNIFTY": {"syms": ["BANKNIFTY"], "step": 100, "fyers": "NSE:NIFTYBANK-INDEX", "spot": 63350.0},
    "FINNIFTY": {"syms": ["FINNIFTY"], "step": 50, "fyers": "NSE:FINNIFTY-INDEX", "spot": 24500.0},
    "MIDCPNIFTY": {"syms": ["MIDCPNIFTY"], "step": 25, "fyers": "NSE:MIDCPNIFTY-INDEX", "spot": 12800.0},
    "NIFTYNXT50": {"syms": ["NIFTYNXT50"], "step": 100, "fyers": "NSE:NIFTYNXT50-INDEX", "spot": 71000.0},
    "SENSEX": {"syms": ["SENSEX", "BSX"], "step": 100, "fyers": "BSE:SENSEX-INDEX", "spot": 84350.0},
    "BANKEX": {"syms": ["BANKEX", "BKX"], "step": 100, "fyers": "BSE:BANKEX-INDEX", "spot": 72000.0},
}

if "fyers_token" not in st.session_state:
    st.session_state["fyers_token"] = ""

st.sidebar.header("1. Index & Broker Settings")
idx = st.sidebar.selectbox("Select Index", list(INDEX_CONFIG.keys()))
cfg = INDEX_CONFIG[idx]
step = cfg["step"]

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

live_price = manual_spot
live_chain = []
if use_fyers and client_id and token:
    try:
        f_spot, live_chain = get_fyers_live_chain(client_id, token, cfg["fyers"])
        if f_spot:
            live_price = f_spot
            st.sidebar.success(f"Live {idx}: {live_price}")
    except Exception as e:
        st.sidebar.error(f"Fyers Live Error: {e}")

if live_chain:
    st.header(f"⚡ Live Fyers Intraday OI & Dual-Squeeze Scanner ({idx})")
    lc_df = pd.DataFrame(live_chain)
    lc_df = lc_df[lc_df["option_type"].isin(["CE", "PE"])].copy()
    lc_df["prev_eod_oi"] = lc_df["oi"] - lc_df["oich"]

    ce_live = lc_df[lc_df["option_type"] == "CE"].set_index("strike_price")
    pe_live = lc_df[lc_df["option_type"] == "PE"].set_index("strike_price")

    live_pcr = round(pe_live["oi"].sum() / ce_live["oi"].sum(), 2) if ce_live["oi"].sum() > 0 else 0
    res_wall = ce_live["oi"].idxmax()
    sup_wall = pe_live["oi"].idxmax()

    trapped_ce = ce_live[(ce_live["prev_eod_oi"] > ce_live["prev_eod_oi"].median()) & (ce_live.index < live_price)].sort_values(by="prev_eod_oi", ascending=False)
    trapped_pe = pe_live[(pe_live["prev_eod_oi"] > pe_live["prev_eod_oi"].median()) & (pe_live.index > live_price)].sort_values(by="prev_eod_oi", ascending=False)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(f"Live {idx} Spot", live_price)
    m2.metric("Live Intraday PCR", live_pcr)
    m3.metric("Immediate Resistance (Max CE OI)", f"{int(res_wall)} CE")
    m4.metric("Immediate Support (Max PE OI)", f"{int(sup_wall)} PE")

    atm = round(live_price / step) * step
    alert_shown = False

    if not trapped_ce.empty:
        ce_breached = trapped_ce.index.tolist()[:4]
        unwinding_ce = trapped_ce[trapped_ce["oich"] < 0].index.tolist()
        note_ce = f" | Live Unwinding Confirmed at: {unwinding_ce}" if unwinding_ce else ""
        st.success(f"🚀 GAP-UP CALL SQUEEZE ({idx}): Breached EOD Call walls {ce_breached}. Best Strike: **{int(atm - step)} CE**{note_ce}")
        alert_shown = True

    if not trapped_pe.empty:
        pe_breached = trapped_pe.index.tolist()[:4]
        unwinding_pe = trapped_pe[trapped_pe["oich"] < 0].index.tolist()
        note_pe = f" | Live Unwinding Confirmed at: {unwinding_pe}" if unwinding_pe else ""
        st.error(f"🔻 GAP-DOWN PUT SQUEEZE ({idx}): Broke below EOD Put walls {pe_breached}. Best Strike: **{int(atm + step)} PE**{note_pe}")
        alert_shown = True

    if not alert_shown:
        st.info(f"Range-Bound Zone: Resistance at **{int(res_wall)} CE** | Support at **{int(sup_wall)} PE**")

    c_left, c_right = st.columns(2)
    show_cols = [c for c in ["ltp", "prev_eod_oi", "oi", "oich", "volume"] if c in lc_df.columns]
    with c_left:
        st.subheader(f"Live {idx} Call (CE) OI & Unwinding")
        st.dataframe(ce_live[show_cols].sort_index())
    with c_right:
        st.subheader(f"Live {idx} Put (PE) OI & Unwinding")
        st.dataframe(pe_live[show_cols].sort_index())
else:
    st.info("💡 Enter your **Fyers App ID** and **Access Token** in the sidebar to run live without uploading Bhavcopies.")

st.divider()
st.header("📁 20–25 Day Bhavcopy Multi-Day OI, PCR History & Writer Breakeven")
mode = st.radio("Choose Bhavcopy Source", ["Upload Files Manually", "Auto-Load from GitHub Folder (./bhavcopy_data)"], horizontal=True)

files = []
if mode == "Upload Files Manually":
    uploaded = st.file_uploader("Select 20–25 NSE (.zip) or BSE (.csv) files", type=["zip", "csv"], accept_multiple_files=True)
    if uploaded:
        files = uploaded
else:
    paths = sorted(glob.glob("bhavcopy_data/*.zip") + glob.glob("bhavcopy_data/*.csv"))
    if paths:
        st.success(f"Auto-loaded {len(paths[-25:])} file(s) from ./bhavcopy_data/")
        for p in paths[-25:]:
            with open(p, "rb") as fp:
                buf = io.BytesIO(fp.read())
                buf.name = os.path.basename(p)
                files.append(buf)

if files:
    render_bhavcopy_section(files, cfg["syms"], idx, live_price, skip_expired)
else:
    st.info("Upload 20–25 NSE (.zip) or BSE (.csv) files above to view the rolling PCR chart, cumulative OI buildup, and writer breakeven status.")

