"""
run_trend_pullback.py — ejecuta el motor Trend+Pullback sobre el universo

Uso:
    python scripts/run_trend_pullback.py                     # hoy
    python scripts/run_trend_pullback.py --date 2026-03-20   # fecha especifica
    python scripts/run_trend_pullback.py --symbol MSFT        # un solo simbolo
    python scripts/run_trend_pullback.py --no-save           # sin persistir en DB
    python scripts/run_trend_pullback.py --debug             # muestra detalle de scores
"""
import argparse
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE
from strategies.trend_pullback import (
    analyze_symbol, run_universe, save_signals, ensure_table
)

# Orden de prioridad de decisiones para la tabla de salida
_DEC_ORDER = {
    'BUY_CANDIDATE': 0,
    'WATCHLIST':     1,
    'NO_ACTION':     2,
    'AVOID':         3,
}

_STATE_LABEL = {
    'PULLBACK_VALID':   'PULLBACK VALIDO',
    'PULLBACK_FORMING': 'PULLBACK FORM. ',
    'TREND_HEALTHY':    'TENDENCIA SANA ',
    'TREND_BROKEN':     'TEND. ROTA     ',
    'NO_SETUP':         'SIN SETUP      ',
}

_DEC_LABEL = {
    'BUY_CANDIDATE': '[COMPRAR]  ',
    'WATCHLIST':     '[VIGILAR]  ',
    'NO_ACTION':     '[ESPERAR]  ',
    'AVOID':         '[EVITAR]   ',
}

_CONF_LABEL = {
    'HIGH':   'ALTA  ',
    'MEDIUM': 'MEDIA ',
    'LOW':    'BAJA  ',
}

_ALIGN_LABEL = {
    'favorable':   'FAVOR.',
    'neutral':     'NEUTR.',
    'unfavorable': 'DESFAV',
}


def print_results(results: list[dict], debug: bool = False) -> None:
    if not results:
        print("Sin resultados.")
        return

    sorted_r = sorted(results, key=lambda r: (
        _DEC_ORDER.get(r['decision'], 9),
        -r['trend_score'],
        -r['pullback_score'],
    ))

    # Cabecera
    print()
    print(f"{'SIM':<6}  {'TREND':>5}  {'PULL':>5}  {'ESTADO':<15}  {'CTX':<6}  "
          f"{'CONF':<6}  {'DECISION':<11}  {'LECT'}")
    print("-" * 100)

    for r in sorted_r:
        sym   = r['simbolo']
        ts    = r['trend_score']
        ps    = r['pullback_score']
        state = _STATE_LABEL.get(r['setup_state'], r['setup_state'])
        ctx   = _ALIGN_LABEL.get(r['context_alignment'], r['context_alignment'])
        conf  = _CONF_LABEL.get(r['confidence_level'], r['confidence_level'])
        dec   = _DEC_LABEL.get(r['decision'], r['decision'])
        read  = r['reading']

        print(f"{sym:<6}  {ts:>5.1f}  {ps:>5.1f}  {state}  {ctx}  {conf}  {dec}  {read}")

        if debug:
            ctx_m = r.get('_ctx', {})
            td    = r.get('_trend_det', {})
            pd    = r.get('_pull_det',  {})
            print(f"         Price={r['price']:.2f}  EMA20={r.get('ema20') or '—':>8}  "
                  f"SMA50={r.get('sma50') or '—':>8}  SMA200={r.get('sma200') or '—':>8}")
            print(f"         RSI={r.get('rsi14') or '—':>5}  "
                  f"mom20={r.get('mom20') or '—':>+6.1f}%  "
                  f"mom60={r.get('mom60') or '—':>+6.1f}%  "
                  f"volR={r.get('vol_ratio') or '—':>4}")
            print(f"         Mercado={ctx_m.get('market_regime','?')}  "
                  f"Sector={ctx_m.get('sector_regime','?')} ({ctx_m.get('sector','?')})")
            print(f"         TrendDet={td}  PullDet={pd}")
            print()

    print("-" * 100)
    # Resumen
    buy   = sum(1 for r in results if r['decision'] == 'BUY_CANDIDATE')
    watch = sum(1 for r in results if r['decision'] == 'WATCHLIST')
    avoid = sum(1 for r in results if r['decision'] == 'AVOID')
    print(f"  Comprar: {buy}  |  Vigilar: {watch}  |  Evitar: {avoid}  |  Total: {len(results)}")
    print()


def main():
    parser = argparse.ArgumentParser(description='Trend+Pullback Engine')
    parser.add_argument('--date',   type=str, default=None, help='Fecha YYYY-MM-DD (default: hoy)')
    parser.add_argument('--symbol', type=str, default=None, help='Un solo simbolo')
    parser.add_argument('--no-save', action='store_true', help='No persistir en DB')
    parser.add_argument('--debug',  action='store_true', help='Mostrar detalle de scores')
    args = parser.parse_args()

    fecha = date.fromisoformat(args.date) if args.date else date.today()
    symbols = [args.symbol.upper()] if args.symbol else UNIVERSE

    print(f"\n=== Trend+Pullback Engine | {fecha} | {len(symbols)} simbolo(s) ===\n")

    # Asegurar que la tabla existe
    ensure_table()

    if args.symbol:
        r = analyze_symbol(args.symbol.upper(), fecha)
        results = [r] if r else []
    else:
        results = run_universe(symbols, fecha)

    if not results:
        print("Sin resultados. Verificar que load_history y run_context fueron ejecutados.")
        return

    print_results(results, debug=args.debug)

    if not args.no_save:
        n = save_signals(results)
        print(f"  {n} señales guardadas en trend_pullback_signals.\n")
    else:
        print("  (modo --no-save: no se persistio en DB)\n")


if __name__ == '__main__':
    main()
