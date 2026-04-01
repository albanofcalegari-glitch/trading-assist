"""
charts.py — Gráficos Plotly para trading-assist
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

# ── Paleta dark terminal ──────────────────────────────────────────────────────
C = {
    'bg':      '#0a0e1a',
    'panel':   '#111827',
    'panel2':  '#0f1623',
    'green':   '#10b981',
    'red':     '#ef4444',
    'blue':    '#3b82f6',
    'orange':  '#f59e0b',
    'purple':  '#8b5cf6',
    'gray':    '#4b5563',
    'text':    '#f1f5f9',
    'text2':   '#94a3b8',
    'grid':    'rgba(255,255,255,0.04)',
    'spike':   'rgba(255,255,255,0.2)',
    'cyan':    '#06b6d4',
    'lime':    '#a3e635',
}

_FONT = dict(family="'JetBrains Mono', 'Fira Code', monospace", size=11, color=C['text2'])


def _base(height=480) -> dict:
    return dict(
        paper_bgcolor=C['bg'],
        plot_bgcolor=C['panel'],
        font=_FONT,
        height=height,
        margin=dict(l=60, r=16, t=32, b=36),
        xaxis=dict(
            showgrid=True, gridcolor=C['grid'], gridwidth=1,
            zeroline=False, showline=True, linecolor=C['gray'],
            tickfont=dict(size=10, color=C['text2']),
            showspikes=True, spikecolor=C['spike'], spikethickness=1, spikedash='dot',
        ),
        yaxis=dict(
            showgrid=True, gridcolor=C['grid'], gridwidth=1,
            zeroline=False, showline=True, linecolor=C['gray'],
            tickfont=dict(size=10, color=C['text2']),
            side='right',
        ),
        legend=dict(
            bgcolor='rgba(0,0,0,0)', font=dict(size=10, color=C['text2']),
            orientation='h', yanchor='bottom', y=1.01, xanchor='left', x=0,
        ),
        hovermode='x unified',
        hoverlabel=dict(
            bgcolor=C['panel'], font_size=11, font_family='monospace',
            bordercolor=C['gray'],
        ),
    )


def _apply_date_ticks(fig: go.Figure, df: pd.DataFrame, tf: str,
                      hide_labels_row: int | None = None,
                      candle_freq: str = 'D') -> None:
    """
    Aplica ticks de fecha al eje X usando update_xaxes.

    D  → type='date'     (eje continuo, ticks diarios/semanales)
    W/M/Y → type='category' (barras equidistantes, sin gaps de fin de semana)
    """
    from datetime import datetime as _dt

    if candle_freq == 'D':
        tick0 = df['fecha'].iloc[0] if not df.empty else '2020-01-01'
        if tf == '3M':
            cfg = dict(type='date', tickmode='linear', tick0=tick0,
                       dtick=7 * 24 * 60 * 60 * 1000, tickformat='%d %b',
                       tickangle=0, showticklabels=True)
        else:  # 1A
            cfg = dict(type='date', tickmode='linear', tick0=tick0,
                       dtick='M1', tickformat='%b %Y',
                       tickangle=0, showticklabels=True)
        fig.update_xaxes(**cfg)

    else:
        # W/M/Y: eje categórico — barras equidistantes, sin gaps de fines de semana
        if df.empty:
            fig.update_xaxes(type='category')
            return

        dates = df['fecha'].tolist()
        n = len(dates)

        if candle_freq == 'W':
            step = max(1, round(n / 16))   # ~16 etiquetas max
            fmt  = '%b %Y'
        elif candle_freq == 'M':
            step = max(1, round(n / 8))    # ~8 etiquetas max
            fmt  = '%b %Y'
        else:  # Y
            step = 1
            fmt  = '%Y'

        tick_indices = list(range(0, n, step))
        tickvals = [dates[i] for i in tick_indices]
        ticktext = [_dt.strptime(dates[i], '%Y-%m-%d').strftime(fmt)
                    for i in tick_indices]

        fig.update_xaxes(
            type='category',
            tickvals=tickvals,
            ticktext=ticktext,
            tickangle=0,
            showticklabels=True,
        )

    if hide_labels_row is not None:
        fig.update_xaxes(showticklabels=False, row=hide_labels_row, col=1)


# ── Resampling OHLCV ──────────────────────────────────────────────────────────

def resample_ohlcv(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """
    Reagrupa velas diarias a frecuencia superior.
    freq: 'D' sin cambio, 'W' semanal, 'M' mensual, 'Y' anual.

    OHLCV:  open=primero, high=max, low=min, close=ultimo, volume=suma.
    MAs (sma50/ema20/sma200): ultimo valor del periodo.

    Usa type='category' en el grafico para evitar gaps de fines de semana.
    """
    if freq == 'D' or df.empty:
        return df.copy()

    df2 = df.copy()
    df2['fecha'] = pd.to_datetime(df2['fecha'])
    df2 = df2.set_index('fecha').sort_index()

    # Aliases: intenta primero la API moderna (pandas 2.2+), fallback a la clasica
    _rules_primary  = {'W': 'W-FRI', 'M': 'ME',  'Y': 'YE'}
    _rules_fallback = {'W': 'W',     'M': 'M',   'Y': 'Y'}
    rule     = _rules_primary.get(freq,  freq)
    rule_fb  = _rules_fallback.get(freq, freq)

    agg: dict = {}
    for c, fn in [('open', 'first'), ('high', 'max'), ('low', 'min'),
                  ('close', 'last'), ('volume', 'sum')]:
        if c in df2.columns:
            agg[c] = fn
    for c in ('sma50', 'ema20', 'sma200'):
        if c in df2.columns:
            agg[c] = 'last'

    try:
        out = df2.resample(rule).agg(agg)
    except Exception:
        out = df2.resample(rule_fb).agg(agg)

    out = out.dropna(subset=['close']).reset_index()
    out['fecha'] = out['fecha'].dt.strftime('%Y-%m-%d')
    return out


# ── S/R dinámico: trendlines construidas con pivotes reales ──────────────────

def get_dynamic_sr(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """
    Detecta pivot lows y pivot highs con ventana de 1 barra:
      pivot low:  low[i] < low[i-1]  AND  low[i] < low[i+1]
      pivot high: high[i] > high[i-1] AND high[i] > high[i+1]

    Construye líneas que:
      - Soporte    → une mínimos CRECIENTES (slope > 0)
      - Resistencia → une máximos DECRECIENTES (slope < 0)

    La línea pasa EXACTAMENTE por los dos pivotes que la definen.
    Se valida contando cuántos otros pivotes caen cerca de ella (±0.5%).
    Puntaje = toques - violaciones * 2 + bonus_recencia.
    Se prefiere la línea con más toques, menos violaciones y más reciente.

    Returns (dyn_supports, dyn_resistances) — listas de 0 ó 1 dict:
      {
        'p1'/'p2' : {'time': str, 'price': float, 'idx': int},
        'value'   : float,   # valor proyectado en el último bar
        'slope'   : float,
        'touches' : int,
        'status'  : 'active' | 'broken',
        'fuerza'  : 'alta' | 'media',
        'is_zone' : False,
      }
    """
    if df.empty or len(df) < 6:
        return [], []

    highs  = pd.to_numeric(df['high'],  errors='coerce')
    lows   = pd.to_numeric(df['low'],   errors='coerce')
    dates  = df['fecha'].tolist()
    n      = len(df)
    TOL     = 0.005   # 0.5% — tolerancia para contar un toque en la línea
    PIVOT_W = 7       # barras a cada lado → mínimo/máximo en ventana de 15 barras
    MIN_SEP = 15      # separación mínima entre pivotes consecutivos (barras)

    # ── 1. Pivot detection: ventana estructural ───────────────────────────────
    # Pivot low:  low[i] == min(low[i-PIVOT_W : i+PIVOT_W+1])
    # Pivot high: high[i] == max(high[i-PIVOT_W : i+PIVOT_W+1])
    # + separación mínima MIN_SEP barras entre pivotes consecutivos
    pivot_lows:  list[tuple[int, float, str]] = []
    pivot_highs: list[tuple[int, float, str]] = []

    for i in range(PIVOT_W, n - PIVOT_W):
        lo_win = lows.iloc[i - PIVOT_W: i + PIVOT_W + 1].dropna()
        hi_win = highs.iloc[i - PIVOT_W: i + PIVOT_W + 1].dropna()
        lo = lows.iat[i]
        hi = highs.iat[i]

        if pd.notna(lo) and len(lo_win) >= PIVOT_W and float(lo) <= float(lo_win.min()):
            # Respetar separación mínima respecto al último pivote
            if not pivot_lows or (i - pivot_lows[-1][0]) >= MIN_SEP:
                pivot_lows.append((i, float(lo), dates[i]))
            elif float(lo) < pivot_lows[-1][1]:
                # Si está más cerca de lo esperado pero es más bajo, reemplaza
                pivot_lows[-1] = (i, float(lo), dates[i])

        if pd.notna(hi) and len(hi_win) >= PIVOT_W and float(hi) >= float(hi_win.max()):
            if not pivot_highs or (i - pivot_highs[-1][0]) >= MIN_SEP:
                pivot_highs.append((i, float(hi), dates[i]))
            elif float(hi) > pivot_highs[-1][1]:
                pivot_highs[-1] = (i, float(hi), dates[i])

    TOL_TOUCH = 0.012   # 1.2% — el pivote "toca" la linea
    TOL_VIO   = 0.020   # 2.0% — el pivote rompe la linea (violacion real)

    # ── Forzar el lowest low como pivot candidato para soporte ────────────────
    # El minimo absoluto del periodo (capitulacion) debe ser siempre evaluado
    # aunque no cumpla la ventana estructural de PIVOT_W barras.
    _valid_lows = lows.dropna()
    if len(_valid_lows) > 0:
        _ll_pos = int(_valid_lows.idxmin())   # posicion absoluta en df
        _ll_val = float(lows.iat[_ll_pos])
        _ll_date = dates[_ll_pos]
        # Verificar si ya esta en pivot_lows (tolerancia 0.5%)
        _already = any(abs(yk - _ll_val) / _ll_val < 0.005 for _, yk, _ in pivot_lows)
        if not _already:
            # Insertar en orden cronologico
            insert_at = len(pivot_lows)
            for k, (ik, _, _) in enumerate(pivot_lows):
                if ik > _ll_pos:
                    insert_at = k
                    break
            pivot_lows.insert(insert_at, (_ll_pos, _ll_val, _ll_date))
            print(f'[SR] Lowest low forzado como pivot: {_ll_date} @ ${_ll_val:.2f} (bar {_ll_pos})', flush=True)

    # ── 2. Mejor línea: evalúa todos los pares ────────────────────────────────
    def _is_broken(i1, y1, slope, price_series, direction) -> bool:
        """True si los últimos 5 bars cruzan la línea más de TOL_VIO."""
        for k in range(max(0, n - 5), n):
            lv = y1 + slope * (k - i1)
            if lv <= 0:
                continue
            v = price_series.iat[k]
            if pd.isna(v):
                continue
            if direction == 'up'   and float(v) < lv * (1 - TOL_VIO):
                return True
            if direction == 'down' and float(v) > lv * (1 + TOL_VIO):
                return True
        return False

    def _score_pair(i1, y1, i2, y2, pivots, direction) -> tuple[int, int]:
        """Cuenta toques y violaciones de todos los pivotes respecto a esta línea."""
        slope = (y2 - y1) / (i2 - i1)
        touches = violations = 0
        for ik, yk, _ in pivots:
            lv = y1 + slope * (ik - i1)
            if lv <= 0:
                continue
            dist = abs(yk - lv) / lv
            if dist <= TOL_TOUCH:
                touches += 1
            elif direction == 'up'   and yk < lv * (1 - TOL_VIO):
                violations += 1
            elif direction == 'down' and yk > lv * (1 + TOL_VIO):
                violations += 1
        return touches, violations

    def _best_line(
        pivots: list[tuple[int, float, str]],
        direction: str,
        price_series: pd.Series,
    ):
        if len(pivots) < 2:
            return None

        best_score = -999.0
        best       = None

        for pi in range(len(pivots)):
            for pj in range(pi + 1, len(pivots)):
                i1, y1, t1 = pivots[pi]
                i2, y2, t2 = pivots[pj]

                # Dirección estricta
                if direction == 'up'   and y2 <= y1: continue
                if direction == 'down' and y2 >= y1: continue

                slope = (y2 - y1) / (i2 - i1)

                touches, violations = _score_pair(i1, y1, i2, y2, pivots, direction)

                # Penalizar fuerte las violaciones (2 violaciones = línea descartada)
                if violations >= 2:
                    continue

                # Penalizar si la línea ya está rota
                broken = _is_broken(i1, y1, slope, price_series, direction)
                broken_penalty = 5 if broken else 0

                # Bonus por longitud: líneas que cubren más del chart son más relevantes
                span_bonus = (i2 - i1) / n   # 0..1

                score = touches * 3 - violations * 4 - broken_penalty + span_bonus

                if score > best_score:
                    best_score = score
                    best = (i1, y1, t1, i2, y2, t2, slope, touches, broken)

        if best is None:
            return None

        i1, y1, t1, i2, y2, t2, slope, touches, broken = best
        current_val = y1 + slope * (n - 1 - i1)

        return {
            'p1':      {'time': t1, 'price': y1, 'idx': i1},
            'p2':      {'time': t2, 'price': y2, 'idx': i2},
            'value':   current_val,
            'slope':   slope,
            'touches': touches,
            'status':  'broken' if broken else 'active',
            'fuerza':  'alta' if touches >= 3 else 'media',
            'is_zone': False,
        }

    # ── Selección de soporte: prioriza span + inicio temprano + p1 importante ──
    def _best_support_line(pivots: list[tuple[int, float, str]]) -> dict | None:
        """
        Selección del soporte dominante.

        Criterios (en orden de peso):
          1. span largo   → línea que cubre más del chart (directriz dominante)
          2. inicio temprano → cuanto antes empieza, más estructural
          3. p1 importante  → profundidad del primer low + magnitud del rebote
          4. toques         → refuerzan validez pero pesan menos que span
          5. violaciones    → penalizan; 3+ descarta la línea
          6. broken         → penalización fuerte si los últimos 5 bars rompieron
        """
        if len(pivots) < 2:
            return None

        all_lows_vals = [yk for _, yk, _ in pivots]
        lo_min = min(all_lows_vals)
        lo_max = max(all_lows_vals)
        lo_range = (lo_max - lo_min) if lo_max > lo_min else 1.0

        candidates = []

        for pi in range(len(pivots)):
            for pj in range(pi + 1, len(pivots)):
                i1, y1, t1 = pivots[pi]
                i2, y2, t2 = pivots[pj]

                # Soporte: lows deben ser CRECIENTES (slope > 0)
                if y2 <= y1:
                    continue

                slope = (y2 - y1) / (i2 - i1)

                # Contar toques/violaciones con umbral 3% (mas permisivo para soporte)
                touches = violations = 0
                for ik, yk, _ in pivots:
                    lv = y1 + slope * (ik - i1)
                    if lv <= 0:
                        continue
                    dist = abs(yk - lv) / lv
                    if dist <= TOL_TOUCH:
                        touches += 1
                    elif yk < lv * (1 - 0.030):
                        violations += 1

                # Sin cutoff duro: permitir hasta 9 violaciones antes de descartar
                if violations >= 10:
                    continue

                broken = _is_broken(i1, y1, slope, lows, 'up')

                # Span: fraccion del chart cubierta (0..1)
                span_frac = (i2 - i1) / n

                # Score simplificado: span domina, violaciones penalizan poco
                # score = span*30 + touches - violations*2 - broken*4
                broken_penalty = 4.0 if broken else 0.0

                score = (
                    span_frac * 30.0 +
                    touches   *  1.0 -
                    violations * 2.0 -
                    broken_penalty
                )

                projected = y1 + slope * (n - 1 - i1)
                candidates.append({
                    'i1': i1, 'y1': y1, 't1': t1,
                    'i2': i2, 'y2': y2, 't2': t2,
                    'slope': slope, 'touches': touches,
                    'violations': violations, 'broken': broken,
                    'span_bars': i2 - i1, 'span_frac': span_frac,
                    'score': score, 'projected': projected,
                })

        if not candidates:
            return None

        candidates.sort(key=lambda x: x['score'], reverse=True)

        # ── Debug: top 3 candidatos ────────────────────────────────────────────
        print('\n=== SOPORTE - Top candidatos ===')
        for rank, c in enumerate(candidates[:3], 1):
            tag = ' <-- ELEGIDA' if rank == 1 else ''
            print(f'  #{rank}{tag}')
            print(f'    p1 : {c["t1"]} @ ${c["y1"]:.2f}  (bar {c["i1"]})')
            print(f'    p2 : {c["t2"]} @ ${c["y2"]:.2f}  (bar {c["i2"]})')
            print(f'    span: {c["span_bars"]} barras ({c["span_frac"]:.1%})')
            print(f'    toques={c["touches"]}  violaciones={c["violations"]}  broken={c["broken"]}')
            print(f'    score={c["score"]:.3f}  projected=${c["projected"]:.2f}')
        if len(candidates) >= 2:
            c1, c2 = candidates[0], candidates[1]
            reasons = []
            if c1['span_bars'] > c2['span_bars']:
                reasons.append(f'span mayor (+{c1["span_bars"]-c2["span_bars"]} barras)')
            if c1['violations'] < c2['violations']:
                reasons.append(f'menos violaciones ({c1["violations"]} vs {c2["violations"]})')
            if c1['touches'] > c2['touches']:
                reasons.append(f'más toques ({c1["touches"]} vs {c2["touches"]})')
            print(f'  >> #1 gano vs #2: {", ".join(reasons) or "score global mas alto"}')
        print('================================\n', flush=True)
        # ──────────────────────────────────────────────────────────────────────

        b = candidates[0]
        return {
            'p1':      {'time': b['t1'], 'price': b['y1'], 'idx': b['i1']},
            'p2':      {'time': b['t2'], 'price': b['y2'], 'idx': b['i2']},
            'value':   b['projected'],
            'slope':   b['slope'],
            'touches': b['touches'],
            'status':  'broken' if b['broken'] else 'active',
            'fuerza':  'alta' if b['touches'] >= 3 else 'media',
            'is_zone': False,
        }

    sup_line = _best_support_line(pivot_lows)
    res_line = _best_line(pivot_highs, 'down', highs)

    return ([sup_line] if sup_line else []), ([res_line] if res_line else [])


# ── WMA21 / SMA30 crossover ────────────────────────────────────────────────────

def get_wma_sma_signal(df: pd.DataFrame) -> dict:
    """
    Calcula WMA21 y SMA30 sobre precios de cierre y detecta cruces.

    WMA21: media ponderada lineal de 21 períodos.
      Pesos: 1, 2, …, 21 (el bar más reciente recibe peso 21).
      Fórmula: WMA[i] = sum(close[i-20..i] * [1..21]) / sum(1..21)
               donde sum(1..21) = 231.

    SMA30: media simple de 30 períodos.

    Cruce alcista  : WMA21[t-1] < SMA30[t-1]  y  WMA21[t] > SMA30[t]
    Cruce bajista  : WMA21[t-1] > SMA30[t-1]  y  WMA21[t] < SMA30[t]

    Returns dict:
      wma21        : pd.Series (índice = índice del df)
      sma30        : pd.Series
      bull_crosses : list[(fecha, close)]  — cruces alcistas
      bear_crosses : list[(fecha, close)]  — cruces bajistas
      estado       : 'Alcista' | 'Bajista' | 'N/D'
      ultimo_cruce : {'fecha': str, 'tipo': str} | None
    """
    _empty = dict(wma21=pd.Series(dtype=float), sma30=pd.Series(dtype=float),
                  bull_crosses=[], bear_crosses=[], estado='N/D', ultimo_cruce=None)
    if df.empty or len(df) < 30:
        return _empty

    closes = pd.to_numeric(df['close'], errors='coerce')

    # WMA21
    _w    = np.arange(1, 22, dtype=float)
    _wsum = _w.sum()          # 231
    wma21 = closes.rolling(21).apply(lambda x: float(np.dot(x, _w) / _wsum), raw=True)

    # SMA30
    sma30 = closes.rolling(30).mean()

    # Detección de cruces (iterar solo sobre posiciones con ambas series válidas)
    bull_crosses: list = []
    bear_crosses: list = []
    ultimo_cruce = None

    valid_pos = [i for i in range(len(df))
                 if pd.notna(wma21.iloc[i]) and pd.notna(sma30.iloc[i])]

    for k in range(1, len(valid_pos)):
        ii = valid_pos[k]
        ip = valid_pos[k - 1]
        w_cur,  w_prev  = float(wma21.iloc[ii]), float(wma21.iloc[ip])
        s_cur,  s_prev  = float(sma30.iloc[ii]),  float(sma30.iloc[ip])
        fecha = df['fecha'].iloc[ii]
        price = float(closes.iloc[ii])

        if w_prev < s_prev and w_cur > s_cur:          # cruce alcista
            bull_crosses.append((fecha, price))
            ultimo_cruce = {'fecha': str(fecha)[:10], 'tipo': 'Alcista'}
        elif w_prev > s_prev and w_cur < s_cur:        # cruce bajista
            bear_crosses.append((fecha, price))
            ultimo_cruce = {'fecha': str(fecha)[:10], 'tipo': 'Bajista'}

    # Estado actual (último valor válido)
    wma_v = wma21.dropna()
    sma_v = sma30.dropna()
    if len(wma_v) > 0 and len(sma_v) > 0:
        estado = 'Alcista' if float(wma_v.iloc[-1]) > float(sma_v.iloc[-1]) else 'Bajista'
    else:
        estado = 'N/D'

    return dict(wma21=wma21, sma30=sma30,
                bull_crosses=bull_crosses, bear_crosses=bear_crosses,
                estado=estado, ultimo_cruce=ultimo_cruce)


# ── BUY_CONFIRMATION — cruce WMA21/SMA30 + confirmación RSI ──────────────────

def get_buy_confirmation(
    df: pd.DataFrame,
    sup: list | None = None,
    dyn_sup: list | None = None,
    sr_threshold: float = 0.02,
    lookback_oversold: int = 5,
) -> dict:
    """
    Señal compuesta BUY_CONFIRMATION.

    Condición principal:
      1. WMA21 cruza por encima de SMA30 (cruce alcista)
      Y además se cumple al menos una de:
      2A. RSI estuvo en sobreventa (<30) en los `lookback_oversold` días anteriores
          y está subiendo al momento del cruce.
      2B. RSI cruza hacia arriba el nivel 50 (RSI[t-1] < 50 y RSI[t] >= 50).

    Condición de fuerza:
      FUERTE → precio ≤ sr_threshold (2%) de un soporte estático o dinámico.
      MEDIA  → en caso contrario.

    Retorna dict:
      activo        : bool   — WMA21 sigue sobre SMA30 (señal no invalidada)
      fuerza        : 'FUERTE' | 'MEDIA' | None
      motivo        : list[str]
      cerca_soporte : bool
      fecha         : str | None
      price         : float | None
      signals       : list[dict]   — histórico de todas las señales detectadas
    """
    _empty = dict(activo=False, fuerza=None, motivo=[], cerca_soporte=False,
                  fecha=None, price=None, signals=[])
    if df.empty or len(df) < 30:
        return _empty

    closes = pd.to_numeric(df['close'], errors='coerce')
    rsi    = (pd.to_numeric(df['rsi14'], errors='coerce')
              if 'rsi14' in df.columns
              else pd.Series([float('nan')] * len(df), index=df.index))

    # WMA21
    _w    = np.arange(1, 22, dtype=float)
    _wsum = _w.sum()          # 231
    wma21 = closes.rolling(21).apply(lambda x: float(np.dot(x, _w) / _wsum), raw=True)

    # SMA30
    sma30 = closes.rolling(30).mean()

    # Consolidar niveles de soporte (estáticos + dinámicos)
    all_supports: list[float] = list(sup or [])
    for item in (dyn_sup or []):
        v = item.get('value') or item.get('vmin')
        if v is not None:
            all_supports.append(float(v))

    valid_pos = [i for i in range(len(df))
                 if pd.notna(wma21.iloc[i]) and pd.notna(sma30.iloc[i])]

    signals: list[dict] = []

    for k in range(1, len(valid_pos)):
        ii = valid_pos[k]
        ip = valid_pos[k - 1]

        w_cur, w_prev = float(wma21.iloc[ii]), float(wma21.iloc[ip])
        s_cur, s_prev = float(sma30.iloc[ii]),  float(sma30.iloc[ip])

        # Condición 1: cruce alcista WMA21 sobre SMA30
        if not (w_prev < s_prev and w_cur > s_cur):
            continue

        fecha = df['fecha'].iloc[ii]
        price = float(closes.iloc[ii])
        rsi_cur  = float(rsi.iloc[ii]) if pd.notna(rsi.iloc[ii]) else None
        rsi_prev = float(rsi.iloc[ip]) if pd.notna(rsi.iloc[ip]) else None

        # Condición RSI
        motivo = ['cruce WMA21/SMA30']
        rsi_ok = False

        # 2A: sobreventa reciente + RSI subiendo
        lb_start   = max(0, ii - lookback_oversold)
        rsi_window = rsi.iloc[lb_start: ii + 1].dropna()
        if (rsi_cur is not None and rsi_prev is not None
                and len(rsi_window) > 0
                and float(rsi_window.min()) < 30
                and rsi_cur > rsi_prev):
            motivo.append('RSI recuperación')
            rsi_ok = True

        # 2B: RSI cruza 50 al alza
        if (not rsi_ok and rsi_cur is not None and rsi_prev is not None
                and rsi_prev < 50 and rsi_cur >= 50):
            motivo.append('RSI > 50')
            rsi_ok = True

        if not rsi_ok:
            continue

        # Fuerza: cercanía a soporte
        cerca = (
            any(abs(price - s) / max(abs(price), 1e-9) <= sr_threshold
                for s in all_supports)
            if all_supports else False
        )

        signals.append(dict(
            fecha=str(fecha)[:10],
            price=price,
            fuerza='FUERTE' if cerca else 'MEDIA',
            motivo=list(motivo),
            cerca_soporte=cerca,
        ))

    if not signals:
        return _empty

    latest = signals[-1]

    # Activo si WMA21 sigue sobre SMA30 actualmente
    wma_v = wma21.dropna()
    sma_v = sma30.dropna()
    activo = (
        len(wma_v) > 0 and len(sma_v) > 0
        and float(wma_v.iloc[-1]) > float(sma_v.iloc[-1])
    )

    return dict(
        activo=activo,
        fuerza=latest['fuerza'],
        motivo=latest['motivo'],
        cerca_soporte=latest['cerca_soporte'],
        fecha=latest['fecha'],
        price=latest['price'],
        signals=signals,
    )


# ── Swing trading: WMA6 / WMA30 crossover ────────────────────────────────────

def get_swing_signal(df: pd.DataFrame, n_recent: int = 4) -> dict:
    """
    Señal de corto plazo basada en WMA6 / WMA30.

    WMA6 : media ponderada lineal de 6 períodos  (pesos 1..6,  suma=21).
    WMA30: media ponderada lineal de 30 períodos (pesos 1..30, suma=465).

    BUY_SWING  : WMA6[t-1] < WMA30[t-1]  y  WMA6[t] > WMA30[t]
    SELL_SWING : WMA6[t-1] > WMA30[t-1]  y  WMA6[t] < WMA30[t]

    Estado actual:
      'Compra'  → WMA6 > WMA30 (y no Neutral)
      'Venta'   → WMA6 < WMA30 (y no Neutral)
      'Neutral' → cruce ocurrió hace ≤ 2 barras  O  distancia < 0.3% del precio

    Returns dict:
      wma6           : pd.Series
      wma30          : pd.Series
      recent_crosses : list[dict]  — últimos `n_recent` cruces (para markers gráfico)
      estado         : 'Compra' | 'Venta' | 'Neutral' | 'N/D'
      ultimo_cruce   : {'fecha', 'tipo'} | None
    """
    _empty = dict(wma6=pd.Series(dtype=float), wma30=pd.Series(dtype=float),
                  recent_crosses=[], estado='N/D', ultimo_cruce=None)
    if df.empty or len(df) < 30:
        return _empty

    closes = pd.to_numeric(df['close'], errors='coerce')

    # WMA6 — pesos [1..6], suma=21
    _w6    = np.arange(1, 7,  dtype=float)
    _w6s   = _w6.sum()
    wma6   = closes.rolling(6).apply(lambda x: float(np.dot(x, _w6) / _w6s), raw=True)

    # WMA30 — pesos [1..30], suma=465
    _w30   = np.arange(1, 31, dtype=float)
    _w30s  = _w30.sum()
    wma30  = closes.rolling(30).apply(lambda x: float(np.dot(x, _w30) / _w30s), raw=True)

    valid_pos = [i for i in range(len(df))
                 if pd.notna(wma6.iloc[i]) and pd.notna(wma30.iloc[i])]

    all_crosses: list[dict] = []
    for k in range(1, len(valid_pos)):
        ii = valid_pos[k]
        ip = valid_pos[k - 1]
        w6_cur,  w6_prev  = float(wma6.iloc[ii]),  float(wma6.iloc[ip])
        w30_cur, w30_prev = float(wma30.iloc[ii]), float(wma30.iloc[ip])
        fecha = df['fecha'].iloc[ii]
        price = float(closes.iloc[ii])

        if w6_prev < w30_prev and w6_cur > w30_cur:
            all_crosses.append(dict(fecha=str(fecha)[:10], price=price,
                                    tipo='BUY_SWING',  pos=ii))
        elif w6_prev > w30_prev and w6_cur < w30_cur:
            all_crosses.append(dict(fecha=str(fecha)[:10], price=price,
                                    tipo='SELL_SWING', pos=ii))

    ultimo_cruce = all_crosses[-1] if all_crosses else None

    # Estado actual
    wma6_v       = wma6.dropna()
    wma30_v      = wma30.dropna()
    closes_clean = closes.dropna()
    if len(wma6_v) > 0 and len(wma30_v) > 0 and len(closes_clean) > 0:
        v6         = float(wma6_v.iloc[-1])
        v30        = float(wma30_v.iloc[-1])
        price_last = float(closes_clean.iloc[-1])
        bars_since = (len(df) - 1 - ultimo_cruce['pos']) if ultimo_cruce else 999
        near_zero  = abs(v6 - v30) / max(price_last, 1e-9) < 0.003
        if near_zero or bars_since <= 2:
            estado = 'Neutral'
        elif v6 > v30:
            estado = 'Compra'
        else:
            estado = 'Venta'
    else:
        estado = 'N/D'

    recent_crosses = all_crosses[-n_recent:] if all_crosses else []

    return dict(
        wma6=wma6, wma30=wma30,
        recent_crosses=recent_crosses,
        estado=estado,
        ultimo_cruce=ultimo_cruce,
    )


# ── Early swing: anticipar cruce WMA6/WMA30 ──────────────────────────────────

def get_early_swing_signal(
    df: pd.DataFrame,
    dyn_res: list | None = None,
    static_res: list | None = None,
    gap_threshold: float = 0.005,
    res_threshold: float = 0.015,
    vol_lookback: int = 20,
    max_signals: int = 5,
) -> dict:
    """
    Dos estrategias de corto plazo sobre WMA6/WMA30 (capa adicional).

    BUY_EARLY_SWING — compra anticipada (1 dia antes del cruce alcista):
      1. Tendencia alcista: precio > SMA200  o  SMA50 > SMA200
      2. WMA6 < WMA30 (aun no cruzo)
      3. Gap % = (WMA30 - WMA6) / WMA30 < gap_threshold (muy cerca del cruce)
      4. Gap hoy < gap ayer  (brecha cerrandose)
      5. WMA6 hoy > WMA6 ayer (pendiente alcista)
      6. Precio hoy >= precio ayer (confirmacion)
      7. Sin resistencia dentro de res_threshold por encima del precio

    BUY_EARLY_SWING_STRONG: idem + volumen comprador
      vol > avg_vol_N  AND  (close > open  OR  close > close_prev con vol > vol_prev)

    SELL_SWING_CROSS:
      WMA6[i-1] > WMA30[i-1]  AND  WMA6[i] < WMA30[i]  (cruce bajista exacto)

    Returns dict:
      estado             : 'COMPRA' | 'COMPRA_FUERTE' | 'VENTA' | 'NEUTRAL'
      senal_activa       : 'BUY_EARLY_SWING' | 'BUY_EARLY_SWING_STRONG' |
                           'SELL_SWING_CROSS' | None
      fuerza             : 'FUERTE' | 'MEDIA' | None
      volumen_comprador  : bool  (estado actual del ultimo bar)
      resistencia_cercana: bool  (estado actual)
      tendencia_alcista  : bool  (estado actual)
      buy_markers        : list[dict]  — señales alcistas para el grafico
      sell_markers       : list[dict]  — señales bajistas para el grafico
      fecha_senal        : str | None
    """
    _empty = dict(
        estado='NEUTRAL', senal_activa=None, fuerza=None,
        volumen_comprador=False, resistencia_cercana=False,
        tendencia_alcista=False, buy_markers=[], sell_markers=[],
        fecha_senal=None,
    )
    if df.empty or len(df) < 31:
        return _empty

    closes = pd.to_numeric(df['close'],  errors='coerce')
    opens  = pd.to_numeric(df['open'],   errors='coerce')
    vols   = pd.to_numeric(df['volume'], errors='coerce')

    # WMA6 — pesos [1..6], suma=21
    _w6  = np.arange(1,  7, dtype=float); _w6s  = _w6.sum()
    wma6  = closes.rolling(6).apply(lambda x: float(np.dot(x, _w6)  / _w6s),  raw=True)

    # WMA30 — pesos [1..30], suma=465
    _w30 = np.arange(1, 31, dtype=float); _w30s = _w30.sum()
    wma30 = closes.rolling(30).apply(lambda x: float(np.dot(x, _w30) / _w30s), raw=True)

    # SMA50 / SMA200 para filtro de tendencia
    sma50  = (pd.to_numeric(df['sma50'],  errors='coerce')
              if 'sma50'  in df.columns else closes.rolling(50).mean())
    sma200 = (pd.to_numeric(df['sma200'], errors='coerce')
              if 'sma200' in df.columns else closes.rolling(200).mean())

    vol_avg = vols.rolling(vol_lookback).mean()

    # Resistencias consolidadas
    all_res: list[float] = list(static_res or [])
    for item in (dyn_res or []):
        v = item.get('value')
        if v is not None:
            all_res.append(float(v))

    valid_pos = [i for i in range(len(df))
                 if pd.notna(wma6.iloc[i]) and pd.notna(wma30.iloc[i])]

    buy_markers:  list[dict] = []
    sell_markers: list[dict] = []

    for k in range(1, len(valid_pos)):
        ii = valid_pos[k]
        ip = valid_pos[k - 1]

        w6_cur,  w6_prev  = float(wma6.iloc[ii]),  float(wma6.iloc[ip])
        w30_cur, w30_prev = float(wma30.iloc[ii]), float(wma30.iloc[ip])
        price   = float(closes.iloc[ii])
        price_p = float(closes.iloc[ip]) if pd.notna(closes.iloc[ip]) else price
        open_i  = float(opens.iloc[ii])  if pd.notna(opens.iloc[ii])  else price
        vol_i   = float(vols.iloc[ii])   if pd.notna(vols.iloc[ii])   else 0.0
        vol_p   = float(vols.iloc[ip])   if pd.notna(vols.iloc[ip])   else 0.0
        vavg_i  = float(vol_avg.iloc[ii]) if pd.notna(vol_avg.iloc[ii]) else 0.0
        fecha   = df['fecha'].iloc[ii]

        # ── SELL_SWING_CROSS: cruce bajista exacto ──────────────────────────
        if w6_prev > w30_prev and w6_cur < w30_cur:
            sell_markers.append(dict(fecha=str(fecha)[:10], price=price))
            continue

        # ── BUY_EARLY_SWING: anticipacion cruce alcista ──────────────────────
        if w6_cur >= w30_cur:
            continue   # ya cruzo → no es "anticipado"

        gap_cur  = (w30_cur  - w6_cur)  / max(w30_cur,  1e-9)
        gap_prev = (w30_prev - w6_prev) / max(w30_prev, 1e-9)

        if not (gap_cur  < gap_threshold    # brecha muy pequeña
                and gap_cur  < gap_prev     # brecha cerrandose
                and w6_cur   > w6_prev      # WMA6 con pendiente alcista
                and price    >= price_p):   # precio confirma
            continue

        # Tendencia alcista de fondo
        s50_i  = float(sma50.iloc[ii])  if pd.notna(sma50.iloc[ii])  else None
        s200_i = float(sma200.iloc[ii]) if pd.notna(sma200.iloc[ii]) else None
        trend_up = (
            (s200_i is not None and price > s200_i) or
            (s50_i is not None and s200_i is not None and s50_i > s200_i)
        )
        if not trend_up:
            continue

        # Sin resistencia bloqueante
        res_near = any(
            0 < (r - price) / max(price, 1e-9) <= res_threshold
            for r in all_res
        ) if all_res else False
        if res_near:
            continue

        # Volumen comprador
        vol_buyer = (
            vavg_i > 0 and vol_i > vavg_i and
            (price > open_i or (price > price_p and vol_i > vol_p))
        )

        buy_markers.append(dict(
            fecha=str(fecha)[:10],
            price=price,
            strong=vol_buyer,
            tipo='BUY_EARLY_SWING_STRONG' if vol_buyer else 'BUY_EARLY_SWING',
        ))

    # ── Estado actual (ultimo bar) ────────────────────────────────────────────
    estado       = 'NEUTRAL'
    senal_activa = None
    fuerza       = None
    fecha_senal  = None

    if len(valid_pos) >= 2:
        ii_l = valid_pos[-1]
        ip_l = valid_pos[-2]

        w6_l,  w6_pl  = float(wma6.iloc[ii_l]),  float(wma6.iloc[ip_l])
        w30_l, w30_pl = float(wma30.iloc[ii_l]), float(wma30.iloc[ip_l])
        price_l  = float(closes.iloc[ii_l])
        price_pl = float(closes.iloc[ip_l]) if pd.notna(closes.iloc[ip_l]) else price_l
        open_l   = float(opens.iloc[ii_l])  if pd.notna(opens.iloc[ii_l])  else price_l
        vol_l    = float(vols.iloc[ii_l])   if pd.notna(vols.iloc[ii_l])   else 0.0
        vol_pl   = float(vols.iloc[ip_l])   if pd.notna(vols.iloc[ip_l])   else 0.0
        vavg_l   = float(vol_avg.iloc[ii_l]) if pd.notna(vol_avg.iloc[ii_l]) else 0.0
        fecha_l  = str(df['fecha'].iloc[ii_l])[:10]

        # SELL_SWING_CROSS hoy
        if w6_pl > w30_pl and w6_l < w30_l:
            senal_activa = 'SELL_SWING_CROSS'
            estado       = 'VENTA'
            fecha_senal  = fecha_l

        # BUY_EARLY_SWING hoy
        elif w6_l < w30_l:
            gap_l  = (w30_l  - w6_l)  / max(w30_l,  1e-9)
            gap_pl = (w30_pl - w6_pl) / max(w30_pl, 1e-9)

            if (gap_l  < gap_threshold
                    and gap_l  < gap_pl
                    and w6_l   > w6_pl
                    and price_l >= price_pl):

                s50_lv  = float(sma50.iloc[ii_l])  if pd.notna(sma50.iloc[ii_l])  else None
                s200_lv = float(sma200.iloc[ii_l]) if pd.notna(sma200.iloc[ii_l]) else None
                trend_l = (
                    (s200_lv is not None and price_l > s200_lv) or
                    (s50_lv  is not None and s200_lv is not None and s50_lv > s200_lv)
                )

                if trend_l:
                    res_l = any(0 < (r - price_l) / max(price_l, 1e-9) <= res_threshold
                                for r in all_res) if all_res else False
                    if not res_l:
                        vol_bl = (vavg_l > 0 and vol_l > vavg_l and
                                  (price_l > open_l or (price_l > price_pl and vol_l > vol_pl)))
                        senal_activa = 'BUY_EARLY_SWING_STRONG' if vol_bl else 'BUY_EARLY_SWING'
                        fuerza       = 'FUERTE' if vol_bl else 'MEDIA'
                        estado       = 'COMPRA_FUERTE' if vol_bl else 'COMPRA'
                        fecha_senal  = fecha_l

    # ── Condiciones actuales para el panel ───────────────────────────────────
    _ii = valid_pos[-1] if valid_pos else (len(df) - 1)
    price_now = float(closes.iloc[_ii]) if pd.notna(closes.iloc[_ii]) else 0.0
    open_now  = float(opens.iloc[_ii])  if pd.notna(opens.iloc[_ii])  else price_now
    vol_now   = float(vols.iloc[_ii])   if pd.notna(vols.iloc[_ii])   else 0.0
    vol_pn    = float(vols.iloc[_ii - 1])   if _ii > 0 and pd.notna(vols.iloc[_ii - 1])   else 0.0
    price_pn  = float(closes.iloc[_ii - 1]) if _ii > 0 and pd.notna(closes.iloc[_ii - 1]) else price_now
    vavg_now  = float(vol_avg.iloc[_ii]) if pd.notna(vol_avg.iloc[_ii]) else 0.0
    s50_now   = float(sma50.iloc[_ii])  if pd.notna(sma50.iloc[_ii])  else None
    s200_now  = float(sma200.iloc[_ii]) if pd.notna(sma200.iloc[_ii]) else None

    vol_buyer_now = (
        vavg_now > 0 and vol_now > vavg_now and
        (price_now > open_now or (price_now > price_pn and vol_now > vol_pn))
    ) if price_now > 0 else False

    res_near_now = (
        any(0 < (r - price_now) / max(price_now, 1e-9) <= res_threshold
            for r in all_res)
        if (all_res and price_now > 0) else False
    )

    trend_now = (
        (s200_now is not None and price_now > s200_now) or
        (s50_now is not None and s200_now is not None and s50_now > s200_now)
    ) if price_now > 0 else False

    return dict(
        estado=estado,
        senal_activa=senal_activa,
        fuerza=fuerza,
        volumen_comprador=vol_buyer_now,
        resistencia_cercana=res_near_now,
        tendencia_alcista=trend_now,
        buy_markers=buy_markers[-max_signals:],
        sell_markers=sell_markers[-max_signals:],
        fecha_senal=fecha_senal,
    )


# ── S/R estático: zonas basadas en pivot HIGH/LOW ────────────────────────────

def _pivot_sr_zones(
    df: pd.DataFrame,
    window: int = 10,
    tol: float = 0.008,
    n: int = 4,
) -> tuple[list[dict], list[dict]]:
    """
    Detecta zonas de S/R estático usando pivots HIGH/LOW.

    Pivot low:  low[i] == min(low[i-window..i+window])  → soporte
    Pivot high: high[i] == max(high[i-window..i+window]) → resistencia

    Agrupa niveles cercanos (±tol) en zonas y cuenta toques reales (velas).
    Aplica cambio de polaridad: zonas rotas se marcan con role_reversal=True.

    Returns (sup_zones, res_zones) — listas de dict:
      {'value': float, 'zone_min': float, 'zone_max': float,
       'touches': int, 'strength': 'weak'|'medium'|'strong',
       'role_reversal': bool}
    """
    if len(df) < window * 2 + 1:
        return [], []

    highs  = pd.to_numeric(df['high'],  errors='coerce')
    lows   = pd.to_numeric(df['low'],   errors='coerce')
    closes = pd.to_numeric(df['close'], errors='coerce')
    cur    = float(closes.iloc[-1])

    raw_sup: list[float] = []
    raw_res: list[float] = []

    for i in range(window, len(df) - window):
        lo = lows.iat[i]
        hi = highs.iat[i]
        if pd.isna(lo) or pd.isna(hi):
            continue
        lo_win = lows.iloc[i - window: i + window + 1]
        hi_win = highs.iloc[i - window: i + window + 1]
        if lo <= lo_win.min():
            raw_sup.append(float(lo))
        if hi >= hi_win.max():
            raw_res.append(float(hi))

    def _cluster_to_zones(levels: list[float]) -> list[dict]:
        if not levels:
            return []
        levels = sorted(levels)
        zones: list[list[float]] = [[levels[0]]]
        for lv in levels[1:]:
            center = sum(zones[-1]) / len(zones[-1])
            if abs(lv - center) / max(center, 1e-9) <= tol:
                zones[-1].append(lv)
            else:
                zones.append([lv])
        result = []
        for zl in zones:
            z_min, z_max = min(zl), max(zl)
            z_mid = (z_min + z_max) / 2
            # Contar velas que tocaron la zona
            candle_touches = int(
                ((highs >= z_min * (1 - tol)) & (lows <= z_max * (1 + tol))).sum()
            )
            touches  = max(len(zl), candle_touches)
            strength = 'strong' if touches >= 3 else 'medium' if touches >= 2 else 'weak'
            result.append({
                'value':    z_mid,
                'zone_min': z_min * (1 - tol / 2),
                'zone_max': z_max * (1 + tol / 2),
                'touches':  touches,
                'strength': strength,
                'role_reversal': False,
            })
        return result

    sup_zones = _cluster_to_zones(raw_sup)
    res_zones = _cluster_to_zones(raw_res)

    # Cambio de polaridad: zona de resistencia rota (ahora debajo) → soporte
    rr_sup = []
    for z in res_zones:
        if z['value'] < cur * 0.998:
            rr_sup.append({**z, 'role_reversal': True})
    # Cambio de polaridad: zona de soporte rota (ahora encima) → resistencia
    rr_res = []
    for z in sup_zones:
        if z['value'] > cur * 1.002:
            rr_res.append({**z, 'role_reversal': True})

    final_sup = sorted(
        [z for z in sup_zones if z['value'] < cur * 0.998] + rr_sup,
        key=lambda x: x['value'], reverse=True,
    )[:n]

    final_res = sorted(
        [z for z in res_zones if z['value'] > cur * 1.002] + rr_res,
        key=lambda x: x['value'],
    )[:n]

    return final_sup, final_res


def get_support_resistance(df: pd.DataFrame, window: int = 10, n: int = 4) -> tuple[list, list]:
    """
    Detecta soportes y resistencias estáticos usando pivots HIGH/LOW.
    Retorna (supports, resistances) — listas de float (midpoints de zona).
    Público: llamable desde app.py y estrategias para verificar proximidad.
    """
    sup_z, res_z = _pivot_sr_zones(df, window=window, n=n)
    return [z['value'] for z in sup_z], [z['value'] for z in res_z]


def price_chart(df: pd.DataFrame, simbolo: str = '', tf: str = '3M',
                dyn_sup: list | None = None,
                dyn_res: list | None = None,
                wma_data: dict | None = None,
                buy_conf_data: dict | None = None,
                swing_data: dict | None = None,
                early_swing_data: dict | None = None,
                show_sma50: bool = True,
                show_sma200: bool = True,
                show_ema20: bool = True,
                show_volume: bool = True,
                show_static_sr: bool = True,
                show_wma6: bool = True,
                show_wma30: bool = True,
                candle_freq: str = 'D') -> go.Figure:
    """
    Candlestick + MAs opcionales + S/R + Volumen opcional.
    Flags show_* permiten activar/desactivar cada capa individualmente.
    candle_freq: 'D'/'W'/'M'/'Y' — se usa para ajustar ticks del eje X.
    """
    # Zonas estáticas (necesitamos los dicts completos para renderizar hrect)
    sup_zones, res_zones = (
        _pivot_sr_zones(df) if (len(df) > 40 and show_static_sr) else ([], [])
    )

    n_rows     = 2 if show_volume else 1
    row_h      = [0.78, 0.22] if show_volume else [1.0]
    fig = make_subplots(
        rows=n_rows, cols=1, shared_xaxes=True,
        row_heights=row_h,
        vertical_spacing=0.02,
    )

    x0, x1 = df['fecha'].iloc[0], df['fecha'].iloc[-1]

    # ── S/R estático: zonas coloreadas (hrect) ────────────────────────────────
    for z in sup_zones:
        alpha  = 0.18 if z['strength'] == 'strong' else 0.10
        border = C['green'] if not z.get('role_reversal') else C['orange']
        fig.add_shape(
            type='rect', x0=x0, x1=x1,
            y0=z['zone_min'], y1=z['zone_max'],
            fillcolor=f"rgba(16,185,129,{alpha})",
            line=dict(color=border, width=0.8),
            row=1, col=1,
        )

    for z in res_zones:
        alpha  = 0.18 if z['strength'] == 'strong' else 0.10
        border = C['red'] if not z.get('role_reversal') else C['orange']
        fig.add_shape(
            type='rect', x0=x0, x1=x1,
            y0=z['zone_min'], y1=z['zone_max'],
            fillcolor=f"rgba(239,68,68,{alpha})",
            line=dict(color=border, width=0.8),
            row=1, col=1,
        )

    # ── S/R dinámico: trendlines diagonales (pivot lows/highs) ───────────────
    _DYN_S = 'rgba(16,185,129,0.75)'
    _DYN_R = 'rgba(239,68,68,0.75)'

    for item in (dyn_sup or []):
        if item.get('status') == 'broken':
            color, dash = 'rgba(16,185,129,0.35)', 'dot'
        else:
            color, dash = _DYN_S, 'dash'
        lw = 1.5 if item.get('fuerza') == 'alta' else 1.0
        # Línea desde p1 hasta el último bar (proyectada)
        p1 = item['p1']
        fig.add_shape(
            type='line',
            x0=p1['time'], y0=p1['price'],
            x1=x1,        y1=item['value'],
            line=dict(color=color, width=lw, dash=dash),
            row=1, col=1,
        )

    for item in (dyn_res or []):
        if item.get('status') == 'broken':
            color, dash = 'rgba(239,68,68,0.35)', 'dot'
        else:
            color, dash = _DYN_R, 'dash'
        lw = 1.5 if item.get('fuerza') == 'alta' else 1.0
        p1 = item['p1']
        fig.add_shape(
            type='line',
            x0=p1['time'], y0=p1['price'],
            x1=x1,        y1=item['value'],
            line=dict(color=color, width=lw, dash=dash),
            row=1, col=1,
        )

    # ── Candlestick ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df['fecha'],
        open=df['open'], high=df['high'],
        low=df['low'],  close=df['close'],
        name='', showlegend=False,
        increasing=dict(line=dict(color=C['green'], width=1),
                        fillcolor=C['green']),
        decreasing=dict(line=dict(color=C['red'],   width=1),
                        fillcolor=C['red']),
    ), row=1, col=1)

    # ── Moving averages ───────────────────────────────────────────────────────
    _show_ma = {
        'ema20':  show_ema20,
        'sma50':  show_sma50,
        'sma200': show_sma200,
    }
    ma_cfg = [
        ('ema20',  C['purple'], 'EMA 20',  1.2),
        ('sma50',  C['blue'],   'SMA 50',  1.2),
        ('sma200', C['orange'], 'SMA 200', 1.4),
    ]
    for col, color, name, width in ma_cfg:
        if not _show_ma.get(col, True):
            continue
        series = pd.to_numeric(df.get(col, pd.Series()), errors='coerce')
        if series.notna().sum() >= 2:
            fig.add_trace(go.Scatter(
                x=df['fecha'], y=series, name=name,
                line=dict(color=color, width=width),
                opacity=0.85, hovertemplate=f'{name}: %{{y:.2f}}<extra></extra>',
            ), row=1, col=1)

    # ── Volumen (opcional) ────────────────────────────────────────────────────
    if show_volume:
        vol = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
        bar_colors = [C['green'] if float(c) >= float(o) else C['red']
                      for c, o in zip(df['close'], df['open'])]
        fig.add_trace(go.Bar(
            x=df['fecha'], y=vol, name='Vol',
            marker=dict(color=bar_colors, opacity=0.45),
            showlegend=False,
            hovertemplate='Vol: %{y:,.0f}<extra></extra>',
        ), row=2, col=1)

    # ── WMA21 / SMA30 (capa adicional — no toca MAs existentes) ──────────────
    if wma_data:
        wma21 = wma_data.get('wma21', pd.Series(dtype=float))
        sma30 = wma_data.get('sma30', pd.Series(dtype=float))

        if wma21.notna().sum() >= 2:
            fig.add_trace(go.Scatter(
                x=df['fecha'], y=wma21, name='WMA 21',
                line=dict(color=C['cyan'], width=1.2),
                opacity=0.9,
                hovertemplate='WMA 21: %{y:.2f}<extra></extra>',
            ), row=1, col=1)

        if sma30.notna().sum() >= 2:
            fig.add_trace(go.Scatter(
                x=df['fecha'], y=sma30, name='SMA 30',
                line=dict(color=C['lime'], width=1.2),
                opacity=0.9,
                hovertemplate='SMA 30: %{y:.2f}<extra></extra>',
            ), row=1, col=1)

        # Cruces alcistas: triángulo verde hacia arriba, debajo de la vela
        bull = wma_data.get('bull_crosses', [])
        if bull:
            fig.add_trace(go.Scatter(
                x=[c[0] for c in bull],
                y=[c[1] * 0.975 for c in bull],
                mode='markers', name='Cruce ↑',
                marker=dict(symbol='triangle-up', size=11,
                            color=C['green'],
                            line=dict(color='white', width=0.8)),
                hovertemplate='Cruce alcista: %{x}<extra></extra>',
            ), row=1, col=1)

        # Cruces bajistas: triángulo rojo hacia abajo, encima de la vela
        bear = wma_data.get('bear_crosses', [])
        if bear:
            fig.add_trace(go.Scatter(
                x=[c[0] for c in bear],
                y=[c[1] * 1.025 for c in bear],
                mode='markers', name='Cruce ↓',
                marker=dict(symbol='triangle-down', size=11,
                            color=C['red'],
                            line=dict(color='white', width=0.8)),
                hovertemplate='Cruce bajista: %{x}<extra></extra>',
            ), row=1, col=1)

    # ── BUY_CONFIRMATION markers (capa adicional — siempre visible) ──────────
    if buy_conf_data and buy_conf_data.get('signals'):
        _sigs   = buy_conf_data['signals']
        _bc_x   = [s['fecha']  for s in _sigs]
        _bc_y   = [s['price'] * 0.963 for s in _sigs]
        _bc_clr = ['#fbbf24' if s['fuerza'] == 'FUERTE' else '#fb923c' for s in _sigs]
        _bc_cd  = [(s['fuerza'], ', '.join(s['motivo'])) for s in _sigs]
        fig.add_trace(go.Scatter(
            x=_bc_x, y=_bc_y,
            mode='markers', name='BUY_CONF',
            marker=dict(symbol='star', size=13, color=_bc_clr,
                        line=dict(color='white', width=0.8)),
            customdata=_bc_cd,
            hovertemplate=(
                '<b>BUY_CONFIRMATION</b><br>'
                'Fuerza: %{customdata[0]}<br>'
                'Motivo: %{customdata[1]}<extra></extra>'
            ),
        ), row=1, col=1)

    # ── Swing: WMA6/WMA30 + cruces recientes (controlado por show_wma6/show_wma30) ──
    if swing_data:
        _sw6  = swing_data.get('wma6',  pd.Series(dtype=float))
        _sw30 = swing_data.get('wma30', pd.Series(dtype=float))

        if show_wma6 and _sw6.notna().sum() >= 2:
            fig.add_trace(go.Scatter(
                x=df['fecha'], y=_sw6, name='WMA 6',
                line=dict(color='#f97316', width=1.0),
                opacity=0.60,
                hovertemplate='WMA 6: %{y:.2f}<extra></extra>',
            ), row=1, col=1)

        if show_wma30 and _sw30.notna().sum() >= 2:
            fig.add_trace(go.Scatter(
                x=df['fecha'], y=_sw30, name='WMA 30',
                line=dict(color='#60a5fa', width=1.0),
                opacity=0.60,
                hovertemplate='WMA 30: %{y:.2f}<extra></extra>',
            ), row=1, col=1)

        if show_wma6 and show_wma30:
            for cross in swing_data.get('recent_crosses', []):
                _is_buy = cross['tipo'] == 'BUY_SWING'
                fig.add_trace(go.Scatter(
                    x=[cross['fecha']],
                    y=[cross['price'] * (0.972 if _is_buy else 1.028)],
                    mode='markers',
                    name=cross['tipo'],
                    showlegend=False,
                    marker=dict(
                        symbol='triangle-up' if _is_buy else 'triangle-down',
                        size=9,
                        color=C['green'] if _is_buy else C['red'],
                        line=dict(color='white', width=0.6),
                    ),
                    hovertemplate=(
                        f"{'BUY_SWING' if _is_buy else 'SELL_SWING'}: "
                        f"{cross['fecha']}<extra></extra>"
                    ),
                ), row=1, col=1)

    # ── Early swing markers (BUY_EARLY_SWING / SELL_SWING_CROSS) ────────────
    # Capa adicional — usa las mismas lineas WMA6/WMA30 del bloque swing_data
    if early_swing_data:
        buy_m  = early_swing_data.get('buy_markers',  [])
        sell_m = early_swing_data.get('sell_markers', [])

        # BUY_EARLY_SWING: circulo vacio verde (sin volumen especial)
        reg = [m for m in buy_m if not m.get('strong')]
        if reg:
            fig.add_trace(go.Scatter(
                x=[m['fecha'] for m in reg],
                y=[m['price'] * 0.971 for m in reg],
                mode='markers', name='BUY_EARLY_SWING',
                showlegend=False,
                marker=dict(symbol='circle-open', size=11,
                            color='#22c55e',
                            line=dict(color='#22c55e', width=2.0)),
                hovertemplate='BUY_EARLY_SWING: %{x}<extra></extra>',
            ), row=1, col=1)

        # BUY_EARLY_SWING_STRONG: circulo relleno verde brillante
        strong = [m for m in buy_m if m.get('strong')]
        if strong:
            fig.add_trace(go.Scatter(
                x=[m['fecha'] for m in strong],
                y=[m['price'] * 0.971 for m in strong],
                mode='markers', name='BUY_EARLY_STRONG',
                showlegend=False,
                marker=dict(symbol='circle', size=13,
                            color='#4ade80',
                            line=dict(color='white', width=0.8)),
                hovertemplate='BUY_EARLY_SWING_STRONG: %{x}<extra></extra>',
            ), row=1, col=1)

        # SELL_SWING_CROSS: X roja
        if sell_m:
            fig.add_trace(go.Scatter(
                x=[m['fecha'] for m in sell_m],
                y=[m['price'] * 1.029 for m in sell_m],
                mode='markers', name='SELL_SWING_CROSS',
                showlegend=False,
                marker=dict(symbol='x', size=11,
                            color=C['red'],
                            line=dict(color=C['red'], width=2.0)),
                hovertemplate='SELL_SWING_CROSS: %{x}<extra></extra>',
            ), row=1, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    layout = _base(height=520)
    layout['title'] = dict(
        text=f'<span style="font-size:14px;font-weight:700;color:{C["text"]}">{simbolo}</span>',
        x=0.01, xanchor='left',
    )
    layout['xaxis_rangeslider_visible'] = False
    if show_volume:
        layout['yaxis2'] = dict(
            showgrid=False, zeroline=False, showticklabels=False,
            side='right', showline=False,
        )
    layout['plot_bgcolor'] = C['panel2']

    fig.update_layout(**layout)

    # Aplicar ticks: ocultar row 2 solo si existe el panel de volumen
    _apply_date_ticks(fig, df, tf,
                      hide_labels_row=(2 if show_volume else None),
                      candle_freq=candle_freq)

    return fig


def rsi_chart(df: pd.DataFrame, tf: str = '3M') -> go.Figure:
    rsi = pd.to_numeric(df['rsi14'], errors='coerce')

    fig = go.Figure()
    fig.add_hrect(y0=70, y1=100, fillcolor='rgba(239,68,68,0.06)',   line_width=0)
    fig.add_hrect(y0=0,  y1=30,  fillcolor='rgba(16,185,129,0.06)', line_width=0)

    for y, color, dash in [(70, C['red'], 'dash'), (30, C['green'], 'dash'), (50, C['gray'], 'dot')]:
        fig.add_hline(y=y, line_color=color, line_dash=dash,
                      line_width=0.8, opacity=0.6)

    fig.add_trace(go.Scatter(
        x=df['fecha'], y=rsi,
        name='RSI 14',
        line=dict(color=C['blue'], width=1.5),
        fill='tozeroy',
        fillcolor='rgba(59,130,246,0.06)',
        hovertemplate='RSI: %{y:.1f}<extra></extra>',
    ))

    layout = _base(height=180)
    layout['yaxis']['range'] = [0, 100]
    layout['yaxis']['side']  = 'right'
    layout['margin'] = dict(l=10, r=60, t=20, b=30)
    layout['showlegend'] = False
    fig.update_layout(**layout)
    _apply_date_ticks(fig, df, tf)
    return fig


def momentum_chart(df: pd.DataFrame, tf: str = '3M') -> go.Figure:
    mom = pd.to_numeric(df['mom_12_1'], errors='coerce') * 100
    rs  = pd.to_numeric(df['rs_sector'], errors='coerce')

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.5],
        vertical_spacing=0.06,
        subplot_titles=[
            f'<span style="color:{C["text2"]};font-size:10px">MOMENTUM 12-1 (%)</span>',
            f'<span style="color:{C["text2"]};font-size:10px">RS SECTOR</span>',
        ],
    )

    fig.add_hline(y=0, line_color=C['gray'], line_dash='solid',
                  line_width=0.8, opacity=0.5, row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=mom, name='Mom 12-1',
        line=dict(color=C['green'], width=1.4),
        fill='tozeroy',
        fillcolor='rgba(16,185,129,0.07)',
        hovertemplate='Mom 12-1: %{y:.1f}%<extra></extra>',
    ), row=1, col=1)

    fig.add_hline(y=0, line_color=C['gray'], line_dash='solid',
                  line_width=0.8, opacity=0.5, row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=rs, name='RS Sector',
        line=dict(color=C['orange'], width=1.4),
        fill='tozeroy',
        fillcolor='rgba(245,158,11,0.07)',
        hovertemplate='RS: %{y:.3f}<extra></extra>',
    ), row=2, col=1)

    layout = _base(height=300)
    layout['margin']     = dict(l=10, r=60, t=28, b=30)
    layout['showlegend'] = False
    layout['yaxis2'] = dict(
        showgrid=True, gridcolor=C['grid'], zeroline=False,
        side='right', tickfont=dict(size=10, color=C['text2']),
    )
    fig.update_layout(**layout)
    # hide row 1 (momentum), mostrar fechas solo en row 2 (RS sector, fila inferior)
    _apply_date_ticks(fig, df, tf, hide_labels_row=1)
    return fig
