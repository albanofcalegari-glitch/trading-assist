"""
run_context.py — calcula y guarda contexto de mercado y sectorial

Uso:
    # Calcular todo (desde el principio):
    python scripts/run_context.py

    # Solo mercado:
    python scripts/run_context.py --only market

    # Solo sectores:
    python scripts/run_context.py --only sector

    # Desde una fecha específica:
    python scripts/run_context.py --from 2025-01-01
"""
import argparse
from datetime import date
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import MARKET_BENCHMARK, SECTOR_BENCHMARKS
from context.market_regime import run_market_regime, get_latest_regime
from context.sector_regime import run_sector_regime, get_latest_sector_regimes


def main():
    parser = argparse.ArgumentParser(description='Calcula contexto de mercado y sectorial')
    parser.add_argument('--only',   choices=['market', 'sector'], default=None)
    parser.add_argument('--from',   dest='from_date', type=str, default=None,
                        help='Fecha inicio YYYY-MM-DD')
    parser.add_argument('--to',     dest='to_date',   type=str, default=None,
                        help='Fecha fin YYYY-MM-DD')
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date   = date.fromisoformat(args.to_date)   if args.to_date   else None

    print(f"\n=== run_context ===")
    if from_date:
        print(f"  Desde: {from_date}")
    if to_date:
        print(f"  Hasta: {to_date}")
    print()

    if args.only != 'sector':
        print(f"[1/2] Régimen de mercado ({MARKET_BENCHMARK})...")
        run_market_regime(
            symbol=MARKET_BENCHMARK,
            from_date=from_date,
            to_date=to_date,
        )

    if args.only != 'market':
        print(f"\n[2/2] Régimen sectorial ({', '.join(SECTOR_BENCHMARKS)})...")
        run_sector_regime(
            sector_benchmarks=SECTOR_BENCHMARKS,
            from_date=from_date,
            to_date=to_date,
        )

    # ── Resumen del estado actual ─────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("RESUMEN — ESTADO ACTUAL")
    print("=" * 55)

    mkt = get_latest_regime(MARKET_BENCHMARK)
    if mkt:
        print(f"\nMercado ({MARKET_BENCHMARK}) — {mkt['fecha']}")
        print(f"  Régimen:      {mkt['regime']}")
        print(f"  Mom20/60:     {mkt['mom20']:+.1f}% / {mkt['mom60']:+.1f}%")
        print(f"  Vol20d:       {mkt['volatility_20d']:.1f}%")
        print(f"  SMA50/200:    {mkt['sma50']:.2f} / {mkt['sma200']:.2f}")

    sectors = get_latest_sector_regimes(SECTOR_BENCHMARKS)
    if sectors:
        print(f"\nSectores:")
        print(f"  {'ETF':<6} {'Sector':<26} {'Régimen':<10} {'Mom60':>7}  {'RS':>6}  {'DD52w':>7}")
        print(f"  {'-'*70}")
        for etf, row in sectors.items():
            print(
                f"  {etf:<6} {row['sector']:<26} {row['regime']:<10} "
                f"{(row['mom60'] or 0):>+6.1f}%  "
                f"{(row['rs_vs_spy'] or 0):>5.2f}x  "
                f"{(row['drawdown_52w'] or 0):>+6.1f}%"
            )

    print("\n[OK] Contexto actualizado.\n")


if __name__ == '__main__':
    main()
