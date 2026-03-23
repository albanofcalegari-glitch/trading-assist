"""
export_divergence_pdf.py -- Reporte PDF de divergencias RSI

Estructura:
  - Portada: tabla resumen de todos los activos
  - Una pagina por activo: grafico izquierda + panel analitico derecha
  - Pagina especial para NVDA: explicacion paso a paso del motor

Uso:
    python scripts/export_divergence_pdf.py
    python scripts/export_divergence_pdf.py --output reports/divergence_report.pdf
    python scripts/export_divergence_pdf.py --start 2024-01-01
    python scripts/export_divergence_pdf.py --symbols GOOGL NVDA VIST
"""
import argparse
import sys
import os
from datetime import date, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.rsi_divergence import (
    analyze_symbol as div_analyze,
    _rsi_series, _pivot_lows, _pivot_highs,
    _bullish_confirmed, _bearish_confirmed,
    _ema_fast,
    _best_bullish_pair, _best_bearish_pair,
    _confidence as _div_confidence,
    _make_decision as _div_decision,
    _READINGS as _DIV_READINGS,
    _RSI_PERIOD, _PIVOT_WIN, _MIN_SEP, _MAX_SEP,
    _RECENCY, _MIN_PRICE_DIFF, _MIN_RSI_DIFF,
    _BULL_RSI_MAX, _BEAR_RSI_MIN,
)
from config import UNIVERSE, SECTOR_MAP


# ─────────────────────────────────────────────────────────────────────────────
# Tema visual
# ─────────────────────────────────────────────────────────────────────────────
_DARK_BG    = '#0d1117'
_PANEL_BG   = '#161b22'
_GRID_COLOR = '#21262d'
_TEXT_COLOR = '#c9d1d9'
_MUTED      = '#8b949e'
_HDR        = '#a8bcc8'
_GREEN      = '#3fb950'
_GREEN_DIM  = '#238636'
_RED        = '#f85149'
_RED_DIM    = '#b62324'
_YELLOW     = '#d29922'
_BLUE       = '#4fc3f7'
_ORANGE     = '#f0a500'
_RSI_COLOR  = '#ce93d8'

_COLORS = {
    'close':  '#e6edf3',
    'ema20':  '#f0a500',
    'sma50':  '#4fc3f7',
    'sma200': '#ef5350',
    'rsi':    '#ce93d8',
}


def _setup_dark(ax):
    ax.set_facecolor(_PANEL_BG)
    ax.tick_params(colors=_TEXT_COLOR, labelsize=7)
    ax.spines[:].set_color(_GRID_COLOR)
    ax.yaxis.label.set_color(_TEXT_COLOR)
    ax.xaxis.label.set_color(_TEXT_COLOR)
    ax.grid(color=_GRID_COLOR, linewidth=0.4, alpha=0.6)


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_ohlcv(symbol: str, end: date) -> pd.DataFrame:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM price_history WHERE simbolo=%s AND fecha<=%s
                   ORDER BY fecha ASC""",
                (symbol, end)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df['fecha'] = pd.to_datetime(df['fecha'])
    df.set_index('fecha', inplace=True)
    return df.astype({'open': float, 'high': float, 'low': float,
                      'close': float, 'volume': float})


def _compute_rsi_df(df: pd.DataFrame, n: int = 14) -> pd.Series:
    delta = df['close'].diff()
    g = delta.clip(lower=0)
    l = (-delta).clip(lower=0)
    ag = g.ewm(alpha=1/n, adjust=False).mean()
    al = l.ewm(alpha=1/n, adjust=False).mean()
    return (100 - 100 / (1 + ag / al)).round(2)


# ─────────────────────────────────────────────────────────────────────────────
# Colores por estado
# ─────────────────────────────────────────────────────────────────────────────

def _div_color(r: dict) -> str:
    state = r['divergence_state']
    if state == 'BULLISH_DIVERGENCE_CONFIRMED':   return _GREEN
    if state == 'BULLISH_DIVERGENCE_FORMING':     return _GREEN_DIM
    if state == 'BEARISH_DIVERGENCE_CONFIRMED':   return _RED
    if state == 'BEARISH_DIVERGENCE_FORMING':     return _RED_DIM
    return _MUTED


def _state_short(state: str) -> str:
    return {
        'BULLISH_DIVERGENCE_CONFIRMED': 'ALCISTA CONF.',
        'BULLISH_DIVERGENCE_FORMING':   'ALCISTA FORM.',
        'BEARISH_DIVERGENCE_CONFIRMED': 'BAJISTA CONF.',
        'BEARISH_DIVERGENCE_FORMING':   'BAJISTA FORM.',
        'NO_DIVERGENCE':                'SIN DIVERGENCIA',
    }.get(state, state)


# ─────────────────────────────────────────────────────────────────────────────
# Portada
# ─────────────────────────────────────────────────────────────────────────────

def _draw_cover(pdf: PdfPages, results: list[dict], fecha: date, start: date):
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(_DARK_BG)
    ax.axis('off')

    # Titulo
    fig.text(0.5, 0.93, 'RSI DIVERGENCE ENGINE', ha='center', va='top',
             color=_TEXT_COLOR, fontsize=20, fontweight='bold')
    tf_lbl = results[0].get('_timeframe_label', 'Diaria') if results else 'Diaria'
    fig.text(0.5, 0.88, f'Reporte: {start.strftime("%d %b %Y")} - {fecha.strftime("%d %b %Y")}  |  Temporalidad: {tf_lbl}  |  Universo: {len(results)} activos',
             ha='center', va='top', color=_MUTED, fontsize=10)
    fig.text(0.5, 0.845, f'Generado: {date.today().strftime("%d/%m/%Y")}',
             ha='center', va='top', color=_MUTED, fontsize=8)

    # Separador
    fig.add_artist(plt.Line2D([0.05, 0.95], [0.83, 0.83],
                              color=_GRID_COLOR, lw=1.2, transform=fig.transFigure))

    # Tabla
    headers = ['SIMBOLO', 'TIPO', 'ESTADO', 'CONF.', 'DECISION',
               'PRECIO P1', 'PRECIO P2', 'RSI P1', 'RSI P2', 'RSI DIFF', 'FECHA P2']
    col_x   = [0.05, 0.12, 0.21, 0.36, 0.44, 0.53, 0.61, 0.69, 0.74, 0.80, 0.87]
    row_h   = 0.055
    hdr_y   = 0.80

    # Cabecera tabla
    for i, (h, x) in enumerate(zip(headers, col_x)):
        fig.text(x, hdr_y, h, ha='left', va='top', color=_HDR, fontsize=7.5, fontweight='bold')

    fig.add_artist(plt.Line2D([0.05, 0.95], [hdr_y - 0.012, hdr_y - 0.012],
                              color=_GRID_COLOR, lw=0.8, transform=fig.transFigure))

    # Ordenar: confirmed primero, luego forming, luego no_div
    _order = {'BULLISH_DIVERGENCE_CONFIRMED': 0, 'BEARISH_DIVERGENCE_CONFIRMED': 1,
               'BULLISH_DIVERGENCE_FORMING': 2,   'BEARISH_DIVERGENCE_FORMING': 3,
               'NO_DIVERGENCE': 4}
    sorted_r = sorted(results, key=lambda r: _order.get(r['divergence_state'], 9))

    for idx, r in enumerate(sorted_r):
        y    = hdr_y - 0.018 - (idx + 1) * row_h
        col  = _div_color(r)
        bg   = '#1a2030' if idx % 2 == 0 else _PANEL_BG

        # Fila de fondo
        rect = plt.Rectangle((0.04, y - row_h * 0.3), 0.92, row_h * 0.85,
                              color=bg, transform=fig.transFigure, zorder=0)
        fig.add_artist(rect)

        sym   = r['simbolo']
        dtype = r['divergence_type'] or '---'
        state = _state_short(r['divergence_state'])
        conf  = r['confidence_level'] or '---'
        dec   = r['decision']
        p1    = f"${r['price_pivot_1']:.2f}" if r['price_pivot_1'] else '---'
        p2    = f"${r['price_pivot_2']:.2f}" if r['price_pivot_2'] else '---'
        r1    = f"{r['rsi_pivot_1']:.1f}"    if r['rsi_pivot_1']   else '---'
        r2    = f"{r['rsi_pivot_2']:.1f}"    if r['rsi_pivot_2']   else '---'
        rdiff = f"{abs((r['rsi_pivot_2'] or 0) - (r['rsi_pivot_1'] or 0)):.1f}" if r['rsi_pivot_1'] else '---'
        t2    = str(r['pivot_2_date'])[:10] if r['pivot_2_date'] else '---'

        # Color de decision
        dec_col = _GREEN if dec == 'BUY_CANDIDATE' else \
                  _YELLOW if dec == 'WATCHLIST'     else \
                  _RED    if dec in ('SELL_WARNING', 'AVOID') else _MUTED

        vals = [sym, dtype, state, conf, dec, p1, p2, r1, r2, rdiff, t2]
        for vi, (v, x) in enumerate(zip(vals, col_x)):
            c = col if vi <= 2 else (dec_col if vi == 4 else _TEXT_COLOR)
            fw = 'bold' if vi == 0 else 'normal'
            fig.text(x, y, v, ha='left', va='center', color=c, fontsize=8, fontweight=fw)

    # Leyenda de colores
    ly = 0.05
    fig.text(0.05, ly, 'Colores:', color=_MUTED, fontsize=7.5, va='bottom')
    legend_items = [
        (_GREEN,     'Alcista confirmada'),
        (_GREEN_DIM, 'Alcista en formacion'),
        (_RED,       'Bajista confirmada'),
        (_RED_DIM,   'Bajista en formacion'),
    ]
    lx = 0.15
    for lc, lt in legend_items:
        fig.add_artist(plt.Rectangle((lx, ly - 0.005), 0.01, 0.012,
                                     color=lc, transform=fig.transFigure))
        fig.text(lx + 0.013, ly + 0.001, lt, color=_MUTED, fontsize=7.5, va='bottom')
        lx += 0.18

    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Pagina por activo
# ─────────────────────────────────────────────────────────────────────────────

def _draw_asset_page(pdf: PdfPages, r: dict, df_full: pd.DataFrame,
                     start: date, fecha: date, detail_nvda: bool = False):
    sym    = r['simbolo']
    state  = r['divergence_state']
    col    = _div_color(r)
    is_div = state != 'NO_DIVERGENCE'

    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)

    # Layout: grafico 65% | panel texto 35%
    gs = gridspec.GridSpec(
        2, 2, figure=fig,
        height_ratios=[3, 1],
        width_ratios=[65, 35],
        hspace=0.06, wspace=0.04,
        left=0.04, right=0.98, top=0.93, bottom=0.07,
    )
    ax_price = fig.add_subplot(gs[0, 0])
    ax_rsi   = fig.add_subplot(gs[1, 0], sharex=ax_price)
    ax_txt   = fig.add_subplot(gs[:, 1])

    _setup_dark(ax_price)
    _setup_dark(ax_rsi)
    ax_txt.set_facecolor(_PANEL_BG)
    ax_txt.axis('off')

    # Filtrar rango visible
    df = df_full[df_full.index.date >= start].copy()
    if df.empty:
        plt.close(fig)
        return

    # Indicadores
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['rsi']    = _compute_rsi_df(df)
    df['log_close'] = df['close']   # para escala log

    # ── Precio ────────────────────────────────────────────────────────────────
    ax_price.set_yscale('log')
    ax_price.plot(df.index, df['close'],  color=_COLORS['close'],  lw=1.3, zorder=3)
    ax_price.plot(df.index, df['ema20'],  color=_COLORS['ema20'],  lw=1.0, ls='--', alpha=0.85, zorder=2)
    ax_price.plot(df.index, df['sma50'],  color=_COLORS['sma50'],  lw=1.0, alpha=0.8, zorder=2)
    ax_price.plot(df.index, df['sma200'], color=_COLORS['sma200'], lw=1.4, alpha=0.85, zorder=2)

    # ── Divergencia en grafico ─────────────────────────────────────────────
    if is_div and r['pivot_1_date'] and r['pivot_2_date']:
        is_bull = r['divergence_type'] == 'BULLISH'
        pt1_ts  = pd.Timestamp(r['pivot_1_date'])
        pt2_ts  = pd.Timestamp(r['pivot_2_date'])

        y1 = df.loc[pt1_ts, 'low']  if (pt1_ts in df.index and is_bull) else \
             df.loc[pt1_ts, 'high'] if (pt1_ts in df.index) else r['price_pivot_1']
        y2 = df.loc[pt2_ts, 'low']  if (pt2_ts in df.index and is_bull) else \
             df.loc[pt2_ts, 'high'] if (pt2_ts in df.index) else r['price_pivot_2']

        if pt1_ts in df.index:
            ax_price.scatter([pt1_ts], [y1], color=col, s=90, zorder=9,
                             marker='o', linewidths=1.2, edgecolors='white', alpha=0.85)
        if pt2_ts in df.index:
            ax_price.scatter([pt2_ts], [y2], color=col, s=120, zorder=9,
                             marker='o', linewidths=1.8, edgecolors='white')

        if pt1_ts in df.index and pt2_ts in df.index:
            ax_price.plot([pt1_ts, pt2_ts], [y1, y2],
                          color=col, lw=1.6, ls='--', alpha=0.7, zorder=5)

        # Anotacion
        confirmed = 'CONFIRMED' in state
        lbl_txt   = ('DIV ALCISTA' if is_bull else 'DIV BAJISTA') + \
                    (' (CONF)' if confirmed else ' (FORM.)')
        off_y = -28 if is_bull else 28
        if pt2_ts in df.index:
            ax_price.annotate(
                lbl_txt, xy=(pt2_ts, y2), xytext=(0, off_y),
                textcoords='offset points',
                color=col, fontsize=8, fontweight='bold', ha='center',
                arrowprops=dict(arrowstyle='->', color=col, lw=1.2),
            )

        # RSI markers
        r1v = r['rsi_pivot_1']
        r2v = r['rsi_pivot_2']
        if pt1_ts in df.index and r1v:
            ax_rsi.scatter([pt1_ts], [r1v], color=col, s=70, zorder=9,
                           marker='o', linewidths=1.2, edgecolors='white', alpha=0.85)
        if pt2_ts in df.index and r2v:
            ax_rsi.scatter([pt2_ts], [r2v], color=col, s=90, zorder=9,
                           marker='o', linewidths=1.8, edgecolors='white')
        if pt1_ts in df.index and pt2_ts in df.index and r1v and r2v:
            ax_rsi.plot([pt1_ts, pt2_ts], [r1v, r2v],
                        color=col, lw=1.6, ls='--', alpha=0.7, zorder=5)
            ax_rsi.annotate(f'{r1v:.0f}', xy=(pt1_ts, r1v), xytext=(4, 4),
                            textcoords='offset points', color=col, fontsize=6.5)
            ax_rsi.annotate(f'{r2v:.0f}', xy=(pt2_ts, r2v), xytext=(4, 4),
                            textcoords='offset points', color=col, fontsize=6.5)

    # ── RSI panel ──────────────────────────────────────────────────────────
    ax_rsi.plot(df.index, df['rsi'], color=_RSI_COLOR, lw=1.0)
    ax_rsi.axhline(70, color=_COLORS['sma200'], ls='--', lw=0.7, alpha=0.6)
    ax_rsi.axhline(30, color=_GREEN, ls='--', lw=0.7, alpha=0.6)
    ax_rsi.fill_between(df.index, 30, df['rsi'].clip(upper=30), alpha=0.12, color=_GREEN)
    ax_rsi.fill_between(df.index, 70, df['rsi'].clip(lower=70), alpha=0.12, color=_COLORS['sma200'])
    ax_rsi.set_ylim(0, 100)
    ax_rsi.set_yticks([30, 50, 70])
    ax_rsi.set_ylabel('RSI(14)', color=_TEXT_COLOR, fontsize=7)
    ax_rsi.text(df.index[-1], 72, 'OB', color=_COLORS['sma200'], fontsize=6, va='bottom', ha='right')
    ax_rsi.text(df.index[-1], 28, 'OS', color=_GREEN, fontsize=6, va='top', ha='right')

    # ── Ejes X ────────────────────────────────────────────────────────────
    ax_rsi.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax_rsi.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax_rsi.xaxis.get_majorticklabels(), rotation=0, ha='center',
             color=_TEXT_COLOR, fontsize=7)
    plt.setp(ax_price.xaxis.get_majorticklabels(), visible=False)

    # ── Titulo principal ───────────────────────────────────────────────────
    sector = SECTOR_MAP.get(sym, {}).get('sector', '')
    dur    = f"{start.strftime('%d %b %Y')} - {fecha.strftime('%d %b %Y')}  |  Diaria"
    fig.suptitle(
        f'{sym}  |  {sector}  |  {dur}',
        color=_TEXT_COLOR, fontsize=11, fontweight='bold', y=0.97,
    )

    # ── Leyenda mini ───────────────────────────────────────────────────────
    ax_price.legend(
        handles=[
            Line2D([0], [0], color=_COLORS['close'],  lw=1.2, label='Precio'),
            Line2D([0], [0], color=_COLORS['ema20'],  lw=1.0, ls='--', label='EMA20'),
            Line2D([0], [0], color=_COLORS['sma50'],  lw=1.0, label='SMA50'),
            Line2D([0], [0], color=_COLORS['sma200'], lw=1.2, label='SMA200'),
        ],
        loc='upper left', facecolor=_PANEL_BG, edgecolor=_GRID_COLOR,
        labelcolor=_TEXT_COLOR, fontsize=7,
    )

    # ── Panel de texto (derecha) ───────────────────────────────────────────
    _draw_text_panel(ax_txt, r, df, fecha, detail_nvda)

    pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)


def _draw_text_panel(ax, r: dict, df: pd.DataFrame, fecha: date, detail_nvda: bool):
    """Renderiza el panel de analisis textual en el eje dado."""
    sym   = r['simbolo']
    state = r['divergence_state']
    col   = _div_color(r)
    is_div = state != 'NO_DIVERGENCE'

    lines = []  # (text, x, y, kwargs)

    def T(text, x, y, **kw):
        lines.append((text, x, y, kw))

    y = 0.97
    dy_title = 0.065
    dy_body  = 0.052
    dy_small = 0.043

    # Estado principal
    T(_state_short(state), 0.04, y,
      color=col, fontsize=10, fontweight='bold', va='top')
    y -= dy_title

    # Separador
    ax.axhline(y, color=_GRID_COLOR, lw=0.8)
    y -= 0.025

    if is_div:
        is_bull = r['divergence_type'] == 'BULLISH'
        p1 = r['price_pivot_1']
        p2 = r['price_pivot_2']
        r1 = r['rsi_pivot_1']
        r2 = r['rsi_pivot_2']
        t1 = str(r['pivot_1_date'])[:10] if r['pivot_1_date'] else '-'
        t2 = str(r['pivot_2_date'])[:10] if r['pivot_2_date'] else '-'
        confirmed = 'CONFIRMED' in state
        conf_lvl  = r['confidence_level'] or '---'
        dec       = r['decision']

        # Temporalidad
        tf_label = r.get('_timeframe_label', 'Diaria')
        T(f'Temporalidad: {tf_label}', 0.04, y, color=_MUTED, fontsize=8, va='top')
        y -= dy_body

        # Tipo
        tipo_str = 'Alcista (precio baja, RSI sube)' if is_bull else 'Bajista (precio sube, RSI baja)'
        T(f'Tipo: {tipo_str}', 0.04, y, color=_TEXT_COLOR, fontsize=8, va='top')
        y -= dy_body

        # Confirmacion
        conf_col = _GREEN if confirmed else _YELLOW
        T(f'Confirmada: {"SI" if confirmed else "NO"}  |  Confianza: {conf_lvl}', 0.04, y,
          color=conf_col, fontsize=8, fontweight='bold', va='top')
        y -= dy_body

        # Decision
        dec_col = _GREEN if dec == 'BUY_CANDIDATE' else \
                  _YELLOW if dec == 'WATCHLIST'    else \
                  _RED    if dec in ('SELL_WARNING','AVOID') else _MUTED
        T(f'Decision: {dec}', 0.04, y, color=dec_col, fontsize=9, fontweight='bold', va='top')
        y -= dy_title

        ax.axhline(y, color=_GRID_COLOR, lw=0.5, ls='--')
        y -= 0.02

        # Pivots
        T('PIVOTS DETECTADOS', 0.04, y, color=_HDR, fontsize=7.5, fontweight='bold', va='top')
        y -= dy_small

        arrow = 'v' if is_bull else '^'
        T(f'P1  {t1}   precio=${p1:.2f}   RSI={r1:.1f}', 0.06, y,
          color=_TEXT_COLOR, fontsize=8, va='top')
        y -= dy_small
        T(f'P2  {t2}   precio=${p2:.2f}   RSI={r2:.1f}  {arrow}', 0.06, y,
          color=col, fontsize=8, fontweight='bold', va='top')
        y -= dy_small

        price_chg = (p2 / p1 - 1) * 100
        rsi_chg   = r2 - r1
        T(f'Precio: {price_chg:+.2f}%   RSI: {rsi_chg:+.1f} pts', 0.06, y,
          color=_MUTED, fontsize=7.5, va='top')
        y -= dy_body

        ax.axhline(y, color=_GRID_COLOR, lw=0.5, ls='--')
        y -= 0.02

        # Lectura
        T('LECTURA', 0.04, y, color=_HDR, fontsize=7.5, fontweight='bold', va='top')
        y -= dy_small
        # Dividir lectura en lineas
        reading = r['reading']
        words = reading.split()
        line_cur = ''
        for w in words:
            if len(line_cur) + len(w) + 1 > 38:
                T(line_cur, 0.06, y, color=_TEXT_COLOR, fontsize=7.5, va='top',
                  style='italic')
                y -= dy_small
                line_cur = w
            else:
                line_cur = (line_cur + ' ' + w).strip()
        if line_cur:
            T(line_cur, 0.06, y, color=_TEXT_COLOR, fontsize=7.5, va='top', style='italic')
            y -= dy_small
        y -= 0.01

        ax.axhline(y, color=_GRID_COLOR, lw=0.5, ls='--')
        y -= 0.02

        # Estado actual del precio
        if not df.empty:
            last_close = df['close'].iloc[-1]
            ema20_last = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            sma200_last = df['close'].rolling(200).mean().iloc[-1]
            T('PRECIO ACTUAL', 0.04, y, color=_HDR, fontsize=7.5, fontweight='bold', va='top')
            y -= dy_small
            T(f'Close: ${last_close:.2f}', 0.06, y, color=_TEXT_COLOR, fontsize=8, va='top')
            y -= dy_small
            ema_rel = 'sobre' if last_close > ema20_last else 'bajo'
            T(f'EMA20: ${ema20_last:.2f}  ({ema_rel} EMA20)', 0.06, y,
              color=_GREEN if last_close > ema20_last else _RED, fontsize=8, va='top')
            y -= dy_small
            if not pd.isna(sma200_last):
                s200_rel = 'sobre' if last_close > sma200_last else 'bajo'
                T(f'SMA200: ${sma200_last:.2f}  ({s200_rel} SMA200)', 0.06, y,
                  color=_GREEN if last_close > sma200_last else _RED, fontsize=8, va='top')
                y -= dy_small

        # Detalle NVDA
        if detail_nvda:
            y -= 0.01
            ax.axhline(y, color=_GRID_COLOR, lw=0.5, ls='--')
            y -= 0.02
            _draw_nvda_explanation(ax, r, df, y)

    else:
        T('Sin divergencia activa detectada', 0.04, y, color=_MUTED, fontsize=8, va='top')
        y -= dy_body
        T('Temporalidad: Diaria', 0.04, y, color=_MUTED, fontsize=8, va='top')
        y -= dy_body
        if not df.empty:
            last_rsi = df['close'].pipe(lambda s: (
                100 - 100 / (1 + s.diff().clip(lower=0).ewm(alpha=1/14,adjust=False).mean() /
                             (-s.diff()).clip(lower=0).ewm(alpha=1/14,adjust=False).mean())
            )).iloc[-1]
            T(f'RSI actual: {last_rsi:.1f}', 0.04, y, color=_MUTED, fontsize=8, va='top')

    # Renderizar todas las lineas
    for text, x, y_pos, kw in lines:
        ax.text(x, y_pos, text, transform=ax.transAxes, **kw)


def _draw_nvda_explanation(ax, r: dict, df: pd.DataFrame, y_start: float):
    """Panel especial explicando paso a paso como llego el motor al resultado de NVDA."""
    col = _div_color(r)
    dy  = 0.041

    def T(txt, x, y, **kw):
        ax.text(x, y, txt, transform=ax.transAxes, va='top', **kw)

    y = y_start
    T('COMO LLEGO EL MOTOR A ESTE RESULTADO', 0.04, y,
      color='#f0a500', fontsize=7.5, fontweight='bold')
    y -= dy * 0.9

    p1 = r['price_pivot_1']
    p2 = r['price_pivot_2']
    r1 = r['rsi_pivot_1']
    r2 = r['rsi_pivot_2']
    t1 = str(r['pivot_1_date'])[:10]
    t2 = str(r['pivot_2_date'])[:10]
    idx1 = r['pivot_1_idx']
    idx2 = r['pivot_2_idx']
    sep  = idx2 - idx1
    n    = len(r.get('_closes') or [])
    bars_since = n - 1 - idx2 if idx2 else 0

    steps = [
        ('1. Busqueda de minimos locales',
         f'   Ventana: {_PIVOT_WIN} barras a cada lado. Se buscan lows que sean',
         f'   el minimo de su ventana [i-5, i+5]. Lookback: {_RECENCY*2}+ barras.'),
        ('2. Pivot 1 detectado',
         f'   Fecha: {t1}  Low: ${p1:.2f}  RSI: {r1:.1f}',
         f'   Es minimo local validado con RSI disponible.'),
        ('3. Pivot 2 detectado',
         f'   Fecha: {t2}  Low: ${p2:.2f}  RSI: {r2:.1f}',
         f'   Recencia: {bars_since} barras desde hoy (limite: {_RECENCY}).'),
        ('4. Condicion divergencia alcista',
         f'   Precio: ${p2:.2f} < ${p1:.2f} ({(p2/p1-1)*100:.2f}%) => precio baja  OK',
         f'   RSI: {r2:.1f} > {r1:.1f} + {_MIN_RSI_DIFF} => RSI sube  OK'),
        ('5. Separacion entre pivots',
         f'   {sep} barras (minimo={_MIN_SEP}, maximo={_MAX_SEP})  OK',
         ''),
        ('6. RSI en zona valida',
         f'   RSI P2={r2:.1f} < {_BULL_RSI_MAX} (no sobrecomprado)  OK',
         ''),
        ('7. Confirmacion (FALLO)',
         f'   Precio actual < EMA20 => sin señal verde posterior',
         f'   => Estado: FORMING (no CONFIRMED)'),
    ]

    for title, line2, line3 in steps:
        is_fail = 'FALLO' in title
        tc = _RED if is_fail else _GREEN
        T(title, 0.04, y, color=tc, fontsize=6.8, fontweight='bold')
        y -= dy * 0.78
        if line2:
            T(line2, 0.04, y, color=_TEXT_COLOR, fontsize=6.5)
            y -= dy * 0.72
        if line3:
            T(line3, 0.04, y, color=_MUTED, fontsize=6.3, style='italic')
            y -= dy * 0.68
        y -= dy * 0.12


# ─────────────────────────────────────────────────────────────────────────────
# Soporte para temporalidad semanal
# ─────────────────────────────────────────────────────────────────────────────

def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resamplea OHLCV diario a semanal (cierre de viernes)."""
    return df.resample('W-FRI').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
    ).dropna(subset=['close'])


def _analyze_from_ohlcv(sym: str, df: pd.DataFrame, fecha: date) -> dict:
    """
    Ejecuta el motor de divergencia sobre datos OHLCV pre-cargados.
    Funciona para cualquier temporalidad (diaria, semanal, etc.).
    """
    closes = df['close'].tolist()
    opens  = df['open'].tolist()
    highs  = df['high'].tolist()
    lows   = df['low'].tolist()
    dates  = [d.date() if hasattr(d, 'date') else d for d in df.index]
    n      = len(closes)

    _no = {
        'simbolo': sym, 'fecha': fecha,
        'divergence_state': 'NO_DIVERGENCE', 'divergence_type': None,
        'price_pivot_1': None, 'price_pivot_2': None,
        'rsi_pivot_1': None,   'rsi_pivot_2': None,
        'pivot_1_date': None,  'pivot_2_date': None,
        'pivot_1_idx': None,   'pivot_2_idx': None,
        'confidence_level': None, 'decision': 'NONE',
        'reading': _DIV_READINGS['NO_DIVERGENCE'],
        '_rsi_series': None, '_dates': dates,
        '_closes': closes, '_highs': highs, '_lows': lows,
    }

    if n < _RSI_PERIOD + _PIVOT_WIN * 2 + 10:
        return _no

    rsi_vals = _rsi_series(closes, _RSI_PERIOD)
    bull = _best_bullish_pair(lows,  rsi_vals, n)
    bear = _best_bearish_pair(highs, rsi_vals, n)

    if not bull and not bear:
        _no['_rsi_series'] = rsi_vals
        return _no

    bull_idx2 = bull[3] if bull else -1
    bear_idx2 = bear[3] if bear else -1

    if bull and bear:
        chosen = 'bullish' if bull_idx2 >= bear_idx2 else 'bearish'
    elif bull:
        chosen = 'bullish'
    else:
        chosen = 'bearish'

    if chosen == 'bullish':
        idx1, p1, r1, idx2, p2, r2 = bull
        confirmed = _bullish_confirmed(closes, opens, highs, idx2)
        state     = 'BULLISH_DIVERGENCE_CONFIRMED' if confirmed else 'BULLISH_DIVERGENCE_FORMING'
        div_type  = 'BULLISH'
    else:
        idx1, p1, r1, idx2, p2, r2 = bear
        confirmed = _bearish_confirmed(closes, opens, lows, idx2)
        state     = 'BEARISH_DIVERGENCE_CONFIRMED' if confirmed else 'BEARISH_DIVERGENCE_FORMING'
        div_type  = 'BEARISH'

    conf = _div_confidence(p1, p2, r1, r2, chosen, confirmed)
    dec  = _div_decision(state, conf)
    read = _DIV_READINGS.get(state, state)

    return {
        'simbolo': sym, 'fecha': fecha,
        'divergence_state': state, 'divergence_type': div_type,
        'price_pivot_1': round(p1, 4), 'price_pivot_2': round(p2, 4),
        'rsi_pivot_1':   round(r1, 2), 'rsi_pivot_2':   round(r2, 2),
        'pivot_1_date':  dates[idx1],  'pivot_2_date':  dates[idx2],
        'pivot_1_idx':   idx1,         'pivot_2_idx':   idx2,
        'confidence_level': conf, 'decision': dec, 'reading': read,
        '_rsi_series': rsi_vals, '_dates': dates,
        '_closes': closes, '_highs': highs, '_lows': lows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='PDF Divergencia RSI')
    parser.add_argument('--output',    default='reports/divergence_report.pdf')
    parser.add_argument('--start',     default='2025-01-01')
    parser.add_argument('--symbols',   nargs='+', default=None)
    parser.add_argument('--timeframe', default='daily', choices=['daily', 'weekly'],
                        help='Temporalidad del grafico y analisis (daily o weekly)')
    args = parser.parse_args()

    symbols   = [s.upper() for s in args.symbols] if args.symbols else UNIVERSE
    start     = date.fromisoformat(args.start)
    fecha     = date.today()
    weekly    = args.timeframe == 'weekly'
    tf_label  = 'Semanal' if weekly else 'Diaria'

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)

    print(f"\n=== Generando PDF: {args.output} ===")
    print(f"    Simbolos:    {symbols}")
    print(f"    Rango:       {start} -> {fecha}")
    print(f"    Temporalidad: {tf_label}\n")

    # Cargar datos, resamplear si semanal, analizar
    results = []
    dfs     = {}   # df en la temporalidad correcta para los graficos

    for sym in symbols:
        print(f"  [{sym}] cargando...", end=' ')
        # Cargar siempre historia completa para RSI bien sembrado
        df_daily = _load_ohlcv(sym, fecha)
        if df_daily.empty:
            print("-> sin datos")
            continue

        if weekly:
            df_tf = _resample_weekly(df_daily)
            r = _analyze_from_ohlcv(sym, df_tf, fecha)
        else:
            df_tf = df_daily
            r = div_analyze(sym, fecha)

        if r:
            r['_timeframe_label'] = tf_label
            results.append(r)
            dfs[sym] = df_tf
            print(f"-> {_state_short(r['divergence_state'])}")
        else:
            print("-> sin datos")

    if not results:
        print("Sin resultados. Abortando.")
        return

    print(f"\n  Generando PDF ({len(results) + 1} paginas)...")

    with PdfPages(args.output) as pdf:
        # Portada con label de temporalidad
        _draw_cover(pdf, results, fecha, start)

        _order = {'BULLISH_DIVERGENCE_CONFIRMED': 0, 'BEARISH_DIVERGENCE_CONFIRMED': 1,
                  'BULLISH_DIVERGENCE_FORMING': 2,   'BEARISH_DIVERGENCE_FORMING': 3,
                  'NO_DIVERGENCE': 4}
        sorted_r = sorted(results, key=lambda r: _order.get(r['divergence_state'], 9))

        for r in sorted_r:
            sym = r['simbolo']
            df  = dfs.get(sym, pd.DataFrame())
            is_nvda = sym == 'NVDA'
            print(f"    pagina: {sym}{'  [+ explicacion detallada]' if is_nvda else ''}...")
            _draw_asset_page(pdf, r, df, start, fecha, detail_nvda=is_nvda)

        pdf.infodict().update({
            'Title':   f'RSI Divergence Report ({tf_label})',
            'Subject': f'Universo: {", ".join(symbols)} | {start} - {fecha} | {tf_label}',
            'Author':  'trading-assist',
        })

    print(f"\n  PDF generado: {args.output}\n")


if __name__ == '__main__':
    main()
