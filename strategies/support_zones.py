"""
support_zones.py — Detector de zonas de soporte estructurales y directrices alcistas

Capa estructural reutilizable. NO genera recomendaciones finales de compra/venta.
Detecta donde el precio encontro soporte historicamente y si fue validado.

Estados horizontales:
    NO_SUPPORT              — sin zona de soporte relevante identificada
    SUPPORT_ZONE_DETECTED   — primer toque con rebote validado, sin retest aun
    SUPPORT_ZONE_RETESTED   — segundo toque dentro de la zona (retest activo)
    SUPPORT_HOLDING         — en zona, sin ruptura, mostrando estabilizacion
    SUPPORT_BROKEN          — cierre significativo debajo de zona (soporte roto)
    SUPPORT_BOUNCE_CONFIRMED — rebote confirmado despues del retest

Estados directriz (soporte dinamico):
    NO_TREND_SUPPORT             — sin directriz alcista identificada
    TREND_SUPPORT_DETECTED       — directriz detectada con minimos crecientes alineados
    TREND_SUPPORT_RETESTED       — precio vuelve a testear la directriz
    TREND_SUPPORT_HOLDING        — precio respetando la directriz actualmente
    TREND_SUPPORT_BROKEN         — ruptura de la directriz alcista
    TREND_SUPPORT_BOUNCE_CONFIRMED — rebote confirmado sobre la directriz

Uso externo:
    from strategies.support_zones import (
        analyze_symbol, analyze_trend_support,
        run_universe, save_zones, ensure_table
    )
"""
from datetime import date
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.utils import ema, vol_ratio


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_SZ_MIN_BOUNCE   = 4.0   # rebote minimo % para validar primer toque como soporte
_SZ_ZONE_MARGIN  = 0.03  # zona = center +/- 3%
_SZ_BREAK_PCT    = 0.04  # cierre >4% bajo zone_low = soporte roto
_SZ_BOUNCE_CONF  = 0.015 # rebote >1.5% sobre zone_high = confirmado
_SZ_LOOKBACK     = 120   # barras maximas hacia atras para buscar soportes
_SZ_LOCAL_WIN    = 5     # ventana para detectar minimos locales
_SZ_MIN_ABOVE    = 3     # barras consecutivas sobre zone_high para contar retest
_SZ_CLUSTER_TOL  = 0.03  # tolerancia para agrupar minimos cercanos en zona


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_ohlcv(symbol: str, fecha: date, n: int = 300) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM price_history
                   WHERE simbolo=%s AND fecha<=%s
                   ORDER BY fecha DESC LIMIT %s""",
                (symbol, fecha, n)
            )
            rows = cur.fetchall()
        rows.reverse()
        return rows
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Deteccion de minimos locales validados
# ─────────────────────────────────────────────────────────────────────────────

def _find_validated_lows(
    lows:       list[float],
    highs:      list[float],
    lookback:   int,
    local_win:  int,
    min_bounce: float,
) -> list[tuple[int, float, float]]:
    """
    Encuentra minimos locales en los ultimos `lookback` bars que tuvieron
    un rebote posterior >= min_bounce%.
    Retorna lista de (idx, low_price, bounce_pct).
    """
    n = len(lows)
    start = max(local_win, n - lookback)
    results = []

    for i in range(start, n - local_win):
        w0 = max(0, i - local_win)
        w1 = min(n, i + local_win + 1)
        if lows[i] != min(lows[w0:w1]):
            continue
        future_highs = highs[i + 1: min(i + 16, n)]
        if not future_highs:
            continue
        bounce = (max(future_highs) / lows[i] - 1) * 100
        if bounce >= min_bounce:
            results.append((i, lows[i], bounce))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Agrupacion en zonas (clusters)
# ─────────────────────────────────────────────────────────────────────────────

def _cluster_lows(
    validated: list[tuple[int, float, float]],
    tolerance: float,
) -> list[list[tuple[int, float, float]]]:
    """
    Agrupa minimos cercanos (dentro de tolerance%) en zonas.
    Retorna lista de clusters, cada uno es lista de (idx, low, bounce).
    """
    if not validated:
        return []
    sorted_lows = sorted(validated, key=lambda x: x[1])
    clusters: list[list] = []

    for item in sorted_lows:
        placed = False
        for cluster in clusters:
            center = sum(s[1] for s in cluster) / len(cluster)
            if abs(item[1] / center - 1) <= tolerance:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    return clusters


# ─────────────────────────────────────────────────────────────────────────────
# Deteccion de visits (retests) a la zona
# ─────────────────────────────────────────────────────────────────────────────

def _find_visits(
    zone_low:  float,
    zone_high: float,
    lows:      list[float],
    closes:    list[float],
    start_idx: int,
    min_above: int,
) -> list[int]:
    """
    Detecta visitas a la zona despues de start_idx.
    Una visita = precio estuvo >= min_above barras sobre zone_high,
    luego el low de una barra toca/entra a la zona (low <= zone_high * 1.01).
    Retorna lista de indices donde comienza cada visita.
    """
    visits = []
    n = len(closes)
    consecutive_above = 0
    in_visit = False

    for i in range(start_idx + 1, n):
        in_zone  = lows[i] <= zone_high * 1.01
        above    = closes[i] > zone_high

        if above:
            consecutive_above += 1
            in_visit = False
        elif in_zone and consecutive_above >= min_above:
            if not in_visit:
                visits.append(i)
                in_visit = True
            consecutive_above = 0
        else:
            consecutive_above = 0
            in_visit = False

    return visits


# ─────────────────────────────────────────────────────────────────────────────
# Construccion de zona completa
# ─────────────────────────────────────────────────────────────────────────────

def _build_zone(
    cluster: list[tuple[int, float, float]],
    lows:    list[float],
    highs:   list[float],
    closes:  list[float],
    dates:   list,
    n:       int,
) -> dict:
    """
    Construye un dict de zona con todas las metricas necesarias.
    El anchor es el minimo mas bajo del cluster (enfoque conservador).
    """
    anchor = min(item[1] for item in cluster)
    zone_low  = anchor * (1 - _SZ_ZONE_MARGIN)
    zone_high = anchor * (1 + _SZ_ZONE_MARGIN)

    first_item = min(cluster, key=lambda x: x[0])
    first_idx  = first_item[0]
    first_date = dates[first_idx]

    visits = _find_visits(zone_low, zone_high, lows, closes, first_idx, _SZ_MIN_ABOVE)

    touches_count    = 1 + len(visits)
    last_visit_idx   = visits[-1] if visits else None
    last_visit_date  = dates[last_visit_idx] if last_visit_idx is not None else None

    max_bounce = max(item[2] for item in cluster)

    fh1 = highs[first_idx + 1: min(first_idx + 21, n)]
    rebound_first = (max(fh1) / anchor - 1) * 100 if fh1 else 0.0

    rebound_second = None
    if last_visit_idx is not None:
        fh2 = highs[last_visit_idx + 1: min(last_visit_idx + 21, n)]
        if fh2:
            rebound_second = (max(fh2) / anchor - 1) * 100

    last_any = last_visit_idx if last_visit_idx is not None else first_idx
    recency  = 1.0 - (n - 1 - last_any) / max(n, 1)

    return {
        'center':            anchor,
        'zone_low':          zone_low,
        'zone_high':         zone_high,
        'first_touch_idx':   first_idx,
        'first_touch_date':  first_date,
        'second_touch_idx':  last_visit_idx,
        'second_touch_date': last_visit_date,
        'touches_count':     touches_count,
        'visits':            visits,
        'max_bounce':        max_bounce,
        'rebound_first':     rebound_first,
        'rebound_second':    rebound_second,
        'recency_score':     recency,
    }


def _select_best_zone(zones: list[dict]) -> dict:
    """Elige la zona mas relevante: mas retests + mas reciente + mejor rebote."""
    def _score(z):
        return z['touches_count'] * 3 + z['recency_score'] * 4 + z['max_bounce'] / 20
    return max(zones, key=_score)


# ─────────────────────────────────────────────────────────────────────────────
# Determinacion del estado actual
# ─────────────────────────────────────────────────────────────────────────────

def _determine_state(
    zone:   dict,
    closes: list[float],
    highs:  list[float],
    lows:   list[float],
    n:      int,
) -> tuple[str, float]:
    """
    Determina el estado actual de la zona.
    Retorna (state, deviation_pct).
    deviation_pct = (current_price / zone_center - 1) * 100
    """
    price     = closes[-1]
    zone_low  = zone['zone_low']
    zone_high = zone['zone_high']
    center    = zone['center']
    last_vi   = zone.get('second_touch_idx')
    first_idx = zone['first_touch_idx']
    deviation = (price / center - 1) * 100

    # ── SUPPORT_BROKEN ────────────────────────────────────────────────────────
    # Cualquier close > 4% debajo de zone_low DESPUES del primer toque
    broken_threshold = zone_low * (1 - _SZ_BREAK_PCT)
    for i in range(first_idx + 1, n):
        if closes[i] < broken_threshold:
            if price < zone_low * (1 - _SZ_BREAK_PCT / 2):
                return 'SUPPORT_BROKEN', deviation
            break

    # ── SUPPORT_BOUNCE_CONFIRMED ──────────────────────────────────────────────
    if last_vi is not None:
        post = closes[last_vi:]
        if post and max(post) > zone_high * (1 + _SZ_BOUNCE_CONF):
            if price > zone_high:
                return 'SUPPORT_BOUNCE_CONFIRMED', deviation

    # ── SUPPORT_HOLDING ───────────────────────────────────────────────────────
    # Precio actualmente en/cerca de la zona + estabilizacion + hay retest
    in_zone = lows[-1] <= zone_high * 1.015 and price >= zone_low * 0.985
    if in_zone and last_vi is not None:
        recent_lows = lows[max(0, n - 5):]
        prior_lows  = lows[max(0, n - 15): max(0, n - 5)]
        if prior_lows and min(recent_lows) >= min(prior_lows) * 0.983:
            return 'SUPPORT_HOLDING', deviation

    # ── SUPPORT_ZONE_RETESTED ────────────────────────────────────────────────
    if zone['touches_count'] >= 2:
        return 'SUPPORT_ZONE_RETESTED', deviation

    # ── SUPPORT_ZONE_DETECTED ────────────────────────────────────────────────
    return 'SUPPORT_ZONE_DETECTED', deviation


# ─────────────────────────────────────────────────────────────────────────────
# Lecturas humanas
# ─────────────────────────────────────────────────────────────────────────────

_READINGS = {
    'NO_SUPPORT':               'Sin zona de soporte relevante identificada',
    'SUPPORT_ZONE_DETECTED':    'Zona de soporte detectada - primer toque validado con rebote',
    'SUPPORT_ZONE_RETESTED':    'El precio volvio a una zona donde ya habia rebotado',
    'SUPPORT_HOLDING':          'La zona de soporte fue respetada - precio estabilizando',
    'SUPPORT_BROKEN':           'Soporte roto - evitar compras prematuras',
    'SUPPORT_BOUNCE_CONFIRMED': 'Rebote confirmado sobre soporte - estructura positiva',
}


# ─────────────────────────────────────────────────────────────────────────────
# Jerarquia temporal y scoring de soportes
# ─────────────────────────────────────────────────────────────────────────────

def _classify_timeframe(duration_days: int) -> str:
    if duration_days > 180:  return 'STRUCTURAL'
    if duration_days > 90:   return 'LONG_TERM'
    if duration_days >= 20:  return 'MID_TERM'
    return 'SHORT_TERM'


def _compute_support_score(
    duration_days: int,
    touches:       int,
    max_rebound:   float,
    is_active:     bool,
) -> float:
    """Score 0-10: duracion(3) + toques(3) + rebote(2) + vigente(2)."""
    dur = min(duration_days / 180.0, 1.0) * 3.0
    tch = min(touches / 5.0,         1.0) * 3.0
    reb = min(max_rebound / 15.0,     1.0) * 2.0
    act = 2.0 if is_active else 0.0
    return round(min(dur + tch + reb + act, 10.0), 1)


def _quality_label(timeframe: str, state: str) -> str:
    is_broken = 'BROKEN' in state
    if is_broken and timeframe in ('LONG_TERM', 'STRUCTURAL'):
        return 'BROKEN_MAJOR_SUPPORT'
    if timeframe == 'STRUCTURAL': return 'STRUCTURAL_SUPPORT'
    if timeframe == 'LONG_TERM':  return 'LONG_TERM_SUPPORT'
    if timeframe == 'MID_TERM':   return 'MID_SUPPORT'
    return 'WEAK_SUPPORT'


_QUALITY_READINGS = {
    'WEAK_SUPPORT':         'Soporte de corto plazo',
    'MID_SUPPORT':          'Soporte relevante de mediano plazo',
    'LONG_TERM_SUPPORT':    'Soporte de largo plazo aun vigente',
    'STRUCTURAL_SUPPORT':   'Soporte estructural - nivel de alta relevancia',
    'BROKEN_MAJOR_SUPPORT': 'Ruptura de soporte mayor - cambio de estructura',
}

_TIMEFRAME_LABEL = {
    'SHORT_TERM': 'CORTO',
    'MID_TERM':   'MEDIO',
    'LONG_TERM':  'LARGO',
    'STRUCTURAL': 'ESTRUCTURAL',
}


# ─────────────────────────────────────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────────────────────────────────────

def analyze_symbol(symbol: str, fecha: date) -> Optional[dict]:
    """
    Detecta la zona de soporte mas relevante para el simbolo en la fecha dada.
    Retorna None si no hay datos suficientes.
    """
    rows = _load_ohlcv(symbol, fecha)
    if len(rows) < 40:
        return None

    closes  = [float(r['close'])  for r in rows]
    highs   = [float(r['high'])   for r in rows]
    lows    = [float(r['low'])    for r in rows]
    dates   = [r['fecha']         for r in rows]
    n = len(closes)

    validated = _find_validated_lows(lows, highs, _SZ_LOOKBACK, _SZ_LOCAL_WIN, _SZ_MIN_BOUNCE)

    if not validated:
        return {
            'simbolo': symbol, 'fecha': fecha,
            'state': 'NO_SUPPORT', 'support_price': None,
            'zone_low': None, 'zone_high': None,
            'first_touch_date': None, 'second_touch_date': None,
            'touches_count': 0, 'deviation_pct': None,
            'bounce_confirmed': False,
            'rebound_pct_after_first_touch': None,
            'rebound_pct_after_second_touch': None,
            'reading': _READINGS['NO_SUPPORT'],
            '_zone': None,
        }

    clusters = _cluster_lows(validated, _SZ_CLUSTER_TOL)
    zones    = [_build_zone(c, lows, highs, closes, dates, n) for c in clusters]
    best     = _select_best_zone(zones)

    state, deviation = _determine_state(best, closes, highs, lows, n)

    # Jerarquia temporal
    ft_date       = best['first_touch_date']
    duration_days = (fecha - ft_date).days if ft_date else 0
    is_active     = 'BROKEN' not in state
    timeframe     = _classify_timeframe(duration_days)
    score         = _compute_support_score(
        duration_days, best['touches_count'], best['max_bounce'], is_active
    )
    qlabel  = _quality_label(timeframe, state)
    reading = _QUALITY_READINGS.get(qlabel, _READINGS.get(state, 'Estado desconocido'))

    return {
        'simbolo':                       symbol,
        'fecha':                         fecha,
        'state':                         state,
        'support_price':                 round(best['center'], 2),
        'zone_low':                      round(best['zone_low'], 2),
        'zone_high':                     round(best['zone_high'], 2),
        'first_touch_date':              ft_date,
        'second_touch_date':             best['second_touch_date'],
        'touches_count':                 best['touches_count'],
        'deviation_pct':                 round(deviation, 2),
        'bounce_confirmed':              state == 'SUPPORT_BOUNCE_CONFIRMED',
        'rebound_pct_after_first_touch': round(best['rebound_first'], 2),
        'rebound_pct_after_second_touch': round(best['rebound_second'], 2) if best['rebound_second'] is not None else None,
        'duration_days':                 duration_days,
        'timeframe':                     timeframe,
        'support_score':                 score,
        'quality_label':                 qlabel,
        'reading':                       reading,
        '_zone':                         best,
    }


def run_universe(symbols: list[str], fecha: date) -> list[dict]:
    results = []
    for sym in symbols:
        r = analyze_symbol(sym, fecha)
        if r:
            results.append(r)
        else:
            print(f"  [SKIP] {sym}: datos insuficientes")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Soporte dinamico / directriz alcista
# ─────────────────────────────────────────────────────────────────────────────

_TS_MIN_BOUNCE  = 3.0   # rebote minimo % para lows candidatos a ancla
_TS_LOOKBACK    = 200   # barras hacia atras para buscar directriz
_TS_TOUCH_TOL   = 0.025 # tolerancia ±2.5% para contar toque en la linea
_TS_BREAK_PCT   = 0.03  # close >3% debajo de linea = ruptura
_TS_NEAR_PCT    = 0.03  # dentro de 3% de la linea = testeo activo
_TS_MIN_SEP     = 15    # separacion minima en barras entre las dos anclas base
_TS_MIN_TOUCHES = 2     # minimo de lows tocando la linea para considerarla valida


def _find_best_trendline(
    lows:     list[float],
    highs:    list[float],
    closes:   list[float],
    dates:    list,
    n:        int,
    lookback: int = None,
) -> Optional[dict]:
    """
    Detecta la mejor directriz alcista de soporte.
    Prueba pares de minimos crecientes como anclas y cuenta cuantos otros
    minimos validados caen cerca de la linea resultante.
    Las lineas rotas siguen siendo retornadas; el estado BROKEN se asigna en
    _determine_trend_state, no aqui.
    """
    lb        = lookback if lookback is not None else _TS_LOOKBACK
    validated = _find_validated_lows(lows, highs, lb, _SZ_LOCAL_WIN, _TS_MIN_BOUNCE)
    if len(validated) < 2:
        return None

    best_line  = None
    best_score = -1e9

    for a in range(len(validated)):
        xi, yi, _ = validated[a]
        for b in range(a + 1, len(validated)):
            xj, yj, _ = validated[b]

            # La directriz debe ser ascendente
            if yj <= yi * 1.005:
                continue
            # Separacion minima entre anclas
            if xj - xi < _TS_MIN_SEP:
                continue

            slope     = (yj - yi) / (xj - xi)   # precio por barra
            intercept = yi - slope * xi

            # Contar lows validados que tocan la linea (desde el primer ancla)
            touch_idxs = []
            for vk in validated:
                xk, yk, _ = vk
                if xk < xi:
                    continue
                line_at_xk = slope * xk + intercept
                if line_at_xk > 0 and abs(yk / line_at_xk - 1) <= _TS_TOUCH_TOL:
                    touch_idxs.append(xk)

            if len(touch_idxs) < _TS_MIN_TOUCHES:
                continue

            # Contar rupturas (solo para scoring, no filtramos lineas rotas)
            hard_breaks = sum(
                1 for k in range(xi, n)
                if (slope * k + intercept) > 0
                and closes[k] < (slope * k + intercept) * (1 - _TS_BREAK_PCT)
            )

            last_touch = max(touch_idxs)
            recency    = 1.0 - (n - 1 - last_touch) / max(n, 1)

            # Score: toques y recencia importan mas que rupturas
            score = len(touch_idxs) * 4 + recency * 5 - hard_breaks * 0.4

            if score > best_score:
                best_score = score
                touch_dates = [dates[k] for k in touch_idxs if k < n]
                best_line = {
                    'slope':          slope,
                    'intercept':      intercept,
                    'anchor_idx':     xi,
                    'anchor_price':   yi,
                    'touch_indices':  touch_idxs,
                    'touch_dates':    touch_dates,
                    'touch_count':    len(touch_idxs),
                    'last_touch_idx': last_touch,
                    'hard_breaks':    hard_breaks,
                    'recency':        recency,
                }

    return best_line


def _determine_trend_state(
    tl:     dict,
    closes: list[float],
    lows:   list[float],
    n:      int,
) -> tuple[str, float]:
    """
    Determina el estado actual de la directriz alcista.
    Retorna (state, deviation_pct) donde deviation_pct = (price/line_today - 1)*100.
    """
    slope          = tl['slope']
    intercept      = tl['intercept']
    last_touch_idx = tl['last_touch_idx']
    price          = closes[-1]
    last_idx       = n - 1

    line_today = slope * last_idx + intercept
    if line_today <= 0:
        return 'TREND_SUPPORT_DETECTED', 0.0

    deviation = (price / line_today - 1) * 100

    # BROKEN: closes recientes significativamente debajo de la linea
    recent_breaks = sum(
        1 for k in range(max(0, n - 5), n)
        if closes[k] < (slope * k + intercept) * (1 - _TS_BREAK_PCT)
    )
    if recent_breaks >= 2 or closes[-1] < line_today * (1 - _TS_BREAK_PCT * 1.5):
        return 'TREND_SUPPORT_BROKEN', deviation

    # BOUNCE_CONFIRMED: testeo la linea y luego reboto con fuerza
    if last_touch_idx < n - 3:
        post = closes[last_touch_idx:]
        if post:
            line_at_touch = slope * last_touch_idx + intercept
            if line_at_touch > 0:
                bounce = (max(post) / line_at_touch - 1) * 100
                if bounce >= 4.0 and price > line_today * (1 + _TS_NEAR_PCT):
                    return 'TREND_SUPPORT_BOUNCE_CONFIRMED', deviation

    # HOLDING: precio actualmente cerca de la linea
    if abs(price / line_today - 1) <= _TS_NEAR_PCT * 1.5:
        return 'TREND_SUPPORT_HOLDING', deviation

    # RETESTED: ultimo toque muy reciente
    if n - 1 - last_touch_idx < 10:
        return 'TREND_SUPPORT_RETESTED', deviation

    return 'TREND_SUPPORT_DETECTED', deviation


_TS_READINGS = {
    'NO_TREND_SUPPORT':              'Sin directriz alcista identificada',
    'TREND_SUPPORT_DETECTED':        'Directriz alcista detectada - minimos crecientes alineados',
    'TREND_SUPPORT_RETESTED':        'El precio vuelve a testear la directriz de tendencia',
    'TREND_SUPPORT_HOLDING':         'Directriz alcista historica aun vigente - precio respetando soporte',
    'TREND_SUPPORT_BROKEN':          'Ruptura de soporte dinamico - estructura de tendencia danada',
    'TREND_SUPPORT_BOUNCE_CONFIRMED':'Rebote confirmado sobre directriz - soporte historico respetado',
}


def analyze_trend_support(symbol: str, fecha: date) -> Optional[dict]:
    """
    Detecta la directriz alcista de soporte mas relevante para el simbolo.
    Usa ventana de 400 barras con lookback completo para capturar directrices
    de mediano/largo plazo incluso si fueron rotas recientemente.
    """
    rows = _load_ohlcv(symbol, fecha, n=400)
    if len(rows) < 60:
        return None

    closes = [float(r['close']) for r in rows]
    highs  = [float(r['high'])  for r in rows]
    lows   = [float(r['low'])   for r in rows]
    dates  = [r['fecha']        for r in rows]
    n      = len(closes)

    # Usar lookback = n para buscar en toda la ventana cargada
    tl = _find_best_trendline(lows, highs, closes, dates, n, lookback=n)

    if tl is None:
        return {
            'simbolo': symbol, 'fecha': fecha,
            'state':   'NO_TREND_SUPPORT',
            'reading': _TS_READINGS['NO_TREND_SUPPORT'],
            '_trendline': None, '_dates': dates, '_n': n,
        }

    state, deviation = _determine_trend_state(tl, closes, lows, n)
    line_today = tl['slope'] * (n - 1) + tl['intercept']

    # Jerarquia temporal (basada en la fecha del primer ancla)
    anchor_date   = dates[tl['anchor_idx']]
    duration_days = (fecha - anchor_date).days if anchor_date else 0
    is_active     = 'BROKEN' not in state
    timeframe     = _classify_timeframe(duration_days)
    score         = _compute_support_score(
        duration_days, tl['touch_count'], tl['recency'] * 15, is_active
    )
    qlabel  = _quality_label(timeframe, state)
    reading = _QUALITY_READINGS.get(qlabel, _TS_READINGS.get(state, 'Estado desconocido'))

    return {
        'simbolo':      symbol,
        'fecha':        fecha,
        'state':        state,
        'deviation_pct': round(deviation, 2),
        'touch_count':  tl['touch_count'],
        'touch_dates':  tl['touch_dates'],
        'line_current': round(line_today, 2),
        'duration_days': duration_days,
        'timeframe':    timeframe,
        'support_score': score,
        'quality_label': qlabel,
        'reading':      reading,
        '_trendline':   tl,
        '_dates':       dates,
        '_n':           n,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS support_zones (
    id                           INT AUTO_INCREMENT PRIMARY KEY,
    fecha                        DATE          NOT NULL,
    simbolo                      VARCHAR(20)   NOT NULL,
    support_price                FLOAT,
    zone_low                     FLOAT,
    zone_high                    FLOAT,
    first_touch_date             DATE,
    second_touch_date            DATE,
    touches_count                INT           DEFAULT 1,
    deviation_pct                FLOAT,
    state                        VARCHAR(40),
    bounce_confirmed             TINYINT(1)    DEFAULT 0,
    rebound_pct_after_first      FLOAT,
    rebound_pct_after_second     FLOAT,
    reading                      VARCHAR(500),
    created_at                   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sz_fecha_sym (fecha, simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def ensure_table() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
        conn.commit()
    finally:
        conn.close()


def save_zones(results: list[dict]) -> int:
    if not results:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for r in results:
                cur.execute(
                    """INSERT INTO support_zones
                       (fecha, simbolo, support_price, zone_low, zone_high,
                        first_touch_date, second_touch_date, touches_count,
                        deviation_pct, state, bounce_confirmed,
                        rebound_pct_after_first, rebound_pct_after_second, reading)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                         support_price        = VALUES(support_price),
                         zone_low             = VALUES(zone_low),
                         zone_high            = VALUES(zone_high),
                         first_touch_date     = VALUES(first_touch_date),
                         second_touch_date    = VALUES(second_touch_date),
                         touches_count        = VALUES(touches_count),
                         deviation_pct        = VALUES(deviation_pct),
                         state                = VALUES(state),
                         bounce_confirmed     = VALUES(bounce_confirmed),
                         rebound_pct_after_first  = VALUES(rebound_pct_after_first),
                         rebound_pct_after_second = VALUES(rebound_pct_after_second),
                         reading              = VALUES(reading)
                    """,
                    (
                        r['fecha'], r['simbolo'],
                        r['support_price'], r['zone_low'], r['zone_high'],
                        r['first_touch_date'], r['second_touch_date'],
                        r['touches_count'], r['deviation_pct'],
                        r['state'], int(r['bounce_confirmed']),
                        r['rebound_pct_after_first_touch'],
                        r['rebound_pct_after_second_touch'],
                        r['reading'],
                    )
                )
        conn.commit()
        return len(results)
    finally:
        conn.close()
