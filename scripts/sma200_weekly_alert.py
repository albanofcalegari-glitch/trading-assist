"""
sma200_weekly_alert.py — Escanea TODOS los activos con historia semanal suficiente
y detecta cruces de precio vs SMA200 semanal.

Señales:
  BUY  CROSS_UP     — precio cruzó al alza la SMA200 semanal
  BUY  NEAR_ABOVE   — precio está ≤3% arriba (cruce reciente, SL cerca)
  BUY  APPROACHING  — precio acercándose desde abajo (≤3%, subiendo)
  SELL CROSS_DOWN   — precio rompió a la baja la SMA200 semanal

Cada señal se inserta en la tabla notification (aparece en la sección de alertas
del sistema) y se envía por Telegram con formato "Alerta cruce SMA semanal:".

Uso:
  python scripts/sma200_weekly_alert.py            # escanea y envía
  python scripts/sma200_weekly_alert.py --dry-run  # imprime sin enviar Telegram
"""
from __future__ import annotations

import argparse
import json
import sys
import os
import datetime as _dt

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from datetime import date
from db.connection import get_conn
from strategies.watchlist_signals import _detect_sma200_weekly
from batches.notifier import make_default_notifier, ConsoleNotifier

BATCH_NAME = 'sma200_weekly_alert'
KIND       = 'sma200_weekly'
MIN_WEEKLY_BARS = 201
ANTISPAM_HOURS  = 168  # 7 días (semanal → no repetir la misma señal en la misma semana)


def _get_symbols() -> list[str]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT simbolo FROM ohlcv_extended
                WHERE timeframe = 'W'
                GROUP BY simbolo
                HAVING COUNT(*) >= %s
                ORDER BY simbolo
            """, (MIN_WEEKLY_BARS,))
            return [r['simbolo'] for r in cur.fetchall()]
    finally:
        conn.close()


def _get_accion_id(cur, symbol: str) -> int | None:
    cur.execute("SELECT id FROM accion WHERE simbolo = %s LIMIT 1", (symbol,))
    row = cur.fetchone()
    return row['id'] if row else None


def _already_sent(cur, symbol: str, cross_type: str) -> bool:
    cur.execute("""
        SELECT 1 FROM notification
        WHERE kind = %s
          AND signal_code = 'SMA200_W_CROSS'
          AND title LIKE %s
          AND data_json LIKE %s
          AND created_at >= (NOW() - INTERVAL %s HOUR)
        LIMIT 1
    """, [KIND, f'%{symbol}%', f'%{cross_type}%', ANTISPAM_HOURS])
    return cur.fetchone() is not None


def _create_run(cur) -> int:
    cur.execute(
        "INSERT INTO batch_run (batch_name, started_at, status) VALUES (%s, %s, 'RUNNING')",
        [BATCH_NAME, _dt.datetime.utcnow()],
    )
    return cur.lastrowid


def _finish_run(conn, run_id: int, status: str, payload: dict, error: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE batch_run
               SET finished_at = %s, status = %s,
                   payload_json = %s, error = %s
               WHERE id = %s""",
            [_dt.datetime.utcnow(), status,
             json.dumps(payload, default=str) if payload else None,
             error, run_id],
        )
    conn.commit()


def run(dry_run: bool = False, fecha: date | None = None) -> dict:
    fecha = fecha or date.today()
    notifier = ConsoleNotifier() if dry_run else make_default_notifier()

    symbols = _get_symbols()
    print(f'SMA200 Weekly Alert — {fecha} — {len(symbols)} activos con ≥{MIN_WEEKLY_BARS} barras W')

    conn = get_conn(autocommit=False)
    run_id: int | None = None

    try:
        with conn.cursor() as cur:
            run_id = _create_run(cur)
        conn.commit()

        emitted = 0
        skipped = 0
        errors: list[str] = []
        signals_found: list[dict] = []

        for symbol in symbols:
            try:
                sigs = _detect_sma200_weekly(symbol, fecha)
            except Exception as e:
                errors.append(f'{symbol}: {e}')
                continue

            for sig in sigs:
                cross_type = (sig.get('data') or {}).get('cross_type', '')

                with conn.cursor() as cur:
                    if _already_sent(cur, symbol, cross_type):
                        skipped += 1
                        continue

                    accion_id = _get_accion_id(cur, symbol)

                    cur.execute(
                        """INSERT INTO notification
                           (batch_run_id, kind, title, body, data_json, created_at,
                            accion_id, signal_code, signal_direction)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        [run_id, KIND, sig['title'], sig['body'],
                         json.dumps(sig.get('data') or {}, default=str),
                         _dt.datetime.utcnow(),
                         accion_id, sig['code'], sig['direction']],
                    )
                conn.commit()
                emitted += 1
                signals_found.append(sig)

                print(f"  [{sig['direction']}] {sig['title']}")

        # ── Telegram: mensaje consolidado ────────────────────────────────
        if signals_found:
            tg_lines = [f'*Alerta cruce SMA semanal* ({fecha})', '']
            buys  = [s for s in signals_found if s['direction'] == 'BUY']
            sells = [s for s in signals_found if s['direction'] == 'SELL']

            if buys:
                tg_lines.append('📈 *COMPRA*')
                for s in buys:
                    d = s['data']
                    ct = d.get('cross_type', '')
                    ct_label = {'CROSS_UP': 'cruzó al alza',
                                'NEAR_ABOVE': 'recién cruzó',
                                'APPROACHING': 'acercándose'}
                    sym = s['title'].split(':')[1].strip().split()[0] if ':' in s['title'] else '?'
                    tg_lines.append(
                        f"  `{sym:6s}` ${d['price']:.2f} | "
                        f"SMA200 ${d['sma200']:.2f} ({d['distance_pct']:+.1f}%) | "
                        f"{ct_label.get(ct, ct)}"
                        f"{' | SL $' + str(d['sl']) if d.get('sl') else ''}"
                    )
                tg_lines.append('')

            if sells:
                tg_lines.append('📉 *VENTA*')
                for s in sells:
                    d = s['data']
                    sym = s['title'].split(':')[1].strip().split()[0] if ':' in s['title'] else '?'
                    tg_lines.append(
                        f"  `{sym:6s}` ${d['price']:.2f} | "
                        f"SMA200 ${d['sma200']:.2f} ({d['distance_pct']:+.1f}%) | "
                        f"rompió a la baja"
                    )
                tg_lines.append('')

            tg_lines.append(f'{len(symbols)} activos escaneados, '
                            f'{emitted} señales, {skipped} anti-spam')

            tg_msg = '\n'.join(tg_lines)
            print(f'\n--- Telegram ---\n{tg_msg}\n---')

            try:
                notifier.notify(KIND, f'Alerta cruce SMA semanal ({fecha})', tg_msg, {})
            except Exception as e:
                errors.append(f'notifier: {e}')
                print(f'  ! Telegram falló: {e}')
        else:
            print(f'\nSin señales SMA200 semanal hoy ({skipped} anti-spam).')

        payload = {
            'symbols_scanned': len(symbols),
            'signals_emitted': emitted,
            'signals_skipped': skipped,
            'errors':          errors[:20],
            'signals':         [{'symbol': s['title'], 'direction': s['direction'],
                                 'cross_type': (s.get('data') or {}).get('cross_type')}
                                for s in signals_found],
        }

        # Summary notification en DB
        summary_title = f'SMA200 Weekly: {emitted} señales' if emitted else 'SMA200 Weekly: sin señales'
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO notification
                   (batch_run_id, kind, title, body, data_json, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [run_id, f'{KIND}_summary', summary_title,
                 f'{len(symbols)} activos, {emitted} señales, {skipped} anti-spam',
                 json.dumps(payload, default=str),
                 _dt.datetime.utcnow()],
            )
        conn.commit()

        _finish_run(conn, run_id, 'OK', payload)
        return {'status': 'OK', 'run_id': run_id, **payload}

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        if run_id:
            try:
                _finish_run(conn, run_id, 'ERROR', None, error=err)
            except Exception:
                pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description='SMA200 Weekly Alert — escanea todos los activos')
    parser.add_argument('--dry-run', action='store_true',
                        help='Solo imprime, no manda Telegram')
    parser.add_argument('--fecha', type=str, default=None,
                        help='Fecha (YYYY-MM-DD). Default: hoy')
    args = parser.parse_args()

    fecha = None
    if args.fecha:
        from datetime import datetime
        fecha = datetime.strptime(args.fecha, '%Y-%m-%d').date()

    result = run(dry_run=args.dry_run, fecha=fecha)
    print(f'\n{json.dumps({k: v for k, v in result.items() if k != "signals"}, indent=2, default=str)}')


if __name__ == '__main__':
    main()
