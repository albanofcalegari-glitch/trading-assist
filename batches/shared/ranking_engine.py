"""
batches.shared.ranking_engine — scoring semanal de acciones USA.

Filosofía: simple, transparente, replicable. Cada métrica se normaliza a 0-100
con un mapeo lineal contra una escala fija (no percentiles del universo, para
que el score sea interpretable de forma absoluta y se pueda explicar).

Métricas (con peso):
    ret_5d        (40%)  retorno últimos 5 días
    rs_20d_vs_spy (25%)  fuerza relativa: ret_20d_stock - ret_20d_spy
    trend_sma200  (15%)  precio sobre / debajo de SMA200
    volume_ratio  (10%)  volumen reciente vs promedio 20d
    consistency   (10%)  cuántos de los últimos 20 días cerraron en verde

Filtros mínimos:
    precio > $5
    volumen promedio 20d > 500k
    ≥ 30 velas en el período de cálculo

Uso típico:
    rows = fetch_universe_history(cur, days=75)              # bulk SQL
    grouped = group_by_symbol(rows)
    spy_ret_20d = compute_return(grouped['SPY'], 20)
    scored = score_all(grouped, spy_ret_20d)
    top10 = scored[:10]
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

USA_MARKETS = ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')

MIN_PRICE   = 5.0
MIN_AVG_VOL = 500_000
MIN_CANDLES = 30

WEIGHTS = {
    'ret_5d':        0.40,
    'rs_20d_vs_spy': 0.25,
    'trend_sma200':  0.15,
    'volume_ratio':  0.10,
    'consistency':   0.10,
}


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_universe_history(cur, days: int = 75) -> list[dict]:
    """
    Trae todas las velas de los últimos `days` días para acciones de mercados USA.
    El bulk fetch se procesa en Python (más simple que CTEs por símbolo).
    """
    cutoff = date.today() - timedelta(days=days)
    placeholders = ','.join(['%s'] * len(USA_MARKETS))
    cur.execute(f"""
        SELECT a.id AS accion_id, a.simbolo, a.nombre, m.descripcion AS mercado,
               v.fecha, v.precio_cierre, v.volumen
        FROM valorhistoricoaccion v
        JOIN accion  a ON a.id = v.accion_id
        JOIN mercado m ON m.id = a.mercado_id
        WHERE m.descripcion IN ({placeholders})
          AND v.fecha >= %s
        ORDER BY a.simbolo, v.fecha
    """, [*USA_MARKETS, cutoff])
    return list(cur.fetchall())


def fetch_spy_history(cur, days: int = 75) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    cur.execute("""
        SELECT v.fecha, v.precio_cierre, v.volumen
        FROM valorhistoricoaccion v
        JOIN accion a ON a.id = v.accion_id
        WHERE a.simbolo = 'SPY' AND v.fecha >= %s
        ORDER BY v.fecha
    """, [cutoff])
    return list(cur.fetchall())


# ─── Range fetchers (para backtests) ─────────────────────────────────────────
#
# Mismas formas que los fetch normales pero con rango [start, end] explícito,
# e incluyendo `precio_apertura` (con fallback a `precio_cierre` vía COALESCE)
# para que el backtest pueda ejecutar al open del siguiente día hábil.

def fetch_universe_history_range(cur, start_date: date, end_date: date) -> list[dict]:
    placeholders = ','.join(['%s'] * len(USA_MARKETS))
    cur.execute(f"""
        SELECT a.id AS accion_id, a.simbolo, a.nombre, m.descripcion AS mercado,
               v.fecha, v.precio_cierre,
               COALESCE(v.precio_apertura, v.precio_cierre) AS precio_apertura,
               v.volumen
        FROM valorhistoricoaccion v
        JOIN accion  a ON a.id = v.accion_id
        JOIN mercado m ON m.id = a.mercado_id
        WHERE m.descripcion IN ({placeholders})
          AND v.fecha BETWEEN %s AND %s
        ORDER BY a.simbolo, v.fecha
    """, [*USA_MARKETS, start_date, end_date])
    return list(cur.fetchall())


def fetch_spy_history_range(cur, start_date: date, end_date: date) -> list[dict]:
    cur.execute("""
        SELECT v.fecha, v.precio_cierre,
               COALESCE(v.precio_apertura, v.precio_cierre) AS precio_apertura,
               v.volumen
        FROM valorhistoricoaccion v
        JOIN accion a ON a.id = v.accion_id
        WHERE a.simbolo = 'SPY' AND v.fecha BETWEEN %s AND %s
        ORDER BY v.fecha
    """, [start_date, end_date])
    return list(cur.fetchall())


def group_by_symbol(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r['simbolo'], []).append(r)
    return out


# ─── Métricas ────────────────────────────────────────────────────────────────

def compute_return(candles: list[dict], lookback: int) -> float | None:
    if len(candles) < lookback + 1:
        return None
    a = float(candles[-(lookback + 1)]['precio_cierre'] or 0)
    b = float(candles[-1]['precio_cierre'] or 0)
    if a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def compute_sma(candles: list[dict], window: int) -> float | None:
    if len(candles) < window:
        return None
    vals = [float(c['precio_cierre'] or 0) for c in candles[-window:]]
    if any(v <= 0 for v in vals):
        return None
    return sum(vals) / window


def compute_avg_volume(candles: list[dict], window: int = 20) -> float | None:
    if len(candles) < window:
        return None
    vols = [float(c['volumen'] or 0) for c in candles[-window:]]
    return sum(vols) / window


def compute_consistency(candles: list[dict], window: int = 20) -> float | None:
    """% de días verdes en la ventana (0-100)."""
    if len(candles) < window + 1:
        return None
    chunk = candles[-(window + 1):]
    greens = 0
    for i in range(1, len(chunk)):
        prev = float(chunk[i - 1]['precio_cierre'] or 0)
        curr = float(chunk[i]['precio_cierre'] or 0)
        if prev > 0 and curr > prev:
            greens += 1
    return (greens / window) * 100.0


# ─── Normalizadores 0-100 ────────────────────────────────────────────────────

def _clip(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


def _norm_ret_5d(ret: float | None) -> float:
    """-10% → 0, 0% → 50, +10% → 100."""
    if ret is None:
        return 0.0
    return _clip(50.0 + ret * 5.0)


def _norm_rs(rs: float | None) -> float:
    """-15% → 0, 0% → 50, +15% → 100."""
    if rs is None:
        return 0.0
    return _clip(50.0 + rs * (50.0 / 15.0))


def _norm_trend(price: float | None, sma: float | None) -> float:
    """precio % por encima de SMA200: -20% → 0, 0% → 50, +20% → 100."""
    if price is None or sma is None or sma <= 0:
        return 0.0
    pct = (price / sma - 1.0) * 100.0
    return _clip(50.0 + pct * 2.5)


def _norm_volume(vol_recent: float | None, vol_avg: float | None) -> float:
    """ratio 0.5 → 0, 1.0 → 50, 2.0 → 100."""
    if vol_recent is None or vol_avg is None or vol_avg <= 0:
        return 50.0
    ratio = vol_recent / vol_avg
    return _clip(50.0 + (ratio - 1.0) * 50.0)


def _norm_consistency(c: float | None) -> float:
    if c is None:
        return 0.0
    return _clip(c)  # ya es 0-100


# ─── Score ───────────────────────────────────────────────────────────────────

def score_symbol(candles: list[dict], spy_ret_20d: float | None) -> dict | None:
    """
    Score 0-100 para un símbolo. Devuelve None si no pasa filtros.
    """
    if len(candles) < MIN_CANDLES:
        return None

    last = candles[-1]
    price = float(last['precio_cierre'] or 0)
    if price < MIN_PRICE:
        return None

    avg_vol = compute_avg_volume(candles, 20)
    if avg_vol is None or avg_vol < MIN_AVG_VOL:
        return None

    ret_5d  = compute_return(candles, 5)
    ret_20d = compute_return(candles, 20)
    sma200  = compute_sma(candles, 200)
    consistency = compute_consistency(candles, 20)

    rs_20d = None
    if ret_20d is not None and spy_ret_20d is not None:
        rs_20d = ret_20d - spy_ret_20d

    last_vol = float(last['volumen'] or 0)

    metrics = {
        'ret_5d':        _norm_ret_5d(ret_5d),
        'rs_20d_vs_spy': _norm_rs(rs_20d),
        'trend_sma200':  _norm_trend(price, sma200),
        'volume_ratio':  _norm_volume(last_vol, avg_vol),
        'consistency':   _norm_consistency(consistency),
    }

    score = sum(metrics[k] * w for k, w in WEIGHTS.items())

    return {
        'symbol':       last['simbolo'],
        'name':         last['nombre'],
        'mercado':      last['mercado'],
        'accion_id':    last['accion_id'],
        'price':        price,
        'score':        round(score, 1),
        'metrics':      {k: round(v, 1) for k, v in metrics.items()},
        'raw': {
            'ret_5d':        round(ret_5d,  2) if ret_5d  is not None else None,
            'ret_20d':       round(ret_20d, 2) if ret_20d is not None else None,
            'rs_20d_vs_spy': round(rs_20d,  2) if rs_20d  is not None else None,
            'sma200':        round(sma200,  2) if sma200  is not None else None,
            'avg_vol_20d':   int(avg_vol)      if avg_vol is not None else None,
            'consistency':   round(consistency, 1) if consistency is not None else None,
        },
        'explain': _explain(metrics, ret_5d, rs_20d, price, sma200),
    }


def _explain(metrics: dict[str, float], ret_5d, rs_20d, price, sma200) -> str:
    bits = []
    if ret_5d is not None:
        bits.append(f"5d {'+' if ret_5d >= 0 else ''}{ret_5d:.1f}%")
    if rs_20d is not None:
        bits.append(f"RS {'+' if rs_20d >= 0 else ''}{rs_20d:.1f}% vs SPY")
    if price and sma200:
        diff = (price / sma200 - 1.0) * 100
        bits.append(f"{'sobre' if diff >= 0 else 'bajo'} SMA200 ({diff:+.1f}%)")
    return ' · '.join(bits) if bits else '—'


def score_symbol_at(candles: list[dict], idx: int,
                    spy_ret_20d: float | None) -> dict | None:
    """
    Score "as of" candles[idx] — para uso en backtests.

    Reusa exactamente la misma lógica que `score_symbol`; sólo recorta la lista
    de velas hasta el índice deseado y delega. NO duplica fórmulas de scoring.
    """
    if idx + 1 < MIN_CANDLES:
        return None
    return score_symbol(candles[: idx + 1], spy_ret_20d)


def score_all(grouped: dict[str, list[dict]],
              spy_ret_20d: float | None) -> list[dict]:
    """
    Devuelve la lista completa scoreada y ordenada por score desc.
    Las que no pasan filtros se descartan silenciosamente.
    """
    scored: list[dict] = []
    for sym, candles in grouped.items():
        if sym == 'SPY':
            continue
        try:
            res = score_symbol(candles, spy_ret_20d)
            if res is not None:
                scored.append(res)
        except Exception as e:
            print(f'  [ranking] {sym}: {e}')
    scored.sort(key=lambda r: r['score'], reverse=True)
    return scored
