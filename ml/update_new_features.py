"""
ml/update_new_features.py — UPDATE targeted de las 3 features nuevas
(has_dyn_short, dyn_short_dist_pct, dist_to_ath_pct) sobre las filas
existentes en ml_signals. Mucho más rápido que rehacer el dataset completo.

Estrategia:
  1. SELECT symbol, fecha, price FROM ml_signals donde las nuevas columnas
     están NULL.
  2. Agrupar por (symbol, semana) → 1 llamada a get_dynamic_supports por grupo.
  3. Calcular dist_to_ath_pct desde ohlcv_extended.
  4. UPDATE ml_signals SET has_dyn_short=..., dyn_short_dist_pct=...,
     dist_to_ath_pct=... WHERE id=%s.

Uso:
  python -m ml.update_new_features
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

from db.connection import get_conn
from strategies.dynamic_supports import get_dynamic_supports


UPDATE_SQL = """
UPDATE ml_signals
SET has_dyn_short = %s,
    dyn_short_dist_pct = %s,
    dist_to_ath_pct = %s
WHERE id = %s
"""


def _week_key(f: date) -> date:
    return f - timedelta(days=f.weekday())


def _ath(cur, symbol: str, fecha: date) -> float | None:
    cur.execute(
        """SELECT MAX(high) AS ath FROM ohlcv_extended
           WHERE simbolo=%s AND timeframe='D' AND fecha<=%s""",
        (symbol, fecha),
    )
    row = cur.fetchone()
    if row and row.get('ath') is not None:
        return float(row['ath'])
    cur.execute(
        """SELECT MAX(high) AS ath FROM price_history
           WHERE simbolo=%s AND fecha<=%s""",
        (symbol, fecha),
    )
    row = cur.fetchone()
    return float(row['ath']) if row and row.get('ath') is not None else None


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    except Exception:
        pass

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, symbol, fecha, price FROM ml_signals
               WHERE has_dyn_short IS NULL OR dist_to_ath_pct IS NULL
               ORDER BY symbol, fecha"""
        )
        rows = cur.fetchall()
    conn.close()

    total = len(rows)
    print(f'[#] {total} filas a actualizar')
    if total == 0:
        return

    dyn_cache: dict[tuple[str, date], dict] = {}
    ath_cache: dict[tuple[str, date], float | None] = {}

    def get_dyn(sym: str, f: date) -> dict:
        key = (sym, _week_key(f))
        r = dyn_cache.get(key)
        if r is None:
            r = get_dynamic_supports(sym, f)
            dyn_cache[key] = r
        return r

    updates: list[tuple] = []
    t0 = time.time()
    last_sym = None
    conn = get_conn()
    try:
        for i, r in enumerate(rows, 1):
            sym = r['symbol']
            fecha = r['fecha']
            price = float(r['price']) if r['price'] is not None else None

            has_short = 0
            short_dist = None
            try:
                dyn = get_dyn(sym, fecha)
                t_short = dyn.get('short')
                if t_short is not None and price:
                    floor = float(t_short.get('current_value') or 0)
                    if floor > 0:
                        has_short = 1
                        short_dist = round((price / floor - 1) * 100, 3)
            except Exception:
                pass

            ath_key = (sym, fecha)
            if ath_key not in ath_cache:
                with conn.cursor() as cur:
                    ath_cache[ath_key] = _ath(cur, sym, fecha)
            ath = ath_cache[ath_key]
            dist_ath = None
            if ath and ath > 0 and price:
                dist_ath = round((price / ath - 1) * 100, 3)

            updates.append((has_short, short_dist, dist_ath, r['id']))

            if len(updates) >= 500:
                with conn.cursor() as cur:
                    cur.executemany(UPDATE_SQL, updates)
                updates.clear()

            if sym != last_sym:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta_min = (total - i) / rate / 60 if rate > 0 else 0
                print(f'  · {sym:8s} ({i:5d}/{total}) '
                      f'cache_hits={len(dyn_cache)} rate={rate:.1f}/s eta={eta_min:.0f}min')
                last_sym = sym

        if updates:
            with conn.cursor() as cur:
                cur.executemany(UPDATE_SQL, updates)
    finally:
        conn.close()

    elapsed = time.time() - t0
    print(f'\n[+] {total} filas actualizadas en {elapsed:.0f}s '
          f'({total/elapsed:.1f} rows/s, {len(dyn_cache)} cache entries)')


if __name__ == '__main__':
    main()
