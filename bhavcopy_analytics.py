import datetime
import io
import zipfile
import pandas as pd
import streamlit as st


def read_bhav_file(f):
    f.seek(0)
    if f.name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(f.read())) as zf:
            csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csvs:
                return None
            with zf.open(next(iter(csvs))) as c:
                return pd.read_csv(c)
    return pd.read_csv(f)


def parse_bhav_master(files, syms):
    frames = []
    for f in files[-25:]:
        try:
            df = read_bhav_file(f)
            if df is None:
                continue
            df.columns = df.columns.str.strip()
            if "TckrSymb" not in df.columns or "FinInstrmTp" not in df.columns:
                continue
            sub = df[
                (df["TckrSymb"].astype(str).str.strip().isin(syms))
                & (df["FinInstrmTp"].astype(str).str.strip().isin(["IDO", "OPTIDX", "IO"]))
            ].copy()
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


def get_active_expiries(master, latest_dt, skip_expired):
    exps = sorted(master[master["TradDt"] == latest_dt]["XpryDt"].unique())
    if skip_expired:
        active = [e for e in exps if e >= pd.Timestamp(datetime.date.today())]
        return active if active else exps
    return exps


def render_bhavcopy_section(master, idx, live_price, skip_expired):
    daily_oi = master.groupby(["TradDt", "OptnTp"])["OpnIntrst"].sum().unstack(fill_value=0)
    if "PE" in daily_oi.columns and "CE" in daily_oi.columns:
        daily_oi["PCR"] = (daily_oi["PE"] / daily_oi["CE"]).round(2)
        st.subheader(f"📈 {len(daily_oi)}-Day Rolling PCR History ({idx})")
        st.line_chart(daily_oi["PCR"])

    latest_dt = master["TradDt"].max()
    exps = get_active_expiries(master, latest_dt, skip_expired)
    chosen_exp = st.selectbox("Select Target Expiry", exps, format_func=lambda d: d.strftime("%d %b %Y"))
    exp_hist = master[master["XpryDt"] == chosen_exp].copy()
    latest_eod = exp_hist[exp_hist["TradDt"] == latest_dt]

    ce_hist = exp_hist[exp_hist["OptnTp"] == "CE"]
    pe_hist = exp_hist[exp_hist["OptnTp"] == "PE"]
    ce_latest = latest_eod[latest_eod["OptnTp"] == "CE"].set_index("StrkPric")
    pe_latest = latest_eod[latest_eod["OptnTp"] == "PE"].set_index("StrkPric")

    ce_sum = pd.DataFrame({
        "Latest_OI": ce_latest["OpnIntrst"],
        "MultiDay_Chg": ce_hist.groupby("StrkPric")["ChngInOpnIntrst"].sum(),
        "Latest_Cls": ce_latest["ClsPric"],
        "Avg_Prem": ce_hist.groupby("StrkPric")["ClsPric"].mean().round(2),
    }).dropna()
    ce_sum["Writer_BE"] = (ce_sum.index + ce_sum["Avg_Prem"]).round(1)
    ce_sum["Status"] = ce_sum["Writer_BE"].apply(lambda b: "🚨 UNDERWATER" if live_price > b else "✅ Safe")

    pe_sum = pd.DataFrame({
        "Latest_OI": pe_latest["OpnIntrst"],
        "MultiDay_Chg": pe_hist.groupby("StrkPric")["ChngInOpnIntrst"].sum(),
        "Latest_Cls": pe_latest["ClsPric"],
        "Avg_Prem": pe_hist.groupby("StrkPric")["ClsPric"].mean().round(2),
    }).dropna()
    pe_sum["Writer_BE"] = (pe_sum.index - pe_sum["Avg_Prem"]).round(1)
    pe_sum["Status"] = pe_sum["Writer_BE"].apply(lambda b: "🚨 UNDERWATER" if live_price < b else "✅ Safe")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"Call (CE) Multi-Day OI & Pain ({chosen_exp.strftime('%d %b')})")
        st.dataframe(ce_sum.sort_values(by="Latest_OI", ascending=False).head(12))
    with c2:
        st.subheader(f"Put (PE) Multi-Day OI & Pain ({chosen_exp.strftime('%d %b')})")
        st.dataframe(pe_sum.sort_values(by="Latest_OI", ascending=False).head(12))


def render_confluence_tab(master, ce_live, pe_live, idx, live_price, step, skip_expired, call_sq, put_sq):
    st.subheader(f"🎯 Master Confluence Signal ({idx} @ {live_price})")
    if master is None or ce_live.empty:
        st.info("Connect **Fyers Live** in the sidebar AND load **Bhavcopy files** above to see the Combined Confluence verdict.")
        return

    latest_dt = master["TradDt"].max()
    near_exp = next(iter(get_active_expiries(master, latest_dt, skip_expired)))
    exp_df = master[master["XpryDt"] == near_exp]

    ce_hist = exp_df[exp_df["OptnTp"] == "CE"]
    pe_hist = exp_df[exp_df["OptnTp"] == "PE"]

    ce_avg = ce_hist.groupby("StrkPric")["ClsPric"].mean()
    pe_avg = pe_hist.groupby("StrkPric")["ClsPric"].mean()

    uw_ce = [int(k) for k, prem in ce_avg.items() if live_price > (k + prem) and k in ce_live.index and ce_live.loc[k, "oich"] < 0]
    uw_pe = [int(k) for k, prem in pe_avg.items() if live_price < (k - prem) and k in pe_live.index and pe_live.loc[k, "oich"] < 0]

    atm = round(live_price / step) * step
    k1, k2, k3 = st.columns(3)
    k1.metric("Target Expiry", near_exp.strftime("%d %b %Y"))
    k2.metric("EOD + Live CE Traps", str(uw_ce) if uw_ce else "None")
    k3.metric("EOD + Live PE Traps", str(uw_pe) if uw_pe else "None")

    if uw_ce and call_sq:
        st.success(f"✅ **HIGH-CONVICTION BULLISH CONFLUENCE:** EOD Call writers at **{uw_ce}** are underwater AND unwinding live! Favor **{int(atm - step)} CE**.")
    elif uw_pe and put_sq:
        st.error(f"✅ **HIGH-CONVICTION BEARISH CONFLUENCE:** EOD Put writers at **{uw_pe}** are underwater AND unwinding live! Favor **{int(atm + step)} PE**.")
    else:
        st.warning("⚖️ **MIXED / NO FULL CONFLUENCE:** EOD writer breakevens and live unwinding are not aligned yet. Wait for confirmation.")
