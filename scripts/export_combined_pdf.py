"""
export_combined_pdf.py — Reporte PDF combinado: Reversal Engine (Fase 3) vs Trend+Pullback (Fase 2)

Estructura:
  - Portada: tabla comparativa de ambos motores por activo
  - Una pagina por activo:
      - Grafico Reversal (precio + MAs + markers de patron + minimos locales + neckline + RSI)
      - Panel derecho: analisis Reversal completo + seccion comparativa Trend+Pullback

Uso:
    python scripts/export_combined_pdf.py
    python scripts/export_combined_pdf.py --output reports/combined_report.pdf
    python scripts/export_combined_pdf.py --symbols GOOGL VIST MSFT AAPL NVDA JPM
    python scripts/export_combined_pdf.py --start 2025-01-01
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
from strategies.reversal import (
    analyze_symbol as rev_analyze,
    _detect_pattern, _score_reversal, _context_alignment,
    _PATTERN_DECISION, _apply_context_degradation, _make_confidence,
    _find_local_mins,
)
from strategies.trend_pullback import (
    _score_trend, _score_pullback, _classify_setup,
    _make_confidence as tp_confidence, _make_decision, _make_reading as tp_reading,
    _MARKET_WEIGHT, _SECTOR_WEIGHT,
    analyze_symbol as tp_analyze,
)
from strategies.utils import (
    ema as _ema_list, sma as _sma_list,
    momentum_pct, vol_ratio, vs_peak, higher_low, rsi as _rsi_list,
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

_C = {
    'close':  '#e6edf3',
    'ema20':  '#f0a500',
    'sma50':  '#4fc3f7',
    'sma200': '#ef5350',
    'rsi':    '#ce93d8',
    'buy':    '#3fb950',
    'watch':  '#d29922',
    'avoid':  '#f85149',
    'min':    '#ff9800',     # minimos locales (naranja)
    'neck':   '#ff9800',     # neckline
    'tp_buy': '#26a641',     # trend BUY (verde oscuro)
    'tp_wch': '#bb8009',     # trend WATCH
    'tp_avd': '#b91c1c',     # trend AVOID
    'sep':    '#30363d',     # linea separadora en panel texto
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

_PAT_ES = {
    'NO_PATTERN':               'Sin patron',
    'OVERSOLD_ONLY':            'Sobrevendido',
    'FLOOR_FORMING':            'Piso formando',
    'BASE_TENTATIVE':           'Base tentativa',
    'DOUBLE_BOTTOM_FORMING':    'Doble piso (form.)',
    'DOUBLE_BOTTOM_CONFIRMED':  'Doble piso (conf.)',
    'HIGHER_LOW_UPTREND':       'Min mas alto',
    'BEAR_MARKET_FAKE_REVERSAL':'Fake reversal',
    'BREAKDOWN_ACTIVE':         'Breakdown activo',
}

_PAT_SHORT = {
    'NO_PATTERN':               '',
    'OVERSOLD_ONLY':            'OVSLD',
    'FLOOR_FORMING':            'PISO',
    'BASE_TENTATIVE':           'BASE?',
    'DOUBLE_BOTTOM_FORMING':    'DB?',
    'DOUBLE_BOTTOM_CONFIRMED':  'DB!',
    'HIGHER_LOW_UPTREND':       'HL',
    'BEAR_MARKET_FAKE_REVERSAL':'FAKE',
    'BREAKDOWN_ACTIVE':         'BRK',
}

_STATE_ES = {
    'PULLBACK_VALID':   'Pullback valido',
    'PULLBACK_FORMING': 'Pullback en formacion',
    'TREND_HEALTHY':    'Tendencia sana',
    'TREND_BROKEN':     'Tendencia danada',
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

_MKT_ES = {
    'favorable':   'Favorable (mercado sube)',
    'neutral':     'Neutral',
    'unfavorable': 'Desfavorable (mercado baja)',
}

_SEC_ES = {
    'strong':  'Fuerte',
    'neutral': 'Neutral',
    'weak':    'Debil (degrada senal)',
}


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_ohlcv(symbol, end):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM price_history
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
# Construccion de DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def _build_df(rows):
    df = pd.DataFrame(rows)
    df['fecha']  = pd.to_datetime(df['fecha'])
    df.set_index('fecha', inplace=True)
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = df[col].astype(float)
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    delta = df['close'].diff()
    g = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    l = (-delta).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    df['rsi']   = (100 - 100 / (1 + g / l)).round(2)
    df['mom20'] = df['close'].pct_change(20) * 100
    df['vol_r'] = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Senales rolling: Reversal
# ─────────────────────────────────────────────────────────────────────────────

def _compute_reversal_signals(df_full, start, mkt_cache, sec_cache):
    closes_all  = df_full['close'].tolist()
    highs_all   = df_full['high'].tolist()
    lows_all    = df_full['low'].tolist()
    volumes_all = df_full['volume'].tolist()
    fechas_all  = list(df_full.index)
    records     = []

    for i, dt in enumerate(fechas_all):
        if dt.date() < start or i < 60:
            continue
        closes  = closes_all[:i + 1]
        lows_s  = lows_all[:i + 1]
        volumes = volumes_all[:i + 1]

        ema20_v  = _ema_list(closes, 20)
        sma50_v  = _sma_list(closes, 50)
        sma200_v = _sma_list(closes, 200)
        mom20_v  = momentum_pct(closes, 20)
        mom60_v  = momentum_pct(closes, 60)
        rsi_v    = float(df_full.loc[dt, 'rsi']) if not pd.isna(df_full.loc[dt, 'rsi']) else None
        vol_r_v  = float(df_full.loc[dt, 'vol_r']) if not pd.isna(df_full.loc[dt, 'vol_r']) else None

        try:
            pattern, pat_det = _detect_pattern(
                closes, lows_s, volumes,
                mom20_v, mom60_v, rsi_v, vol_r_v,
                sma50_v, ema20_v, sma200_v,
            )
        except Exception:
            pattern, pat_det = 'NO_PATTERN', {}

        mkt_regime = _nearest(mkt_cache, dt) or 'RANGE'
        sec_regime = _nearest(sec_cache, dt) or 'NEUTRAL'

        class _FakeRow:
            def __init__(self, regime): self.get = lambda k, d=None: regime if k == 'regime' else d
        mkt_row_f = {'regime': mkt_regime}
        sec_row_f = {'regime': sec_regime}

        market_align, sector_align, overall = _context_alignment(mkt_row_f, sec_row_f)
        raw_dec  = _PATTERN_DECISION.get(pattern, 'AVOID')
        decision = _apply_context_degradation(raw_dec, market_align, sector_align)

        # neckline si aplica
        neckline = pat_det.get('neckline') if pat_det else None

        records.append({
            'fecha':    dt,
            'decision': decision,
            'pattern':  pattern,
            'neckline': neckline,
        })

    return pd.DataFrame(records).set_index('fecha') if records else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Senales rolling: Trend+Pullback
# ─────────────────────────────────────────────────────────────────────────────

def _compute_trend_signals(df_full, start, mkt_cache, sec_cache):
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
        conf   = tp_confidence(state, trend_sc, pull_sc, align)
        dec    = _make_decision(state, align, conf, trend_sc)

        records.append({'fecha': dt, 'decision': dec, 'state': state,
                        'trend_sc': trend_sc, 'pull_sc': pull_sc})

    return pd.DataFrame(records).set_index('fecha') if records else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Panel de texto: analisis reversal + comparativa trend
# ─────────────────────────────────────────────────────────────────────────────

def _build_combined_text(rev_result, tp_result, rev_signals, tp_signals):
    """Genera lista de (texto, color, is_header) para el panel derecho."""
    lines = []

    def H(t):          lines.append((t, _HDR, True))
    def L(t, c=_TEXT_COLOR): lines.append((t, c, False))
    def S():           lines.append(('', _MUTED, False))
    def SEP():
        lines.append(('- - - - - - - - - - - - - - - - -', _C['sep'], False))

    # ── REVERSAL ─────────────────────────────────────────────────────────────
    if rev_result:
        pat     = rev_result['pattern_state']
        dec     = rev_result['decision']
        score   = rev_result['reversal_score']
        overall = rev_result['overall_context']
        conf    = rev_result['confidence_level']
        mkt_a   = rev_result['market_alignment']
        sec_a   = rev_result['sector_alignment']
        reading = rev_result['reading']
        price   = rev_result['price']
        rsi_v   = rev_result.get('rsi14') or 0
        mom20   = rev_result.get('mom20') or 0
        mom60   = rev_result.get('mom60') or 0
        vol_r   = rev_result.get('vol_ratio') or 1.0
        sma200  = rev_result.get('sma200') or 0
        sma50   = rev_result.get('sma50') or 0
        ema20   = rev_result.get('ema20') or 0
        pd_det  = rev_result.get('_pattern_det', {})
        sd      = rev_result.get('_score_det', {})
        dec_c   = _DEC_COLORS.get(dec, _MUTED)

        H("REVERSAL — DECISION")
        L(f"{_DEC_LABELS.get(dec, dec)}  —  {_CONF_ES.get(conf, conf)}", dec_c)
        L(f"Patron:   {_PAT_ES.get(pat, pat)}", _TEXT_COLOR)
        L(f"Score:    {score:.1f}/10   |   Contexto: {_ALIGN_ES.get(overall,'')}", _MUTED)

        S()
        H("SCORE REVERSAL (comp.)")
        L(
            f"RSI:{sd.get('rsi',0):.1f}  Vol:{sd.get('volume',0):.1f}  "
            f"Mom:{sd.get('momentum',0):.1f}  Pat:{sd.get('pattern',0):.1f}  "
            f"Est:{sd.get('stabilization',0):.1f}",
            _MUTED
        )

        S()
        H("INDICADORES")
        L(f"Precio:  ${price:.2f}", _TEXT_COLOR)
        def _vs(ref, label):
            if not ref: return
            pct = (price / ref - 1) * 100
            c = _C['buy'] if pct >= 0 else _C['avoid']
            L(f"{label:<7} ${ref:>8.2f}  {pct:+.1f}%", c)
        _vs(ema20,  'EMA20:')
        _vs(sma50,  'SMA50:')
        _vs(sma200, 'SMA200:')

        if rsi_v < 30:   rsi_lbl, rc = "sobrevendido", _C['buy']
        elif rsi_v < 45: rsi_lbl, rc = "frio", _C['buy']
        elif rsi_v < 55: rsi_lbl, rc = "neutral", _TEXT_COLOR
        else:            rsi_lbl, rc = "caliente", _C['watch']
        L(f"RSI(14): {rsi_v:.1f}  ({rsi_lbl})", rc)

        m20c = _C['buy'] if mom20 > 0 else _C['avoid']
        m60c = _C['buy'] if mom60 > 0 else _C['avoid']
        L(f"Mom 20d: {mom20:+.1f}%", m20c)
        L(f"Mom 60d: {mom60:+.1f}%", m60c)

        if vol_r < 0.85:   vl, vc = "comprimido (sano)", _C['buy']
        elif vol_r < 1.10: vl, vc = "normal", _TEXT_COLOR
        else:              vl, vc = "elevado (vendedores)", _C['avoid']
        L(f"Vol R:   {vol_r:.2f}x  ({vl})", vc)

        # detalles del patron
        if pat in ('DOUBLE_BOTTOM_FORMING', 'DOUBLE_BOTTOM_CONFIRMED', 'BASE_TENTATIVE') and pd_det:
            S()
            H("DETALLE PATRON")
            L(f"Min1: ${pd_det.get('min1',0):.2f}  Min2: ${pd_det.get('min2',0):.2f}", _MUTED)
            L(f"Neckline: ${pd_det.get('neckline',0):.2f}  "
              f"Bounce: {pd_det.get('bounce_pct',0):.1f}%  "
              f"Sep: {pd_det.get('separation',0)}d", _MUTED)
            if pd_det.get('quality_note'):
                L(f"Nota: {pd_det['quality_note']}", _C['watch'])

        S()
        H("CONTEXTO (Reversal)")
        mkt_c = _C['buy'] if mkt_a == 'favorable' else (_C['avoid'] if mkt_a == 'unfavorable' else _TEXT_COLOR)
        sec_c = _C['buy'] if sec_a == 'strong' else (_C['avoid'] if sec_a == 'weak' else _TEXT_COLOR)
        L(f"Mercado: {_MKT_ES.get(mkt_a, mkt_a)}", mkt_c)
        L(f"Sector:  {_SEC_ES.get(sec_a, sec_a)}", sec_c)

        S()
        H("LECTURA")
        L(f'"{reading}"', _TEXT_COLOR)

        # estadisticas periodo
        if not rev_signals.empty:
            S()
            nb = (rev_signals['decision'] == 'BUY_CANDIDATE').sum()
            nw = (rev_signals['decision'] == 'WATCHLIST').sum()
            na = (rev_signals['decision'] == 'AVOID').sum()
            td = len(rev_signals)
            L(f"Ruedas graficadas: {td}", _MUTED)
            L(f"BUY {nb:>3}d  WATCH {nw:>3}d  AVOID {na:>3}d", _MUTED)

    else:
        H("REVERSAL")
        L("Sin datos suficientes.", _MUTED)

    # ── SEPARADOR ────────────────────────────────────────────────────────────
    S()
    SEP()
    S()

    # ── TENDENCIA (Fase 2) ────────────────────────────────────────────────────
    H("TENDENCIA (Fase 2)")
    if tp_result:
        state   = tp_result['setup_state']
        dec_tp  = tp_result['decision']
        ts      = tp_result['trend_score']
        ps      = tp_result['pullback_score']
        align   = tp_result['context_alignment']
        conf_tp = tp_result.get('confidence_level', 'LOW')
        reading_tp = tp_result.get('reading', '')
        dec_c2  = _DEC_COLORS.get(dec_tp, _MUTED)

        L(f"{_DEC_LABELS.get(dec_tp, dec_tp)}  —  {_STATE_ES.get(state, state)}", dec_c2)
        L(f"T.Score: {ts:.0f}/10   P.Score: {ps:.0f}/10", _TEXT_COLOR)
        L(f"Contexto: {_ALIGN_ES.get(align,'')}   Conf: {_CONF_ES.get(conf_tp,'')}", _MUTED)
        S()
        L(f'"{reading_tp}"', _TEXT_COLOR)

        # estadisticas trend
        if not tp_signals.empty:
            S()
            nb2 = (tp_signals['decision'] == 'BUY_CANDIDATE').sum()
            nw2 = (tp_signals['decision'] == 'WATCHLIST').sum()
            na2 = (tp_signals['decision'] == 'AVOID').sum()
            td2 = len(tp_signals)
            L(f"Ruedas graficadas: {td2}", _MUTED)
            L(f"BUY {nb2:>3}d  WATCH {nw2:>3}d  AVOID {na2:>3}d", _MUTED)

        # ── COMPARATIVA ──────────────────────────────────────────────────────
        if rev_result:
            S()
            SEP()
            S()
            H("COMPARATIVA")
            rev_dec = rev_result['decision']
            tp_dec  = tp_result['decision']
            if rev_dec == tp_dec:
                L(f"Ambos motores: {_DEC_LABELS.get(rev_dec, rev_dec)}", _DEC_COLORS.get(rev_dec, _MUTED))
                L("Convergencia de señales.", _C['buy'] if rev_dec == 'BUY_CANDIDATE' else _MUTED)
            elif rev_dec == 'BUY_CANDIDATE' and tp_dec == 'AVOID':
                L("Rev: COMPRAR  /  Trend: EVITAR", _C['watch'])
                L("Divergencia. Reversal sin tendencia previa.", _C['watch'])
            elif rev_dec == 'AVOID' and tp_dec == 'BUY_CANDIDATE':
                L("Rev: EVITAR  /  Trend: COMPRAR", _C['watch'])
                L("Tendencia intacta pero estructura debilitada.", _C['watch'])
            else:
                L(f"Rev: {_DEC_LABELS.get(rev_dec,rev_dec)}  /  "
                  f"Trend: {_DEC_LABELS.get(tp_dec,tp_dec)}", _MUTED)
                L("Senales parciales — esperar confirmacion.", _MUTED)
    else:
        L("Sin datos Trend+Pullback.", _MUTED)

    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Setup de ejes
# ─────────────────────────────────────────────────────────────────────────────

def _setup_ax(ax):
    ax.set_facecolor(_PANEL_BG)
    ax.tick_params(colors=_TEXT_COLOR, labelsize=7)
    ax.spines[:].set_color(_GRID_COLOR)
    ax.yaxis.label.set_color(_TEXT_COLOR)
    ax.grid(color=_GRID_COLOR, linewidth=0.4, alpha=0.6)


# ─────────────────────────────────────────────────────────────────────────────
# Pagina por activo
# ─────────────────────────────────────────────────────────────────────────────

def _render_page(pdf, symbol, start, end, rev_result, tp_result, verbose=True):
    if verbose:
        print(f"  Generando pagina: {symbol}...")

    rows = _load_ohlcv(symbol, end)
    if not rows:
        print(f"  [SKIP] {symbol}: sin datos")
        return

    df_full = _build_df(rows)
    df      = df_full[df_full.index.date >= start]
    if df.empty:
        print(f"  [SKIP] {symbol}: sin datos en rango")
        return

    sector    = SECTOR_MAP.get(symbol, {}).get('sector', '')
    ctx_start = start - timedelta(days=60)
    mkt_cache = _load_market_ctx(ctx_start, end)
    sec_cache = _load_sector_ctx(sector, ctx_start, end) if sector else {}

    rev_signals = _compute_reversal_signals(df_full, start, mkt_cache, sec_cache)
    tp_signals  = _compute_trend_signals(df_full, start, mkt_cache, sec_cache)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)
    outer = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[3, 1],
                              wspace=0.04, left=0.05, right=0.97,
                              top=0.93, bottom=0.08)
    inner = gridspec.GridSpecFromSubplotSpec(
        2, 1, subplot_spec=outer[0],
        height_ratios=[3, 1], hspace=0.04
    )
    ax1 = fig.add_subplot(inner[0])   # precio
    ax2 = fig.add_subplot(inner[1], sharex=ax1)   # RSI
    ax_text = fig.add_subplot(outer[1])
    ax_text.set_facecolor(_PANEL_BG)
    ax_text.axis('off')
    _setup_ax(ax1)
    _setup_ax(ax2)

    # ── Precio + MAs ──────────────────────────────────────────────────────────
    ax1.plot(df.index, df['close'],  color=_C['close'],  lw=1.4, zorder=3)
    ax1.plot(df.index, df['ema20'],  color=_C['ema20'],  lw=1.1, ls='--', alpha=0.9, zorder=2)
    ax1.plot(df.index, df['sma50'],  color=_C['sma50'],  lw=1.1, alpha=0.9, zorder=2)
    ax1.plot(df.index, df['sma200'], color=_C['sma200'], lw=1.5, alpha=0.9, zorder=2)

    # Minimos locales
    closes_disp = df['close'].tolist()
    dates_disp  = list(df.index)
    local_mins  = _find_local_mins(closes_disp, w=4)
    for idx_m, price_m in local_mins:
        if idx_m < len(dates_disp):
            ax1.scatter(dates_disp[idx_m], price_m, color=_C['min'],
                        marker='x', s=40, zorder=7, linewidths=1.2)

    # Neckline del resultado actual si aplica
    if rev_result:
        pat_now = rev_result.get('pattern_state', '')
        if pat_now in ('DOUBLE_BOTTOM_FORMING', 'DOUBLE_BOTTOM_CONFIRMED', 'BASE_TENTATIVE'):
            neck = (rev_result.get('_pattern_det') or {}).get('neckline')
            if neck:
                ax1.axhline(neck, color=_C['neck'], lw=0.9, ls=':', alpha=0.75, zorder=4)
                ax1.text(df.index[-1], neck * 1.002, f'  neck ${neck:.0f}',
                         color=_C['neck'], fontsize=6, va='bottom', ha='right', zorder=8)

    # Señales Reversal (markers grandes)
    if not rev_signals.empty:
        for dt_s, row_s in rev_signals.iterrows():
            if dt_s not in df.index:
                continue
            p   = df.loc[dt_s, 'close']
            dec = row_s['decision']
            if dec == 'BUY_CANDIDATE':
                ax1.scatter(dt_s, p * 0.980, color=_C['buy'],   marker='^', s=70, zorder=6, linewidths=0)
            elif dec == 'WATCHLIST':
                ax1.scatter(dt_s, p * 0.987, color=_C['watch'], marker='o', s=24, zorder=5, linewidths=0, alpha=0.7)
            elif dec == 'AVOID':
                ax1.scatter(dt_s, p * 1.020, color=_C['avoid'], marker='v', s=50, zorder=6, linewidths=0, alpha=0.7)

    # Anotaciones de cambio de patron (rotadas, max 8)
    if not rev_signals.empty and 'pattern' in rev_signals.columns:
        prev_pat   = None
        annotations = []
        for dt_s, row_s in rev_signals.iterrows():
            if dt_s not in df.index:
                continue
            curr_pat = row_s['pattern']
            if curr_pat != prev_pat and curr_pat and curr_pat != 'NO_PATTERN':
                annotations.append((dt_s, df.loc[dt_s, 'close'], curr_pat))
                prev_pat = curr_pat
        # Limitar a 8
        step = max(1, len(annotations) // 8) if len(annotations) > 8 else 1
        for dt_s, p_a, pat_a in annotations[::step][:8]:
            lbl = _PAT_SHORT.get(pat_a, pat_a[:5])
            ax1.annotate(
                lbl,
                xy=(dt_s, p_a),
                xytext=(0, 18), textcoords='offset points',
                color=_C['watch'], fontsize=5.5,
                rotation=70, ha='center', va='bottom',
                arrowprops=dict(arrowstyle='-', color=_C['sep'], lw=0.5),
                zorder=9,
            )

    # Señales Trend+Pullback (markers pequeños distintos)
    if not tp_signals.empty:
        for dt_s, row_s in tp_signals.iterrows():
            if dt_s not in df.index:
                continue
            p   = df.loc[dt_s, 'close']
            dec = row_s['decision']
            if dec == 'BUY_CANDIDATE':
                ax1.scatter(dt_s, p * 0.970, color=_C['tp_buy'], marker='^',
                            s=28, zorder=5, linewidths=0, alpha=0.5)
            elif dec == 'AVOID':
                ax1.scatter(dt_s, p * 1.030, color=_C['tp_avd'], marker='v',
                            s=20, zorder=5, linewidths=0, alpha=0.4)

    # Leyenda
    leg = [
        Line2D([0],[0], color=_C['close'],  lw=1.4,           label='Precio'),
        Line2D([0],[0], color=_C['ema20'],  lw=1.1, ls='--',  label='EMA20'),
        Line2D([0],[0], color=_C['sma50'],  lw=1.1,           label='SMA50'),
        Line2D([0],[0], color=_C['sma200'], lw=1.5,           label='SMA200'),
        Line2D([0],[0], marker='x', color='none', markerfacecolor=_C['min'],
               markeredgecolor=_C['min'], ms=6, label='Min local'),
        Line2D([0],[0], marker='^', color='none', markerfacecolor=_C['buy'],
               ms=7, label='REV-BUY'),
        Line2D([0],[0], marker='o', color='none', markerfacecolor=_C['watch'],
               ms=5, label='REV-WATCH', alpha=0.7),
        Line2D([0],[0], marker='v', color='none', markerfacecolor=_C['avoid'],
               ms=6, label='REV-AVOID'),
        Line2D([0],[0], marker='^', color='none', markerfacecolor=_C['tp_buy'],
               ms=5, label='T+P-BUY', alpha=0.5),
        Line2D([0],[0], marker='v', color='none', markerfacecolor=_C['tp_avd'],
               ms=4, label='T+P-AVOID', alpha=0.4),
    ]
    ax1.legend(handles=leg, loc='upper left',
               facecolor=_PANEL_BG, edgecolor=_GRID_COLOR,
               labelcolor=_TEXT_COLOR, fontsize=5.8, ncol=2)
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

    # ── Titulo ────────────────────────────────────────────────────────────────
    rev_dec   = rev_result['decision'] if rev_result else 'N/A'
    rev_label = _DEC_LABELS.get(rev_dec, rev_dec)
    rev_color = _DEC_COLORS.get(rev_dec, _MUTED)

    tp_dec    = tp_result['decision'] if tp_result else 'N/A'
    tp_label  = _DEC_LABELS.get(tp_dec, tp_dec)
    tp_color  = _DEC_COLORS.get(tp_dec, _MUTED)

    fig.text(0.05, 0.96, symbol, color=_TEXT_COLOR, fontsize=16,
             fontweight='bold', va='top')
    fig.text(0.155, 0.965, f"  {start} / {end}", color=_MUTED, fontsize=9, va='top')
    # Badge reversal
    fig.text(0.63, 0.965, f"REV: [ {rev_label} ]",
             color=rev_color, fontsize=11, fontweight='bold', va='top')
    # Badge trend
    fig.text(0.78, 0.965, f"T+P: [ {tp_label} ]",
             color=tp_color, fontsize=11, fontweight='bold', va='top')

    # ── Panel texto ───────────────────────────────────────────────────────────
    analysis = _build_combined_text(rev_result, tp_result, rev_signals, tp_signals)

    y = 0.97
    for item in analysis:
        text, color, is_header = item
        fs      = 6.8 if is_header else 6.2
        fw      = 'bold' if is_header else 'normal'
        wrap_at = 44
        y_step  = 0.039
        words   = text.split()
        line    = ''
        for word in words:
            test = line + (' ' if line else '') + word
            if len(test) > wrap_at:
                ax_text.text(0.04, y, line, color=color, fontsize=fs,
                             fontweight=fw, va='top', transform=ax_text.transAxes)
                y -= y_step
                line = word
                fw   = 'normal'
                fs   = 6.2
            else:
                line = test
        if line:
            ax_text.text(0.04, y, line, color=color, fontsize=fs,
                         fontweight=fw, va='top', transform=ax_text.transAxes)
            y -= y_step
        if is_header:
            y -= 0.006

    pdf.savefig(fig, facecolor=_DARK_BG)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Portada
# ─────────────────────────────────────────────────────────────────────────────

def _render_cover(pdf, symbols, fecha, rev_results, tp_results):
    fig = plt.figure(figsize=(11.69, 8.27), facecolor=_DARK_BG)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(_DARK_BG)
    ax.axis('off')

    fig.text(0.5, 0.90, 'VectorAlpha — Reversal Engine (Fase 3) + Tendencia (Fase 2)',
             color=_TEXT_COLOR, fontsize=18, fontweight='bold', ha='center', va='top')
    fig.text(0.5, 0.83, f'Reporte comparativo  |  {fecha.strftime("%d %B %Y")}',
             color=_MUTED, fontsize=12, ha='center', va='top')

    # Sub-titulo motores
    fig.text(0.50, 0.77, 'Reversal Engine', color=_C['watch'], fontsize=9,
             fontweight='bold', ha='center')
    fig.text(0.80, 0.77, 'Trend+Pullback', color=_C['sma50'], fontsize=9,
             fontweight='bold', ha='center')

    # Headers tabla
    col_x = [0.06, 0.17, 0.28, 0.38, 0.48, 0.58, 0.68, 0.78, 0.88]
    hdrs  = ['Activo', 'Patron Rev.', 'Rev.Score', 'Contexto', 'REV.Dec',
             'Estado T+P', 'T.Score', 'P.Score', 'T+P.Dec']
    y_hdr = 0.72

    for cx, h in zip(col_x, hdrs):
        fig.text(cx, y_hdr, h, color=_MUTED, fontsize=8.5,
                 fontweight='bold', ha='left', va='top')
    fig.add_artist(plt.Line2D(
        [0.04, 0.96], [y_hdr - 0.022, y_hdr - 0.022],
        color=_GRID_COLOR, linewidth=0.8
    ))

    y = y_hdr - 0.050
    for sym in symbols:
        rv = rev_results.get(sym)
        tp = tp_results.get(sym)

        if rv:
            rev_dec = rv['decision']
            vals_rev = [
                sym,
                _PAT_ES.get(rv['pattern_state'], rv['pattern_state'])[:16],
                f"{rv['reversal_score']:.1f}",
                _ALIGN_ES.get(rv['overall_context'], rv['overall_context']),
                _DEC_LABELS.get(rev_dec, rev_dec),
            ]
            colors_rev = [
                _TEXT_COLOR, _TEXT_COLOR, _TEXT_COLOR, _TEXT_COLOR,
                _DEC_COLORS.get(rev_dec, _MUTED),
            ]
        else:
            vals_rev   = [sym, '-', '-', '-', '-']
            colors_rev = [_TEXT_COLOR] * 5

        if tp:
            tp_dec = tp['decision']
            vals_tp = [
                _STATE_ES.get(tp['setup_state'], tp['setup_state'])[:14],
                f"{tp['trend_score']:.0f}/10",
                f"{tp['pullback_score']:.0f}/10",
                _DEC_LABELS.get(tp_dec, tp_dec),
            ]
            colors_tp = [
                _TEXT_COLOR, _TEXT_COLOR, _TEXT_COLOR,
                _DEC_COLORS.get(tp_dec, _MUTED),
            ]
        else:
            vals_tp   = ['-', '-', '-', '-']
            colors_tp = [_TEXT_COLOR] * 4

        all_vals   = vals_rev + vals_tp
        all_colors = colors_rev + colors_tp

        for cx, val, col in zip(col_x, all_vals, all_colors):
            fig.text(cx, y, val, color=col, fontsize=8.5, ha='left', va='top')
        y -= 0.045

    fig.text(0.5, 0.06,
             'Reporte automatico — No constituye recomendacion de inversion.',
             color=_MUTED, fontsize=7.5, ha='center', va='bottom', style='italic')

    pdf.savefig(fig, facecolor=_DARK_BG)
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Reporte PDF Combinado Reversal+Tendencia')
    parser.add_argument('--output',  default='reports/combined_report.pdf')
    parser.add_argument('--symbols', nargs='+', default=None)
    parser.add_argument('--start',   default='2025-01-01')
    parser.add_argument('--end',     default=None)
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else UNIVERSE
    start   = date.fromisoformat(args.start)
    end     = date.fromisoformat(args.end) if args.end else date.today()

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== export_combined_pdf ===")
    print(f"Simbolos : {', '.join(symbols)}")
    print(f"Rango    : {start} -> {end}")
    print(f"Output   : {args.output}\n")

    print("Analizando con Reversal Engine...")
    rev_results = {}
    for sym in symbols:
        r = rev_analyze(sym, end)
        rev_results[sym] = r

    print("Analizando con Trend+Pullback Engine...")
    tp_results = {}
    for sym in symbols:
        r = tp_analyze(sym, end)
        tp_results[sym] = r

    print()
    print(f"{'SIM':<6}  {'PATRON':<22}  {'REV':<8}  {'ESTADO T+P':<18}  {'T+P'}")
    print('-' * 80)
    for sym in symbols:
        rv = rev_results.get(sym)
        tp = tp_results.get(sym)
        pat    = _PAT_ES.get(rv['pattern_state'], '?')[:20] if rv else '-'
        rev_d  = _DEC_LABELS.get(rv['decision'], '?') if rv else '-'
        state  = _STATE_ES.get(tp['setup_state'], '?')[:16] if tp else '-'
        tp_d   = _DEC_LABELS.get(tp['decision'], '?') if tp else '-'
        print(f"{sym:<6}  {pat:<22}  {rev_d:<8}  {state:<18}  {tp_d}")

    print()

    with PdfPages(args.output) as pdf:
        _render_cover(pdf, symbols, end, rev_results, tp_results)
        for sym in symbols:
            _render_page(pdf, sym, start, end, rev_results.get(sym), tp_results.get(sym))

        d = pdf.infodict()
        d['Title']   = f'VectorAlpha — Reversal+Tendencia {end}'
        d['Author']  = 'trading-assist engine'
        d['Subject'] = 'Analisis tecnico combinado Reversal+Tendencia'

    print(f"\nPDF generado: {args.output}")
    print(f"Paginas: {1 + len(symbols)} (portada + {len(symbols)} activos)\n")

    try:
        import subprocess
        subprocess.Popen(['start', '', args.output], shell=True)
    except Exception:
        pass


if __name__ == '__main__':
    main()
