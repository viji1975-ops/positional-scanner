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


def render_bhavcopy_section(files, syms, idx, live_price, skip_expired):
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
        st.error(f"No valid {idx} options data found in uploaded files.")
        return

    master = pd.concat(frames, ignore_index=True)
    master["TradDt"] = pd.to_datetime(master["TradDt"])
    master["XpryDt"] = pd.to_datetime(master["XpryDt"])
    master["OptnTp"] = master["OptnTp"].astype(str).str.strip()

    # 1. 20-25 Day Rolling PCR History Chart
    daily_oi = master.groupby(["TradDt", "OptnTp"])["OpnIntrst"].sum().unstack(fill_value=0)
    if "PE" in daily_oi.columns and "CE" in daily_oi.columns:
        daily_oi["PCR"] = (daily_oi["PE"] / daily_oi["CE"]).round(2)
        st.subheader(f"📈 {len(daily_oi)}-Day Rolling PCR History ({idx})")
        st.line_chart(daily_oi["PCR"])

    # 2. Target Expiry Selection
    latest_dt = master["TradDt"].max()
    exps = sorted(master[master["TradDt"] == latest_dt]["XpryDt"].unique())
    if skip_expired:
        active = [e for e in exps if e >= pd.Timestamp(datetime.date.today())]
        exps = active if active else exps

    chosen_exp = st.selectbox(
        "Select Target Expiry for Multi-Day OI & Writer Breakeven",
        exps,
        format_func=lambda d: d.strftime("%d %b %Y"),
    )
    exp_hist = master[master["XpryDt"] == chosen_exp].copy()
    latest_eod = exp_hist[exp_hist["TradDt"] == latest_dt]

    # 3. Cumulative Multi-Day OI Change & Writer Breakeven Pain Levels
    ce_hist = exp_hist[exp_hist["OptnTp"] == "CE"]
    pe_hist = exp_hist[exp_hist["OptnTp"] == "PE"]

    ce_latest = latest_eod[latest_eod["OptnTp"] == "CE"].set_index("StrkPric")
    pe_latest = latest_eod[latest_eod["OptnTp"] == "PE"].set_index("StrkPric")

    ce_summary = pd.DataFrame({
        "Latest_OI": ce_latest["OpnIntrst"],
        "MultiDay_OI_Chg": ce_hist.groupby("StrkPric")["ChngInOpnIntrst"].sum(),
        "Latest_Cls": ce_latest["ClsPric"],
        "Avg_Prem": ce_hist.groupby("StrkPric")["ClsPric"].mean().round(2),
    }).dropna()
    ce_summary["Writer_BE"] = (ce_summary.index + ce_summary["Avg_Prem"]).round(1)
    ce_summary["Live_Status"] = ce_summary["Writer_BE"].apply(
        lambda be: "🚨 UNDERWATER" if live_price > be else "✅ Safe"
    )

    pe_summary = pd.DataFrame({
        "Latest_OI": pe_latest["OpnIntrst"],
        "MultiDay_OI_Chg": pe_hist.groupby("StrkPric")["ChngInOpnIntrst"].sum(),
        "Latest_Cls": pe_latest["ClsPric"],
        "Avg_Prem": pe_hist.groupby("StrkPric")["ClsPric"].mean().round(2),
    }).dropna()
    pe_summary["Writer_BE"] = (pe_summary.index - pe_summary["Avg_Prem"]).round(1)
    pe_summary["Live_Status"] = pe_summary["Writer_BE"].apply(
        lambda be: "🚨 UNDERWATER" if live_price < be else "✅ Safe"
    )

    b_left, b_right = st.columns(2)
    with b_left:
        st.subheader(f"Call (CE) Multi-Day OI & Writer Pain ({chosen_exp.strftime('%d %b')})")
        st.dataframe(ce_summary.sort_values(by="Latest_OI", ascending=False).head(12))
    with b_right:
        st.subheader(f"Put (PE) Multi-Day OI & Writer Pain ({chosen_exp.strftime('%d %b')})")
        st.dataframe(pe_summary.sort_values(by="Latest_OI", ascending=False).head(12))
