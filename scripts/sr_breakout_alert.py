"""
sr_breakout_alert.py — Alerta diaria S/R dinámicos
====================================================
Escanea activos con suficiente historia, detecta 5 situaciones:

  Resistencia:
    - TOCO: high llegó a <=1.5% de la línea (posible rechazo o ruptura)
    - ROMPIO: cerró >2% arriba de la línea (ruptura más confiable)

  Soporte:
    - TOCO: low llegó a <=1.5% de la línea (posible rebote o quiebre)
    - REBOTO: low tocó y cerró arriba con vela bullish (rebote confirmado)

  Lateralización:
    - LATERALIZADO: S y R horizontal con 4+ toques cada uno, rango <5%

Envía por Telegram si hay señales. Diseñado para correr como cron post-cierre.

Uso:
  python scripts/sr_breakout_alert.py            # escanea y envía
  python scripts/sr_breakout_alert.py --dry-run  # imprime sin enviar
"""
import sys, os, argparse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from datetime import date
from db.connection import get_conn
from strategies.dynamic_resistances import get_dynamic_resistances
from strategies.dynamic_supports import get_dynamic_supports
from batches.notifier import make_default_notifier

MIN_WEEKLY_BARS = 200
MIN_TOUCHES = 3

RES_TOUCH_TOL_PCT = 1.5
RES_BREAK_MIN_PCT = 2.0
RES_BREAK_MAX_PCT = 8.0

SUP_TOUCH_TOL_PCT = 1.5
SUP_BOUNCE_MAX_DIST_LOW_PCT = 1.5

LAT_MAX_RANGE_PCT = 5.0
LAT_MIN_TOUCHES = 4

FOCUS_WATCHLIST = ['TSLA']
FOCUS_TOUCH_TOL_PCT = 2.0
FOCUS_BREAK_MIN_PCT = 1.5
FOCUS_BREAK_MAX_PCT = 10.0
FOCUS_MIN_TOUCHES = 2


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


def _get_last_2_bars(symbol: str) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT fecha, open, high, low, close, volume
                FROM ohlcv_extended
                WHERE simbolo = %s AND timeframe = 'D'
                ORDER BY fecha DESC LIMIT 2
            ''', (symbol,))
            return cur.fetchall()
    finally:
        conn.close()


def _get_avg_volume(symbol: str, n: int = 20) -> float:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT AVG(volume) as avg_vol
                FROM (
                    SELECT volume FROM ohlcv_extended
                    WHERE simbolo = %s AND timeframe = 'D'
                      AND volume > 0
                    ORDER BY fecha DESC LIMIT %s
                ) sub
            ''', (symbol, n))
            row = cur.fetchone()
            return float(row['avg_vol']) if row and row['avg_vol'] else 0
    finally:
        conn.close()


def _find_line_value_at_date(line_points: list[dict], date_str: str):
    for p in line_points:
        if p['fecha'] == date_str:
            return p['value']
    return None


def _kind_label(kind: str) -> str:
    if 'desc' in kind:
        return 'desc'
    if 'asc' in kind:
        return 'asc'
    return 'horiz'


def scan(symbols: list[str]):
    res_touched = []
    res_broke = []
    sup_touched = []
    sup_bounced = []
    lateralized = []

    for idx, symbol in enumerate(symbols):
        if idx % 50 == 0:
            print(f'  scanning {idx}/{len(symbols)}...')

        try:
            bars = _get_last_2_bars(symbol)
            if len(bars) < 2:
                continue

            today = bars[0]
            yesterday = bars[1]
            tdate = str(today['fecha'])
            ydate = str(yesterday['fecha'])
            curr_close = float(today['close'])
            curr_high = float(today['high'])
            curr_low = float(today['low'])
            curr_open = float(today['open'])
            curr_vol = float(today.get('volume', 0))
            prev_close = float(yesterday['close'])

            avg_vol = _get_avg_volume(symbol)
            vr = round(curr_vol / avg_vol, 1) if avg_vol > 0 else 0
            vol_tag = f' [Vol {vr}x]' if vr >= 1.3 else ''

            horiz_res = []
            horiz_sup = []

            # ── Resistance ──
            try:
                res = get_dynamic_resistances(symbol, tf='D')
            except Exception:
                res = {'long': None, 'mid': None, 'short': None}

            for tier_name in ('long', 'mid', 'short'):
                r = res.get(tier_name)
                if not r or r['touches'] < MIN_TOUCHES:
                    continue

                lp = r.get('line_points', [])
                val_today = _find_line_value_at_date(lp, tdate)
                if not val_today:
                    continue

                if _kind_label(r.get('kind', '?')) == 'horiz':
                    horiz_res.append({'value': val_today, 'touches': r['touches'],
                                     'anchor1': r['anchor1']['fecha']})

                dist_high = (curr_high / val_today - 1) * 100
                dist_close = (curr_close / val_today - 1) * 100

                entry = {
                    'symbol': symbol, 'tier': tier_name,
                    'kind': _kind_label(r.get('kind', '?')),
                    'close': round(curr_close, 2),
                    'high': round(curr_high, 2),
                    'resistance': round(val_today, 2),
                    'dist_close_pct': round(dist_close, 1),
                    'touches': r['touches'],
                    'anchor1': r['anchor1']['fecha'],
                    'vol_tag': vol_tag,
                }

                if dist_close >= RES_BREAK_MIN_PCT and dist_close <= RES_BREAK_MAX_PCT:
                    val_yesterday = _find_line_value_at_date(lp, ydate)
                    if val_yesterday and prev_close < val_yesterday:
                        entry['action'] = 'ROMPIO'
                        res_broke.append(entry)
                elif abs(dist_high) <= RES_TOUCH_TOL_PCT and dist_close < RES_BREAK_MIN_PCT:
                    entry['action'] = 'TOCO'
                    res_touched.append(entry)

            # ── Support ──
            try:
                sup = get_dynamic_supports(symbol, tf='D')
            except Exception:
                sup = {'long': None, 'mid': None, 'short': None}

            for tier_name in ('long', 'mid', 'short'):
                s = sup.get(tier_name)
                if not s or s['touches'] < MIN_TOUCHES:
                    continue

                lp = s.get('line_points', [])
                val_today = _find_line_value_at_date(lp, tdate)
                if not val_today:
                    continue

                if _kind_label(s.get('kind', '?')) == 'horiz':
                    horiz_sup.append({'value': val_today, 'touches': s['touches'],
                                     'anchor1': s['anchor1']['fecha']})

                dist_low = (curr_low / val_today - 1) * 100
                dist_close = (curr_close / val_today - 1) * 100

                entry = {
                    'symbol': symbol, 'tier': tier_name,
                    'kind': _kind_label(s.get('kind', '?')),
                    'close': round(curr_close, 2),
                    'low': round(curr_low, 2),
                    'support': round(val_today, 2),
                    'dist_low_pct': round(dist_low, 1),
                    'vol_tag': vol_tag,
                    'dist_close_pct': round(dist_close, 1),
                    'touches': s['touches'],
                    'anchor1': s['anchor1']['fecha'],
                }

                if abs(dist_low) <= SUP_TOUCH_TOL_PCT:
                    if dist_close > 0 and curr_close > curr_open and dist_low >= -SUP_BOUNCE_MAX_DIST_LOW_PCT:
                        entry['action'] = 'REBOTO'
                        sup_bounced.append(entry)
                    else:
                        entry['action'] = 'TOCO'
                        sup_touched.append(entry)

            # ── Lateralization ──
            for hr in horiz_res:
                for hs in horiz_sup:
                    if hr['value'] <= hs['value']:
                        continue
                    range_pct = (hr['value'] - hs['value']) / hs['value'] * 100
                    if (range_pct <= LAT_MAX_RANGE_PCT
                            and hr['touches'] >= LAT_MIN_TOUCHES
                            and hs['touches'] >= LAT_MIN_TOUCHES):
                        lateralized.append({
                            'symbol': symbol,
                            'close': round(curr_close, 2),
                            'support': round(hs['value'], 2),
                            'resistance': round(hr['value'], 2),
                            'range_pct': round(range_pct, 1),
                            'sup_touches': hs['touches'],
                            'res_touches': hr['touches'],
                            'action': 'LATERALIZADO',
                        })

        except Exception as e:
            print(f'  {symbol}: error {e}')
            continue

    def dedup(lst):
        seen = {}
        for item in lst:
            s = item['symbol']
            if s not in seen or item['touches'] > seen[s]['touches']:
                seen[s] = item
        return sorted(seen.values(), key=lambda x: -x['touches'])

    def dedup_lat(lst):
        seen = {}
        for item in lst:
            s = item['symbol']
            if s not in seen or item['range_pct'] < seen[s]['range_pct']:
                seen[s] = item
        return sorted(seen.values(), key=lambda x: x['range_pct'])

    return dedup(res_broke), dedup(res_touched), dedup(sup_bounced), dedup(sup_touched), dedup_lat(lateralized)


def scan_focus(symbols: list[str]):
    """Escaneo detallado para tickers en FOCUS_WATCHLIST — chequea D y W."""
    results = []

    for symbol in symbols:
        if symbol not in FOCUS_WATCHLIST:
            continue

        try:
            bars_d = _get_last_2_bars(symbol)
            if len(bars_d) < 2:
                continue

            today = bars_d[0]
            tdate = str(today['fecha'])
            curr_close = float(today['close'])
            curr_high = float(today['high'])

            for tf in ('W', 'D'):
                try:
                    res = get_dynamic_resistances(symbol, tf=tf)
                except Exception:
                    continue

                for tier_name in ('long', 'mid', 'short'):
                    r = res.get(tier_name)
                    if not r or r['touches'] < FOCUS_MIN_TOUCHES:
                        continue

                    lp = r.get('line_points', [])
                    val_today = _find_line_value_at_date(lp, tdate)
                    if not val_today:
                        val_today = r.get('current_value')
                    if not val_today:
                        continue

                    dist_close = (curr_close / val_today - 1) * 100
                    dist_high = (curr_high / val_today - 1) * 100

                    action = None
                    if dist_close >= FOCUS_BREAK_MIN_PCT and dist_close <= FOCUS_BREAK_MAX_PCT:
                        action = 'ROMPIO'
                    elif abs(dist_high) <= FOCUS_TOUCH_TOL_PCT and dist_close < FOCUS_BREAK_MIN_PCT:
                        action = 'TESTEANDO'
                    elif abs(dist_close) <= FOCUS_TOUCH_TOL_PCT:
                        action = 'TESTEANDO'

                    if action:
                        results.append({
                            'symbol': symbol,
                            'tf': tf,
                            'tier': tier_name,
                            'kind': _kind_label(r.get('kind', '?')),
                            'action': action,
                            'close': round(curr_close, 2),
                            'high': round(curr_high, 2),
                            'resistance': round(val_today, 2),
                            'dist_close_pct': round(dist_close, 1),
                            'touches': r['touches'],
                            'slope_annual_pct': round(r.get('slope_annual_pct', 0), 1),
                            'anchor1': r['anchor1']['fecha'],
                            'anchor2': r['anchor2']['fecha'],
                            'status': r.get('status', '?'),
                        })
        except Exception as e:
            print(f'  focus {symbol}: error {e}')

    return results


def format_telegram_message(res_broke, res_touched, sup_bounced, sup_touched, lateralized, fecha, focus_results=None):
    lines = [f'*S/R Alert* ({fecha})', '']

    if focus_results:
        lines.append('=== FOCUS WATCHLIST ===')
        for f in focus_results:
            emoji = 'BREAKOUT' if f['action'] == 'ROMPIO' else 'TESTING'
            lines.append(
                f"  [{emoji}] `{f['symbol']}` {f['tf']}/{f['tier']} "
                f"${f['close']} vs R ${f['resistance']} "
                f"({f['dist_close_pct']:+.1f}%) "
                f"{f['touches']}t {f['kind']} "
                f"({f['anchor1']} -> {f['anchor2']}) "
                f"slope {f['slope_annual_pct']}%/y"
            )
        lines.append('')

    if res_broke:
        lines.append('ROMPIERON resistencia:')
        for r in res_broke[:10]:
            lines.append(
                f"  `{r['symbol']:6s}` ${r['close']} > R ${r['resistance']} "
                f"({r['dist_close_pct']:+.1f}%) {r['touches']}t {r['kind']} {r['anchor1']}"
                f"{r.get('vol_tag', '')}"
            )
        lines.append('')

    if res_touched:
        lines.append('TOCARON resistencia:')
        for r in res_touched[:10]:
            lines.append(
                f"  `{r['symbol']:6s}` hi ${r['high']} ~ R ${r['resistance']} "
                f"(c {r['dist_close_pct']:+.1f}%) {r['touches']}t {r['kind']} {r['anchor1']}"
                f"{r.get('vol_tag', '')}"
            )
        lines.append('')

    if sup_bounced:
        lines.append('REBOTARON en soporte:')
        for s in sup_bounced[:10]:
            lines.append(
                f"  `{s['symbol']:6s}` lo ${s['low']} ~ S ${s['support']} "
                f"({s['dist_low_pct']:+.1f}%) -> ${s['close']} "
                f"{s['touches']}t {s['kind']} {s['anchor1']}"
                f"{s.get('vol_tag', '')}"
            )
        lines.append('')

    if sup_touched:
        lines.append('TOCARON soporte:')
        for s in sup_touched[:10]:
            lines.append(
                f"  `{s['symbol']:6s}` lo ${s['low']} ~ S ${s['support']} "
                f"({s['dist_low_pct']:+.1f}%) c ${s['close']} "
                f"{s['touches']}t {s['kind']} {s['anchor1']}"
                f"{s.get('vol_tag', '')}"
            )

    if lateralized:
        lines.append('LATERALIZADOS (rango comprimido):')
        for l in lateralized[:10]:
            lines.append(
                f"  `{l['symbol']:6s}` S ${l['support']} | R ${l['resistance']} "
                f"({l['range_pct']:.1f}%) c ${l['close']} "
                f"{l['sup_touches']}+{l['res_touches']}t"
            )
        lines.append('')

    if not any([res_broke, res_touched, sup_bounced, sup_touched, lateralized]):
        lines.append('Sin senales hoy.')

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print('=== S/R Breakout Alert ===')
    symbols = _get_symbols()
    print(f'Symbols to scan: {len(symbols)}')

    res_broke, res_touched, sup_bounced, sup_touched, lateralized = scan(symbols)

    focus_results = scan_focus(symbols)
    if focus_results:
        print(f'\nFOCUS WATCHLIST:')
        for f in focus_results:
            print(f"  {f['action']} {f['symbol']} {f['tf']}/{f['tier']} "
                  f"close=${f['close']} R=${f['resistance']} ({f['dist_close_pct']:+.1f}%) "
                  f"{f['touches']}t {f['kind']}")

    fecha = date.today().isoformat()
    print(f'\nResultados ({fecha}):')

    for label, lst in [('Rompieron R', res_broke), ('Tocaron R', res_touched),
                       ('Rebotaron S', sup_bounced), ('Tocaron S', sup_touched),
                       ('Lateralizados', lateralized)]:
        print(f'  {label}: {len(lst)}')
        for item in lst:
            print(f"    {item['symbol']} {item.get('tier', '-')} {item}")

    has_signals = any([res_broke, res_touched, sup_bounced, sup_touched, lateralized, focus_results])

    if has_signals:
        msg = format_telegram_message(res_broke, res_touched, sup_bounced, sup_touched, lateralized, fecha, focus_results)
        print(f'\n--- Telegram ---\n{msg}\n---')

        if not args.dry_run:
            notifier = make_default_notifier()
            notifier.notify('sr_alert', 'S/R Alert', msg, {})
            print('Telegram enviado.')
        else:
            print('(dry-run, no se envio)')
    else:
        print('\nSin senales hoy.')


if __name__ == '__main__':
    main()
