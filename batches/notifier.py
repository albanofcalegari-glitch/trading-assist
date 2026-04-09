"""
batches.notifier — abstracción del canal de salida de los batches.

Implementaciones:
  - ConsoleNotifier  → stdout
  - TelegramNotifier → Bot API de Telegram (requiere bot_token + chat_id)
  - MultiNotifier    → combina varios

`make_default_notifier()` arma automáticamente la cadena Console+Telegram
si las env vars TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID están definidas.
Antes mira si existe `/opt/trading-assist/.env` y carga sus KEY=VALUE
en `os.environ` (sin pisar lo que ya estuviera) — esto sirve para que
funcione tanto bajo gunicorn (systemd) como bajo cron sin tener que
configurar dos lugares.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Protocol


# ─── env file loader (idempotente, sin dependencias) ────────────────────────

_ENV_FILE_DEFAULT = '/opt/trading-assist/.env'


def _load_env_file(path: str = _ENV_FILE_DEFAULT) -> None:
    """Carga KEY=VALUE de un archivo si existe, sin pisar os.environ."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception as e:  # pragma: no cover
        print(f'[notifier] WARN no se pudo leer {path}: {e}')


# ─── Notifiers ──────────────────────────────────────────────────────────────

class Notifier(Protocol):
    def notify(self, kind: str, title: str, body: str, payload: dict) -> None: ...


class ConsoleNotifier:
    """Notificador mínimo: imprime a stdout. Los datos ya quedan en DB
    via Batch._insert_notification — el frontend los lee desde ahí."""

    def notify(self, kind: str, title: str, body: str, payload: dict) -> None:
        print(f'[{kind}] {title}')
        print(f'  {body}')


class TelegramNotifier:
    """Envía notificaciones via la HTTP Bot API de Telegram.

    Formato del mensaje (Markdown):
        *<title>*
        _<kind>_

        <body>
    """

    API_BASE = 'https://api.telegram.org'

    def __init__(self, bot_token: str, chat_id: str, timeout: int = 15):
        self.bot_token = bot_token
        self.chat_id   = chat_id
        self.timeout   = timeout

    def _send(self, text: str) -> None:
        url = f'{self.API_BASE}/bot{self.bot_token}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id':    self.chat_id,
            'text':       text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': 'true',
        }).encode()
        req = urllib.request.Request(url, data=data, method='POST')
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            body = r.read().decode('utf-8', errors='replace')
            j = json.loads(body)
            if not j.get('ok'):
                raise RuntimeError(f'telegram API !ok: {body[:300]}')

    @staticmethod
    def _escape_md(s: str) -> str:
        # Markdown legacy: solo escapamos los chars problemáticos basicos
        return s.replace('_', r'\_').replace('*', r'\*').replace('[', r'\[').replace('`', r'\`')

    def notify(self, kind: str, title: str, body: str, payload: dict) -> None:
        # Mensaje compacto. Limita body a 3500 chars (Telegram max 4096).
        safe_title = self._escape_md(title)
        safe_kind  = self._escape_md(kind)
        safe_body  = self._escape_md(body[:3500])
        text = f'*{safe_title}*\n_{safe_kind}_\n\n{safe_body}'
        try:
            self._send(text)
        except Exception as e:
            # Fallback: re-raise para que MultiNotifier capture y siga
            raise RuntimeError(f'TelegramNotifier.notify falló: {e}') from e


class MultiNotifier:
    """Combina varios notificadores (ej. console + telegram)."""

    def __init__(self, *notifiers: Notifier):
        self._notifiers = notifiers

    def notify(self, kind: str, title: str, body: str, payload: dict) -> None:
        for n in self._notifiers:
            try:
                n.notify(kind, title, body, payload)
            except Exception as e:  # pragma: no cover
                print(f'  ! notifier {type(n).__name__} falló: {e}')


# ─── Factory ────────────────────────────────────────────────────────────────

def make_default_notifier() -> Notifier:
    """Devuelve el Notifier por default segun el entorno.

    - Si TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID están seteados (env o .env),
      devuelve MultiNotifier(Console, Telegram).
    - Si no, solo ConsoleNotifier.
    """
    _load_env_file()
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat  = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if token and chat:
        return MultiNotifier(ConsoleNotifier(), TelegramNotifier(token, chat))
    return ConsoleNotifier()
