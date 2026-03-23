"""
rsi_divergence.py -- Motor de divergencias precio-RSI

Motor independiente. No depende de Trend+Pullback ni Reversal.
Detecta agotamiento de tendencia mediante desconexion entre precio y RSI.

Tipos de divergencia:
    Alcista -- precio hace minimo mas bajo, RSI hace minimo mas alto
               => debilidad bajista que pierde fuerza, posible rebote

    Bajista -- precio hace maximo mas alto, RSI hace maximo mas bajo
               => fuerza alcista que se agota, posible techo

Estados:
    NO_DIVERGENCE                -- sin divergencia activa detectada
    BULLISH_DIVERGENCE_FORMING   -- condicion detectada, sin confirmacion aun
    BULLISH_DIVERGENCE_CONFIRMED -- divergencia + vela/EMA confirman rebote
    BEARISH_DIVERGENCE_FORMING   -- condicion detectada, sin confirmacion aun
    BEARISH_DIVERGENCE_CONFIRMED -- divergencia + vela/EMA confirman debilidad

Uso externo:
    from strategies.rsi_divergence import analyze_symbol, run_universe, save_signals, ensure_table
"""
from datetime import date
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn


# -----------------------------------------------------------------------------
# Constantes
# -----------------------------------------------------------------------------

_RSI_PERIOD     = 14    # periodo RSI (Wilder)
_PIVOT_WIN      = 5     # barras a cada lado para confirmar pivot local
_MIN_SEP        = 8     # separacion minima entre pivots (barras)
_MAX_SEP        = 70    # separacion maxima entre pivots (barras)
_LOOKBACK       = 120   # barras hacia atras para buscar pivots
_RECENCY        = 35    # el segundo pivot debe estar dentro de los ultimos N bars
_MIN_PRICE_DIFF = 0.003  # diferencia minima de precio entre pivots (0.3%)
_MIN_RSI_DIFF   = 1.5    # diferencia minima RSI entre pivots (puntos)
_BULL_RSI_MAX   = 65     # RSI en lows alcistas debe estar por debajo de este valor
_BEAR_RSI_MIN   = 35     # RSI en highs bajistas debe estar por encima de este valor


# -----------------------------------------------------------------------------
# Carga de datos
# -----------------------------------------------------------------------------

def _load_ohlcv(symbol: str, fecha: date, n: int = 280) -> list[dict]:
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


# -----------------------------------------------------------------------------
# RSI en serie completa (un valor por barra, suavizado de Wilder)
# -----------------------------------------------------------------------------

def _rsi_series(closes: list[float], n: int = 14) -> list[Optional[float]]:
    """
    Calcula RSI para cada barra usando suavizado de Wilder.
    result[i] = RSI en la barra i (None si datos insuficientes).
    result[0..n-1] = None, result[n..] = valor RSI.
    """
    result = [None] * len(closes)
    if len(closes) < n + 1:
        return result

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains  = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n

    def _val(ag, al):
        return 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)

    result[n] = _val(avg_g, avg_l)
    for i in range(n, len(deltas)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
        result[i + 1] = _val(avg_g, avg_l)

    return result


# -----------------------------------------------------------------------------
# Deteccion de pivots locales
# -----------------------------------------------------------------------------

def _pivot_lows(
    prices:    list[float],
    rsi_vals:  list[Optional[float]],
    lookback:  int,
    pivot_win: int,
) -> list[tuple[int, float, float]]:
    """
    Minimos locales en precio con RSI disponible.
    Retorna [(idx, price, rsi), ...] ordenados por idx ASC.
    """
    n     = len(prices)
    start = max(pivot_win, n - lookback)
    out   = []
    for i in range(start, n - pivot_win):
        if rsi_vals[i] is None:
            continue
        w0 = max(0, i - pivot_win)
        w1 = min(n, i + pivot_win + 1)
        if prices[i] == min(prices[w0:w1]):
            out.append((i, prices[i], rsi_vals[i]))
    return out


def _pivot_highs(
    prices:    list[float],
    rsi_vals:  list[Optional[float]],
    lookback:  int,
    pivot_win: int,
) -> list[tuple[int, float, float]]:
    """
    Maximos locales en precio con RSI disponible.
    Retorna [(idx, price, rsi), ...] ordenados por idx ASC.
    """
    n     = len(prices)
    start = max(pivot_win, n - lookback)
    out   = []
    for i in range(start, n - pivot_win):
        if rsi_vals[i] is None:
            continue
        w0 = max(0, i - pivot_win)
        w1 = min(n, i + pivot_win + 1)
        if prices[i] == max(prices[w0:w1]):
            out.append((i, prices[i], rsi_vals[i]))
    return out


# -----------------------------------------------------------------------------
# Busqueda de divergencias
# -----------------------------------------------------------------------------

def _best_bullish_pair(
    lows:     list[float],
    rsi_vals: list[Optional[float]],
    n:        int,
) -> Optional[tuple]:
    """
    Busca el mejor par de minimos que forme divergencia alcista.
    Criterio: price2 < price1, rsi2 > rsi1.
    El segundo pivot debe ser reciente (_RECENCY bars).
    Retorna (idx1, p1, r1, idx2, p2, r2) con mayor diferencia RSI, o None.
    """
    pivots = _pivot_lows(lows, rsi_vals, _LOOKBACK, _PIVOT_WIN)
    if len(pivots) < 2:
        return None

    best          = None
    best_rsi_diff = _MIN_RSI_DIFF

    for i in range(len(pivots) - 1, 0, -1):
        idx2, p2, r2 = pivots[i]
        # Pivot2 debe ser reciente
        if n - 1 - idx2 > _RECENCY:
            continue
        # RSI no debe estar en zona sobrecomprada (no tiene sentido buscar
        # divergencia alcista si el RSI ya esta alto)
        if r2 >= _BULL_RSI_MAX:
            continue

        for j in range(i - 1, -1, -1):
            idx1, p1, r1 = pivots[j]
            sep = idx2 - idx1
            if sep < _MIN_SEP or sep > _MAX_SEP:
                continue
            if r1 >= _BULL_RSI_MAX:
                continue

            price_lower = p2 < p1 * (1 - _MIN_PRICE_DIFF)
            rsi_higher  = r2 > r1 + _MIN_RSI_DIFF

            if price_lower and rsi_higher:
                rsi_diff = r2 - r1
                if rsi_diff > best_rsi_diff:
                    best_rsi_diff = rsi_diff
                    best = (idx1, p1, r1, idx2, p2, r2)

    return best


def _best_bearish_pair(
    highs:    list[float],
    rsi_vals: list[Optional[float]],
    n:        int,
) -> Optional[tuple]:
    """
    Busca el mejor par de maximos que forme divergencia bajista.
    Criterio: price2 > price1, rsi2 < rsi1.
    El segundo pivot debe ser reciente (_RECENCY bars).
    Retorna (idx1, p1, r1, idx2, p2, r2) con mayor diferencia RSI, o None.
    """
    pivots = _pivot_highs(highs, rsi_vals, _LOOKBACK, _PIVOT_WIN)
    if len(pivots) < 2:
        return None

    best          = None
    best_rsi_diff = _MIN_RSI_DIFF

    for i in range(len(pivots) - 1, 0, -1):
        idx2, p2, r2 = pivots[i]
        if n - 1 - idx2 > _RECENCY:
            continue
        if r2 <= _BEAR_RSI_MIN:
            continue

        for j in range(i - 1, -1, -1):
            idx1, p1, r1 = pivots[j]
            sep = idx2 - idx1
            if sep < _MIN_SEP or sep > _MAX_SEP:
                continue
            if r1 <= _BEAR_RSI_MIN:
                continue

            price_higher = p2 > p1 * (1 + _MIN_PRICE_DIFF)
            rsi_lower    = r2 < r1 - _MIN_RSI_DIFF

            if price_higher and rsi_lower:
                rsi_diff = r1 - r2
                if rsi_diff > best_rsi_diff:
                    best_rsi_diff = rsi_diff
                    best = (idx1, p1, r1, idx2, p2, r2)

    return best


# -----------------------------------------------------------------------------
# EMA rapida (para confirmacion)
# -----------------------------------------------------------------------------

def _ema_fast(closes: list[float], n: int = 20) -> Optional[float]:
    if len(closes) < n:
        return None
    k   = 2.0 / (n + 1)
    val = sum(closes[:n]) / n
    for p in closes[n:]:
        val = p * k + val * (1 - k)
    return val


# -----------------------------------------------------------------------------
# Confirmacion de divergencia
# -----------------------------------------------------------------------------

def _bullish_confirmed(
    closes:    list[float],
    opens:     list[float],
    highs:     list[float],
    pivot2_idx: int,
) -> bool:
    """
    Busca confirmacion alcista DESPUES del segundo pivot de precio.
    Basta con cualquiera de estas condiciones:
    1. Vela verde significativa en las 3 barras post-pivot (body > 0.5%)
    2. Cierre por encima del maximo de las 5 barras previas al pivot
    3. Precio por encima de EMA20
    """
    n    = len(closes)
    post = list(range(max(pivot2_idx + 1, 0), n))
    if not post:
        return False

    price = closes[-1]

    # 1. Vela verde reciente
    for k in post[-3:]:
        body_pct = (closes[k] - opens[k]) / opens[k] if opens[k] > 0 else 0
        if body_pct > 0.005:
            return True

    # 2. Precio supera maximo anterior al pivot
    pre_highs = highs[max(0, pivot2_idx - 5): pivot2_idx]
    if pre_highs and price > max(pre_highs) * 1.005:
        return True

    # 3. Precio sobre EMA20
    ema20 = _ema_fast(closes, 20)
    if ema20 and price > ema20:
        return True

    return False


def _bearish_confirmed(
    closes:    list[float],
    opens:     list[float],
    lows:      list[float],
    pivot2_idx: int,
) -> bool:
    """
    Busca confirmacion bajista DESPUES del segundo pivot de precio.
    Basta con cualquiera de estas condiciones:
    1. Vela roja significativa en las 3 barras post-pivot (body > 0.5%)
    2. Cierre por debajo del minimo de las 5 barras previas al pivot
    3. Precio por debajo de EMA20
    """
    n    = len(closes)
    post = list(range(max(pivot2_idx + 1, 0), n))
    if not post:
        return False

    price = closes[-1]

    # 1. Vela roja reciente
    for k in post[-3:]:
        body_pct = (opens[k] - closes[k]) / opens[k] if opens[k] > 0 else 0
        if body_pct > 0.005:
            return True

    # 2. Precio bajo el minimo anterior al pivot
    pre_lows = lows[max(0, pivot2_idx - 5): pivot2_idx]
    if pre_lows and price < min(pre_lows) * 0.995:
        return True

    # 3. Precio bajo EMA20
    ema20 = _ema_fast(closes, 20)
    if ema20 and price < ema20:
        return True

    return False


# -----------------------------------------------------------------------------
# Nivel de confianza
# -----------------------------------------------------------------------------

def _confidence(
    p1:        float,
    p2:        float,
    r1:        float,
    r2:        float,
    div_type:  str,    # 'bullish' o 'bearish'
    confirmed: bool,
) -> str:
    """
    HIGH:   confirmado + rsi_diff >= 5 + price_diff >= 1.5%
    MEDIUM: confirmado O rsi_diff >= 3
    LOW:    en formacion sin suficiente divergencia
    """
    price_diff = abs(p2 / p1 - 1) * 100 if p1 > 0 else 0
    rsi_diff   = abs(r2 - r1)

    if confirmed and rsi_diff >= 5.0 and price_diff >= 1.5:
        return 'HIGH'
    if confirmed or rsi_diff >= 3.0:
        return 'MEDIUM'
    return 'LOW'


# -----------------------------------------------------------------------------
# Decision
# -----------------------------------------------------------------------------

def _make_decision(state: str, confidence: str) -> str:
    if state == 'BULLISH_DIVERGENCE_CONFIRMED':
        return 'BUY_CANDIDATE' if confidence == 'HIGH' else 'WATCHLIST'
    if state == 'BULLISH_DIVERGENCE_FORMING':
        return 'WATCHLIST'
    if state == 'BEARISH_DIVERGENCE_CONFIRMED':
        return 'SELL_WARNING'
    if state == 'BEARISH_DIVERGENCE_FORMING':
        return 'AVOID'
    return 'NONE'


# -----------------------------------------------------------------------------
# Lecturas humanas
# -----------------------------------------------------------------------------

_READINGS = {
    'NO_DIVERGENCE':
        'Sin divergencia activa entre precio y RSI',
    'BULLISH_DIVERGENCE_FORMING':
        'El precio hizo un minimo mas bajo, pero el RSI no acompano la debilidad - divergencia alcista en formacion',
    'BULLISH_DIVERGENCE_CONFIRMED':
        'Perdida de fuerza bajista confirmada - posible rebote en curso',
    'BEARISH_DIVERGENCE_FORMING':
        'El precio sube con impulso decreciente en el RSI - agotamiento posible',
    'BEARISH_DIVERGENCE_CONFIRMED':
        'Divergencia bajista confirmada - riesgo de correccion',
}


# -----------------------------------------------------------------------------
# Motor principal
# -----------------------------------------------------------------------------

def _no_divergence(symbol: str, fecha: date) -> dict:
    return {
        'simbolo':          symbol,
        'fecha':            fecha,
        'divergence_state': 'NO_DIVERGENCE',
        'divergence_type':  None,
        'price_pivot_1':    None,
        'price_pivot_2':    None,
        'rsi_pivot_1':      None,
        'rsi_pivot_2':      None,
        'pivot_1_date':     None,
        'pivot_2_date':     None,
        'pivot_1_idx':      None,
        'pivot_2_idx':      None,
        'confidence_level': None,
        'decision':         'NONE',
        'reading':          _READINGS['NO_DIVERGENCE'],
        '_rsi_series':      None,
        '_dates':           None,
        '_closes':          None,
        '_highs':           None,
        '_lows':            None,
    }


def analyze_symbol(symbol: str, fecha: date) -> Optional[dict]:
    """
    Detecta divergencia precio-RSI para el simbolo en la fecha dada.
    Retorna None si datos insuficientes; dict con resultado en caso contrario.
    """
    rows = _load_ohlcv(symbol, fecha)
    if len(rows) < _RSI_PERIOD + _PIVOT_WIN * 2 + 10:
        return None

    closes = [float(r['close']) for r in rows]
    opens  = [float(r['open'])  for r in rows]
    highs  = [float(r['high'])  for r in rows]
    lows   = [float(r['low'])   for r in rows]
    dates  = [r['fecha']        for r in rows]
    n      = len(closes)

    rsi_vals = _rsi_series(closes, _RSI_PERIOD)

    bull = _best_bullish_pair(lows,  rsi_vals, n)
    bear = _best_bearish_pair(highs, rsi_vals, n)

    # Si no hay ninguna divergencia
    if not bull and not bear:
        return _no_divergence(symbol, fecha)

    # Elegir la mas reciente entre ambas
    bull_idx2 = bull[3] if bull else -1
    bear_idx2 = bear[3] if bear else -1

    if bull and bear:
        chosen = 'bullish' if bull_idx2 >= bear_idx2 else 'bearish'
    elif bull:
        chosen = 'bullish'
    else:
        chosen = 'bearish'

    if chosen == 'bullish':
        idx1, p1, r1, idx2, p2, r2 = bull
        confirmed  = _bullish_confirmed(closes, opens, highs, idx2)
        state      = 'BULLISH_DIVERGENCE_CONFIRMED' if confirmed else 'BULLISH_DIVERGENCE_FORMING'
        div_type   = 'BULLISH'
    else:
        idx1, p1, r1, idx2, p2, r2 = bear
        confirmed  = _bearish_confirmed(closes, opens, lows, idx2)
        state      = 'BEARISH_DIVERGENCE_CONFIRMED' if confirmed else 'BEARISH_DIVERGENCE_FORMING'
        div_type   = 'BEARISH'

    conf  = _confidence(p1, p2, r1, r2, chosen, confirmed)
    dec   = _make_decision(state, conf)
    read  = _READINGS.get(state, state)

    return {
        'simbolo':          symbol,
        'fecha':            fecha,
        'divergence_state': state,
        'divergence_type':  div_type,
        'price_pivot_1':    round(p1, 4),
        'price_pivot_2':    round(p2, 4),
        'rsi_pivot_1':      round(r1, 2),
        'rsi_pivot_2':      round(r2, 2),
        'pivot_1_date':     dates[idx1],
        'pivot_2_date':     dates[idx2],
        'pivot_1_idx':      idx1,
        'pivot_2_idx':      idx2,
        'confidence_level': conf,
        'decision':         dec,
        'reading':          read,
        '_rsi_series':      rsi_vals,
        '_dates':           dates,
        '_closes':          closes,
        '_highs':           highs,
        '_lows':            lows,
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


# -----------------------------------------------------------------------------
# Persistencia
# -----------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS rsi_divergence_signals (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    fecha             DATE         NOT NULL,
    simbolo           VARCHAR(20)  NOT NULL,
    divergence_state  VARCHAR(40),
    divergence_type   VARCHAR(10),
    price_pivot_1     FLOAT,
    price_pivot_2     FLOAT,
    rsi_pivot_1       FLOAT,
    rsi_pivot_2       FLOAT,
    pivot_1_date      DATE,
    pivot_2_date      DATE,
    confidence_level  VARCHAR(10),
    decision          VARCHAR(20),
    reading           VARCHAR(500),
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_rdiv_fecha_sym (fecha, simbolo)
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


def save_signals(results: list[dict]) -> int:
    """Guarda senales en DB. Omite NO_DIVERGENCE para no saturar la tabla."""
    if not results:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            saved = 0
            for r in results:
                if r['divergence_state'] == 'NO_DIVERGENCE':
                    continue
                cur.execute(
                    """INSERT INTO rsi_divergence_signals
                       (fecha, simbolo, divergence_state, divergence_type,
                        price_pivot_1, price_pivot_2, rsi_pivot_1, rsi_pivot_2,
                        pivot_1_date, pivot_2_date, confidence_level, decision, reading)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                         divergence_state = VALUES(divergence_state),
                         divergence_type  = VALUES(divergence_type),
                         price_pivot_1    = VALUES(price_pivot_1),
                         price_pivot_2    = VALUES(price_pivot_2),
                         rsi_pivot_1      = VALUES(rsi_pivot_1),
                         rsi_pivot_2      = VALUES(rsi_pivot_2),
                         pivot_1_date     = VALUES(pivot_1_date),
                         pivot_2_date     = VALUES(pivot_2_date),
                         confidence_level = VALUES(confidence_level),
                         decision         = VALUES(decision),
                         reading          = VALUES(reading)
                    """,
                    (
                        r['fecha'], r['simbolo'],
                        r['divergence_state'], r['divergence_type'],
                        r['price_pivot_1'], r['price_pivot_2'],
                        r['rsi_pivot_1'],   r['rsi_pivot_2'],
                        r['pivot_1_date'],  r['pivot_2_date'],
                        r['confidence_level'], r['decision'], r['reading'],
                    )
                )
                saved += 1
        conn.commit()
        return saved
    finally:
        conn.close()
