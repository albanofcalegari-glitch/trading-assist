"""
generate_sr_charts.py — Genera PDF multi-página con velas + soportes/resistencias dinámicos.

Uso:
    python scripts/generate_sr_charts.py AAPL TSLA GOOGL NU KO OKLO AMD JNJ MELI
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd
import numpy as np
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.backends.backend_pdf import PdfPages

from db.connection import get_conn
from strategies.dynamic_supports import get_dynamic_supports
from strategies.dynamic_resistances import get_dynamic_resistances
from datetime import date


SUP_COLORS = {'long': '#22c55e', 'mid': '#facc15', 'short': '#06b6d4'}
SUP_LABELS = {'long': 'Soporte LP', 'mid': 'Soporte MP', 'short': 'Soporte CP'}
RES_COLORS = {'long': '#ef4444', 'mid': '#fb923c', 'short': '#f43f5e'}
RES_LABELS = {'long': 'Resistencia LP', 'mid': 'Resistencia MP', 'short': 'Resistencia CP'}


def _add_tier_line(tier, df, n, colors, labels, tier_name, addplots, legend_items, is_resistance=False):
    if not tier or not isinstance(tier, dict):
        return
    color = colors[tier_name]
    label_prefix = labels[tier_name]

    if tier.get('kind') == 'horizontal':
        if is_resistance:
            val = tier.get('zone_ceiling', tier.get('current_value', 0))
        else:
            val = tier.get('current_value', 0)
        pts = tier.get('line_points', [])
        if not pts:
            return
        pt_map = {pd.Timestamp(p['fecha']): p['value'] for p in pts}
        line_vals = np.array([pt_map.get(d, np.nan) for d in df.index])
        addplots.append(mpf.make_addplot(line_vals, color=color, width=1.5, linestyle='--'))
        legend_items.append((color, '--', f'{label_prefix} (horiz ${val:.0f})'))
    else:
        pts = tier.get('line_points', [])
        if not pts:
            return
        pt_map = {pd.Timestamp(p['fecha']): p['value'] for p in pts}
        line_vals = np.array([pt_map.get(d, np.nan) for d in df.index])
        status = tier.get('status', '?')
        touches = tier.get('touches', 0)
        dist = tier.get('distance_pct', 0)
        addplots.append(mpf.make_addplot(line_vals, color=color, width=1.5))
        legend_items.append((color, '-', f'{label_prefix} t={touches} dist={dist:.1f}% ({status})'))


def generate_chart(symbol: str, fecha: date | None = None):
    fecha = fecha or date.today()

    sup = get_dynamic_supports(symbol, fecha, tf='D')
    res = get_dynamic_resistances(symbol, fecha, tf='D')

    earliest = '2024-01-01'
    for data in (sup, res):
        for tier_name in ('long', 'mid', 'short'):
            t = data.get(tier_name)
            if t and t.get('anchor1'):
                a1 = t['anchor1']['fecha']
                if isinstance(a1, str) and a1 < earliest:
                    earliest = a1

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fecha, open, high, low, close, volume FROM ohlcv_extended
               WHERE simbolo=%s AND timeframe='D'
               AND fecha >= %s AND fecha <= %s
               ORDER BY fecha""",
            (symbol, earliest, fecha),
        )
        rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f'  {symbol}: sin datos diarios')
        return None

    df = pd.DataFrame(rows)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df.set_index('fecha', inplace=True)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    df['volume'] = df['volume'].astype(float)
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    n = len(df)

    addplots: list = []
    legend_items: list = []

    for tier_name in ('long', 'mid', 'short'):
        _add_tier_line(sup.get(tier_name), df, n, SUP_COLORS, SUP_LABELS,
                       tier_name, addplots, legend_items, is_resistance=False)

    for tier_name in ('long', 'mid', 'short'):
        _add_tier_line(res.get(tier_name), df, n, RES_COLORS, RES_LABELS,
                       tier_name, addplots, legend_items, is_resistance=True)

    mc = mpf.make_marketcolors(
        up='#22c55e', down='#ef4444', edge='inherit',
        wick={'up': '#22c55e', 'down': '#ef4444'},
        volume={'up': '#22c55e66', 'down': '#ef444466'},
    )
    style = mpf.make_mpf_style(
        marketcolors=mc, base_mpf_style='nightclouds',
        facecolor='#0f172a', edgecolor='#1e293b',
        figcolor='#0f172a', gridcolor='#1e293b44',
        rc={
            'axes.labelcolor': '#94a3b8',
            'xtick.color': '#94a3b8',
            'ytick.color': '#94a3b8',
        },
    )

    chart_type = 'candle' if n <= 500 else 'line'
    kwargs = dict(
        type=chart_type, style=style, volume=True,
        figsize=(16, 8), warn_too_much_data=n + 1,
        title=dict(title=f'{symbol} — Soportes y Resistencias (D)', color='#e2e8f0', fontsize=14),
        ylabel='Precio (USD)', ylabel_lower='Volumen',
        yscale='log',
        returnfig=True,
    )
    if addplots:
        kwargs['addplot'] = addplots

    fig, axes = mpf.plot(df, **kwargs)

    ax = axes[0]
    if legend_items:
        handles = [
            Line2D([0], [0], color=c, linestyle=ls, linewidth=2, label=lbl)
            for c, ls, lbl in legend_items
        ]
        ax.legend(
            handles=handles, loc='upper left', fontsize=7,
            facecolor='#1e293b', edgecolor='#334155', labelcolor='#e2e8f0',
        )
    else:
        ax.text(0.5, 0.5, 'Sin soportes ni resistencias válidos',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=14, color='#94a3b8')

    return fig


if __name__ == '__main__':
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['AAPL', 'TSLA', 'GOOGL', 'NU', 'KO', 'OKLO', 'AMD', 'JNJ', 'MELI']
    base = os.path.join(os.path.dirname(__file__), '..')
    out_path = os.path.abspath(os.path.join(base, 'SR_charts.pdf'))

    with PdfPages(out_path) as pdf:
        for sym in tickers:
            print(f'Generando {sym}...')
            fig = generate_chart(sym)
            if fig:
                pdf.savefig(fig, bbox_inches='tight', dpi=150)
                plt.close(fig)
                print(f'  OK')
            else:
                print(f'  SKIP')

    print(f'\nPDF → {out_path}')
