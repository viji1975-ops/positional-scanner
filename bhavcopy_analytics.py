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


def render_live_institutional(lc_df, lot_size):
    st.divider()
    st.subheader(f"🏦 Live Institutional Footprint (Lot Size: {lot_size})")
    df = lc_df.copy()
    df["OI_Lots_Chg"] = (df["oich"] / lot_size).round(0)
    df["Total_Lots"] = (df["oi"] / lot_size).round(0)

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
        fii = p_df[p_df["Client Type"] == "FII"].iloc[0]
        pro = p_df[p_df["Client Type"] == "Pro"].iloc[0]
        cli = p_df[p_df["Client Type"] == "Client"].iloc[0]

        f_long, f_short = float(fii["Future Index Long"]), float(fii["Future Index Short"])
        fii_pct = round((f_long / (f_long + f_short)) * 100, 1)
        fii_net = int(f_long - f_short)
        pro_net = int(float(pro["Future Index Long"]) - float(pro["Future Index Short"]))
        cli_net = int(float(cli["Future Index Long"]) - float(cli["Future Index Short"]))

        st.subheader("🏛️ EOD Participant-Wise Institutional Positioning (FII / Pro / Client)")
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("FII Index Fut Long %", f"{fii_pct}%", help="<20% = Extreme Oversold | >75% = Overbought")
        p2.metric("FII Net Index Futures", f"{fii_net:+,}")
        p3.metric("Pro Desk Net Futures", f"{pro_net:+,}")
        p4.metric("Retail (Client) Net Futures", f"{cli_net:+,}")
    except Exception as e:
        st.warning(f"Could not parse Participant OI CSV: {e}")


def render_bhavcopy_section(master, idx, live_price, skip_expired, part_file=None):
    if part_file is not None:
        render_participant_eod(part_file)
        st.divider()

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

    eod_inst = latest_eod.copy()
    med_chg = eod_inst["ChngInOpnIntrst"].abs().median()
    eod_inst["OI_Surge_x"] = (eod_inst["ChngInOpnIntrst"].abs() / (med_chg if med_chg > 0 else 1)).round(1)
    spikes = eod_inst[eod_inst["OI_Surge_x"] >= 3.0].sort_values(by="OI_Surge_x", ascending=False)
    if not spikes.empty:
        st.subheader(f"🏦 EOD Institutional Block OI Surges (>= 3.0x Median) — {chosen_exp.strftime('%d %b')}")
        st.dataframe(spikes[["OptnTp", "StrkPric", "ClsPric", "OpnIntrst", "ChngInOpnIntrst", "OI_Surge_x"]].head(8))

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
    latest_eod = exp_df[exp_df["TradDt"] == latest_dt]

    ce_avg = exp_df[exp_df["OptnTp"] == "CE"].groupby("StrkPric")["ClsPric"].mean()
    pe_avg = exp_df[exp_df["OptnTp"] == "PE"].groupby("StrkPric")["ClsPric"].mean()

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

    # ==========================================
    # AUTOMATED TRADE ZONE & SUPPORT/RESISTANCE BOX
    # ==========================================
    st.divider()
    st.subheader("🧭 Automated Institutional Trade Zone & Invalidation Levels")

    # 1. Institutional Support Floor (Top Live PE Addition <= Spot, fallback to Max Live PE OI)
    pe_below = pe_live[pe_live.index <= live_price]
    if not pe_below.empty and pe_below["oich"].max() > 0:
        inst_floor = int(pe_below["oich"].idxmax())
    else:
        inst_floor = int(pe_live["oi"].idxmax())

    ce_above = ce_live[ce_live.index >= live_price]
    if not ce_above.empty and ce_above["oich"].max() > 0:
        live_ceiling = int(ce_above["oich"].idxmax())
    else:
        live_ceiling = int(ce_live["oi"].idxmax())

    eod_ce = latest_eod[(latest_eod["OptnTp"] == "CE") & (latest_eod["StrkPric"] >= live_price)]
    eod_mega_wall = int(eod_ce.set_index("StrkPric")["OpnIntrst"].idxmax()) if not eod_ce.empty else live_ceiling

    invalidation_low = int(inst_floor - (step * 0.4))
    breakout_trigger = int(live_ceiling + (step * 0.4))

    z1, z2, z3, z4 = st.columns(4)
    z1.metric("🛡️ Institutional Floor (Live PE)", f"{inst_floor}")
    z2.metric("🧱 Immediate Ceiling (Live CE)", f"{live_ceiling}")
    z3.metric("🏔️ EOD Positional Mega-Wall", f"{eod_mega_wall}")
    z4.metric("🛑 Bullish Invalidation SL", f"{invalidation_low}")

    st.info(
        f"**Actionable Zone Plan ({idx}):**\n"
        f"- **Buy-on-Dip Zone:** `{inst_floor}` to `{inst_floor + int(step * 0.4)}` (target `{live_ceiling - int(step * 0.2)}` – `{live_ceiling}`, strict SL below `{invalidation_low}`).\n"
        f"- **Profit-Booking / Ceiling Zone:** `{live_ceiling}` to `{eod_mega_wall}` (breakout trigger above `{breakout_trigger}` with negative Call `oich`)."
    )
def render_multi_index_radar(index_config, client_id, token):
    from fyers_apiv3 import fyersModel

    fyers = fyersModel.FyersModel(client_id=client_id.strip(), token=token.strip(), is_async=False)
    rows = []
    squeeze_count = 0

    with st.spinner("Scanning all 7 NSE & BSE indices for squeezes & institutional footprints..."):
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
                pe_lots = int(pe["lots_chg"].sum())
                ce_lots = int(ce["lots_chg"].sum())

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
                    sig = "⚖️ Range-Bound"
                    strike = "—"

                rows.append({
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
        if squeeze_count >= 3:
            st.success(f"🔥 SYNCHRONIZED MARKET BREAKOUT: {squeeze_count} of {len(rows)} indices are in an active institutional squeeze!")
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
    else:
        st.warning("Could not fetch multi-index quotes. Verify your Fyers Access Token.")
