"""
backfill_missing.py — wrapper que backfillea TODOS los símbolos de `accion`
que no tienen filas en `ohlcv_extended`. Reusa `backfill_history.backfill_symbol`.

Usa el fix `PBR.A -> PBR-A` (vía `_yf_symbol()` en backfill_history).
Diseñado para correr en prod con `nohup`:

    nohup venv/bin/python scripts/backfill_missing.py > /var/log/backfill_mass.log 2>&1 &

Flags:
    --delay 0.8      delay entre requests (default 0.8s)
    --tf D,W,M       timeframes a procesar (default todos)
    --limit N        solo procesar primeros N símbolos (debug)
    --resume         saltea símbolos que ya tienen aunque sea 1 barra en ohlcv_extended
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from scripts.backfill_history import backfill_symbol, ensure_table, _log


def _missing_symbols(tfs: list[str]) -> list[str]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT a.simbolo
                   FROM accion a
                   LEFT JOIN ohlcv_extended o ON o.simbolo = a.simbolo
                   WHERE o.simbolo IS NULL
                   ORDER BY a.simbolo"""
            )
            return [r['simbolo'] for r in cur.fetchall()]
    finally:
        conn.close()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[attr-defined]
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument('--delay', type=float, default=0.8)
    p.add_argument('--tf', type=str, default='D,W,M')
    p.add_argument('--limit', type=int, default=None)
    args = p.parse_args()

    tfs = [t.strip() for t in args.tf.split(',') if t.strip() in ('D', 'W', 'M')]
    if not tfs:
        print('[!] no valid timeframes')
        sys.exit(1)

    ensure_table()
    symbols = _missing_symbols(tfs)
    if args.limit:
        symbols = symbols[:args.limit]

    total = len(symbols)
    print(f'[#] backfill_missing: {total} símbolos sin ohlcv_extended, tfs={tfs}, delay={args.delay}s')
    print(f'[#] estimado: {total * len(tfs) * (args.delay + 0.3):.0f}s '
          f'({total * len(tfs) * (args.delay + 0.3) / 3600:.1f}h)')
    sys.stdout.flush()

    ok_syms = 0
    empty_syms = 0
    total_bars = 0
    t0 = time.time()

    for i, sym in enumerate(symbols, 1):
        inserted_any = False
        for tf in tfs:
            try:
                res = backfill_symbol(sym, tf)
                _log(res)
                if not res['skipped']:
                    inserted_any = True
                    total_bars += res['bars_total']
            except Exception as e:
                print(f'  {sym:8s} [{tf}]  ERROR: {type(e).__name__}: {e}')
            time.sleep(args.delay)

        if inserted_any:
            ok_syms += 1
        else:
            empty_syms += 1

        if i % 50 == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta_h = (total - i) / rate / 3600 if rate > 0 else 0
            print(f'--- progress {i}/{total}  ok={ok_syms}  empty={empty_syms}  '
                  f'bars={total_bars}  rate={rate:.2f}syms/s  eta={eta_h:.1f}h ---')
            sys.stdout.flush()

    elapsed = time.time() - t0
    print(f'\n[+] DONE {total} símbolos en {elapsed/3600:.2f}h. '
          f'ok={ok_syms}  empty={empty_syms}  bars_inserted={total_bars}')


if __name__ == '__main__':
    main()
