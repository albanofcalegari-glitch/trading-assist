"""
batches.historical_highs_batch — Batch de deteccion de maximos historicos.

Corre la estrategia historical_highs para todo el universo con precios,
filtra los que tienen senial (NEAR_52W_HIGH, AT_52W_HIGH, NEW_52W_HIGH)
y genera notificacion + Telegram.

Schedule sugerido: lunes a viernes 17:15 ART (despues del closing).
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.base import Batch
from strategies.historical_highs import run_universe, ensure_table, save_signals


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


class HistoricalHighsBatch(Batch):
    name = 'historical_highs'
    kind = 'historical_highs'

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

        new_highs  = [a for a in alerts if a['setup_state'] == 'NEW_52W_HIGH']
        at_highs   = [a for a in alerts if a['setup_state'] == 'AT_52W_HIGH']
        near_highs = [a for a in alerts if a['setup_state'] == 'NEAR_52W_HIGH']

        # Titulo
        n_critical = len(new_highs) + len(at_highs)
        if n_critical > 0:
            title = f'Maximos historicos: {n_critical} activos en zona critica'
        elif near_highs:
            title = f'Maximos historicos: {len(near_highs)} activos cerca de maximos'
        else:
            title = 'Maximos historicos: sin alertas hoy'

        # Body para Telegram
        lines = []
        if new_highs:
            lines.append('NUEVOS MAXIMOS 52w:')
            for a in sorted(new_highs, key=lambda x: -(x.get('distance_52w_pct') or 0))[:15]:
                ath = ' [ATH]' if a['is_all_time_high'] else ''
                lines.append(
                    f"  {a['simbolo']} ${a['price']:.2f} "
                    f"(max ${a['high_52w']:.2f}){ath}"
                )
            if len(new_highs) > 15:
                lines.append(f'  ... y {len(new_highs) - 15} mas')
        if at_highs:
            lines.append('EN MAXIMO 52w:')
            for a in sorted(at_highs, key=lambda x: -(x.get('distance_52w_pct') or 0))[:15]:
                lines.append(
                    f"  {a['simbolo']} ${a['price']:.2f} "
                    f"dist {_fmt_pct(a['distance_52w_pct'])}"
                )
            if len(at_highs) > 15:
                lines.append(f'  ... y {len(at_highs) - 15} mas')
        if near_highs:
            lines.append('CERCA DE MAXIMO 52w:')
            for a in sorted(near_highs, key=lambda x: -(x.get('distance_52w_pct') or 0))[:10]:
                lines.append(
                    f"  {a['simbolo']} ${a['price']:.2f} "
                    f"dist {_fmt_pct(a['distance_52w_pct'])}"
                )
            if len(near_highs) > 10:
                lines.append(f'  ... y {len(near_highs) - 10} mas')

        body = '\n'.join(lines) if lines else f'Se analizaron {total} activos. Sin alertas.'

        # top_up = activos en alerta critica (NEW + AT), top_down = watchlist (NEAR)
        top_up = [
            {
                'symbol':    a['simbolo'],
                'pct':       a['distance_52w_pct'] or 0,
                'accion_id': a.get('accion_id'),
                'state':     a['setup_state'],
                'is_ath':    a['is_all_time_high'],
            }
            for a in sorted(new_highs + at_highs,
                            key=lambda x: -(x.get('distance_52w_pct') or 0))
        ]
        top_down = [
            {
                'symbol':    a['simbolo'],
                'pct':       a['distance_52w_pct'] or 0,
                'accion_id': a.get('accion_id'),
                'state':     a['setup_state'],
            }
            for a in sorted(near_highs,
                            key=lambda x: -(x.get('distance_52w_pct') or 0))[:10]
        ]

        return {
            'title':           title,
            'body':            body,
            'total_analyzed':  total,
            'n_new_highs':     len(new_highs),
            'n_at_highs':      len(at_highs),
            'n_near_highs':    len(near_highs),
            'top_up':          top_up,
            'top_down':        top_down,
        }
