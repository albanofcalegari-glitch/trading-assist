"""
batches — sistema de jobs/notificaciones para Trading Assist.

Cada batch hereda de `Batch` (en `batches.base`) e implementa:
  - fetch()         → obtiene los datos crudos
  - build_payload() → arma el payload tipado
  - render()        → genera el (title, body) humano para la notificación

El método `run()` orquesta: fetch → build_payload → persist en batch_run →
crear notification → notificar vía Notifier (logs/DB; en el futuro Telegram/email).

Punto de entrada: `python -m batches.run_batch <name>`  (ver run_batch.py).
"""

from batches.base import Batch  # noqa: F401
