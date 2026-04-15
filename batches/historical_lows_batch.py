"""
batches.historical_lows_batch — Batch de deteccion de minimos historicos.

Corre la estrategia historical_lows para todo el universo con precios,
filtra los que tienen senial (NEAR_52W_LOW, AT_52W_LOW, NEW_52W_LOW)
y genera notificacion + Telegram.

Schedule sugerido: lunes a viernes 17:15 ART (despues del closing).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.base import Batch
from strategies.historical_lows import run_universe, ensure_table, save_signals


def _get_symbols_with_prices(cur) -> list[str]:
    """Retorna simbolos que tienen al menos 100 dias de precio."""
    cur.execute("""
        SELECT simbolo, COUNT(*) AS cnt
        FROM price_history
        GROUP BY simbolo
        HAVING cnt >= 100
    """)
    return [r['simbolo'] for r in cur.fetchall()]


def _resolve_accion_ids(cur, symbols: list[str]) -> dict[str, int]:
    """Mapea simbolo -> accion.id para navegacion en el frontend."""
    if not symbols:
        return {}
    placeholders = ','.join(['%s'] * len(symbols))
    cur.execute(
        f"SELECT id, simbolo FROM accion WHERE simbolo IN ({placeholders})",
        symbols,
    )
    return {r['simbolo']: r['id'] for r in cur.fetchall()}


def _fmt_pct(v) -> str:
    if v is None:
        return '--'
    sign = '+' if v >= 0 else ''
    return f'{sign}{v:.1f}%'


class HistoricalLowsBatch(Batch):
    name = 'historical_lows'
    kind = 'historical_lows'

    def fetch(self):
        ensure_table()

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                symbols = _get_symbols_with_prices(cur)
                accion_map = _resolve_accion_ids(cur, symbols)
        finally:
            conn.close()

        results = run_universe(symbols)
        save_signals(results)

        # Solo los que tienen senial
        alerts = [r for r in results if r['setup_state'] != 'NO_SIGNAL']

        # Agregar accion_id a cada resultado
        for r in alerts:
            r['accion_id'] = accion_map.get(r['simbolo'])

        return {
            'total_analyzed': len(results),
            'alerts':         alerts,
        }

    def build_payload(self, raw):
        alerts = raw['alerts']
        total  = raw['total_analyzed']

        new_lows  = [a for a in alerts if a['setup_state'] == 'NEW_52W_LOW']
        at_lows   = [a for a in alerts if a['setup_state'] == 'AT_52W_LOW']
        near_lows = [a for a in alerts if a['setup_state'] == 'NEAR_52W_LOW']

        # Titulo
        n_critical = len(new_lows) + len(at_lows)
        if n_critical > 0:
            title = f'Minimos historicos: {n_critical} activos en zona critica'
        elif near_lows:
            title = f'Minimos historicos: {len(near_lows)} activos cerca de minimos'
        else:
            title = 'Minimos historicos: sin alertas hoy'

        # Body para Telegram
        lines = []
        if new_lows:
            lines.append('NUEVOS MINIMOS 52w:')
            for a in sorted(new_lows, key=lambda x: x.get('distance_52w_pct') or 0)[:15]:
                atl = ' [ATL]' if a['is_all_time_low'] else ''
                lines.append(
                    f"  {a['simbolo']} ${a['price']:.2f} "
                    f"(min ${a['low_52w']:.2f}){atl}"
                )
            if len(new_lows) > 15:
                lines.append(f'  ... y {len(new_lows) - 15} mas')
        if at_lows:
            lines.append('EN MINIMO 52w:')
            for a in sorted(at_lows, key=lambda x: x.get('distance_52w_pct') or 0)[:15]:
                lines.append(
                    f"  {a['simbolo']} ${a['price']:.2f} "
                    f"dist {_fmt_pct(a['distance_52w_pct'])}"
                )
            if len(at_lows) > 15:
                lines.append(f'  ... y {len(at_lows) - 15} mas')
        if near_lows:
            lines.append('CERCA DE MINIMO 52w:')
            for a in sorted(near_lows, key=lambda x: x.get('distance_52w_pct') or 0)[:10]:
                lines.append(
                    f"  {a['simbolo']} ${a['price']:.2f} "
                    f"dist {_fmt_pct(a['distance_52w_pct'])}"
                )
            if len(near_lows) > 10:
                lines.append(f'  ... y {len(near_lows) - 10} mas')

        body = '\n'.join(lines) if lines else f'Se analizaron {total} activos. Sin alertas.'

        # top_up / top_down para chips en el frontend Alerts
        # top_up = activos en alerta (NEW + AT), top_down = NEAR
        top_up = [
            {
                'symbol':    a['simbolo'],
                'pct':       a['distance_52w_pct'] or 0,
                'accion_id': a.get('accion_id'),
                'state':     a['setup_state'],
                'is_atl':    a['is_all_time_low'],
            }
            for a in sorted(new_lows + at_lows,
                            key=lambda x: x.get('distance_52w_pct') or 0)
        ]
        top_down = [
            {
                'symbol':    a['simbolo'],
                'pct':       a['distance_52w_pct'] or 0,
                'accion_id': a.get('accion_id'),
                'state':     a['setup_state'],
            }
            for a in sorted(near_lows,
                            key=lambda x: x.get('distance_52w_pct') or 0)[:10]
        ]

        return {
            'title':           title,
            'body':            body,
            'total_analyzed':  total,
            'n_new_lows':      len(new_lows),
            'n_at_lows':       len(at_lows),
            'n_near_lows':     len(near_lows),
            'top_up':          top_up,
            'top_down':        top_down,
        }
