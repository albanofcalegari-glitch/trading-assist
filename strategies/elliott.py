"""
elliott.py  --  Detección automática de Ondas de Elliott + señales

Módulo standalone, no toca ninguna estrategia existente.

Algoritmo:
  1. Zigzag adaptativo (ATR-based) para encontrar pivots significativos.
  2. Pattern matching sobre la secuencia de pivots para contar ondas
     (5 impulso + 3 correctivas).
  3. Validación con las 3 reglas inviolables de Elliott.
  4. Scoring por proximidad a ratios Fibonacci.
  5. Señales (BUY/SELL/HOLD) según la posición en el ciclo.

Función pública:
    analyze_elliott(symbol, fecha=today) -> dict
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db.connection import get_conn

# ── Constantes ──────────────────────────────────────────────────────────────

ZIGZAG_PCT         = 5.0
ATR_PERIOD         = 14
ATR_MULTIPLIER     = 2.5
MIN_BARS_BETWEEN   = 5
MIN_BARS_DATA      = 120
FIB_TOLERANCE      = 0.12
MAX_WAVE_ORIGINS   = 10
LOOKBACK_BARS      = 500

# Fibonacci ideales
FIB_WAVE2_RETRACE  = [0.500, 0.618, 0.786]
FIB_WAVE3_EXTEND   = [1.618, 2.000, 2.618]
FIB_WAVE4_RETRACE  = [0.236, 0.382, 0.500]
FIB_WAVE5_EXTEND   = [0.618, 1.000, 1.618]
FIB_WAVEA_RETRACE  = [0.382, 0.500, 0.618]
FIB_WAVEB_RETRACE  = [0.382, 0.500, 0.618]
FIB_WAVEC_EXTEND   = [0.618, 1.000, 1.618]


# ── Carga de datos ──────────────────────────────────────────────────────────

def _load_ohlcv(symbol: str, fecha: date, n: int = LOOKBACK_BARS) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = 'D' AND fecha <= %s
                   ORDER BY fecha DESC
                   LIMIT %s""",
                (symbol, fecha, n),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    rows.reverse()
    return rows


# ── ATR ─────────────────────────────────────────────────────────────────────

def _compute_atr(rows: list[dict], period: int = ATR_PERIOD) -> float:
    if len(rows) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(rows)):
        h = float(rows[i]['high'])
        l = float(rows[i]['low'])
        pc = float(rows[i - 1]['close'])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


# ── Zigzag adaptativo ──────────────────────────────────────────────────────

def _zigzag(rows: list[dict], threshold_pct: float = ZIGZAG_PCT) -> list[dict]:
    """
    Zigzag porcentual con alternancia estricta high/low garantizada.
    Retorna lista de {'index': int, 'fecha': str, 'price': float, 'type': 'high'|'low'}
    """
    if len(rows) < 3:
        return []

    atr = _compute_atr(rows)
    last_close = float(rows[-1]['close'])
    if last_close > 0 and atr > 0:
        adaptive_pct = max(threshold_pct, (atr / last_close) * 100 * ATR_MULTIPLIER)
    else:
        adaptive_pct = threshold_pct

    threshold = adaptive_pct / 100.0

    highs = [float(r['high']) for r in rows]
    lows = [float(r['low']) for r in rows]

    def _make_pivot(idx: int, ptype: str) -> dict:
        return {
            'index': idx,
            'fecha': str(rows[idx]['fecha']),
            'price': highs[idx] if ptype == 'high' else lows[idx],
            'type': ptype,
        }

    # Fase 1: encontrar dirección inicial
    first_hi = highs[0]
    first_hi_idx = 0
    first_lo = lows[0]
    first_lo_idx = 0

    direction = 0
    start_i = 0
    for i in range(1, len(rows)):
        if highs[i] > first_hi:
            first_hi = highs[i]
            first_hi_idx = i
        if lows[i] < first_lo:
            first_lo = lows[i]
            first_lo_idx = i
        if first_hi > 0 and (first_hi - lows[i]) / first_hi >= threshold:
            direction = -1
            start_i = i
            break
        if first_lo > 0 and (highs[i] - first_lo) / first_lo >= threshold:
            direction = 1
            start_i = i
            break

    if direction == 0:
        return []

    # Fase 2: construir zigzag con alternancia estricta
    pivots: list[dict] = []

    if direction == -1:
        pivots.append(_make_pivot(first_hi_idx, 'high'))
        cur_lo = lows[start_i]
        cur_lo_idx = start_i
    else:
        pivots.append(_make_pivot(first_lo_idx, 'low'))
        cur_hi = highs[start_i]
        cur_hi_idx = start_i

    for i in range(start_i + 1, len(rows)):
        if direction == 1:
            if highs[i] > cur_hi:
                cur_hi = highs[i]
                cur_hi_idx = i
            if cur_hi > 0 and (cur_hi - lows[i]) / cur_hi >= threshold:
                pivots.append(_make_pivot(cur_hi_idx, 'high'))
                cur_lo = lows[i]
                cur_lo_idx = i
                direction = -1
        else:
            if lows[i] < cur_lo:
                cur_lo = lows[i]
                cur_lo_idx = i
            if cur_lo > 0 and (highs[i] - cur_lo) / cur_lo >= threshold:
                pivots.append(_make_pivot(cur_lo_idx, 'low'))
                cur_hi = highs[i]
                cur_hi_idx = i
                direction = 1

    # Agregar el último pivot pendiente si aporta info
    if len(pivots) >= 1:
        last_p = pivots[-1]
        if direction == 1 and 'cur_hi_idx' in dir():
            pass  # solo si hubo reversal
        elif direction == -1 and 'cur_lo_idx' in dir():
            pass

    return pivots


# ── Fibonacci scoring ──────────────────────────────────────────────────────

def _fib_score(actual_ratio: float, ideal_ratios: list[float]) -> float:
    best = min(abs(actual_ratio - fib) for fib in ideal_ratios)
    return max(0.0, 1.0 - best / FIB_TOLERANCE)


def _score_wave_count(waves: list[dict], bullish: bool) -> float:
    """
    Calcula score 0-100 de un conteo basado en proximidad a ratios Fibonacci.
    waves = lista con labels '0','1','2','3','4','5','A','B','C' y sus prices.
    """
    scores = []
    w = {wv['label']: wv['price'] for wv in waves}

    sign = 1 if bullish else -1

    # Wave 2 retrace of wave 1
    if '0' in w and '1' in w and '2' in w:
        w1_range = (w['1'] - w['0']) * sign
        if abs(w1_range) > 0.001:
            w2_retrace = abs((w['1'] - w['2']) * sign / w1_range)
            scores.append(_fib_score(w2_retrace, FIB_WAVE2_RETRACE))

    # Wave 3 extension of wave 1
    if '0' in w and '1' in w and '2' in w and '3' in w:
        w1_range = (w['1'] - w['0']) * sign
        if abs(w1_range) > 0.001:
            w3_range = (w['3'] - w['2']) * sign
            w3_ext = w3_range / w1_range
            scores.append(_fib_score(w3_ext, FIB_WAVE3_EXTEND))

    # Wave 4 retrace of wave 3
    if '2' in w and '3' in w and '4' in w:
        w3_range = (w['3'] - w['2']) * sign
        if abs(w3_range) > 0.001:
            w4_retrace = abs((w['3'] - w['4']) * sign / w3_range)
            scores.append(_fib_score(w4_retrace, FIB_WAVE4_RETRACE))

    # Wave 5 extension
    if '0' in w and '1' in w and '4' in w and '5' in w:
        w1_range = (w['1'] - w['0']) * sign
        if abs(w1_range) > 0.001:
            w5_range = (w['5'] - w['4']) * sign
            w5_ext = w5_range / w1_range
            scores.append(_fib_score(w5_ext, FIB_WAVE5_EXTEND))

    # Corrective waves
    if '0' in w and '5' in w and 'A' in w:
        impulse_range = (w['5'] - w['0']) * sign
        if abs(impulse_range) > 0.001:
            a_retrace = abs((w['5'] - w['A']) * sign / impulse_range)
            scores.append(_fib_score(a_retrace, FIB_WAVEA_RETRACE))

    if 'A' in w and 'B' in w:
        # Wave B retrace of A (from wave 5)
        if '5' in w:
            a_range = abs(w['5'] - w['A'])
            if a_range > 0.001:
                b_retrace = abs(w['B'] - w['A']) / a_range
                scores.append(_fib_score(b_retrace, FIB_WAVEB_RETRACE))

    if 'A' in w and 'B' in w and 'C' in w:
        a_range = abs(w['5'] - w['A']) if '5' in w else abs(w['A'] - w.get('0', w['A']))
        if a_range > 0.001:
            c_range = abs(w['C'] - w['B'])
            c_ext = c_range / a_range
            scores.append(_fib_score(c_ext, FIB_WAVEC_EXTEND))

    if not scores:
        return 0.0
    return (sum(scores) / len(scores)) * 100.0


# ── Validación de las 3 reglas ─────────────────────────────────────────────

def _validate_rules(waves: list[dict], bullish: bool) -> dict:
    """
    Valida las 3 reglas inviolables de Elliott.
    Retorna dict con cada regla y si pasa o no.
    """
    w = {wv['label']: wv['price'] for wv in waves}
    results = {
        'rule1_wave2_retrace': True,
        'rule2_wave3_not_shortest': True,
        'rule3_wave4_no_overlap': True,
    }

    if bullish:
        # Rule 1: Wave 2 no retrace > 100% of wave 1
        if '0' in w and '1' in w and '2' in w:
            results['rule1_wave2_retrace'] = w['2'] > w['0']

        # Rule 2: Wave 3 is not the shortest
        if all(k in w for k in ('0', '1', '2', '3', '4', '5')):
            w1_len = w['1'] - w['0']
            w3_len = w['3'] - w['2']
            w5_len = w['5'] - w['4']
            results['rule2_wave3_not_shortest'] = not (
                w3_len < w1_len and w3_len < w5_len
            )

        # Rule 3: Wave 4 doesn't overlap wave 1
        if '1' in w and '4' in w:
            results['rule3_wave4_no_overlap'] = w['4'] > w['1']
    else:
        # Bearish mirror
        if '0' in w and '1' in w and '2' in w:
            results['rule1_wave2_retrace'] = w['2'] < w['0']

        if all(k in w for k in ('0', '1', '2', '3', '4', '5')):
            w1_len = abs(w['0'] - w['1'])
            w3_len = abs(w['2'] - w['3'])
            w5_len = abs(w['4'] - w['5'])
            results['rule2_wave3_not_shortest'] = not (
                w3_len < w1_len and w3_len < w5_len
            )

        if '1' in w and '4' in w:
            results['rule3_wave4_no_overlap'] = w['4'] < w['1']

    return results


# ── Conteo de ondas ────────────────────────────────────────────────────────

def _try_count_from(pivots: list[dict], start_idx: int,
                    bullish: bool) -> Optional[dict]:
    """
    Intenta asignar etiquetas de ondas desde un pivot de inicio.
    Para bullish: el start debe ser un 'low' (inicio de onda 1 ascendente).
    Para bearish: el start debe ser un 'high' (inicio de onda 1 descendente).
    """
    remaining = pivots[start_idx:]

    if bullish:
        expected_types = ['low', 'high', 'low', 'high', 'low', 'high',
                          'low', 'high', 'low']
        labels = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']
    else:
        expected_types = ['high', 'low', 'high', 'low', 'high', 'low',
                          'high', 'low', 'high']
        labels = ['0', '1', '2', '3', '4', '5', 'A', 'B', 'C']

    waves: list[dict] = []
    piv_i = 0

    for label, exp_type in zip(labels, expected_types):
        while piv_i < len(remaining):
            p = remaining[piv_i]
            if p['type'] == exp_type:
                waves.append({
                    'label': label,
                    'fecha': p['fecha'],
                    'price': p['price'],
                    'bar_index': p['index'],
                    'type': p['type'],
                })
                piv_i += 1
                break
            piv_i += 1
        else:
            break

    if len(waves) < 6:  # al menos hasta onda 5 (labels 0-5)
        return None

    # Validar reglas con lo que tengamos
    rules = _validate_rules(waves, bullish)
    if not all(rules.values()):
        # Intentar conteo parcial sin las ondas correctivas
        impulse_only = [w for w in waves if w['label'] in ('0', '1', '2', '3', '4', '5')]
        if len(impulse_only) >= 4:
            rules_partial = _validate_rules(impulse_only, bullish)
            if not all(rules_partial.values()):
                return None
            waves = impulse_only
            rules = rules_partial

    score = _score_wave_count(waves, bullish)

    return {
        'waves': waves,
        'bullish': bullish,
        'score': score,
        'rules': rules,
        'complete_impulse': any(w['label'] == '5' for w in waves),
        'complete_correction': any(w['label'] == 'C' for w in waves),
    }


def _count_waves(pivots: list[dict]) -> Optional[dict]:
    """
    Prueba múltiples puntos de inicio y direcciones (bull/bear).
    Retorna el mejor conteo encontrado.
    """
    if len(pivots) < 6:
        return None

    candidates: list[dict] = []

    # Buscar puntos de inicio: lows para bullish, highs para bearish
    low_starts = [i for i, p in enumerate(pivots) if p['type'] == 'low']
    high_starts = [i for i, p in enumerate(pivots) if p['type'] == 'high']

    for idx in low_starts[-MAX_WAVE_ORIGINS:]:
        result = _try_count_from(pivots, idx, bullish=True)
        if result:
            candidates.append(result)

    for idx in high_starts[-MAX_WAVE_ORIGINS:]:
        result = _try_count_from(pivots, idx, bullish=False)
        if result:
            candidates.append(result)

    if not candidates:
        return None

    # Priorizar: completos sobre parciales, luego por score
    candidates.sort(key=lambda c: (
        c['complete_correction'],
        c['complete_impulse'],
        c['score'],
    ), reverse=True)

    return candidates[0]


# ── Señales y targets ──────────────────────────────────────────────────────

def _determine_signal(count: dict, current_price: float) -> dict:
    """
    Determina señal según la posición en el ciclo de Elliott.
    """
    waves = count['waves']
    bullish = count['bullish']
    w = {wv['label']: wv['price'] for wv in waves}
    last_wave = waves[-1]
    last_label = last_wave['label']

    signal = 'HOLD'
    reason = ''
    current_wave = ''

    if bullish:
        if last_label == '2':
            signal = 'BUY'
            reason = 'Onda 2 completa — onda 3 (la más fuerte) por comenzar'
            current_wave = 'Inicio Onda 3'
        elif last_label == '3':
            if current_price > w['3']:
                signal = 'HOLD'
                reason = 'Onda 3 en curso — mantener posición, es la onda más fuerte'
                current_wave = 'Onda 3 en curso'
            else:
                signal = 'HOLD'
                reason = 'Corrección onda 4 esperada'
                current_wave = 'Fin Onda 3 — esperando Onda 4'
        elif last_label == '4':
            signal = 'BUY'
            reason = 'Onda 4 completa — onda 5 por comenzar (último impulso)'
            current_wave = 'Inicio Onda 5'
        elif last_label == '5':
            signal = 'SELL'
            reason = 'Impulso completo (5 ondas) — corrección A-B-C esperada'
            current_wave = 'Impulso completo — corrección inminente'
        elif last_label == 'A':
            signal = 'HOLD'
            reason = 'Onda A correctiva completada — esperando rebote B'
            current_wave = 'Corrección Onda A'
        elif last_label == 'B':
            signal = 'SELL'
            reason = 'Rebote B terminado — onda C (última caída) por venir'
            current_wave = 'Fin rebote B — Onda C inminente'
        elif last_label == 'C':
            signal = 'BUY'
            reason = 'Corrección A-B-C completa — nuevo impulso alcista esperado'
            current_wave = 'Corrección completa — nuevo ciclo'
        elif last_label == '1':
            signal = 'HOLD'
            reason = 'Onda 1 en formación — esperar pullback de onda 2 para entrada'
            current_wave = 'Onda 1 — esperando Onda 2'
        else:
            current_wave = f'Onda {last_label}'
    else:
        # Bearish — señales invertidas
        if last_label == '2':
            signal = 'SELL'
            reason = 'Onda 2 correctiva completa — onda 3 bajista por comenzar'
            current_wave = 'Inicio Onda 3 bajista'
        elif last_label == '4':
            signal = 'SELL'
            reason = 'Onda 4 completa — onda 5 bajista por venir'
            current_wave = 'Inicio Onda 5 bajista'
        elif last_label == '5':
            signal = 'BUY'
            reason = 'Impulso bajista completo — rebote correctivo esperado'
            current_wave = 'Impulso bajista completo'
        elif last_label == 'C':
            signal = 'SELL'
            reason = 'Corrección alcista A-B-C terminada — nueva caída esperada'
            current_wave = 'Corrección completa — nueva baja'
        elif last_label == '3':
            signal = 'HOLD'
            reason = 'Onda 3 bajista en curso'
            current_wave = 'Onda 3 bajista en curso'
        elif last_label == 'A':
            signal = 'HOLD'
            reason = 'Rebote correctivo onda A'
            current_wave = 'Corrección Onda A'
        elif last_label == 'B':
            signal = 'BUY'
            reason = 'Onda B completa — onda C alcista correctiva por venir'
            current_wave = 'Inicio Onda C correctiva'
        else:
            current_wave = f'Onda {last_label} bajista'

    # Fibonacci targets
    fib_targets = _compute_fib_targets(waves, bullish, current_price)
    fib_levels = _compute_fib_levels(waves, bullish)

    return {
        'signal': signal,
        'signal_reason': reason,
        'current_wave': current_wave,
        'current_wave_label': last_label,
        'fib_targets': fib_targets,
        'fib_levels': fib_levels,
    }


def _compute_fib_targets(waves: list[dict], bullish: bool,
                         current_price: float) -> list[dict]:
    """Calcula niveles target Fibonacci hacia adelante."""
    w = {wv['label']: wv['price'] for wv in waves}
    targets: list[dict] = []

    if bullish:
        # Target Onda 3 (desde onda 2)
        if '0' in w and '1' in w and '2' in w and '3' not in w:
            w1_range = w['1'] - w['0']
            for ratio in [1.618, 2.0, 2.618]:
                targets.append({
                    'label': f'Onda 3 ({ratio:.1%})',
                    'price': round(w['2'] + w1_range * ratio, 2),
                    'ratio': f'{ratio:.1%}',
                })

        # Target Onda 5 (desde onda 4)
        if '0' in w and '1' in w and '4' in w and '5' not in w:
            w1_range = w['1'] - w['0']
            for ratio in [0.618, 1.0, 1.618]:
                targets.append({
                    'label': f'Onda 5 ({ratio:.1%})',
                    'price': round(w['4'] + w1_range * ratio, 2),
                    'ratio': f'{ratio:.1%}',
                })

        # Target Onda C (desde onda B)
        if '5' in w and 'A' in w and 'B' in w and 'C' not in w:
            a_range = abs(w['5'] - w['A'])
            for ratio in [0.618, 1.0, 1.618]:
                targets.append({
                    'label': f'Onda C ({ratio:.1%})',
                    'price': round(w['B'] - a_range * ratio, 2),
                    'ratio': f'{ratio:.1%}',
                })
    else:
        # Bearish targets (mirror)
        if '0' in w and '1' in w and '2' in w and '3' not in w:
            w1_range = abs(w['0'] - w['1'])
            for ratio in [1.618, 2.0, 2.618]:
                targets.append({
                    'label': f'Onda 3 ({ratio:.1%})',
                    'price': round(w['2'] - w1_range * ratio, 2),
                    'ratio': f'{ratio:.1%}',
                })

        if '0' in w and '1' in w and '4' in w and '5' not in w:
            w1_range = abs(w['0'] - w['1'])
            for ratio in [0.618, 1.0, 1.618]:
                targets.append({
                    'label': f'Onda 5 ({ratio:.1%})',
                    'price': round(w['4'] - w1_range * ratio, 2),
                    'ratio': f'{ratio:.1%}',
                })

    return targets


def _compute_fib_levels(waves: list[dict], bullish: bool) -> list[dict]:
    """Calcula niveles de retroceso Fibonacci sobre las ondas completadas."""
    w = {wv['label']: wv['price'] for wv in waves}
    levels: list[dict] = []

    # Retrace levels del impulso completo (0 → 5)
    if '0' in w and '5' in w:
        impulse_range = w['5'] - w['0']
        base = w['5']
        for ratio in [0.236, 0.382, 0.500, 0.618, 0.786]:
            if bullish:
                price = base - impulse_range * ratio
            else:
                price = base + abs(impulse_range) * ratio
            levels.append({
                'label': f'Fib {ratio:.1%}',
                'price': round(price, 2),
                'ratio': f'{ratio:.1%}',
            })
    elif '0' in w and '1' in w:
        # Solo tenemos onda 1, retrace levels para onda 2
        w1_range = w['1'] - w['0']
        base = w['1']
        for ratio in [0.382, 0.500, 0.618, 0.786]:
            if bullish:
                price = base - w1_range * ratio
            else:
                price = base + abs(w1_range) * ratio
            levels.append({
                'label': f'Fib {ratio:.1%} (W1)',
                'price': round(price, 2),
                'ratio': f'{ratio:.1%}',
            })

    return levels


# ── Función principal ──────────────────────────────────────────────────────

def analyze_elliott(symbol: str, fecha: Optional[date] = None) -> dict:
    fecha = fecha or date.today()
    rows = _load_ohlcv(symbol, fecha)

    if len(rows) < MIN_BARS_DATA:
        return {
            'symbol': symbol,
            'fecha': str(fecha),
            'error': f'Datos insuficientes ({len(rows)} barras, mínimo {MIN_BARS_DATA})',
            'wave_count': [],
            'current_wave': 'Sin datos',
            'current_wave_label': '',
            'signal': 'HOLD',
            'signal_reason': 'Datos insuficientes para análisis',
            'confidence': 0,
            'rules_valid': False,
            'fib_targets': [],
            'fib_levels': [],
            'zigzag_pivots': [],
            'bullish': True,
            'direction': 'N/A',
        }

    current_price = float(rows[-1]['close'])
    last_data_date = rows[-1]['fecha']
    if isinstance(last_data_date, date):
        data_age_days = (fecha - last_data_date).days
    else:
        data_age_days = 0

    pivots = _zigzag(rows)

    if len(pivots) < 6:
        return {
            'symbol': symbol,
            'fecha': str(fecha),
            'error': 'Pivots insuficientes para conteo de ondas',
            'wave_count': [],
            'current_wave': 'Sin patrón claro',
            'current_wave_label': '',
            'signal': 'HOLD',
            'signal_reason': 'No se detecta patrón de ondas definido',
            'confidence': 0,
            'rules_valid': False,
            'fib_targets': [],
            'fib_levels': [],
            'zigzag_pivots': [
                {'fecha': p['fecha'], 'price': p['price'], 'type': p['type']}
                for p in pivots
            ],
            'bullish': True,
            'direction': 'N/A',
        }

    count = _count_waves(pivots)

    if count is None:
        return {
            'symbol': symbol,
            'fecha': str(fecha),
            'wave_count': [],
            'current_wave': 'Sin patrón válido',
            'current_wave_label': '',
            'signal': 'HOLD',
            'signal_reason': 'No se encontró conteo válido de Elliott',
            'confidence': 0,
            'rules_valid': False,
            'fib_targets': [],
            'fib_levels': [],
            'zigzag_pivots': [
                {'fecha': p['fecha'], 'price': p['price'], 'type': p['type']}
                for p in pivots
            ],
            'bullish': True,
            'direction': 'N/A',
        }

    signal_data = _determine_signal(count, current_price)
    rules = count['rules']
    all_rules_valid = all(rules.values())

    direction = 'ALCISTA' if count['bullish'] else 'BAJISTA'

    return {
        'symbol': symbol,
        'fecha': str(fecha),
        'wave_count': [
            {
                'label': wv['label'],
                'fecha': wv['fecha'],
                'price': round(wv['price'], 2),
                'bar_index': wv['bar_index'],
            }
            for wv in count['waves']
        ],
        'current_wave': signal_data['current_wave'],
        'current_wave_label': signal_data['current_wave_label'],
        'signal': signal_data['signal'],
        'signal_reason': signal_data['signal_reason'],
        'confidence': round(count['score'], 1),
        'rules_valid': all_rules_valid,
        'rules_detail': rules,
        'fib_targets': signal_data['fib_targets'],
        'fib_levels': signal_data['fib_levels'],
        'zigzag_pivots': [
            {'fecha': p['fecha'], 'price': p['price'], 'type': p['type']}
            for p in pivots
        ],
        'bullish': count['bullish'],
        'direction': direction,
        'price': round(current_price, 2),
        'last_data_date': str(last_data_date),
        'data_age_days': data_age_days,
        'data_stale': data_age_days > 3,
    }


if __name__ == '__main__':
    import json
    sym = sys.argv[1] if len(sys.argv) > 1 else 'SBUX'
    result = analyze_elliott(sym)
    print(json.dumps(result, indent=2, default=str))
