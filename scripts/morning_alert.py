"""
morning_alert.py — Pipeline de apertura + alerta Telegram
==========================================================
Orden de ejecución:
  1. Actualización de precios  (load_history --update)
  2. Contexto de mercado       (run_context)
  3. Estrategias corto plazo   (WMA cross + reversal + support zones)
  4. Señales de compra         (trend pullback + BUY_CONFIRMATION scan)
  5. Envío Telegram

Uso:
  python scripts/morning_alert.py            # ejecuta todo y envía
  python scripts/morning_alert.py --dry-run  # imprime sin enviar
"""

import sys, os, argparse
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from datetime import date
import requests

from config import UNIVERSE, MARKET_BENCHMARK, SECTOR_BENCHMARKS, SECTOR_MAP
from data.data_loader import update_prices_daily
from context.market_regime  import run_market_regime,  get_latest_regime
from context.sector_regime  import run_sector_regime,  get_latest_sector_regimes
from strategies.trend_pullback import run_universe as run_trend_pullback
from strategies.reversal       import run_universe as run_reversal
from strategies.support_zones  import run_universe as run_support_zones
from backfill_history import backfill_symbol, ensure_table, _ALL_SYMBOLS

# ── Credenciales Telegram (mismas que morning_scan.py de finanzas_personales) ──
TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN',  '8254793386:AAExpnwxEpnWqDqyJmRsN9MZmE3lea6_lis')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID',   '-1003654041356')

REGIME_EMOJI = {1: 'verde', 0: 'amarillo', 2: 'rojo', None: 'blanco'}
REGIME_LABEL = {1: 'Alcista', 0: 'Lateral', 2: 'Bajista', None: 'Sin datos'}


# =============================================================================
#  PASO 1 — Actualizar precios
# =============================================================================
def step_update_prices():
    print('\n[1/5] Actualizando precios...')
    try:
        update_prices_daily(
            universe=UNIVERSE,
            market_benchmark=MARKET_BENCHMARK,
            sector_benchmarks=SECTOR_BENCHMARKS,
            sector_map=SECTOR_MAP,
        )
        print('  OK')
    except Exception as e:
        print(f'  ERROR: {e}')


# =============================================================================
#  PASO 1b — Actualizar ohlcv_extended (datos faltantes)
# =============================================================================
def step_update_ohlcv_extended():
    print('\n[1b/5] Actualizando ohlcv_extended...')
    try:
        ensure_table()
        updated = 0
        for sym in _ALL_SYMBOLS:
            for tf in ['D', 'W', 'M']:
                r = backfill_symbol(sym, tf, update_only=True)
                if not r.get('skipped'):
                    updated += r.get('inserted', 0) + r.get('updated', 0)
        print(f'  OK — {updated} registros actualizados')
    except Exception as e:
        print(f'  ERROR: {e}')


# =============================================================================
#  PASO 2 — Contexto de mercado
# =============================================================================
def step_context():
    print('\n[2/5] Calculando contexto...')
    try:
        run_market_regime(symbol=MARKET_BENCHMARK)
        run_sector_regime(sector_benchmarks=SECTOR_BENCHMARKS)
        print('  OK')
    except Exception as e:
        print(f'  ERROR contexto: {e}')


# =============================================================================
#  PASO 3 — Estrategias corto plazo
# =============================================================================
def step_short_term(hoy: date) -> dict:
    """
    Corre reversal y support_zones.
    Devuelve dict con listas de señales agrupadas por decision.
    """
    print('\n[3/5] Estrategias corto plazo...')
    result = {'reversal': [], 'support': []}

    try:
        rev = run_reversal(UNIVERSE, hoy)
        result['reversal'] = [r for r in rev if r.get('decision') in ('BUY_CANDIDATE', 'WATCHLIST')]
        print(f'  Reversal: {len(result["reversal"])} señales relevantes')
    except Exception as e:
        print(f'  Reversal ERROR: {e}')

    try:
        sup = run_support_zones(UNIVERSE, hoy)
        result['support'] = [r for r in sup if r.get('decision') in ('BUY_CANDIDATE', 'WATCHLIST')]
        print(f'  Support Zones: {len(result["support"])} señales relevantes')
    except Exception as e:
        print(f'  Support Zones ERROR: {e}')

    return result


# =============================================================================
#  PASO 4 — Señales de compra
# =============================================================================
def step_buy_signals(hoy: date) -> list[dict]:
    """
    Corre trend_pullback. Devuelve candidatos ordenados por prioridad.
    """
    print('\n[4/5] Señales de compra (Trend Pullback)...')
    try:
        res = run_trend_pullback(UNIVERSE, hoy)
        # Ordenar: BUY_CANDIDATE primero, luego WATCHLIST
        priority = {'BUY_CANDIDATE': 0, 'WATCHLIST': 1, 'NO_ACTION': 2, 'AVOID': 3}
        candidates = [r for r in res if r.get('decision') in ('BUY_CANDIDATE', 'WATCHLIST')]
        candidates.sort(key=lambda x: (priority.get(x['decision'], 9), -(x.get('trend_score') or 0)))
        print(f'  {len(candidates)} candidatos encontrados')
        return candidates
    except Exception as e:
        print(f'  Trend Pullback ERROR: {e}')
        return []


# =============================================================================
#  PASO 5 — Armar y enviar mensaje Telegram
# =============================================================================
def _regime_line(mkt: dict | None) -> str:
    if not mkt:
        return 'Mercado: sin datos'
    reg   = mkt.get('regime')
    label = REGIME_LABEL.get(reg, str(reg))
    mom20 = mkt.get('mom20') or 0
    mom60 = mkt.get('mom60') or 0
    vol   = mkt.get('volatility_20d') or 0
    return f'Mercado (SPY): {label}  |  Mom20: {mom20:+.1f}%  Mom60: {mom60:+.1f}%  Vol: {vol:.1f}%'


def _sector_lines(sectors: dict) -> str:
    if not sectors:
        return ''
    lines = []
    for etf, row in sectors.items():
        label = REGIME_LABEL.get(row.get('regime'), '?')
        rs    = row.get('rs_vs_spy') or 0
        mom60 = row.get('mom60') or 0
        lines.append(f'  {etf:<5} {label:<8}  rs={rs:.2f}x  mom60={mom60:+.1f}%')
    return '\n'.join(lines)


def _short_term_lines(short: dict) -> str:
    lines = []

    # Reversal
    buys = [r for r in short['reversal'] if r.get('decision') == 'BUY_CANDIDATE']
    watch = [r for r in short['reversal'] if r.get('decision') == 'WATCHLIST']
    if buys:
        syms = ', '.join(r['simbolo'] for r in buys[:5])
        lines.append(f'  [COMPRAR] Reversal: {syms}')
    if watch:
        syms = ', '.join(r['simbolo'] for r in watch[:3])
        lines.append(f'  [VIGILAR] Reversal: {syms}')

    # Support Zones
    buys_s  = [r for r in short['support'] if r.get('decision') == 'BUY_CANDIDATE']
    watch_s = [r for r in short['support'] if r.get('decision') == 'WATCHLIST']
    if buys_s:
        syms = ', '.join(r['simbolo'] for r in buys_s[:5])
        lines.append(f'  [COMPRAR] Soporte: {syms}')
    if watch_s:
        syms = ', '.join(r['simbolo'] for r in watch_s[:3])
        lines.append(f'  [VIGILAR] Soporte: {syms}')

    return '\n'.join(lines) if lines else '  Sin señales de corto plazo'


def _buy_signal_lines(candidates: list[dict]) -> str:
    if not candidates:
        return '  Sin candidatos de compra hoy'
    lines = []
    for r in candidates[:5]:
        sym   = r['simbolo']
        dec   = r['decision']
        ts    = r.get('trend_score') or 0
        ps    = r.get('pullback_score') or 0
        state = r.get('setup_state', '')
        conf  = r.get('confidence_level', '')
        tag   = '[COMPRAR]' if dec == 'BUY_CANDIDATE' else '[VIGILAR]'
        lines.append(f'  {tag} {sym:<6}  trend={ts:.0f}  pullback={ps:.0f}  {state}  [{conf}]')
    return '\n'.join(lines)


def build_message(hoy: date, mkt, sectors, short: dict, candidates: list[dict]) -> str:
    sep = '-' * 32

    # Cabecera
    parts = [
        f'Trading Assist — {hoy.strftime("%d/%m/%Y")}',
        f'Apertura NYSE (10:30 AR)',
        sep,
    ]

    # Contexto de mercado
    parts.append('MERCADO')
    parts.append(_regime_line(mkt))

    # Sectores
    sector_txt = _sector_lines(sectors)
    if sector_txt:
        parts.append('')
        parts.append('SECTORES')
        parts.append(sector_txt)

    # Corto plazo
    parts.append('')
    parts.append(sep)
    parts.append('CORTO PLAZO')
    parts.append(_short_term_lines(short))

    # Señales de compra
    parts.append('')
    parts.append(sep)
    parts.append('SEÑALES DE COMPRA (Trend Pullback)')
    parts.append(_buy_signal_lines(candidates))

    return '\n'.join(parts)


def send_telegram(text: str, dry_run: bool = False):
    print('\n[5/5] Enviando Telegram...')
    print()
    print(text)
    print()
    if dry_run:
        print('  [DRY-RUN] No enviado.')
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    r = requests.post(url, data={
        'chat_id':    TELEGRAM_CHAT_ID,
        'text':       text,
        'parse_mode': 'HTML',
    }, timeout=15)
    if r.status_code == 200:
        print('  Mensaje enviado OK')
    else:
        print(f'  ERROR Telegram: {r.status_code} — {r.text[:200]}')


# =============================================================================
#  MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Imprime sin enviar a Telegram')
    parser.add_argument('--skip-update', action='store_true', help='Omitir actualización de precios')
    args = parser.parse_args()

    hoy = date.today()
    print(f'=== morning_alert — {hoy} ===')

    if not args.skip_update:
        step_update_prices()
        step_update_ohlcv_extended()

    step_context()
    short      = step_short_term(hoy)
    candidates = step_buy_signals(hoy)

    mkt     = get_latest_regime(MARKET_BENCHMARK)
    sectors = get_latest_sector_regimes(SECTOR_BENCHMARKS)

    msg = build_message(hoy, mkt, sectors, short, candidates)
    send_telegram(msg, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
