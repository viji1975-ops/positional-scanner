import zipfile
import numpy as np
import pandas as pd


def load_fo_bhavcopy(file_obj):
    filename = getattr(file_obj, "name", str(file_obj))
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(file_obj) as z:
            csv_files = [f for f in z.namelist() if f.lower().endswith(".csv")]
            if not csv_files: return pd.DataFrame()
            with z.open(next(iter(csv_files))) as f: df = pd.read_csv(f, low_memory=False)
    else:
        df = pd.read_csv(file_obj, low_memory=False)

    df.columns = [c.strip().upper() for c in df.columns]

    if "TCKRSYMB" in df.columns:
        df["FININSTRMTP"] = df["FININSTRMTP"].astype(str).str.strip().str.upper()
        df = df[df["FININSTRMTP"].isin(["STF", "STO", "FUTSTK", "OPTSTK"])].copy()
        out = pd.DataFrame()
        out["INSTRUMENT"] = df["FININSTRMTP"].map({"STF": "FUTSTK", "FUTSTK": "FUTSTK", "STO": "OPTSTK", "OPTSTK": "OPTSTK"})
        out["SYMBOL"] = df["TCKRSYMB"].astype(str).str.strip()
        out["DATE"] = pd.to_datetime(df["TRADDT"], errors="coerce")
        out["EXPIRY"] = pd.to_datetime(df["XPRYDT"], errors="coerce")
        out["STRIKE"] = pd.to_numeric(df["STRKPRIC"], errors="coerce").fillna(0.0).astype(float)
        out["OPTION_TYP"] = df["OPTNTP"].fillna("XX").astype(str).str.strip().str.upper()
        out["CLOSE"] = pd.to_numeric(df["CLSPRIC"], errors="coerce").astype(float)
        out["HIGH"] = pd.to_numeric(df["HGHPRIC"] if "HGHPRIC" in df.columns else df["CLSPRIC"], errors="coerce").astype(float)
        out["LOW"] = pd.to_numeric(df["LWPRIC"] if "LWPRIC" in df.columns else df["CLSPRIC"], errors="coerce").astype(float)
        out["OPEN_INT"] = pd.to_numeric(df["OPNINTRST"], errors="coerce").fillna(0.0).astype(float)
        out["CHG_IN_OI"] = pd.to_numeric(df["CHNGINOPNINTRST"], errors="coerce").fillna(0.0).astype(float)
        vol_col = "TTLTRADGVOL" if "TTLTRADGVOL" in df.columns else ("TTLTRFVAL" if "TTLTRFVAL" in df.columns else None)
        out["VOLUME"] = pd.to_numeric(df[vol_col], errors="coerce").fillna(1.0).astype(float) if vol_col else 1.0
        return out.dropna(subset=["DATE", "EXPIRY", "CLOSE"])

    if "INSTRUMENT" in df.columns:
        df["INSTRUMENT"] = df["INSTRUMENT"].astype(str).str.strip().str.upper()
        df = df[df["INSTRUMENT"].isin(["FUTSTK", "OPTSTK"])].copy()
        out = pd.DataFrame()
        out["INSTRUMENT"] = df["INSTRUMENT"]
        out["SYMBOL"] = df["SYMBOL"].astype(str).str.strip()
        out["DATE"] = pd.to_datetime(df["TIMESTAMP"], errors="coerce")
        out["EXPIRY"] = pd.to_datetime(df["EXPIRY_DT"], errors="coerce")
        out["STRIKE"] = pd.to_numeric(df["STRIKE_PR"], errors="coerce").fillna(0.0).astype(float)
        out["OPTION_TYP"] = df["OPTION_TYP"].fillna("XX").astype(str).str.strip().str.upper()
        out["CLOSE"] = pd.to_numeric(df["CLOSE"], errors="coerce").astype(float)
        out["HIGH"] = pd.to_numeric(df["HIGH"] if "HIGH" in df.columns else df["CLOSE"], errors="coerce").astype(float)
        out["LOW"] = pd.to_numeric(df["LOW"] if "LOW" in df.columns else df["CLOSE"], errors="coerce").astype(float)
        out["OPEN_INT"] = pd.to_numeric(df["OPEN_INT"], errors="coerce").fillna(0.0).astype(float)
        out["CHG_IN_OI"] = pd.to_numeric(df["CHG_IN_OI"], errors="coerce").fillna(0.0).astype(float)
        out["VOLUME"] = pd.to_numeric(df["CONTRACTS"], errors="coerce").fillna(0.0).astype(float)
        return out.dropna(subset=["DATE", "EXPIRY", "CLOSE"])

    return pd.DataFrame()


def analyze_all_metrics(fut_row, sym_opts):
    chg, f_oi, spot = fut_row["1D_CHG_%"], fut_row["FUT_OI_CHG_%"], fut_row["CLOSE"]
    c3, oi3 = fut_row.get("3D_CHG_%", np.nan), fut_row.get("3D_OI_CHG_%", np.nan)
    if sym_opts.empty:
        return {"OI_SCORE": 0, "SENTIMENT": "NEUTRAL / SIDEWAYS", "TOP_CE": "None", "TOP_PE": "None", "ACTION": "NO SETUP", "STRIKE": "-", "PREM": 0.0, "SCORE": 0, "REASON": "No options", "PCR": 0.0, "MAX_PAIN": 0.0, "PUT_FLOOR": "-", "CALL_WALL": "-", "NET_PE_CHG": 0.0, "NET_CE_CHG": 0.0, "INST_BIAS": "NO DATA", "BREAKOUT_RADAR": "NO DATA", "BREAKOUT_LEVEL": "-", "RADAR_NOTES": "-"}

    ce, pe = sym_opts[sym_opts["OPTION_TYP"] == "CE"].copy(), sym_opts[sym_opts["OPTION_TYP"] == "PE"].copy()
    tot_ce, tot_pe = ce["OPEN_INT"].sum(), pe["OPEN_INT"].sum()
    pcr = round(tot_pe / tot_ce, 2) if tot_ce > 0 else 0.0
    net_ce, net_pe = float(ce["CHG_IN_OI"].sum()), float(pe["CHG_IN_OI"].sum())
    put_row = next(iter(pe.sort_values("OPEN_INT", ascending=False).to_dict("records")), None)
    call_row = next(iter(ce.sort_values("OPEN_INT", ascending=False).to_dict("records")), None)
    put_floor = f"{put_row['STRIKE']:g} PE" if put_row else "-"
    call_wall = f"{call_row['STRIKE']:g} CE" if call_row else "-"

    strikes = sorted(sym_opts["STRIKE"].unique())
    max_pain = float(next(iter(strikes), 0.0))
    if strikes:
        ce_g, pe_g = ce.groupby("STRIKE")["OPEN_INT"].sum(), pe.groupby("STRIKE")["OPEN_INT"].sum()
        best_p = None
        for s in strikes:
            loss = sum((s - k) * v for k, v in ce_g.items() if s > k) + sum((k - s) * v for k, v in pe_g.items() if s < k)
            if best_p is None or loss < best_p: best_p, max_pain = loss, float(s)

    if pcr >= 1.25 and net_pe > net_ce: bias = "🟢 STRONG BULLISH (Heavy Put Writing)"
    elif pcr >= 0.95 and net_pe > 0 and net_ce <= 0: bias = "🟢 BULLISH (Put Add + Call Unwind)"
    elif pcr <= 0.65 and net_ce > net_pe: bias = "🔴 STRONG BEARISH (Heavy Call Writing)"
    elif pcr <= 0.85 and net_ce > 0 and net_pe <= 0: bias = "🔴 BEARISH (Call Add + Put Unwind)"
    elif net_ce > 0 and net_pe > 0: bias = "🟡 RANGEBOUND (Short Strangle)"
    else: bias = "⚪ NEUTRAL / MIXED"

    ce["ABS_OI"], pe["ABS_OI"] = ce["CHG_IN_OI"].abs(), pe["CHG_IN_OI"].abs()
    t_ce, t_pe = ce.sort_values("ABS_OI", ascending=False).head(3), pe.sort_values("ABS_OI", ascending=False).head(3)
    ce_m, pe_m = {"Massive Windup": 2, "Windup": 1, "Massive Addition": -2, "Addition": -1}, {"Massive Addition": 2, "Addition": 1, "Massive Windup": -2, "Windup": -1}
    oi_sc = int(sum(ce_m.get(x, 0) for x in t_ce["OI_ACTION"]) + sum(pe_m.get(x, 0) for x in t_pe["OI_ACTION"]))
    ce_s = ", ".join([f"{int(r['STRIKE'])}CE ({r['OI_ACTION']})" for _, r in t_ce.iterrows() if r["OI_ACTION"] != "Neutral"]) or "Neutral"
    pe_s = ", ".join([f"{int(r['STRIKE'])}PE ({r['OI_ACTION']})" for _, r in t_pe.iterrows() if r["OI_ACTION"] != "Neutral"]) or "Neutral"

    sent = "NEUTRAL / SIDEWAYS"
    if pd.notna(chg):
        if chg > 0.5: sent = "STRONG BULLISH" if oi_sc >= 3 else ("BULLISH" if oi_sc >= 1 else ("REVERSAL WATCH" if oi_sc <= -2 else "NEUTRAL / SIDEWAYS"))
        elif chg < -0.5: sent = "STRONG BEARISH" if oi_sc <= -3 else ("BEARISH" if oi_sc <= -1 else ("REVERSAL WATCH" if oi_sc >= 2 else "NEUTRAL / SIDEWAYS"))
        elif abs(oi_sc) >= 3: sent = "REVERSAL WATCH"

    act, stk, prm, sc, rsn_str = "NO SETUP", "-", 0.0, 0, "Upload 2+ days"
    if pd.notna(chg):
        near = sym_opts[(sym_opts["STRIKE"] >= spot * 0.94) & (sym_opts["STRIKE"] <= spot * 1.06) & (sym_opts["VOLUME"] > 0)].copy()
        if abs(chg) > 5.5: act, rsn_str = "EXHAUSTED", f"Moved {chg:.1f}%"
        elif not near.empty:
            ce_n, pe_n = near[near["OPTION_TYP"] == "CE"].copy(), near[near["OPTION_TYP"] == "PE"].copy()
            ce_w, pe_a = ce_n[ce_n["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum(), pe_n[pe_n["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()
            pe_w, ce_a = pe_n[pe_n["CHG_IN_OI"] < 0]["CHG_IN_OI"].sum(), ce_n[ce_n["CHG_IN_OI"] > 0]["CHG_IN_OI"].sum()
            rsn = []
            if 0.4 <= chg <= 5.5: sc += 4 if (pd.notna(f_oi) and f_oi > 2) else 2; rsn.append(f"Fut Long (OI +{f_oi:.1f}%)" if (pd.notna(f_oi) and f_oi > 2) else f"Momentum +{chg:.1f}%")
            elif -5.5 <= chg <= -0.4: sc -= 4 if (pd.notna(f_oi) and f_oi > 2) else 2; rsn.append(f"Fut Short (OI +{f_oi:.1f}%)" if (pd.notna(f_oi) and f_oi > 2) else f"Momentum {chg:.1f}%")
            if abs(ce_w) > abs(ce_a) and abs(ce_w) > 0: sc += 2; rsn.append("CE Unwinding")
            if pe_a > abs(pe_w) and pe_a > 0: sc += 2; rsn.append("PE Support")
            if abs(pe_w) > abs(pe_a) and abs(pe_w) > 0: sc -= 2; rsn.append("PE Unwinding")
            if ce_a > abs(ce_w) and ce_a > 0: sc -= 2; rsn.append("CE Resistance")
            if sc >= 4 and not ce_n.empty:
                tr = ce_n[ce_n["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI"); ce_n["D"] = (ce_n["STRIKE"] - spot).abs()
                br = next(iter((tr if not tr.empty else ce_n.sort_values("D")).to_dict("records")))
                act, stk, prm, rsn_str = "🟢 BUY CALL (CE)", f"{br['STRIKE']:g} CE", float(br["CLOSE"]), " + ".join(rsn)
            elif sc <= -4 and not pe_n.empty:
                tr = pe_n[pe_n["CHG_IN_OI"] < 0].sort_values("CHG_IN_OI"); pe_n["D"] = (pe_n["STRIKE"] - spot).abs()
                br = next(iter((tr if not tr.empty else pe_n.sort_values("D")).to_dict("records")))
                act, stk, prm, rsn_str = "🔴 BUY PUT (PE)", f"{br['STRIKE']:g} PE", float(br["CLOSE"]), " + ".join(rsn)
            else: act, rsn_str = "NEUTRAL / WAIT", "No clear edge"

    radar, b_lvl, r_notes = "⚪ NO COIL", "-", []
    c_strike = call_row["STRIKE"] if call_row else 0.0
    p_strike = put_row["STRIKE"] if put_row else 0.0
    if c_strike > 0 and 0 <= (c_strike - spot) / spot <= 0.025 and (net_pe > 0 or oi_sc >= 2):
        radar, b_lvl = "🚀 IMMINENT UPSIDE BREAKOUT", f"Above {c_strike:g}"
        r_notes.append(f"Spot within {((c_strike-spot)/spot)*100:.1f}% of {c_strike:g} Call Wall + Put Support")
    elif p_strike > 0 and 0 <= (spot - p_strike) / spot <= 0.025 and (net_ce > 0 or oi_sc <= -2):
        radar, b_lvl = "🔻 IMMINENT DOWNSIDE BREAKDOWN", f"Below {p_strike:g}"
        r_notes.append(f"Spot within {((spot-p_strike)/spot)*100:.1f}% of {p_strike:g} Put Floor + Call Resistance")
    if pd.notna(c3) and pd.notna(oi3) and c3 >= 1.5 and oi3 >= 5.0:
