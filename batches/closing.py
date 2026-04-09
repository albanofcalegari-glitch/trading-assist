"""
batches.closing — Batch D · Resumen de cierre del mercado.

Schedule sugerido: lunes a viernes 17:00 ART.

Output:
  - Sentimiento general (alcista / bajista / mixto) según SPY del día
  - Performance de SPY y QQQ
  - Top 5 movers up + Top 5 movers down (USA)
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.base import Batch


USA_MARKETS = ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')


def _last_two_dates(cur) -> tuple:
    cur.execute("""
        SELECT fecha FROM valorhistoricoaccion
        GROUP BY fecha HAVING COUNT(*) >= 5000
        ORDER BY fecha DESC LIMIT 2
    """)
    rows = cur.fetchall()
    if len(rows) >= 2:
        return rows[0]['fecha'], rows[1]['fecha']
    cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion")
    last = cur.fetchone()['f']
    cur.execute("SELECT MAX(fecha) AS f FROM valorhistoricoaccion WHERE fecha < %s", [last])
    return last, cur.fetchone()['f']


def _index_pct(cur, symbol: str, last, prev) -> float | None:
    cur.execute("""
        SELECT v1.precio_cierre AS c1, v2.precio_cierre AS c0
        FROM valorhistoricoaccion v1
        JOIN accion a ON a.id = v1.accion_id
        JOIN valorhistoricoaccion v2
          ON v2.accion_id = v1.accion_id AND v2.fecha = %s
        WHERE a.simbolo = %s AND v1.fecha = %s
        LIMIT 1
    """, [prev, symbol, last])
    row = cur.fetchone()
    if not row or not row['c0']:
        return None
    return float(row['c1'] / row['c0'] - 1) * 100


def _top_movers(cur, last, prev, direction: str = 'up', n: int = 5) -> list[dict]:
    order = 'DESC' if direction == 'up' else 'ASC'
    placeholders = ','.join(['%s'] * len(USA_MARKETS))
    cur.execute(f"""
        SELECT a.id AS accion_id, a.simbolo, a.nombre, m.descripcion AS mercado,
               v1.precio_cierre AS precio,
               ROUND((v1.precio_cierre / v2.precio_cierre - 1) * 100, 2) AS pct_cambio
        FROM valorhistoricoaccion v1
        JOIN valorhistoricoaccion v2
          ON v1.accion_id = v2.accion_id AND v2.fecha = %s
        JOIN accion a ON a.id = v1.accion_id
        JOIN mercado m ON m.id = a.mercado_id
        WHERE v1.fecha = %s AND v1.precio_cierre > 0.5 AND v2.precio_cierre > 0.5
          AND m.descripcion IN ({placeholders})
        ORDER BY pct_cambio {order}
        LIMIT %s
    """, [prev, last, *USA_MARKETS, n])
    return list(cur.fetchall())


def _classify_sentiment(spy_pct: float | None) -> str:
    if spy_pct is None:
        return 'sin datos'
    if spy_pct >= 0.5:  return 'alcista'
    if spy_pct <= -0.5: return 'bajista'
    return 'mixto'


def _fmt_pct(v) -> str:
    if v is None:
        return '—'
    sign = '+' if v >= 0 else ''
    return f'{sign}{v:.2f}%'


class ClosingBatch(Batch):
    name = 'closing'
    kind = 'close'

    def fetch(self):
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                last, prev = _last_two_dates(cur)
                return {
                    'fecha':    str(last),
                    'spy_pct':  _index_pct(cur, 'SPY', last, prev),
                    'qqq_pct':  _index_pct(cur, 'QQQ', last, prev),
                    'movers_up':   _top_movers(cur, last, prev, 'up',   5),
                    'movers_down': _top_movers(cur, last, prev, 'down', 5),
                }
        finally:
            conn.close()

    def build_payload(self, raw):
        sentiment = _classify_sentiment(raw['spy_pct'])

        ups = ', '.join(
            f"{m['simbolo']} {_fmt_pct(float(m['pct_cambio']))}"
            for m in raw['movers_up'][:5]
        ) or '—'
        downs = ', '.join(
            f"{m['simbolo']} {_fmt_pct(float(m['pct_cambio']))}"
            for m in raw['movers_down'][:5]
        ) or '—'

        title = f'Cierre {sentiment} · SPY {_fmt_pct(raw["spy_pct"])}'
        body  = (
            f"SPY {_fmt_pct(raw['spy_pct'])}, QQQ {_fmt_pct(raw['qqq_pct'])}. "
            f"Top alza: {ups}. Top baja: {downs}."
        )

        return {
            'title':       title,
            'body':        body,
            'fecha':       raw['fecha'],
            'sentiment':   sentiment,
            'spy_pct':     raw['spy_pct'],
            'qqq_pct':     raw['qqq_pct'],
            'top_up':      [
                {'symbol': m['simbolo'], 'name': m['nombre'],
                 'price': float(m['precio']), 'pct': float(m['pct_cambio']),
                 'accion_id': m['accion_id']}
                for m in raw['movers_up']
            ],
            'top_down':    [
                {'symbol': m['simbolo'], 'name': m['nombre'],
                 'price': float(m['precio']), 'pct': float(m['pct_cambio']),
                 'accion_id': m['accion_id']}
                for m in raw['movers_down']
            ],
        }
