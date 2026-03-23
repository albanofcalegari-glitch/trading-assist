"""
run_support_zones.py — ejecuta el detector de zonas de soporte

Uso:
    python scripts/run_support_zones.py
    python scripts/run_support_zones.py --symbol MSFT
    python scripts/run_support_zones.py --date 2026-03-21
    python scripts/run_support_zones.py --no-save
"""
import argparse
from datetime import date
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import UNIVERSE
from strategies.support_zones import analyze_symbol, run_universe, save_zones, ensure_table

_STATE_LABEL = {
    'NO_SUPPORT':               'SIN_SOPORTE   ',
    'SUPPORT_ZONE_DETECTED':    'DETECTADO     ',
    'SUPPORT_ZONE_RETESTED':    'RETESTEADO    ',
    'SUPPORT_HOLDING':          'RESPETADO     ',
    'SUPPORT_BROKEN':           'ROTO          ',
    'SUPPORT_BOUNCE_CONFIRMED': 'REBOTE_CONF.  ',
}

_STATE_ORDER = {
    'SUPPORT_BOUNCE_CONFIRMED': 0,
    'SUPPORT_HOLDING':          1,
    'SUPPORT_ZONE_RETESTED':    2,
    'SUPPORT_ZONE_DETECTED':    3,
    'SUPPORT_BROKEN':           4,
    'NO_SUPPORT':               5,
}


def print_results(results: list[dict]) -> None:
    if not results:
        print("Sin resultados.")
        return

    sorted_r = sorted(results, key=lambda r: _STATE_ORDER.get(r['state'], 9))

    hdr = (
        f"{'SIM':<6}  {'ESTADO':<14}  {'SOPORTE':>8}  {'ZONA':>18}  "
        f"{'TOQUES':>6}  {'DESV%':>6}  {'T1':<12}  {'T2':<12}  LECTURA"
    )
    sep = '-' * 130
    print()
    print(hdr)
    print(sep)

    for r in sorted_r:
        sym   = r['simbolo']
        state = _STATE_LABEL.get(r['state'], r['state'])[:14]
        sp    = f"${r['support_price']:.2f}" if r['support_price'] else '-'
        zl    = f"${r['zone_low']:.2f}"      if r['zone_low']      else '-'
        zh    = f"${r['zone_high']:.2f}"     if r['zone_high']     else '-'
        zona  = f"{zl} - {zh}"
        tq    = str(r['touches_count'])
        dv    = f"{r['deviation_pct']:+.1f}%" if r['deviation_pct'] is not None else '-'
        t1    = str(r['first_touch_date'])[:10]  if r['first_touch_date']  else '-'
        t2    = str(r['second_touch_date'])[:10] if r['second_touch_date'] else '-'
        read  = r['reading'][:60]

        print(
            f"{sym:<6}  {state:<14}  {sp:>8}  {zona:>18}  "
            f"{tq:>6}  {dv:>6}  {t1:<12}  {t2:<12}  {read}"
        )

    print(sep)
    detected  = sum(1 for r in results if r['state'] != 'NO_SUPPORT')
    retested  = sum(1 for r in results if r['state'] in ('SUPPORT_ZONE_RETESTED', 'SUPPORT_HOLDING', 'SUPPORT_BOUNCE_CONFIRMED'))
    confirmed = sum(1 for r in results if r['state'] == 'SUPPORT_BOUNCE_CONFIRMED')
    broken    = sum(1 for r in results if r['state'] == 'SUPPORT_BROKEN')
    print(
        f"  Detectados: {detected}  |  Retesteados: {retested}  |  "
        f"Confirmados: {confirmed}  |  Rotos: {broken}  |  Total: {len(results)}"
    )
    print()


def main():
    parser = argparse.ArgumentParser(description='Support Zones Detector')
    parser.add_argument('--date',    type=str,  default=None)
    parser.add_argument('--symbol',  type=str,  default=None)
    parser.add_argument('--no-save', action='store_true')
    args = parser.parse_args()

    fecha   = date.fromisoformat(args.date) if args.date else date.today()
    symbols = [args.symbol.upper()] if args.symbol else UNIVERSE

    print(f"\n=== Support Zones Detector | {fecha} | {len(symbols)} simbolo(s) ===\n")

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
        n = save_zones(results)
        print(f"  {n} zonas guardadas en support_zones.\n")
    else:
        print("  (modo --no-save: no se persistio en DB)\n")


if __name__ == '__main__':
    main()
