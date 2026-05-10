"""
strategies.ema_cross — Detección de cruces EMA50 / EMA200 (Golden & Death Cross)
=================================================================================
Señales:
  GOLDEN_CROSS  — EMA50 cruza al alza la EMA200 (bullish)
  DEATH_CROSS   — EMA50 cruza a la baja la EMA200 (bearish)
  APPROACHING_GOLDEN — EMA50 a menos del 1% de cruzar al alza
  APPROACHING_DEATH  — EMA50 a menos del 1% de cruzar a la baja

Cada señal incluye contexto: distancia entre EMAs, pendiente de ambas,
momentum, RSI y volumen relativo.
"""
from __future__ import annotations

import sys, os
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.utils import rsi, momentum_pct, vol_ratio

EMA_FAST = 50
EMA_SLOW = 200
APPROACH_PCT = 1.0
MIN_BARS = EMA_SLOW + 30


def _ema_series(prices: list[float], n: int) -> list[float]:
    """Serie EMA completa. Devuelve lista del mismo largo que prices (NaN-padded)."""
    if len(prices) < n:
        return []
    k = 2.0 / (n + 1)
    import statistics
    seed = statistics.mean(prices[:n])
    result = [float('nan')] * (n - 1)
    result.append(seed)
    val = seed
    for p in prices[n:]:
        val = p * k + val * (1 - k)
        result.append(val)
    return result


def _slope_pct(series: list[float], lookback: int = 5) -> Optional[float]:
    """Pendiente porcentual de los últimos N valores."""
    if len(series) < lookback + 1:
        return None
    old = series[-lookback - 1]
    new = series[-1]
    if old <= 0:
        return None
    return (new / old - 1) * 100


def _load_closes(symbol: str, fecha: date, n: int = 500) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, close, volume
                   FROM price_history
                   WHERE simbolo=%s AND fecha<=%s
                   ORDER BY fecha DESC LIMIT %s""",
                (symbol, fecha, n)
            )
            rows = list(cur.fetchall())
        rows.reverse()
        return rows
    finally:
        conn.close()


def analyze_symbol(symbol: str, fecha: Optional[date] = None) -> Optional[dict]:
    """
    Analiza cruce EMA50/EMA200 para un símbolo.

    Returns dict con señal, o None si datos insuficientes.
    """
    fecha = fecha or date.today()
    rows = _load_closes(symbol, fecha, n=500)
    if len(rows) < MIN_BARS:
        return None

    closes = [float(r['close']) for r in rows]
    volumes = [float(r['volume']) for r in rows]

    ema_fast = _ema_series(closes, EMA_FAST)
    ema_slow = _ema_series(closes, EMA_SLOW)

    if not ema_fast or not ema_slow or len(ema_fast) < 2 or len(ema_slow) < 2:
        return None

    fast_now = ema_fast[-1]
    fast_prev = ema_fast[-2]
    slow_now = ema_slow[-1]
    slow_prev = ema_slow[-2]

    if any(v != v for v in (fast_now, fast_prev, slow_now, slow_prev)):
        return None

    price = closes[-1]
    gap_pct = (fast_now / slow_now - 1) * 100 if slow_now > 0 else 0

    signal = None
    if fast_prev <= slow_prev and fast_now > slow_now:
        signal = 'GOLDEN_CROSS'
    elif fast_prev >= slow_prev and fast_now < slow_now:
        signal = 'DEATH_CROSS'
    elif fast_now < slow_now and abs(gap_pct) <= APPROACH_PCT:
        signal = 'APPROACHING_GOLDEN'
    elif fast_now > slow_now and abs(gap_pct) <= APPROACH_PCT:
        signal = 'APPROACHING_DEATH'

    rsi_val = rsi(closes, 14)
    mom20 = momentum_pct(closes, 20)
    mom60 = momentum_pct(closes, 60)
    vol_r = vol_ratio(volumes, short=5, long=20)
    fast_slope = _slope_pct(ema_fast, 5)
    slow_slope = _slope_pct(ema_slow, 5)

    return {
        'fecha': fecha,
        'simbolo': symbol,
        'signal': signal,
        'price': round(price, 2),
        'ema50': round(fast_now, 2),
        'ema200': round(slow_now, 2),
        'gap_pct': round(gap_pct, 2),
        'ema50_slope': round(fast_slope, 3) if fast_slope else None,
        'ema200_slope': round(slow_slope, 3) if slow_slope else None,
        'rsi14': round(rsi_val, 1) if rsi_val else None,
        'mom20': round(mom20, 2) if mom20 else None,
        'mom60': round(mom60, 2) if mom60 else None,
        'vol_ratio': round(vol_r, 2) if vol_r else None,
    }


def scan_universe(symbols: list[str], fecha: Optional[date] = None) -> list[dict]:
    """Escanea lista de símbolos, devuelve solo los que tienen señal."""
    fecha = fecha or date.today()
    results = []
    for i, sym in enumerate(symbols):
        if i % 100 == 0:
            print(f'  ema_cross: {i}/{len(symbols)}...')
        try:
            r = analyze_symbol(sym, fecha)
            if r and r['signal']:
                results.append(r)
        except Exception as e:
            print(f'  {sym}: error {e}')
    return results
