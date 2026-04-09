"""
batches.base — clase base para todos los batches.

Cada batch sigue el mismo ciclo de vida:

    1. Crea un row en `batch_run` con status RUNNING.
    2. fetch()         → trae los datos crudos desde la DB / Yahoo / etc.
    3. build_payload() → estructura el payload tipado (dict serializable).
    4. render()        → produce (title, body) en formato humano.
    5. Inserta el resultado en `notification` y notifica vía Notifier.
    6. Marca el batch_run como OK / ERROR.

Las subclases sólo tienen que implementar fetch / build_payload / render
y declarar `name` y `kind`.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import os
import traceback
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.notifier import Notifier, make_default_notifier


class Batch:
    """Base class para batches.  Subclases deben definir name + kind."""

    name: str = ''   # ej. 'closing', 'premarket', 'weekly_ranking'
    kind: str = ''   # tipo de notification, ej. 'close', 'pre_market'

    def __init__(self, notifier: Notifier | None = None):
        # Si no se pasa notifier explícito, usa el default que mira las
        # env vars / /opt/trading-assist/.env y arma Console+Telegram si
        # las creds de Telegram están disponibles.
        self.notifier = notifier or make_default_notifier()

    # ── Hooks que las subclases implementan ───────────────────────────────

    def fetch(self) -> Any:
        raise NotImplementedError

    def build_payload(self, raw: Any) -> dict:
        raise NotImplementedError

    def render(self, payload: dict) -> tuple[str, str]:
        """Devuelve (title, body) humano para la notificación."""
        return payload.get('title', self.name), payload.get('body', '')

    # ── Orquestación ──────────────────────────────────────────────────────

    def run(self) -> dict:
        if not self.name or not self.kind:
            raise RuntimeError(f'{type(self).__name__}: name/kind no definidos')

        run_id = self._create_run()
        try:
            raw     = self.fetch()
            payload = self.build_payload(raw)
            title, body = self.render(payload)

            notif_id = self._insert_notification(run_id, title, body, payload)
            self._finish_run(run_id, 'OK', payload)
            self.notifier.notify(self.kind, title, body, payload)

            return {
                'batch':         self.name,
                'run_id':        run_id,
                'notification':  notif_id,
                'status':        'OK',
                'payload':       payload,
            }
        except Exception as e:
            err = ''.join(traceback.format_exception_only(type(e), e)).strip()
            self._finish_run(run_id, 'ERROR', None, error=err + '\n' + traceback.format_exc())
            raise

    # ── Helpers de DB ─────────────────────────────────────────────────────

    def _create_run(self) -> int:
        conn = get_conn(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO batch_run (batch_name, started_at, status) VALUES (%s, %s, 'RUNNING')",
                    [self.name, _dt.datetime.utcnow()],
                )
                run_id = cur.lastrowid
            conn.commit()
            return run_id
        finally:
            conn.close()

    def _finish_run(self, run_id: int, status: str, payload: dict | None,
                    error: str | None = None) -> None:
        conn = get_conn(autocommit=False)
        try:
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
        finally:
            conn.close()

    def _insert_notification(self, run_id: int, title: str, body: str,
                             payload: dict) -> int:
        conn = get_conn(autocommit=False)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO notification
                       (batch_run_id, kind, title, body, data_json, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    [
                        run_id,
                        self.kind,
                        title,
                        body,
                        json.dumps(payload, default=str),
                        _dt.datetime.utcnow(),
                    ],
                )
                notif_id = cur.lastrowid
            conn.commit()
            return notif_id
        finally:
            conn.close()
