"""
batches.weekly_ranking — Batch E · Top 10 semanal del universo USA.

Schedule sugerido: viernes 17:30 ART (después del cierre RTH).

Lógica:
  - Bulk fetch de últimas ~75 velas para todo el universo USA (un único SQL).
  - Agrupa por símbolo en Python.
  - Calcula SPY 20d ret una sola vez.
  - Score 0-100 por símbolo via ranking_engine.score_all().
  - Si hay duplicados de símbolo en distintos mercados (p.ej. NU en NASDAQ +
    NYSE), nos quedamos con el de mercado con prioridad NASDAQ → NYSE → resto.
  - Top 10 va al notification.payload, los siguientes 20 quedan en `runner_ups`.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from batches.base import Batch
from batches.shared.ranking_engine import (
    fetch_universe_history, fetch_spy_history,
    group_by_symbol, score_all, compute_return,
)


# Prioridad de mercado cuando un símbolo aparece en varios
MARKET_PRIORITY = {
    'NASDAQ':        0,
    'NYSE':          1,
    'NYSE_AMERICAN': 2,
    'NYSE_ARCA':     3,
    'CBOE_BZX':      4,
}


def _dedupe_by_market(grouped: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """
    Si un símbolo está duplicado, deja sólo el que vino del mercado de mayor
    prioridad. (En la práctica los datos vienen agrupados por simbolo+accion_id,
    así que esto sólo dispara con ADRs / dual-listed.)
    """
    out: dict[str, list[dict]] = {}
    for sym, candles in grouped.items():
        if sym in out:
            existing_mkt = out[sym][-1]['mercado']
            new_mkt      = candles[-1]['mercado']
            if MARKET_PRIORITY.get(new_mkt, 99) < MARKET_PRIORITY.get(existing_mkt, 99):
                out[sym] = candles
        else:
            out[sym] = candles
    return out


class WeeklyRankingBatch(Batch):
    name = 'weekly_ranking'
    kind = 'weekly_rank'

    def fetch(self):
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                rows = fetch_universe_history(cur, days=75)
                spy_rows = fetch_spy_history(cur, days=75)
        finally:
            conn.close()
        return {'rows': rows, 'spy_rows': spy_rows}

    def build_payload(self, raw):
        grouped = group_by_symbol(raw['rows'])
        grouped = _dedupe_by_market(grouped)

        spy_ret_20d = compute_return(raw['spy_rows'], 20)

        scored = score_all(grouped, spy_ret_20d)
        top10 = scored[:10]
        runner_ups = scored[10:30]

        # Resumen humano
        if top10:
            line = ' · '.join(f"{r['symbol']} {r['score']}" for r in top10[:5])
        else:
            line = '—'

        title = f'Top 10 semanal · líder {top10[0]["symbol"]} ({top10[0]["score"]})' \
                if top10 else 'Top 10 semanal · sin datos'

        body = (
            f"Universo: {len(scored)} acciones evaluadas. "
            f"SPY 20d {('+' if (spy_ret_20d or 0) >= 0 else '')}{(spy_ret_20d or 0):.2f}%. "
            f"Top 5: {line}."
        )

        # MoverChip arrays — usamos `pct` = score (Alerts.tsx ya pinta esto)
        top_up = [
            {'symbol': r['symbol'], 'pct': r['score'],
             'price': r['price'], 'accion_id': r['accion_id']}
            for r in top10
        ]

        return {
            'title':         title,
            'body':          body,
            'spy_ret_20d':   spy_ret_20d,
            'evaluated':     len(scored),
            'top10':         top10,
            'runner_ups':    runner_ups,
            'top_up':        top_up,   # para que Alerts.tsx pinte chips
            'top_down':      [],
        }
