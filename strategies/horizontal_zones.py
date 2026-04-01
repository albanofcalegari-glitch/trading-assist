"""
horizontal_zones.py — Detector de zonas horizontales de soporte/resistencia

Usa datos semanales de ohlcv_extended para detectar zonas de precio
donde el activo encontró soporte o resistencia múltiples veces.

Concepto: un trader identifica niveles HORIZONTALES de precio (no líneas
diagonales) donde el precio rebota repetidamente.  Esto es lo que
TradingView y el análisis técnico real usan como soporte/resistencia.

Output: múltiples zonas para soporte y resistencia, ordenadas por score.

Uso:
    from strategies.horizontal_zones import detect_horizontal_zones
    result = detect_horizontal_zones('DIS')
"""

from datetime import date, timedelta
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn


# ─────────────────────────────────────────────────────────────────────────────
# Constantes — tunables
# ─────────────────────────────────────────────────────────────────────────────

_PIVOT_WIN       = 5       # barras a cada lado para pivot detection (semanal)
_CLUSTER_TOL     = 0.03    # 3% single-linkage tolerance para clustering
_CLUSTER_SPREAD  = 0.04    # 4% max spread total dentro de un cluster
_ZONE_PAD        = 0.005   # padding extra ±0.5% sobre min/max del cluster
_MIN_TOUCHES     = 3       # mínimo de toques totales para zona válida
_MIN_RECENT      = 1       # mínimo de toques en últimos 3 años
_MAX_DIST_PCT    = 20.0    # máxima distancia zona-precio para incluir
_BREAK_MARGIN    = 0.04    # close >4% fuera de zona en 3+ de últimas 5 = broken
_LOOKBACK_YEARS  = 10      # años de historia a analizar
_RECENT_YEARS    = 3       # qué cuenta como "reciente"
_MAX_ZONES       = 3       # zonas retornadas por tipo (primary + secondary + 1)
_MERGE_TOL       = 0.05    # zonas con centros a ≤5% se mergean

# ── Excepción 2-touch (zonas weak) ───────────────────────────────────────────
_WEAK_MAX_DIST   = 10.0    # max distancia zona-precio para 2-touch
_WEAK_MAX_AGE_Y  = 2       # ambos pivots dentro de últimos N años
_WEAK_MAX_SPREAD = 0.05    # max spread entre los 2 pivots: 5%
_WEAK_PENALTY    = 3.0     # penalización de score vs zonas normales
_WEAK_NEARBY_TOL = 0.10    # rechazo si zona 3+ toques tiene centro a ≤10%


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_weekly(symbol: str, fecha_max: date) -> list[dict]:
    """Carga histórico semanal completo desde ohlcv_extended."""
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
# Detección de pivotes
# ─────────────────────────────────────────────────────────────────────────────

def _find_pivot_lows(lows: list[float], win: int) -> list[int]:
    """Mínimos locales: low[i] es el menor en [i-win, i+win]."""
    pivots = []
    n = len(lows)
    for i in range(win, n - win):
        val = lows[i]
        if val <= 0:
            continue
        ok = True
        for j in range(i - win, i):
            if lows[j] < val:
                ok = False
                break
        if not ok:
            continue
        for j in range(i + 1, i + win + 1):
            if lows[j] < val:
                ok = False
                break
        if ok:
            pivots.append(i)
    return pivots


def _find_pivot_highs(highs: list[float], win: int) -> list[int]:
    """Máximos locales: high[i] es el mayor en [i-win, i+win]."""
    pivots = []
    n = len(highs)
    for i in range(win, n - win):
        val = highs[i]
        if val <= 0:
            continue
        ok = True
        for j in range(i - win, i):
            if highs[j] > val:
                ok = False
                break
        if not ok:
            continue
        for j in range(i + 1, i + win + 1):
            if highs[j] > val:
                ok = False
                break
        if ok:
            pivots.append(i)
    return pivots


# ─────────────────────────────────────────────────────────────────────────────
# Clustering — single-linkage por precio
# ─────────────────────────────────────────────────────────────────────────────

def _cluster_pivots(
    pivot_indices: list[int],
    prices:        list[float],
    dates:         list,
    tolerance:     float,
    max_spread:    float = _CLUSTER_SPREAD,
) -> list[list[dict]]:
    """
    Agrupa pivots cuyos precios están dentro de tolerance%.
    Single-linkage con constraint de spread máximo: si agregar el pivot
    haría que el rango del cluster supere max_spread, se crea cluster nuevo.
    """
    items = sorted(
        [{'idx': i, 'price': prices[i], 'fecha': dates[i]} for i in pivot_indices],
        key=lambda x: x['price'],
    )
    if not items:
        return []

    clusters: list[list[dict]] = [[items[0]]]

    for item in items[1:]:
        cur = clusters[-1]
        max_in = max(p['price'] for p in cur)
        min_in = min(p['price'] for p in cur)
        # Single-linkage: adjacent within tolerance AND total range within max_spread
        if (item['price'] / max_in - 1 <= tolerance and
                item['price'] / min_in - 1 <= max_spread):
            cur.append(item)
        else:
            clusters.append([item])

    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# Construcción y scoring de zona
# ─────────────────────────────────────────────────────────────────────────────

def _build_zone(
    cluster:       list[dict],
    current_price: float,
    today:         date,
    zone_type:     str,      # 'support' | 'resistance'
) -> Optional[dict]:
    """
    Construye zona a partir de un cluster de pivots.
    Retorna None si no pasa filtros.
    """
    prices = [p['price'] for p in cluster]
    center = sum(prices) / len(prices)

    zone_low  = min(prices) * (1 - _ZONE_PAD)
    zone_high = max(prices) * (1 + _ZONE_PAD)

    total_touches = len(cluster)

    cutoff_recent = today - timedelta(days=_RECENT_YEARS * 365)
    recent_touches = sum(1 for p in cluster if p['fecha'] >= cutoff_recent)

    # ── Filtros ────────────────────────────────────────────────────────────────
    dist_pct = abs(current_price / center - 1) * 100
    is_weak = False

    if total_touches >= _MIN_TOUCHES:
        # Regla normal: >=3 toques
        if recent_touches < _MIN_RECENT:
            return None
        if dist_pct > _MAX_DIST_PCT:
            return None
    elif total_touches == 2:
        # Excepción controlada: 2 toques bajo criterios estrictos
        cutoff_2y = today - timedelta(days=_WEAK_MAX_AGE_Y * 365)
        both_recent = all(p['fecha'] >= cutoff_2y for p in cluster)
        spread_ok = (max(prices) / min(prices) - 1) <= _WEAK_MAX_SPREAD
        dist_ok = dist_pct <= _WEAK_MAX_DIST
        if both_recent and spread_ok and dist_ok:
            is_weak = True
        else:
            return None
    else:
        return None

    # ── Score ──────────────────────────────────────────────────────────────────
    last_touch_date = max(p['fecha'] for p in cluster)
    days_since      = (today - last_touch_date).days
    recency         = max(0, 1.0 - days_since / (365 * 5))

    proximity   = max(0, 1.0 - dist_pct / _MAX_DIST_PCT)
    avg_age     = sum((today - p['fecha']).days for p in cluster) / len(cluster)
    age_penalty = min(avg_age / (365 * 10), 1.0)

    score = (
        recent_touches * 4.0
        + total_touches * 2.0
        + proximity     * 3.0
        + recency       * 2.0
        - age_penalty   * 1.5
    )
    if is_weak:
        score -= _WEAK_PENALTY

    strength = 'weak' if is_weak else ('strong' if total_touches >= 5 else 'normal')
    sorted_pivots = sorted(cluster, key=lambda p: p['fecha'])

    return {
        'zone_low':        round(zone_low, 2),
        'zone_high':       round(zone_high, 2),
        'center':          round(center, 2),
        'total_touches':   total_touches,
        'recent_touches':  recent_touches,
        'distance_pct':    round(dist_pct, 2),
        'last_touch':      str(last_touch_date),
        'first_touch':     str(min(p['fecha'] for p in cluster)),
        'score':           round(score, 2),
        'type':            zone_type,
        'strength':        strength,
        'pivots':          [
            {'fecha': str(p['fecha']), 'price': round(p['price'], 2)}
            for p in sorted_pivots
        ],
    }


def _is_broken(
    zone:    dict,
    closes:  list[float],
    zone_type: str,
) -> bool:
    """
    Support roto: ≥3 de últimos 5 cierres semanales bajo zone_low - margen.
    Resistance rota: ≥3 de últimos 5 cierres sobre zone_high + margen.
    """
    if len(closes) < 5:
        return False

    recent = closes[-5:]

    if zone_type == 'support':
        thresh = zone['zone_low'] * (1 - _BREAK_MARGIN)
        return sum(1 for c in recent if c < thresh) >= 3
    else:
        thresh = zone['zone_high'] * (1 + _BREAK_MARGIN)
        return sum(1 for c in recent if c > thresh) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# Merge de zonas cercanas + ranking
# ─────────────────────────────────────────────────────────────────────────────

def _merge_close_zones(zones: list[dict], merge_tol: float = _MERGE_TOL) -> list[dict]:
    """
    Mergea zonas cuya distancia entre centros es ≤ merge_tol.
    Constraint: el rango resultante no puede exceder 10%.
    """
    if len(zones) <= 1:
        return zones

    zones = sorted(zones, key=lambda z: z['center'])
    merged: list[dict] = [zones[0]]

    for z in zones[1:]:
        prev = merged[-1]
        combined_pivots = prev['pivots'] + z['pivots']
        all_prices = [p['price'] for p in combined_pivots]
        result_range = max(all_prices) / min(all_prices) - 1

        if z['center'] / prev['center'] - 1 <= merge_tol and result_range <= 0.10:
            merged[-1] = {
                'zone_low':        round(min(all_prices) * (1 - _ZONE_PAD), 2),
                'zone_high':       round(max(all_prices) * (1 + _ZONE_PAD), 2),
                'center':          round(sum(all_prices) / len(all_prices), 2),
                'total_touches':   prev['total_touches'] + z['total_touches'],
                'recent_touches':  prev['recent_touches'] + z['recent_touches'],
                'distance_pct':    min(prev['distance_pct'], z['distance_pct']),
                'last_touch':      max(prev['last_touch'], z['last_touch']),
                'first_touch':     min(prev['first_touch'], z['first_touch']),
                'score':           round(max(prev['score'], z['score'])
                                         + min(prev['score'], z['score']) * 0.5, 2),
                'type':            prev['type'],
                'pivots':          sorted(combined_pivots, key=lambda p: p['fecha']),
            }
        else:
            merged.append(z)

    return merged


def _filter_weak_near_strong(zones: list[dict]) -> list[dict]:
    """Elimina zonas weak si hay una zona de 3+ toques con centro a ≤_WEAK_NEARBY_TOL."""
    strong = [z for z in zones if z.get('strength') != 'weak']
    if not strong:
        return zones

    result = list(strong)
    for z in zones:
        if z.get('strength') != 'weak':
            continue
        dominated = any(
            abs(z['center'] / s['center'] - 1) <= _WEAK_NEARBY_TOL
            for s in strong
        )
        if not dominated:
            result.append(z)
    return result


def _assign_ranks(zones: list[dict]) -> list[dict]:
    """Asigna rank='primary' al top-1, 'secondary' al top-2, 'tertiary' al resto.
    Zonas weak no pueden ser primary si existe alguna zona normal/strong."""
    has_strong = any(z.get('strength', 'normal') != 'weak' for z in zones)
    zones = sorted(
        zones,
        key=lambda z: (z.get('strength') == 'weak' and has_strong, -z['score']),
    )
    for i, z in enumerate(zones):
        z['rank'] = 'primary' if i == 0 else ('secondary' if i == 1 else 'tertiary')
    return zones


# ─────────────────────────────────────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────────────────────────────────────

def detect_horizontal_zones(
    symbol: str,
    fecha:  date = None,
) -> dict:
    """
    Detecta zonas horizontales de soporte y resistencia usando datos
    semanales de ohlcv_extended.

    Retorna dict con:
      symbol, fecha, current_price,
      support_zones:    [{zone_low, zone_high, center, total_touches, ...}],
      resistance_zones: [{...}],
      status: 'OK' | 'INSUFFICIENT_DATA'
    """
    if fecha is None:
        fecha = date.today()

    rows = _load_weekly(symbol, fecha)

    if len(rows) < 52:
        return {
            'symbol': symbol, 'fecha': str(fecha),
            'current_price': None,
            'support_zones': [], 'resistance_zones': [],
            'timeframe': 'W', 'status': 'INSUFFICIENT_DATA',
            'pivot_lows_found': 0, 'pivot_highs_found': 0,
        }

    # Limitar a los últimos _LOOKBACK_YEARS
    cutoff = fecha - timedelta(days=_LOOKBACK_YEARS * 365)
    rows = [r for r in rows if r['fecha'] >= cutoff]

    if len(rows) < 52:
        return {
            'symbol': symbol, 'fecha': str(fecha),
            'current_price': None,
            'support_zones': [], 'resistance_zones': [],
            'timeframe': 'W', 'status': 'INSUFFICIENT_DATA',
            'pivot_lows_found': 0, 'pivot_highs_found': 0,
        }

    closes = [float(r['close']) for r in rows]
    highs  = [float(r['high'])  for r in rows]
    lows   = [float(r['low'])   for r in rows]
    dates  = [r['fecha']        for r in rows]
    n      = len(closes)
    price  = closes[-1]

    # ── Soporte: pivot lows → cluster → zonas ─────────────────────────────────
    piv_low_idxs       = _find_pivot_lows(lows, _PIVOT_WIN)
    support_clusters   = _cluster_pivots(piv_low_idxs, lows, dates, _CLUSTER_TOL)
    support_zones      = []

    for cluster in support_clusters:
        zone = _build_zone(cluster, price, fecha, 'support')
        if zone and not _is_broken(zone, closes, 'support'):
            support_zones.append(zone)

    support_zones = _merge_close_zones(support_zones)
    for z in support_zones:
        t = z['total_touches']
        z['strength'] = 'weak' if t == 2 else ('strong' if t >= 5 else 'normal')
    support_zones = _filter_weak_near_strong(support_zones)
    support_zones = _assign_ranks(support_zones)[:_MAX_ZONES]

    # ── Resistencia: pivot highs → cluster → zonas ────────────────────────────
    piv_high_idxs       = _find_pivot_highs(highs, _PIVOT_WIN)
    resistance_clusters = _cluster_pivots(piv_high_idxs, highs, dates, _CLUSTER_TOL)
    resistance_zones    = []

    for cluster in resistance_clusters:
        zone = _build_zone(cluster, price, fecha, 'resistance')
        if zone and not _is_broken(zone, closes, 'resistance'):
            resistance_zones.append(zone)

    resistance_zones = _merge_close_zones(resistance_zones)
    for z in resistance_zones:
        t = z['total_touches']
        z['strength'] = 'weak' if t == 2 else ('strong' if t >= 5 else 'normal')
    resistance_zones = _filter_weak_near_strong(resistance_zones)
    resistance_zones = _assign_ranks(resistance_zones)[:_MAX_ZONES]

    return {
        'symbol':           symbol,
        'fecha':            str(fecha),
        'current_price':    round(price, 2),
        'support_zones':    support_zones,
        'resistance_zones': resistance_zones,
        'timeframe':        'W',
        'status':           'OK',
        'pivot_lows_found':  len(piv_low_idxs),
        'pivot_highs_found': len(piv_high_idxs),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI diagnóstico
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'DIS'
    result = detect_horizontal_zones(symbol)

    print(f"\n{'='*70}")
    print(f"  HORIZONTAL ZONES — {symbol}")
    print(f"{'='*70}")
    print(f"  Precio actual:  ${result['current_price']}")
    print(f"  Pivot lows:     {result['pivot_lows_found']}")
    print(f"  Pivot highs:    {result['pivot_highs_found']}")
    print(f"  Status:         {result['status']}")

    print(f"\n── ZONAS DE SOPORTE ({len(result['support_zones'])}) ──")
    for i, z in enumerate(result['support_zones'], 1):
        print(f"\n  [{i}] ${z['zone_low']:.2f} — ${z['zone_high']:.2f}"
              f"  (centro ${z['center']:.2f})")
        print(f"      Toques: {z['total_touches']} total,"
              f" {z['recent_touches']} recientes (2a)")
        print(f"      Dist: {z['distance_pct']:.1f}%  |  Score: {z['score']:.1f}")
        print(f"      Primer toque: {z['first_touch']}  |"
              f"  Último: {z['last_touch']}")
        print(f"      Pivots:")
        for p in z['pivots']:
            print(f"        {p['fecha']}  ${p['price']:.2f}")

    print(f"\n── ZONAS DE RESISTENCIA ({len(result['resistance_zones'])}) ──")
    for i, z in enumerate(result['resistance_zones'], 1):
        print(f"\n  [{i}] ${z['zone_low']:.2f} — ${z['zone_high']:.2f}"
              f"  (centro ${z['center']:.2f})")
        print(f"      Toques: {z['total_touches']} total,"
              f" {z['recent_touches']} recientes (2a)")
        print(f"      Dist: {z['distance_pct']:.1f}%  |  Score: {z['score']:.1f}")
        print(f"      Primer toque: {z['first_touch']}  |"
              f"  Último: {z['last_touch']}")
        print(f"      Pivots:")
        for p in z['pivots']:
            print(f"        {p['fecha']}  ${p['price']:.2f}")
