"""
batches.premarket — Batch A · Resumen pre-mercado.

Schedule sugerido: lunes a viernes 10:00 ART (≈ 08:00 ET, antes de la apertura).

Output:
  - Sentimiento premarket según SPY (alcista / bajista / mixto / sin datos)
  - Premarket % de SPY y QQQ
  - Top movers up / down del UNIVERSE en premarket
  - Watchlist completa (cada símbolo con su premarket_pct)

El payload se persiste en `notification.data_json` para que OpeningBatch lo lea
al cabo de 30 minutos y compare expectativas vs realidad.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from config import UNIVERSE, MARKET_BENCHMARK
from batches.base import Batch
from batches.shared.yahoo_quote import fetch_quotes_batch


PREMARKET_BENCHMARKS = [MARKET_BENCHMARK, 'QQQ']


def _classify_sentiment(spy_pct: float | None) -> str:
    if spy_pct is None:
        return 'sin datos'
    if spy_pct >= 0.3:  return 'alcista'
    if spy_pct <= -0.3: return 'bajista'
    return 'mixto'


def _fmt_pct(v) -> str:
    if v is None:
        return '—'
    sign = '+' if v >= 0 else ''
    return f'{sign}{v:.2f}%'


def _accion_id_map(symbols: list[str]) -> dict[str, int]:
    """Mapea símbolo → accion_id (sólo los que existen en DB)."""
    if not symbols:
        return {}
    placeholders = ','.join(['%s'] * len(symbols))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, simbolo FROM accion WHERE simbolo IN ({placeholders})",
                symbols,
            )
            return {row['simbolo']: row['id'] for row in cur.fetchall()}
    finally:
        conn.close()


class PremarketBatch(Batch):
    name = 'premarket'
    kind = 'pre_market'

    def fetch(self):
        watch = sorted(set(PREMARKET_BENCHMARKS) | set(UNIVERSE))
        quotes = fetch_quotes_batch(watch, delay=0.15)
        ids = _accion_id_map(list(quotes.keys()))
        return {'quotes': quotes, 'accion_ids': ids}

    def build_payload(self, raw):
        quotes: dict[str, dict] = raw['quotes']
        ids:    dict[str, int]  = raw['accion_ids']

        spy = quotes.get(MARKET_BENCHMARK, {}) or {}
        qqq = quotes.get('QQQ', {}) or {}
        spy_pct = spy.get('premarket_pct')
        qqq_pct = qqq.get('premarket_pct')
        sentiment = _classify_sentiment(spy_pct)

        # Watchlist = UNIVERSE (sin benchmarks) con premarket_pct disponible
        rows = []
        for sym in UNIVERSE:
            q = quotes.get(sym)
            if not q:
                continue
            pct = q.get('premarket_pct')
            rows.append({
                'symbol':         sym,
                'pct':            pct,
                'price':          q.get('premarket_price') or q.get('prev_close'),
                'prev_close':     q.get('prev_close'),
                'market_state':   q.get('market_state'),
                'accion_id':      ids.get(sym),
            })

        # Movers (sólo los que tienen pct numérico)
        rated = [r for r in rows if r['pct'] is not None]
        rated.sort(key=lambda r: r['pct'], reverse=True)
        top_up   = [r for r in rated if r['pct'] >  0][:5]
        top_down = [r for r in reversed(rated) if r['pct'] < 0][:5]

        ups = ', '.join(f"{r['symbol']} {_fmt_pct(r['pct'])}" for r in top_up) or '—'
        downs = ', '.join(f"{r['symbol']} {_fmt_pct(r['pct'])}" for r in top_down) or '—'

        title = f'Premarket {sentiment} · SPY {_fmt_pct(spy_pct)}'
        body = (
            f"SPY {_fmt_pct(spy_pct)}, QQQ {_fmt_pct(qqq_pct)}. "
            f"Top alza: {ups}. Top baja: {downs}."
        )

        return {
            'title':       title,
            'body':        body,
            'sentiment':   sentiment,
            'spy_pct':     spy_pct,
            'qqq_pct':     qqq_pct,
            'spy_state':   spy.get('market_state'),
            # MoverChip-friendly arrays
            'top_up':      [
                {'symbol': r['symbol'], 'pct': r['pct'],
                 'price': r['price'], 'accion_id': r['accion_id']}
                for r in top_up
            ],
            'top_down':    [
                {'symbol': r['symbol'], 'pct': r['pct'],
                 'price': r['price'], 'accion_id': r['accion_id']}
                for r in top_down
            ],
            'watchlist':   rows,           # OpeningBatch lo va a consumir
            'universe':    list(UNIVERSE),
        }
