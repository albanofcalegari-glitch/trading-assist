"""
batches.universe_scan — Escanea TODOS los activos del universo buscando señales.

A diferencia de watchlist_alerts (que solo analiza la watchlist de cada usuario),
este batch barre config.UNIVERSE completo y emite notificaciones globales
(user_id=NULL) para cada señal detectada.

Ideal para correr ~12:00 AR después de que los precios se acomoden post-apertura.

Uso:
    python -m batches.universe_scan [--dry-run] [--fecha YYYY-MM-DD]
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import traceback
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE
from db.connection import get_conn
from batches.notifier import Notifier, make_default_notifier
from strategies.watchlist_signals import detect_signals


BATCH_NAME   = 'universe_scan'
KIND         = 'universe_scan'
KIND_SUMMARY = 'universe_scan_summary'
ANTISPAM_HOURS = 24


def _create_run(cur) -> int:
    cur.execute(
        "INSERT INTO batch_run (batch_name, started_at, status) VALUES (%s, %s, 'RUNNING')",
        [BATCH_NAME, _dt.datetime.utcnow()],
    )
    return cur.lastrowid


def _finish_run(conn, run_id: int, status: str, payload: dict | None,
                error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE batch_run
               SET finished_at = %s, status = %s,
                   payload_json = %s, error = %s
               WHERE id = %s""",
            [
                _dt.datetime.utcnow(), status,
                json.dumps(payload, default=str) if payload else None,
                error, run_id,
            ],
        )
    conn.commit()


def _already_sent(cur, signal_code: str, accion_id: int | None) -> bool:
    cur.execute("""
        SELECT 1 FROM notification
        WHERE user_id IS NULL
          AND signal_code = %s
          AND accion_id = %s
          AND kind = %s
          AND created_at >= (NOW() - INTERVAL %s HOUR)
        LIMIT 1
    """, [signal_code, accion_id, KIND, ANTISPAM_HOURS])
    return cur.fetchone() is not None


def _get_accion_id(cur, simbolo: str) -> int | None:
    cur.execute("SELECT id FROM accion WHERE simbolo = %s LIMIT 1", [simbolo])
    row = cur.fetchone()
    return row['id'] if row else None


def run(notifier: Notifier | None = None, fecha: _dt.date | None = None) -> dict:
    notifier = notifier or make_default_notifier()
    fecha    = fecha or _dt.date.today()

    conn = get_conn(autocommit=False)
    run_id: int | None = None
    try:
        with conn.cursor() as cur:
            run_id = _create_run(cur)
        conn.commit()

        symbols = list(UNIVERSE)
        emitted  = 0
        skipped  = 0
        errors: list[str] = []
        by_code: dict[str, list[dict]] = defaultdict(list)

        for sym in symbols:
            try:
                signals = detect_signals(sym, fecha)
            except Exception as e:
                errors.append(f'{sym}: {e}')
                continue
            if not signals:
                continue

            with conn.cursor() as cur:
                accion_id = _get_accion_id(cur, sym)

            for sig in signals:
                code = sig.get('code')
                if not code:
                    continue

                with conn.cursor() as cur:
                    if _already_sent(cur, code, accion_id):
                        skipped += 1
                        continue

                    try:
                        cur.execute(
                            """INSERT INTO notification
                               (batch_run_id, kind, title, body, data_json, created_at,
                                user_id, accion_id, signal_code, signal_direction)
                               VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, %s)""",
                            [
                                run_id, KIND,
                                sig['title'], sig['body'],
                                json.dumps(sig.get('data') or {}, default=str),
                                _dt.datetime.utcnow(),
                                accion_id, code, sig['direction'],
                            ],
                        )
                    except Exception as e:
                        errors.append(f'{sym} {code}: insert {e}')
                        conn.rollback()
                        continue
                conn.commit()
                emitted += 1
                by_code[code].append({
                    'symbol':    sym,
                    'direction': sig['direction'],
                    'title':     sig['title'],
                })

                try:
                    notifier.notify(KIND, sig['title'], sig['body'], sig.get('data') or {})
                except Exception as e:
                    errors.append(f'notifier {sym} {code}: {e}')

        payload = {
            'symbols_scanned': len(symbols),
            'signals_emitted': emitted,
            'signals_skipped': skipped,
            'by_code':         {c: len(v) for c, v in by_code.items()},
            'errors':          errors[:20],
        }

        if emitted == 0:
            title = 'Universe scan: sin señales nuevas'
            body  = (f'Se analizaron {len(symbols)} activos. '
                     f'{skipped} señales ya emitidas (anti-spam {ANTISPAM_HOURS}h).')
        else:
            title = f'Universe scan: {emitted} señales nuevas'
            lines = [f'{emitted} señales en {len(symbols)} activos:']
            for code, items in sorted(by_code.items()):
                symbols_list = ', '.join(i['symbol'] for i in items[:15])
                if len(items) > 15:
                    symbols_list += f' ... (+{len(items)-15})'
                lines.append(f'  [{items[0]["direction"]}] {code} ({len(items)}): {symbols_list}')
            if skipped:
                lines.append(f'({skipped} saltadas por anti-spam)')
            body = '\n'.join(lines)

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO notification
                   (batch_run_id, kind, title, body, data_json, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [run_id, KIND_SUMMARY, title, body,
                 json.dumps(payload, default=str), _dt.datetime.utcnow()],
            )
        conn.commit()
        _finish_run(conn, run_id, 'OK', payload)

        try:
            notifier.notify(KIND_SUMMARY, title, body, payload)
        except Exception as e:
            print(f'[universe_scan] WARN notifier summary: {e}')

        return {'status': 'OK', 'run_id': run_id, **payload}

    except Exception as e:
        err = ''.join(traceback.format_exception_only(type(e), e)).strip()
        full = err + '\n' + traceback.format_exc()
        if run_id is not None:
            try:
                _finish_run(conn, run_id, 'ERROR', None, error=full)
            except Exception:
                pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--fecha', type=str, default=None)
    args = parser.parse_args()

    if args.dry_run:
        from batches.notifier import ConsoleNotifier
        notifier = ConsoleNotifier()
    else:
        notifier = make_default_notifier()

    fecha = _dt.date.fromisoformat(args.fecha) if args.fecha else None
    result = run(notifier=notifier, fecha=fecha)
    print(json.dumps({k: v for k, v in result.items()}, indent=2, default=str))
