"""Script temporal para generar PNGs de preview del reporte."""
import sys
sys.path.insert(0, '.')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
import pandas as pd
from datetime import date, timedelta
import os

from scripts.export_report_pdf import (
    _load_ohlcv, _build_df, _compute_signals, _build_analysis_text,
    _setup_ax, _C, _DARK_BG, _PANEL_BG, _GRID_COLOR, _TEXT_COLOR, _MUTED,
    _DEC_COLORS, _DEC_LABELS, _STATE_ES, _CONF_ES, _ALIGN_ES,
    _load_market_ctx, _load_sector_ctx, analyze_symbol,
)
from config import SECTOR_MAP

SYMBOLS  = ['GOOGL', 'VIST', 'MSFT', 'AAPL', 'NVDA']
END      = date(2026, 3, 21)
START_D  = date(2025, 1, 1)
OUT_DIR  = 'charts/preview'
os.makedirs(OUT_DIR, exist_ok=True)

results = {s: analyze_symbol(s, END) for s in SYMBOLS}


def render_cover():
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.axis('off')
    ax.set_facecolor(_DARK_BG)

    fig.text(0.5, 0.88, 'VectorAlpha — Trend+Pullback Engine',
             color=_TEXT_COLOR, fontsize=22, fontweight='bold', ha='center', va='top')
    fig.text(0.5, 0.80, f'Reporte de mercado  |  {END.strftime("%d %B %Y")}',
             color=_MUTED, fontsize=13, ha='center', va='top')

    col_x   = [0.10, 0.24, 0.38, 0.50, 0.62, 0.74, 0.87]
    headers = ['Activo', 'Estado', 'T.Score', 'P.Score', 'Contexto', 'Conf.', 'Decision']
    y_hdr   = 0.68
    for cx, h in zip(col_x, headers):
        fig.text(cx, y_hdr, h, color=_MUTED, fontsize=9,
                 fontweight='bold', ha='left', va='top')
    fig.add_artist(plt.Line2D(
        [0.07, 0.93], [y_hdr - 0.025, y_hdr - 0.025],
        color=_GRID_COLOR, lw=0.8
    ))
    y = y_hdr - 0.055
    for sym in SYMBOLS:
        r = results[sym]
        dec = r['decision']
        colors = [_TEXT_COLOR] * 6 + [_DEC_COLORS.get(dec, _MUTED)]
        vals = [
            sym,
            _STATE_ES.get(r['setup_state'], r['setup_state']),
            f"{r['trend_score']:.0f}/10",
            f"{r['pullback_score']:.0f}/10",
            _ALIGN_ES.get(r['context_alignment'], ''),
            _CONF_ES.get(r['confidence_level'], ''),
            _DEC_LABELS.get(dec, dec),
        ]
        for cx, v, c in zip(col_x, vals, colors):
            fig.text(cx, y, v, color=c, fontsize=9, ha='left', va='top')
        y -= 0.048

    fig.text(0.5, 0.06,
             'Reporte automatico — No constituye recomendacion de inversion.',
             color=_MUTED, fontsize=7.5, ha='center', va='bottom', style='italic')

    fig.savefig(f'{OUT_DIR}/00_portada.png', dpi=130,
                bbox_inches='tight', facecolor=_DARK_BG)
    plt.close('all')
    print("  Portada OK")


def render_asset(sym, idx):
    rows    = _load_ohlcv(sym, END)
    df_full = _build_df(rows)
    df      = df_full[df_full.index.date >= START_D]
    sector    = SECTOR_MAP.get(sym, {}).get('sector', '')
    ctx_start = START_D - timedelta(days=60)
    mkt_cache = _load_market_ctx(ctx_start, END)
    sec_cache = _load_sector_ctx(sector, ctx_start, END) if sector else {}
    signals_df = _compute_signals(df_full, START_D, mkt_cache, sec_cache)
    result     = results[sym]

    fig   = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)
    outer = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[3, 1],
                              wspace=0.04, left=0.05, right=0.97,
                              top=0.92, bottom=0.08)
    inner = gridspec.GridSpecFromSubplotSpec(
        2, 1, subplot_spec=outer[0], height_ratios=[3, 1], hspace=0.04
    )
    ax1 = fig.add_subplot(inner[0])
    ax2 = fig.add_subplot(inner[1], sharex=ax1)
    ax_t = fig.add_subplot(outer[1])
    ax_t.set_facecolor(_PANEL_BG)
    ax_t.axis('off')
    _setup_ax(ax1)
    _setup_ax(ax2)

    ax1.plot(df.index, df['close'],  color=_C['close'],  lw=1.4, zorder=3)
    ax1.plot(df.index, df['ema20'],  color=_C['ema20'],  lw=1.1, ls='--', alpha=0.9)
    ax1.plot(df.index, df['sma50'],  color=_C['sma50'],  lw=1.1, alpha=0.9)
    ax1.plot(df.index, df['sma200'], color=_C['sma200'], lw=1.5, alpha=0.9)

    if not signals_df.empty:
        for dt, row in signals_df.iterrows():
            if dt not in df.index:
                continue
            p = df.loc[dt, 'close']
            d = row['decision']
            if d == 'BUY_CANDIDATE':
                ax1.scatter(dt, p * 0.982, color=_C['buy'],   marker='^', s=55, zorder=6, linewidths=0)
            elif d == 'WATCHLIST':
                ax1.scatter(dt, p * 0.988, color=_C['watch'], marker='o', s=20, zorder=5, linewidths=0, alpha=0.7)
            elif d == 'AVOID':
                ax1.scatter(dt, p * 1.018, color=_C['avoid'], marker='v', s=42, zorder=6, linewidths=0, alpha=0.8)

    leg = [
        Line2D([0], [0], color=_C['close'],  lw=1.4,             label='Precio'),
        Line2D([0], [0], color=_C['ema20'],  lw=1.1, ls='--',    label='EMA20'),
        Line2D([0], [0], color=_C['sma50'],  lw=1.1,             label='SMA50'),
        Line2D([0], [0], color=_C['sma200'], lw=1.5,             label='SMA200'),
        Line2D([0], [0], marker='^', color='none', markerfacecolor=_C['buy'],   ms=6, label='BUY'),
        Line2D([0], [0], marker='o', color='none', markerfacecolor=_C['watch'], ms=5, label='WATCH', alpha=0.7),
        Line2D([0], [0], marker='v', color='none', markerfacecolor=_C['avoid'], ms=5, label='AVOID'),
    ]
    ax1.legend(handles=leg, loc='upper left', facecolor=_PANEL_BG,
               edgecolor=_GRID_COLOR, labelcolor=_TEXT_COLOR,
               fontsize=6.5, ncol=2)
    ax1.set_ylabel('Precio (USD)', color=_TEXT_COLOR, fontsize=8)

    ax2.plot(df.index, df['rsi'], color=_C['rsi'], lw=0.9)
    ax2.axhline(70, color=_C['avoid'], ls='--', lw=0.7, alpha=0.5)
    ax2.axhline(30, color=_C['buy'],   ls='--', lw=0.7, alpha=0.5)
    ax2.fill_between(df.index, 30, df['rsi'].clip(upper=30), alpha=0.12, color=_C['buy'])
    ax2.fill_between(df.index, 70, df['rsi'].clip(lower=70), alpha=0.12, color=_C['avoid'])
    ax2.set_ylim(0, 100)
    ax2.set_yticks([30, 50, 70])
    ax2.set_ylabel('RSI(14)', color=_TEXT_COLOR, fontsize=7)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %y'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=0, ha='center',
             color=_TEXT_COLOR, fontsize=7)
    plt.setp(ax1.xaxis.get_majorticklabels(), visible=False)

    dec_now = result['decision']
    fig.text(0.05, 0.96, sym, color=_TEXT_COLOR, fontsize=16,
             fontweight='bold', va='top')
    fig.text(0.14, 0.965, f'  {START_D} / {END}',
             color=_MUTED, fontsize=9, va='top')
    fig.text(0.75, 0.965, f"[ {_DEC_LABELS.get(dec_now, dec_now)} ]",
             color=_DEC_COLORS.get(dec_now, _MUTED), fontsize=13,
             fontweight='bold', va='top', ha='center')

    analysis = _build_analysis_text(sym, result, signals_df, df)
    y = 0.97
    for item in analysis:
        text, color, is_header = item
        fs      = 7.0 if is_header else 6.5
        fw      = 'bold' if is_header else 'normal'
        wrap_at = 46
        y_step  = 0.042
        words = text.split()
        line  = ''
        for word in words:
            test = line + (' ' if line else '') + word
            if len(test) > wrap_at:
                ax_t.text(0.04, y, line, color=color, fontsize=fs, fontweight=fw,
                          va='top', transform=ax_t.transAxes)
                y -= y_step
                line = word
                fw   = 'normal'
                fs   = 6.5
            else:
                line = test
        if line:
            ax_t.text(0.04, y, line, color=color, fontsize=fs, fontweight=fw,
                      va='top', transform=ax_t.transAxes)
            y -= y_step
        if is_header:
            y -= 0.008

    out = f'{OUT_DIR}/{idx:02d}_{sym.lower()}.png'
    fig.savefig(out, dpi=130, bbox_inches='tight', facecolor=_DARK_BG)
    plt.close('all')
    print(f"  {sym} -> {out}")


if __name__ == '__main__':
    print("Generando previews...")
    render_cover()
    for i, sym in enumerate(SYMBOLS, 1):
        render_asset(sym, i)
    print("Listo.")
