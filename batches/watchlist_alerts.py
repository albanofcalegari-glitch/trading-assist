"""
batches.watchlist_alerts — emite notificaciones BUY/SELL para la watchlist de cada usuario.

Flujo:
  1. Itera los users que tienen al menos un item en user_watchlist.
  2. Para cada (user_id, accion_id, simbolo) corre strategies.watchlist_signals.detect_signals.
  3. Cada señal se inserta como notification (kind='watchlist') con user_id/accion_id/signal_code/signal_direction.
  4. Anti-spam: no repite la misma (user_id, accion_id, signal_code) dentro de las últimas 24h.
  5. Al terminar inserta una notification global (user_id NULL, kind='watchlist_summary')
     para trazabilidad del run y manda el resumen a Telegram via el notifier.

El modelo difiere del resto de batches: no emite una única notificación final sino N por usuario.
Por eso no usamos Batch._insert_notification (no soporta user_id/accion_id) y escribimos el insert local.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import os
import traceback
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.notifier import Notifier, make_default_notifier
from strategies.watchlist_signals import detect_signals


BATCH_NAME = 'watchlist_alerts'
KIND       = 'watchlist'
KIND_SUMMARY = 'watchlist_summary'
ANTISPAM_HOURS = 24


def _ensure_user_watchlist(cur) -> None:
    """Crea user_watchlist si no existe. Duplicado defensivo del ensure que hace api.py
    para que el batch pueda correr contra una DB donde la api no arrancó todavía."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_watchlist (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            user_id       INT           NOT NULL,
            accion_id     INT           NOT NULL,
            qty           DECIMAL(20,6) NULL,
            avg_buy_price DECIMAL(20,6) NULL,
            note          VARCHAR(500)  NULL,
            added_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_user_accion (user_id, accion_id),
            INDEX idx_user (user_id)
        )
    """)


def _create_run(cur) -> int:
    cur.execute(
        "INSERT INTO batch_run (batch_name, started_at, status) VALUES (%s, %s, 'RUNNING')",
        [BATCH_NAME, _dt.datetime.utcnow()],
    )
    return cur.lastrowid


def _finish_run(conn, run_id: int, status: str, payload: dict | None, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE batch_run
               SET finished_at = %s, status = %s,
                   payload_json = %s, error = %s
               WHERE id = %s""",
            [
                _dt.datetime.utcnow(),
                status,
                json.dumps(payload, default=str) if payload else None,
                error,
                run_id,
            ],
        )
    conn.commit()


def _load_watchlist(cur) -> list[dict]:
    """Trae (user_id, username, accion_id, simbolo) de todos los usuarios con watchlist no vacía."""
    cur.execute("""
        SELECT uw.user_id, u.username, uw.accion_id, a.simbolo
        FROM user_watchlist uw
        JOIN users  u ON u.id = uw.user_id
        JOIN accion a ON a.id = uw.accion_id
        ORDER BY uw.user_id, a.simbolo
    """)
    return cur.fetchall() or []


def _already_sent(cur, user_id: int, accion_id: int, signal_code: str) -> bool:
    cur.execute("""
        SELECT 1 FROM notification
        WHERE user_id = %s
          AND accion_id = %s
          AND signal_code = %s
          AND created_at >= (NOW() - INTERVAL %s HOUR)
        LIMIT 1
    """, [user_id, accion_id, signal_code, ANTISPAM_HOURS])
    return cur.fetchone() is not None


def _insert_signal_notification(cur, run_id: int, user_id: int, accion_id: int,
                                signal: dict) -> int:
    cur.execute(
        """INSERT INTO notification
           (batch_run_id, kind, title, body, data_json, created_at,
            user_id, accion_id, signal_code, signal_direction)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        [
            run_id,
            KIND,
            signal['title'],
            signal['body'],
            json.dumps(signal.get('data') or {}, default=str),
            _dt.datetime.utcnow(),
            user_id,
            accion_id,
            signal['code'],
            signal['direction'],
        ],
    )
    return cur.lastrowid


def _insert_summary_notification(cur, run_id: int, title: str, body: str, payload: dict) -> int:
    cur.execute(
        """INSERT INTO notification
           (batch_run_id, kind, title, body, data_json, created_at)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        [
            run_id,
            KIND_SUMMARY,
            title,
            body,
            json.dumps(payload, default=str),
            _dt.datetime.utcnow(),
        ],
    )
    return cur.lastrowid


def run(notifier: Notifier | None = None, fecha: _dt.date | None = None) -> dict:
    notifier = notifier or make_default_notifier()
    fecha    = fecha or _dt.date.today()

    conn = get_conn(autocommit=False)
    run_id: int | None = None
    try:
        with conn.cursor() as cur:
            _ensure_user_watchlist(cur)
            run_id = _create_run(cur)
        conn.commit()

        # 1) watchlist: qué símbolos corren por qué usuarios
        with conn.cursor() as cur:
            items = _load_watchlist(cur)

        if not items:
            payload = {'users': 0, 'symbols': 0, 'signals_emitted': 0, 'signals_skipped': 0}
            title = 'Watchlist alerts: sin usuarios con watchlist'
            body  = 'No hay ítems en user_watchlist. Nada que analizar.'
            with conn.cursor() as cur:
                _insert_summary_notification(cur, run_id, title, body, payload)
            conn.commit()
            _finish_run(conn, run_id, 'OK', payload)
            notifier.notify(KIND_SUMMARY, title, body, payload)
            return {'status': 'OK', 'run_id': run_id, **payload}

        # 2) agrupa por símbolo para correr detect_signals una sola vez por símbolo
        symbol_to_users: dict[str, list[dict]] = defaultdict(list)
        for it in items:
            symbol_to_users[it['simbolo']].append(it)

        emitted = 0
        skipped = 0
        per_user: dict[int, list[dict]] = defaultdict(list)
        errors: list[str] = []

        for symbol, subs in symbol_to_users.items():
            try:
                signals = detect_signals(symbol, fecha)
            except Exception as e:
                errors.append(f'{symbol}: {e}')
                continue
            if not signals:
                continue
            for sub in subs:
                user_id    = sub['user_id']
                accion_id  = sub['accion_id']
                for sig in signals:
                    code = sig.get('code')
                    if not code:
                        continue
                    with conn.cursor() as cur:
                        if _already_sent(cur, user_id, accion_id, code):
                            skipped += 1
                            continue
                        try:
                            notif_id = _insert_signal_notification(cur, run_id, user_id, accion_id, sig)
                        except Exception as e:
                            errors.append(f'{symbol} u{user_id} {code}: {e}')
                            conn.rollback()
                            continue
                    conn.commit()
                    emitted += 1
                    per_user[user_id].append({
                        'symbol':     symbol,
                        'direction':  sig['direction'],
                        'code':       code,
                        'title':      sig['title'],
                        'notif_id':   notif_id,
                    })
                    # Notifica a canales externos (Telegram/Console) por cada señal nueva
                    try:
                        notifier.notify(KIND, sig['title'], sig['body'], sig.get('data') or {})
                    except Exception as e:
                        errors.append(f'notifier {symbol} u{user_id} {code}: {e}')

        n_users = len({i['user_id'] for i in items})
        payload = {
            'users':           n_users,
            'symbols':         len(symbol_to_users),
            'signals_emitted': emitted,
            'signals_skipped': skipped,
            'errors':          errors[:20],
            'per_user':        {str(uid): sigs for uid, sigs in per_user.items()},
        }

        if emitted == 0:
            title = 'Watchlist alerts: sin señales nuevas'
            body  = (f'Se analizaron {len(symbol_to_users)} símbolos en {payload["users"]} '
                     f'watchlists. {skipped} señales ya estaban emitidas (anti-spam).')
        else:
            title = f'Watchlist alerts: {emitted} señales nuevas'
            lines = [f'{emitted} señales nuevas en {len(symbol_to_users)} símbolos '
                     f'({payload["users"]} usuarios):']
            for uid, sigs in per_user.items():
                lines.append(f'  user {uid}:')
                for s in sigs[:20]:
                    lines.append(f"    [{s['direction']}] {s['symbol']} · {s['code']}")
                if len(sigs) > 20:
                    lines.append(f'    ... y {len(sigs) - 20} más')
            if skipped:
                lines.append(f'({skipped} señales saltadas por anti-spam {ANTISPAM_HOURS}h)')
            body = '\n'.join(lines)

        with conn.cursor() as cur:
            _insert_summary_notification(cur, run_id, title, body, payload)
        conn.commit()

        _finish_run(conn, run_id, 'OK', payload)

        # resumen a consola/telegram
        try:
            notifier.notify(KIND_SUMMARY, title, body, payload)
        except Exception as e:
            print(f'[watchlist_alerts] WARN notifier summary falló: {e}')

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
    result = run()
    print(json.dumps({k: v for k, v in result.items() if k != 'per_user'}, indent=2, default=str))
