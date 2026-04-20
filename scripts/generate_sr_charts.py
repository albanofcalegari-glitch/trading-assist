"""
generate_sr_charts.py — Genera PDFs con gráficos de velas + soportes/resistencias V2.

Uso:
    python scripts/generate_sr_charts.py AAPL AMD MCD OKLO
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

from db.connection import get_conn
from strategies.dynamic_supports import get_dynamic_supports
from strategies.dynamic_resistances import get_dynamic_resistances
from datetime import date


SUP_COLORS = {'long': '#22c55e', 'mid': '#facc15', 'short': '#06b6d4'}
SUP_LABELS = {'long': 'Soporte LP', 'mid': 'Soporte MP', 'short': 'Soporte CP'}
RES_COLORS = {'long': '#ef4444', 'mid': '#fb923c', 'short': '#f43f5e'}
RES_LABELS = {'long': 'Resistencia LP', 'mid': 'Resistencia MP', 'short': 'Resistencia CP'}


def _find_bar_idx(df_index, fecha_str):
    t = pd.Timestamp(fecha_str)
    diffs = abs(df_index - t)
    return diffs.argmin()


def _add_tier_line(tier, df, n, colors, labels, tier_name, addplots, legend_items, is_resistance=False):
    if not tier or not isinstance(tier, dict):
        return
    if 'anchor1' not in tier or 'anchor2' not in tier:
        return

    color = colors[tier_name]
    label_prefix = labels[tier_name]

    if tier.get('kind') == 'horizontal':
        if is_resistance:
            val = tier.get('zone_ceiling', tier.get('current_value', 0))
        else:
            val = tier.get('current_value', 0)
        a1idx = _find_bar_idx(df.index, tier['anchor1']['fecha'])
        line_vals = np.full(n, np.nan)
        for i in range(a1idx, n):
            line_vals[i] = val
        addplots.append(mpf.make_addplot(line_vals, color=color, width=1.5, linestyle='--'))
        legend_items.append((color, '--', f'{label_prefix} (horiz ${val:.0f})'))
    else:
        a1v = tier['anchor1']['value']
        a2v = tier['anchor2']['value']
        a1idx = _find_bar_idx(df.index, tier['anchor1']['fecha'])
        a2idx = _find_bar_idx(df.index, tier['anchor2']['fecha'])
        if a2idx <= a1idx:
            return
        lg1 = np.log(a1v)
        lgS = (np.log(a2v) - lg1) / (a2idx - a1idx)
        line_vals = np.full(n, np.nan)
        for i in range(a1idx, n):
            line_vals[i] = np.exp(lg1 + lgS * (i - a1idx))
        addplots.append(mpf.make_addplot(line_vals, color=color, width=1.5))
        legend_items.append((color, '-', f'{label_prefix} ({tier.get("status", "?")})'))


def generate_chart(symbol: str, out_path: str, fecha: date | None = None) -> bool:
    fecha = fecha or date.today()

    sup = get_dynamic_supports(symbol, fecha)
    res = get_dynamic_resistances(symbol, fecha)

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fecha, open, high, low, close, volume FROM ohlcv_extended
               WHERE simbolo=%s AND timeframe='D'
               AND fecha >= '2024-10-01' AND fecha <= %s
               ORDER BY fecha""",
            (symbol, fecha),
        )
        rows = cur.fetchall()
    conn.close()

    if not rows:
        print(f'  {symbol}: sin datos diarios')
        return False

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

    if not addplots:
        print(f'  {symbol}: sin lineas para dibujar')
        return False

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

    fig, axes = mpf.plot(
        df, type='candle', style=style, addplot=addplots,
        volume=True, figsize=(16, 8),
        title=dict(title=f'{symbol} \u2014 Soportes y Resistencias V2', color='#e2e8f0', fontsize=14),
        ylabel='Precio (USD)', ylabel_lower='Volumen',
        returnfig=True,
    )

    ax = axes[0]
    handles = [
        Line2D([0], [0], color=c, linestyle=ls, linewidth=2, label=lbl)
        for c, ls, lbl in legend_items
    ]
    ax.legend(
        handles=handles, loc='upper left', fontsize=7,
        facecolor='#1e293b', edgecolor='#334155', labelcolor='#e2e8f0',
    )

    fig.savefig(out_path, bbox_inches='tight', dpi=150)
    plt.close()
    return True


if __name__ == '__main__':
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ['AAPL', 'AMD', 'MCD', 'OKLO']
    base = os.path.join(os.path.dirname(__file__), '..')
    for sym in tickers:
        out = os.path.abspath(os.path.join(base, f'{sym}_SR_chart.pdf'))
        print(f'Generando {sym}...')
        if generate_chart(sym, out):
            print(f'  OK -> {out}')
        else:
            print(f'  SKIP')
    print('Done!')
