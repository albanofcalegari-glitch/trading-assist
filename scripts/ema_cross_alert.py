"""
ema_cross_alert.py — Alerta diaria de cruces EMA50/EMA200
==========================================================
Escanea todos los activos con historia suficiente y alerta por Telegram
cuando detecta golden cross, death cross o proximidad al cruce.

Diseñado para correr como cron post-cierre (ej: 21:55 UTC L-V).

Uso:
  python scripts/ema_cross_alert.py            # escanea y envía
  python scripts/ema_cross_alert.py --dry-run  # imprime sin enviar
"""
import sys, os, argparse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from datetime import date
from db.connection import get_conn
from strategies.ema_cross import scan_universe
from batches.notifier import make_default_notifier

MIN_WEEKLY_BARS = 200


def _get_symbols() -> list[str]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT simbolo FROM ohlcv_extended
                WHERE timeframe = 'W'
                GROUP BY simbolo
                HAVING COUNT(*) >= %s
                ORDER BY simbolo
            ''', (MIN_WEEKLY_BARS,))
            return [r['simbolo'] for r in cur.fetchall()]
    finally:
        conn.close()


SIGNAL_PRIORITY = {
    'GOLDEN_CROSS': 0,
    'DEATH_CROSS': 1,
    'APPROACHING_GOLDEN': 2,
    'APPROACHING_DEATH': 3,
}

SIGNAL_LABEL = {
    'GOLDEN_CROSS': 'GOLDEN CROSS (EMA50 cruzo arriba de EMA200)',
    'DEATH_CROSS': 'DEATH CROSS (EMA50 cruzo abajo de EMA200)',
    'APPROACHING_GOLDEN': 'Acercandose a Golden Cross',
    'APPROACHING_DEATH': 'Acercandose a Death Cross',
}


MAX_APPROACHING = 10


def format_message(results: list[dict], fecha: date) -> str:
    lines = [f'EMA Cross Alert ({fecha})', '']

    grouped: dict[str, list[dict]] = {}
    for r in results:
        sig = r['signal']
        grouped.setdefault(sig, []).append(r)

    for sig in sorted(grouped.keys(), key=lambda s: SIGNAL_PRIORITY.get(s, 99)):
        items = grouped[sig]
        items.sort(key=lambda x: abs(x['gap_pct']))
        is_approaching = 'APPROACHING' in sig
        show = items[:MAX_APPROACHING] if is_approaching else items[:20]
        lines.append(f'{SIGNAL_LABEL.get(sig, sig)} ({len(items)}):')
        for r in show:
            mom_str = ''
            if r.get('mom20') is not None:
                mom_str = f' m20={r["mom20"]:+.1f}%'
            if r.get('mom60') is not None:
                mom_str += f' m60={r["mom60"]:+.1f}%'
            rsi_str = f' RSI={r["rsi14"]:.0f}' if r.get('rsi14') else ''
            lines.append(
                f'  {r["simbolo"]:6s} ${r["price"]:>8.2f}  '
                f'E50=${r["ema50"]:.2f} E200=${r["ema200"]:.2f} '
                f'({r["gap_pct"]:+.2f}%)'
                f'{rsi_str}{mom_str}'
            )
        if len(items) > len(show):
            lines.append(f'  ... y {len(items) - len(show)} mas')
        lines.append('')

    if not results:
        lines.append('Sin cruces EMA50/EMA200 hoy.')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    hoy = date.today()
    print(f'=== EMA Cross Alert — {hoy} ===')

    symbols = _get_symbols()
    print(f'Symbols to scan: {len(symbols)}')

    results = scan_universe(symbols, hoy)
    results.sort(key=lambda r: SIGNAL_PRIORITY.get(r['signal'], 99))

    golden = [r for r in results if r['signal'] == 'GOLDEN_CROSS']
    death = [r for r in results if r['signal'] == 'DEATH_CROSS']
    app_g = [r for r in results if r['signal'] == 'APPROACHING_GOLDEN']
    app_d = [r for r in results if r['signal'] == 'APPROACHING_DEATH']

    print(f'\nResultados:')
    print(f'  Golden Cross:        {len(golden)}')
    print(f'  Death Cross:         {len(death)}')
    print(f'  Approaching Golden:  {len(app_g)}')
    print(f'  Approaching Death:   {len(app_d)}')

    has_cross = bool(golden or death)

    if has_cross or app_g or app_d:
        msg = format_message(results, hoy)
        print(f'\n--- Telegram ---\n{msg}\n---')

        if not args.dry_run:
            notifier = make_default_notifier()
            notifier.notify('ema_cross', 'EMA Cross Alert', msg, {})
            print('Telegram enviado.')
        else:
            print('(dry-run, no se envio)')
    else:
        print('\nSin cruces hoy.')


if __name__ == '__main__':
    main()
