"""
strategies.rotation_compare — Comparativo entre variantes del backtest V2.

Corre el mismo período sobre varias configuraciones y muestra una tabla
con total_return, CAGR, max_drawdown, Sharpe, rotaciones y outperformance
vs SPY. Sirve para decidir qué variante vale la pena llevar a producto.

Uso:
    python -m strategies.rotation_compare
    python -m strategies.rotation_compare 2024-09-01 2025-04-01
    python -m strategies.rotation_compare 2024-09-01 2025-04-01 --max-universe 300
"""
from __future__ import annotations

import argparse
import sys
import os
from datetime import date, datetime, timedelta

# Forzar stdout UTF-8 (Windows usa cp1252 por default)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from strategies.rotation import RotationBacktest, DEFAULT_INITIAL_CAPITAL


# Variantes a comparar — pensadas para responder:
#   ¿el filtro de régimen ayuda? ¿menos churn ayuda? ¿top-K diversifica mejor?
VARIANTS = [
    {
        'name': 'Base V1 (top1, sin régimen)',
        'params': dict(mode='top1',       top_keep=5,  rotate_diff=8.0,
                       regime_filter=False,
                       min_price=5.0,  min_avg_vol=500_000),
    },
    {
        'name': 'Régimen only',
        'params': dict(mode='top1',       top_keep=5,  rotate_diff=8.0,
                       regime_filter=True,
                       min_price=5.0,  min_avg_vol=500_000),
    },
    {
        'name': 'Régimen + diff=15',
        'params': dict(mode='top1',       top_keep=5,  rotate_diff=15.0,
                       regime_filter=True,
                       min_price=5.0,  min_avg_vol=500_000),
    },
    {
        'name': 'Régimen + top10 + diff=15',
        'params': dict(mode='top1',       top_keep=10, rotate_diff=15.0,
                       regime_filter=True,
                       min_price=10.0, min_avg_vol=1_000_000),
    },
    {
        'name': 'Top3 equal + régimen',
        'params': dict(mode='top3_equal', top_keep=10, rotate_diff=15.0,
                       regime_filter=True,
                       min_price=10.0, min_avg_vol=1_000_000),
    },
]


def run_compare(start: date | None, end: date | None,
                max_universe: int = 300) -> list[dict]:
    end   = end   or date.today()
    start = start or (end - timedelta(days=365))

    print(f'\nComparando {len(VARIANTS)} variantes  ({start} → {end})')
    print(f'Universo (max): {max_universe}\n')

    rows: list[dict] = []
    for v in VARIANTS:
        bt = RotationBacktest(max_universe=max_universe, **v['params'])
        try:
            result = bt.run(start, end)
        except Exception as e:
            print(f'  [ERROR] {v["name"]}: {e}')
            continue
        s = result['summary']
        m = result['metrics']
        rows.append({
            'name':         v['name'],
            'total_return': m['total_return'] * 100,
            'cagr':         m['cagr'] * 100,
            'max_dd':       m['max_drawdown'] * 100,
            'sharpe':       m['sharpe'],
            'rotations':    m['rotations_count'],
            'final_eq':     s['final_equity'],
            'spy_eq':       s['final_spy_equity'],
            'outperf':      s['outperformance_pct'],
        })
        print(f'  ✓ {v["name"]}')

    print()
    if not rows:
        print('Sin resultados.')
        return rows

    # ─── Tabla ──────────────────────────────────────────────────────────────
    hdr = (f"{'Variant':<32}{'TotRet%':>10}{'CAGR%':>9}{'MaxDD%':>9}"
           f"{'Sharpe':>8}{'Rot':>5}{'Final$':>12}{'vs SPY%':>11}")
    print(hdr)
    print('─' * len(hdr))
    for r in rows:
        print(f"{r['name']:<32}"
              f"{r['total_return']:>+10.2f}"
              f"{r['cagr']:>+9.2f}"
              f"{r['max_dd']:>9.2f}"
              f"{r['sharpe']:>8.2f}"
              f"{r['rotations']:>5}"
              f"{r['final_eq']:>12,.0f}"
              f"{r['outperf']:>+11.2f}")
    print('─' * len(hdr))
    spy_final = rows[0]['spy_eq']
    spy_ret   = (spy_final / DEFAULT_INITIAL_CAPITAL - 1) * 100
    print(f"{'SPY buy & hold':<32}"
          f"{spy_ret:>+10.2f}"
          f"{'':>9}{'':>9}{'':>8}{'':>5}"
          f"{spy_final:>12,.0f}{'':>11}")
    print()

    # ─── Veredicto ──────────────────────────────────────────────────────────
    best = max(rows, key=lambda r: r['outperf'])
    beats_spy = [r for r in rows if r['outperf'] > 0]
    print(f'Mejor outperformance vs SPY: {best["name"]}  ({best["outperf"]:+.2f}%)')
    if beats_spy:
        print(f'Variantes que superan a SPY: {len(beats_spy)} / {len(rows)}')
        for r in beats_spy:
            print(f'   • {r["name"]}  ({r["outperf"]:+.2f}%)')
    else:
        print('Ninguna variante supera a SPY en este período.')
    print()
    return rows


def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def main() -> int:
    p = argparse.ArgumentParser(description='Comparativo de variantes de rotation backtest')
    p.add_argument('start', nargs='?', type=_parse_date, default=None)
    p.add_argument('end',   nargs='?', type=_parse_date, default=None)
    p.add_argument('--max-universe', type=int, default=300)
    args = p.parse_args()
    run_compare(args.start, args.end, args.max_universe)
    return 0


if __name__ == '__main__':
    sys.exit(main())
