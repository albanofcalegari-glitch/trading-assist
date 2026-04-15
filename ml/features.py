"""
ml/features.py — extracción de features para el dataset ml_signals.

Para una (symbol, fecha) trae:
  - features técnicos snapshot desde `indicadortecnico` (joineado por accion_id)
  - contexto macro desde `indicadormercado`
  - features derivados (rs_vs_spy = ret_20d - spy_return_20d)

NO computa nada que dependa del futuro. Todo es snapshot al cierre del día t0.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional

from db.connection import get_conn
from strategies.dynamic_supports import get_dynamic_supports


# ── Resolución de accion_id (cache simple, hay duplicados en `accion`) ───────

_ACCION_ID_CACHE: dict[str, Optional[int]] = {}

# Cache semanal para get_dynamic_supports: los soportes se basan en weekly
# pivots, cambian poco dentro de la misma semana calendario. Reduce las
# llamadas al backfill (29k rows) de ~200ms cada una a <5ms en cache-hit.
_DYN_SUPPORTS_CACHE: dict[tuple[str, date], dict] = {}


def _week_key(fecha: date) -> date:
    # lunes de la semana
    return fecha - timedelta(days=fecha.weekday())


def _get_dyn_supports_cached(symbol: str, fecha: date) -> dict:
    key = (symbol, _week_key(fecha))
    r = _DYN_SUPPORTS_CACHE.get(key)
    if r is None:
        r = get_dynamic_supports(symbol, fecha)
        _DYN_SUPPORTS_CACHE[key] = r
    return r


def _load_ath(cur, symbol: str, fecha: date) -> Optional[float]:
    """All-time-high hasta `fecha` inclusive. None si no hay datos."""
    cur.execute(
        """SELECT MAX(high) AS ath FROM ohlcv_extended
           WHERE simbolo=%s AND timeframe='D' AND fecha<=%s""",
        (symbol, fecha),
    )
    row = cur.fetchone()
    if row and row.get('ath') is not None:
        return float(row['ath'])
    # fallback a price_history si no hay ohlcv_extended
    cur.execute(
        """SELECT MAX(high) AS ath FROM price_history
           WHERE simbolo=%s AND fecha<=%s""",
        (symbol, fecha),
    )
    row = cur.fetchone()
    return float(row['ath']) if row and row.get('ath') is not None else None


def resolve_accion_id(cur, symbol: str) -> Optional[int]:
    """
    Devuelve el accion_id con MÁS filas en indicadortecnico para ese símbolo.
    Hay símbolos duplicados en `accion` (ej AAPL: id=25 y id=12433); nos quedamos
    con el que tiene más historia. Cacheado en proceso.
    """
    if symbol in _ACCION_ID_CACHE:
        return _ACCION_ID_CACHE[symbol]

    cur.execute(
        """SELECT a.id, COUNT(it.id) AS n
           FROM accion a
           LEFT JOIN indicadortecnico it ON it.accion_id = a.id
           WHERE a.simbolo = %s
           GROUP BY a.id
           ORDER BY n DESC
           LIMIT 1""",
        (symbol,),
    )
    row = cur.fetchone()
    aid = int(row['id']) if row and row['n'] else None
    _ACCION_ID_CACHE[symbol] = aid
    return aid


# ── Lectores ─────────────────────────────────────────────────────────────────

_TECH_COLS = (
    'rsi14', 'adx14', 'dist_sma200_pct', 'momentum_5d', 'momentum_20d',
    'atr14_rel', 'vs_52w_high', 'rs_sector', 'volume_ratio_20d',
)


def _load_tech(cur, accion_id: int, fecha: date) -> Optional[dict]:
    cols = ', '.join(_TECH_COLS)
    cur.execute(
        f"SELECT {cols} FROM indicadortecnico "
        f"WHERE accion_id=%s AND fecha=%s LIMIT 1",
        (accion_id, fecha),
    )
    return cur.fetchone()


def _load_macro(cur, fecha: date) -> Optional[dict]:
    """
    indicadormercado tiene una fila por fecha (no por símbolo). Si no hay fila
    exacta para `fecha` agarra la última anterior (most-recent prior).
    """
    cur.execute(
        """SELECT spy_return_20d, vix_percentile_1y, market_regime
           FROM indicadormercado
           WHERE fecha <= %s
           ORDER BY fecha DESC LIMIT 1""",
        (fecha,),
    )
    return cur.fetchone()


def _load_today_bar(cur, symbol: str, fecha: date) -> Optional[dict]:
    """OHLC del día t0 para gap/range_position. Necesita la barra previa para gap."""
    cur.execute(
        """SELECT fecha, open, high, low, close
           FROM price_history
           WHERE simbolo=%s AND fecha<=%s
           ORDER BY fecha DESC LIMIT 2""",
        (symbol, fecha),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    today = rows[0]
    prev  = rows[1] if len(rows) >= 2 else None
    o = float(today['open']); h = float(today['high']); l = float(today['low']); c = float(today['close'])
    rng = h - l
    range_pos = ((c - l) / rng) if rng > 0 else None
    gap = None
    if prev:
        pc = float(prev['close'])
        if pc > 0:
            gap = (o / pc) - 1
    return {
        'price':          c,
        'gap_pct':        round(gap, 6) if gap is not None else None,
        'range_position': round(range_pos, 4) if range_pos is not None else None,
    }


# ── API pública ──────────────────────────────────────────────────────────────

def extract_features(cur, symbol: str, fecha: date) -> Optional[dict]:
    """
    Devuelve dict con todos los features de la fila ml_signals (sin labels, sin
    columnas de identificación). None si faltan datos críticos (precio o tech).
    """
    accion_id = resolve_accion_id(cur, symbol)
    if accion_id is None:
        return None

    tech = _load_tech(cur, accion_id, fecha)
    if tech is None:
        return None  # crítico

    bar = _load_today_bar(cur, symbol, fecha)
    if bar is None:
        return None  # sin precio no hay features útiles

    macro = _load_macro(cur, fecha) or {}

    ret_20d = float(tech['momentum_20d']) if tech['momentum_20d'] is not None else None
    spy_20d = float(macro['spy_return_20d']) if macro.get('spy_return_20d') is not None else None
    rs_vs_spy = (ret_20d - spy_20d) if (ret_20d is not None and spy_20d is not None) else None

    price  = bar['price']
    # indicadortecnico ya guarda dist_sma200_pct (en %); lo normalizamos a fracción
    dist_sma200 = (float(tech['dist_sma200_pct']) / 100.0) if tech['dist_sma200_pct'] is not None else None

    # ── Dynamic support short (tier cyan) ─────────────────────────────────────
    # has_dyn_short:       1 si la estrategia detecta soporte short (horizontal o diagonal)
    # dyn_short_dist_pct:  (price/floor - 1) * 100 — % ARRIBA del piso del short
    #                      (positivo = price encima del soporte; negativo = roto)
    has_dyn_short = 0
    dyn_short_dist_pct: Optional[float] = None
    try:
        dyn = _get_dyn_supports_cached(symbol, fecha)
        short_tier = dyn.get('short')
        if short_tier is not None:
            floor = float(short_tier.get('current_value') or 0)
            if floor > 0 and price > 0:
                has_dyn_short = 1
                dyn_short_dist_pct = round((price / floor - 1) * 100, 3)
    except Exception:
        pass

    # ── Distancia al ATH (all-time-high) ──────────────────────────────────────
    # dist_to_ath_pct: (price/ath - 1) * 100 — típicamente negativo (precio debajo de ATH).
    dist_to_ath_pct: Optional[float] = None
    ath = _load_ath(cur, symbol, fecha)
    if ath and ath > 0 and price > 0:
        dist_to_ath_pct = round((price / ath - 1) * 100, 3)

    return {
        'price':          round(price, 4),
        'volume_ratio':   round(float(tech['volume_ratio_20d']), 4) if tech['volume_ratio_20d'] is not None else None,
        'gap_pct':        bar['gap_pct'],
        'range_position': bar['range_position'],
        'rsi_14':         round(float(tech['rsi14']), 2)            if tech['rsi14']           is not None else None,
        'adx_14':         round(float(tech['adx14']), 2)            if tech['adx14']           is not None else None,
        'dist_sma200':    round(dist_sma200, 6)                     if dist_sma200             is not None else None,
        'ret_5d':         round(float(tech['momentum_5d']) / 100.0, 6)  if tech['momentum_5d']  is not None else None,
        'ret_20d':        round(ret_20d / 100.0, 6)                 if ret_20d                 is not None else None,
        'rs_vs_spy':      round(rs_vs_spy / 100.0, 6)               if rs_vs_spy               is not None else None,
        'atr14_rel':      round(float(tech['atr14_rel']), 4)        if tech['atr14_rel']       is not None else None,
        'vs_52w_high':    round(float(tech['vs_52w_high']), 4)      if tech['vs_52w_high']     is not None else None,
        'rs_sector':      round(float(tech['rs_sector']), 4)        if tech['rs_sector']       is not None else None,
        # zonas: nullable (Fase 2 las enchufa)
        'dist_to_support':    None,
        'dist_to_resistance': None,
        # dynamic_supports (2026-04-15)
        'has_dyn_short':        has_dyn_short,
        'dyn_short_dist_pct':   dyn_short_dist_pct,
        'dist_to_ath_pct':      dist_to_ath_pct,
        # macro
        'market_regime':  int(macro['market_regime']) if macro.get('market_regime') is not None else None,
        'vix_percentile': round(float(macro['vix_percentile_1y']), 4) if macro.get('vix_percentile_1y') is not None else None,
        'spy_return_20d': round(float(macro['spy_return_20d']) / 100.0, 6) if macro.get('spy_return_20d') is not None else None,
    }


# ── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for sym in ('AAPL', 'NVDA', 'JPM'):
                f = extract_features(cur, sym, date(2025, 12, 1))
                print(f'\n{sym} 2025-12-01:')
                for k, v in (f or {}).items():
                    print(f'  {k:18}= {v}')
    finally:
        conn.close()
