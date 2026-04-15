"""
run_historical_highs.py — corre la deteccion de maximos historicos para el universo.

Uso:
    python scripts/run_historical_highs.py
    python scripts/run_historical_highs.py --symbol AAPL
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE
from strategies.historical_highs import (
    analyze_symbol, run_universe, ensure_table, save_signals,
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Deteccion de maximos historicos')
    parser.add_argument('--symbol', type=str, default=None,
                        help='Procesar solo este simbolo')
    args = parser.parse_args()

    print('\n=== run_historical_highs ===\n')

    ensure_table()
    print('[OK] Tabla historical_high_signals verificada')

    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        symbols = UNIVERSE

    print(f'Analizando {len(symbols)} simbolos...\n')

    results = run_universe(symbols)
    alerts = [r for r in results if r['setup_state'] != 'NO_SIGNAL']

    saved = save_signals(results)
    print(f'\n[OK] {saved} seniales guardadas en DB')

    if alerts:
        print(f'\n--- {len(alerts)} activos con senial ---\n')
        for r in sorted(alerts, key=lambda x: abs(x.get('distance_52w_pct') or 999)):
            flag = ' *** ALL-TIME HIGH ***' if r['is_all_time_high'] else ''
            print(f"  {r['simbolo']:6s}  {r['setup_state']:15s}  "
                  f"${r['price']:.2f}  dist_52w={r['distance_52w_pct']:.2f}%  "
                  f"RSI={r['rsi14'] or 0:.1f}{flag}")
    else:
        print('\nNingun activo cerca de maximos historicos.')

    return 0


if __name__ == '__main__':
    sys.exit(main())
