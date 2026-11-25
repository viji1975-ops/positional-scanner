import datetime
import glob
import io
import os
import urllib.parse
import zipfile
import pandas as pd
import streamlit as st

st.set_page_config(page_title="NSE/BSE OI & Gap Scanner", layout="wide")
st.title("📊 NSE & BSE Bhavcopy OI + Fyers Live Option Chain Scanner")

INDEX_CONFIG = {
    "NIFTY": {"syms": ["NIFTY"], "step": 50, "fyers": "NSE:NIFTY50-INDEX", "spot": 25660.0},
    "BANKNIFTY": {"syms": ["BANKNIFTY"], "step": 100, "fyers": "NSE:NIFTYBANK-INDEX", "spot": 53500.0},
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

use_fyers = st.sidebar.checkbox("Fetch Live Spot & Option Chain (Fyers)", value=False)
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
manual_spot = st.sidebar.number_input("Or Enter Simulated / Live Open Price", value=cfg["spot"], step=float(step))
skip_expired = st.sidebar.checkbox("Auto-Skip Expired Contracts (Post-Holiday Safe)", value=True)

st.header("2. Load 20–25 NSE (.zip) or BSE (.csv) UDiFF Bhavcopies")
mode = st.radio(
    "Choose Data Source",
    ["Upload Files Manually", "Auto-Load from GitHub Folder (./bhavcopy_data)"],
    horizontal=True,
)

files = []
if mode == "Upload Files Manually":
    uploaded = st.file_uploader(
        "Click Upload and select your NSE (.zip) or BSE (.csv) files",
        type=["zip", "csv"],
        accept_multiple_files=True,
    )
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
    else:
        st.warning("No files found in ./bhavcopy_data/.")

def read_file(f):
    f.seek(0)
    if f.name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
            csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csvs:
                return None
            with zf.open(next(iter(csvs))) as c:
                return pd.read_csv(c)
    return pd.read_csv(f)

def load_master_df(file_list, syms):
    frames = []
    for f in file_list[-25:]:
        try:
            df = read_file(f)
            if df is None:
                continue
            df.columns = df.columns.str.strip()
            if "TckrSymb" not in df.columns or "FinInstrmTp" not in df.columns:
                continue
            df["TckrSymb"] = df["TckrSymb"].astype(str).str.strip()
            df["FinInstrmTp"] = df["FinInstrmTp"].astype(str).str.strip()
            sub = df[(df["TckrSymb"].isin(syms)) & (df["FinInstrmTp"].isin(["IDO", "OPTIDX", "IO"]))].copy()
            if not sub.empty:
                frames.append(sub)
        except Exception as e:
            st.warning(f"Skipped {f.name}: {e}")
    if not frames:
        return None
    master = pd.concat(frames, ignore_index=True)
    master["TradDt"] = pd.to_datetime(master["TradDt"])
    master["XpryDt"] = pd.to_datetime(master["XpryDt"])
    master["OptnTp"] = master["OptnTp"].astype(str).str.strip()
    return master

def get_fyers_live_chain(cid, tok, sym):
    from fyers_apiv3 import fyersModel
    fyers = fyersModel.FyersModel(client_id=cid.strip(), token=tok.strip(), is_async=False)
    q_res = fyers.quotes(data={"symbols": sym})
    spot = None
    if q_res.get("s") == "ok" and q_res.get("d"):
        spot = next(iter(q_res["d"]))["v"]["lp"]
    oc_res = fyers.optionchain(data={"symbol": sym, "strikecount": 10, "timestamp": ""})
    chain_rows = oc_res.get("data", {}).get("optionsChain", []) if oc_res.get("s") == "ok" else []
    return spot, chain_rows

if files:
    master = load_master_df(files, cfg["syms"])
    if master is None or master.empty:
        st.error(f"No valid {idx} options data found.")
    else:
        latest_dt = master["TradDt"].max()
        avail_expiries = sorted(master[master["TradDt"] == latest_dt]["XpryDt"].unique())
        today_ts = pd.Timestamp(datetime.date.today())

        if skip_expired:
            active_expiries = [e for e in avail_expiries if e >= today_ts]
            if not active_expiries:
                active_expiries = avail_expiries
        else:
            active_expiries = avail_expiries

        exp_labels = [e.strftime("%d %b %Y") for e in active_expiries]
        chosen_label = st.selectbox("Select Active Contract Expiry", exp_labels)
        chosen_exp = active_expiries[exp_labels.index(chosen_label)]

        eod = master[(master["TradDt"] == latest_dt) & (master["XpryDt"] == chosen_exp)].copy()
        ce = eod[eod["OptnTp"] == "CE"].set_index("StrkPric")
        pe = eod[eod["OptnTp"] == "PE"].set_index("StrkPric")

        pcr = round(pe["OpnIntrst"].sum() / ce["OpnIntrst"].sum(), 2) if ce["OpnIntrst"].sum() > 0 else 0
        call_wall = ce["OpnIntrst"].idxmax()
        put_wall = pe["OpnIntrst"].idxmax()

        trapped_ce = ce[ce["ChngInOpnIntrst"] > ce["ChngInOpnIntrst"].quantile(0.75)].sort_values(by="OpnIntrst", ascending=False)
        trapped_strikes = trapped_ce.index.tolist()[:5]

        live_price = manual_spot
        live_chain = []
        if use_fyers and client_id and token:
            try:
                f_spot, live_chain = get_fyers_live_chain(client_id, token, cfg["fyers"])
                if f_spot:
                    live_price = f_spot
                    st.sidebar.success(f"Live {idx}: {live_price}")
            except Exception as e:
                st.sidebar.error(str(e))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latest EOD Bhavcopy", latest_dt.strftime("%d %b %Y"))
        c2.metric("Active Target Expiry", chosen_exp.strftime("%d %b %Y"))
        c3.metric("EOD Active PCR", pcr)
        c4.metric(f"{idx} Live / Open", live_price)

        st.divider()

        breached = [s for s in trapped_strikes if live_price > s]
        if breached:
            atm = round(live_price / step) * step
            eff_strike = int(atm - step)
            st.success(f"🚀 ACTIVE EXPIRY SHORT SQUEEZE ({idx}): Breached {breached}. Best Strike: {eff_strike} CE")
        else:
            st.info(f"No active trapped Call walls breached. Resistance: {int(call_wall)} CE | Support: {int(put_wall)} PE")

        cols = ["ClsPric", "OpnIntrst", "ChngInOpnIntrst"]
        left, right = st.columns(2)
        with left:
            st.subheader(f"EOD Trapped {idx} Call (CE) — {chosen_label}")
            st.dataframe(trapped_ce[cols].head(10))
        with right:
            st.subheader(f"EOD {idx} Put (PE) Support — {chosen_label}")
            st.dataframe(pe[cols].sort_values(by="OpnIntrst", ascending=False).head(10))

        if live_chain:
            st.divider()
            st.subheader(f"⚡ Live Fyers Intraday Option Chain OI Change ({idx})")
            lc_df = pd.DataFrame(live_chain)
            keep_cols = [c for c in ["strike_price", "option_type", "ltp", "oi", "oich", "volume"] if c in lc_df.columns]
            if keep_cols:
                st.dataframe(lc_df[keep_cols].sort_values(by="strike_price"))
else:
    st.info("👈 Upload your NSE (.zip) or BSE (.csv) files or add them to ./bhavcopy_data/ in GitHub.")
