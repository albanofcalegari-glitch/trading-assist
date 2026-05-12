"""
bonds_alert.py — Alerta diaria de bonos argentinos
===================================================
Fetch BYMA → calcula TIR/Z-score → detecta señales → Telegram.

Cron post-cierre BYMA (18:30 ART = 21:30 UTC):
  30 21 * * 1-5 cd /opt/trading-assist && venv/bin/python -m batches.run_batch bonds_alert
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from batches.base import Batch
from scripts.byma_bonds_fetch import run as byma_run
from strategies.bonds_ar import BONDS, PAIRS, calc_spread_signal
from db.connection import get_conn


class BondsAlertBatch(Batch):
    name = 'bonds_alert'
    kind = 'bonds'

    def fetch(self):
        return byma_run(dry_run=False)

    def build_payload(self, analyses: list[dict]) -> dict:
        if not analyses:
            return {'title': 'Bonos AR', 'body': 'Sin datos de BYMA', 'signals': [], 'spreads': []}

        signals = [a for a in analyses if a.get('signal') in ('BUY', 'SELL')]

        spreads = []
        tir_map = {a['symbol']: a['tir'] for a in analyses if a.get('tir') is not None}

        for al_sym, gd_sym in PAIRS:
            if al_sym not in tir_map or gd_sym not in tir_map:
                continue
            spread_bps = round((tir_map[al_sym] - tir_map[gd_sym]) * 100, 1)

            spread_hist = self._get_spread_history(al_sym, gd_sym)
            spread_signal = calc_spread_signal(spread_bps, spread_hist)

            spreads.append({
                'al': al_sym,
                'gd': gd_sym,
                'spread_bps': spread_bps,
                **spread_signal,
            })

        return {
            'title': 'Bonos AR — Señales',
            'body': '',
            'signals': signals,
            'spreads': spreads,
            'all_bonds': analyses,
        }

    def render(self, payload: dict) -> tuple[str, str]:
        lines = []

        for s in payload.get('signals', []):
            emoji = '\U0001f7e2' if s['signal'] == 'BUY' else '\U0001f534'
            z_str = f"Z={s.get('z_score', '?'):+.1f}" if s.get('z_score') is not None else ''
            avg_str = f"prom {s.get('avg_tir', '?')}%" if s.get('avg_tir') is not None else ''
            action = 'COMPRAR' if s['signal'] == 'BUY' else 'VENDER'
            lines.append(
                f"{emoji} {action} {s['symbol']} [{BONDS[s['symbol']]['law']}] "
                f"— TIR {s['tir']}% ({z_str}, {avg_str})"
            )

        for sp in payload.get('spreads', []):
            if sp.get('spread_signal', 'NEUTRAL') == 'NEUTRAL':
                continue
            sig_text = 'AL barato' if sp['spread_signal'] == 'AL_CHEAP' else 'GD barato'
            lines.append(
                f"\U0001f4ca Spread {sp['al']}-{sp['gd']}: "
                f"{sp['spread_bps']:.0f}bps (prom {sp.get('avg_spread', '?')}bps, "
                f"Z={sp.get('spread_z', '?'):+.1f}) → {sig_text}"
            )

        if not lines:
            all_bonds = payload.get('all_bonds', [])
            if all_bonds:
                lines.append('Sin señales hoy. Resumen TIR:')
                for a in sorted(all_bonds, key=lambda x: x.get('tir', 0), reverse=True):
                    lines.append(
                        f"  {a['symbol']:6s} [{BONDS[a['symbol']]['law']:3s}] "
                        f"TIR {a.get('tir', '?'):>5}%  Par {a.get('paridad', '?')}%"
                    )

        title = 'Bonos AR'
        body = '\n'.join(lines) if lines else 'Sin datos'
        return title, body

    def _get_spread_history(self, al_sym: str, gd_sym: str, days: int = 60) -> list[float]:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.tir AS al_tir, g.tir AS gd_tir
                    FROM bonds_tir_history a
                    JOIN bonds_tir_history g ON a.fecha = g.fecha AND g.symbol = %s
                    WHERE a.symbol = %s
                    ORDER BY a.fecha DESC
                    LIMIT %s
                """, (gd_sym, al_sym, days))
                return [
                    round((float(r['al_tir']) - float(r['gd_tir'])) * 100, 1)
                    for r in cur.fetchall()
                ]
        finally:
            conn.close()
