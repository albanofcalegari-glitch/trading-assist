"""
export_report_pdf.py — genera PDF con gráficos + análisis por activo

Uso:
    python scripts/export_report_pdf.py
    python scripts/export_report_pdf.py --output mi_reporte.pdf
    python scripts/export_report_pdf.py --symbols GOOGL VIST MSFT
    python scripts/export_report_pdf.py --start 2025-06-01
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
from strategies.trend_pullback import (
    _score_trend, _score_pullback, _classify_setup,
    _make_confidence, _make_decision, _make_reading,
    _MARKET_WEIGHT, _SECTOR_WEIGHT,
    analyze_symbol,
)
from strategies.utils import (
    ema as _ema_list, sma as _sma_list,
    momentum_pct, vol_ratio, vs_peak, higher_low,
)
from config import UNIVERSE, SECTOR_MAP

# ─────────────────────────────────────────────────────────────────────────────
# Colores / tema
# ─────────────────────────────────────────────────────────────────────────────
_DARK_BG    = '#0d1117'
_PANEL_BG   = '#161b22'
_GRID_COLOR = '#21262d'
_TEXT_COLOR = '#c9d1d9'
_MUTED      = '#8b949e'

_C = {
    'close':  '#e6edf3',
    'ema20':  '#f0a500',
    'sma50':  '#4fc3f7',
    'sma200': '#ef5350',
    'rsi':    '#ce93d8',
    'buy':    '#3fb950',
    'watch':  '#d29922',
    'avoid':  '#f85149',
}

_DEC_COLORS = {
    'BUY_CANDIDATE': '#3fb950',
    'WATCHLIST':     '#d29922',
    'AVOID':         '#f85149',
    'NO_ACTION':     '#8b949e',
}

_DEC_LABELS = {
    'BUY_CANDIDATE': 'COMPRAR',
    'WATCHLIST':     'VIGILAR',
    'AVOID':         'EVITAR',
    'NO_ACTION':     'NEUTRAL',
}

_STATE_ES = {
    'PULLBACK_VALID':   'Pullback válido',
    'PULLBACK_FORMING': 'Pullback en formación',
    'TREND_HEALTHY':    'Tendencia sana',
    'TREND_BROKEN':     'Tendencia dañada',
    'NO_SETUP':         'Sin setup',
}

_CONF_ES = {
    'HIGH':   'Alta',
    'MEDIUM': 'Media',
    'LOW':    'Baja',
}

_ALIGN_ES = {
    'favorable':   'Favorable',
    'neutral':     'Neutral',
    'unfavorable': 'Desfavorable',
}


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_ohlcv(symbol, end):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, close, volume FROM price_history
                   WHERE simbolo=%s AND fecha<=%s ORDER BY fecha ASC""",
                (symbol, end)
            )
            return cur.fetchall()
    finally:
        conn.close()


def _load_market_ctx(start, end):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, regime FROM market_context_daily
                   WHERE fecha BETWEEN %s AND %s ORDER BY fecha""",
                (start, end)
            )
            return {r['fecha']: r['regime'] for r in cur.fetchall()}
    finally:
        conn.close()


def _load_sector_ctx(sector, start, end):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, regime FROM sector_context_daily
                   WHERE sector=%s AND fecha BETWEEN %s AND %s ORDER BY fecha""",
                (sector, start, end)
            )
            return {r['fecha']: r['regime'] for r in cur.fetchall()}
    finally:
        conn.close()


def _nearest(cache, d):
    dk = d.date() if hasattr(d, 'date') else d
    for i in range(11):
        k = dk - timedelta(days=i)
        if k in cache:
            return cache[k]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Indicadores pandas
# ─────────────────────────────────────────────────────────────────────────────

def _build_df(rows):
    df = pd.DataFrame(rows)
    df['fecha']  = pd.to_datetime(df['fecha'])
    df.set_index('fecha', inplace=True)
    df['close']  = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    delta        = df['close'].diff()
    g = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    l = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    df['rsi']    = (100 - 100 / (1 + g / l)).round(2)
    df['mom20']  = df['close'].pct_change(20) * 100
    df['vol_r']  = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Señales rolling
# ─────────────────────────────────────────────────────────────────────────────

def _compute_signals(df_full, start, mkt_cache, sec_cache):
    closes_all  = df_full['close'].tolist()
    volumes_all = df_full['volume'].tolist()
    fechas_all  = list(df_full.index)
    records     = []

    for i, dt in enumerate(fechas_all):
        if dt.date() < start or i < 60:
            continue
        closes  = closes_all[:i + 1]
        volumes = volumes_all[:i + 1]
        price   = closes[-1]

        ema20_v  = _ema_list(closes, 20)
        sma50_v  = _sma_list(closes, 50)
        sma200_v = _sma_list(closes, 200)
        mom20_v  = momentum_pct(closes, 20)
        mom60_v  = momentum_pct(closes, 60)
        peak60_v = vs_peak(closes, 60)
        rsi_v    = float(df_full.loc[dt, 'rsi']) if not pd.isna(df_full.loc[dt, 'rsi']) else None
        vol_r_v  = float(df_full.loc[dt, 'vol_r']) if not pd.isna(df_full.loc[dt, 'vol_r']) else None

        trend_sc, _ = _score_trend(price, ema20_v, sma50_v, sma200_v, mom20_v, mom60_v, peak60_v)
        pull_sc, _  = _score_pullback(price, ema20_v, sma50_v, rsi_v, vol_r_v, mom20_v, closes)
        state       = _classify_setup(trend_sc, pull_sc, price, sma200_v, ema20_v, mom20_v, mom60_v)

        mkt_r  = _nearest(mkt_cache, dt) or 'RANGE'
        sec_r  = _nearest(sec_cache, dt) or 'NEUTRAL'
        total  = _MARKET_WEIGHT.get(mkt_r, 0) + _SECTOR_WEIGHT.get(sec_r, 0)
        align  = 'favorable' if total >= 1.0 else ('unfavorable' if total <= -0.5 else 'neutral')

        conf   = _make_confidence(state, trend_sc, pull_sc, align)
        dec    = _make_decision(state, align, conf, trend_sc)

        records.append({'fecha': dt, 'decision': dec, 'state': state,
                        'trend_sc': trend_sc, 'pull_sc': pull_sc, 'align': align})

    return pd.DataFrame(records).set_index('fecha') if records else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Texto de análisis dinámico
# ─────────────────────────────────────────────────────────────────────────────

_HDR = '#a8bcc8'   # color de encabezados de sección


def _build_analysis_text(symbol, result, signals_df, df_display):
    """
    Genera lista de (texto, color, is_header) para el panel derecho.
    is_header=True → fuente un poco mayor y negrita.
    """
    if result is None:
        return [("Sin datos suficientes para analizar.", _MUTED, False)]

    state   = result['setup_state']
    dec     = result['decision']
    ts      = result['trend_score']
    ps      = result['pullback_score']
    align   = result['context_alignment']
    reading = result['reading']
    price   = result['price']
    sma200  = result.get('sma200') or 0
    sma50   = result.get('sma50') or 0
    ema20   = result.get('ema20') or 0
    mom20   = result.get('mom20') or 0
    mom60   = result.get('mom60') or 0
    rsi_val = result.get('rsi14') or 0
    vol_r   = result.get('vol_ratio') or 1.0
    conf    = result.get('confidence_level', 'LOW')
    td      = result.get('_trend_det', {})
    pd_det  = result.get('_pull_det',  {})
    ctx     = result.get('_ctx', {})

    dec_color = _DEC_COLORS.get(dec, _MUTED)

    # helpers
    def H(t):  lines.append((t, _HDR, True))
    def L(t, c=_TEXT_COLOR): lines.append((t, c, False))
    def S():   lines.append(('', _MUTED, False))

    lines = []

    # ── 1. DECISION ───────────────────────────────────────────────────────────
    H("DECISION")
    L(f"{_DEC_LABELS.get(dec, dec)}  —  {_STATE_ES.get(state, state)}", dec_color)
    L(f"Confianza: {_CONF_ES.get(conf,'')}  |  Contexto: {_ALIGN_ES.get(align,'')}", _MUTED)

    # ── 2. SCORES ─────────────────────────────────────────────────────────────
    S()
    H("SCORES DEL MOTOR")
    L(f"Tendencia:  {ts:.0f} / 10   |   Pullback:  {ps:.0f} / 10", _TEXT_COLOR)

    # Breakdown trend (5 componentes × 2 pts)
    tn = {'mom60': 'mom60', 'vs_sma200': 'SMA200', 'ma_align': 'align',
          'vs_peak': 'pico60', 'vs_sma50': 'SMA50'}
    t_parts = [f"{lbl}:{td.get(k,0)}" for k, lbl in tn.items()]
    L("T> " + "  ".join(t_parts[:3]), _MUTED)
    L("   " + "  ".join(t_parts[3:]), _MUTED)

    pn = {'magnitude': 'mag', 'proximity': 'prox', 'rsi': 'rsi',
          'volume': 'vol', 'stabilization': 'estab'}
    p_parts = [f"{lbl}:{pd_det.get(k,0)}" for k, lbl in pn.items()]
    L("P> " + "  ".join(p_parts), _MUTED)

    # ── 3. PRECIO VS MEDIAS ───────────────────────────────────────────────────
    S()
    H("PRECIO vs MEDIAS MOVILES")
    L(f"Precio actual:   ${price:.2f}", _TEXT_COLOR)

    def _vs(ref, label, color_key):
        if not ref:
            return
        pct = (price / ref - 1) * 100
        arrow = "encima" if pct >= 0 else "debajo"
        c = _C['buy'] if pct >= 0 else _C['avoid']
        L(f"{label:<8} ${ref:>8.2f}   {pct:+.1f}%  ({arrow})", c)

    _vs(ema20,  'EMA20:', 'ema20')
    _vs(sma50,  'SMA50:', 'sma50')
    _vs(sma200, 'SMA200:', 'sma200')

    # ── 4. MOMENTUM Y OSCILADORES ─────────────────────────────────────────────
    S()
    H("MOMENTUM Y OSCILADORES")

    m20c = _C['buy'] if mom20 > 0 else _C['avoid']
    m60c = _C['buy'] if mom60 > 0 else _C['avoid']
    L(f"Momentum 20d:  {mom20:+.1f}%", m20c)
    L(f"Momentum 60d:  {mom60:+.1f}%", m60c)

    if rsi_val > 70:   rsi_lbl, rsi_c = "sobrecomprado — no entrar", _C['avoid']
    elif rsi_val < 30: rsi_lbl, rsi_c = "sobrevendido — zona tecnica", _C['buy']
    elif rsi_val < 45: rsi_lbl, rsi_c = "frio — zona de compra", _C['buy']
    elif rsi_val < 55: rsi_lbl, rsi_c = "neutral", _TEXT_COLOR
    else:              rsi_lbl, rsi_c = "todavia caliente", _C['watch']
    L(f"RSI(14):       {rsi_val:.1f}  —  {rsi_lbl}", rsi_c)

    if vol_r < 0.75:   vol_lbl, vol_c = "muy bajo — venta sin conviccion", _C['buy']
    elif vol_r < 1.0:  vol_lbl, vol_c = "bajo — presion leve", _C['buy']
    elif vol_r < 1.3:  vol_lbl, vol_c = "normal", _TEXT_COLOR
    else:              vol_lbl, vol_c = "alto — presion vendedora", _C['avoid']
    L(f"Vol ratio:     {vol_r:.2f}x  —  {vol_lbl}", vol_c)

    # ── 5. CONTEXTO DE MERCADO ────────────────────────────────────────────────
    S()
    H("CONTEXTO")
    mkt_r = ctx.get('market_regime', '—')
    sec_r = ctx.get('sector_regime', '—')
    sec_n = ctx.get('sector', '—')
    mkt_c = _C['buy'] if mkt_r == 'TREND_UP' else (_C['avoid'] if mkt_r == 'TREND_DOWN' else _TEXT_COLOR)
    sec_c = _C['buy'] if sec_r == 'STRONG' else (_C['avoid'] if sec_r == 'WEAK' else _TEXT_COLOR)
    L(f"Mercado (SPY):  {mkt_r}", mkt_c)
    L(f"Sector:  {sec_n}", _TEXT_COLOR)
    L(f"Regimen sector:  {sec_r}", sec_c)

    # ── 6. ANALISIS NARRATIVO ─────────────────────────────────────────────────
    S()
    H("ANALISIS")
    L(f'"{reading}"', _TEXT_COLOR)

    if state == 'TREND_BROKEN':
        vs200 = (price / sma200 - 1) * 100 if sma200 else 0
        if vs200 < -3:
            L(f"Precio {abs(vs200):.1f}% debajo de SMA200.", _MUTED)
            L("Estructura de largo plazo rota. Sin", _MUTED)
            L("argumento tecnico para entrar largo.", _MUTED)
        else:
            L("Momentum y medias desalineados.", _MUTED)
            L("Esperar recuperacion confirmada.", _MUTED)
        if rsi_val < 32:
            L(f"RSI {rsi_val:.0f}: oversold. Posible rebote", _C['watch'])
            L("tecnico, pero no es setup de tendencia.", _C['watch'])

    elif state == 'TREND_HEALTHY':
        vs50  = (price / sma50  - 1) * 100 if sma50  else 0
        vs200 = (price / sma200 - 1) * 100 if sma200 else 0
        L(f"Precio {vs200:+.1f}% sobre SMA200,", _MUTED)
        L(f"{vs50:+.1f}% sobre SMA50.", _MUTED)
        L(f"Zona de entrada ideal: EMA20 ${ema20:.0f}", _MUTED)
        L(f"o SMA50 ${sma50:.0f} con volumen bajo.", _MUTED)
        if rsi_val > 65:
            L(f"RSI {rsi_val:.0f}: extendido, no perseguir.", _C['watch'])

    elif state == 'PULLBACK_VALID':
        zona  = "EMA20" if ema20 and abs(price/ema20-1) < abs(price/sma50-1) else "SMA50"
        zpx   = ema20 if zona == "EMA20" else sma50
        dist  = abs(price / zpx - 1) * 100 if zpx else 0
        L(f"Caida de {abs(mom20):.1f}% en 20d.", _MUTED)
        L(f"A {dist:.1f}% de {zona} (${zpx:.0f}).", _MUTED)
        if ts >= 7:
            L(f"Tendencia fuerte: mom60 {mom60:+.1f}%.", _MUTED)
        else:
            L(f"Tendencia moderada (score {ts:.0f}/10):", _MUTED)
            L(f"confirmar antes de entrar.", _MUTED)
        if vol_r < 1.0:
            L(f"Volumen bajo ({vol_r:.2f}x): sano.", _C['buy'])
        if rsi_val < 45:
            L(f"RSI {rsi_val:.0f}: zona tecnica de rebote.", _C['buy'])

    elif state == 'PULLBACK_FORMING':
        dist_ema = abs(price/ema20-1)*100 if ema20 else 0
        dist_s50 = abs(price/sma50-1)*100 if sma50 else 0
        L(f"Correccion activa: {mom20:+.1f}% en 20d.", _MUTED)
        L(f"A {dist_ema:.1f}% de EMA20 (${ema20:.0f}),", _MUTED)
        L(f"{dist_s50:.1f}% de SMA50 (${sma50:.0f}).", _MUTED)
        L("Esperar acercamiento al soporte", _MUTED)
        L("y señal de freno (vela + vol bajo).", _MUTED)

    # ── 7. ESTADISTICAS DEL PERIODO ───────────────────────────────────────────
    if not signals_df.empty:
        S()
        H("PERIODO GRAFICADO")
        n_buy   = (signals_df['decision'] == 'BUY_CANDIDATE').sum()
        n_watch = (signals_df['decision'] == 'WATCHLIST').sum()
        n_avoid = (signals_df['decision'] == 'AVOID').sum()
        total_d = len(signals_df)
        L(f"Total ruedas: {total_d}", _MUTED)
        L(f"BUY    {n_buy:>3}d  ({n_buy/total_d*100:.0f}%)", _C['buy'])
        L(f"WATCH  {n_watch:>3}d  ({n_watch/total_d*100:.0f}%)", _C['watch'])
        L(f"AVOID  {n_avoid:>3}d  ({n_avoid/total_d*100:.0f}%)", _C['avoid'])

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Página del PDF
# ─────────────────────────────────────────────────────────────────────────────

def _setup_ax(ax):
    ax.set_facecolor(_PANEL_BG)
    ax.tick_params(colors=_TEXT_COLOR, labelsize=7)
    ax.spines[:].set_color(_GRID_COLOR)
    ax.yaxis.label.set_color(_TEXT_COLOR)
    ax.grid(color=_GRID_COLOR, linewidth=0.4, alpha=0.6)


def _render_page(pdf, symbol, start, end, result, verbose=True):
    if verbose:
        print(f"  Generando pagina: {symbol}...")

    # ── Cargar datos ───────────────────────────────────────────────────────────
    rows = _load_ohlcv(symbol, end)
    if not rows:
        print(f"  [SKIP] {symbol}: sin datos")
        return

    df_full = _build_df(rows)
    df      = df_full[df_full.index.date >= start]
    if df.empty:
        print(f"  [SKIP] {symbol}: sin datos en rango")
        return

    # Señales
    sector    = SECTOR_MAP.get(symbol, {}).get('sector', '')
    ctx_start = start - timedelta(days=60)
    mkt_cache = _load_market_ctx(ctx_start, end)
    sec_cache = _load_sector_ctx(sector, ctx_start, end) if sector else {}
    signals_df = _compute_signals(df_full, start, mkt_cache, sec_cache)

    # ── Layout de la página ────────────────────────────────────────────────────
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)   # A4 landscape

    # Dividir en zona de gráfico (izq) y zona de texto (der)
    outer = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[3, 1], wspace=0.04,
                              left=0.05, right=0.97, top=0.93, bottom=0.08)

    # Panel izquierdo: precio + RSI
    inner = gridspec.GridSpecFromSubplotSpec(
        2, 1, subplot_spec=outer[0],
        height_ratios=[3, 1], hspace=0.04
    )
    ax1 = fig.add_subplot(inner[0])
    ax2 = fig.add_subplot(inner[1], sharex=ax1)
    _setup_ax(ax1)
    _setup_ax(ax2)

    # Panel derecho: texto
    ax_text = fig.add_subplot(outer[1])
    ax_text.set_facecolor(_PANEL_BG)
    ax_text.axis('off')

    # ── Precio + MAs ──────────────────────────────────────────────────────────
    ax1.plot(df.index, df['close'],  color=_C['close'],  lw=1.4, zorder=3)
    ax1.plot(df.index, df['ema20'],  color=_C['ema20'],  lw=1.1, ls='--', alpha=0.9, zorder=2)
    ax1.plot(df.index, df['sma50'],  color=_C['sma50'],  lw=1.1, alpha=0.9, zorder=2)
    ax1.plot(df.index, df['sma200'], color=_C['sma200'], lw=1.5, alpha=0.9, zorder=2)

    # Señales
    if not signals_df.empty:
        for dt, row in signals_df.iterrows():
            if dt not in df.index:
                continue
            p   = df.loc[dt, 'close']
            dec = row['decision']
            if dec == 'BUY_CANDIDATE':
                ax1.scatter(dt, p * 0.982, color=_C['buy'],   marker='^', s=60, zorder=6, linewidths=0)
            elif dec == 'WATCHLIST':
                ax1.scatter(dt, p * 0.988, color=_C['watch'], marker='o', s=22, zorder=5, linewidths=0, alpha=0.7)
            elif dec == 'AVOID':
                ax1.scatter(dt, p * 1.018, color=_C['avoid'], marker='v', s=45, zorder=6, linewidths=0, alpha=0.8)

    # Leyenda
    leg_elems = [
        Line2D([0],[0], color=_C['close'],  lw=1.4,  label='Precio'),
        Line2D([0],[0], color=_C['ema20'],  lw=1.1, ls='--', label='EMA20'),
        Line2D([0],[0], color=_C['sma50'],  lw=1.1,  label='SMA50'),
        Line2D([0],[0], color=_C['sma200'], lw=1.5,  label='SMA200'),
        Line2D([0],[0], marker='^', color='none', markerfacecolor=_C['buy'],   ms=7,  label='BUY'),
        Line2D([0],[0], marker='o', color='none', markerfacecolor=_C['watch'], ms=5,  label='WATCHLIST', alpha=0.7),
        Line2D([0],[0], marker='v', color='none', markerfacecolor=_C['avoid'], ms=6,  label='AVOID'),
    ]
    ax1.legend(handles=leg_elems, loc='upper left',
               facecolor=_PANEL_BG, edgecolor=_GRID_COLOR,
               labelcolor=_TEXT_COLOR, fontsize=6.5, ncol=2)
    ax1.set_ylabel('Precio (USD)', color=_TEXT_COLOR, fontsize=8)

    # ── RSI ───────────────────────────────────────────────────────────────────
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

    # ── Título ────────────────────────────────────────────────────────────────
    dec_now   = result['decision'] if result else 'N/A'
    dec_color = _DEC_COLORS.get(dec_now, _MUTED)
    dec_label = _DEC_LABELS.get(dec_now, dec_now)

    fig.text(0.05, 0.96, symbol,
             color=_TEXT_COLOR, fontsize=16, fontweight='bold', va='top')
    fig.text(0.14, 0.965, f"  —  {start} / {end}",
             color=_MUTED, fontsize=9, va='top')
    # Badge de decisión
    fig.text(0.75, 0.965, f"[ {dec_label} ]",
             color=dec_color, fontsize=13, fontweight='bold', va='top', ha='center')

    # ── Panel de texto ────────────────────────────────────────────────────────
    analysis = _build_analysis_text(symbol, result, signals_df, df)

    y = 0.97
    for item in analysis:
        text, color, is_header = item
        fs      = 7.0 if is_header else 6.5
        fw      = 'bold' if is_header else 'normal'
        wrap_at = 46
        y_step  = 0.042
        # Wrap manual por longitud
        words = text.split()
        line  = ''
        for word in words:
            test = line + (' ' if line else '') + word
            if len(test) > wrap_at:
                ax_text.text(0.04, y, line, color=color,
                             fontsize=fs, fontweight=fw,
                             va='top', transform=ax_text.transAxes)
                y -= y_step
                line = word
                fw   = 'normal'   # continuación de un header no es bold
                fs   = 6.5
            else:
                line = test
        if line:
            ax_text.text(0.04, y, line, color=color,
                         fontsize=fs, fontweight=fw,
                         va='top', transform=ax_text.transAxes)
            y -= y_step
        if is_header:
            y -= 0.008   # pequeño espacio extra tras el título de sección

    pdf.savefig(fig, facecolor=_DARK_BG)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Portada
# ─────────────────────────────────────────────────────────────────────────────

def _render_cover(pdf, symbols, fecha, results):
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(_DARK_BG)
    ax.axis('off')

    fig.text(0.5, 0.88, 'VectorAlpha — Trend+Pullback Engine',
             color=_TEXT_COLOR, fontsize=22, fontweight='bold',
             ha='center', va='top')
    fig.text(0.5, 0.80, f'Reporte de mercado  |  {fecha.strftime("%d %B %Y")}',
             color=_MUTED, fontsize=13, ha='center', va='top')

    # Tabla de resumen
    col_x = [0.12, 0.26, 0.40, 0.53, 0.64, 0.76, 0.88]
    headers = ['Activo', 'Estado', 'T.Score', 'P.Score', 'Contexto', 'Conf.', 'Decision']
    y_hdr   = 0.68

    for cx, hdr in zip(col_x, headers):
        fig.text(cx, y_hdr, hdr, color=_MUTED, fontsize=9,
                 fontweight='bold', ha='left', va='top')

    # Línea separadora
    fig.add_artist(plt.Line2D([0.08, 0.92], [y_hdr - 0.025, y_hdr - 0.025],
                              color=_GRID_COLOR, linewidth=0.8))

    y = y_hdr - 0.055
    for sym in symbols:
        r = results.get(sym)
        if r is None:
            vals   = [sym, '—', '—', '—', '—', '—', '—']
            colors = [_TEXT_COLOR] * 7
        else:
            dec    = r['decision']
            colors = [_TEXT_COLOR, _TEXT_COLOR, _TEXT_COLOR, _TEXT_COLOR,
                      _TEXT_COLOR, _TEXT_COLOR, _DEC_COLORS.get(dec, _MUTED)]
            vals = [
                sym,
                _STATE_ES.get(r['setup_state'], r['setup_state']),
                f"{r['trend_score']:.0f}/10",
                f"{r['pullback_score']:.0f}/10",
                _ALIGN_ES.get(r['context_alignment'], ''),
                _CONF_ES.get(r['confidence_level'], ''),
                _DEC_LABELS.get(dec, dec),
            ]
        for cx, val, color in zip(col_x, vals, colors):
            fig.text(cx, y, val, color=color, fontsize=9, ha='left', va='top')
        y -= 0.048

    # Pie
    fig.text(0.5, 0.06,
             'Este reporte es generado automaticamente por el motor Trend+Pullback. '
             'No constituye recomendacion de inversion.',
             color=_MUTED, fontsize=7.5, ha='center', va='bottom', style='italic')

    pdf.savefig(fig, facecolor=_DARK_BG)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Reporte PDF Trend+Pullback')
    parser.add_argument('--output',  default='reports/trend_pullback_report.pdf')
    parser.add_argument('--symbols', nargs='+', default=None)
    parser.add_argument('--start',   default='2025-01-01')
    parser.add_argument('--end',     default=None)
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else UNIVERSE
    start   = date.fromisoformat(args.start)
    end     = date.fromisoformat(args.end) if args.end else date.today()

    # Carpeta de salida
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== export_report_pdf ===")
    print(f"Simbolos : {', '.join(symbols)}")
    print(f"Rango    : {start} -> {end}")
    print(f"Output   : {args.output}\n")

    # Obtener resultados actuales del motor para cada símbolo
    results = {}
    for sym in symbols:
        r = analyze_symbol(sym, end)
        results[sym] = r
        state = r['setup_state'] if r else 'N/A'
        dec   = _DEC_LABELS.get(r['decision'], '?') if r else '?'
        print(f"  {sym:<6}  {state:<20}  {dec}")

    print()

    with PdfPages(args.output) as pdf:
        # Portada
        _render_cover(pdf, symbols, end, results)
        # Una página por activo
        for sym in symbols:
            _render_page(pdf, sym, start, end, results.get(sym))

        # Metadata del PDF
        d = pdf.infodict()
        d['Title']   = f'VectorAlpha — Trend+Pullback Report {end}'
        d['Author']  = 'trading-assist engine'
        d['Subject'] = 'Analisis tecnico automatico'

    print(f"\nPDF generado: {args.output}")
    print(f"Paginas: {1 + len(symbols)} (portada + {len(symbols)} activos)\n")

    # Abrir el PDF automáticamente en Windows
    try:
        os.startfile(os.path.abspath(args.output))
    except Exception:
        pass


if __name__ == '__main__':
    main()
