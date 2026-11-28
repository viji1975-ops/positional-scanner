import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title='F&O OI Trade Scanner', layout='wide')
st.title('📊 Institutional Options OI Trade Scanner')
st.markdown(
    'Upload your **Sentiment Report (CSV)** to detect institutional '
    'footprints, filter by spot move & risk-reward, and get option strike '
    'targets.'
)


def parse_signals(signal_str):
  if pd.isna(signal_str) or not str(signal_str).strip():
    return []
  pattern = r'(\d+(?:\.\d+)?)(CE|PE)\s*\(([^)]+)\)'
  matches = re.findall(pattern, str(signal_str))
  return [(float(strike), opt, act.strip()) for strike, opt, act in matches]


def detect_institutional_move(direction, oi_score, chg_1d, ce_signals, pe_signals):
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
    if oi_score >= 5 and chg_1d >= 2.5:
      pts += 2
      tags.append('High OI + Surge')
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
    if oi_score >= 5 and chg_1d <= -2.5:
      pts += 2
      tags.append('High OI + Drop')

  if pts >= 3:
    return f"🔥 HEAVY INST. ({', '.join(tags)})", pts
  elif pts >= 1:
    return f"⚡ MODERATE INST. ({', '.join(tags)})", pts
  return '⚠️ WEAK / NO MASSIVE OI', 0
def analyze_row(row):
  symbol = str(row.get('SYMBOL', '')).strip()
  sentiment = str(row.get('SENTIMENT', '')).upper().strip()
  try:
    close = float(row['CLOSE'])
    chg_1d = float(row['1D_CHG_%'])
    oi_score = float(row['OI_SCORE'])
  except (ValueError, KeyError):
    return None

  ce_signals = parse_signals(row.get('TOP_CE_SIGNALS', ''))
  pe_signals = parse_signals(row.get('TOP_PE_SIGNALS', ''))
  score, reasons = 0, []

  if 'BULLISH' in sentiment:
    direction = 'BULLISH'
    if oi_score >= 4 and chg_1d >= 1.5:
      score += 30
      reasons.append(f'Strong 1D momentum (+{chg_1d:.2f}%)')
    elif chg_1d < 1.0:
      score -= 20
      reasons.append('Weak 1D follow-through (<1%)')

    pe_floors = sorted([s for s, _, a in pe_signals if 'Addition' in a and s <= close * 1.005])
    nearest_floor = pe_floors[-1] if pe_floors else round(close * 0.985, 2)
    if pe_floors:
      score += 25
      reasons.append(f'PE Support floor at {nearest_floor:g}')

    at_par_ce = next((s for s, _, a in ce_signals if 'Addition' in a and abs(s - close) / close <= 0.008), None)
    below_windup = [s for s, _, a in ce_signals if 'Windup' in a and s < close]
    if at_par_ce is not None:
      score += 25
      reasons.append(f'At-par squeeze trigger at {at_par_ce:g}CE')
    if below_windup:
      score += 10
      reasons.append(f'Sellers unwinding at {max(below_windup):g}CE')

    above_windups = sorted([s for s, _, a in ce_signals if 'Windup' in a and s > close * 1.005])
    above_walls = sorted([s for s, _, a in ce_signals if 'Addition' in a and s > close * 1.008])
    if above_windups:
      target = above_windups[0]
      score += 10
      reasons.append(f'Open runway to {target:g}CE (Windup)')
    elif above_walls:
      target = above_walls[0]
      reasons.append(f'Overhead wall at {target:g}CE')
    else:
      target = round(close * 1.03, 2)

    rec_strike = f'{at_par_ce:g} CE' if at_par_ce is not None else (f'{nearest_floor:g} CE' if pe_floors else 'ATM CE')
    entry_zone = f'Above {at_par_ce:g}' if at_par_ce is not None else f'Hold above {nearest_floor:g}'
    stop_loss = round(nearest_floor * 0.995, 2)
    spot_reward, spot_risk = max(target - close, 0), max(close - stop_loss, 0.05)

  elif 'BEARISH' in sentiment:
    direction = 'BEARISH'
    if oi_score >= 4 and chg_1d <= -1.5:
      score += 30
      reasons.append(f'Strong 1D drop ({chg_1d:.2f}%)')
    elif chg_1d > -1.0:
      score -= 20
      reasons.append('Weak 1D breakdown (<1%)')

    ce_ceilings = sorted([s for s, _, a in ce_signals if 'Addition' in a and s >= close * 0.995])
    nearest_ceiling = ce_ceilings[0] if ce_ceilings else round(close * 1.015, 2)
    if ce_ceilings:
      score += 25
      reasons.append(f'CE Resistance wall at {nearest_ceiling:g}')

    at_par_pe = next((s for s, _, a in pe_signals if 'Addition' in a and abs(s - close) / close <= 0.008), None)
    above_windup = [s for s, _, a in pe_signals if 'Windup' in a and s > close]
    if at_par_pe is not None:
      score += 25
      reasons.append(f'At-par breakdown trigger at {at_par_pe:g}PE')
    if above_windup:
      score += 10
      reasons.append(f'Put writers exiting at {min(above_windup):g}PE')

    below_windups = sorted([s for s, _, a in pe_signals if 'Windup' in a and s < close * 0.995], reverse=True)
    below_floors = sorted([s for s, _, a in pe_signals if 'Addition' in a and s < close * 0.992], reverse=True)
    if below_windups:
      target = below_windups[0]
      score += 10
      reasons.append(f'Open path down to {target:g}PE (Windup)')
    elif below_floors:
      target = below_floors[0]
      reasons.append(f'Support floor at {target:g}PE')
    else:
      target = round(close * 0.97, 2)

    rec_strike = f'{at_par_pe:g} PE' if at_par_pe is not None else (f'{nearest_ceiling:g} PE' if ce_ceilings else 'ATM PE')
    entry_zone = f'Below {at_par_pe:g}' if at_par_pe is not None else f'Stay below {nearest_ceiling:g}'
    stop_loss = round(nearest_ceiling * 1.005, 2)
    spot_reward, spot_risk = max(close - target, 0), max(stop_loss - close, 0.05)
  else:
    return None

  inst_label, inst_pts = detect_institutional_move(direction, oi_score, chg_1d, ce_signals, pe_signals)
  final_score = max(min(score + inst_pts * 3, 100), 0)
  grade = 'HIGH' if final_score >= 75 else ('MODERATE' if final_score >= 50 else 'LOW / SKIP')
  rr_num = round(spot_reward / spot_risk, 1)

  return {
      'SYMBOL': symbol, 'DIRECTION': direction, 'GRADE': grade, 'SCORE_%': final_score,
      'INST_ACTIVITY': inst_label, 'OI_SCORE': int(oi_score), 'CLOSE': close,
      '1D_CHG_%': round(chg_1d, 2), 'ENTRY_CONDITION': entry_zone, 'STOP_LOSS': stop_loss,
      'TARGET': target, 'SPOT_MOVE_%': round((spot_reward / close) * 100, 2),
      'RISK_REWARD': f'1 : {rr_num}', 'RR_NUM': rr_num,
      'EST_OPT_GAIN_PTS': f'+{round(spot_reward * 0.60, 2):g} pts',
      'REC_STRIKE': rec_strike, 'RATIONALE': ' | '.join(reasons),
  }


st.sidebar.header('⚙️ Trade & Risk Filters')
min_score = st.sidebar.slider('Minimum Setup Score (%)', 0, 100, 50, step=5)
min_spot_move = st.sidebar.slider('Minimum Spot Move (%)', 0.0, 10.0, 1.5, step=0.5)
min_rr = st.sidebar.slider('Minimum Risk-to-Reward (1 : X)', 0.5, 5.0, 1.5, step=0.5)
grade_filter = st.sidebar.multiselect('Setup Grade', ['HIGH', 'MODERATE', 'LOW / SKIP'], default=['HIGH', 'MODERATE'])
only_heavy_inst = st.sidebar.checkbox('🔥 Show Only Heavy Institutional Moves', value=False)

uploaded_file = st.file_uploader('Upload Sentiment Report CSV', type=['csv'])
if uploaded_file is not None:
  try:
    raw_df = pd.read_csv(uploaded_file)
    raw_df.columns = [c.strip() for c in raw_df.columns]
    parsed = [r for r in (analyze_row(row) for _, row in raw_df.iterrows()) if r is not None]
    if not parsed:
      st.warning('No valid Bullish or Bearish rows found in CSV.')
    else:
      res_df = pd.DataFrame(parsed).sort_values(by=['SCORE_%', 'OI_SCORE'], ascending=False)
      filt_df = res_df[(res_df['SCORE_%'] >= min_score) & (res_df['SPOT_MOVE_%'] >= min_spot_move) & (res_df['RR_NUM'] >= min_rr) & (res_df['GRADE'].isin(grade_filter))]
      if only_heavy_inst:
        filt_df = filt_df[filt_df['INST_ACTIVITY'].str.contains('HEAVY INST.')]
      disp_df = filt_df.drop(columns=['RR_NUM'])

      c1, c2, c3, c4 = st.columns(4)
      c1.metric('Total Stocks Scanned', len(res_df))
      c2.metric('High Probability Setups', len(res_df[res_df['GRADE'] == 'HIGH']))
      c3.metric('🔥 Heavy Inst. Footprint', len(res_df[res_df['INST_ACTIVITY'].str.contains('HEAVY INST.')]))
      c4.metric('Filtered Matches', len(disp_df))

      st.subheader('🎯 Actionable Trade Setups')
      st.dataframe(disp_df, use_container_width=True, hide_index=True)
      st.download_button('📥 Download Filtered Trade Plan CSV', disp_df.to_csv(index=False).encode('utf-8'), 'institutional_trade_plan.csv', 'text/csv')
  except Exception as e:
    st.error(f'Error processing CSV file: {e}')
else:
  st.info('👆 Upload your downloaded CSV file above to generate the trade plan.')
