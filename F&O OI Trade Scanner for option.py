import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title='F&O OI Trade Scanner', layout='wide')

st.title('📊 Institutional Options OI Trade Scanner')
st.markdown(
    'Upload your **Sentiment Report (CSV)** to automatically rank setups, '
    'identify entry/stop-loss/target levels, and select optimal option strikes.'
)


def parse_signals(signal_str):
  """Extracts list of tuples: (strike_price, option_type, action)"""
  if pd.isna(signal_str) or not str(signal_str).strip():
    return []
  pattern = r'(\d+(?:\.\d+)?)(CE|PE)\s*\(([^)]+)\)'
  matches = re.findall(pattern, str(signal_str))
  return [(float(strike), opt, act.strip()) for strike, opt, act in matches]


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

  score = 0
  reasons = []

  # --- BULLISH LOGIC ---
  if 'BULLISH' in sentiment:
    if oi_score >= 4 and chg_1d >= 1.5:
      score += 30
      reasons.append(f'Strong 1D momentum (+{chg_1d:.2f}%)')
    elif chg_1d < 1.0:
      score -= 20
      reasons.append('Weak 1D follow-through (<1%)')

    # Support Floor (PE Addition at or below close)
    pe_floors = sorted([
        s for s, _, a in pe_signals if 'Addition' in a and s <= close * 1.005
    ])
    if pe_floors:
      nearest_floor = pe_floors[-1]
      score += 25
      reasons.append(f'PE Support floor at {nearest_floor:g}')
    else:
      nearest_floor = round(close * 0.985, 2)

    # Squeeze Trigger (At-Par CE Addition or Below-Close CE Windup)
    at_par_ce = [
        s
        for s, _, a in ce_signals
        if 'Addition' in a and abs(s - close) / close <= 0.008
    ]
    below_windup = [s for s, _, a in ce_signals if 'Windup' in a and s < close]

    if at_par_ce:
      score += 25
      reasons.append(f'At-par squeeze trigger at {at_par_ce[0]:g}CE')
    if below_windup:
      score += 10
      reasons.append(f'Sellers unwinding at {max(below_windup):g}CE')

    # Target & Runway
    above_windups = sorted(
        [s for s, _, a in ce_signals if 'Windup' in a and s > close * 1.005]
    )
    above_walls = sorted(
        [s for s, _, a in ce_signals if 'Addition' in a and s > close * 1.008]
    )

    if above_windups:
      target = above_windups[0]
      score += 10
      reasons.append(f'Open runway to {target:g}CE (Windup)')
    elif above_walls:
      target = above_walls[0]
      reasons.append(f'Overhead wall at {target:g}CE')
    else:
      target = round(close * 1.03, 2)

    recommended_strike = (
        f'{at_par_ce[0]:g} CE'
        if at_par_ce
        else (f'{pe_floors[-1]:g} CE' if pe_floors else 'ATM CE')
    )
    entry_zone = (
        f'Above {at_par_ce[0]:g}'
        if at_par_ce
        else f'Hold above {nearest_floor:g}'
    )
    stop_loss = round(nearest_floor * 0.995, 2)
    reward_pct = ((target - close) / close) * 100
    direction = 'BULLISH'

  # --- BEARISH LOGIC ---
  elif 'BEARISH' in sentiment:
    if oi_score >= 4 and chg_1d <= -1.5:
      score += 30
      reasons.append(f'Strong 1D drop ({chg_1d:.2f}%)')
    elif chg_1d > -1.0:
      score -= 20
      reasons.append('Weak 1D breakdown (<1%)')

    # Resistance Ceiling (CE Addition at or above close)
    ce_ceilings = sorted([
        s for s, _, a in ce_signals if 'Addition' in a and s >= close * 0.995
    ])
    if ce_ceilings:
      nearest_ceiling = ce_ceilings[0]
      score += 25
      reasons.append(f'CE Resistance wall at {nearest_ceiling:g}')
    else:
      nearest_ceiling = round(close * 1.015, 2)

    # Breakdown Trigger (At-Par PE Addition or Above-Close PE Windup)
    at_par_pe = [
        s
        for s, _, a in pe_signals
        if 'Addition' in a and abs(s - close) / close <= 0.008
    ]
    above_windup = [s for s, _, a in pe_signals if 'Windup' in a and s > close]

    if at_par_pe:
      score += 25
      reasons.append(f'At-par breakdown trigger at {at_par_pe[0]:g}PE')
    if above_windup:
      score += 10
      reasons.append(f'Put writers exiting at {min(above_windup):g}PE')

    # Target & Downside Runway
    below_windups = sorted(
        [s for s, _, a in pe_signals if 'Windup' in a and s < close * 0.995],
        reverse=True,
    )
    below_floors = sorted(
        [s for s, _, a in pe_signals if 'Addition' in a and s < close * 0.992],
        reverse=True,
    )

    if below_windups:
      target = below_windups[0]
      score += 10
      reasons.append(f'Open path down to {target:g}PE (Windup)')
    elif below_floors:
      target = below_floors[0]
      reasons.append(f'Support floor at {target:g}PE')
    else:
      target = round(close * 0.97, 2)

    recommended_strike = (
        f'{at_par_pe[0]:g} PE'
        if at_par_pe
        else (f'{nearest_ceiling:g} PE' if ce_ceilings else 'ATM PE')
    )
    entry_zone = (
        f'Below {at_par_pe[0]:g}'
        if at_par_pe
        else f'Stay below {nearest_ceiling:g}'
    )
    stop_loss = round(nearest_ceiling * 1.005, 2)
    reward_pct = ((close - target) / close) * 100
    direction = 'BEARISH'
  else:
    return None

  final_score = max(min(score, 100), 0)
  if final_score >= 75:
    grade = 'HIGH'
  elif final_score >= 50:
    grade = 'MODERATE'
  else:
    grade = 'LOW / SKIP'

  return {
      'SYMBOL': symbol,
      'DIRECTION': direction,
      'GRADE': grade,
      'SCORE_%': final_score,
      'OI_SCORE': int(oi_score),
      'CLOSE': close,
      '1D_CHG_%': round(chg_1d, 2),
      'ENTRY_CONDITION': entry_zone,
      'STOP_LOSS': stop_loss,
      'TARGET': target,
      'SPOT_MOVE_%': round(reward_pct, 2),
      'REC_STRIKE': recommended_strike,
      'RATIONALE': ' | '.join(reasons),
  }


# --- SIDEBAR FILTERS ---
st.sidebar.header('⚙️ Scanner Filters')
min_score = st.sidebar.slider('Minimum Setup Score (%)', 0, 100, 50, step=5)
grade_filter = st.sidebar.multiselect(
    'Setup Grade',
    ['HIGH', 'MODERATE', 'LOW / SKIP'],
    default=['HIGH', 'MODERATE'],
)

# --- FILE UPLOADER ---
uploaded_file = st.file_uploader(
    'Upload Sentiment Report CSV', type=['csv']
)

if uploaded_file is not None:
  try:
    raw_df = pd.read_csv(uploaded_file)
    # Clean column names in case of extra spaces
    raw_df.columns = [c.strip() for c in raw_df.columns]

    parsed_rows = [analyze_row(row) for _, row in raw_df.iterrows()]
    parsed_rows = [r for r in parsed_rows if r is not None]

    if not parsed_rows:
      st.warning(
          'No valid Bullish or Bearish rows found. Check that your CSV has '
          'SYMBOL, SENTIMENT, OI_SCORE, CLOSE, 1D_CHG_%, TOP_CE_SIGNALS, and '
          'TOP_PE_SIGNALS columns.'
      )
    else:
      results_df = pd.DataFrame(parsed_rows)
      results_df = results_df.sort_values(
          by=['SCORE_%', 'OI_SCORE'], ascending=False
      )

      filtered_df = results_df[
          (results_df['SCORE_%'] >= min_score)
          & (results_df['GRADE'].isin(grade_filter))
      ]

      # Summary Metrics
      col1, col2, col3 = st.columns(3)
      col1.metric('Total Stocks Scanned', len(results_df))
      col2.metric(
          'High Probability Setups',
          len(results_df[results_df['GRADE'] == 'HIGH']),
      )
      col3.metric(
          'Moderate Setups',
          len(results_df[results_df['GRADE'] == 'MODERATE']),
      )

      st.subheader('🎯 Filtered Trade Setups')
      st.dataframe(filtered_df, use_container_width=True, hide_index=True)

      # Download Processed Report
      csv_out = filtered_df.to_csv(index=False).encode('utf-8')
      st.download_button(
          label='📥 Download Trade Plan CSV',
          data=csv_out,
          file_name='analyzed_trade_setups.csv',
          mime='text/csv',
      )

  except Exception as e:
    st.error(f'Error processing CSV file: {e}')
else:
  st.info(
      '👆 Upload your downloaded CSV file above to generate the trade plan.'
  )
