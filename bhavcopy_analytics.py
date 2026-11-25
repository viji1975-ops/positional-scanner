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


def get_active_expiries(master, ref_dt, skip_expired):
    exps = sorted(master[master["TradDt"] == ref_dt]["XpryDt"].unique())
    if skip_expired:
        active = [e for e in exps if e >= ref_dt]
        return active if active else exps
    return exps


def render_live_institutional(lc_df, lot_size):
    st.divider()
    st.subheader(f"🏦 Live Institutional Footprint (Lot Size: {lot_size})")
    df = lc_df.copy()
    df["OI_Lots_Chg"] = (df["oich"] / lot_size).round(0)
    pe_lots = int(df[df["option_type"] == "PE"]["OI_Lots_Chg"].sum())
    ce_lots = int(df[df["option_type"] == "CE"]["OI_Lots_Chg"].sum())

    if pe_lots > ce_lots * 1.25:
        bias = "🟢 INSTITUTIONAL BULLISH (Heavy Put Writing)"
    elif ce_lots > pe_lots * 1.25:
        bias = "🔴 INSTITUTIONAL BEARISH (Heavy Call Writing)"
    else:
        bias = "🟡 NEUTRAL / STRADDLE WRITING"

    i1, i2, i3 = st.columns(3)
    i1.metric("Smart Money Intraday Bias", bias)
    i2.metric("Net Put (PE) Lots Added", f"{pe_lots:+,}")
    i3.metric("Net Call (CE) Lots Added", f"{ce_lots:+,}")

    inst_walls = df[df["OI_Lots_Chg"] >= 2500].sort_values(by="OI_Lots_Chg", ascending=False)
    inst_unwind = df[df["OI_Lots_Chg"] <= -2500].sort_values(by="OI_Lots_Chg")

    w1, w2 = st.columns(2)
    with w1:
        st.caption("🧱 Institutional Writing Walls (+2,500 Lots Added)")
        st.dataframe(inst_walls[["strike_price", "option_type", "ltp", "OI_Lots_Chg", "volume"]] if not inst_walls.empty else pd.DataFrame())
    with w2:
        st.caption("🏃 Institutional Short Covering (-2,500 Lots Unwound)")
        st.dataframe(inst_unwind[["strike_price", "option_type", "ltp", "OI_Lots_Chg", "volume"]] if not inst_unwind.empty else pd.DataFrame())


def render_participant_eod(part_file):
    try:
        part_file.seek(0)
        p_df = pd.read_csv(part_file, skiprows=1)
        p_df.columns = p_df.columns.str.strip()
        p_df["Client Type"] = p_df["Client Type"].astype(str).str.strip()
        fii = p_df[p_df["Client Type"] == "FII"].iloc
        pro = p_df[p_df["Client Type"] == "Pro"].iloc
        cli = p_df[p_df["Client Type"] == "Client"].iloc

        f_long, f_short = float(fii["Future Index Long"]), float(fii["Future Index Short"])
        fii_pct = round((f_long / (f_long + f_short)) * 100, 1)
        fii_net = int(f_long - f_short)
        pro_net = int(float(pro["Future Index Long"]) - float(pro["Future Index Short"]))
        cli_net = int(float(cli["Future Index Long"]) - float(cli["Future Index Short"]))

        st.subheader("🏛️ EOD Participant-Wise Institutional Positioning (FII / Pro / Client)")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("FII Index Fut Long %", f"{fii_pct}%")
        p2.metric("FII Net Index Futures", f"{fii_net:+,}")
        p3.metric("Pro Desk Net Futures", f"{pro_net:+,}")
        p4.metric("Retail (Client) Net Futures", f"{cli_net:+,}")
    except Exception as e:
        st.warning(f"Could not parse Participant OI CSV: {e}")


def render_bhavcopy_section(master, idx, live_price, skip_expired, part_file=None):
    if part_file is not None:
        render_participant_eod(part_file)
        st.divider()

    # EOD Backtest Date Selector (Rewind to any Bhavcopy date)
    avail_dates = sorted(master["TradDt"].unique(), reverse=True)
    c_dt, c_info = st.columns(2)
    with c_dt:
        ref_dt = st.selectbox(
            "⏮️ Select EOD Analysis / Backtest Date",
            avail_dates,
            format_func=lambda d: d.strftime("%d %b %Y") + (" (Latest)" if d == avail_dates else " (Backtest)"),
        )

    hist_upto_dt = master[master["TradDt"] <= ref_dt].copy()
    future_dates = sorted([d for d in avail_dates if d > ref_dt])
    next_dt = next(iter(future_dates)) if future_dates else None

    with c_info:
        if next_dt is not None:
            st.info(f"🧪 **Backtest Mode Active:** Viewing EOD data as of **{ref_dt.strftime('%d %b %Y')}** and verifying outcome on **{next_dt.strftime('%d %b %Y')}**.")
        else:
            st.success(f"📅 **Latest EOD Mode:** Analyzing **{ref_dt.strftime('%d %b %Y')}** against Live Spot (**{live_price}**).")

    daily_oi = hist_upto_dt.groupby(["TradDt", "OptnTp"])["OpnIntrst"].sum().unstack(fill_value=0)
    if "PE" in daily_oi.columns and "CE" in daily_oi.columns:
        daily_oi["PCR"] = (daily_oi["PE"] / daily_oi["CE"]).round(2)
        st.subheader(f"📈 {len(daily_oi)}-Day Rolling PCR History up to {ref_dt.strftime('%d %b')} ({idx})")
        st.line_chart(daily_oi["PCR"])

    exps = get_active_expiries(hist_upto_dt, ref_dt, skip_expired)
    chosen_exp = st.selectbox("Select Target Expiry", exps, format_func=lambda d: d.strftime("%d %b %Y"))
    exp_hist = hist_upto_dt[hist_upto_dt["XpryDt"] == chosen_exp].copy()
    ref_eod = exp_hist[exp_hist["TradDt"] == ref_dt]

    eval_price = live_price
    if next_dt is not None and "UndrlygPric" in master.columns:
        nxt_vals = master[(master["TradDt"] == next_dt) & (master["XpryDt"] == chosen_exp)]["UndrlygPric"].dropna()
        if not nxt_vals.empty:
            eval_price = float(next(iter(nxt_vals)))
    
    med_chg = ref_eod["ChngInOpnIntrst"].abs().median()
    eod_inst = ref_eod.copy()
    eod_inst["OI_Surge_x"] = (eod_inst["ChngInOpnIntrst"].abs() / (med_chg if med_chg > 0 else 1)).round(1)
    spikes = eod_inst[eod_inst["OI_Surge_x"] >= 3.0].sort_values(by="OI_Surge_x", ascending=False)
    if not spikes.empty:
        st.subheader(f"🏦 EOD Institutional Block OI Surges (>= 3.0x Median) — {ref_dt.strftime('%d %b')}")
        st.dataframe(spikes[["OptnTp", "StrkPric", "ClsPric", "OpnIntrst", "ChngInOpnIntrst", "OI_Surge_x"]].head(8))

    ce_hist = exp_hist[exp_hist["OptnTp"] == "CE"]
    pe_hist = exp_hist[exp_hist["OptnTp"] == "PE"]
    ce_ref = ref_eod[ref_eod["OptnTp"] == "CE"].set_index("StrkPric")
    pe_ref = ref_eod[ref_eod["OptnTp"] == "PE"].set_index("StrkPric")

    status_label = f"NextDay_({next_dt.strftime('%d-%b')})" if next_dt else "Live_Status"

    ce_sum = pd.DataFrame({
        "EOD_OI": ce_ref["OpnIntrst"],
        "MultiDay_Chg": ce_hist.groupby("StrkPric")["ChngInOpnIntrst"].sum(),
        "EOD_Cls": ce_ref["ClsPric"],
        "Avg_Prem": ce_hist.groupby("StrkPric")["ClsPric"].mean().round(2),
    }).dropna()
    ce_sum["Writer_BE"] = (ce_sum.index + ce_sum["Avg_Prem"]).round(1)
    ce_sum[status_label] = ce_sum["Writer_BE"].apply(lambda b: f"🚨 SQUEEZED (@{eval_price})" if eval_price > b else "✅ Safe")

    pe_sum = pd.DataFrame({
        "EOD_OI": pe_ref["OpnIntrst"],
        "MultiDay_Chg": pe_hist.groupby("StrkPric")["ChngInOpnIntrst"].sum(),
        "EOD_Cls": pe_ref["ClsPric"],
        "Avg_Prem": pe_hist.groupby("StrkPric")["ClsPric"].mean().round(2),
    }).dropna()
    pe_sum["Writer_BE"] = (pe_sum.index - pe_sum["Avg_Prem"]).round(1)
    pe_sum[status_label] = pe_sum["Writer_BE"].apply(lambda b: f"🚨 SQUEEZED (@{eval_price})" if eval_price < b else "✅ Safe")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"Call (CE) {ref_dt.strftime('%d %b')} EOD OI & Pain (Exp: {chosen_exp.strftime('%d %b')})")
        st.dataframe(ce_sum.sort_values(by="EOD_OI", ascending=False).head(12))
    with c2:
        st.subheader(f"Put (PE) {ref_dt.strftime('%d %b')} EOD OI & Pain (Exp: {chosen_exp.strftime('%d %b')})")
        st.dataframe(pe_sum.sort_values(by="EOD_OI", ascending=False).head(12))
    
def render_confluence_tab(master, ce_live, pe_live, idx, live_price, step, skip_expired, call_sq, put_sq):
    st.subheader(f"🎯 Master Confluence Signal ({idx} @ {live_price})")
    if master is None or ce_live.empty:
        st.info("Connect **Fyers Live** in the sidebar AND load **Bhavcopy files** above to see the Combined Confluence verdict.")
        return

    latest_dt = master["TradDt"].max()
    near_exp = next(iter(get_active_expiries(master, latest_dt, skip_expired)))
    exp_df = master[master["XpryDt"] == near_exp]
    latest_eod = exp_df[exp_df["TradDt"] == latest_dt]

    ce_avg = exp_df[exp_df["OptnTp"] == "CE"].groupby("StrkPric")["ClsPric"].mean()
    pe_avg = exp_df[exp_df["OptnTp"] == "PE"].groupby("StrkPric")["ClsPric"].mean()

    uw_ce = [int(k) for k, prem in ce_avg.items() if live_price > (k + prem) and k in ce_live.index and ce_live.loc[k, "oich"] < 0]
    uw_pe = [int(k) for k, prem in pe_avg.items() if live_price < (k - prem) and k in pe_live.index and pe_live.loc[k, "oich"] < 0]

    atm = round(live_price / step) * step
    k1, k2, k3 = st.columns(3)
def render_multi_index_radar(index_config, client_id, token):
    from fyers_apiv3 import fyersModel

    if "radar_snapshots" not in st.session_state:
        st.session_state["radar_snapshots"] = {}

    slots = ["Live Now", "09:30 AM", "10:30 AM", "11:00 AM", "11:30 AM", "01:30 PM", "02:30 PM"]
    c_slot, c_btn, c_view = st.columns(3)
    with c_slot:
        chosen_slot = st.selectbox("Select Time Slot to Capture / View", slots)
    with c_btn:
        st.write("")
        scan_clicked = st.button("📡 Scan & Save Selected Slot", use_container_width=True)
    with c_view:
        saved_keys = list(st.session_state["radar_snapshots"].keys())
        view_slot = st.selectbox("Compare Saved Time Slot", saved_keys if saved_keys else ["No snapshots saved yet"])

    if scan_clicked:
        fyers = fyersModel.FyersModel(client_id=client_id.strip(), token=token.strip(), is_async=False)
        rows = []
        squeeze_count = 0
        with st.spinner(f"Scanning all 7 indices for {chosen_slot}..."):
            for name, cfg in index_config.items():
                try:
                    q_res = fyers.quotes(data={"symbols": cfg["fyers"]})
                    spot = next(iter(q_res["d"]))["v"]["lp"] if q_res.get("s") == "ok" and q_res.get("d") else None
                    oc_res = fyers.optionchain(data={"symbol": cfg["fyers"], "strikecount": 10, "timestamp": ""})
                    chain = oc_res.get("data", {}).get("optionsChain", []) if oc_res.get("s") == "ok" else []
                    if not spot or not chain:
                        continue

                    df = pd.DataFrame(chain)
                    df = df[df["option_type"].isin(["CE", "PE"])].copy()
                    df["prev_oi"] = df["oi"] - df["oich"]
                    df["lots_chg"] = (df["oich"] / cfg["lot"]).round(0)

                    ce = df[df["option_type"] == "CE"].set_index("strike_price")
                    pe = df[df["option_type"] == "PE"].set_index("strike_price")

                    pcr = round(pe["oi"].sum() / ce["oi"].sum(), 2) if ce["oi"].sum() > 0 else 0
                    pe_lots, ce_lots = int(pe["lots_chg"].sum()), int(ce["lots_chg"].sum())

                    if pe_lots > ce_lots * 1.25:
                        bias = f"🟢 Bullish ({pe_lots - ce_lots:+,} net lots)"
                    elif ce_lots > pe_lots * 1.25:
                        bias = f"🔴 Bearish ({ce_lots - pe_lots:+,} net lots)"
                    else:
                        bias = "🟡 Neutral / Straddle"

                    trap_ce = ce[(ce["prev_oi"] > ce["prev_oi"].median()) & (ce.index < spot) & (ce["oich"] < 0)]
                    trap_pe = pe[(pe["prev_oi"] > pe["prev_oi"].median()) & (pe.index > spot) & (pe["oich"] < 0)]

                    atm = round(spot / cfg["step"]) * cfg["step"]
                    if not trap_ce.empty:
                        sig = f"🚀 CALL SQUEEZE ({trap_ce.index.tolist()[:2]})"
                        strike = f"{int(atm - cfg['step'])} CE"
                        squeeze_count += 1
                    elif not trap_pe.empty and pcr < 0.85:
                        sig = f"🔻 PUT SQUEEZE ({trap_pe.index.tolist()[:2]})"
                        strike = f"{int(atm + cfg['step'])} PE"
                        squeeze_count += 1
                    else:
                        sig, strike = "⚖️ Range-Bound", "—"

                    rows.append({
                        "Time Slot": chosen_slot,
                        "Index": name,
                        "Live Spot": spot,
                        "PCR": pcr,
                        "Institutional Footprint": bias,
                        "Squeeze Signal": sig,
                        "Best Strike": strike,
                    })
                except Exception:
                    pass

        if rows:
            st.session_state["radar_snapshots"][chosen_slot] = (pd.DataFrame(rows), squeeze_count)
            view_slot = chosen_slot

    if view_slot in st.session_state["radar_snapshots"]:
        snap_df, sq_cnt = st.session_state["radar_snapshots"][view_slot]
        if sq_cnt >= 3:
            st.success(f"🔥 SYNCHRONIZED MARKET BREAKOUT ({view_slot}): {sq_cnt} of {len(snap_df)} indices in active squeeze!")
        st.dataframe(snap_df, use_container_width=True)

        all_snaps = pd.concat([next(iter(v)) for v in st.session_state["radar_snapshots"].values()], ignore_index=True)
        st.download_button(
            "📥 Export All Saved Time-Slot Snapshots (CSV)",
            data=all_snaps.to_csv(index=False).encode("utf-8"),
            file_name=f"multi_index_snapshots_{datetime.date.today()}.csv",
            mime="text/csv",
        )
def render_eod_vs_live_blocks(master, ce_live, pe_live, live_price, lot_size, skip_expired):
    if master is None or ce_live.empty:
        return

    latest_dt = master["TradDt"].max()
    near_exp = next(iter(get_active_expiries(master, latest_dt, skip_expired)))
    eod = master[(master["TradDt"] == latest_dt) & (master["XpryDt"] == near_exp)].copy()
    if eod.empty:
        return

    med_chg = eod["ChngInOpnIntrst"].abs().median()
    eod["Surge_x"] = (eod["ChngInOpnIntrst"].abs() / (med_chg if med_chg > 0 else 1)).round(1)
    blocks = eod[(eod["Surge_x"] >= 3.0) & (eod["ChngInOpnIntrst"] > 0)].sort_values(by="Surge_x", ascending=False)
    if blocks.empty:
        return

    st.divider()
    st.subheader(f"🧱 EOD Institutional Blocks vs. Live Market ({latest_dt.strftime('%d %b')} EOD → Exp: {near_exp.strftime('%d %b')})")

    trapped_rows, ceiling_rows = [], []
    for _, r in blocks.iterrows():
        strike = float(r["StrkPric"])
        opt = str(r["OptnTp"]).strip()
        surge = r["Surge_x"]
        live_tbl = ce_live if opt == "CE" else pe_live
        live_lots = int(round(live_tbl.loc[strike, "oich"] / lot_size)) if strike in live_tbl.index else 0

        if opt == "CE" and strike < live_price:
            status = "🏃 TRAPPED & UNWINDING (Fuel)" if live_lots < 0 else "⚠️ Breached (Holding)"
            trapped_rows.append({"Strike": f"{int(strike)} CE", "EOD Surge": f"{surge}x", "Live Lots Chg": f"{live_lots:+,}", "Status": status})
        elif opt == "CE" and strike >= live_price:
            status = "🛡️ DEFENDING CEILING (Book Profit)" if live_lots >= 0 else "🚀 BREAKING OUT (Unwinding)"
            ceiling_rows.append({"Strike": f"{int(strike)} CE", "EOD Surge": f"{surge}x", "Live Lots Chg": f"{live_lots:+,}", "Status": status})
        elif opt == "PE" and strike > live_price:
            status = "🏃 TRAPPED & UNWINDING (Drop Fuel)" if live_lots < 0 else "⚠️ Breached (Holding)"
            trapped_rows.append({"Strike": f"{int(strike)} PE", "EOD Surge": f"{surge}x", "Live Lots Chg": f"{live_lots:+,}", "Status": status})
        elif opt == "PE" and strike <= live_price:
            status = "🛡️ DEFENDING FLOOR (Buy Support)" if live_lots >= 0 else "🔻 BREAKING DOWN (Unwinding)"
            ceiling_rows.append({"Strike": f"{int(strike)} PE", "EOD Surge": f"{surge}x", "Live Lots Chg": f"{live_lots:+,}", "Status": status})

    b1, b2 = st.columns(2)
    with b1:
        st.caption("🔥 Trapped EOD Blocks (Crossed by Live Spot)")
        st.dataframe(pd.DataFrame(trapped_rows) if trapped_rows else pd.DataFrame(), use_container_width=True)
    with b2:
        st.caption("🚧 Active EOD Walls (Overhead Ceilings & Support Floors)")
        st.dataframe(pd.DataFrame(ceiling_rows) if ceiling_rows else pd.DataFrame(), use_container_width=True)
