"""
update_prices_cron.py — Actualización automática de precios (apertura y cierre)

Diseñado para correr vía cron en el VPS:
  # Apertura USA (10:30 ART = 9:30 ET)
  30 10 * * 1-5  cd /opt/trading-assist && venv/bin/python scripts/update_prices_cron.py --mode open  >> /var/log/trading-prices.log 2>&1
  # Cierre USA (17:15 ART = 16:15 ET, 15 min después del cierre)
  15 17 * * 1-5  cd /opt/trading-assist && venv/bin/python scripts/update_prices_cron.py --mode close >> /var/log/trading-prices.log 2>&1

Modo 'open':  actualiza precios + ohlcv_extended (datos intradía parciales)
Modo 'close': actualiza precios + ohlcv_extended + recalcula señales
"""

import argparse
import sys
import os
import time
from datetime import datetime, date

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from config import UNIVERSE, MARKET_BENCHMARK, SECTOR_BENCHMARKS, SECTOR_MAP
from data.data_loader import update_prices_daily
from backfill_history import backfill_symbol, ensure_table, _ALL_SYMBOLS


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


def update_prices():
    log('Actualizando precios diarios...')
    try:
        update_prices_daily(
            universe=UNIVERSE,
            market_benchmark=MARKET_BENCHMARK,
            sector_benchmarks=SECTOR_BENCHMARKS,
            sector_map=SECTOR_MAP,
        )
        log('  Precios OK')
    except Exception as e:
        log(f'  ERROR precios: {e}')


def update_ohlcv_extended():
    log('Actualizando ohlcv_extended (D/W/M)...')
    try:
        ensure_table()
        updated = 0
        errors = 0
        for sym in _ALL_SYMBOLS:
            for tf in ['D', 'W', 'M']:
                try:
                    r = backfill_symbol(sym, tf, update_only=True)
                    if not r.get('skipped'):
                        updated += r.get('inserted', 0) + r.get('updated', 0)
                except Exception:
                    errors += 1
        log(f'  ohlcv_extended OK — {updated} registros, {errors} errores')
    except Exception as e:
        log(f'  ERROR ohlcv_extended: {e}')


def recalc_signals():
    log('Recalculando señales post-cierre...')
    try:
        from context.market_regime import run_market_regime
        from context.sector_regime import run_sector_regime
        run_market_regime(symbol=MARKET_BENCHMARK)
        run_sector_regime(sector_benchmarks=SECTOR_BENCHMARKS)
        log('  Contexto de mercado OK')
    except Exception as e:
        log(f'  ERROR contexto: {e}')

    try:
        from batches.universe_scan import run as run_universe_scan
        run_universe_scan(hoy=date.today())
        log('  Universe scan OK')
    except Exception as e:
        log(f'  ERROR universe scan: {e}')


def main():
    parser = argparse.ArgumentParser(description='Actualización de precios cron')
    parser.add_argument('--mode', choices=['open', 'close', 'full'], default='close',
                        help='open=precios+ohlcv, close=precios+ohlcv+señales, full=todo')
    args = parser.parse_args()

    log(f'=== Inicio update_prices_cron mode={args.mode} ===')
    t0 = time.time()

    update_prices()
    update_ohlcv_extended()

    if args.mode in ('close', 'full'):
        recalc_signals()

    elapsed = time.time() - t0
    log(f'=== Fin — {elapsed:.0f}s ===')


if __name__ == '__main__':
    main()
