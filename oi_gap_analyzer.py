import io
import urllib.parse
import zipfile
import pandas as pd
import streamlit as st

st.set_page_config(page_title="NSE/BSE OI & Gap Scanner", layout="wide")
st.title("📊 NSE & BSE Bhavcopy OI + Fyers Live Gap Scanner")

INDEX_CONFIG = {
    "NIFTY": {"syms": ["NIFTY"], "step": 50, "fyers": "NSE:NIFTY50-INDEX", "spot": 25900.0},
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

use_fyers = st.sidebar.checkbox("Fetch Live Spot from Fyers API", value=False)
client_id = st.sidebar.text_input("Fyers App ID (Client ID)", placeholder="e.g. XC4XXXXM-100")

with st.sidebar.expander("🔑 Generate Today's Fyers Access Token"):
    secret_id = st.text_input("Fyers Secret ID", type="password")
    redir_uri = st.text_input("Redirect URI", value="https://fyers.in")
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
                q = urllib.parse.parse_qs(urllib.parse.urlparse(redir_url.strip()).query)
                code = q.get("auth_code", [redir_url.strip()])[0]
                sess.set_token(code)
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

st.header("2. Upload 20–25 NSE (.zip) or BSE (.csv) UDiFF Bhavcopies")
files = st.file_uploader("Upload NSE (.zip) or BSE (.csv) files", type=["zip", "csv"], accept_multiple_files=True)

def read_file(f):
    f.seek(0)
    if f.name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
            csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csvs:
                return None
            with zf.open(csvs[0]) as c:
                return pd.read_csv(c)
    return pd.read_csv(f)

def process_files(file_list, syms):
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
        return None, None, None
    master = pd.concat(frames, ignore_index=True)
    master["TradDt"] = pd.to_datetime(master["TradDt"])
    master["XpryDt"] = pd.to_datetime(master["XpryDt"])
    master["OptnTp"] = master["OptnTp"].astype(str).str.strip()
    latest_dt = master["TradDt"].max()
    near_exp = master[master["TradDt"] == latest_dt]["XpryDt"].min()
    return master[master["XpryDt"] == near_exp].sort_values("TradDt"), latest_dt, near_exp

def get_fyers_spot(cid, tok, sym):
    from fyers_apiv3 import fyersModel
    fyers = fyersModel.FyersModel(client_id=cid.strip(), token=tok.strip(), is_async=False)
    res = fyers.quotes(data={"symbols": sym})
    if res.get("s") == "ok" and res.get("d"):
        return res["d"][0]["v"]["lp"]
    raise Exception(f"Fyers Error: {res}")

if files:
    exp_df, latest_dt, near_exp = process_files(files, cfg["syms"])
    if exp_df is None or exp_df.empty:
        st.error(f"No valid {idx} options data found. Check exchange file match.")
    else:
        eod = exp_df[exp_df["TradDt"] == latest_dt].copy()
        ce = eod[eod["OptnTp"] == "CE"].set_index("StrkPric")
        pe = eod[eod["OptnTp"] == "PE"].set_index("StrkPric")

        pcr = round(pe["OpnIntrst"].sum() / ce["OpnIntrst"].sum(), 2) if ce["OpnIntrst"].sum() > 0 else 0
        call_wall = ce["OpnIntrst"].idxmax()
        put_wall = pe["OpnIntrst"].idxmax()

        trapped_ce = ce[ce["ChngInOpnIntrst"] > ce["ChngInOpnIntrst"].quantile(0.75)].sort_values(by="OpnIntrst", ascending=False)
        trapped_strikes = trapped_ce.index.tolist()[:5]

        live_price = manual_spot
        if use_fyers and client_id and token:
            try:
                live_price = get_fyers_spot(client_id, token, cfg["fyers"])
                st.sidebar.success(f"Live {idx}: {live_price}")
            except Exception as e:
                st.sidebar.error(str(e))

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Latest EOD", latest_dt.strftime("%d %b %Y"))
        c2.metric("Nearest Expiry", near_exp.strftime("%d %b %Y"))
        c3.metric("EOD PCR", pcr)
        c4.metric(f"{idx} Open / Live", live_price)

        st.divider()

        breached = [s for s in trapped_strikes if live_price > s]
        if breached:
            atm = round(live_price / step) * step
            eff_strike = int(atm - step)
            st.success(f"🚀 SHORT SQUEEZE ({idx}): Breached {breached}. Best Strike: {eff_strike} CE")
        else:
            st.info(f"No trapped Call walls breached. Resistance: {int(call_wall)} CE | Support: {int(put_wall)} PE")

        cols = ["ClsPric", "OpnIntrst", "ChngInOpnIntrst"]
        left, right = st.columns(2)
        with left:
            st.subheader(f"Top Trapped {idx} Call (CE) Strikes")
            st.dataframe(trapped_ce[cols].head(10))
        with right:
            st.subheader(f"Top {idx} Put (PE) Support Strikes")
            st.dataframe(pe[cols].sort_values(by="OpnIntrst", ascending=False).head(10))
else:
    st.info("👈 Upload your NSE (.zip) or BSE (.csv) Bhavcopy files above to begin.")
