"""
reversal.py — motor de estrategia Reversal

Detecta estructuras de reversión, pisos en formación y rebotes técnicos.
Trabaja con 3 capas de contexto: Mercado -> Sector -> Activo.
La señal del activo NO se analiza aislada.

Estados de patrón:
    NO_PATTERN               — sin señal clara
    OVERSOLD_ONLY            — sobrevendido sin estructura de piso
    FLOOR_FORMING            — posible piso en formación con señales de estabilización
    DOUBLE_BOTTOM_FORMING    — doble piso en formación (neckline aún no rota)
    DOUBLE_BOTTOM_CONFIRMED  — doble piso confirmado (precio superó neckline)
    HIGHER_LOW_UPTREND       — mínimo más alto dentro de tendencia alcista previa
    BEAR_MARKET_FAKE_REVERSAL— rebote técnico en tendencia bajista estructural
    BREAKDOWN_ACTIVE         — ruptura bajista activa con volumen, caída en curso

Decisiones:
    BUY_CANDIDATE — setup de reversión con contexto aceptable
    WATCHLIST     — patrón visible sin confirmación, o contexto degradado
    AVOID         — sin estructura, caída activa, o contexto muy adverso

Degradación por contexto (IMPORTANTE):
    sector WEAK       → degrada decisión 1 paso
    market UNFAVORABLE → degrada decisión 1 paso adicional
    Ejemplo: DOUBLE_BOTTOM_CONFIRMED + sector WEAK → WATCHLIST (no BUY)
"""
from datetime import date
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.utils import ema, sma, rsi, momentum_pct, vol_ratio, vs_peak, higher_low
from config import SECTOR_MAP


# ─────────────────────────────────────────────────────────────────────────────
# Constantes y umbrales
# ─────────────────────────────────────────────────────────────────────────────

# Doble piso — umbrales estructurales (mínimo para considerarlo candidato)
_DB_MIN_SEP     = 8     # separación mínima en barras entre dos mínimos
_DB_MAX_DIFF    = 3.0   # diferencia máx % entre los dos mínimos
_DB_BOUNCE_MIN  = 4.0   # rebote mínimo % absoluto para iniciar evaluación
_DB_RECENCY     = 25    # el segundo mínimo debe estar en los últimos N barras

# Doble piso — criterios de CALIDAD (necesarios para DB_FORMING sólido)
# Si no pasan todos → BASE_TENTATIVE (estructura débil)
_DB_BOUNCE_GOOD = 5.5   # rebote mínimo para calificar como DB_FORMING (vs. 4% mínimo)
_DB_VS_SMA200   = 0.90  # precio debe ser >= SMA200 * este factor (endurecido de 0.88)
_DB_VOLR_MAX    = 1.15  # vol_ratio en segundo mínimo debe ser < este factor

# Presión vendedora — vela roja con cuerpo amplio, cierre débil y volumen elevado
_SP_VOLR_MIN    = 1.20  # vol_ratio mínimo para confirmar presión vendedora
_SP_CLOSE_RANGE = 0.30  # cierre en tercio inferior del rango: (close-low)/(high-low)
_SP_BODY_PCT    = 0.40  # cuerpo >= 40% del rango total (high-low)

# Higher low uptrend
_HL_MOM60_MIN   = 5.0   # mom60 mínimo para que haya tendencia previa positiva
_HL_MOM20_MAX   = -2.0  # mom20 debe ser negativo (corrección activa)
_HL_MOM20_MIN   = -22.0 # mom20 mínimo (sin colapso)

# Bear market fake reversal
_BEAR_MOM60     = -25.0 # mom60 mínimo para BEAR_MARKET_FAKE_REVERSAL
_BEAR_VS_SMA200 = 0.85  # precio debe ser < SMA200 * este factor (>15% debajo)

# Breakdown activo
_BRK_MOM20      = -10.0 # mom20 para BREAKDOWN_ACTIVE
_BRK_VOLR       = 1.10  # vol_ratio mínimo (vendedores activos)
_BRK_PEAK       = -10.0 # vs_peak_20d para confirmar nuevos mínimos

# Floor forming
_FLOOR_RSI_MAX  = 45    # RSI máximo para FLOOR_FORMING
_FLOOR_RSI_MIN  = 25    # RSI mínimo (no destruido)
_FLOOR_MOM60    = -10.0 # mom60 máximo (daño estructural previo)
_FLOOR_MOM20_L  = -20.0 # mom20 mínimo (caída previa, no de hoy)
_FLOOR_MOM20_H  = 5.0   # mom20 máximo (puede estar estabilizando ya)


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


def _get_market_regime(fecha: date) -> Optional[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT regime, mom20, mom60, volatility_20d
                   FROM market_context_daily
                   WHERE fecha <= %s ORDER BY fecha DESC LIMIT 1""",
                (fecha,)
            )
            return cur.fetchone()
    finally:
        conn.close()


def _get_sector_regime(sector: str, fecha: date) -> Optional[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT regime, mom60, rs_vs_spy
                   FROM sector_context_daily
                   WHERE sector=%s AND fecha<=%s ORDER BY fecha DESC LIMIT 1""",
                (sector, fecha)
            )
            return cur.fetchone()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Detección de mínimos locales
# ─────────────────────────────────────────────────────────────────────────────

def _detect_selling_pressure(
    opens:   list[float],
    highs:   list[float],
    lows:    list[float],
    closes:  list[float],
    volumes: list[float],
) -> bool:
    """
    Detecta presión vendedora fuerte en la última vela.
    Todas las condiciones deben cumplirse:
      1. Vela roja: close < open
      2. Cuerpo amplio: (open - close) / (high - low) >= _SP_BODY_PCT (40%)
      3. Cierre cerca del mínimo: (close - low) / (high - low) < _SP_CLOSE_RANGE (30%)
      4. Volumen elevado: vol_ratio(5, 20) >= _SP_VOLR_MIN (1.20)

    Distingue volumen vendedor (vela roja + cierre débil) de volumen comprador.
    """
    if len(closes) < 20:
        return False
    o = opens[-1];  h = highs[-1];  l = lows[-1];  c = closes[-1]
    rng = h - l
    if rng < 1e-9:
        return False
    # 1. Vela roja
    if c >= o:
        return False
    # 2. Cuerpo amplio (no mecha, real selling body)
    body = o - c
    if body / rng < _SP_BODY_PCT:
        return False
    # 3. Cierre en tercio inferior del rango
    close_pos = (c - l) / rng
    if close_pos > _SP_CLOSE_RANGE:
        return False
    # 4. Volumen por encima del promedio
    vr = vol_ratio(volumes, 5, 20)
    if vr is None or vr < _SP_VOLR_MIN:
        return False
    return True


def _find_local_mins(prices: list[float], w: int = 4) -> list[tuple[int, float]]:
    """
    Devuelve lista de (idx, price) donde prices[idx] es mínimo local
    en ventana de 2*w+1 barras. Ordenado por índice ASC.
    """
    result = []
    n = len(prices)
    for i in range(w, n - w):
        if prices[i] == min(prices[i - w:i + w + 1]):
            result.append((i, prices[i]))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Detección de patrón: Doble Piso
# ─────────────────────────────────────────────────────────────────────────────

def _detect_double_bottom(
    closes:           list[float],
    vol_r:            Optional[float],
    sma200_val:       Optional[float],
    selling_pressure: bool = False,
    lookback:         int  = 80,
) -> tuple[Optional[str], dict]:
    """
    Busca patrón de doble piso con filtro de calidad de dos niveles:

    Nivel 1 — estructura mínima:
      - dos mínimos con diferencia <= _DB_MAX_DIFF % (3%)
      - separación >= _DB_MIN_SEP barras (8)
      - rebote intermedio >= _DB_BOUNCE_MIN % (4%)
      - segundo mínimo dentro de los últimos _DB_RECENCY barras

    Nivel 2 — calidad (los tres deben pasar para DB_FORMING sólido):
      a. bounce >= _DB_BOUNCE_GOOD (5.5%) — rebote claro, no ruido
      b. precio >= sma200 * _DB_VS_SMA200 (0.88) — no en bear profundo
      c. vol_r < _DB_VOLR_MAX (1.15) — vendedores cediendo en segundo mínimo

    Si pasan Nivel 1 pero falla alguno de Nivel 2 → BASE_TENTATIVE
    CONFIRMED si precio actual > neckline * 1.005, FORMING en caso contrario.
    """
    prices = closes[-lookback:] if len(closes) >= lookback else closes
    n = len(prices)
    if n < 20:
        return None, {}

    local_mins    = _find_local_mins(prices, w=4)
    current_idx   = n - 1
    current_price = prices[-1]

    # Candidatos = mínimos confirmados + precio actual como potencial segundo mínimo
    candidates = list(local_mins) + [(current_idx, current_price)]

    # Probar pares de más reciente a más antiguo
    for j in range(len(candidates) - 1, 0, -1):
        idx2, p2 = candidates[j]

        # El segundo mínimo debe ser reciente
        if idx2 < n - _DB_RECENCY and idx2 != current_idx:
            continue

        for i in range(j - 1, -1, -1):
            idx1, p1 = candidates[i]

            if idx2 - idx1 < _DB_MIN_SEP:
                continue

            # Similaridad de precios
            diff_pct = abs(p2 - p1) / min(p1, p2) * 100
            if diff_pct > _DB_MAX_DIFF:
                continue

            # Rebote intermedio (neckline) — umbral mínimo absoluto
            between  = prices[idx1:idx2 + 1]
            neckline = max(between)
            lower    = min(p1, p2)
            bounce   = (neckline / lower - 1) * 100
            if bounce < _DB_BOUNCE_MIN:
                continue

            # ── Estructura mínima encontrada. Ahora evaluar calidad ──────────
            quality_issues = []
            if bounce < _DB_BOUNCE_GOOD:
                quality_issues.append('rebote_debil')
            if sma200_val is not None and current_price < sma200_val * _DB_VS_SMA200:
                quality_issues.append('debajo_sma200')
            if vol_r is not None and vol_r >= _DB_VOLR_MAX:
                quality_issues.append('vol_alto')
            if selling_pressure:
                quality_issues.append('presion_vendedora')

            details = {
                'min1':         round(p1, 2),
                'min2':         round(p2, 2),
                'diff_pct':     round(diff_pct, 2),
                'neckline':     round(neckline, 2),
                'bounce_pct':   round(bounce, 2),
                'separation':   idx2 - idx1,
                'quality_note': quality_issues[0] if quality_issues else '',
            }

            if quality_issues:
                # Estructura existe pero calidad insuficiente → BASE_TENTATIVE
                return 'BASE_TENTATIVE', details

            # Calidad OK → DB_FORMING o CONFIRMED
            state = (
                'DOUBLE_BOTTOM_CONFIRMED'
                if current_price > neckline * 1.005
                else 'DOUBLE_BOTTOM_FORMING'
            )
            return state, details

    return None, {}


# ─────────────────────────────────────────────────────────────────────────────
# Detección de patrón: Higher Low Uptrend
# ─────────────────────────────────────────────────────────────────────────────

def _detect_higher_low_uptrend(
    closes: list[float],
    lows:   list[float],
    mom20:  Optional[float],
    mom60:  Optional[float],
    sma50_val:  Optional[float],
    ema20_val:  Optional[float],
) -> tuple[bool, dict]:
    """
    Detecta corrección dentro de tendencia alcista previa (Higher Low).
    Esto NO es un doble piso — es un retroceso saludable.
    Condiciones:
      - mom60 >= _HL_MOM60_MIN: tendencia previa positiva
      - mom20 en (_HL_MOM20_MIN, _HL_MOM20_MAX): corrección activa pero sin colapso
      - mínimo reciente (last 10d) > mínimo previo (10-40d atrás): higher low confirmado
      - precio cerca de soporte dinámico (EMA20 o SMA50)
    """
    if mom60 is None or mom60 < _HL_MOM60_MIN:
        return False, {}
    if mom20 is None or mom20 > _HL_MOM20_MAX or mom20 < _HL_MOM20_MIN:
        return False, {}
    if len(lows) < 40:
        return False, {}

    recent_low = min(lows[-10:])
    prior_low  = min(lows[-40:-10])

    if recent_low <= prior_low:
        return False, {}

    # Precio cerca de soporte dinámico (razonable, no ya rebotado)
    price = closes[-1]
    near_support = (
        (ema20_val and abs(price / ema20_val - 1) < 0.12) or
        (sma50_val and abs(price / sma50_val - 1) < 0.14)
    )
    if not near_support:
        return False, {}

    return True, {
        'recent_low':     round(recent_low, 2),
        'prior_low':      round(prior_low, 2),
        'higher_by_pct':  round((recent_low / prior_low - 1) * 100, 2),
        'mom60':          round(mom60, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher de patrones
# ─────────────────────────────────────────────────────────────────────────────

def _detect_pattern(
    closes:    list[float],
    lows:      list[float],
    volumes:   list[float],
    mom20:     Optional[float],
    mom60:     Optional[float],
    rsi_val:   Optional[float],
    vol_r:     Optional[float],
    sma50_val:  Optional[float],
    ema20_val:  Optional[float],
    sma200_val: Optional[float],
    selling_pressure: bool = False,
) -> tuple[str, dict]:
    """
    Clasifica el patrón actual en orden de prioridad descendente.
    Orden: BREAKDOWN > BEAR_FAKE > HIGHER_LOW > DOUBLE_BOTTOM > FLOOR > OVERSOLD > NO_PATTERN
    """
    price = closes[-1]

    # ── 1. BREAKDOWN_ACTIVE — caída activa con volumen ────────────────────────
    vs_peak_20 = vs_peak(closes, 20)
    if (
        mom20 is not None     and mom20 < _BRK_MOM20 and
        vol_r is not None     and vol_r >= _BRK_VOLR  and
        vs_peak_20 is not None and vs_peak_20 < _BRK_PEAK
    ):
        return 'BREAKDOWN_ACTIVE', {
            'mom20': round(mom20, 1),
            'vol_ratio': round(vol_r, 2),
            'vs_peak_20d': round(vs_peak_20, 1),
        }

    # ── 2. BEAR_MARKET_FAKE_REVERSAL — daño estructural sin piso real ─────────
    # mom60 muy negativo + precio lejos de SMA200: el rebote no va a mantenerse
    if (
        mom60 is not None      and mom60 < _BEAR_MOM60 and
        sma200_val is not None and price < sma200_val * _BEAR_VS_SMA200 and
        rsi_val is not None    and rsi_val < 45
    ):
        vs200 = round((price / sma200_val - 1) * 100, 1) if sma200_val else None
        return 'BEAR_MARKET_FAKE_REVERSAL', {
            'mom60': round(mom60, 1),
            'vs_sma200_pct': vs200,
        }

    # ── 3. HIGHER_LOW_UPTREND — corrección dentro de tendencia alcista ────────
    hl_ok, hl_det = _detect_higher_low_uptrend(
        closes, lows, mom20, mom60, sma50_val, ema20_val
    )
    if hl_ok:
        return 'HIGHER_LOW_UPTREND', hl_det

    # ── 4. DOUBLE_BOTTOM (CONFIRMED, FORMING, o BASE_TENTATIVE) ──────────────
    db_state, db_det = _detect_double_bottom(closes, vol_r, sma200_val,
                                             selling_pressure=selling_pressure)
    if db_state:
        return db_state, db_det

    # ── 5. FLOOR_FORMING — estabilización sin estructura clara ────────────────
    # RSI frío + daño estructural previo (mom60 negativo) + vol comprimiéndose
    # mom20 puede ser moderadamente negativo o casi flat (post-estabilización)
    if (
        rsi_val is not None and _FLOOR_RSI_MIN <= rsi_val <= _FLOOR_RSI_MAX and
        mom60 is not None   and mom60 < _FLOOR_MOM60 and
        mom20 is not None   and _FLOOR_MOM20_L <= mom20 <= _FLOOR_MOM20_H and
        vol_r is not None   and vol_r < 1.0 and
        len(closes) >= 10
    ):
        # Verificar que no está haciendo nuevos mínimos recientes
        recent_low = min(closes[-5:])
        prior_low  = min(closes[-10:-5])
        if recent_low >= prior_low * 0.99:   # sin nuevos mínimos relevantes
            return 'FLOOR_FORMING', {
                'rsi': round(rsi_val, 1),
                'mom20': round(mom20, 1),
                'vol_ratio': round(vol_r, 2),
            }

    # ── 6. OVERSOLD_ONLY — sobrevendido sin estructura ────────────────────────
    if rsi_val is not None and rsi_val < 35:
        return 'OVERSOLD_ONLY', {
            'rsi': round(rsi_val, 1),
            'mom20': round(mom20, 1) if mom20 else None,
        }

    # ── 7. NO_PATTERN ─────────────────────────────────────────────────────────
    return 'NO_PATTERN', {}


# ─────────────────────────────────────────────────────────────────────────────
# Reversal score (0–10)
# ─────────────────────────────────────────────────────────────────────────────

def _score_reversal(
    rsi_val: Optional[float],
    vol_r:   Optional[float],
    mom20:   Optional[float],
    mom60:   Optional[float],
    pattern: str,
    closes:  list[float],
) -> tuple[float, dict]:
    """
    Cinco componentes × 2 pts → máximo 10.
    Mide la calidad técnica del setup, independiente del contexto.
    El contexto degrada la DECISIÓN, no el score.
    """
    score = 0.0
    det   = {}

    # 1. Zona RSI — oscilador sobrevendido como condición base
    if rsi_val is not None:
        if rsi_val < 28:
            score += 2.0; det['rsi'] = 2.0
        elif rsi_val < 35:
            score += 1.5; det['rsi'] = 1.5
        elif rsi_val < 42:
            score += 1.0; det['rsi'] = 1.0
        elif rsi_val < 48:
            score += 0.5; det['rsi'] = 0.5
        else:
            det['rsi'] = 0.0
    else:
        det['rsi'] = 0.0

    # 2. Firma de volumen — compresión = vendedores perdiendo fuerza
    if vol_r is not None:
        if vol_r < 0.70:
            score += 2.0; det['volume'] = 2.0
        elif vol_r < 0.85:
            score += 1.5; det['volume'] = 1.5
        elif vol_r < 1.00:
            score += 1.0; det['volume'] = 1.0
        else:
            det['volume'] = 0.0
    else:
        det['volume'] = 0.0

    # 3. Estructura de momentum — zona óptima de caída para reversal
    if mom20 is not None:
        if -20.0 <= mom20 <= -6.0:
            score += 2.0; det['momentum'] = 2.0   # caída sana, típica de pullback/reversal
        elif (-30.0 < mom20 < -20.0) or (-6.0 < mom20 <= -2.0):
            score += 1.0; det['momentum'] = 1.0
        else:
            det['momentum'] = 0.0                  # muy leve o colapso extremo
    else:
        det['momentum'] = 0.0

    # 4. Calidad del patrón detectado
    _PAT_PTS = {
        'DOUBLE_BOTTOM_CONFIRMED':   2.0,
        'HIGHER_LOW_UPTREND':        1.5,
        'DOUBLE_BOTTOM_FORMING':     1.0,
        'BASE_TENTATIVE':            0.5,
        'FLOOR_FORMING':             0.5,
        'OVERSOLD_ONLY':             0.0,
        'BEAR_MARKET_FAKE_REVERSAL': 0.0,
        'BREAKDOWN_ACTIVE':          0.0,
        'NO_PATTERN':                0.0,
    }
    pts = _PAT_PTS.get(pattern, 0.0)
    score += pts; det['pattern'] = pts

    # 5. Estabilización reciente — ¿dejó de hacer mínimos?
    if higher_low(closes, lookback=5):
        score += 2.0; det['stabilization'] = 2.0
    elif higher_low(closes, lookback=10):
        score += 1.0; det['stabilization'] = 1.0
    else:
        det['stabilization'] = 0.0

    return round(min(score, 10.0), 1), det


# ─────────────────────────────────────────────────────────────────────────────
# Contexto: mercado + sector (3 capas)
# ─────────────────────────────────────────────────────────────────────────────

def _context_alignment(
    mkt_row: Optional[dict],
    sec_row: Optional[dict],
) -> tuple[str, str, str]:
    """
    Devuelve (market_alignment, sector_alignment, overall_context).

    Para Reversal, el contexto tiene semántica específica:
      - market TREND_UP = favorable (el mercado empuja la recuperación)
      - market RANGE    = neutral
      - market TREND_DOWN / VOLATILE = unfavorable (viento en contra)
      - sector STRONG   = +1 (rebotes en sectores fuertes son más confiables)
      - sector NEUTRAL  = 0
      - sector WEAK     = -2 (degrada fuerte — rebotes en sectores rotos son trampas)

    overall:
      - >= +1 pts: favorable
      - <= -1 pts: unfavorable
      - 0: neutral
    """
    mkt_regime = (mkt_row or {}).get('regime', '')
    if mkt_regime == 'TREND_UP':
        market_align = 'favorable'
    elif mkt_regime in ('TREND_DOWN', 'VOLATILE'):
        market_align = 'unfavorable'
    else:
        market_align = 'neutral'

    sec_regime = (sec_row or {}).get('regime', '')
    if sec_regime == 'STRONG':
        sector_align = 'strong'
    elif sec_regime == 'WEAK':
        sector_align = 'weak'
    else:
        sector_align = 'neutral'

    mkt_pts = {'favorable': 1, 'neutral': 0, 'unfavorable': -1}[market_align]
    sec_pts = {'strong': 1, 'neutral': 0, 'weak': -2}[sector_align]
    total   = mkt_pts + sec_pts

    if total >= 1:
        overall = 'favorable'
    elif total <= -1:
        overall = 'unfavorable'
    else:
        overall = 'neutral'

    return market_align, sector_align, overall


# ─────────────────────────────────────────────────────────────────────────────
# Decisión y degradación por contexto
# ─────────────────────────────────────────────────────────────────────────────

_PATTERN_DECISION = {
    'DOUBLE_BOTTOM_CONFIRMED':   'BUY_CANDIDATE',
    'HIGHER_LOW_UPTREND':        'WATCHLIST',
    'DOUBLE_BOTTOM_FORMING':     'WATCHLIST',
    'BASE_TENTATIVE':            'WATCHLIST',    # estructura débil: vigila pero sin convicción
    'FLOOR_FORMING':             'WATCHLIST',
    'OVERSOLD_ONLY':             'AVOID',
    'BEAR_MARKET_FAKE_REVERSAL': 'AVOID',
    'BREAKDOWN_ACTIVE':          'AVOID',
    'NO_PATTERN':                'AVOID',
}

_DECISION_ORDER = ['BUY_CANDIDATE', 'WATCHLIST', 'AVOID']


def _apply_context_degradation(
    raw_decision: str,
    market_align: str,
    sector_align: str,
) -> str:
    """
    Degrada la decisión base según el contexto.
    sector WEAK       → -1 paso  (un rebote en sector roto es una trampa)
    market UNFAVORABLE → -1 paso adicional
    Las dos pueden acumularse: BUY_CANDIDATE + sector_WEAK + market_UNFAVORABLE → AVOID
    """
    if raw_decision == 'AVOID':
        return 'AVOID'
    idx   = _DECISION_ORDER.index(raw_decision)
    steps = 0
    if sector_align == 'weak':
        steps += 1
    if market_align == 'unfavorable':
        steps += 1
    return _DECISION_ORDER[min(idx + steps, len(_DECISION_ORDER) - 1)]


def _make_confidence(
    score:    float,
    pattern:  str,
    overall:  str,
    decision: str,
) -> str:
    if decision == 'AVOID':
        return 'LOW'
    # BASE_TENTATIVE siempre LOW: la estructura no está validada
    if pattern == 'BASE_TENTATIVE':
        return 'LOW'
    if (
        pattern == 'DOUBLE_BOTTOM_CONFIRMED' and
        score   >= 7.0 and
        overall in ('favorable', 'neutral')
    ):
        return 'HIGH'
    if score >= 5.5 and overall != 'unfavorable':
        return 'MEDIUM'
    return 'LOW'


# ─────────────────────────────────────────────────────────────────────────────
# Lectura humana
# ─────────────────────────────────────────────────────────────────────────────

_BASE_READING = {
    'DOUBLE_BOTTOM_CONFIRMED':   'Doble piso confirmado - precio supero neckline',
    'DOUBLE_BOTTOM_FORMING':     'Posible doble piso en formacion - aguardar ruptura de neckline',
    'BASE_TENTATIVE':            'Base tentativa - estructura insuficiente para reversion',
    'HIGHER_LOW_UPTREND':        'Minimo mas alto en tendencia alcista - correccion saludable',
    'FLOOR_FORMING':             'Posible piso formando - estabilizacion sin confirmacion',
    'OVERSOLD_ONLY':             'Sobrevendido sin estructura de piso - no anticipar rebote',
    'BEAR_MARKET_FAKE_REVERSAL': 'Intento de rebote en tendencia bajista - trampa probable',
    'BREAKDOWN_ACTIVE':          'Caida activa con volumen vendedor - evitar posicion',
    'NO_PATTERN':                'Sin estructura de reversion identificable',
}

# Causas específicas de BASE_TENTATIVE para enriquecer el reading
_TENTATIVE_CAUSE = {
    'rebote_debil':      'rebote intermedio insuficiente',
    'debajo_sma200':     'precio lejos de SMA200',
    'vol_alto':          'vendedores activos en el segundo minimo',
    'presion_vendedora': 'presion vendedora activa en cierre',
}


def _make_reading(
    pattern:          str,
    decision:         str,
    market_align:     str,
    sector_align:     str,
    overall:          str,
    mom60:            Optional[float],
    rsi_val:          Optional[float],
    pattern_det:      Optional[dict] = None,
    selling_pressure: bool           = False,
) -> str:
    base = _BASE_READING.get(pattern, 'Sin senal')

    # Para BASE_TENTATIVE: reemplazar la causa genérica por la específica
    if pattern == 'BASE_TENTATIVE' and pattern_det:
        cause = pattern_det.get('quality_note', '')
        cause_txt = _TENTATIVE_CAUSE.get(cause, '')
        if cause_txt:
            base = f'Base tentativa - {cause_txt}'

    # Selling pressure tiene prioridad — anula contexto positivo
    if selling_pressure:
        if pattern in ('DOUBLE_BOTTOM_CONFIRMED', 'DOUBLE_BOTTOM_FORMING'):
            base += ' - presion vendedora activa, evitar anticiparse'
        elif pattern in ('BASE_TENTATIVE',):
            base += ' - presion vendedora confirma debilidad'
        elif pattern in ('OVERSOLD_ONLY', 'NO_PATTERN'):
            base = 'Sobrevendido con presion vendedora fuerte - no anticipar rebote'
        elif pattern == 'HIGHER_LOW_UPTREND':
            base += ' - atencion: presion vendedora activa en cierre'
        return base

    # Contexto sectorial: impacta la conviccion
    if sector_align == 'weak':
        if pattern in ('DOUBLE_BOTTOM_FORMING', 'DOUBLE_BOTTOM_CONFIRMED'):
            base += ' - sector debil, rebote de baja conviccion'
        elif pattern == 'FLOOR_FORMING':
            base += ' - sector en contra, evitar anticiparse'
        elif pattern == 'OVERSOLD_ONLY':
            base += ' - sector en contra, sin argumento de entrada'
        elif pattern not in ('BREAKDOWN_ACTIVE', 'BEAR_MARKET_FAKE_REVERSAL', 'NO_PATTERN'):
            base += ' - sector debil degrada la senal'
        else:
            base += ' con sector debil'
    elif sector_align == 'strong':
        if pattern in ('DOUBLE_BOTTOM_CONFIRMED', 'DOUBLE_BOTTOM_FORMING', 'FLOOR_FORMING'):
            base += ' - sector fuerte a favor'
        elif pattern == 'HIGHER_LOW_UPTREND':
            base += ' - sector acompana el rebote'
    elif market_align == 'unfavorable':
        if pattern not in ('BREAKDOWN_ACTIVE', 'BEAR_MARKET_FAKE_REVERSAL'):
            base += ' - contexto de mercado desfavorable'
    elif overall == 'favorable':
        if pattern in ('DOUBLE_BOTTOM_CONFIRMED', 'DOUBLE_BOTTOM_FORMING', 'FLOOR_FORMING'):
            base += ' con contexto favorable'

    return base


# ─────────────────────────────────────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────────────────────────────────────

def analyze_symbol(symbol: str, fecha: date) -> Optional[dict]:
    """
    Analiza un símbolo en la fecha dada y devuelve el dict de señal Reversal.
    Retorna None si hay datos insuficientes.
    """
    rows = _load_ohlcv(symbol, fecha)
    if len(rows) < 30:
        return None

    opens   = [float(r['open'])   for r in rows]
    closes  = [float(r['close'])  for r in rows]
    highs   = [float(r['high'])   for r in rows]
    lows    = [float(r['low'])    for r in rows]
    volumes = [float(r['volume']) for r in rows]
    price   = closes[-1]

    # ── Indicadores técnicos ──────────────────────────────────────────────────
    ema20_val  = ema(closes, 20)
    sma50_val  = sma(closes, 50)
    sma200_val = sma(closes, 200)
    rsi_val    = rsi(closes, 14)
    mom20_val  = momentum_pct(closes, 20)
    mom60_val  = momentum_pct(closes, 60)
    vol_r      = vol_ratio(volumes, 5, 20)
    vs_pk_60   = vs_peak(closes, 60)

    # ── Presión vendedora ─────────────────────────────────────────────────────
    sell_p = _detect_selling_pressure(opens, highs, lows, closes, volumes)

    # ── Detección de patrón ───────────────────────────────────────────────────
    pattern, pattern_det = _detect_pattern(
        closes, lows, volumes,
        mom20_val, mom60_val, rsi_val, vol_r,
        sma50_val, ema20_val, sma200_val,
        selling_pressure=sell_p,
    )

    # ── Score de reversión ────────────────────────────────────────────────────
    score, score_det = _score_reversal(
        rsi_val, vol_r, mom20_val, mom60_val, pattern, closes
    )

    # ── Contexto (3 capas) ────────────────────────────────────────────────────
    mkt_row = _get_market_regime(fecha)
    sector  = SECTOR_MAP.get(symbol, {}).get('sector', '')
    sec_row = _get_sector_regime(sector, fecha) if sector else None

    market_align, sector_align, overall = _context_alignment(mkt_row, sec_row)

    # ── Decisión con degradación contextual ───────────────────────────────────
    raw_decision = _PATTERN_DECISION.get(pattern, 'AVOID')
    decision     = _apply_context_degradation(raw_decision, market_align, sector_align)

    # ── Confianza y permiso de trading ────────────────────────────────────────
    confidence  = _make_confidence(score, pattern, overall, decision)
    allow_trade = (decision == 'BUY_CANDIDATE') and (confidence in ('HIGH', 'MEDIUM'))

    # ── Lectura humana ────────────────────────────────────────────────────────
    reading = _make_reading(
        pattern, decision, market_align, sector_align, overall,
        mom60_val, rsi_val, pattern_det,
        selling_pressure=sell_p,
    )

    sector_regime_str = (sec_row or {}).get('regime', 'NEUTRAL')
    sector_mom60_val  = (sec_row or {}).get('mom60')

    ctx = {
        'market_regime': (mkt_row or {}).get('regime'),
        'sector_regime': sector_regime_str,
        'sector':        sector,
    }

    return {
        'simbolo':          symbol,
        'fecha':            fecha,
        'reversal_score':   score,
        'pattern_state':    pattern,
        'market_alignment': market_align,
        'sector_alignment': sector_align,
        'overall_context':  overall,
        'decision':         decision,
        'confidence_level': confidence,
        'allow_trade':      allow_trade,
        'reading':          reading,
        'price':            price,
        'rsi14':            rsi_val,
        'mom20':            mom20_val,
        'mom60':            mom60_val,
        'vol_ratio':        vol_r,
        'ema20':            ema20_val,
        'sma50':            sma50_val,
        'sma200':           sma200_val,
        'vs_peak_60':       vs_pk_60,
        # Sector explícito
        'sector':           sector,
        'sector_regime':    sector_regime_str,
        'sector_mom60':     float(sector_mom60_val) if sector_mom60_val is not None else None,
        # Presión vendedora
        'selling_pressure': sell_p,
        '_pattern_det':     pattern_det,
        '_score_det':       score_det,
        '_ctx':             ctx,
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
# Persistencia
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS reversal_signals (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    fecha            DATE          NOT NULL,
    simbolo          VARCHAR(20)   NOT NULL,
    sector           VARCHAR(80)   DEFAULT NULL,
    reversal_score   FLOAT,
    pattern_state    VARCHAR(40),
    market_alignment VARCHAR(20),
    sector_alignment VARCHAR(20),
    sector_regime    VARCHAR(20)   DEFAULT NULL,
    sector_mom60     FLOAT         DEFAULT NULL,
    overall_context  VARCHAR(20),
    decision         VARCHAR(20),
    confidence_level VARCHAR(10),
    allow_trade      TINYINT(1),
    selling_pressure TINYINT(1)    DEFAULT 0,
    reading          VARCHAR(500),
    price            FLOAT,
    rsi14            FLOAT,
    mom20            FLOAT,
    mom60            FLOAT,
    vol_ratio        FLOAT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_reversal_fecha_sym (fecha, simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

# Migraciones para tablas existentes
_MIGRATIONS = [
    "ALTER TABLE reversal_signals ADD COLUMN sector VARCHAR(80) DEFAULT NULL AFTER simbolo",
    "ALTER TABLE reversal_signals ADD COLUMN sector_regime VARCHAR(20) DEFAULT NULL AFTER sector_alignment",
    "ALTER TABLE reversal_signals ADD COLUMN sector_mom60 FLOAT DEFAULT NULL AFTER sector_regime",
    "ALTER TABLE reversal_signals ADD COLUMN selling_pressure TINYINT(1) DEFAULT 0 AFTER allow_trade",
]


def ensure_table() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_CREATE_TABLE)
            for migration in _MIGRATIONS:
                try:
                    cur.execute(migration)
                except Exception:
                    pass  # columna ya existe
        conn.commit()
    finally:
        conn.close()


def save_signals(results: list[dict]) -> int:
    if not results:
        return 0
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for r in results:
                cur.execute(
                    """INSERT INTO reversal_signals
                       (fecha, simbolo, sector, reversal_score, pattern_state,
                        market_alignment, sector_alignment, sector_regime, sector_mom60,
                        overall_context, decision, confidence_level, allow_trade,
                        selling_pressure, reading, price, rsi14, mom20, mom60, vol_ratio)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                         sector           = VALUES(sector),
                         reversal_score   = VALUES(reversal_score),
                         pattern_state    = VALUES(pattern_state),
                         market_alignment = VALUES(market_alignment),
                         sector_alignment = VALUES(sector_alignment),
                         sector_regime    = VALUES(sector_regime),
                         sector_mom60     = VALUES(sector_mom60),
                         overall_context  = VALUES(overall_context),
                         decision         = VALUES(decision),
                         confidence_level = VALUES(confidence_level),
                         allow_trade      = VALUES(allow_trade),
                         selling_pressure = VALUES(selling_pressure),
                         reading          = VALUES(reading),
                         price            = VALUES(price),
                         rsi14            = VALUES(rsi14),
                         mom20            = VALUES(mom20),
                         mom60            = VALUES(mom60),
                         vol_ratio        = VALUES(vol_ratio)
                    """,
                    (
                        r['fecha'], r['simbolo'], r.get('sector'),
                        r['reversal_score'], r['pattern_state'],
                        r['market_alignment'], r['sector_alignment'],
                        r.get('sector_regime'), r.get('sector_mom60'),
                        r['overall_context'],
                        r['decision'], r['confidence_level'],
                        int(r['allow_trade']),
                        int(r.get('selling_pressure', False)),
                        r['reading'],
                        r['price'], r['rsi14'], r['mom20'],
                        r['mom60'], r['vol_ratio'],
                    )
                )
        conn.commit()
        return len(results)
    finally:
        conn.close()
