"""
generate_zones_pdf.py — Genera PDF con gráficos de cada ticker mostrando
zonas horizontales de soporte y resistencia.

Uso:
    python scripts/generate_zones_pdf.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle
from datetime import date, timedelta

from db.connection import get_conn
from strategies.horizontal_zones import detect_horizontal_zones


# ── Config ────────────────────────────────────────────────────────────────────

TICKERS = ['GOOGL', 'AAPL', 'META', 'NU', 'VIST', 'NVDA', 'MSFT', 'BABA', 'DIS']
DAYS_CHART = 365          # 1 año de velas diarias en el chart
OUTPUT = os.path.join(os.path.dirname(__file__), '..', 'output', 'zonas_horizontales.pdf')


# ── Tema oscuro estilo TradingView ────────────────────────────────────────────

TV_STYLE = mpf.make_mpf_style(
    base_mpf_style='nightclouds',
    marketcolors=mpf.make_marketcolors(
        up='#26a69a', down='#ef5350',
        edge={'up': '#26a69a', 'down': '#ef5350'},
        wick={'up': '#26a69a', 'down': '#ef5350'},
        volume={'up': '#26a69a80', 'down': '#ef535080'},
    ),
    facecolor='#131722',
    edgecolor='#1e222d',
    figcolor='#131722',
    gridcolor='#1e222d',
    gridstyle='--',
    gridaxis='both',
    y_on_right=True,
    rc={
        'axes.labelcolor': '#d1d4dc',
        'xtick.color':     '#787b86',
        'ytick.color':     '#787b86',
        'font.size':       9,
    },
)


# ── Carga de datos ────────────────────────────────────────────────────────────

def load_daily(symbol: str, days: int) -> pd.DataFrame:
    cutoff = date.today() - timedelta(days=days)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha, open, high, low, close, volume
                FROM ohlcv_extended
                WHERE simbolo = %s AND timeframe = 'D' AND fecha >= %s
                ORDER BY fecha ASC
            """, (symbol, cutoff))
            rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df.set_index('fecha', inplace=True)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    df['volume'] = df['volume'].astype(int)
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
    return df


# ── Generación de chart ──────────────────────────────────────────────────────

def make_chart(symbol: str, df: pd.DataFrame, zones: dict, fig_width=16, fig_height=8):
    """Genera figure con candlestick + zonas horizontales."""

    support_zones = zones.get('support_zones', [])
    resistance_zones = zones.get('resistance_zones', [])
    price = zones.get('current_price', 0)

    # Preparar addplots (vacío, mplfinance lo necesita)
    fig, axlist = mpf.plot(
        df,
        type='candle',
        style=TV_STYLE,
        volume=True,
        returnfig=True,
        figsize=(fig_width, fig_height),
        tight_layout=True,
        panel_ratios=(4, 1),
    )

    ax = axlist[0]

    # Dibujar zonas de soporte
    for z in support_zones:
        rank = z.get('rank', 'tertiary')
        strength = z.get('strength', 'normal')
        alpha = 0.25 if rank == 'primary' else (0.15 if rank == 'secondary' else 0.08)
        color = '#26a69a'
        lw = 2 if rank == 'primary' else 1

        ax.axhspan(z['zone_low'], z['zone_high'], color=color, alpha=alpha, zorder=1)
        ax.axhline(z['center'], color=color, linewidth=lw,
                    linestyle='-' if rank == 'primary' else '--', alpha=0.6, zorder=2)

        label = f"S {rank[0].upper()}"
        if strength == 'weak':
            label += ' (weak)'
        label += f"  ${z['center']:.1f}  [{z['total_touches']}t]"
        ax.text(df.index[2], z['zone_high'], label,
                fontsize=7.5, color=color, alpha=0.9,
                verticalalignment='bottom', fontweight='bold')

    # Dibujar zonas de resistencia
    for z in resistance_zones:
        rank = z.get('rank', 'tertiary')
        strength = z.get('strength', 'normal')
        alpha = 0.25 if rank == 'primary' else (0.15 if rank == 'secondary' else 0.08)
        color = '#ef5350'
        lw = 2 if rank == 'primary' else 1

        ax.axhspan(z['zone_low'], z['zone_high'], color=color, alpha=alpha, zorder=1)
        ax.axhline(z['center'], color=color, linewidth=lw,
                    linestyle='-' if rank == 'primary' else '--', alpha=0.6, zorder=2)

        label = f"R {rank[0].upper()}"
        if strength == 'weak':
            label += ' (weak)'
        label += f"  ${z['center']:.1f}  [{z['total_touches']}t]"
        ax.text(df.index[2], z['zone_low'], label,
                fontsize=7.5, color=color, alpha=0.9,
                verticalalignment='top', fontweight='bold')

    # Título
    n_s = len(support_zones)
    n_r = len(resistance_zones)
    title = f"{symbol}  —  ${price:.2f}  |  Soportes: {n_s}  Resistencias: {n_r}"
    ax.set_title(title, fontsize=13, color='#d1d4dc', fontweight='bold', pad=12)

    return fig


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

    print(f'\nGenerando PDF con {len(TICKERS)} tickers...\n')

    with PdfPages(OUTPUT) as pdf:
        for sym in TICKERS:
            print(f'  {sym:6s}', end='  ', flush=True)

            df = load_daily(sym, DAYS_CHART)
            if df.empty:
                print('SIN DATOS — skip')
                continue

            zones = detect_horizontal_zones(sym)
            n_s = len(zones.get('support_zones', []))
            n_r = len(zones.get('resistance_zones', []))
            print(f'candles={len(df):4d}  S={n_s} R={n_r}', end='  ', flush=True)

            fig = make_chart(sym, df, zones)
            pdf.savefig(fig, facecolor='#131722')
            plt.close(fig)
            print('OK')

    print(f'\n  PDF guardado en: {os.path.abspath(OUTPUT)}\n')


if __name__ == '__main__':
    main()
