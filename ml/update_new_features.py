"""
ml/update_new_features.py — UPDATE targeted de features nuevas sobre las filas
existentes en ml_signals. Mucho más rápido que rehacer el dataset completo.

Estrategia:
  1. SELECT filas donde las columnas nuevas están NULL.
  2. Cache semanal para get_dynamic_supports/resistances.
  3. UPDATE ml_signals SET ... WHERE id=%s.

Uso:
  python -m ml.update_new_features
  python -m ml.update_new_features --only-resistances
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta

from db.connection import get_conn
from strategies.dynamic_supports import get_dynamic_supports
from strategies.dynamic_resistances import get_dynamic_resistances


UPDATE_SQL = """
UPDATE ml_signals
SET has_dyn_short = %s,
    dyn_short_dist_pct = %s,
    dist_to_ath_pct = %s,
    has_res_long = %s,
    res_long_dist_pct = %s,
    has_res_mid = %s,
    res_mid_dist_pct = %s,
    res_mid_slope = %s,
    has_res_short = %s,
    res_short_dist_pct = %s
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

    parser = argparse.ArgumentParser()
    parser.add_argument('--only-resistances', action='store_true',
                        help='solo backfill columnas de resistencias (skip supports/ATH)')
    args = parser.parse_args()

    conn = get_conn()
    with conn.cursor() as cur:
        if args.only_resistances:
            cur.execute(
                """SELECT id, symbol, fecha, price FROM ml_signals
                   WHERE has_res_long IS NULL
                   ORDER BY symbol, fecha"""
            )
        else:
            cur.execute(
                """SELECT id, symbol, fecha, price FROM ml_signals
                   WHERE has_dyn_short IS NULL OR dist_to_ath_pct IS NULL
                      OR has_res_long IS NULL
                   ORDER BY symbol, fecha"""
            )
        rows = cur.fetchall()
    conn.close()

    total = len(rows)
    print(f'[#] {total} filas a actualizar')
    if total == 0:
        return

    dyn_sup_cache: dict[tuple[str, date], dict] = {}
    dyn_res_cache: dict[tuple[str, date], dict] = {}
    ath_cache: dict[tuple[str, date], float | None] = {}

    def get_sup(sym: str, f: date) -> dict:
        key = (sym, _week_key(f))
        r = dyn_sup_cache.get(key)
        if r is None:
            r = get_dynamic_supports(sym, f)
            dyn_sup_cache[key] = r
        return r

    def get_res(sym: str, f: date) -> dict:
        key = (sym, _week_key(f))
        r = dyn_res_cache.get(key)
        if r is None:
            r = get_dynamic_resistances(sym, f)
            dyn_res_cache[key] = r
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

            # ── supports ──
            has_short = 0
            short_dist = None
            if not args.only_resistances:
                try:
                    dyn = get_sup(sym, fecha)
                    t_short = dyn.get('short')
                    if t_short is not None and price:
                        floor = float(t_short.get('current_value') or 0)
                        if floor > 0:
                            has_short = 1
                            short_dist = round((price / floor - 1) * 100, 3)
                except Exception:
                    pass

            # ── ATH ──
            dist_ath = None
            if not args.only_resistances:
                ath_key = (sym, fecha)
                if ath_key not in ath_cache:
                    with conn.cursor() as cur:
                        ath_cache[ath_key] = _ath(cur, sym, fecha)
                ath = ath_cache[ath_key]
                if ath and ath > 0 and price:
                    dist_ath = round((price / ath - 1) * 100, 3)

            # ── resistances ──
            h_res_long = 0; d_res_long = None
            h_res_mid = 0;  d_res_mid = None; s_res_mid = None
            h_res_short = 0; d_res_short = None
            try:
                dres = get_res(sym, fecha)
                for tier_key in ('long', 'mid', 'short'):
                    tier = dres.get(tier_key)
                    if tier is not None and price:
                        cv = float(tier.get('current_value') or 0)
                        if cv > 0:
                            dist = round((price / cv - 1) * 100, 3)
                            if tier_key == 'long':
                                h_res_long = 1; d_res_long = dist
                            elif tier_key == 'mid':
                                h_res_mid = 1; d_res_mid = dist
                                s_res_mid = float(tier.get('slope_annual_pct', 0))
                            else:
                                h_res_short = 1; d_res_short = dist
            except Exception:
                pass

            updates.append((
                has_short, short_dist, dist_ath,
                h_res_long, d_res_long,
                h_res_mid, d_res_mid, s_res_mid,
                h_res_short, d_res_short,
                r['id'],
            ))

            if len(updates) >= 500:
                with conn.cursor() as cur:
                    cur.executemany(UPDATE_SQL, updates)
                updates.clear()

            if sym != last_sym:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta_min = (total - i) / rate / 60 if rate > 0 else 0
                print(f'  · {sym:8s} ({i:5d}/{total}) '
                      f'cache={len(dyn_sup_cache)}+{len(dyn_res_cache)} '
                      f'rate={rate:.1f}/s eta={eta_min:.0f}min')
                last_sym = sym

        if updates:
            with conn.cursor() as cur:
                cur.executemany(UPDATE_SQL, updates)
    finally:
        conn.close()

    elapsed = time.time() - t0
    print(f'\n[+] {total} filas actualizadas en {elapsed:.0f}s '
          f'({total/elapsed:.1f} rows/s)')


if __name__ == '__main__':
    main()
