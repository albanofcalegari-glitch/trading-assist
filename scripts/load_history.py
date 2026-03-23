"""
load_history.py — descarga histórico completo o actualización incremental

Uso:
    # Carga completa (2 años):
    python scripts/load_history.py

    # Solo actualización desde última fecha en DB:
    python scripts/load_history.py --update

    # Solo un símbolo:
    python scripts/load_history.py --symbol NVDA
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE, MARKET_BENCHMARK, SECTOR_BENCHMARKS, SECTOR_MAP, HISTORY_YEARS
from data.data_loader import (
    fetch_price_history,
    save_asset_prices,
    save_market_index,
    save_sector_index,
    update_prices_daily,
    get_last_date,
)

_SECTOR_ETF_TO_NAME = {
    'XLK': 'Technology',
    'XLC': 'Communication Services',
    'XLF': 'Financials',
    'XLY': 'Consumer Discretionary',
    'XLE': 'Energy',
}


def load_full(symbols_filter: str = None):
    """Carga histórico completo para todos los símbolos."""
    all_syms = sorted(set(UNIVERSE) | {MARKET_BENCHMARK} | set(SECTOR_BENCHMARKS))

    if symbols_filter:
        all_syms = [s for s in all_syms if s == symbols_filter.upper()]
        if not all_syms:
            print(f"Símbolo '{symbols_filter}' no encontrado en el universo.")
            return

    print(f"\n=== load_history — carga completa ({HISTORY_YEARS} años) ===")
    print(f"Símbolos: {', '.join(all_syms)}\n")

    for sym in all_syms:
        print(f"  Fetching {sym}...", end=' ', flush=True)
        rows = fetch_price_history(sym, years=HISTORY_YEARS)
        if not rows:
            print("sin datos")
            continue

        if sym == MARKET_BENCHMARK:
            n = save_market_index(rows)
        elif sym in SECTOR_BENCHMARKS:
            sector_name = _SECTOR_ETF_TO_NAME.get(sym, sym)
            n = save_sector_index(rows, sector_name)
        else:
            n = save_asset_prices(rows)

        print(f"{n} filas | {rows[0]['fecha']} -> {rows[-1]['fecha']}")

    print("\n[OK] Carga completa finalizada.\n")


def main():
    parser = argparse.ArgumentParser(description='Carga histórico de precios')
    parser.add_argument('--update', action='store_true',
                        help='Solo actualizar desde última fecha en DB')
    parser.add_argument('--symbol', type=str, default=None,
                        help='Procesar solo este símbolo')
    args = parser.parse_args()

    if args.update:
        update_prices_daily(
            universe=UNIVERSE,
            market_benchmark=MARKET_BENCHMARK,
            sector_benchmarks=SECTOR_BENCHMARKS,
            sector_map=SECTOR_MAP,
        )
    else:
        load_full(args.symbol)


if __name__ == '__main__':
    main()
