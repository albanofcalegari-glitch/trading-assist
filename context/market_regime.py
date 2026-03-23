"""
market_regime — clasificación del régimen de mercado diario
Fuente: SPY (o el benchmark configurado)

Regímenes:
    TREND_UP    — precio > SMA50 > SMA200, momentum positivo
    TREND_DOWN  — precio < SMA50 < SMA200, momentum negativo
    VOLATILE    — volatilidad anualizada > umbral (independiente de dirección)
    RANGE       — nada de lo anterior
"""
import math
import statistics
from datetime import date, timedelta
from typing import Optional
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn

# ── Parámetros ────────────────────────────────────────────────────────────────
SMA_SHORT        = 50
SMA_LONG         = 200
MOM_SHORT_DAYS   = 20
MOM_LONG_DAYS    = 60
VOL_DAYS         = 20
VOL_THRESHOLD    = 25.0    # % anualizado — encima de esto = VOLATILE
TREND_MOM_MIN    = 3.0     # % mínimo de momentum para confirmar tendencia


# ─────────────────────────────────────────────────────────────────────────────
# Cálculos
# ─────────────────────────────────────────────────────────────────────────────

def _sma(prices: list[float], n: int) -> Optional[float]:
    if len(prices) < n:
        return None
    return statistics.mean(prices[-n:])


def _ema(prices: list[float], n: int) -> Optional[float]:
    """EMA con factor de suavizado estándar k=2/(n+1)."""
    if len(prices) < n:
        return None
    k = 2.0 / (n + 1)
    ema = statistics.mean(prices[:n])
    for p in prices[n:]:
        ema = p * k + ema * (1 - k)
    return ema


def _momentum_pct(prices: list[float], lookback: int) -> Optional[float]:
    """Retorno porcentual hace `lookback` días vs hoy."""
    if len(prices) <= lookback:
        return None
    return (prices[-1] / prices[-1 - lookback] - 1) * 100


def _volatility_annualized(prices: list[float], n: int = VOL_DAYS) -> Optional[float]:
    """Volatilidad anualizada (std de log-retornos diarios × sqrt(252))."""
    if len(prices) < n + 1:
        return None
    log_rets = [
        math.log(prices[i] / prices[i - 1])
        for i in range(len(prices) - n, len(prices))
    ]
    return statistics.stdev(log_rets) * math.sqrt(252) * 100


def classify_regime(
    closes: list[float],
    vol_threshold: float = VOL_THRESHOLD,
    trend_mom_min: float = TREND_MOM_MIN,
) -> dict:
    """
    Clasifica el régimen de mercado dado un array de cierres (orden ASC).

    Returns dict con:
        regime, sma50, sma200, mom20, mom60, volatility_20d
    """
    price   = closes[-1] if closes else None
    sma50   = _sma(closes, SMA_SHORT)
    sma200  = _sma(closes, SMA_LONG)
    mom20   = _momentum_pct(closes, MOM_SHORT_DAYS)
    mom60   = _momentum_pct(closes, MOM_LONG_DAYS)
    vol20   = _volatility_annualized(closes, VOL_DAYS)

    # ── Clasificación ─────────────────────────────────────────────────────────
    regime = 'RANGE'   # default

    if vol20 is not None and vol20 > vol_threshold:
        regime = 'VOLATILE'
    elif (
        sma50 is not None and sma200 is not None and price is not None
        and price > sma50 > sma200
        and mom60 is not None and mom60 > trend_mom_min
    ):
        regime = 'TREND_UP'
    elif (
        sma50 is not None and sma200 is not None and price is not None
        and price < sma50 < sma200
        and mom60 is not None and mom60 < -trend_mom_min
    ):
        regime = 'TREND_DOWN'

    return {
        'regime':         regime,
        'sma50':          round(sma50,  4) if sma50  else None,
        'sma200':         round(sma200, 4) if sma200 else None,
        'mom20':          round(mom20,  4) if mom20  else None,
        'mom60':          round(mom60,  4) if mom60  else None,
        'volatility_20d': round(vol20,  4) if vol20  else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_all_closes(symbol: str, table: str = 'market_index') -> list[tuple[date, float]]:
    """Devuelve [(fecha, close)] ordenado ASC para el símbolo dado."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT fecha, close FROM {table} WHERE simbolo=%s ORDER BY fecha ASC",
                (symbol,)
            )
            return [(row['fecha'], float(row['close'])) for row in cur.fetchall()]
    finally:
        conn.close()


def _save_market_context(rows: list[dict]) -> None:
    if not rows:
        return
    sql = """
        INSERT INTO market_context_daily
            (fecha, simbolo, regime, sma50, sma200, mom20, mom60, volatility_20d)
        VALUES
            (%(fecha)s, %(simbolo)s, %(regime)s, %(sma50)s, %(sma200)s,
             %(mom20)s, %(mom60)s, %(volatility_20d)s)
        ON DUPLICATE KEY UPDATE
            regime=VALUES(regime), sma50=VALUES(sma50), sma200=VALUES(sma200),
            mom20=VALUES(mom20),   mom60=VALUES(mom60),
            volatility_20d=VALUES(volatility_20d)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Runner principal
# ─────────────────────────────────────────────────────────────────────────────

def run_market_regime(
    symbol: str = 'SPY',
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list[dict]:
    """
    Calcula y guarda el régimen de mercado para cada fecha disponible.

    Args:
        symbol:    benchmark de mercado (default 'SPY')
        from_date: calcular desde esta fecha (None = todas)
        to_date:   calcular hasta esta fecha (None = hoy)

    Returns:
        lista de dicts con el resultado por fecha
    """
    series = _load_all_closes(symbol, table='market_index')
    if not series:
        print(f"[WARN] No hay datos de {symbol} en market_index")
        return []

    to_date   = to_date   or date.today()
    from_date = from_date or (series[0][0] if series else date.today())

    # Necesitamos al menos SMA_LONG días de historia antes de la primera fecha a calcular
    min_history = SMA_LONG + MOM_LONG_DAYS + 5

    results = []
    closes_up_to = []   # buffer acumulativo

    for idx, (d, c) in enumerate(series):
        closes_up_to.append(c)
        if d < from_date or d > to_date:
            continue
        if len(closes_up_to) < min_history:
            continue

        ctx = classify_regime(closes_up_to)
        row = {'fecha': d, 'simbolo': symbol, **ctx}
        results.append(row)

    _save_market_context(results)
    print(f"  market_regime [{symbol}]: {len(results)} fechas guardadas")
    return results


def get_latest_regime(symbol: str = 'SPY') -> Optional[dict]:
    """Devuelve el último régimen guardado en DB."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM market_context_daily
                   WHERE simbolo=%s ORDER BY fecha DESC LIMIT 1""",
                (symbol,)
            )
            return cur.fetchone()
    finally:
        conn.close()
