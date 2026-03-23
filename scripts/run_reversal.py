"""
run_reversal.py — ejecuta el motor Reversal sobre el universo

Uso:
    python scripts/run_reversal.py                     # hoy
    python scripts/run_reversal.py --date 2026-03-21   # fecha especifica
    python scripts/run_reversal.py --symbol GOOGL      # un solo simbolo
    python scripts/run_reversal.py --no-save           # sin persistir en DB
    python scripts/run_reversal.py --debug             # muestra detalle de scores
    python scripts/run_reversal.py --debug --symbol NVDA  # debug de un activo
"""
import argparse
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE
from strategies.reversal import (
    analyze_symbol, run_universe, save_signals, ensure_table
)

# ── Labels para salida por consola ────────────────────────────────────────────

_DEC_ORDER = {'BUY_CANDIDATE': 0, 'WATCHLIST': 1, 'AVOID': 2}

_PAT_LABEL = {
    'NO_PATTERN':               'SIN_PATRON     ',
    'OVERSOLD_ONLY':            'SOBREVENDIDO   ',
    'FLOOR_FORMING':            'PISO_FORMANDO  ',
    'DOUBLE_BOTTOM_FORMING':    'DB_FORMING     ',
    'DOUBLE_BOTTOM_CONFIRMED':  'DB_CONFIRMED   ',
    'HIGHER_LOW_UPTREND':       'HIGHER_LOW_UPT ',
    'BEAR_MARKET_FAKE_REVERSAL':'FAKE_REVERSAL  ',
    'BREAKDOWN_ACTIVE':         'BREAKDOWN_ACTV.',
}

_DEC_LABEL = {
    'BUY_CANDIDATE': '[COMPRAR] ',
    'WATCHLIST':     '[VIGILAR] ',
    'AVOID':         '[EVITAR]  ',
}

_MKT_LABEL = {
    'favorable':   'FAVOR. ',
    'neutral':     'NEUTR. ',
    'unfavorable': 'DESFAV.',
}

_SECT_LABEL = {
    'strong':  'FUERTE ',
    'neutral': 'NEUTR. ',
    'weak':    'DEBIL  ',
}

_OV_LABEL = {
    'favorable':   'FAVOR. ',
    'neutral':     'NEUTR. ',
    'unfavorable': 'DESFAV.',
}


# ── Impresión de resultados ───────────────────────────────────────────────────

def print_results(results: list[dict], debug: bool = False) -> None:
    if not results:
        print("Sin resultados.")
        return

    sorted_r = sorted(results, key=lambda r: (
        _DEC_ORDER.get(r['decision'], 9),
        -r['reversal_score'],
    ))

    hdr = (
        f"{'SIM':<6}  {'PATRON':<15}  {'SCORE':>5}  "
        f"{'MKT':<7}  {'SECT':<7}  {'OVR':<7}  "
        f"{'DECISION':<10}  {'CONF':<6}  {'TRD'}  LECTURA"
    )
    sep = '-' * 115

    print()
    print(hdr)
    print(sep)

    for r in sorted_r:
        sym   = r['simbolo']
        pat   = _PAT_LABEL.get(r['pattern_state'], r['pattern_state'])[:15]
        score = r['reversal_score']
        mkt   = _MKT_LABEL.get(r['market_alignment'],  r['market_alignment'])[:7]
        sect  = _SECT_LABEL.get(r['sector_alignment'],  r['sector_alignment'])[:7]
        ov    = _OV_LABEL.get(r['overall_context'],     r['overall_context'])[:7]
        dec   = _DEC_LABEL.get(r['decision'], r['decision'])
        conf  = r['confidence_level'][:6]
        trd   = 'SI ' if r['allow_trade'] else 'NO '
        read  = r['reading'][:55]

        print(
            f"{sym:<6}  {pat:<15}  {score:>5.1f}  "
            f"{mkt:<7}  {sect:<7}  {ov:<7}  "
            f"{dec:<10}  {conf:<6}  {trd}  {read}"
        )

        if debug:
            sd  = r.get('_score_det', {})
            pd  = r.get('_pattern_det', {})
            ctx = r.get('_ctx', {})
            vs  = r.get('vs_peak_60')

            print(
                f"         Score det:  rsi={sd.get('rsi',0):.1f}  "
                f"vol={sd.get('volume',0):.1f}  "
                f"mom={sd.get('momentum',0):.1f}  "
                f"pat={sd.get('pattern',0):.1f}  "
                f"stab={sd.get('stabilization',0):.1f}"
            )
            rsi_s  = f"{r['rsi14']:.1f}"   if r.get('rsi14')    else '—'
            volr_s = f"{r['vol_ratio']:.2f}" if r.get('vol_ratio') else '—'
            vs_s   = f"{vs:.1f}"             if vs               else '—'
            print(
                f"         Indicadores: "
                f"RSI={rsi_s}  "
                f"mom20={r.get('mom20') or 0:>+6.1f}%  "
                f"mom60={r.get('mom60') or 0:>+6.1f}%  "
                f"volR={volr_s}  "
                f"vsPeak60={vs_s}"
            )
            print(
                f"         Precios:  "
                f"${r.get('price',0):.2f}  "
                f"EMA20=${r.get('ema20') or 0:.2f}  "
                f"SMA50=${r.get('sma50') or 0:.2f}  "
                f"SMA200=${r.get('sma200') or 0:.2f}"
            )
            print(
                f"         Contexto: "
                f"Mercado={ctx.get('market_regime','?')}  "
                f"Sector={ctx.get('sector_regime','?')} ({ctx.get('sector','?')})"
            )
            if pd:
                print(f"         PatDet: {pd}")
            print()

    print(sep)
    buy   = sum(1 for r in results if r['decision'] == 'BUY_CANDIDATE')
    watch = sum(1 for r in results if r['decision'] == 'WATCHLIST')
    avoid = sum(1 for r in results if r['decision'] == 'AVOID')
    trade = sum(1 for r in results if r['allow_trade'])
    print(
        f"  Comprar: {buy}  |  Vigilar: {watch}  |  "
        f"Evitar: {avoid}  |  Con trade: {trade}  |  Total: {len(results)}"
    )
    print()


def main():
    parser = argparse.ArgumentParser(description='Reversal Engine')
    parser.add_argument('--date',    type=str,  default=None, help='Fecha YYYY-MM-DD')
    parser.add_argument('--symbol',  type=str,  default=None, help='Un solo simbolo')
    parser.add_argument('--no-save', action='store_true',     help='No persistir en DB')
    parser.add_argument('--debug',   action='store_true',     help='Mostrar detalle de scores')
    args = parser.parse_args()

    fecha   = date.fromisoformat(args.date) if args.date else date.today()
    symbols = [args.symbol.upper()] if args.symbol else UNIVERSE

    print(f"\n=== Reversal Engine | {fecha} | {len(symbols)} simbolo(s) ===\n")

    ensure_table()

    if args.symbol:
        r       = analyze_symbol(args.symbol.upper(), fecha)
        results = [r] if r else []
    else:
        results = run_universe(symbols, fecha)

    if not results:
        print("Sin resultados. Verificar que load_history y run_context fueron ejecutados.")
        return

    print_results(results, debug=args.debug)

    if not args.no_save:
        n = save_signals(results)
        print(f"  {n} senales guardadas en reversal_signals.\n")
    else:
        print("  (modo --no-save: no se persistio en DB)\n")


if __name__ == '__main__':
    main()
