"""
ut_bot.py  --  UT Bot trailing stop (variante QuantNomad / Yo_adriiiiaan)

Algoritmo por barra (cronologico), sobre cierre diario:

  nLoss[i] = sensitivity * ATR(period)[i]        # ATR con Wilder smoothing (RMA)

  if close[i] > prev_stop and close[i-1] > prev_stop:
      trailing[i] = max(prev_stop, close[i] - nLoss[i])      # ratchet hacia arriba
  elif close[i] < prev_stop and close[i-1] < prev_stop:
      trailing[i] = min(prev_stop, close[i] + nLoss[i])      # ratchet hacia abajo
  elif close[i] > prev_stop:
      trailing[i] = close[i] - nLoss[i]                      # flip a UP
  else:
      trailing[i] = close[i] + nLoss[i]                      # flip a DOWN

  state[i] = 'UP' si close[i] > trailing[i] else 'DOWN'
  signal BUY : state flipa de DOWN a UP
  signal SELL: state flipa de UP a DOWN

Defaults validados sobre equities diarias (QuantNomad usa 1, acá 2 para menos ruido):
  sensitivity = 2.0
  atr_period  = 10

Funcion publica:
    get_ut_bot(symbol, fecha=today, sensitivity=2.0, atr_period=10) -> dict
"""

from __future__ import annotations

import os
import sys
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from db.connection import get_conn


# ── Carga de datos ───────────────────────────────────────────────────────────

def _load(symbol: str, fecha_max: date) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, high, low, close
                   FROM ohlcv_extended
                   WHERE simbolo = %s AND timeframe = 'D' AND fecha <= %s
                   ORDER BY fecha ASC""",
                (symbol, fecha_max),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ── ATR con Wilder smoothing (RMA) ────────────────────────────────────────────

def _wilder_atr(
    high:   list[float],
    low:    list[float],
    close:  list[float],
    period: int,
) -> list[Optional[float]]:
    """
    ATR usando RMA (Wilder's smoothing):
      seed = mean(TR[0..period-1])
      RMA[i] = (RMA[i-1] * (period-1) + TR[i]) / period

    Retorna lista de len(close) con None en los primeros (period-1) bars.
    """
    n = len(close)
    atr: list[Optional[float]] = [None] * n
    if n < period + 1:
        return atr

    tr = [high[0] - low[0]]
    for i in range(1, n):
        tr.append(max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        ))

    seed = sum(tr[:period]) / period
    atr[period - 1] = seed
    for i in range(period, n):
        prev = atr[i - 1] if atr[i - 1] is not None else seed
        atr[i] = (prev * (period - 1) + tr[i]) / period

    return atr


# ── Main ─────────────────────────────────────────────────────────────────────

def get_ut_bot(
    symbol:      str,
    fecha:       Optional[date] = None,
    sensitivity: float          = 2.0,
    atr_period:  int            = 10,
) -> dict:
    """
    Devuelve la serie de trailing stop de UT Bot mas las señales BUY/SELL.

    Estructura:
      {
        symbol, sensitivity, atr_period, bars_of_data,
        points:  [{fecha, value, state}],   # state ∈ {'UP','DOWN'}
        signals: [{fecha, kind, price}],    # kind  ∈ {'BUY','SELL'}
      }
    """
    fecha = fecha or date.today()
    rows  = _load(symbol, fecha)

    result_base = {
        'symbol':       symbol,
        'sensitivity':  sensitivity,
        'atr_period':   atr_period,
        'bars_of_data': len(rows),
        'points':       [],
        'signals':      [],
    }

    if len(rows) < atr_period + 2:
        return result_base

    high  = [float(r['high'])  for r in rows]
    low   = [float(r['low'])   for r in rows]
    close = [float(r['close']) for r in rows]
    atr   = _wilder_atr(high, low, close, atr_period)

    n = len(rows)
    trailing: list[Optional[float]] = [None] * n
    state:    list[Optional[str]]   = [None] * n

    start = atr_period - 1
    a0    = atr[start] or 0.0
    nloss = sensitivity * a0
    trailing[start] = close[start] - nloss
    state[start]    = 'UP' if close[start] > trailing[start] else 'DOWN'

    for i in range(start + 1, n):
        a  = atr[i] or 0.0
        nl = sensitivity * a
        prev = trailing[i - 1]
        assert prev is not None  # garantizado: trailing[start] inicializado

        if close[i] > prev and close[i - 1] > prev:
            trailing[i] = max(prev, close[i] - nl)
        elif close[i] < prev and close[i - 1] < prev:
            trailing[i] = min(prev, close[i] + nl)
        elif close[i] > prev:
            trailing[i] = close[i] - nl
        else:
            trailing[i] = close[i] + nl

        state[i] = 'UP' if close[i] > trailing[i] else 'DOWN'

    points = [{
        'fecha': rows[i]['fecha'].isoformat(),
        'value': round(trailing[i] or 0.0, 4),
        'state': state[i],
    } for i in range(start, n)]

    signals = []
    for i in range(start + 1, n):
        if state[i - 1] == 'DOWN' and state[i] == 'UP':
            signals.append({
                'fecha': rows[i]['fecha'].isoformat(),
                'kind':  'BUY',
                'price': round(close[i], 4),
            })
        elif state[i - 1] == 'UP' and state[i] == 'DOWN':
            signals.append({
                'fecha': rows[i]['fecha'].isoformat(),
                'kind':  'SELL',
                'price': round(close[i], 4),
            })

    return {
        'symbol':       symbol,
        'sensitivity':  sensitivity,
        'atr_period':   atr_period,
        'bars_of_data': n,
        'points':       points,
        'signals':      signals,
    }


if __name__ == '__main__':
    import json
    sym = sys.argv[1] if len(sys.argv) > 1 else 'GOOGL'
    res = get_ut_bot(sym)
    print(json.dumps({
        'symbol':         res['symbol'],
        'sensitivity':    res['sensitivity'],
        'atr_period':     res['atr_period'],
        'bars_of_data':   res['bars_of_data'],
        'points_count':   len(res['points']),
        'signals_count':  len(res['signals']),
        'last_points':    res['points'][-3:]  if res['points']  else [],
        'last_signals':   res['signals'][-5:] if res['signals'] else [],
    }, indent=2))
