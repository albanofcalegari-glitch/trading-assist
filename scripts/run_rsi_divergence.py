"""
run_rsi_divergence.py -- ejecuta el motor de divergencias RSI sobre el universo

Uso:
    python scripts/run_rsi_divergence.py                     # hoy
    python scripts/run_rsi_divergence.py --date 2026-03-21   # fecha especifica
    python scripts/run_rsi_divergence.py --symbol MSFT        # un solo simbolo
    python scripts/run_rsi_divergence.py --no-save           # sin persistir en DB
"""
import argparse
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE
from strategies.rsi_divergence import (
    analyze_symbol, run_universe, save_signals, ensure_table
)

_STATE_ORDER = {
    'BULLISH_DIVERGENCE_CONFIRMED': 0,
    'BEARISH_DIVERGENCE_CONFIRMED': 1,
    'BULLISH_DIVERGENCE_FORMING':   2,
    'BEARISH_DIVERGENCE_FORMING':   3,
    'NO_DIVERGENCE':                4,
}

_STATE_LABEL = {
    'BULLISH_DIVERGENCE_CONFIRMED': 'ALCISTA CONF.',
    'BEARISH_DIVERGENCE_CONFIRMED': 'BAJISTA CONF.',
    'BULLISH_DIVERGENCE_FORMING':   'ALCISTA FORM.',
    'BEARISH_DIVERGENCE_FORMING':   'BAJISTA FORM.',
    'NO_DIVERGENCE':                'SIN DIV.     ',
}

_DEC_LABEL = {
    'BUY_CANDIDATE': '[COMPRAR] ',
    'WATCHLIST':     '[VIGILAR] ',
    'SELL_WARNING':  '[CUIDADO] ',
    'AVOID':         '[EVITAR]  ',
    'NONE':          '[NEUTRAL] ',
}

_CONF_LABEL = {
    'HIGH':   'ALTA  ',
    'MEDIUM': 'MEDIA ',
    'LOW':    'BAJA  ',
    None:     '---   ',
}


def print_results(results: list[dict]) -> None:
    sorted_r = sorted(results, key=lambda r: _STATE_ORDER.get(r['divergence_state'], 9))

    print()
    print(
        f"{'SIM':<6}  {'ESTADO':<14}  {'TIPO':<7}  "
        f"{'P1':>8}  {'P2':>8}  {'R1':>5}  {'R2':>5}  "
        f"{'CONF':<6}  {'DEC':<10}  {'T_P2':<12}  LECTURA"
    )
    print("-" * 130)

    for r in sorted_r:
        sym   = r['simbolo']
        state = _STATE_LABEL.get(r['divergence_state'], r['divergence_state'])
        dtype = r['divergence_type'] or '---'
        p1    = f"${r['price_pivot_1']:.2f}" if r['price_pivot_1'] else '---'
        p2    = f"${r['price_pivot_2']:.2f}" if r['price_pivot_2'] else '---'
        r1    = f"{r['rsi_pivot_1']:.1f}"    if r['rsi_pivot_1']   else '---'
        r2    = f"{r['rsi_pivot_2']:.1f}"    if r['rsi_pivot_2']   else '---'
        conf  = _CONF_LABEL.get(r['confidence_level'], '---')
        dec   = _DEC_LABEL.get(r['decision'], r['decision'])
        t2    = str(r['pivot_2_date'])[:10]  if r['pivot_2_date']  else '---'
        read  = r['reading'][:55]

        print(
            f"{sym:<6}  {state}  {dtype:<7}  "
            f"{p1:>8}  {p2:>8}  {r1:>5}  {r2:>5}  "
            f"{conf}  {dec}  {t2:<12}  {read}"
        )

    print("-" * 130)
    bull_c = sum(1 for r in results if r['divergence_state'] == 'BULLISH_DIVERGENCE_CONFIRMED')
    bear_c = sum(1 for r in results if r['divergence_state'] == 'BEARISH_DIVERGENCE_CONFIRMED')
    bull_f = sum(1 for r in results if r['divergence_state'] == 'BULLISH_DIVERGENCE_FORMING')
    bear_f = sum(1 for r in results if r['divergence_state'] == 'BEARISH_DIVERGENCE_FORMING')
    none_c = sum(1 for r in results if r['divergence_state'] == 'NO_DIVERGENCE')
    print(
        f"  Alcista conf: {bull_c}  |  Bajista conf: {bear_c}  |  "
        f"Alcista form: {bull_f}  |  Bajista form: {bear_f}  |  Sin div: {none_c}"
        f"  |  Total: {len(results)}"
    )
    print()

    # Detalle de senales accionables
    actionable = [r for r in sorted_r if r['divergence_state'] != 'NO_DIVERGENCE']
    if actionable:
        print("  Detalle de divergencias detectadas:")
        for r in actionable:
            sym   = r['simbolo']
            state = r['divergence_state']
            conf  = r['confidence_level'] or '---'
            dec   = r['decision']
            p1, p2 = r['price_pivot_1'], r['price_pivot_2']
            r1, r2 = r['rsi_pivot_1'],   r['rsi_pivot_2']
            t1  = str(r['pivot_1_date'])[:10] if r['pivot_1_date'] else '---'
            t2  = str(r['pivot_2_date'])[:10] if r['pivot_2_date'] else '---'
            print(f"    {sym}: {state} | conf={conf} | dec={dec}")
            if p1 and p2:
                arrow = 'v' if r['divergence_type'] == 'BULLISH' else '^'
                print(
                    f"      precio: ${p1:.2f} ({t1}) {arrow} ${p2:.2f} ({t2})"
                    f"  |  RSI: {r1:.1f} -> {r2:.1f}"
                )
            print(f"      {r['reading']}")
        print()


def main():
    parser = argparse.ArgumentParser(description='RSI Divergence Engine')
    parser.add_argument('--date',    type=str, default=None, help='Fecha YYYY-MM-DD (default: hoy)')
    parser.add_argument('--symbol',  type=str, default=None, help='Un solo simbolo')
    parser.add_argument('--no-save', action='store_true',    help='No persistir en DB')
    args = parser.parse_args()

    fecha   = date.fromisoformat(args.date) if args.date else date.today()
    symbols = [args.symbol.upper()] if args.symbol else UNIVERSE

    print(f"\n=== RSI Divergence Engine | {fecha} | {len(symbols)} simbolo(s) ===\n")

    ensure_table()

    if args.symbol:
        r       = analyze_symbol(args.symbol.upper(), fecha)
        results = [r] if r else []
    else:
        results = run_universe(symbols, fecha)

    if not results:
        print("Sin resultados. Verificar que load_history fue ejecutado.")
        return

    print_results(results)

    if not args.no_save:
        n = save_signals(results)
        print(f"  {n} senales guardadas en rsi_divergence_signals.\n")
    else:
        print("  (modo --no-save: no se persistio en DB)\n")


if __name__ == '__main__':
    main()
