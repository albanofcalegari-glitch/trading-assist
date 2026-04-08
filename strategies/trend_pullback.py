"""
trend_pullback.py — motor de estrategia Trend + Pullback

Estados de setup:
    NO_SETUP         — no hay condiciones claras
    TREND_HEALTHY    — tendencia sana, sin retroceso util todavia
    PULLBACK_FORMING — en retroceso, todavia sin señal de freno
    PULLBACK_VALID   — retroceso estabilizado, potencial entrada
    TREND_BROKEN     — estructura de tendencia dañada

Decisiones:
    BUY_CANDIDATE    — entrada táctica válida
    WATCHLIST        — monitorear, aún no operable
    AVOID            — tendencia rota, no operar
    NO_ACTION        — sin setup
"""
from datetime import date
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.utils import ema, sma, rsi, momentum_pct, vol_ratio, vs_peak, higher_low
from config import SECTOR_MAP

# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

_TREND_BROKEN_THRESHOLD  = 3    # trend_score <= este valor → TREND_BROKEN
_PULLBACK_VALID_MIN      = 6    # pullback_score >= este valor → PULLBACK_VALID
_IN_PULLBACK_MOM_MAX     = -1.5 # mom20 < este % para considerar que hay pullback
_IN_PULLBACK_MOM60_MIN   = -15  # mom60 por encima de este % (tendencia no destruida)

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
# Trend score (0–10)
# ─────────────────────────────────────────────────────────────────────────────
# Cinco componentes de 0/1/2 puntos → max = 10
# Se enfoca en la estructura subyacente de largo plazo

def _score_trend(
    price: float,
    ema20_val: Optional[float],
    sma50_val: Optional[float],
    sma200_val: Optional[float],
    mom20_val: Optional[float],
    mom60_val: Optional[float],
    vs_peak_60d: Optional[float],
) -> tuple[float, dict]:

    score = 0
    details = {}

    # 1. Momentum 60d — base de la tendencia
    if mom60_val is None:
        details['mom60'] = 0
    elif mom60_val > 8:
        score += 2; details['mom60'] = 2
    elif mom60_val > 0:
        score += 1; details['mom60'] = 1
    else:
        details['mom60'] = 0

    # 2. Precio vs SMA200 — estructura de largo plazo
    if sma200_val is None:
        details['vs_sma200'] = 0
    elif price > sma200_val * 1.03:   # más del 3% por encima
        score += 2; details['vs_sma200'] = 2
    elif price >= sma200_val:
        score += 1; details['vs_sma200'] = 1
    else:
        details['vs_sma200'] = 0

    # 3. Alineación de medias (SMA50 > SMA200 = golden cross)
    if sma50_val is None or sma200_val is None:
        details['ma_align'] = 0
    elif sma50_val > sma200_val * 1.02:    # golden cross sólido
        score += 2; details['ma_align'] = 2
    elif sma50_val >= sma200_val:
        score += 1; details['ma_align'] = 1
    else:
        details['ma_align'] = 0

    # 4. Distancia desde pico de 60d — ¿qué tan castigado está?
    if vs_peak_60d is None:
        details['vs_peak'] = 0
    elif vs_peak_60d > -10:            # dentro del 10% del máximo reciente
        score += 2; details['vs_peak'] = 2
    elif vs_peak_60d > -20:
        score += 1; details['vs_peak'] = 1
    else:
        details['vs_peak'] = 0

    # 5. Precio vs SMA50 — salud de tendencia de mediano plazo
    if sma50_val is None:
        details['vs_sma50'] = 0
    elif price >= sma50_val:
        score += 2; details['vs_sma50'] = 2
    elif price >= sma50_val * 0.96:    # dentro del 4% por debajo
        score += 1; details['vs_sma50'] = 1
    else:
        details['vs_sma50'] = 0

    return float(min(score, 10)), details


# ─────────────────────────────────────────────────────────────────────────────
# Pullback score (0–10)
# ─────────────────────────────────────────────────────────────────────────────
# Solo es relevante si hay pullback activo (in_pullback=True)

def _score_pullback(
    price: float,
    ema20_val: Optional[float],
    sma50_val: Optional[float],
    rsi_val: Optional[float],
    vol_ratio_val: Optional[float],
    mom20_val: Optional[float],
    closes: list[float],
) -> tuple[float, dict]:

    score = 0
    details = {}

    # 1. Magnitud del retroceso — pullback sano entre -2% y -15%
    if mom20_val is None:
        details['magnitude'] = 0
    elif -15 <= mom20_val <= -1.5:     # zona óptima de pullback
        score += 2; details['magnitude'] = 2
    elif -25 <= mom20_val < -15:       # retroceso fuerte, posible pero riesgoso
        score += 1; details['magnitude'] = 1
    else:
        details['magnitude'] = 0       # no hay retroceso real o colapso

    # 2. Proximidad a soporte dinámico (EMA20 o SMA50) — zona de rebote esperada
    min_dist = None
    if ema20_val and ema20_val > 0:
        min_dist = abs(price / ema20_val - 1) * 100
    if sma50_val and sma50_val > 0:
        d50 = abs(price / sma50_val - 1) * 100
        if min_dist is None or d50 < min_dist:
            min_dist = d50

    if min_dist is None:
        details['proximity'] = 0
    elif min_dist <= 4:                # muy cerca del soporte
        score += 2; details['proximity'] = 2
    elif min_dist <= 9:
        score += 1; details['proximity'] = 1
    else:
        details['proximity'] = 0

    # 3. RSI — enfriado pero no destruido
    if rsi_val is None:
        details['rsi'] = 0
    elif 30 <= rsi_val <= 52:          # zona ideal: frío pero vivo
        score += 2; details['rsi'] = 2
    elif 52 < rsi_val <= 62 or 25 <= rsi_val < 30:
        score += 1; details['rsi'] = 1
    else:
        details['rsi'] = 0             # sobrecomprado o destruido

    # 4. Volumen de la caída — bajo = vendedores sin convicción (bullish)
    if vol_ratio_val is None:
        details['volume'] = 1          # neutral si no hay datos
    elif vol_ratio_val < 0.8:          # corrección con volumen muy bajo
        score += 2; details['volume'] = 2
    elif vol_ratio_val < 1.0:
        score += 1; details['volume'] = 1
    else:
        details['volume'] = 0          # volumen alto en la caída (presión vendedora)

    # 5. Estabilización — ¿dejó de hacer nuevos mínimos?
    hl = higher_low(closes, lookback=5)
    if hl:
        score += 2; details['stabilization'] = 2
    else:
        # check más suave: al menos no en el mínimo absoluto de 5 días
        if len(closes) >= 5:
            min5 = min(closes[-5:])
            if price > min5 * 1.005:   # al menos 0.5% por encima del mínimo de 5d
                score += 1; details['stabilization'] = 1
            else:
                details['stabilization'] = 0
        else:
            details['stabilization'] = 0

    return float(min(score, 10)), details


# ─────────────────────────────────────────────────────────────────────────────
# Context alignment
# ─────────────────────────────────────────────────────────────────────────────

_MARKET_WEIGHT = {
    'TREND_UP':   1.0,
    'RANGE':      0.0,
    'VOLATILE':  -0.5,
    'TREND_DOWN': -1.0,
}

_SECTOR_WEIGHT = {
    'STRONG':   1.0,
    'NEUTRAL':  0.0,
    'WEAK':    -1.0,
}


def context_alignment(symbol: str, fecha: date) -> tuple[str, dict]:
    """
    Calcula alineación de contexto para un símbolo en una fecha.

    Returns:
        ('favorable' | 'neutral' | 'unfavorable', metadata_dict)
    """
    mkt = _get_market_regime(fecha)
    sector = SECTOR_MAP.get(symbol, {}).get('sector')
    sec = _get_sector_regime(sector, fecha) if sector else None

    mkt_regime = mkt['regime'] if mkt else 'RANGE'
    sec_regime = sec['regime'] if sec else 'NEUTRAL'

    mkt_w = _MARKET_WEIGHT.get(mkt_regime, 0.0)
    sec_w = _SECTOR_WEIGHT.get(sec_regime, 0.0)
    total = mkt_w + sec_w

    if total >= 1.0:
        alignment = 'favorable'
    elif total <= -0.5:
        alignment = 'unfavorable'
    else:
        alignment = 'neutral'

    return alignment, {
        'market_regime': mkt_regime,
        'sector_regime': sec_regime,
        'sector':        sector,
        'score':         total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Clasificación de setup
# ─────────────────────────────────────────────────────────────────────────────

def _classify_setup(
    trend_score: float,
    pullback_score: float,
    price: float,
    sma200_val: Optional[float],
    ema20_val: Optional[float],
    mom20_val: Optional[float],
    mom60_val: Optional[float],
) -> str:
    """Determina el estado del setup."""

    # ── TREND_BROKEN: estructura dañada ──────────────────────────────────────
    if trend_score <= _TREND_BROKEN_THRESHOLD:
        return 'TREND_BROKEN'
    if sma200_val and price < sma200_val * 0.97 and mom60_val is not None and mom60_val < -5:
        return 'TREND_BROKEN'

    # ── ¿Hay pullback activo? ─────────────────────────────────────────────────
    in_pullback = (
        mom20_val is not None
        and mom20_val < _IN_PULLBACK_MOM_MAX
        and (mom60_val is None or mom60_val > _IN_PULLBACK_MOM60_MIN)
    )
    # También considerar si el precio cruzó por debajo de EMA20
    if not in_pullback and ema20_val and price < ema20_val and mom20_val is not None and mom20_val < -0.5:
        in_pullback = True

    if in_pullback:
        if pullback_score >= _PULLBACK_VALID_MIN:
            return 'PULLBACK_VALID'
        return 'PULLBACK_FORMING'

    # TREND_HEALTHY requiere tendencia sólida (score >= 6)
    # trend_score 4-5 sin pullback = tendencia moderada, sin setup claro
    if trend_score >= 6:
        return 'TREND_HEALTHY'

    return 'NO_SETUP'


# ─────────────────────────────────────────────────────────────────────────────
# Lectura humana + decisión
# ─────────────────────────────────────────────────────────────────────────────

def _make_reading(state: str, alignment: str, trend_score: float, pullback_score: float) -> str:
    """Lectura en lenguaje natural, graduada por la fortaleza de la tendencia."""

    if state == 'TREND_HEALTHY':
        if trend_score >= 9:
            base = "Activo fuerte — sin zona de entrada todavia, esperar retroceso"
        else:
            base = "Tendencia sana — sin retroceso util todavia"
        if alignment == 'unfavorable':
            return f"{base} (contexto de mercado/sector debil)"
        return base

    if state == 'PULLBACK_VALID':
        if trend_score >= 7:
            base = "Pullback sano dentro de tendencia fuerte"
        elif trend_score >= 5:
            base = "Retroceso valido, pero tendencia de fondo moderada"
        else:
            base = "Retroceso tecnico con tendencia de fondo debil — precaucion"
        if alignment == 'favorable':
            return f"{base} — contexto favorable"
        if alignment == 'unfavorable':
            return f"{base} — contexto desfavorable, esperar confirmacion"
        return base

    if state == 'PULLBACK_FORMING':
        if trend_score >= 7:
            return "Pullback en formacion dentro de tendencia fuerte — esperar estabilizacion"
        if alignment == 'unfavorable':
            return "Correccion activa con contexto negativo — no operar aun"
        return "Correccion en curso — esperar señales de freno antes de entrar"

    if state == 'TREND_BROKEN':
        if alignment == 'unfavorable':
            return "Tendencia dañada con contexto negativo — fuera del radar"
        return "Tendencia dañada — evitar nuevas compras"

    # NO_SETUP
    return "Sin setup claro en este momento"


def _make_confidence(
    state: str,
    trend_score: float,
    pullback_score: float,
    alignment: str,
) -> str:
    if state == 'PULLBACK_VALID':
        # HIGH: tendencia muy fuerte + pullback limpio + contexto a favor
        if trend_score >= 7 and pullback_score >= 7 and alignment == 'favorable':
            return 'HIGH'
        # MEDIUM: tendencia fuerte con pullback decente
        if trend_score >= 7 and pullback_score >= 6:
            return 'MEDIUM'
        # MEDIUM: tendencia moderada pero contexto acompaña
        if trend_score >= 5 and pullback_score >= 6 and alignment == 'favorable':
            return 'MEDIUM'
        # Degradar si contexto es adverso y tendencia no es fuerte
        return 'LOW'

    if state == 'PULLBACK_FORMING':
        if trend_score >= 7 and alignment == 'favorable':
            return 'MEDIUM'
        return 'LOW'

    return 'LOW'


def _make_decision(
    state: str,
    alignment: str,
    confidence: str,
    trend_score: float,
) -> str:
    if state == 'TREND_BROKEN':
        return 'AVOID'
    if state == 'NO_SETUP':
        return 'NO_ACTION'

    if state == 'PULLBACK_VALID':
        # Tendencia fuerte: entrada si contexto no es adverso
        if trend_score >= 7 and alignment != 'unfavorable' and confidence in ('HIGH', 'MEDIUM'):
            return 'BUY_CANDIDATE'
        # Tendencia moderada: solo entrar si contexto es favorable
        if trend_score >= 5 and alignment == 'favorable' and confidence == 'MEDIUM':
            return 'BUY_CANDIDATE'
        # Todo lo demás: vigilar
        return 'WATCHLIST'

    if state in ('PULLBACK_FORMING', 'TREND_HEALTHY'):
        return 'WATCHLIST'

    return 'NO_ACTION'


# ─────────────────────────────────────────────────────────────────────────────
# Análisis por símbolo
# ─────────────────────────────────────────────────────────────────────────────

def _today_gap_pct(rows: list[dict]) -> Optional[float]:
    """Gap de apertura del día = (open_today / close_yesterday - 1) * 100.

    Se usa para etiquetar señales BUY como 'gap-blocked' en el cliente. NO
    filtra hard en el backend: el frontend tiene un selector global con el
    threshold preferido del usuario y aplica la transformación visual.
    """
    if len(rows) < 2:
        return None
    today = rows[-1]
    prev  = rows[-2]
    open_t = today.get('open')
    close_y = prev.get('close')
    if not open_t or not close_y:
        return None
    try:
        return round((float(open_t) / float(close_y) - 1) * 100, 2)
    except (ValueError, ZeroDivisionError):
        return None


def analyze_symbol(symbol: str, fecha: Optional[date] = None) -> Optional[dict]:
    """
    Analiza el setup Trend+Pullback de un símbolo en una fecha dada.

    Returns dict con todos los campos, o None si no hay suficientes datos.
    """
    fecha = fecha or date.today()

    rows = _load_ohlcv(symbol, fecha, n=300)
    if len(rows) < 60:
        return None

    closes  = [float(r['close'])  for r in rows]
    volumes = [float(r['volume']) for r in rows]
    price   = closes[-1]
    gap_pct = _today_gap_pct(rows)

    # Indicadores
    ema20_val  = ema(closes, 20)
    sma50_val  = sma(closes, 50)
    sma200_val = sma(closes, 200)
    rsi_val    = rsi(closes, 14)
    mom20_val  = momentum_pct(closes, 20)
    mom60_val  = momentum_pct(closes, 60)
    vol_r      = vol_ratio(volumes, short=5, long=20)
    peak_60d   = vs_peak(closes, 60)

    # Scores
    trend_sc, trend_det = _score_trend(
        price, ema20_val, sma50_val, sma200_val, mom20_val, mom60_val, peak_60d
    )
    pull_sc, pull_det = _score_pullback(
        price, ema20_val, sma50_val, rsi_val, vol_r, mom20_val, closes
    )

    # Setup state
    state = _classify_setup(
        trend_sc, pull_sc, price, sma200_val, ema20_val, mom20_val, mom60_val
    )

    # Contexto
    alignment, ctx_meta = context_alignment(symbol, fecha)

    # Decisión + lectura
    confidence = _make_confidence(state, trend_sc, pull_sc, alignment)
    decision   = _make_decision(state, alignment, confidence, trend_sc)
    reading    = _make_reading(state, alignment, trend_sc, pull_sc)
    allow      = decision == 'BUY_CANDIDATE'

    return {
        'fecha':             fecha,
        'simbolo':           symbol,
        'trend_score':       trend_sc,
        'pullback_score':    pull_sc,
        'setup_state':       state,
        'context_alignment': alignment,
        'decision':          decision,
        'confidence_level':  confidence,
        'allow_trade':       allow,
        'reading':           reading,
        # snapshot de indicadores
        'price':             round(price, 4),
        'ema20':             round(ema20_val,  4) if ema20_val  else None,
        'sma50':             round(sma50_val,  4) if sma50_val  else None,
        'sma200':            round(sma200_val, 4) if sma200_val else None,
        'rsi14':             rsi_val,
        'mom20':             mom20_val,
        'mom60':             mom60_val,
        'vol_ratio':         vol_r,
        # Gap de apertura del día — el cliente decide si lo usa como filtro
        'gap_pct':           gap_pct,
        # metadata de debug
        '_trend_det':        trend_det,
        '_pull_det':         pull_det,
        '_ctx':              ctx_meta,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Runner de universo
# ─────────────────────────────────────────────────────────────────────────────

def run_universe(
    symbols: list[str],
    fecha: Optional[date] = None,
) -> list[dict]:
    """Analiza todos los símbolos para una fecha. Devuelve lista de resultados."""
    fecha = fecha or date.today()
    results = []
    for sym in symbols:
        r = analyze_symbol(sym, fecha)
        if r:
            results.append(r)
        else:
            print(f"  [SKIP] {sym} — datos insuficientes")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia en DB
# ─────────────────────────────────────────────────────────────────────────────

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trend_pullback_signals (
    id               INT AUTO_INCREMENT,
    fecha            DATE          NOT NULL,
    simbolo          VARCHAR(20)   NOT NULL,
    trend_score      DECIMAL(4,1)  NOT NULL,
    pullback_score   DECIMAL(4,1)  NOT NULL,
    setup_state      VARCHAR(25)   NOT NULL,
    context_alignment VARCHAR(15)  NOT NULL,
    decision         VARCHAR(20)   NOT NULL,
    confidence_level VARCHAR(10)   NOT NULL,
    allow_trade      TINYINT(1)    NOT NULL DEFAULT 0,
    reading          VARCHAR(220)  NOT NULL,
    price            DECIMAL(14,4) DEFAULT NULL,
    ema20            DECIMAL(14,4) DEFAULT NULL,
    sma50            DECIMAL(14,4) DEFAULT NULL,
    sma200           DECIMAL(14,4) DEFAULT NULL,
    rsi14            DECIMAL(6,2)  DEFAULT NULL,
    mom20            DECIMAL(8,4)  DEFAULT NULL,
    mom60            DECIMAL(8,4)  DEFAULT NULL,
    vol_ratio        DECIMAL(6,3)  DEFAULT NULL,
    gap_pct          DECIMAL(6,2)  DEFAULT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                     ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_fecha_sim (fecha, simbolo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# Migración idempotente para agregar gap_pct a tablas existentes.
# MySQL 8 no soporta `IF NOT EXISTS` en ADD COLUMN, así que verificamos
# information_schema antes de ejecutar.
_ADD_GAP_PCT_SQL = """
SELECT COUNT(*) AS n FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name   = 'trend_pullback_signals'
  AND column_name  = 'gap_pct'
"""

_UPSERT_SQL = """
INSERT INTO trend_pullback_signals
    (fecha, simbolo, trend_score, pullback_score, setup_state,
     context_alignment, decision, confidence_level, allow_trade, reading,
     price, ema20, sma50, sma200, rsi14, mom20, mom60, vol_ratio, gap_pct)
VALUES
    (%(fecha)s, %(simbolo)s, %(trend_score)s, %(pullback_score)s, %(setup_state)s,
     %(context_alignment)s, %(decision)s, %(confidence_level)s, %(allow_trade)s, %(reading)s,
     %(price)s, %(ema20)s, %(sma50)s, %(sma200)s, %(rsi14)s, %(mom20)s, %(mom60)s, %(vol_ratio)s,
     %(gap_pct)s)
ON DUPLICATE KEY UPDATE
    trend_score=VALUES(trend_score), pullback_score=VALUES(pullback_score),
    setup_state=VALUES(setup_state), context_alignment=VALUES(context_alignment),
    decision=VALUES(decision), confidence_level=VALUES(confidence_level),
    allow_trade=VALUES(allow_trade), reading=VALUES(reading),
    price=VALUES(price), ema20=VALUES(ema20), sma50=VALUES(sma50), sma200=VALUES(sma200),
    rsi14=VALUES(rsi14), mom20=VALUES(mom20), mom60=VALUES(mom60), vol_ratio=VALUES(vol_ratio),
    gap_pct=VALUES(gap_pct)
"""


def ensure_table() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_ENSURE_TABLE_SQL)
            # Migración idempotente: agregar gap_pct si la tabla ya existía
            cur.execute(_ADD_GAP_PCT_SQL)
            row = cur.fetchone()
            n = row['n'] if isinstance(row, dict) else row[0]
            if n == 0:
                cur.execute(
                    "ALTER TABLE trend_pullback_signals "
                    "ADD COLUMN gap_pct DECIMAL(6,2) DEFAULT NULL AFTER vol_ratio"
                )
    finally:
        conn.close()


def save_signals(results: list[dict]) -> int:
    """Persiste resultados en trend_pullback_signals. Retorna cantidad guardada."""
    clean = [
        {k: v for k, v in r.items() if not k.startswith('_')}
        for r in results
    ]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, clean)
        return len(clean)
    finally:
        conn.close()
