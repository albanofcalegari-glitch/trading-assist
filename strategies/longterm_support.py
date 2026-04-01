"""
longterm_support.py — Soportes y resistencias estructurales de largo plazo

Detecta directrices sobre el historico COMPLETO disponible en ohlcv_extended
(semanal o mensual), independientemente del zoom o de las velas visibles.

Cambios v2:
  - Dataset: siempre usa TODOS los datos disponibles
  - Scoring: span_en_anios*3 + toques*2 - violaciones*1  (span domina)
  - Filtro de escala: separacion minima entre anclas = 6 meses
  - Minimo global: el low/high absoluto siempre es candidato
  - Output garantizado: siempre devuelve 1 soporte + 1 resistencia estructural

Cambios v3:
  - Agrega capas "activas" (ultimos 7 anios) para soporte y resistencia operativa
  - Retorna 4 capas: historical_support, active_support,
                     historical_resistance, active_resistance

Horizontes disponibles:
    long_term  — semanal (preferido) o mensual como fallback
    mid_term   — semanal o diario
    short_term — solo diario

Funcion principal:
    get_longterm_support(symbol, fecha, horizon='long_term') -> dict | None
"""

import math
import sys
import os
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db.connection import get_conn


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_BREAK_TOL   = 0.06   # >6% por debajo/encima de la linea = violacion real
_TESTING_TOL = 0.05   # dentro de +/-5% = testing activo

# Ventana estructural: la barra debe ser el minimo/maximo en +/-WIN barras
# Valores grandes -> solo los swings mas importantes (como TradingView)
_STRUCT_WIN = {'D': 60, 'W': 26, 'M': 6}

# Rebote/pullback minimo para confirmar un swing estructural
_STRUCT_BOUNCE = 8.0   # 8% — filtra ruido, solo swings reales

# Separacion minima entre las dos anclas
_MIN_SEP_BARS = {'D': 180, 'W': 26, 'M': 6}

# Timeframes preferidos por horizonte (el primero con datos suficientes)
# long_term: semanal preferido — da mejor resolucion en historial multi-anio
_HORIZON_TF = {
    'long_term':  ['W', 'M'],
    'mid_term':   ['W', 'D'],
    'short_term': ['D'],
}

# Minimo de barras para que el horizonte sea valido
_MIN_BARS = {
    'long_term':  52,
    'mid_term':   30,
    'short_term': 60,
}

_FUTURE_BARS  = {'D': 60, 'W': 26, 'M': 12}
_DAYS_PER_BAR = {'D': 1,  'W': 7,  'M': 30}


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load(symbol: str, tf: str, fecha_max: date) -> list[dict]:
    """Carga TODO el historico disponible en ohlcv_extended hasta fecha_max."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = %s AND fecha <= %s
                   ORDER BY fecha ASC""",
                (symbol, tf, fecha_max),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Swing estructurales con ventana grande
# ─────────────────────────────────────────────────────────────────────────────

def _structural_lows(lows: list[float], highs: list[float], win: int) -> list[tuple]:
    """
    Minimos estructurales: la barra debe ser el minimo en +/-win barras Y tener
    un rebote posterior >= _STRUCT_BOUNCE%.
    Ventana grande (26 barras semanales = 6 meses) -> solo los swings principales.
    Retorna [(idx, price), ...] ordenado por idx ASC.
    """
    n      = len(lows)
    result = []
    for i in range(win, n - win):
        v = lows[i]
        if v <= 0:
            continue
        # Minimo absoluto en la ventana completa
        if v != min(lows[max(0, i - win): i + win + 1]):
            continue
        # Rebote posterior confirma el swing
        future = highs[i + 1: min(i + 41, n)]
        if not future or (max(future) / v - 1) * 100 < _STRUCT_BOUNCE:
            continue
        result.append((i, v))
    return result


def _structural_highs(highs: list[float], lows: list[float], win: int) -> list[tuple]:
    """
    Maximos estructurales: maximo en +/-win barras con pullback posterior >= _STRUCT_BOUNCE%.
    """
    n      = len(highs)
    result = []
    for i in range(win, n - win):
        v = highs[i]
        if v <= 0:
            continue
        if v != max(highs[max(0, i - win): i + win + 1]):
            continue
        future = lows[i + 1: min(i + 41, n)]
        if not future or (1 - min(future) / v) * 100 < _STRUCT_BOUNCE:
            continue
        result.append((i, v))
    return result


def _sig_low(price: float, p_min: float, p_max: float) -> float:
    """Significancia estructural de un minimo: 1.0 = minimo absoluto."""
    rng = p_max - p_min
    return (p_max - price) / rng if rng > 0 else 0.0


def _sig_high(price: float, p_min: float, p_max: float) -> float:
    """Significancia estructural de un maximo: 1.0 = maximo absoluto."""
    rng = p_max - p_min
    return (price - p_min) / rng if rng > 0 else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Soporte estructural historico (renombrado de _find_best_trendline)
# ─────────────────────────────────────────────────────────────────────────────

def _find_historical_support(
    lows:   list[float],
    highs:  list[float],
    closes: list[float],
    dates:  list,
    tf:     str = 'W',
) -> Optional[dict]:
    """
    Directriz de soporte principal.

    Criterios (en orden de prioridad):
      1. Toques recientes (ultimos 2 anos): peso 3.0 cada uno
      2. Proximidad al precio actual: peso 2.0
      3. Recencia del par (p1 y p2 recientes): peso 1.5
      4. Antiguedad del pivote: penalizacion 0.3 por anio de antiguedad

    Filtros duros:
      - Minimo 2 toques en los ultimos 2 anos
      - Linea dentro del 30% del precio actual
      - Pendiente entre -10%/anio y +40%/anio
    """
    n            = len(lows)
    win          = _STRUCT_WIN.get(tf, 26)
    days_per_bar = _DAYS_PER_BAR.get(tf, 7)
    min_sep      = _MIN_SEP_BARS.get(tf, 26)
    bars_per_year = 365.25 / days_per_bar
    current_price = closes[-1]

    # Todos los minimos estructurales (toda la historia)
    all_structs = _structural_lows(lows, highs, win)
    if len(all_structs) < 2:
        return None

    # Ventanas para scoring
    window_2y = int(2 * 365.25 / days_per_bar)
    window_8y = int(8 * 365.25 / days_per_bar)
    start_2y  = max(0, n - window_2y)
    start_8y  = max(0, n - window_8y)

    candidate_rows = []

    for b in range(1, len(all_structs)):
        p2_idx, p2_val = all_structs[b]
        for a in range(b):
            p1_idx, p1_val = all_structs[a]

            if p2_idx - p1_idx < min_sep:
                continue
            if p1_val <= 0 or p2_val <= 0:
                continue

            log_slope = (math.log(p2_val) - math.log(p1_val)) / (p2_idx - p1_idx)
            log_inter = math.log(p1_val) - log_slope * p1_idx

            yearly_change = math.exp(log_slope * bars_per_year) - 1
            if yearly_change > 0.40:   # pendiente irreal
                continue
            if yearly_change < -0.10:  # linea muy descendente = resistencia, no soporte
                continue

            line_now        = math.exp(log_slope * (n - 1) + log_inter)
            dist_to_current = (current_price / line_now) - 1

            # FILTRO DURO: solo lineas dentro del 30% del precio actual
            if dist_to_current > 0.30 or dist_to_current < -0.20:
                continue

            # Contar toques: pivotes dentro del +-5% de la linea en su barra
            touches_2y = 0
            touches_all = 0
            violations  = 0
            for xi, yi in all_structs:
                line_at_xi = math.exp(log_slope * xi + log_inter)
                if line_at_xi <= 0:
                    continue
                rel = (yi - line_at_xi) / line_at_xi
                if abs(rel) <= 0.05:
                    touches_all += 1
                    if xi >= start_2y:
                        touches_2y += 1
                elif yi < line_at_xi * (1 - _BREAK_TOL):
                    violations += 1

            # FILTRO DURO: minimo 2 toques en los ultimos 2 anos
            if touches_2y < 2:
                continue

            # Antiguedad media del par (en anos desde hoy)
            age_p1_years = (n - 1 - p1_idx) * days_per_bar / 365.25
            age_p2_years = (n - 1 - p2_idx) * days_per_bar / 365.25
            age_penalty  = (age_p1_years + age_p2_years) * 0.5 * 0.3

            proximity = max(0.0, 1.0 - abs(dist_to_current) / 0.30)

            # Recencia del par: 1.0 si ambos pivotes son muy recientes
            p1_recency = max(0.0, 1.0 - age_p1_years / 8.0)
            p2_recency = max(0.0, 1.0 - age_p2_years / 8.0)

            sc = (touches_2y  * 3.0
                + touches_all * 0.5
                + proximity   * 2.0
                + p2_recency  * 1.5
                + p1_recency  * 1.0
                - violations  * 0.5
                - age_penalty)

            span_years = (p2_idx - p1_idx) * days_per_bar / 365.25

            candidate_rows.append({
                'p1_idx': p1_idx, 'p1_date': dates[p1_idx], 'p1_value': p1_val,
                'p2_idx': p2_idx, 'p2_date': dates[p2_idx], 'p2_value': p2_val,
                'log_slope': log_slope, 'log_inter': log_inter,
                'touches_2y': touches_2y, 'touches_all': touches_all,
                'violations': violations, 'dist': dist_to_current,
                'span_years': span_years, 'age_p1': age_p1_years,
                'score': sc,
            })

    if not candidate_rows:
        return None

    candidate_rows.sort(key=lambda x: x['score'], reverse=True)

    print(f'[SUPPORT CANDIDATES]  {len(candidate_rows)} pares validos  precio={current_price:.2f}', flush=True)
    for rank, r in enumerate(candidate_rows[:8]):
        marker = ' << ELEGIDO' if rank == 0 else ''
        print(
            f'  [{rank+1}] p1={r["p1_date"]} ${r["p1_value"]:.2f}'
            f'  p2={r["p2_date"]} ${r["p2_value"]:.2f}'
            f'  touches_2y={r["touches_2y"]}  touches_all={r["touches_all"]}'
            f'  viols={r["violations"]}  dist={r["dist"]*100:.1f}%'
            f'  score={r["score"]:.3f}{marker}',
            flush=True,
        )

    best = candidate_rows[0]
    return {
        'log_slope':   best['log_slope'],
        'log_inter':   best['log_inter'],
        'p1_idx':      best['p1_idx'],
        'p1_date':     best['p1_date'],
        'p1_value':    best['p1_value'],
        'p2_idx':      best['p2_idx'],
        'p2_date':     best['p2_date'],
        'p2_value':    best['p2_value'],
        'touch_count': best['touches_all'],
        'breaks':      best['violations'],
        'span_years':  best['span_years'],
    }


# Alias para compatibilidad backward
_find_best_trendline = _find_historical_support


# ─────────────────────────────────────────────────────────────────────────────
# Resistencia estructural historica (renombrado de _find_best_resistance)
# ─────────────────────────────────────────────────────────────────────────────

def _find_historical_resistance(
    highs:  list[float],
    lows:   list[float],
    closes: list[float],
    dates:  list,
    tf:     str = 'W',
) -> Optional[dict]:
    """
    Directriz de resistencia principal.

    Misma logica que _find_historical_support pero para maximos:
      - Toques recientes (2 anos) peso 3.0
      - Proximidad al precio actual peso 2.0
      - Recencia del par peso 1.5
      - Penalizacion por antiguedad 0.3/anio

    Filtros duros:
      - Minimo 2 toques en los ultimos 2 anos
      - Linea dentro del 30% sobre el precio actual
      - Pendiente entre -40%/anio y +10%/anio (linea descendente o plana = resistencia)
    """
    n            = len(highs)
    win          = _STRUCT_WIN.get(tf, 26)
    days_per_bar = _DAYS_PER_BAR.get(tf, 7)
    min_sep      = _MIN_SEP_BARS.get(tf, 26)
    bars_per_year = 365.25 / days_per_bar
    current_price = closes[-1]

    all_structs = _structural_highs(highs, lows, win)
    if len(all_structs) < 2:
        return None

    window_2y = int(2 * 365.25 / days_per_bar)
    start_2y  = max(0, n - window_2y)

    candidate_rows = []

    for b in range(1, len(all_structs)):
        p2_idx, p2_val = all_structs[b]
        for a in range(b):
            p1_idx, p1_val = all_structs[a]

            if p2_idx - p1_idx < min_sep:
                continue
            if p1_val <= 0 or p2_val <= 0:
                continue

            log_slope = (math.log(p2_val) - math.log(p1_val)) / (p2_idx - p1_idx)
            log_inter = math.log(p1_val) - log_slope * p1_idx

            yearly_change = math.exp(log_slope * bars_per_year) - 1
            if yearly_change > 0.10:   # sube >10%/anio -> mas soporte que resistencia
                continue
            if yearly_change < -0.40:  # baja >40%/anio -> pendiente irreal
                continue

            line_now        = math.exp(log_slope * (n - 1) + log_inter)
            dist_to_current = (current_price / line_now) - 1  # negativo = precio bajo la linea

            # FILTRO DURO: resistencia debe estar por encima o muy cerca del precio
            if dist_to_current > 0.20:   # precio >20% encima -> rota
                continue
            if dist_to_current < -0.30:  # linea >30% encima -> muy lejana
                continue

            touches_2y  = 0
            touches_all = 0
            violations  = 0
            for xi, yi in all_structs:
                line_at_xi = math.exp(log_slope * xi + log_inter)
                if line_at_xi <= 0:
                    continue
                rel = (yi - line_at_xi) / line_at_xi
                if abs(rel) <= 0.05:
                    touches_all += 1
                    if xi >= start_2y:
                        touches_2y += 1
                elif yi > line_at_xi * (1 + _BREAK_TOL):
                    violations += 1

            # FILTRO DURO: minimo 2 toques en los ultimos 2 anos
            if touches_2y < 2:
                continue

            age_p1_years = (n - 1 - p1_idx) * days_per_bar / 365.25
            age_p2_years = (n - 1 - p2_idx) * days_per_bar / 365.25
            age_penalty  = (age_p1_years + age_p2_years) * 0.5 * 0.3

            proximity  = max(0.0, 1.0 - abs(dist_to_current) / 0.30)
            p1_recency = max(0.0, 1.0 - age_p1_years / 8.0)
            p2_recency = max(0.0, 1.0 - age_p2_years / 8.0)

            sc = (touches_2y  * 3.0
                + touches_all * 0.5
                + proximity   * 2.0
                + p2_recency  * 1.5
                + p1_recency  * 1.0
                - violations  * 0.5
                - age_penalty)

            span_years = (p2_idx - p1_idx) * days_per_bar / 365.25

            candidate_rows.append({
                'p1_idx': p1_idx, 'p1_date': dates[p1_idx], 'p1_value': p1_val,
                'p2_idx': p2_idx, 'p2_date': dates[p2_idx], 'p2_value': p2_val,
                'log_slope': log_slope, 'log_inter': log_inter,
                'touches_2y': touches_2y, 'touches_all': touches_all,
                'violations': violations, 'dist': dist_to_current,
                'span_years': span_years, 'age_p1': age_p1_years,
                'score': sc,
            })

    if not candidate_rows:
        return None

    candidate_rows.sort(key=lambda x: x['score'], reverse=True)

    print(f'[RESISTANCE CANDIDATES]  {len(candidate_rows)} pares validos  precio={current_price:.2f}', flush=True)
    for rank, r in enumerate(candidate_rows[:8]):
        marker = ' << ELEGIDO' if rank == 0 else ''
        print(
            f'  [{rank+1}] p1={r["p1_date"]} ${r["p1_value"]:.2f}'
            f'  p2={r["p2_date"]} ${r["p2_value"]:.2f}'
            f'  touches_2y={r["touches_2y"]}  touches_all={r["touches_all"]}'
            f'  viols={r["violations"]}  dist={r["dist"]*100:.1f}%'
            f'  score={r["score"]:.3f}{marker}',
            flush=True,
        )

    best = candidate_rows[0]
    return {
        'log_slope':   best['log_slope'],
        'log_inter':   best['log_inter'],
        'p1_idx':      best['p1_idx'],
        'p1_date':     best['p1_date'],
        'p1_value':    best['p1_value'],
        'p2_idx':      best['p2_idx'],
        'p2_date':     best['p2_date'],
        'p2_value':    best['p2_value'],
        'touch_count': best['touches_all'],
        'breaks':      best['violations'],
        'span_years':  best['span_years'],
    }


# Alias para compatibilidad backward
_find_best_resistance = _find_historical_resistance


# ─────────────────────────────────────────────────────────────────────────────
# Soporte activo (ultimos 7 anios)
# ─────────────────────────────────────────────────────────────────────────────

def _find_active_support(
    lows:   list[float],
    highs:  list[float],
    closes: list[float],
    dates:  list,
    tf:     str = 'W',
) -> Optional[dict]:
    """
    Directriz de soporte operativo activo:

    Considera SOLO minimos estructurales de los ultimos 7 anios.
    Si menos de 2 pivotes en 7a, expande a 10 anios.
    Prueba TODOS los pares (p1, p2) dentro de la ventana reciente.
    Filtra lineas descendentes >5%/anio (serian resistencias) o ascendentes >30%/anio.
    Filtra lineas rotas (dist_to_current < -20%) o irrelevantes (> 150% debajo).

    Score = touches*1.5 + recent_touches*2.5 + recency*1.0 + proximity*1.0 - violations*0.5
    """
    n            = len(lows)
    win          = _STRUCT_WIN.get(tf, 26)
    days_per_bar = _DAYS_PER_BAR.get(tf, 7)
    min_sep      = _MIN_SEP_BARS.get(tf, 26)
    bars_per_year = 365.25 / days_per_bar

    # Ventana corta: solo los ultimos 4 anios para p1 y p2
    # Objetivo: pivotes de la MISMA estructura de mercado reciente, visibles en pantalla
    window_4y  = int(4  * 365.25 / days_per_bar)
    window_6y  = int(6  * 365.25 / days_per_bar)
    window_10y = int(10 * 365.25 / days_per_bar)
    window_2y  = int(2  * 365.25 / days_per_bar)

    # Minimos estructurales en toda la serie (para contar toques)
    all_structs = _structural_lows(lows, highs, win)

    # Pivotes recientes: primero intentar 4 anios
    start_4y = max(0, n - window_4y)
    recent_structs = [(i, v) for i, v in all_structs if i >= start_4y]

    # Si menos de 2, expandir a 6 anios; luego 10
    if len(recent_structs) < 2:
        start_6y = max(0, n - window_6y)
        recent_structs = [(i, v) for i, v in all_structs if i >= start_6y]
    if len(recent_structs) < 2:
        start_10y = max(0, n - window_10y)
        recent_structs = [(i, v) for i, v in all_structs if i >= start_10y]

    if len(recent_structs) < 2:
        print('[ACTIVE SUPPORT CANDIDATES]  sin pivotes suficientes en ventana reciente', flush=True)
        return None

    current_price = closes[-1]
    start_2y = max(0, n - window_2y)

    candidate_rows = []

    for b in range(1, len(recent_structs)):
        p2_idx, p2_val = recent_structs[b]
        for a in range(b):
            p1_idx, p1_val = recent_structs[a]

            # Separacion minima entre anclas
            if p2_idx - p1_idx < min_sep:
                continue

            if p1_val <= 0 or p2_val <= 0:
                continue

            # Calcular slope en espacio log
            log_slope = (math.log(p2_val) - math.log(p1_val)) / (p2_idx - p1_idx)
            log_inter = math.log(p1_val) - log_slope * p1_idx

            yearly_change = math.exp(log_slope * bars_per_year) - 1

            # Filtrar lineas demasiado descendentes (seria resistencia) o irreal ascendente
            if yearly_change < -0.05:   # descend >5%/anio -> seria resistencia
                continue
            if yearly_change > 0.30:    # sube >30%/anio -> irreal para soporte
                continue

            # Valor actual de la linea y distancia al precio
            line_now = math.exp(log_slope * (n - 1) + log_inter)
            dist_to_current = (current_price / line_now) - 1  # positivo = precio sobre la linea

            # Filtrar lineas rotas o irrelevantes
            if dist_to_current < -0.20:  # precio >20% debajo -> soporte roto
                continue
            if dist_to_current > 1.50:   # precio >150% sobre la linea -> irrelevante
                continue

            # Contar toques: minimos estructurales dentro de +/-5% de la linea proyectada
            touches = 0
            recent_touches = 0
            violations = 0

            for xi, yi in recent_structs:
                line_at_xi = math.exp(log_slope * xi + log_inter)
                if line_at_xi <= 0:
                    continue
                rel_dist = (yi - line_at_xi) / line_at_xi
                if abs(rel_dist) <= 0.05:
                    touches += 1
                    if xi >= start_2y:
                        recent_touches += 1
                elif yi < line_at_xi * (1 - 0.06):
                    violations += 1

            window_start = recent_structs[0][0] if recent_structs else 0
            window_len   = max(1, n - window_start)
            recency    = (p2_idx - window_start) / window_len
            p1_recency = (p1_idx - window_start) / window_len
            proximity  = max(0.0, 1.0 - abs(dist_to_current) * 2)

            score = (touches * 1.5
                     + recent_touches * 2.5
                     + recency * 2.0
                     + p1_recency * 1.0
                     + proximity * 1.0
                     - violations * 0.5)

            span_years = (p2_idx - p1_idx) * days_per_bar / 365.25

            candidate_rows.append({
                'p1_idx':       p1_idx,
                'p1_date':      dates[p1_idx],
                'p1_value':     p1_val,
                'p2_idx':       p2_idx,
                'p2_date':      dates[p2_idx],
                'p2_value':     p2_val,
                'log_slope':    log_slope,
                'log_inter':    log_inter,
                'touches':      touches,
                'recent_touches': recent_touches,
                'violations':   violations,
                'yearly_change': yearly_change,
                'dist_to_current': dist_to_current,
                'span_years':   span_years,
                'score':        score,
            })

    if not candidate_rows:
        print('[ACTIVE SUPPORT CANDIDATES]  sin candidatos validos', flush=True)
        return None

    candidate_rows.sort(key=lambda x: x['score'], reverse=True)

    print(f'[ACTIVE SUPPORT CANDIDATES]  {len(candidate_rows)} pares evaluados', flush=True)
    for rank, r in enumerate(candidate_rows[:5]):
        marker = ' << ELEGIDO' if rank == 0 else ''
        print(
            f'  [{rank+1}] p1={r["p1_date"]} ${r["p1_value"]:.2f}'
            f'  p2={r["p2_date"]} ${r["p2_value"]:.2f}'
            f'  touches={r["touches"]}  recent={r["recent_touches"]}'
            f'  viols={r["violations"]}  dist={r["dist_to_current"]*100:.1f}%'
            f'  yearly={r["yearly_change"]*100:.1f}%'
            f'  score={r["score"]:.3f}{marker}',
            flush=True,
        )

    best = candidate_rows[0]
    return {
        'log_slope':      best['log_slope'],
        'log_inter':      best['log_inter'],
        'p1_idx':         best['p1_idx'],
        'p1_date':        best['p1_date'],
        'p1_value':       best['p1_value'],
        'p2_idx':         best['p2_idx'],
        'p2_date':        best['p2_date'],
        'p2_value':       best['p2_value'],
        'touch_count':    best['touches'],
        'recent_touches': best['recent_touches'],
        'breaks':         best['violations'],
        'span_years':     best['span_years'],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Resistencia activa (ultimos 7 anios)
# ─────────────────────────────────────────────────────────────────────────────

def _find_active_resistance(
    highs:  list[float],
    lows:   list[float],
    closes: list[float],
    dates:  list,
    tf:     str = 'W',
) -> Optional[dict]:
    """
    Directriz de resistencia operativa activa:

    Considera SOLO maximos estructurales de los ultimos 7 anios.
    Si menos de 2 pivotes en 7a, expande a 10 anios.
    Prueba TODOS los pares (p1, p2) dentro de la ventana reciente.
    Prefiere lineas descendentes o planas (yearly_change entre -30% y +5%).
    Filtra lineas rotas (dist_to_current > 20% = precio ya rompio al alza).

    Score = touches*1.5 + recent_touches*2.5 + recency*1.0 + proximity*1.0 - violations*0.5
    """
    n            = len(highs)
    win          = _STRUCT_WIN.get(tf, 26)
    days_per_bar = _DAYS_PER_BAR.get(tf, 7)
    min_sep      = _MIN_SEP_BARS.get(tf, 26)
    bars_per_year = 365.25 / days_per_bar

    window_4y  = int(4  * 365.25 / days_per_bar)
    window_6y  = int(6  * 365.25 / days_per_bar)
    window_10y = int(10 * 365.25 / days_per_bar)
    window_2y  = int(2  * 365.25 / days_per_bar)

    # Maximos estructurales en toda la serie (para contar toques)
    all_structs = _structural_highs(highs, lows, win)

    # Pivotes recientes: primero 4 anios, luego expandir si hay pocos
    start_4y = max(0, n - window_4y)
    recent_structs = [(i, v) for i, v in all_structs if i >= start_4y]

    if len(recent_structs) < 2:
        start_6y = max(0, n - window_6y)
        recent_structs = [(i, v) for i, v in all_structs if i >= start_6y]
    if len(recent_structs) < 2:
        start_10y = max(0, n - window_10y)
        recent_structs = [(i, v) for i, v in all_structs if i >= start_10y]

    if len(recent_structs) < 2:
        print('[ACTIVE RESISTANCE CANDIDATES]  sin pivotes suficientes en ventana reciente', flush=True)
        return None

    current_price = closes[-1]
    start_2y = max(0, n - window_2y)

    candidate_rows = []

    for b in range(1, len(recent_structs)):
        p2_idx, p2_val = recent_structs[b]
        for a in range(b):
            p1_idx, p1_val = recent_structs[a]

            # Separacion minima entre anclas
            if p2_idx - p1_idx < min_sep:
                continue

            if p1_val <= 0 or p2_val <= 0:
                continue

            # Calcular slope en espacio log
            log_slope = (math.log(p2_val) - math.log(p1_val)) / (p2_idx - p1_idx)
            log_inter = math.log(p1_val) - log_slope * p1_idx

            yearly_change = math.exp(log_slope * bars_per_year) - 1

            # Preferir lineas descendentes o planas: yearly_change entre -30% y +5%
            if yearly_change > 0.05:    # sube >5%/anio -> mas soporte que resistencia
                continue
            if yearly_change < -0.30:   # baja >30%/anio -> pendiente irreal
                continue

            # Valor actual de la linea y distancia al precio
            line_now = math.exp(log_slope * (n - 1) + log_inter)
            dist_to_current = (current_price / line_now) - 1  # positivo = precio sobre la linea (la rompio)

            # Filtrar lineas rotas (precio >20% por encima) o irrelevantes (linea >150% sobre precio)
            if dist_to_current > 0.20:   # precio >20% por encima -> resistencia rota
                continue
            if dist_to_current < -1.50:  # linea >150% por encima del precio -> irrelevante
                continue

            # Contar toques: maximos estructurales dentro de +/-5% de la linea proyectada
            touches = 0
            recent_touches = 0
            violations = 0

            for xi, yi in recent_structs:
                line_at_xi = math.exp(log_slope * xi + log_inter)
                if line_at_xi <= 0:
                    continue
                rel_dist = (yi - line_at_xi) / line_at_xi
                if abs(rel_dist) <= 0.05:
                    touches += 1
                    if xi >= start_2y:
                        recent_touches += 1
                elif yi > line_at_xi * (1 + 0.06):
                    violations += 1

            window_start = recent_structs[0][0] if recent_structs else 0
            window_len   = max(1, n - window_start)
            recency    = (p2_idx - window_start) / window_len
            p1_recency = (p1_idx - window_start) / window_len
            proximity  = max(0.0, 1.0 - abs(dist_to_current) * 2)

            score = (touches * 1.5
                     + recent_touches * 2.5
                     + recency * 2.0
                     + p1_recency * 1.0
                     + proximity * 1.0
                     - violations * 0.5)

            span_years = (p2_idx - p1_idx) * days_per_bar / 365.25

            candidate_rows.append({
                'p1_idx':         p1_idx,
                'p1_date':        dates[p1_idx],
                'p1_value':       p1_val,
                'p2_idx':         p2_idx,
                'p2_date':        dates[p2_idx],
                'p2_value':       p2_val,
                'log_slope':      log_slope,
                'log_inter':      log_inter,
                'touches':        touches,
                'recent_touches': recent_touches,
                'violations':     violations,
                'yearly_change':  yearly_change,
                'dist_to_current': dist_to_current,
                'span_years':     span_years,
                'score':          score,
            })

    if not candidate_rows:
        print('[ACTIVE RESISTANCE CANDIDATES]  sin candidatos validos', flush=True)
        return None

    candidate_rows.sort(key=lambda x: x['score'], reverse=True)

    print(f'[ACTIVE RESISTANCE CANDIDATES]  {len(candidate_rows)} pares evaluados', flush=True)
    for rank, r in enumerate(candidate_rows[:5]):
        marker = ' << ELEGIDO' if rank == 0 else ''
        print(
            f'  [{rank+1}] p1={r["p1_date"]} ${r["p1_value"]:.2f}'
            f'  p2={r["p2_date"]} ${r["p2_value"]:.2f}'
            f'  touches={r["touches"]}  recent={r["recent_touches"]}'
            f'  viols={r["violations"]}  dist={r["dist_to_current"]*100:.1f}%'
            f'  yearly={r["yearly_change"]*100:.1f}%'
            f'  score={r["score"]:.3f}{marker}',
            flush=True,
        )

    best = candidate_rows[0]
    return {
        'log_slope':      best['log_slope'],
        'log_inter':      best['log_inter'],
        'p1_idx':         best['p1_idx'],
        'p1_date':        best['p1_date'],
        'p1_value':       best['p1_value'],
        'p2_idx':         best['p2_idx'],
        'p2_date':        best['p2_date'],
        'p2_value':       best['p2_value'],
        'touch_count':    best['touches'],
        'recent_touches': best['recent_touches'],
        'breaks':         best['violations'],
        'span_years':     best['span_years'],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Generacion de puntos para renderizado
# ─────────────────────────────────────────────────────────────────────────────

def _generate_line_points(
    tl:    dict,
    dates: list,
    n:     int,
    tf:    str,
) -> list[dict]:
    """
    Genera puntos {fecha, value} desde p1 hasta hoy + proyeccion futura.
    """
    log_slope   = tl['log_slope']
    log_inter   = tl['log_inter']
    p1_idx      = tl['p1_idx']
    days_step   = _DAYS_PER_BAR[tf]
    future_bars = _FUTURE_BARS[tf]

    points = []

    for k in range(p1_idx, n):
        value = math.exp(log_slope * k + log_inter)
        if value > 0:
            fd = dates[k]
            points.append({
                'fecha': str(fd) if not isinstance(fd, str) else fd,
                'value': round(value, 4),
            })

    last_d = dates[-1]
    if isinstance(last_d, str):
        y, m, d = map(int, last_d.split('-'))
        from datetime import date as _date
        last_d = _date(y, m, d)

    for k in range(1, future_bars + 1):
        t     = n - 1 + k
        value = math.exp(log_slope * t + log_inter)
        fdate = last_d + timedelta(days=days_step * k)
        points.append({'fecha': str(fdate), 'value': round(value, 4)})

    return points


# ─────────────────────────────────────────────────────────────────────────────
# Clasificacion del estado actual
# ─────────────────────────────────────────────────────────────────────────────

def _classify_status(
    tl:     dict,
    closes: list[float],
    n:      int,
) -> tuple[str, float]:
    """
    (status, distance_pct) para soporte.
    distance_pct positivo = precio sobre la linea.
    """
    log_slope = tl['log_slope']
    log_inter = tl['log_inter']
    price     = closes[-1]
    line_now  = math.exp(log_slope * (n - 1) + log_inter)

    if line_now <= 0:
        return 'NO_SUPPORT', 0.0

    dist_pct = (price / line_now - 1) * 100

    recent_breaks = sum(
        1 for k in range(max(0, n - 4), n)
        if closes[k] < math.exp(log_slope * k + log_inter) * (1 - _BREAK_TOL)
    )
    if recent_breaks >= 2 or dist_pct < -_BREAK_TOL * 100:
        return 'BROKEN', dist_pct

    if abs(dist_pct) <= _TESTING_TOL * 100:
        return 'TESTING', dist_pct

    return 'ACTIVE', dist_pct


def _classify_status_resistance(
    tl:     dict,
    closes: list[float],
    n:      int,
) -> tuple[str, float]:
    """
    (status, distance_pct) para resistencia.
    distance_pct positivo = precio sobre la linea (la rompio).
    """
    log_slope = tl['log_slope']
    log_inter = tl['log_inter']
    price     = closes[-1]
    line_now  = math.exp(log_slope * (n - 1) + log_inter)

    if line_now <= 0:
        return 'NO_SUPPORT', 0.0

    dist_pct = (price / line_now - 1) * 100

    recent_breaks = sum(
        1 for k in range(max(0, n - 4), n)
        if closes[k] > math.exp(log_slope * k + log_inter) * (1 + _BREAK_TOL)
    )
    if recent_breaks >= 2 or dist_pct > _BREAK_TOL * 100:
        return 'BROKEN', dist_pct

    if abs(dist_pct) <= _TESTING_TOL * 100:
        return 'TESTING', dist_pct

    return 'ACTIVE', dist_pct


_STATUS_READING = {
    'ACTIVE':     'Directriz de largo plazo activa -- soporte estructural vigente',
    'TESTING':    'Precio testeando la directriz de largo plazo',
    'BROKEN':     'Directriz de largo plazo rota -- estructura de tendencia comprometida',
    'NO_SUPPORT': 'Sin directriz de largo plazo identificada con suficiente historia',
}

_RES_STATUS_READING = {
    'ACTIVE':     'Resistencia estructural activa -- techo de largo plazo vigente',
    'TESTING':    'Precio testeando la resistencia estructural',
    'BROKEN':     'Resistencia estructural rota -- precio por encima del techo historico',
    'NO_SUPPORT': 'Sin resistencia estructural identificada',
}

_ACTIVE_READING = {
    'ACTIVE':     'Soporte operativo activo -- vigente en el rango reciente',
    'TESTING':    'Precio testeando el soporte operativo',
    'BROKEN':     'Soporte operativo perforado',
    'NO_SUPPORT': 'Sin soporte operativo identificado en el rango reciente',
}

_ACTIVE_RES_READING = {
    'ACTIVE':     'Resistencia operativa activa -- techo vigente en el rango reciente',
    'TESTING':    'Precio testeando la resistencia operativa',
    'BROKEN':     'Resistencia operativa rota -- precio por encima del techo reciente',
    'NO_SUPPORT': 'Sin resistencia operativa identificada',
}


# ─────────────────────────────────────────────────────────────────────────────
# Funcion publica principal
# ─────────────────────────────────────────────────────────────────────────────

def get_longterm_support(
    symbol:  str,
    fecha:   date,
    horizon: str = 'long_term',
) -> Optional[dict]:
    """
    Calcula el soporte y la resistencia estructural de largo plazo.

    Usa el historico COMPLETO de ohlcv_extended — no depende del zoom ni
    del rango visible.  Devuelve SIEMPRE 1 soporte + 1 resistencia aunque
    tengan violaciones, excepto si no hay datos en ohlcv_extended.

    Campos del resultado:
      Soporte historico      -> line_points, status, p1, p2, current_value,
                                distance_pct, touch_count, reading
      Soporte activo         -> active_*, mismos subcampos
      Resist. historica      -> resistance_*, mismos subcampos
      Resist. activa         -> active_resistance_*, mismos subcampos
    """
    timeframes = _HORIZON_TF.get(horizon, ['W', 'D'])
    min_bars   = _MIN_BARS.get(horizon, 50)

    rows    = []
    used_tf = None
    for tf in timeframes:
        rows = _load(symbol, tf, fecha)
        if len(rows) >= min_bars:
            used_tf = tf
            break

    if not rows or used_tf is None:
        return None

    closes = [float(r['close']) for r in rows]
    highs  = [float(r['high'])  for r in rows]
    lows   = [float(r['low'])   for r in rows]
    dates  = [r['fecha']        for r in rows]
    n      = len(closes)

    first_date = str(dates[0])
    last_date  = str(dates[-1])

    # Log obligatorio: confirmar dataset completo
    print(f'[DATASET] symbol={symbol}  horizon={horizon}  timeframe={used_tf}')
    print(f'          candles_count={n}')
    print(f'          first_date={first_date}')
    print(f'          last_date={last_date}', flush=True)

    # Validacion: para W se requieren +1000 barras con historia desde <=2005
    if used_tf == 'W':
        if n < 1000:
            print(f'[DATASET] ABORT: candles_count={n} < 1000 -- dataset insuficiente para calculo estructural', flush=True)
            return None
        if first_date > '2005-12-31':
            print(f'[DATASET] ABORT: first_date={first_date} > 2005 -- faltan datos historicos en ohlcv_extended', flush=True)
            return None

    # ── Soporte historico ─────────────────────────────────────────────────────
    tl = _find_historical_support(lows, highs, closes, dates, used_tf)

    if tl is None:
        support_block = {
            'status':        'NO_SUPPORT',
            'p1':            None,
            'p2':            None,
            'line_points':   [],
            'current_value': None,
            'distance_pct':  None,
            'touch_count':   0,
            'reading':       _STATUS_READING['NO_SUPPORT'],
        }
    else:
        status, dist = _classify_status(tl, closes, n)
        line_now     = math.exp(tl['log_slope'] * (n - 1) + tl['log_inter'])
        support_block = {
            'status':        status,
            'p1':            {'fecha': str(tl['p1_date']), 'value': round(tl['p1_value'], 4)},
            'p2':            {'fecha': str(tl['p2_date']), 'value': round(tl['p2_value'], 4)},
            'line_points':   _generate_line_points(tl, dates, n, used_tf),
            'current_value': round(line_now, 4),
            'distance_pct':  round(dist, 2),
            'touch_count':   tl['touch_count'],
            'reading':       _STATUS_READING.get(status, status),
        }

    # ── Soporte activo ────────────────────────────────────────────────────────
    act = _find_active_support(lows, highs, closes, dates, used_tf)

    if act is None:
        active_support_block = {
            'active_status':        'NO_SUPPORT',
            'active_p1':            None,
            'active_p2':            None,
            'active_line_points':   [],
            'active_current_value': None,
            'active_distance_pct':  None,
            'active_touch_count':   0,
            'active_reading':       _ACTIVE_READING['NO_SUPPORT'],
        }
    else:
        act_status, act_dist = _classify_status(act, closes, n)
        act_line_now         = math.exp(act['log_slope'] * (n - 1) + act['log_inter'])
        active_support_block = {
            'active_status':        act_status,
            'active_p1':            {'fecha': str(act['p1_date']), 'value': round(act['p1_value'], 4)},
            'active_p2':            {'fecha': str(act['p2_date']), 'value': round(act['p2_value'], 4)},
            'active_line_points':   _generate_line_points(act, dates, n, used_tf),
            'active_current_value': round(act_line_now, 4),
            'active_distance_pct':  round(act_dist, 2),
            'active_touch_count':   act['touch_count'],
            'active_reading':       _ACTIVE_READING.get(act_status, act_status),
        }

    # ── Resistencia historica ─────────────────────────────────────────────────
    res = _find_historical_resistance(highs, lows, closes, dates, used_tf)

    if res is None:
        resistance_block = {
            'resistance_status':          'NO_SUPPORT',
            'resistance_p1':              None,
            'resistance_p2':              None,
            'resistance_line_points':     [],
            'resistance_current_value':   None,
            'resistance_distance_pct':    None,
            'resistance_touch_count':     0,
            'resistance_reading':         _RES_STATUS_READING['NO_SUPPORT'],
        }
    else:
        res_status, res_dist = _classify_status_resistance(res, closes, n)
        res_now              = math.exp(res['log_slope'] * (n - 1) + res['log_inter'])
        resistance_block = {
            'resistance_status':          res_status,
            'resistance_p1':              {'fecha': str(res['p1_date']), 'value': round(res['p1_value'], 4)},
            'resistance_p2':              {'fecha': str(res['p2_date']), 'value': round(res['p2_value'], 4)},
            'resistance_line_points':     _generate_line_points(res, dates, n, used_tf),
            'resistance_current_value':   round(res_now, 4),
            'resistance_distance_pct':    round(res_dist, 2),
            'resistance_touch_count':     res['touch_count'],
            'resistance_reading':         _RES_STATUS_READING.get(res_status, res_status),
        }

    # ── Resistencia activa ────────────────────────────────────────────────────
    act_res = _find_active_resistance(highs, lows, closes, dates, used_tf)

    if act_res is None:
        active_resistance_block = {
            'active_resistance_status':          'NO_SUPPORT',
            'active_resistance_p1':              None,
            'active_resistance_p2':              None,
            'active_resistance_line_points':     [],
            'active_resistance_current_value':   None,
            'active_resistance_distance_pct':    None,
            'active_resistance_touch_count':     0,
            'active_resistance_reading':         _ACTIVE_RES_READING['NO_SUPPORT'],
        }
    else:
        act_res_status, act_res_dist = _classify_status_resistance(act_res, closes, n)
        act_res_now                  = math.exp(act_res['log_slope'] * (n - 1) + act_res['log_inter'])
        active_resistance_block = {
            'active_resistance_status':          act_res_status,
            'active_resistance_p1':              {'fecha': str(act_res['p1_date']), 'value': round(act_res['p1_value'], 4)},
            'active_resistance_p2':              {'fecha': str(act_res['p2_date']), 'value': round(act_res['p2_value'], 4)},
            'active_resistance_line_points':     _generate_line_points(act_res, dates, n, used_tf),
            'active_resistance_current_value':   round(act_res_now, 4),
            'active_resistance_distance_pct':    round(act_res_dist, 2),
            'active_resistance_touch_count':     act_res['touch_count'],
            'active_resistance_reading':         _ACTIVE_RES_READING.get(act_res_status, act_res_status),
        }

    return {
        'symbol':         symbol,
        'timeframe_used': used_tf,
        'bars_of_data':   n,
        **support_block,
        **active_support_block,
        **resistance_block,
        **active_resistance_block,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ['DIS', 'MSFT', 'GOOGL']
    today   = date.today()

    print()
    print(f'=== Long-Term Support/Resistance  fecha={today} ===')
    print()

    for sym in symbols:
        result = get_longterm_support(sym, today, horizon='long_term')

        if result is None:
            print(f'{sym:8s}  sin datos en ohlcv_extended')
            print(f'          -> Ejecutar: python scripts/backfill_history.py --symbol {sym}')
            print()
            continue

        print(
            f'{sym:8s}  [{result["timeframe_used"]}]  '
            f'{result["bars_of_data"]} barras'
        )

        if result['status'] != 'NO_SUPPORT':
            print(f'  SOPORTE     p1={result["p1"]["fecha"]}  p2={result["p2"]["fecha"]}'
                  f'  toques={result["touch_count"]}  status={result["status"]}'
                  f'  dist={result["distance_pct"]:+.1f}%')
            print(f'              {result["reading"]}')
        else:
            print(f'  SOPORTE     NO_SUPPORT')

        if result['active_status'] != 'NO_SUPPORT':
            print(f'  SOPORTE ACT p1={result["active_p1"]["fecha"]}  p2={result["active_p2"]["fecha"]}'
                  f'  toques={result["active_touch_count"]}  status={result["active_status"]}'
                  f'  dist={result["active_distance_pct"]:+.1f}%')
            print(f'              {result["active_reading"]}')
        else:
            print(f'  SOPORTE ACT NO_SUPPORT')

        if result['resistance_status'] != 'NO_SUPPORT':
            print(f'  RESISTENCIA p1={result["resistance_p1"]["fecha"]}  p2={result["resistance_p2"]["fecha"]}'
                  f'  toques={result["resistance_touch_count"]}  status={result["resistance_status"]}'
                  f'  dist={result["resistance_distance_pct"]:+.1f}%')
            print(f'              {result["resistance_reading"]}')
        else:
            print(f'  RESISTENCIA NO_SUPPORT')

        if result['active_resistance_status'] != 'NO_SUPPORT':
            print(f'  RES ACT     p1={result["active_resistance_p1"]["fecha"]}  p2={result["active_resistance_p2"]["fecha"]}'
                  f'  toques={result["active_resistance_touch_count"]}  status={result["active_resistance_status"]}'
                  f'  dist={result["active_resistance_distance_pct"]:+.1f}%')
            print(f'              {result["active_resistance_reading"]}')
        else:
            print(f'  RES ACT     NO_SUPPORT')

        print()
