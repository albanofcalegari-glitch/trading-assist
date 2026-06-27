"""
tiered_sr.py  --  Soportes y resistencias con clasificacion behavioral

Produce tres tiers por lado (soporte y resistencia):

  historical   — soporte/resistencia estructural, preferentemente semanal,
                 cubre el rally o bear market vigente.
  accelerated  — diagonal empinada en diario cuando el precio se despego
                 del soporte/resistencia historico (fase de aceleracion).
  tactical     — zona horizontal cuando no hay diagonal acelerada valida
                 (lateralizacion / consolidacion).

El modulo NO duplica logica de fitting: importa las funciones internas de
dynamic_supports.py y dynamic_resistances.py (pivots, trendline log-space,
sideways detection, build_tier) y agrega una capa de deteccion de aceleracion
+ orquestacion multi-timeframe.

Funcion publica:
    get_tiered_sr(symbol, fecha=today) -> dict
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from strategies.dynamic_supports import (
    _load,
    _pivot_lows,
    _try_fit as _try_fit_sup,
    _detect_sideways_horizontal as _detect_sideways_sup,
    _build_tier as _build_tier_sup,
    _slope_annual_pct,
    PRICE_TOL_PCT,
    NO_BODY_CROSS_TOL_PCT,
    MIN_TOUCHES,
)
from strategies.dynamic_resistances import (
    _pivot_highs,
    _try_fit as _try_fit_res,
    _detect_sideways_horizontal as _detect_sideways_res,
    _build_tier as _build_tier_res,
)


# ── Constantes de aceleracion ───────────────────────────────────────────────

# Distancia minima del precio al soporte/resistencia estructural para
# considerar que hay aceleracion.  Por debajo de 25%, el precio sigue
# "cerca" de la linea historica y el tier mid/short clasico alcanza.
ACCEL_MIN_DIST_PCT = 25.0

# La pendiente diaria (anualizada) debe ser > ACCEL_SLOPE_RATIO veces la
# pendiente estructural semanal.  1.5x es el punto donde la divergencia
# se percibe claramente en el chart — el precio sube (o baja) mucho mas
# rapido que la tendencia de fondo.
ACCEL_SLOPE_RATIO = 1.5

# Minimo de pivots consecutivos crecientes (soporte) o decrecientes
# (resistencia) en la data diaria reciente para confirmar que la
# aceleracion es sostenida, no un spike aislado.
ACCEL_MIN_RISING_LOWS = 3

# Barras de data diaria a analizar para la linea acelerada (~6 meses).
ACCEL_DAILY_LOOKBACK = 120

# Ventana de pivot para diario (mas chica que la semanal porque daily
# es mas ruidoso y necesitamos resolucion fina).
ACCEL_PIVOT_WIN_D = 5

# Min span en barras diarias para la linea acelerada (~3 semanas).
ACCEL_MIN_SPAN_D = 15

# ── Stop hint ────────────────────────────────────────────────────────────────

# Buffer debajo/encima del valor actual de la linea para sugerir stop.
# 2% absorbe ruido de mechas normales sin ser tan ajustado que salte con
# la volatilidad intradía.
STOP_BUFFER_PCT = 2.0


# ── Deteccion de aceleracion ────────────────────────────────────────────────

def _ols_slope(values: list[float]) -> float:
    """Pendiente OLS sobre lista de valores. Devuelve slope per bar."""
    n = len(values)
    if n < 3:
        return 0.0
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    num = sum((k - mean_x) * (values[k] - mean_y) for k in range(n))
    den = sum((k - mean_x) ** 2 for k in range(n))
    if den == 0:
        return 0.0
    return num / den


def _detect_acceleration(
    structural_slope_annual: float,
    structural_current_value: float,
    price: float,
    daily_rows: list[dict],
    side: str,
) -> dict:
    """
    Detecta si el precio esta en fase de aceleracion respecto al soporte/
    resistencia estructural.

    Retorna dict con 'detected' (bool) y metricas de diagnostico.
    """
    result = {
        'detected': False,
        'direction': None,
        'distance_from_structural_pct': 0.0,
        'slope_ratio': 0.0,
        'rising_lows_count': 0,
    }

    if not daily_rows or structural_current_value <= 0:
        return result

    # 1. Distancia al soporte/resistencia estructural
    if side == 'support':
        dist_pct = (price / structural_current_value - 1) * 100
        if dist_pct < ACCEL_MIN_DIST_PCT:
            return result
    else:
        dist_pct = (1 - price / structural_current_value) * 100
        if dist_pct < ACCEL_MIN_DIST_PCT:
            return result

    result['distance_from_structural_pct'] = round(dist_pct, 2)

    # 2. Pendiente reciente en diario (OLS sobre log)
    recent = daily_rows[-ACCEL_DAILY_LOOKBACK:]
    if len(recent) < 30:
        return result

    if side == 'support':
        vals = [float(r['low']) for r in recent]
    else:
        vals = [float(r['high']) for r in recent]

    log_vals = [math.log(v) for v in vals if v > 0]
    if len(log_vals) < 30:
        return result

    daily_slope = _ols_slope(log_vals)
    daily_slope_annual = (math.exp(daily_slope * 252) - 1) * 100

    # 3. Comparar pendientes
    if side == 'support':
        if daily_slope_annual <= 0:
            return result
        if structural_slope_annual > 0:
            ratio = daily_slope_annual / structural_slope_annual
        else:
            ratio = 99.0 if daily_slope_annual > 30 else 0.0
        if ratio < ACCEL_SLOPE_RATIO:
            return result
    else:
        if daily_slope_annual >= 0:
            return result
        if structural_slope_annual < 0:
            ratio = abs(daily_slope_annual) / abs(structural_slope_annual)
        else:
            ratio = 99.0 if daily_slope_annual < -30 else 0.0
        if ratio < ACCEL_SLOPE_RATIO:
            return result

    result['slope_ratio'] = round(ratio, 2)

    # 4. Pivots consecutivos crecientes/decrecientes
    if side == 'support':
        lows = [float(r['low']) for r in recent]
        pivots = _pivot_lows(lows, ACCEL_PIVOT_WIN_D)
        if len(pivots) < ACCEL_MIN_RISING_LOWS:
            return result
        last_pivots = pivots[-(ACCEL_MIN_RISING_LOWS + 2):]
        rising = 0
        for k in range(1, len(last_pivots)):
            if lows[last_pivots[k]] > lows[last_pivots[k - 1]]:
                rising += 1
        result['rising_lows_count'] = rising
        if rising < ACCEL_MIN_RISING_LOWS:
            return result
        result['direction'] = 'bullish'
    else:
        highs = [float(r['high']) for r in recent]
        pivots = _pivot_highs(highs, ACCEL_PIVOT_WIN_D)
        if len(pivots) < ACCEL_MIN_RISING_LOWS:
            return result
        last_pivots = pivots[-(ACCEL_MIN_RISING_LOWS + 2):]
        falling = 0
        for k in range(1, len(last_pivots)):
            if highs[last_pivots[k]] < highs[last_pivots[k - 1]]:
                falling += 1
        result['rising_lows_count'] = falling
        if falling < ACCEL_MIN_RISING_LOWS:
            return result
        result['direction'] = 'bearish'

    result['detected'] = True
    return result


# ── Fitting de linea acelerada ──────────────────────────────────────────────

def _fit_accelerated_support(daily_rows: list[dict]) -> Optional[dict]:
    """
    Busca soporte ascendente empinado en data diaria reciente.
    Reutiliza _try_fit de dynamic_supports con parametros ajustados
    para capturar aceleraciones de corto plazo.
    """
    recent = daily_rows[-ACCEL_DAILY_LOOKBACK:]
    if len(recent) < 30:
        return None

    lows = [float(r['low']) for r in recent]
    body_lows = [min(float(r['open']), float(r['close'])) for r in recent]
    n = len(recent)

    piv_fine = _pivot_lows(lows, ACCEL_PIVOT_WIN_D)
    piv_coarse = _pivot_lows(lows, ACCEL_PIVOT_WIN_D * 2)

    if len(piv_fine) < 2:
        return None

    tl = _try_fit_sup(
        lows, body_lows,
        [piv_fine, piv_coarse],
        min_span=ACCEL_MIN_SPAN_D,
        tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.0, 0.70),
        anchor2_min=0.80,
        n_total=n,
        min_touches=2,
    )

    return tl


def _fit_accelerated_resistance(daily_rows: list[dict]) -> Optional[dict]:
    """
    Busca resistencia descendente empinada en data diaria reciente.
    Espejo de _fit_accelerated_support usando dynamic_resistances.
    """
    recent = daily_rows[-ACCEL_DAILY_LOOKBACK:]
    if len(recent) < 30:
        return None

    highs = [float(r['high']) for r in recent]
    body_highs = [max(float(r['open']), float(r['close'])) for r in recent]
    n = len(recent)

    piv_fine = _pivot_highs(highs, ACCEL_PIVOT_WIN_D)
    piv_coarse = _pivot_highs(highs, ACCEL_PIVOT_WIN_D * 2)

    if len(piv_fine) < 2:
        return None

    tl = _try_fit_res(
        highs, body_highs,
        [piv_fine, piv_coarse],
        min_span=ACCEL_MIN_SPAN_D,
        tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.0, 0.70),
        anchor2_min=0.80,
        n_total=n,
        min_touches=2,
    )

    return tl


# ── Tactical (horizontal fallback) ─────────────────────────────────────────

def _fit_tactical_support(rows: list[dict], tf: str) -> Optional[dict]:
    """Lateral support zone via sideways detection."""
    n = len(rows)
    if n < 6:
        return None
    lows = [float(r['low']) for r in rows]
    body_lows = [min(float(r['open']), float(r['close'])) for r in rows]
    highs = [float(r['high']) for r in rows]
    closes = [float(r['close']) for r in rows]
    return _detect_sideways_sup(lows, body_lows, highs, closes, n, tf)


def _fit_tactical_resistance(rows: list[dict], tf: str) -> Optional[dict]:
    """Lateral resistance zone via sideways detection."""
    n = len(rows)
    if n < 6:
        return None
    highs = [float(r['high']) for r in rows]
    body_highs = [max(float(r['open']), float(r['close'])) for r in rows]
    lows = [float(r['low']) for r in rows]
    closes = [float(r['close']) for r in rows]
    return _detect_sideways_res(highs, body_highs, lows, closes, n, tf)


# ── Stop hint ───────────────────────────────────────────────────────────────

def _compute_stop_hint(tier: dict, side: str) -> float:
    """
    Sugiere precio de stop-loss basado en el valor actual de la linea.

    Soporte ascendente/horizontal: stop debajo.
    Resistencia descendente/horizontal: stop encima.
    """
    buf = STOP_BUFFER_PCT / 100

    if side == 'support':
        if tier.get('kind') == 'horizontal':
            base = tier.get('zone_low', tier['current_value'])
        else:
            base = tier['current_value']
        return round(base * (1 - buf), 4)
    else:
        if tier.get('kind') == 'horizontal':
            base = tier.get('zone_top', tier.get('zone_ceiling', tier['current_value']))
        else:
            base = tier['current_value']
        return round(base * (1 + buf), 4)


# ── Enrichment: agrega campos behavioral al tier_dict ───────────────────────

def _enrich_tier(tier: dict, classification: str, side: str) -> dict:
    """Agrega classification y stop_hint al tier ya armado por _build_tier."""
    tier['classification'] = classification
    tier['stop_hint'] = _compute_stop_hint(tier, side)
    # Normalizar zone fields para soporte horizontal
    if tier.get('kind') == 'horizontal' and side == 'support':
        tier['zone_low'] = tier['current_value']
    if tier.get('kind') == 'horizontal' and side == 'resistance':
        tier['zone_top'] = tier.get('zone_ceiling', tier['current_value'])
        tier['zone_low'] = tier.get('zone_floor', tier['current_value'])
    return tier


# ── Historical tier: soporte/resistencia estructural ────────────────────────

def _get_historical_support(weekly_rows: list[dict]) -> Optional[dict]:
    """
    Soporte estructural: linea ascendente sobre el historico semanal completo.
    Reutiliza _try_fit con los mismos rangos que el tier 'long' de
    dynamic_supports pero sin restriccion de max_span, priorizando el
    soporte del rally vigente.
    """
    if not weekly_rows or len(weekly_rows) < 80:
        return None

    lows = [float(r['low']) for r in weekly_rows]
    body_lows = [min(float(r['open']), float(r['close'])) for r in weekly_rows]
    n = len(weekly_rows)

    if n < 400:
        win, min_span = 6, 25
    else:
        win, min_span = 12, 40

    piv_a = _pivot_lows(lows, win)
    piv_b = _pivot_lows(lows, max(4, win // 2))

    max_span = min(20 * 52, int(n * 0.90))

    tl = _try_fit_sup(
        lows, body_lows,
        [piv_a, piv_b],
        min_span=min_span,
        tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.05, 0.50),
        anchor2_min=0.65,
        n_total=n,
        max_span=max_span,
    )
    return tl


def _get_historical_resistance(weekly_rows: list[dict]) -> Optional[dict]:
    """
    Resistencia estructural: linea descendente sobre el historico semanal.
    """
    if not weekly_rows or len(weekly_rows) < 80:
        return None

    highs = [float(r['high']) for r in weekly_rows]
    body_highs = [max(float(r['open']), float(r['close'])) for r in weekly_rows]
    n = len(weekly_rows)

    if n < 400:
        win, min_span = 6, 25
    else:
        win, min_span = 12, 40

    piv_a = _pivot_highs(highs, win)
    piv_b = _pivot_highs(highs, max(4, win // 2))

    max_span = min(20 * 52, int(n * 0.90))

    tl = _try_fit_res(
        highs, body_highs,
        [piv_a, piv_b],
        min_span=min_span,
        tol_pct=PRICE_TOL_PCT,
        anchor1_range=(0.05, 0.50),
        anchor2_min=0.65,
        n_total=n,
        max_span=max_span,
    )
    return tl


# ── Orquestador principal ──────────────────────────────────────────────────

def get_tiered_sr(
    symbol: str,
    fecha: Optional[date] = None,
) -> dict:
    """
    Devuelve soportes y resistencias clasificados behavioralmente.

    Retorna:
    {
        'symbol':      str,
        'price':       float | None,
        'fecha':       str,
        'support': {
            'historical':  tier_dict | None,
            'accelerated': tier_dict | None,
            'tactical':    tier_dict | None,
        },
        'resistance': {
            'historical':  tier_dict | None,
            'accelerated': tier_dict | None,
            'tactical':    tier_dict | None,
        },
        'acceleration': {
            'support':    accel_info,
            'resistance': accel_info,
        },
    }
    """
    fecha = fecha or date.today()
    empty_side = {'historical': None, 'accelerated': None, 'tactical': None}
    empty_accel = {
        'detected': False, 'direction': None,
        'distance_from_structural_pct': 0.0,
        'slope_ratio': 0.0, 'rising_lows_count': 0,
    }
    base = {
        'symbol': symbol,
        'price': None,
        'fecha': fecha.isoformat(),
        'support': dict(empty_side),
        'resistance': dict(empty_side),
        'acceleration': {
            'support': dict(empty_accel),
            'resistance': dict(empty_accel),
        },
    }

    # ── Cargar datos ────────────────────────────────────────────────────────
    weekly_rows = _load(symbol, 'W', fecha) or []
    daily_rows = _load(symbol, 'D', fecha) or []

    if not weekly_rows and not daily_rows:
        return base

    # Precio actual: preferir la ultima vela disponible (daily > weekly)
    if daily_rows:
        price = float(daily_rows[-1]['close'])
    elif weekly_rows:
        price = float(weekly_rows[-1]['close'])
    else:
        return base
    base['price'] = price

    # ── SOPORTE ─────────────────────────────────────────────────────────────

    # 1. Historical (semanal)
    hist_sup_tl = _get_historical_support(weekly_rows)
    hist_sup_tier = None
    if hist_sup_tl is not None:
        hist_sup_tier = _build_tier_sup(hist_sup_tl, weekly_rows, 'W')
        hist_sup_tier = _enrich_tier(hist_sup_tier, 'historical', 'support')
        base['support']['historical'] = hist_sup_tier

    # 2. Acceleration check
    accel_sup = empty_accel
    if hist_sup_tier and hist_sup_tier['status'] == 'ACTIVE' and daily_rows:
        accel_sup = _detect_acceleration(
            hist_sup_tier['slope_annual_pct'],
            hist_sup_tier['current_value'],
            price,
            daily_rows,
            'support',
        )
        base['acceleration']['support'] = accel_sup

    # 3. Accelerated support (diario) si hay aceleracion
    if accel_sup['detected'] and daily_rows:
        accel_tl = _fit_accelerated_support(daily_rows)
        if accel_tl is not None:
            recent_d = daily_rows[-ACCEL_DAILY_LOOKBACK:]
            accel_tier = _build_tier_sup(accel_tl, recent_d, 'D')
            accel_tier = _enrich_tier(accel_tier, 'accelerated', 'support')
            base['support']['accelerated'] = accel_tier

    # 4. Tactical (horizontal) si no hay acelerada valida
    if base['support']['accelerated'] is None:
        # Intentar primero en daily reciente, luego weekly
        tact_rows, tact_tf = daily_rows, 'D'
        if not tact_rows or len(tact_rows) < 20:
            tact_rows, tact_tf = weekly_rows, 'W'
        tact_tl = _fit_tactical_support(tact_rows, tact_tf) if tact_rows else None
        if tact_tl is not None:
            tact_tier = _build_tier_sup(tact_tl, tact_rows, tact_tf)
            tact_tier = _enrich_tier(tact_tier, 'tactical', 'support')
            base['support']['tactical'] = tact_tier

    # ── RESISTENCIA ─────────────────────────────────────────────────────────

    # 1. Historical (semanal)
    hist_res_tl = _get_historical_resistance(weekly_rows)
    hist_res_tier = None
    if hist_res_tl is not None:
        hist_res_tier = _build_tier_res(hist_res_tl, weekly_rows, 'W')
        hist_res_tier = _enrich_tier(hist_res_tier, 'historical', 'resistance')
        base['resistance']['historical'] = hist_res_tier

    # 2. Acceleration check
    accel_res = empty_accel
    if hist_res_tier and hist_res_tier['status'] == 'ACTIVE' and daily_rows:
        accel_res = _detect_acceleration(
            hist_res_tier['slope_annual_pct'],
            hist_res_tier['current_value'],
            price,
            daily_rows,
            'resistance',
        )
        base['acceleration']['resistance'] = accel_res

    # 3. Accelerated resistance (diario)
    if accel_res['detected'] and daily_rows:
        accel_tl_r = _fit_accelerated_resistance(daily_rows)
        if accel_tl_r is not None:
            recent_d = daily_rows[-ACCEL_DAILY_LOOKBACK:]
            accel_tier_r = _build_tier_res(accel_tl_r, recent_d, 'D')
            accel_tier_r = _enrich_tier(accel_tier_r, 'accelerated', 'resistance')
            base['resistance']['accelerated'] = accel_tier_r

    # 4. Tactical resistance
    if base['resistance']['accelerated'] is None:
        tact_rows_r, tact_tf_r = daily_rows, 'D'
        if not tact_rows_r or len(tact_rows_r) < 20:
            tact_rows_r, tact_tf_r = weekly_rows, 'W'
        tact_tl_r = _fit_tactical_resistance(tact_rows_r, tact_tf_r) if tact_rows_r else None
        if tact_tl_r is not None:
            tact_tier_r = _build_tier_res(tact_tl_r, tact_rows_r, tact_tf_r)
            tact_tier_r = _enrich_tier(tact_tier_r, 'tactical', 'resistance')
            base['resistance']['tactical'] = tact_tier_r

    return base
