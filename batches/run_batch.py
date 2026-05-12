"""
batches.run_batch — entry point CLI para ejecutar un batch por nombre.

Uso:
    python -m batches.run_batch closing
    python -m batches.run_batch premarket
    python -m batches.run_batch weekly_ranking

Diseñado para ser invocado desde Windows Task Scheduler / cron / systemd.

Roadmap de schedule (horarios ART):
    10:00  premarket
    10:30  opening      (no implementado aún)
    12:00  midday       (no implementado aún)
    17:00  closing
    viernes 17:30  weekly_ranking + rotation_evaluation (no implementados aún)
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from batches.closing              import ClosingBatch
from batches.premarket            import PremarketBatch
from batches.opening              import OpeningBatch
from batches.weekly_ranking       import WeeklyRankingBatch
from batches.historical_lows_batch import HistoricalLowsBatch
from batches.historical_highs_batch import HistoricalHighsBatch
from batches.bonds_alert            import BondsAlertBatch
# Conforme se vayan implementando, importar acá:
# from batches.midday          import MiddayBatch


REGISTRY = {
    'closing':         ClosingBatch,
    'premarket':       PremarketBatch,
    'opening':         OpeningBatch,
    'weekly_ranking':  WeeklyRankingBatch,
    'historical_lows': HistoricalLowsBatch,
    'historical_highs': HistoricalHighsBatch,
    'bonds_alert':     BondsAlertBatch,
    # 'midday':          MiddayBatch,
}


def main() -> int:
    parser = argparse.ArgumentParser(description='Ejecuta un batch de Trading Assist')
    parser.add_argument('batch', choices=sorted(REGISTRY.keys()),
                        help='Nombre del batch a ejecutar')
    args = parser.parse_args()

    cls = REGISTRY[args.batch]
    batch = cls()
    print(f'>>> Ejecutando batch "{args.batch}"...')
    try:
        result = batch.run()
        print(f'>>> OK · run_id={result["run_id"]} · notification={result["notification"]}')
        return 0
    except Exception as e:
        print(f'>>> ERROR: {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
