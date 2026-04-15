"""
backfill_missing_daily.py — Carga precios diarios (tf='D') para todos los
simbolos de la tabla `accion` que no tienen historico en `ohlcv_extended`.

Resumable: si se interrumpe, al relanzar salta los simbolos ya procesados
leyendo DIRECTO de la DB (no del progress file) — asi si lo abortas a mitad
de un simbolo, al retomar lo completa desde su ultima fecha.

Uso:
    python scripts/backfill_missing_daily.py
    python scripts/backfill_missing_daily.py --delay 1.2
    python scripts/backfill_missing_daily.py --limit 100       # solo primeros 100
    python scripts/backfill_missing_daily.py --log backfill.log
"""

import argparse
import os
import sys
import time
import signal
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from scripts.backfill_history import ensure_table, backfill_symbol


_STOP = False

def _handle_sigint(signum, frame):
    global _STOP
    print('\n[INT] Ctrl+C recibido — terminando al finalizar simbolo actual...', flush=True)
    _STOP = True

signal.signal(signal.SIGINT, _handle_sigint)


def _missing_symbols() -> list[str]:
    """
    Retorna simbolos que estan en `accion` y no tienen ninguna fila en
    `ohlcv_extended` con timeframe='D'.

    Ordenados alfabeticamente para que el progreso sea previsible.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.simbolo
                  FROM accion a
                  LEFT JOIN (
                      SELECT DISTINCT simbolo
                        FROM ohlcv_extended
                       WHERE timeframe = 'D'
                  ) o ON o.simbolo = a.simbolo
                 WHERE o.simbolo IS NULL
                 ORDER BY a.simbolo
            """)
            rows = cur.fetchall()
            return [r['simbolo'] for r in rows]
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--delay', type=float, default=0.8,
                    help='Delay en segundos entre requests a Yahoo (default 0.8)')
    ap.add_argument('--limit', type=int, default=None,
                    help='Limitar a los primeros N simbolos (util para testing)')
    ap.add_argument('--log', type=str, default=None,
                    help='Archivo de log — si se omite, va a stdout solamente')
    args = ap.parse_args()

    log_fh = open(args.log, 'a', encoding='utf-8', buffering=1) if args.log else None

    def log(msg: str):
        stamp = datetime.now().strftime('%H:%M:%S')
        line = f'[{stamp}] {msg}'
        print(line, flush=True)
        if log_fh:
            log_fh.write(line + '\n')

    ensure_table()

    pending = _missing_symbols()
    if args.limit:
        pending = pending[:args.limit]

    total = len(pending)
    log(f'backfill_missing_daily  |  pendientes: {total}  |  delay: {args.delay}s')
    log(f'estimado: ~{(total * (args.delay + 0.4)) / 60:.0f} min ({(total * (args.delay + 0.4)) / 3600:.1f} hs)')
    log('=' * 72)

    ok = 0
    skipped = 0
    failed = 0
    total_bars = 0
    started = time.time()

    for i, sym in enumerate(pending, start=1):
        if _STOP:
            log(f'abortado por usuario — procesados {i - 1}/{total}')
            break

        try:
            result = backfill_symbol(sym, 'D', update_only=False)
        except Exception as e:
            failed += 1
            log(f'[{i:5d}/{total}] {sym:10s}  EXCEPTION  {e}')
            time.sleep(args.delay)
            continue

        if result['skipped']:
            reason = result.get('reason', '')
            skipped += 1
            log(f'[{i:5d}/{total}] {sym:10s}  SKIP       {reason}')
        else:
            ok += 1
            total_bars += result['bars_total']
            log(
                f'[{i:5d}/{total}] {sym:10s}  OK         '
                f'{result["first_date"]} -> {result["last_date"]}  '
                f'bars={result["bars_total"]:5d}'
            )

        # Summary cada 100
        if i % 100 == 0:
            elapsed = time.time() - started
            rate = i / elapsed if elapsed > 0 else 0
            eta_min = (total - i) / rate / 60 if rate > 0 else 0
            log(
                f'  -- progreso: {i}/{total}  OK={ok}  SKIP={skipped}  FAIL={failed}  '
                f'bars={total_bars:,}  ETA={eta_min:.0f} min'
            )

        time.sleep(args.delay)

    elapsed = time.time() - started
    log('=' * 72)
    log(
        f'RESUMEN  procesados={ok + skipped + failed}/{total}  '
        f'OK={ok}  SKIP={skipped}  FAIL={failed}  '
        f'bars_totales={total_bars:,}  '
        f'tiempo={elapsed / 60:.1f} min'
    )

    if log_fh:
        log_fh.close()


if __name__ == '__main__':
    main()
