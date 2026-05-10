"""
smh_correction_alert.py — Alerta Telegram de corrección en SMH
===============================================================
Monitorea SMH diariamente buscando oportunidades de entrada en pullback.

Señales que disparan alerta:
  1. PULLBACK_FORMING — corrección en curso, tendencia sana
  2. PULLBACK_VALID  — pullback maduro, potencial entrada
  3. Precio cerca de soporte dinámico (TESTING status)
  4. Drawdown significativo desde pico reciente (>5%)

Diseñado para correr como cron post-cierre (ej: 21:30 UTC L-V).

Uso:
  python scripts/smh_correction_alert.py            # evalúa y envía si hay señal
  python scripts/smh_correction_alert.py --dry-run  # imprime sin enviar
  python scripts/smh_correction_alert.py --force     # envía aunque no haya señal
"""
import sys, os, argparse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from datetime import date
from db.connection import get_conn
from strategies.trend_pullback import analyze_symbol
from strategies.dynamic_supports import get_dynamic_supports
from batches.notifier import make_default_notifier

SYMBOL = 'SMH'

DRAWDOWN_ALERT_PCT = -5.0
ALERT_STATES = ('PULLBACK_FORMING', 'PULLBACK_VALID')


def _get_peak_and_drawdown(symbol: str, lookback: int = 60) -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT fecha, high, close
                FROM price_history
                WHERE simbolo = %s
                ORDER BY fecha DESC LIMIT %s
            ''', (symbol, lookback))
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {}

    current = rows[0]
    price = float(current['close'])
    peak_high = max(float(r['high']) for r in rows)
    peak_row = next(r for r in rows if float(r['high']) == peak_high)
    drawdown_pct = (price / peak_high - 1) * 100

    return {
        'price': price,
        'peak_high': peak_high,
        'peak_date': str(peak_row['fecha']),
        'drawdown_pct': round(drawdown_pct, 2),
        'current_date': str(current['fecha']),
    }


def _get_support_info(symbol: str) -> dict:
    try:
        sup = get_dynamic_supports(symbol, tf='D')
    except Exception:
        return {}

    info = {'tiers': {}}
    for tier in ('long', 'mid', 'short'):
        s = sup.get(tier)
        if not s:
            continue
        info['tiers'][tier] = {
            'value': s['current_value'],
            'distance_pct': s['distance_pct'],
            'status': s['status'],
            'touches': s['touches'],
            'kind': s.get('kind', '?'),
        }
    return info


def evaluate() -> dict:
    hoy = date.today()

    tp = analyze_symbol(SYMBOL, hoy)
    peak = _get_peak_and_drawdown(SYMBOL)
    supports = _get_support_info(SYMBOL)

    should_alert = False
    reasons = []

    if tp:
        state = tp['setup_state']
        if state in ALERT_STATES:
            should_alert = True
            reasons.append(f'Estado: {state}')
        if tp['decision'] == 'BUY_CANDIDATE':
            should_alert = True
            reasons.append('Decisión: BUY_CANDIDATE')

    if peak:
        dd = peak['drawdown_pct']
        if dd <= DRAWDOWN_ALERT_PCT:
            should_alert = True
            reasons.append(f'Drawdown: {dd:.1f}% desde máx ${peak["peak_high"]:.2f}')

    testing_tiers = []
    for tier, info in supports.get('tiers', {}).items():
        if info['status'] == 'TESTING':
            should_alert = True
            testing_tiers.append(tier)
    if testing_tiers:
        reasons.append(f'Soporte TESTING: {", ".join(testing_tiers)}')

    return {
        'should_alert': should_alert,
        'reasons': reasons,
        'trend_pullback': tp,
        'peak': peak,
        'supports': supports,
        'fecha': hoy,
    }


def format_message(ev: dict) -> str:
    tp = ev['trend_pullback']
    peak = ev['peak']
    supports = ev['supports']
    fecha = ev['fecha']

    lines = [f'SMH Correccion Alert ({fecha})', '']

    if ev['reasons']:
        lines.append('SEÑALES:')
        for r in ev['reasons']:
            lines.append(f'  > {r}')
        lines.append('')

    if tp:
        lines.append('TREND PULLBACK:')
        lines.append(f'  Precio:    ${tp["price"]:.2f}')
        lines.append(f'  Estado:    {tp["setup_state"]}')
        lines.append(f'  Decision:  {tp["decision"]} [{tp["confidence_level"]}]')
        lines.append(f'  Trend:     {tp["trend_score"]:.0f}/10')
        lines.append(f'  Pullback:  {tp["pullback_score"]:.0f}/10')
        if tp.get('mom20') is not None:
            lines.append(f'  Mom20:     {tp["mom20"]:+.2f}%')
        if tp.get('mom60') is not None:
            lines.append(f'  Mom60:     {tp["mom60"]:+.2f}%')
        if tp.get('rsi14') is not None:
            lines.append(f'  RSI14:     {tp["rsi14"]:.1f}')
        lines.append(f'  Contexto:  {tp["context_alignment"]}')
        lines.append(f'  Lectura:   {tp["reading"]}')
        lines.append('')

    if peak:
        lines.append('DRAWDOWN:')
        lines.append(f'  Precio:    ${peak["price"]:.2f}')
        lines.append(f'  Maximo:    ${peak["peak_high"]:.2f} ({peak["peak_date"]})')
        lines.append(f'  Caida:     {peak["drawdown_pct"]:+.1f}%')
        lines.append('')

    if supports.get('tiers'):
        lines.append('SOPORTES DINAMICOS:')
        for tier, info in supports['tiers'].items():
            emoji = 'TESTING' if info['status'] == 'TESTING' else info['status']
            lines.append(
                f'  {tier:5s}: ${info["value"]:.2f}  '
                f'({info["distance_pct"]:+.1f}%)  '
                f'[{emoji}] {info["touches"]}t {info["kind"]}'
            )
        lines.append('')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true', help='Enviar aunque no haya señal')
    args = parser.parse_args()

    print(f'=== SMH Correction Alert — {date.today()} ===')

    ev = evaluate()

    if not ev['trend_pullback']:
        print('ERROR: no se pudo analizar SMH (datos insuficientes)')
        return

    msg = format_message(ev)
    print(f'\n{msg}')

    if ev['should_alert'] or args.force:
        print('--- ALERTA ACTIVA ---')
        if not args.dry_run:
            notifier = make_default_notifier()
            notifier.notify('smh_correction', 'SMH Correccion', msg, {})
            print('Telegram enviado.')
        else:
            print('(dry-run, no se envio)')
    else:
        print('Sin señal de corrección hoy — no se envía alerta.')


if __name__ == '__main__':
    main()
