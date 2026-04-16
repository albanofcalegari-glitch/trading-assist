"""
run_watchlist_alerts.py — emite notificaciones BUY/SELL para la watchlist de cada usuario.

Uso:
    python scripts/run_watchlist_alerts.py
    python scripts/run_watchlist_alerts.py --fecha 2026-04-16
    python scripts/run_watchlist_alerts.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from batches.notifier import ConsoleNotifier, make_default_notifier
from batches.watchlist_alerts import run as run_batch


def _parse_fecha(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s, '%Y-%m-%d').date()


def main() -> int:
    parser = argparse.ArgumentParser(description='Watchlist alerts (BUY/SELL por usuario)')
    parser.add_argument('--fecha',   type=str, default=None,
                        help='Fecha a analizar (YYYY-MM-DD). Default: hoy.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Fuerza notifier=Console (no manda Telegram aunque esté configurado).')
    args = parser.parse_args()

    fecha = _parse_fecha(args.fecha)
    notifier = ConsoleNotifier() if args.dry_run else make_default_notifier()

    print('\n=== run_watchlist_alerts ===')
    print(f'fecha   : {fecha or date.today()}')
    print(f'notifier: {type(notifier).__name__}\n')

    result = run_batch(notifier=notifier, fecha=fecha)

    # Reporte final (omitimos per_user porque puede ser grande)
    summary = {k: v for k, v in result.items() if k != 'per_user'}
    print('\n--- summary ---')
    print(json.dumps(summary, indent=2, default=str))
    return 0 if result.get('status') == 'OK' else 1


if __name__ == '__main__':
    sys.exit(main())
