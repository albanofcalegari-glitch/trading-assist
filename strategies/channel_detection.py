"""
channel_detection.py — Detección de canales paralelos (ascendentes, descendentes, horizontales).

Trabaja en log-space sobre datos semanales de ohlcv_extended.
Las dos líneas del canal tienen el MISMO slope → paralelas en gráfico log
(como dibuja un humano en TradingView).

Soporta múltiples horizontes temporales (largo, medio, corto) para detectar
canales anidados como los que se ven en TradingView.

Método:
  1. Detectar pivots highs y lows sobre velas semanales.
  2. Probar todos los pares de pivot lows → define slope + lower intercept.
  3. Para cada slope, probar cada pivot high como anchor de la upper.
  4. Puntuar cada combinación por toques, violaciones, containment, width.
  5. Devolver el canal con mejor score.

Uso:
    from strategies.channel_detection import detect_channel, detect_channels_multi
    result = detect_channel('NU')
    channels = detect_channels_multi('UBER')   # long + medium + short
"""

from __future__ import annotations

import math
import sys
import os
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn


# ─────────────────────────────────────────────────────────────────────────────
# Constantes — tunables
# ─────────────────────────────────────────────────────────────────────────────

PIVOT_WINDOW     = 5      # semanas a cada lado para detectar pivot
MIN_PIVOTS       = 4      # mínimo de pivots para fitear línea
MIN_WEEKS        = 30     # mínimo de semanas de data
LOOKBACK_YEARS   = 4      # cuántos años de historia para detección
TOUCH_TOL        = 0.05   # tolerancia en log-space (~5% en precio)
MIN_TOUCHES      = 5      # mínimo de toques totales (lower + upper)
MIN_CONTAINMENT  = 0.60   # mínimo % de semanas dentro del canal
MAX_WIDTH_LOG    = 1.0    # máximo ancho en log-space (~172% en precio)
MAX_BREACH_PCT   = 30.0   # si algún pivot rompe la línea del canal >30%, rechazar

# Horizontes para detección multi-canal
HORIZONS = [
    {'lookback': 4,   'label': 'long',   'min_pivots': 4, 'min_touches': 5, 'min_weeks': 30, 'min_dx': 60},
    {'lookback': 2,   'label': 'medium', 'min_pivots': 3, 'min_touches': 4, 'min_weeks': 25, 'min_dx': 40},
    {'lookback': 1,   'label': 'short',  'min_pivots': 3, 'min_touches': 4, 'min_weeks': 20, 'min_dx': 30},
]


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_weekly(symbol: str, fecha_max: date) -> list[dict]:
    """Carga histórico semanal desde ohlcv_extended."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = 'W' AND fecha <= %s
                   ORDER BY fecha ASC""",
                (symbol, fecha_max),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Detección de pivots
# ─────────────────────────────────────────────────────────────────────────────

def _find_pivot_highs(highs: list[float], window: int = PIVOT_WINDOW) -> list[int]:
    """Índices de máximos locales: high[i] >= max en [i-win, i+win]."""
    pivots = []
    n = len(highs)
    for i in range(window, n - window):
        val = highs[i]
        left = max(highs[i - window:i])
        right = max(highs[i + 1:i + window + 1])
        if val >= left and val >= right:
            pivots.append(i)
    return pivots


def _find_pivot_lows(lows: list[float], window: int = PIVOT_WINDOW) -> list[int]:
    """Índices de mínimos locales: low[i] <= min en [i-win, i+win]."""
    pivots = []
    n = len(lows)
    for i in range(window, n - window):
        val = lows[i]
        left = min(lows[i - window:i])
        right = min(lows[i + 1:i + window + 1])
        if val <= left and val <= right:
            pivots.append(i)
    return pivots


# ─────────────────────────────────────────────────────────────────────────────
# Trendline helpers
# ─────────────────────────────────────────────────────────────────────────────

def _trendline_at(slope: float, intercept: float, origin_days: float, target_days: float) -> float:
    """Valor en log-space de la trendline en target_days desde origin."""
    return slope * (target_days - origin_days) + intercept


# ─────────────────────────────────────────────────────────────────────────────
# Detección de canal
# ─────────────────────────────────────────────────────────────────────────────

def detect_channel(symbol: str, fecha: date = None, *,
                   lookback_years: float = LOOKBACK_YEARS,
                   min_pivots: int = MIN_PIVOTS,
                   min_touches: int = MIN_TOUCHES,
                   min_weeks: int = MIN_WEEKS,
                   min_dx: int = 60) -> Optional[dict]:
    """
    Detecta un canal paralelo en log-space para el símbolo dado.

    Retorna dict con datos del canal o None si no se detecta.
    """
    if fecha is None:
        fecha = date.today()

    rows = _load_weekly(symbol, fecha)
    if not rows:
        return None

    # Extraer arrays
    fechas = [r['fecha'] for r in rows]
    highs = [float(r['high']) for r in rows]
    lows = [float(r['low']) for r in rows]
    closes = [float(r['close']) for r in rows]

    # Recortar a lookback_years
    max_date = fechas[-1]
    cutoff = max_date - timedelta(days=int(lookback_years * 365))
    start_idx = 0
    for i, f in enumerate(fechas):
        if f >= cutoff:
            start_idx = i
            break

    fechas = fechas[start_idx:]
    highs = highs[start_idx:]
    lows = lows[start_idx:]
    closes = closes[start_idx:]

    if len(fechas) < min_weeks:
        return None

    # Pivots
    ph_idx = _find_pivot_highs(highs)
    pl_idx = _find_pivot_lows(lows)

    if len(ph_idx) < min_pivots or len(pl_idx) < min_pivots:
        return None

    # Convertir a días desde inicio (para regresión)
    origin = fechas[0]
    days = [(f - origin).days for f in fechas]

    # Log-space coordinates de pivots
    pl_days = [days[i] for i in pl_idx]
    pl_log = [math.log(lows[i]) for i in pl_idx]

    ph_days = [days[i] for i in ph_idx]
    ph_log = [math.log(highs[i]) for i in ph_idx]

    last_days = days[-1]
    last_log_close = math.log(closes[-1])
    tol = TOUCH_TOL

    # ── Brute-force: probar (lower_pair, upper_anchor) ──────────────────
    best = None
    best_score = -999
    n_low = len(pl_days)

    for i in range(n_low):
        for j in range(i + 1, n_low):
            dx = pl_days[j] - pl_days[i]
            if abs(dx) < min_dx:
                continue
            slope = (pl_log[j] - pl_log[i]) / dx
            ic_low = pl_log[i] - slope * pl_days[i]

            # Métricas lower
            low_touches = 0
            low_violations = 0
            max_breach_log = math.log(1 + MAX_BREACH_PCT / 100)
            has_massive_breach = False
            for k in range(n_low):
                pred = slope * pl_days[k] + ic_low
                diff = pl_log[k] - pred
                if abs(diff) < tol:
                    low_touches += 1
                elif diff < -tol:
                    low_violations += 1
                if diff < -max_breach_log:
                    has_massive_breach = True

            if has_massive_breach:
                continue

            # Upper: probar cada pivot high como techo
            for hi in range(len(ph_days)):
                ic_up = ph_log[hi] - slope * ph_days[hi]

                if ic_up <= ic_low + 0.05:
                    continue

                width_log = ic_up - ic_low
                if width_log > MAX_WIDTH_LOG:
                    continue

                # Métricas upper
                up_touches = 0
                up_violations = 0
                up_massive_breach = False
                for hk in range(len(ph_days)):
                    pred = slope * ph_days[hk] + ic_up
                    diff = ph_log[hk] - pred
                    if abs(diff) < tol:
                        up_touches += 1
                    elif diff > tol:
                        up_violations += 1
                    if diff > max_breach_log:
                        up_massive_breach = True

                if up_massive_breach:
                    continue

                # ¿Precio actual dentro del canal?
                support_now = slope * last_days + ic_low
                resist_now = slope * last_days + ic_up
                inside = support_now < last_log_close < resist_now

                # Width penalty
                if width_log < 0.10:
                    width_penalty = 8
                elif width_log > 0.45:
                    width_penalty = (width_log - 0.45) * 25
                else:
                    width_penalty = 0

                # Span bonus
                span = pl_days[j] - pl_days[i]
                span_bonus = min(2.0, span / 400)

                score = ((low_touches + up_touches) * 5
                         - low_violations * 6
                         - up_violations * 6
                         + (4 if inside else -3)
                         + span_bonus
                         - width_penalty)

                if score > best_score:
                    best_score = score
                    best = {
                        'slope': slope,
                        'ic_low': ic_low,
                        'ic_up': ic_up,
                        'low_touches': low_touches,
                        'up_touches': up_touches,
                        'low_violations': low_violations,
                        'up_violations': up_violations,
                    }

    if best is None:
        return None

    # Filtro de calidad
    total_touches = best['low_touches'] + best['up_touches']
    if total_touches < min_touches:
        return None

    slope = best['slope']
    ic_low = best['ic_low']
    ic_up = best['ic_up']

    # Valores actuales
    upper_now = math.exp(slope * last_days + ic_up)
    lower_now = math.exp(slope * last_days + ic_low)
    if upper_now <= lower_now:
        return None

    last_close = closes[-1]
    width = upper_now - lower_now
    position = (last_close - lower_now) / width if width > 0 else 0.5

    # Containment
    in_channel = 0
    for idx in range(len(fechas)):
        d = days[idx]
        u = math.exp(slope * d + ic_up)
        l = math.exp(slope * d + ic_low)
        if l <= closes[idx] <= u:
            in_channel += 1
    containment = in_channel / len(fechas)

    if containment < MIN_CONTAINMENT:
        return None

    # Tipo de canal
    if slope > 0.0005:
        channel_type = 'ASCENDING'
    elif slope < -0.0005:
        channel_type = 'DESCENDING'
    else:
        channel_type = 'HORIZONTAL'

    # Width en %
    width_pct = (math.exp(ic_up - ic_low) - 1) * 100

    # Slope anualizado en %
    slope_annual_pct = (math.exp(slope * 365) - 1) * 100

    # ── Decision logic ──────────────────────────────────────────────────
    if position < 0:
        decision = 'BELOW_SUPPORT'
        reading = (f'{symbol} rompió el soporte del canal {channel_type.lower()} '
                   f'(${lower_now:.2f}). Precio actual ${last_close:.2f}.')
    elif position <= 0.25:
        decision = 'NEAR_SUPPORT'
        reading = (f'{symbol} cerca del soporte del canal {channel_type.lower()} '
                   f'(${lower_now:.2f}). Posición {position:.0%}. '
                   f'Zona de potencial rebote.')
    elif position <= 0.75:
        decision = 'MID_CHANNEL'
        reading = (f'{symbol} en zona media del canal {channel_type.lower()} '
                   f'(${lower_now:.2f} - ${upper_now:.2f}). Posición {position:.0%}.')
    elif position <= 1.0:
        decision = 'NEAR_RESISTANCE'
        reading = (f'{symbol} cerca de la resistencia del canal {channel_type.lower()} '
                   f'(${upper_now:.2f}). Posición {position:.0%}. '
                   f'Zona de potencial rechazo.')
    else:
        decision = 'ABOVE_RESISTANCE'
        reading = (f'{symbol} rompió la resistencia del canal {channel_type.lower()} '
                   f'(${upper_now:.2f}). Breakout alcista. Posición {position:.0%}.')

    # Líneas para plotting (origin + slope + intercept en log-space)
    origin_str = str(origin)

    return {
        'simbolo':           symbol,
        'fecha':             str(fecha),
        'channel_type':      channel_type,
        'upper_now':         round(upper_now, 2),
        'lower_now':         round(lower_now, 2),
        'width_pct':         round(width_pct, 1),
        'position':          round(position, 3),
        'containment':       round(containment, 3),
        'slope_annual_pct':  round(slope_annual_pct, 1),
        'decision':          decision,
        'reading':           reading,
        'pivot_highs_count': len(ph_idx),
        'pivot_lows_count':  len(pl_idx),
        'low_touches':       best['low_touches'],
        'up_touches':        best['up_touches'],
        'score':             round(best_score, 1),
        # Datos para reconstruir las líneas en el frontend
        'line_origin':       origin_str,
        'line_slope':        round(slope, 8),
        'line_ic_lower':     round(ic_low, 6),
        'line_ic_upper':     round(ic_up, 6),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Multi-horizonte: detectar canales a distintos lookbacks y deduplicar
# ─────────────────────────────────────────────────────────────────────────────

def _channels_are_similar(a: dict, b: dict, slope_tol: float = 0.3, level_tol: float = 0.12) -> bool:
    """Dos canales son similares si tienen slope parecido y niveles parecidos."""
    sa = a['slope_annual_pct']
    sb = b['slope_annual_pct']
    if sa == 0 and sb == 0:
        slope_sim = True
    elif sa == 0 or sb == 0:
        slope_sim = False
    else:
        slope_sim = abs(sa - sb) / max(abs(sa), abs(sb)) < slope_tol

    la = a['lower_now']
    lb = b['lower_now']
    level_sim = abs(la - lb) / max(la, lb) < level_tol if max(la, lb) > 0 else True

    return slope_sim and level_sim


def detect_channels_multi(symbol: str, fecha: date = None) -> list[dict]:
    """
    Detecta canales a múltiples horizontes (long, medium, short).
    Deduplica canales que sean esencialmente el mismo.
    Retorna lista ordenada por horizonte (long primero).
    """
    if fecha is None:
        fecha = date.today()

    results = []
    for h in HORIZONS:
        ch = detect_channel(
            symbol, fecha,
            lookback_years=h['lookback'],
            min_pivots=h['min_pivots'],
            min_touches=h['min_touches'],
            min_weeks=h['min_weeks'],
            min_dx=h['min_dx'],
        )
        if ch:
            ch['horizon'] = h['label']
            results.append(ch)

    # Deduplicar: si dos canales son similares, quedarse con el de mayor score
    unique = []
    for ch in results:
        is_dup = False
        for i, existing in enumerate(unique):
            if _channels_are_similar(ch, existing):
                if ch['score'] > existing['score']:
                    unique[i] = ch
                is_dup = True
                break
        if not is_dup:
            unique.append(ch)

    return unique


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    symbols = sys.argv[1:] if len(sys.argv) > 1 else ['NU', 'DIS', 'B', 'UBER']
    for sym in symbols:
        print(f'\n=== {sym} ===')
        channels = detect_channels_multi(sym)
        if channels:
            for ch in channels:
                print(f'  [{ch["horizon"].upper()}] {ch["channel_type"]} channel')
                print(f'    Upper: ${ch["upper_now"]} | Lower: ${ch["lower_now"]} | Width: {ch["width_pct"]}%')
                print(f'    Position: {ch["position"]:.0%} | Containment: {ch["containment"]:.0%}')
                print(f'    Slope: {ch["slope_annual_pct"]}%/yr | Score: {ch["score"]}')
                print(f'    Touches: {ch["low_touches"]}L + {ch["up_touches"]}U')
                print(f'    {ch["reading"]}')
        else:
            print('  No channels detected')
