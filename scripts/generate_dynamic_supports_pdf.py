"""
generate_dynamic_supports_pdf.py  --  PDF con SOPORTES DINAMICOS.

Script standalone.  Usa `strategies.dynamic_supports.get_dynamic_supports()`
como unica fuente de verdad — asi el PDF muestra exactamente lo mismo que
rinde la API productiva (incluida la deteccion de ZONA horizontal para
lateralizaciones recientes: ORCL/MSFT/PLTR/GOOGL al 2026-04).

Tiers:
  - long   (verde)   diagonal estructural
  - mid    (amarillo) diagonal rally reciente
  - short  (cyan)    diagonal corta OR ZONA horizontal (si hay lateralizacion)

Uso:
    python scripts/generate_dynamic_supports_pdf.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pandas as pd
import mplfinance as mpf
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter
from datetime import date

from db.connection import get_conn
from strategies.dynamic_supports import get_dynamic_supports


TICKERS = [
    'ORCL', 'MSFT', 'PLTR', 'GOOGL',
    'AAPL', 'SHOP', 'NVDA', 'META', 'AMZN', 'TSLA', 'SPY',
]

OUTPUT = os.path.join(
    os.path.dirname(__file__), '..', 'output', 'soportes_dinamicos.pdf'
)


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


# ── Carga de OHLCV (replicando lo que hace el modulo productivo) ─────────────

def load_ohlcv_df(symbol: str, tf_used: str) -> pd.DataFrame:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha, open, high, low, close, volume
                FROM ohlcv_extended
                WHERE simbolo = %s AND timeframe = %s
                ORDER BY fecha ASC
            """, (symbol, tf_used))
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


# ── Chart ────────────────────────────────────────────────────────────────────

GREEN, YELLOW, CYAN = '#00e676', '#ffd54f', '#4fc3f7'
TIER_COLORS = {'long': GREEN, 'mid': YELLOW, 'short': CYAN}
TIER_LABELS = {'long': 'LARGO PLAZO', 'mid': 'MEDIANO PLAZO', 'short': 'CORTO PLAZO'}


def _date_to_idx(df: pd.DataFrame, fecha_iso: str) -> int | None:
    """Mapea una fecha ISO al indice posicional del df (o None si no esta)."""
    ts = pd.Timestamp(fecha_iso)
    try:
        return int(df.index.get_loc(ts))
    except KeyError:
        # buscar el primer indice >= ts (para fechas semanales que caen martes, etc.)
        idxs = np.where(df.index >= ts)[0]
        return int(idxs[0]) if len(idxs) else None


def draw_tier(ax, df: pd.DataFrame, tier: dict, color: str) -> float | None:
    """Dibuja un tier. Horizontal = zona (axhspan + 2 lineas), diagonal = linea."""
    if tier.get('kind') == 'horizontal' and 'zone_top' in tier:
        floor = tier['current_value']
        top   = tier['zone_top']
        # banda semi-transparente
        ax.axhspan(floor, top, facecolor=color, alpha=0.12, zorder=4)
        # borde inferior (piso) solido + borde superior (tope) punteado
        ax.axhline(floor, color=color, linewidth=1.5, linestyle='-',
                   alpha=0.95, zorder=6)
        ax.axhline(top,   color=color, linewidth=1.0, linestyle=':',
                   alpha=0.85, zorder=6)
        return floor

    # Diagonal: `line_points` viene en fechas; mapeo a indices del df.
    pts = tier.get('line_points') or []
    if not pts:
        return None
    xs, ys = [], []
    for p in pts:
        idx = _date_to_idx(df, p['fecha'])
        if idx is None:
            continue
        xs.append(idx)
        ys.append(p['value'])
    if len(xs) < 2:
        return None
    ax.plot(xs, ys, color=color, linewidth=1.3, linestyle='-',
            alpha=0.95, zorder=6)
    return float(ys[-1])


def make_chart(symbol: str, df: pd.DataFrame, res: dict):
    n     = len(df)
    price = float(df['Close'].iloc[-1])
    lows  = df['Low'].values
    highs = df['High'].values

    fig, axlist = mpf.plot(
        df, type='candle', style=TV_STYLE, volume=True, returnfig=True,
        figsize=(16, 9), tight_layout=True, panel_ratios=(4, 1),
    )
    ax = axlist[0]
    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v:.2f}'))

    projected = {}
    for key in ('long', 'mid', 'short'):
        tier = res.get(key)
        if tier:
            projected[key] = draw_tier(ax, df, tier, TIER_COLORS[key])

    ax.set_xlim(-4, n + 6)
    vis_min = float(lows.min())
    vis_max = float(highs.max())
    for key, val in projected.items():
        if val is not None:
            factor = {'long': 0.85, 'mid': 0.90, 'short': 0.92}[key]
            vis_min = min(vis_min, val * factor)
    vis_min = max(vis_min, 0.01)
    ratio = vis_max / vis_min
    pad   = ratio ** 0.05
    ax.set_ylim(vis_min / pad, vis_max * pad)

    # ── Caja de datos ────────────────────────────────────────────────────────
    def pct_vs(x):
        if x is None or x == 0:
            return '--'
        d = (price / x - 1) * 100
        return f'{"+" if d >= 0 else ""}{d:.1f}%'

    first_date = df.index[0].strftime('%Y-%m-%d')
    tf_used = res.get('timeframe_used', '?')
    lines = [
        f'Timeframe: {tf_used} ({n} barras)   escala: LOG',
        f'Desde:     {first_date}',
        f'Precio:    ${price:.2f}',
    ]
    for key in ('long', 'mid', 'short'):
        tier = res.get(key)
        if not tier:
            continue
        kind = tier.get('kind', 'ascending')
        header = f'SOPORTE {TIER_LABELS[key]}  ({kind})  [{tier["status"]}]'
        lines.append('')
        lines.append(header)
        if kind == 'horizontal':
            floor = tier['current_value']
            top = tier.get('zone_top', floor)
            lines.append(f'  zona:       ${floor:7.2f}  -  ${top:7.2f}')
            lines.append(f'  dist piso:  {pct_vs(floor)}   (touches: {tier["touches"]})')
        else:
            cur = tier['current_value']
            slope_ann = tier['slope_annual_pct']
            a1 = tier['anchor1']; a2 = tier['anchor2']
            lines.append(f'  valor hoy:  ${cur:7.2f}   dist {pct_vs(cur)}')
            lines.append(f'  pendiente:  {slope_ann:+.1f}% anual')
            lines.append(f'  ancla #1:   {a1["fecha"][:7]}  ${a1["value"]:.2f}')
            lines.append(f'  ancla #2:   {a2["fecha"][:7]}  ${a2["value"]:.2f}')
            lines.append(f'  toques: {tier["touches"]}   rupturas: {tier["violations"]}')

    if not (res.get('long') or res.get('mid') or res.get('short')):
        lines.append('')
        lines.append('Sin soportes detectados.')

    ax.text(
        0.012, 0.985, '\n'.join(lines),
        transform=ax.transAxes, fontsize=9, color='#d1d4dc',
        family='monospace', verticalalignment='top',
        bbox=dict(facecolor='#0d1117', edgecolor='#2a2e39',
                  alpha=0.88, boxstyle='round,pad=0.5'),
        zorder=10,
    )

    # Regimen: priorizar short > mid > long
    ref = projected.get('short') or projected.get('mid') or projected.get('long')
    regime = ''
    color_ = '#d1d4dc'
    if ref and price > ref * 1.03:
        regime = 'SOBRE SOPORTE'
        color_ = '#26a69a'
    elif ref and price < ref * 0.97:
        regime = 'DEBAJO DEL SOPORTE (roto)'
        color_ = '#ef5350'
    elif ref:
        regime = 'TESTEANDO SOPORTE'
        color_ = '#ffa726'

    ax.set_title(
        f'{symbol}   ${price:.2f}    |   {regime}',
        fontsize=13, color=color_, fontweight='bold', pad=12,
    )
    return fig


# ── Portada ──────────────────────────────────────────────────────────────────

def _cover_page(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=(16, 9), facecolor='#131722')
    ax = fig.add_subplot(111)
    ax.set_facecolor('#131722')
    ax.axis('off')

    ax.text(0.5, 0.94, 'SOPORTES DINAMICOS  -  3 tiers + lateralizacion',
            ha='center', va='center', fontsize=22, color='#d1d4dc',
            fontweight='bold', transform=ax.transAxes)

    body = (
        'Tres soportes por chart (mismo calculo que la API productiva):\n\n'
        '   VERDE     LARGO PLAZO       diagonal del rally estructural vigente.\n'
        '                               Primer ancla en 30%-98% del historico,\n'
        '                               descarta si quedo >50% por debajo del precio\n'
        '                               (linea obsoleta).\n\n'
        '   AMARILLO  MEDIANO PLAZO     diagonal del sub-rally mas reciente,\n'
        '                               primer ancla en ultimo 20%.\n\n'
        '   CYAN      CORTO PLAZO       dos modos:\n'
        '             A. LATERALIZACION (ZONA)\n'
        '                Si en las ultimas 10 semanas: stdev/mean de lows < 8%\n'
        '                AND el piso no cedio mas de 12% AND >= 2 bars tocan\n'
        '                el piso AND slope no es un cohete (<100%/yr).\n'
        '                --> Zona piso(=2do low mas bajo) .. piso*1.05\n'
        '                    Dibujada como banda translucida + linea piso + tope.\n'
        '                --> Casos 2026-04: ORCL, MSFT, PLTR, GOOGL, AAPL, NVDA.\n\n'
        '             B. DIAGONAL\n'
        '                Si no hay lateralizacion pero hay chain de higher-lows,\n'
        '                regresion lineal en log-space sobre la cadena.\n\n'
        'Algoritmo comun para diagonales (long/mid):\n'
        '   - Pivots semanales con ventana adaptativa (6 o 12 bars).\n'
        '   - Log-space: los soportes exponenciales se dibujan como rectas.\n'
        '   - Regresion sobre cadenas de higher-lows (prioritario) + lineas\n'
        '     exactas entre 2 anclas (fallback).\n'
        '   - Filtros: obsolescencia, invalidacion por cambio de tendencia,\n'
        '     proyeccion no muy por encima del precio actual.\n\n'
        'Estados:\n'
        '   ACTIVE      precio > soporte +3%\n'
        '   TESTING     precio dentro de +/-3%\n'
        '   BROKEN      precio < soporte -3%\n\n'
        'Escala LOG en todos los charts: asi la diagonal exponencial se ve\n'
        'como recta, igual que TradingView.\n'
    )

    ax.text(0.05, 0.86, body, fontsize=10.5, color='#d1d4dc',
            family='monospace', verticalalignment='top',
            transform=ax.transAxes)

    ax.text(0.5, 0.02,
            'Trading Assist - fuente: strategies.dynamic_supports.get_dynamic_supports()',
            ha='center', fontsize=8, color='#787b86', style='italic',
            transform=ax.transAxes)

    pdf.savefig(fig, facecolor='#131722')
    plt.close(fig)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    print(f'\nGenerando PDF de soportes dinamicos para {len(TICKERS)} tickers...\n')

    with PdfPages(OUTPUT) as pdf:
        _cover_page(pdf)
        for sym in TICKERS:
            print(f'  {sym:6s}', end='  ', flush=True)
            res = get_dynamic_supports(sym)
            tf = res.get('timeframe_used')
            if not tf:
                print('SIN DATOS -- skip')
                continue
            df = load_ohlcv_df(sym, tf)
            if df.empty:
                print('SIN DATOS -- skip')
                continue
            print(f'tf={tf}  bars={len(df):4d}', end='  ', flush=True)
            try:
                fig = make_chart(sym, df, res)
                pdf.savefig(fig, facecolor='#131722', bbox_inches='tight')
                plt.close(fig)
                tier_summary = []
                for key in ('long','mid','short'):
                    t = res.get(key)
                    if t:
                        tier_summary.append(f'{key[0].upper()}={t.get("kind","?")[:3]}')
                print(f'OK  [{",".join(tier_summary) or "---"}]')
            except Exception as e:
                print(f'ERROR: {e}')
                import traceback; traceback.print_exc()

    print(f'\n  PDF guardado en: {os.path.abspath(OUTPUT)}\n')


if __name__ == '__main__':
    main()
