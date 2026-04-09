"""
batches.opening — Batch B · Apertura del mercado (compara premarket vs realidad).

Schedule sugerido: lunes a viernes 10:30 ART (~30 min después de PremarketBatch,
ya con la apertura RTH 09:30 ET en marcha).

Lee el último run exitoso de PremarketBatch desde `batch_run.payload_json`,
re-fetchea los mismos símbolos con includePrePost=true y clasifica cada uno:

    confirmed   → premarket y open en la misma dirección, |gap| ≥ 0.3%
    amplified   → misma dirección que premarket, pero gap más fuerte (>1.5×)
    faded       → premarket positivo y open negativo (o viceversa)
    flat        → |gap| < 0.3%

Output:
  - Sentimiento de apertura según SPY gap_pct
  - Tabla de comparativa por símbolo
  - Top sorpresas (los que más se desviaron del premarket)
"""
from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from config import UNIVERSE, MARKET_BENCHMARK
from batches.base import Batch
from batches.shared.yahoo_quote import fetch_quotes_batch


OPENING_BENCHMARKS = [MARKET_BENCHMARK, 'QQQ']
FLAT_THRESHOLD     = 0.3   # |gap%| < 0.3 → flat
AMPLIFY_RATIO      = 1.5   # |gap| > 1.5 × |premarket| → amplified


def _last_premarket_payload() -> dict | None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT payload_json FROM batch_run
                WHERE batch_name = 'premarket' AND status = 'OK'
                ORDER BY id DESC LIMIT 1
            """)
            row = cur.fetchone()
            if not row or not row['payload_json']:
                return None
            try:
                return json.loads(row['payload_json'])
            except Exception:
                return None
    finally:
        conn.close()


def _classify(pre_pct: float | None, gap_pct: float | None) -> str:
    if gap_pct is None:
        return 'no_data'
    if abs(gap_pct) < FLAT_THRESHOLD:
        return 'flat'
    if pre_pct is None:
        return 'confirmed' if abs(gap_pct) >= FLAT_THRESHOLD else 'flat'
    same_dir = (pre_pct >= 0) == (gap_pct >= 0)
    if not same_dir:
        return 'faded'
    if abs(gap_pct) > AMPLIFY_RATIO * max(abs(pre_pct), 0.1):
        return 'amplified'
    return 'confirmed'


def _classify_sentiment(spy_gap: float | None) -> str:
    if spy_gap is None:
        return 'sin datos'
    if spy_gap >= 0.3:  return 'alcista'
    if spy_gap <= -0.3: return 'bajista'
    return 'mixto'


def _fmt_pct(v) -> str:
    if v is None:
        return '—'
    sign = '+' if v >= 0 else ''
    return f'{sign}{v:.2f}%'


def _accion_id_map(symbols: list[str]) -> dict[str, int]:
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


class OpeningBatch(Batch):
    name = 'opening'
    kind = 'opening'

    def fetch(self):
        prev = _last_premarket_payload()  # puede ser None si nunca corrió premarket
        # Watchlist: la del premarket si existe, sino UNIVERSE
        if prev and prev.get('universe'):
            symbols = sorted(set(OPENING_BENCHMARKS) | set(prev['universe']))
        else:
            symbols = sorted(set(OPENING_BENCHMARKS) | set(UNIVERSE))

        quotes = fetch_quotes_batch(symbols, delay=0.15)
        ids = _accion_id_map(list(quotes.keys()))

        # Mapeo symbol → premarket_pct anterior
        pre_map: dict[str, float | None] = {}
        if prev:
            for r in (prev.get('watchlist') or []):
                pre_map[r['symbol']] = r.get('pct')
            pre_map.setdefault(MARKET_BENCHMARK, prev.get('spy_pct'))
            pre_map.setdefault('QQQ',           prev.get('qqq_pct'))

        return {'quotes': quotes, 'pre_map': pre_map, 'ids': ids,
                'had_premarket': prev is not None}

    def build_payload(self, raw):
        quotes:   dict[str, dict]        = raw['quotes']
        pre_map:  dict[str, float | None] = raw['pre_map']
        ids:      dict[str, int]         = raw['ids']

        spy = quotes.get(MARKET_BENCHMARK, {}) or {}
        qqq = quotes.get('QQQ', {}) or {}
        spy_gap = spy.get('gap_pct')
        qqq_gap = qqq.get('gap_pct')
        sentiment = _classify_sentiment(spy_gap)

        # Comparativa universe
        rows = []
        for sym in UNIVERSE:
            q = quotes.get(sym)
            if not q:
                continue
            pre = pre_map.get(sym)
            gap = q.get('gap_pct')
            cls = _classify(pre, gap)
            rows.append({
                'symbol':     sym,
                'premarket':  pre,
                'gap':        gap,
                'open':       q.get('open_price'),
                'prev_close': q.get('prev_close'),
                'class':      cls,
                'accion_id':  ids.get(sym),
            })

        # Conteos
        counts = {'confirmed': 0, 'amplified': 0, 'faded': 0, 'flat': 0, 'no_data': 0}
        for r in rows:
            counts[r['class']] = counts.get(r['class'], 0) + 1

        # Sorpresas: mayor desviación |gap - premarket|
        def _surprise(r):
            if r['gap'] is None or r['premarket'] is None:
                return -1
            return abs(r['gap'] - r['premarket'])
        surprises = sorted([r for r in rows if _surprise(r) >= 0],
                           key=_surprise, reverse=True)[:5]

        # MoverChip-style top up/down (por gap)
        rated = [r for r in rows if r['gap'] is not None]
        rated.sort(key=lambda r: r['gap'], reverse=True)
        top_up   = [r for r in rated if r['gap'] >  0][:5]
        top_down = [r for r in reversed(rated) if r['gap'] < 0][:5]

        ups = ', '.join(f"{r['symbol']} {_fmt_pct(r['gap'])}" for r in top_up) or '—'
        downs = ', '.join(f"{r['symbol']} {_fmt_pct(r['gap'])}" for r in top_down) or '—'

        title = f'Apertura {sentiment} · SPY gap {_fmt_pct(spy_gap)}'
        body = (
            f"SPY gap {_fmt_pct(spy_gap)}, QQQ gap {_fmt_pct(qqq_gap)}. "
            f"Confirmados {counts['confirmed']} · amplificados {counts['amplified']} · "
            f"desvanecidos {counts['faded']} · planos {counts['flat']}. "
            f"Top alza: {ups}. Top baja: {downs}."
        )

        return {
            'title':         title,
            'body':          body,
            'sentiment':     sentiment,
            'spy_gap_pct':   spy_gap,
            'qqq_gap_pct':   qqq_gap,
            'had_premarket': raw['had_premarket'],
            'counts':        counts,
            'rows':          rows,
            'surprises':     [
                {'symbol': r['symbol'], 'pct': r['gap'],
                 'price': r['open'], 'accion_id': r['accion_id'],
                 'class': r['class'], 'premarket': r['premarket']}
                for r in surprises
            ],
            'top_up':        [
                {'symbol': r['symbol'], 'pct': r['gap'],
                 'price': r['open'], 'accion_id': r['accion_id']}
                for r in top_up
            ],
            'top_down':      [
                {'symbol': r['symbol'], 'pct': r['gap'],
                 'price': r['open'], 'accion_id': r['accion_id']}
                for r in top_down
            ],
        }
