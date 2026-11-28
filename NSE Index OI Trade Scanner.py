import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title='NSE Index OI Trade Scanner', layout='wide')
st.title('📈 Institutional Index Options OI Scanner (All Formats)')
st.markdown(
    'Supports **Index Sentiment Reports** AND **Raw Option Chain CSVs** '
    '(NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY).'
)


def parse_signals(signal_str):
  if pd.isna(signal_str) or not str(signal_str).strip() or str(signal_str).strip() == 'Neutral':
    return []
  pattern = r'(\d+(?:\.\d+)?)(CE|PE)\s*\(([^)]+)\)'
  matches = re.findall(pattern, str(signal_str))
  return [(float(strike), opt, act.strip()) for strike, opt, act in matches]


def detect_index_inst_move(direction, oi_score, chg_1d, ce_signals, pe_signals):
  m_ce_add = sum(1 for _, _, a in ce_signals if 'Massive Addition' in a)
  m_ce_wind = sum(1 for _, _, a in ce_signals if 'Massive Windup' in a)
  m_pe_add = sum(1 for _, _, a in pe_signals if 'Massive Addition' in a)
  m_pe_wind = sum(1 for _, _, a in pe_signals if 'Massive Windup' in a)

  pts, tags = 0, []
  if direction == 'BULLISH':
    if m_pe_add >= 2:
      pts += 2
      tags.append(f'{m_pe_add}x Massive PE Floor')
    elif m_pe_add == 1:
      pts += 1
      tags.append('1x Massive PE Floor')
    if m_ce_wind >= 1:
      pts += 2
      tags.append(f'{m_ce_wind}x Massive CE Squeeze')
    if oi_score >= 3 and chg_1d >= 0.75:
      pts += 2
      tags.append('OI + Index Surge')
  elif direction == 'BEARISH':
    if m_ce_add >= 2:
      pts += 2
      tags.append(f'{m_ce_add}x Massive CE Wall')
    elif m_ce_add == 1:
      pts += 1
      tags.append('1x Massive CE Wall')
    if m_pe_wind >= 1:
      pts += 2
      tags.append(f'{m_pe_wind}x Massive PE Breakdown')
    if oi_score <= -3 and chg_1d <= -0.50:
      pts += 2
      tags.append('OI + Index Drop')

  if pts >= 3:
    return f"🔥 HEAVY INST. ({', '.join(tags)})", pts
  elif pts >= 1:
    return f"⚡ MODERATE INST. ({', '.join(tags)})", pts
  return '⚠️ WEAK / RANGEBOUND', 0
def analyze_sentiment_row(row):
  symbol = str(row.get('SYMBOL', '')).upper().strip()
  sentiment = str(row.get('SENTIMENT', '')).upper().strip()
  try:
    close = float(row['CLOSE'])
    chg_1d = float(row['1D_CHG_%'])
    oi_score = float(row['OI_SCORE'])
  except (ValueError, KeyError):
    return None

  ce_col = row.get('TOP_CE', row.get('TOP_CE_SIGNALS', ''))
  pe_col = row.get('TOP_PE', row.get('TOP_PE_SIGNALS', ''))
  ce_signals = parse_signals(ce_col)
  pe_signals = parse_signals(pe_col)
  score, reasons = 0, []

  # Determine direction from SENTIMENT or OI_SCORE (handles REVERSAL WATCH)
  if 'BULLISH' in sentiment or ('REVERSAL' in sentiment and oi_score > 0):
    direction = 'BULLISH'
    if oi_score >= 3 and chg_1d >= 0.50:
      score += 35
      reasons.append(f'Strong Index trend (+{chg_1d:.2f}%)')
    elif oi_score >= 3:
      score += 20
      reasons.append(f'Bullish Reversal OI (+{oi_score:g})')

    pe_floors = sorted([s for s, _, a in pe_signals if 'Addition' in a and s <= close * 1.005])
    nearest_floor = pe_floors[-1] if pe_floors else round(close * 0.995, 2)
    if pe_floors:
      score += 25
      reasons.append(f'PE Support at {nearest_floor:g}')

    at_par_ce = next((s for s, _, a in ce_signals if 'Addition' in a and abs(s - close) / close <= 0.004), None)
    below_windup = [s for s, _, a in ce_signals if 'Windup' in a and s < close]
    if at_par_ce is not None:
      score += 20
      reasons.append(f'ATM squeeze at {at_par_ce:g}CE')
    if below_windup:
      score += 10
      reasons.append(f'Sellers trapped below {max(below_windup):g}CE')

    above_windups = sorted([s for s, _, a in ce_signals if 'Windup' in a and s > close * 1.002])
    above_walls = sorted([s for s, _, a in ce_signals if 'Addition' in a and s > close * 1.0035])
    target = above_windups[0] if above_windups else (above_walls[0] if above_walls else round(close * 1.01, 2))
    reasons.append(f'Target {target:g}CE')

    rec_strike = f'{at_par_ce:g} CE' if at_par_ce is not None else (f'{nearest_floor:g} CE' if pe_floors else 'ATM CE')
    entry_zone = f'Above {at_par_ce:g}' if at_par_ce is not None else f'Hold above {nearest_floor:g}'
    stop_loss = round(nearest_floor * 0.9975, 2)
    spot_reward, spot_risk = max(target - close, 0), max(close - stop_loss, 1.0)

  elif 'BEARISH' in sentiment or ('REVERSAL' in sentiment and oi_score < 0):
    direction = 'BEARISH'
    if oi_score <= -3:
      score += 30
      reasons.append(f'Bearish OI Score ({oi_score:g})')

    ce_ceilings = sorted([s for s, _, a in ce_signals if 'Addition' in a and s >= close * 0.995])
    nearest_ceiling = ce_ceilings[0] if ce_ceilings else round(close * 1.005, 2)
    if ce_ceilings:
      score += 25
      reasons.append(f'CE Resistance wall at {nearest_ceiling:g}')

    at_par_pe = next((s for s, _, a in pe_signals if 'Addition' in a and abs(s - close) / close <= 0.004), None)
    if at_par_pe is not None:
      score += 20
      reasons.append(f'ATM breakdown at {at_par_pe:g}PE')

    below_windups = sorted([s for s, _, a in pe_signals if 'Windup' in a and s < close * 0.998], reverse=True)
    below_floors = sorted([s for s, _, a in pe_signals if 'Addition' in a and s < close * 0.9965], reverse=True)
    target = below_windups[0] if below_windups else (below_floors[0] if below_floors else round(close * 0.99, 2))
    reasons.append(f'Target {target:g}PE')

    rec_strike = f'{at_par_pe:g} PE' if at_par_pe is not None else (f'{nearest_ceiling:g} PE' if ce_ceilings else 'ATM PE')
    entry_zone = f'Below {at_par_pe:g}' if at_par_pe is not None else f'Stay below {nearest_ceiling:g}'
    stop_loss = round(nearest_ceiling * 1.0025, 2)
    spot_reward, spot_risk = max(close - target, 0), max(stop_loss - close, 1.0)
  else:
    return None

  inst_label, inst_pts = detect_index_inst_move(direction, oi_score, chg_1d, ce_signals, pe_signals)
  final_score = max(min(score + inst_pts * 4, 100), 0)
  grade = 'HIGH' if final_score >= 70 else ('MODERATE' if final_score >= 45 else 'LOW / SKIP')
  rr_num = round(spot_reward / spot_risk, 1)

  return {
      'INDEX': symbol, 'DIRECTION': direction, 'GRADE': grade, 'SCORE_%': final_score,
      'INST_ACTIVITY': inst_label, 'OI_SCORE': int(oi_score), 'CLOSE': close,
      '1D_CHG_%': round(chg_1d, 2), 'ENTRY_CONDITION': entry_zone, 'STOP_LOSS': stop_loss,
      'TARGET': target, 'SPOT_MOVE_PTS': round(spot_reward, 1),
      'SPOT_MOVE_%': round((spot_reward / close) * 100, 2),
      'RISK_REWARD': f'1 : {rr_num}', 'RR_NUM': rr_num,
      'EST_OPT_GAIN_PTS': f'+{round(spot_reward * 0.55, 1):g} pts',
      'REC_STRIKE': rec_strike, 'RATIONALE': ' | '.join(reasons),
  }


def analyze_raw_option_chain(df):
  """Handles Files 2, 3, and 4 (Strike-level Option Chain CSVs)."""
  cols = set(df.columns)
  if 'Index' in cols and 'Strike' in cols:
    df = df.rename(columns={'Index': 'SYM', 'Strike': 'STRIKE', 'Type': 'TYP', 'OI': 'OI', 'OI_Chg': 'OI_CHG', 'Activity': 'ACT'})
  elif 'STRIKE' in cols and 'OPTION_TYP' in cols:
    df['SYM'] = 'BANKNIFTY (Single Chain)'
    df = df.rename(columns={'OPTION_TYP': 'TYP', 'OPEN_INT': 'OI', 'CHG_IN_OI': 'OI_CHG', 'OI_ACTION': 'ACT'})
  else:
    return None

  summaries = []
  for sym, grp in df.groupby('SYM'):
    ce = grp[grp['TYP'] == 'CE']
    pe = grp[grp['TYP'] == 'PE']
    if ce.empty or pe.empty:
      continue

    total_pe_oi, total_ce_oi = pe['OI'].sum(), ce['OI'].sum()
    pcr = round(total_pe_oi / max(total_ce_oi, 1), 2)
    pe_chg, ce_chg = pe['OI_CHG'].sum(), ce['OI_CHG'].sum()

    top_ce = ce.sort_values(by='OI', ascending=False).iloc[0]
    top_pe = pe.sort_values(by='OI', ascending=False).iloc[0]
    max_ce_add = ce.sort_values(by='OI_CHG', ascending=False).iloc[0]
    max_pe_add = pe.sort_values(by='OI_CHG', ascending=False).iloc[0]

    if pcr >= 1.15 and pe_chg > ce_chg:
      bias, rec = 'BULLISH (Put Writing Dominance)', f"{int(max_pe_add['STRIKE'])} CE"
    elif pcr <= 0.85 and ce_chg > pe_chg:
      bias, rec = 'BEARISH (Call Writing Dominance)', f"{int(max_ce_add['STRIKE'])} PE"
    else:
      bias, rec = 'RANGEBOUND / STRADDLE', f"Sell {int(top_pe['STRIKE'])}PE & {int(top_ce['STRIKE'])}CE"

    summaries.append({
        'INDEX': sym, 'PCR (OI)': pcr, 'NET_PE_OI_CHG': int(pe_chg), 'NET_CE_OI_CHG': int(ce_chg),
        'MAX_PUT_SUPPORT': f"{int(top_pe['STRIKE'])} PE (OI: {int(top_pe['OI']):,})",
        'MAX_CALL_RESISTANCE': f"{int(top_ce['STRIKE'])} CE (OI: {int(top_ce['OI']):,})",
        'FRESH_PE_ADDITION': f"{int(max_pe_add['STRIKE'])} PE (+{int(max_pe_add['OI_CHG']):,})",
        'FRESH_CE_ADDITION': f"{int(max_ce_add['STRIKE'])} CE (+{int(max_ce_add['OI_CHG']):,})",
        'INSTITUTIONAL_BIAS': bias, 'SUGGESTED_PLAY': rec
    })
  return pd.DataFrame(summaries)


st.sidebar.header('⚙️ Index Scanner Filters')
min_score = st.sidebar.slider('Minimum Setup Score (%)', 0, 100, 45, step=5)
min_spot_move = st.sidebar.slider('Minimum Index Move (%)', 0.0, 5.0, 0.3, step=0.1)
min_rr = st.sidebar.slider('Minimum Risk-to-Reward (1 : X)', 0.5, 5.0, 1.0, step=0.5)
grade_filter = st.sidebar.multiselect('Setup Grade', ['HIGH', 'MODERATE', 'LOW / SKIP'], default=['HIGH', 'MODERATE'])
only_heavy_inst = st.sidebar.checkbox('🔥 Show Only Heavy Institutional Moves', value=False)

uploaded_file = st.file_uploader('Upload Index Sentiment OR Raw Option Chain CSV', type=['csv'])
if uploaded_file is not None:
  try:
    raw_df = pd.read_csv(uploaded_file)
    raw_df.columns = [c.strip() for c in raw_df.columns]

    # Mode 1: Sentiment Summary CSV (File 1)
    if 'SENTIMENT' in raw_df.columns and 'OI_SCORE' in raw_df.columns:
      parsed = [r for r in (analyze_sentiment_row(row) for _, row in raw_df.iterrows()) if r is not None]
      res_df = pd.DataFrame(parsed).sort_values(by=['SCORE_%', 'OI_SCORE'], ascending=False)
      filt_df = res_df[(res_df['SCORE_%'] >= min_score) & (res_df['SPOT_MOVE_%'] >= min_spot_move) & (res_df['RR_NUM'] >= min_rr) & (res_df['GRADE'].isin(grade_filter))]
      if only_heavy_inst:
        filt_df = filt_df[filt_df['INST_ACTIVITY'].str.contains('HEAVY INST.')]
      disp_df = filt_df.drop(columns=['RR_NUM'])

      c1, c2, c3, c4 = st.columns(4)
      c1.metric('Directional Indices', len(res_df))
      c2.metric('High Probability Setups', len(res_df[res_df['GRADE'] == 'HIGH']))
      c3.metric('🔥 Heavy Inst. Footprint', len(res_df[res_df['INST_ACTIVITY'].str.contains('HEAVY INST.')]))
      c4.metric('Filtered Matches', len(disp_df))

      st.subheader('🎯 Index Sentiment Trade Setups')
      st.dataframe(disp_df, use_container_width=True, hide_index=True)
      st.download_button('📥 Download Index Trade Plan CSV', disp_df.to_csv(index=False).encode('utf-8'), 'index_trade_plan.csv', 'text/csv')

    # Mode 2: Raw Option Chain CSV (Files 2, 3, 4)
    else:
      chain_df = analyze_raw_option_chain(raw_df)
      if chain_df is not None and not chain_df.empty:
        st.subheader('⛓️ Raw Option Chain Institutional Summary (PCR & Key Walls)')
        st.dataframe(chain_df, use_container_width=True, hide_index=True)
        st.download_button('📥 Download Chain Summary CSV', chain_df.to_csv(index=False).encode('utf-8'), 'option_chain_summary.csv', 'text/csv')
      else:
        st.error('Unrecognized CSV column structure.')
  except Exception as e:
    st.error(f'Error processing CSV file: {e}')
else:
  st.info('👆 Upload any of your 4 Index CSV files above.')
