"""
plot_asset.py — grafico de debug para un activo

Modos:
  --mode trend    (default) Señales Trend+Pullback
  --mode reversal           Señales Reversal Engine

Muestra:
  - Precio (close), EMA20, SMA50, SMA200
  - Marcadores BUY/WATCHLIST/AVOID calculados en rolling sobre el rango
  - RSI(14) en subplot inferior

Modo reversal agrega:
  - Minimos locales marcados con 'x' naranja
  - Anotaciones de cambio de patron (etiqueta pequeña)
  - Neckline horizontal si DB_FORMING/CONFIRMED al final

Uso:
    python scripts/plot_asset.py --symbol GOOGL
    python scripts/plot_asset.py --symbol MSFT --mode reversal
    python scripts/plot_asset.py --symbol NVDA --mode reversal --save charts/nvda_rev.png
"""
import argparse
import sys
import os
from datetime import date, datetime, timedelta
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_conn
from strategies.trend_pullback import (
    _score_trend, _score_pullback, _classify_setup,
    _make_confidence, _make_decision,
    _MARKET_WEIGHT, _SECTOR_WEIGHT,
)
from strategies.reversal import (
    _detect_pattern as _rev_detect_pattern,
    _PATTERN_DECISION as _REV_PATTERN_DECISION,
    _apply_context_degradation as _rev_degrade,
    _find_local_mins,
    _detect_selling_pressure,
    _DB_BOUNCE_GOOD, _DB_VS_SMA200, _DB_VOLR_MAX,
)
from strategies.support_zones import (
    analyze_symbol as sz_analyze,
    analyze_trend_support as ts_analyze,
)
from strategies.rsi_divergence import analyze_symbol as div_analyze
from strategies.utils import ema as _ema_list, sma as _sma_list, momentum_pct, vol_ratio, vs_peak, higher_low
from config import SECTOR_MAP

# Labels cortos para anotaciones de patron en modo reversal
_PAT_SHORT = {
    'DOUBLE_BOTTOM_CONFIRMED':   'DB-CONF',
    'DOUBLE_BOTTOM_FORMING':     'DB-FORM',
    'BASE_TENTATIVE':            'BASE-T.',
    'HIGHER_LOW_UPTREND':        'HL-UPT.',
    'FLOOR_FORMING':             'FLOOR  ',
    'OVERSOLD_ONLY':             'OVERSLD',
    'BEAR_MARKET_FAKE_REVERSAL': 'FAKE-R.',
    'BREAKDOWN_ACTIVE':          'BRKDOWN',
    'NO_PATTERN':                'NO-PAT.',
}

# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def _load_ohlcv_full(symbol: str, end: date) -> pd.DataFrame:
    """Carga OHLCV completo hasta `end` (necesita buffer para SMA200)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, open, high, low, close, volume
                   FROM price_history
                   WHERE simbolo=%s AND fecha<=%s
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
    df = df.astype({'open': float, 'high': float, 'low': float,
                    'close': float, 'volume': float})
    return df


def _load_market_context(start: date, end: date) -> dict:
    """Carga regímenes de mercado para el rango → {fecha: regime}."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, regime FROM market_context_daily
                   WHERE fecha BETWEEN %s AND %s ORDER BY fecha ASC""",
                (start, end)
            )
            return {row['fecha']: row['regime'] for row in cur.fetchall()}
    finally:
        conn.close()


def _load_sector_context(sector: str, start: date, end: date) -> dict:
    """Carga regímenes sectoriales para el rango → {fecha: regime}."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT fecha, regime FROM sector_context_daily
                   WHERE sector=%s AND fecha BETWEEN %s AND %s ORDER BY fecha ASC""",
                (sector, start, end)
            )
            return {row['fecha']: row['regime'] for row in cur.fetchall()}
    finally:
        conn.close()


def _nearest_regime(cache: dict, d) -> str:
    """Devuelve el régimen más reciente disponible para la fecha dada."""
    d_key = d.date() if hasattr(d, 'date') else d
    # Buscar hacia atrás hasta 10 días
    for i in range(11):
        key = d_key - timedelta(days=i)
        if key in cache:
            return cache[key]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Indicadores con pandas (rápido y vectorizado)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss
    return (100 - 100 / (1 + rs)).round(2)


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema20']  = df['close'].ewm(span=20, adjust=False).mean()
    df['sma50']  = df['close'].rolling(50).mean()
    df['sma200'] = df['close'].rolling(200).mean()
    df['rsi']    = _compute_rsi(df['close'], 14)
    df['mom20']  = df['close'].pct_change(20) * 100
    df['mom60']  = df['close'].pct_change(60) * 100
    df['vol_r']  = df['volume'].rolling(5).mean() / df['volume'].rolling(20).mean()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo de señales por fecha (rolling, sin DB por iteración)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_signals_range(
    df: pd.DataFrame,
    start: date,
    symbol: str,
    mkt_cache: dict,
    sec_cache: dict,
) -> pd.DataFrame:
    """
    Calcula señales Trend+Pullback para cada fecha del rango [start, fin del df].
    Usa datos rolling (cada fecha solo ve lo que estaba disponible hasta ese día).
    """
    closes_all  = df['close'].tolist()
    volumes_all = df['volume'].tolist()
    fechas_all  = list(df.index)

    MIN_BARS = 60
    records  = []

    for i, dt in enumerate(fechas_all):
        if dt.date() < start:
            continue
        if i < MIN_BARS:
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
        rsi_v    = df.loc[dt, 'rsi'] if 'rsi' in df.columns else None
        vol_r_v  = df.loc[dt, 'vol_r'] if 'vol_r' in df.columns else None

        trend_sc, _ = _score_trend(price, ema20_v, sma50_v, sma200_v, mom20_v, mom60_v, peak60_v)
        pull_sc, _  = _score_pullback(price, ema20_v, sma50_v, rsi_v, vol_r_v, mom20_v, closes)
        state       = _classify_setup(trend_sc, pull_sc, price, sma200_v, ema20_v, mom20_v, mom60_v)

        # Contexto desde caché
        mkt_r = _nearest_regime(mkt_cache, dt) or 'RANGE'
        sec_r = _nearest_regime(sec_cache, dt) or 'NEUTRAL'
        mkt_w = _MARKET_WEIGHT.get(mkt_r, 0.0)
        sec_w = _SECTOR_WEIGHT.get(sec_r, 0.0)
        total = mkt_w + sec_w
        alignment = 'favorable' if total >= 1.0 else ('unfavorable' if total <= -0.5 else 'neutral')

        confidence = _make_confidence(state, trend_sc, pull_sc, alignment)
        decision   = _make_decision(state, alignment, confidence, trend_sc)

        records.append({
            'fecha':      dt,
            'decision':   decision,
            'state':      state,
            'trend_sc':   trend_sc,
            'pull_sc':    pull_sc,
            'alignment':  alignment,
        })

    return pd.DataFrame(records).set_index('fecha') if records else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Señales Reversal en rolling (un resultado por fecha, sin look-ahead)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_reversal_signals_range(
    df:        pd.DataFrame,
    start:     date,
    symbol:    str,
    mkt_cache: dict,
    sec_cache: dict,
) -> pd.DataFrame:
    """
    Calcula señales Reversal para cada fecha del rango.
    Usa datos rolling (cada fecha solo ve lo disponible hasta ese día).
    """
    opens_all   = df['open'].tolist()
    closes_all  = df['close'].tolist()
    highs_all   = df['high'].tolist()
    lows_all    = df['low'].tolist()
    volumes_all = df['volume'].tolist()
    fechas_all  = list(df.index)
    MIN_BARS    = 60
    records     = []

    def _safe(v):
        import math
        try:
            return None if (v is None or math.isnan(float(v))) else float(v)
        except Exception:
            return None

    for i, dt in enumerate(fechas_all):
        if dt.date() < start:
            continue
        if i < MIN_BARS:
            continue

        opens   = opens_all[:i + 1]
        closes  = closes_all[:i + 1]
        highs   = highs_all[:i + 1]
        lows    = lows_all[:i + 1]
        volumes = volumes_all[:i + 1]

        rsi_v    = df.loc[dt, 'rsi']    if 'rsi'    in df.columns else None
        vol_r_v  = df.loc[dt, 'vol_r'] if 'vol_r'  in df.columns else None
        mom20_v  = df.loc[dt, 'mom20'] if 'mom20'  in df.columns else None
        mom60_v  = df.loc[dt, 'mom60'] if 'mom60'  in df.columns else None
        ema20_v  = df.loc[dt, 'ema20'] if 'ema20'  in df.columns else None
        sma50_v  = df.loc[dt, 'sma50'] if 'sma50'  in df.columns else None
        sma200_v = df.loc[dt, 'sma200'] if 'sma200' in df.columns else None

        sell_p = _detect_selling_pressure(opens, highs, lows, closes, volumes)

        pattern, _ = _rev_detect_pattern(
            closes, lows, volumes,
            _safe(mom20_v), _safe(mom60_v), _safe(rsi_v), _safe(vol_r_v),
            _safe(sma50_v), _safe(ema20_v), _safe(sma200_v),
            selling_pressure=sell_p,
        )

        mkt_r = _nearest_regime(mkt_cache, dt) or 'RANGE'
        sec_r = _nearest_regime(sec_cache, dt) or 'NEUTRAL'
        mkt_align = (
            'favorable'   if mkt_r == 'TREND_UP' else
            'unfavorable' if mkt_r in ('TREND_DOWN', 'VOLATILE') else
            'neutral'
        )
        sec_align = (
            'strong' if sec_r == 'STRONG' else
            'weak'   if sec_r == 'WEAK'   else
            'neutral'
        )

        raw_decision = _REV_PATTERN_DECISION.get(pattern, 'AVOID')
        decision     = _rev_degrade(raw_decision, mkt_align, sec_align)

        records.append({
            'fecha':            dt,
            'decision':         decision,
            'pattern':          pattern,
            'selling_pressure': sell_p,
        })

    return pd.DataFrame(records).set_index('fecha') if records else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Plot
# ─────────────────────────────────────────────────────────────────────────────

_DARK_BG    = '#0d1117'
_PANEL_BG   = '#161b22'
_GRID_COLOR = '#21262d'
_TEXT_COLOR = '#c9d1d9'

_COLORS = {
    'close':  '#e6edf3',
    'ema20':  '#f0a500',
    'sma50':  '#4fc3f7',
    'sma200': '#ef5350',
    'rsi':    '#ce93d8',
    'buy':    '#3fb950',
    'watch':  '#d29922',
    'avoid':  '#f85149',
    'ob':     '#ef5350',   # overbought line
    'os':     '#3fb950',   # oversold line
}


def _setup_dark(ax):
    ax.set_facecolor(_PANEL_BG)
    ax.tick_params(colors=_TEXT_COLOR, labelsize=8)
    ax.spines[:].set_color(_GRID_COLOR)
    ax.yaxis.label.set_color(_TEXT_COLOR)
    ax.xaxis.label.set_color(_TEXT_COLOR)
    ax.grid(color=_GRID_COLOR, linewidth=0.5, alpha=0.7)


def plot_asset(
    symbol:       str,
    start:        date,
    end:          date,
    show_signals: bool = True,
    save_path:    str  = None,
    mode:         str  = 'trend',    # 'trend', 'reversal' o 'support'
):
    print(f"Cargando {symbol} ({start} -> {end})...")

    # ── Cargar datos ───────────────────────────────────────────────────────────
    df_full = _load_ohlcv_full(symbol, end)
    if df_full.empty:
        print(f"[ERROR] Sin datos para {symbol} en price_history.")
        return

    df_full = _add_indicators(df_full)
    df      = df_full[df_full.index.date >= start]

    if df.empty:
        print(f"[ERROR] Sin datos en el rango {start} → {end}")
        return

    # ── Señales ────────────────────────────────────────────────────────────────
    signals_df = pd.DataFrame()
    sec_cache  = {}
    if show_signals and mode != 'divergence':
        sector    = SECTOR_MAP.get(symbol, {}).get('sector', '')
        ctx_start = start - timedelta(days=60)
        mkt_cache = _load_market_context(ctx_start, end)
        sec_cache = _load_sector_context(sector, ctx_start, end) if sector else {}
        print(f"Calculando señales ({mode}) para {len(df)} fechas...")
        if mode == 'reversal':
            signals_df = _compute_reversal_signals_range(
                df_full, start, symbol, mkt_cache, sec_cache
            )
        else:
            signals_df = _compute_signals_range(
                df_full, start, symbol, mkt_cache, sec_cache
            )

    # ── Zona de soporte (modo support) ────────────────────────────────────────
    sz_result  = None
    ts_result  = None
    div_result = None
    if mode == 'support':
        sz_result = sz_analyze(symbol, end)
        ts_result = ts_analyze(symbol, end)
    elif mode == 'divergence':
        print(f"Calculando divergencia RSI para {symbol}...")
        div_result = div_analyze(symbol, end)

    # ── Figura ─────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(15, 9), facecolor=_DARK_BG)
    gs  = gridspec.GridSpec(
        2, 1, figure=fig,
        height_ratios=[3, 1],
        hspace=0.04,
    )
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)

    _setup_dark(ax1)
    _setup_dark(ax2)
    ax1.set_yscale('log')

    # ── Panel 1: Precio + MAs ─────────────────────────────────────────────────
    ax1.plot(df.index, df['close'],  label='Precio', color=_COLORS['close'],
             linewidth=1.4, zorder=3)
    ax1.plot(df.index, df['ema20'],  label='EMA20',  color=_COLORS['ema20'],
             linewidth=1.2, linestyle='--', alpha=0.9, zorder=2)
    ax1.plot(df.index, df['sma50'],  label='SMA50',  color=_COLORS['sma50'],
             linewidth=1.2, alpha=0.9, zorder=2)
    ax1.plot(df.index, df['sma200'], label='SMA200', color=_COLORS['sma200'],
             linewidth=1.6, alpha=0.9, zorder=2)

    # ── Marcadores de señal ────────────────────────────────────────────────────
    if not signals_df.empty:
        for dt, row in signals_df.iterrows():
            if dt not in df.index:
                continue
            price = df.loc[dt, 'close']
            dec   = row['decision']
            if dec == 'BUY_CANDIDATE':
                ax1.scatter(dt, price * 0.982, color=_COLORS['buy'],
                            marker='^', s=90, zorder=6, edgecolors='none')
            elif dec == 'WATCHLIST':
                ax1.scatter(dt, price * 0.987, color=_COLORS['watch'],
                            marker='o', s=35, zorder=5, edgecolors='none', alpha=0.7)
            elif dec == 'AVOID':
                ax1.scatter(dt, price * 1.018, color=_COLORS['avoid'],
                            marker='v', s=65, zorder=6, edgecolors='none', alpha=0.8)

    # ── Parametros visuales segun jerarquia de soporte ───────────────────────
    _QUALITY_VIZ = {
        'WEAK_SUPPORT':         {'lw': 0.8, 'line_alpha': 0.50, 'band_alpha': 0.07, 'fs': 6.0},
        'MID_SUPPORT':          {'lw': 1.3, 'line_alpha': 0.70, 'band_alpha': 0.11, 'fs': 6.5},
        'LONG_TERM_SUPPORT':    {'lw': 2.0, 'line_alpha': 0.88, 'band_alpha': 0.17, 'fs': 7.5},
        'STRUCTURAL_SUPPORT':   {'lw': 2.8, 'line_alpha': 1.00, 'band_alpha': 0.24, 'fs': 8.5},
        'BROKEN_MAJOR_SUPPORT': {'lw': 2.0, 'line_alpha': 0.75, 'band_alpha': 0.13, 'fs': 7.5},
    }
    _TF_LABEL = {
        'SHORT_TERM': 'CORTO', 'MID_TERM': 'MEDIO',
        'LONG_TERM': 'LARGO', 'STRUCTURAL': 'ESTRUCTURAL',
    }

    # ── Support zone visualization ────────────────────────────────────────────
    if mode == 'support' and sz_result and sz_result['state'] != 'NO_SUPPORT':
        zone   = sz_result['_zone']
        zl     = zone['zone_low']
        zh     = zone['zone_high']
        zc     = zone['center']
        qlabel = sz_result.get('quality_label', 'MID_SUPPORT')
        qviz   = _QUALITY_VIZ.get(qlabel, _QUALITY_VIZ['MID_SUPPORT'])

        _SZ_STATE_COLORS = {
            'SUPPORT_BOUNCE_CONFIRMED': '#3fb950',
            'SUPPORT_HOLDING':          '#4fc3f7',
            'SUPPORT_ZONE_RETESTED':    '#d29922',
            'SUPPORT_ZONE_DETECTED':    '#8b949e',
            'SUPPORT_BROKEN':           '#f85149',
        }
        zcolor = _SZ_STATE_COLORS.get(sz_result['state'], '#8b949e')

        # Banda sombreada (mas intensa segun jerarquia)
        ax1.axhspan(zl, zh, alpha=qviz['band_alpha'], color=zcolor, zorder=1)
        # Linea central (mas gruesa segun jerarquia)
        ax1.axhline(zc, color=zcolor, lw=qviz['lw'], ls='--',
                    alpha=qviz['line_alpha'], zorder=2)

        # Label con jerarquia
        tf_str    = _TF_LABEL.get(sz_result.get('timeframe', ''), '')
        dur_str   = f"{sz_result.get('duration_days', 0)}d"
        score_str = f"{sz_result.get('support_score', 0):.1f}"
        tq_str    = str(sz_result.get('touches_count', 0))
        ax1.text(
            df.index[0], zc,
            f'  {tf_str} ${zc:.2f}  [{dur_str} · {tq_str}tq · {score_str}]',
            color=zcolor, fontsize=qviz['fs'], va='bottom', ha='left',
            fontweight='bold' if qlabel in ('STRUCTURAL_SUPPORT', 'LONG_TERM_SUPPORT') else 'normal',
            zorder=8,
        )

        # Marker primer toque
        ft_date = zone['first_touch_date']
        if ft_date:
            ft_ts = pd.Timestamp(ft_date)
            if ft_ts in df.index:
                ft_price = df.loc[ft_ts, 'low']
                ax1.scatter(ft_ts, ft_price * 0.985, color=zcolor, marker='D',
                            s=55, zorder=7, linewidths=0)
                ax1.annotate('T1', xy=(ft_ts, ft_price * 0.983),
                             xytext=(0, -14), textcoords='offset points',
                             color=zcolor, fontsize=6, ha='center')

        # Marker segundo toque (retest)
        st_date = zone['second_touch_date']
        if st_date:
            st_ts = pd.Timestamp(st_date)
            if st_ts in df.index:
                st_price = df.loc[st_ts, 'low']
                ax1.scatter(st_ts, st_price * 0.985, color=zcolor, marker='D',
                            s=55, zorder=7, linewidths=0)
                ax1.annotate('T2', xy=(st_ts, st_price * 0.983),
                             xytext=(0, -14), textcoords='offset points',
                             color=zcolor, fontsize=6, ha='center')

    # ── Directriz alcista (modo support) ─────────────────────────────────────
    _TS_STATE_COLORS = {
        'TREND_SUPPORT_BOUNCE_CONFIRMED': '#3fb950',
        'TREND_SUPPORT_HOLDING':          '#a8d8a8',
        'TREND_SUPPORT_RETESTED':         '#d29922',
        'TREND_SUPPORT_DETECTED':         '#8b949e',
        'TREND_SUPPORT_BROKEN':           '#f85149',
    }
    if mode == 'support' and ts_result and ts_result['_trendline'] is not None:
        tl       = ts_result['_trendline']
        ts_color = _TS_STATE_COLORS.get(ts_result['state'], '#8b949e')
        all_dates_ts = ts_result['_dates']   # list of date objects

        # Construir mapping date -> bar_index para proyectar la linea
        date_to_idx = {d: k for k, d in enumerate(all_dates_ts)}

        # Calcular valores de la linea para cada fecha visible en el grafico
        tl_plot_dates  = []
        tl_plot_values = []
        for dt in df.index:
            d = dt.date() if hasattr(dt, 'date') else dt
            if d in date_to_idx:
                k   = date_to_idx[d]
                val = tl['slope'] * k + tl['intercept']
                if val > 0:
                    tl_plot_dates.append(dt)
                    tl_plot_values.append(val)

        if tl_plot_dates:
            ts_qlabel = ts_result.get('quality_label', 'MID_SUPPORT')
            ts_qviz   = _QUALITY_VIZ.get(ts_qlabel, _QUALITY_VIZ['MID_SUPPORT'])
            ax1.plot(tl_plot_dates, tl_plot_values,
                     color=ts_color, lw=ts_qviz['lw'], ls='-',
                     alpha=ts_qviz['line_alpha'], zorder=4)
            # Label con jerarquia al final de la linea
            ts_tf_str  = _TF_LABEL.get(ts_result.get('timeframe', ''), '')
            ts_dur_str = f"{ts_result.get('duration_days', 0)}d"
            ts_sc_str  = f"{ts_result.get('support_score', 0):.1f}"
            ts_tq_str  = str(ts_result.get('touch_count', 0))
            ax1.text(
                tl_plot_dates[-1], tl_plot_values[-1],
                f'  {ts_tf_str} TL ${tl_plot_values[-1]:.2f}  [{ts_dur_str} · {ts_tq_str}tq · {ts_sc_str}]',
                color=ts_color, fontsize=ts_qviz['fs'], va='bottom', ha='left',
                fontweight='bold' if ts_qlabel in ('STRUCTURAL_SUPPORT', 'LONG_TERM_SUPPORT') else 'normal',
                zorder=8,
            )

        # Marcar puntos de toque en la directriz
        for td in ts_result['touch_dates']:
            td_ts = pd.Timestamp(td)
            if td_ts in df.index:
                td_price = df.loc[td_ts, 'low']
                ax1.scatter(td_ts, td_price * 0.983, color=ts_color,
                            marker='^', s=50, zorder=7, linewidths=0)

    # ── Divergencia RSI (modo divergence) ────────────────────────────────────
    if mode == 'divergence' and div_result and div_result['divergence_state'] != 'NO_DIVERGENCE':
        div_type  = div_result['divergence_type']
        div_state = div_result['divergence_state']
        is_bull   = div_type == 'BULLISH'
        confirmed = 'CONFIRMED' in div_state

        # Color: verde alcista, rojo bajista; mas brillante si confirmado
        if is_bull:
            div_color = '#3fb950' if confirmed else '#238636'
        else:
            div_color = '#f85149' if confirmed else '#b62324'

        p1 = div_result['price_pivot_1']
        p2 = div_result['price_pivot_2']
        r1 = div_result['rsi_pivot_1']
        r2 = div_result['rsi_pivot_2']
        pt1_ts = pd.Timestamp(div_result['pivot_1_date'])
        pt2_ts = pd.Timestamp(div_result['pivot_2_date'])

        # ── Panel precio: markers y linea ──────────────────────────────────
        # Usar lows para bullish, highs para bearish
        y1_price = df.loc[pt1_ts, 'low']  if (pt1_ts in df.index and is_bull) else \
                   df.loc[pt1_ts, 'high'] if (pt1_ts in df.index) else p1
        y2_price = df.loc[pt2_ts, 'low']  if (pt2_ts in df.index and is_bull) else \
                   df.loc[pt2_ts, 'high'] if (pt2_ts in df.index) else p2

        ax1.scatter([pt1_ts], [y1_price], color=div_color, s=100,
                    zorder=9, marker='o', linewidths=1.5,
                    edgecolors='white', alpha=0.85)
        ax1.scatter([pt2_ts], [y2_price], color=div_color, s=140,
                    zorder=9, marker='o', linewidths=2.0,
                    edgecolors='white')

        if pt1_ts in df.index and pt2_ts in df.index:
            ax1.plot([pt1_ts, pt2_ts], [y1_price, y2_price],
                     color=div_color, lw=1.8, ls='--', alpha=0.75, zorder=5)

        # Anotacion en el segundo pivot
        label_txt = ('DIV ALCISTA' if is_bull else 'DIV BAJISTA') + \
                    (' (CONF)' if confirmed else ' (FORM.)')
        offset_y = -30 if is_bull else 30
        if pt2_ts in df.index:
            ax1.annotate(
                label_txt,
                xy=(pt2_ts, y2_price),
                xytext=(0, offset_y),
                textcoords='offset points',
                color=div_color, fontsize=9, fontweight='bold', ha='center',
                arrowprops=dict(arrowstyle='->', color=div_color, lw=1.3),
            )

        # ── Panel RSI: markers y linea de divergencia ──────────────────────
        if pt1_ts in df.index and pt2_ts in df.index:
            ax2.scatter([pt1_ts], [r1], color=div_color, s=80,
                        zorder=9, marker='o', linewidths=1.5, edgecolors='white', alpha=0.85)
            ax2.scatter([pt2_ts], [r2], color=div_color, s=110,
                        zorder=9, marker='o', linewidths=2.0, edgecolors='white')
            ax2.plot([pt1_ts, pt2_ts], [r1, r2],
                     color=div_color, lw=1.8, ls='--', alpha=0.75, zorder=5)
            # Etiquetas RSI
            ax2.annotate(f'{r1:.0f}', xy=(pt1_ts, r1), xytext=(4, 4),
                         textcoords='offset points',
                         color=div_color, fontsize=7, ha='left')
            ax2.annotate(f'{r2:.0f}', xy=(pt2_ts, r2), xytext=(4, 4),
                         textcoords='offset points',
                         color=div_color, fontsize=7, ha='left')

        # Barra de info en parte inferior
        conf_str = div_result['confidence_level'] or '---'
        dec_str  = div_result['decision']
        t1_str   = str(div_result['pivot_1_date'])[:10] if div_result['pivot_1_date'] else '-'
        t2_str   = str(div_result['pivot_2_date'])[:10] if div_result['pivot_2_date'] else '-'
        info = (
            f"Estado: {div_state}  |  Confianza: {conf_str}  |  Decision: {dec_str}  |  "
            f"P1: ${p1:.2f} ({t1_str})  P2: ${p2:.2f} ({t2_str})  |  "
            f"RSI: {r1:.1f} -> {r2:.1f}"
        )
        fig.text(0.5, 0.002, info, ha='center', va='bottom', color=div_color, fontsize=7.5)

    # Leyenda de señales como parches
    from matplotlib.lines import Line2D
    legend_elems = [
        Line2D([0], [0], color=_COLORS['close'],  linewidth=1.4, label='Precio'),
        Line2D([0], [0], color=_COLORS['ema20'],  linewidth=1.2, linestyle='--', label='EMA20'),
        Line2D([0], [0], color=_COLORS['sma50'],  linewidth=1.2, label='SMA50'),
        Line2D([0], [0], color=_COLORS['sma200'], linewidth=1.6, label='SMA200'),
    ]
    if show_signals:
        legend_elems += [
            Line2D([0], [0], marker='^', color='none', markerfacecolor=_COLORS['buy'],
                   markersize=9, label='BUY CANDIDATE'),
            Line2D([0], [0], marker='o', color='none', markerfacecolor=_COLORS['watch'],
                   markersize=7, label='WATCHLIST', alpha=0.7),
            Line2D([0], [0], marker='v', color='none', markerfacecolor=_COLORS['avoid'],
                   markersize=8, label='AVOID'),
        ]
    if mode == 'reversal':
        legend_elems += [
            Line2D([0], [0], marker='x', color='none', markerfacecolor='#ff8c00',
                   markeredgecolor='#ff8c00', markersize=8, label='Min local'),
            Line2D([0], [0], marker='s', color='none', markerfacecolor='#ff4444',
                   markersize=6, label='Sell.Press.', alpha=0.85),
        ]
    if mode == 'support' and sz_result and sz_result['state'] != 'NO_SUPPORT':
        _sc = {'SUPPORT_BOUNCE_CONFIRMED': '#3fb950', 'SUPPORT_HOLDING': '#4fc3f7',
               'SUPPORT_ZONE_RETESTED': '#d29922', 'SUPPORT_ZONE_DETECTED': '#8b949e',
               'SUPPORT_BROKEN': '#f85149'}.get(sz_result['state'], '#8b949e')
        legend_elems += [
            Line2D([0], [0], color=_sc, lw=1.5, ls='--', label='Soporte horiz.'),
            Line2D([0], [0], marker='D', color='none', markerfacecolor=_sc,
                   markersize=6, label='Toque horiz.'),
        ]
    if mode == 'support' and ts_result and ts_result['_trendline'] is not None:
        _tc = _TS_STATE_COLORS.get(ts_result['state'], '#8b949e')
        legend_elems += [
            Line2D([0], [0], color=_tc, lw=1.6, ls='-', label='Directriz'),
            Line2D([0], [0], marker='^', color='none', markerfacecolor=_tc,
                   markersize=6, label='Toque directriz'),
        ]
    leg = ax1.legend(
        handles=legend_elems, loc='upper left',
        facecolor=_PANEL_BG, edgecolor=_GRID_COLOR,
        labelcolor=_TEXT_COLOR, fontsize=8,
    )

    ax1.set_ylabel('Precio (USD)', color=_TEXT_COLOR, fontsize=9)
    if mode == 'reversal':
        engine_label = 'Reversal Engine'
    elif mode == 'support':
        engine_label = 'Support Zones'
    elif mode == 'divergence':
        engine_label = 'RSI Divergence Engine'
    else:
        engine_label = 'Trend+Pullback Engine'

    # Sector info en titulo (modo reversal)
    sector_name = SECTOR_MAP.get(symbol, {}).get('sector', '')
    sec_suffix  = ''
    if mode == 'reversal' and sector_name and sec_cache:
        last_sec_regime = None
        for d in sorted(sec_cache.keys(), reverse=True):
            last_sec_regime = sec_cache[d]
            break
        if last_sec_regime:
            sec_suffix = f'  |  Sector: {sector_name} ({last_sec_regime})'

    ax1.set_title(
        f'{symbol}  |  {start.strftime("%Y-%m-%d")} - {end.strftime("%Y-%m-%d")}  |  '
        f'{engine_label}{sec_suffix}',
        color=_TEXT_COLOR, fontsize=11, pad=10,
    )

    # ── Subtitulo modo support ─────────────────────────────────────────────────
    if mode == 'support':
        sub_parts = []

        # Soporte horizontal
        if sz_result:
            sp_str   = f"${sz_result['support_price']:.2f}" if sz_result['support_price'] else '-'
            sz_ql    = sz_result.get('quality_label', '')
            sz_score = sz_result.get('support_score', 0)
            sz_dur   = sz_result.get('duration_days', 0)
            sub_parts.append(
                f"Horizontal: {sp_str}  [{sz_ql}  {sz_dur}d  score={sz_score:.1f}]"
            )

        # Directriz alcista
        if ts_result:
            tl_str   = f"${ts_result['line_current']:.2f}" if ts_result.get('line_current') else '-'
            ts_ql    = ts_result.get('quality_label', '')
            ts_score = ts_result.get('support_score', 0)
            ts_dur   = ts_result.get('duration_days', 0)
            sub_parts.append(
                f"Directriz: {tl_str}  [{ts_ql}  {ts_dur}d  score={ts_score:.1f}]"
            )

        if sub_parts:
            fig.text(0.5, 0.935, '     |     '.join(sub_parts),
                     ha='center', va='bottom', color='#8b949e', fontsize=8)

    # ── Extras modo reversal ───────────────────────────────────────────────────
    if mode == 'reversal':
        # Marcar dias con presion vendedora (cuadrado rojo en parte superior)
        if not signals_df.empty and 'selling_pressure' in signals_df.columns:
            sp_dates = [dt for dt, row in signals_df.iterrows()
                        if row.get('selling_pressure') and dt in df.index]
            if sp_dates:
                sp_prices = [df.loc[dt, 'high'] * 1.008 for dt in sp_dates]
                ax1.scatter(sp_dates, sp_prices, color='#ff4444', marker='s',
                            s=22, zorder=8, linewidths=0, alpha=0.85)

        # Marcar mínimos locales detectados en el rango visible
        closes_list = df['close'].tolist()
        local_mins  = _find_local_mins(closes_list, w=4)
        if local_mins:
            min_dates  = [df.index[idx] for idx, _ in local_mins if idx < len(df)]
            min_prices = [p for idx, p in local_mins if idx < len(df)]
            ax1.scatter(min_dates, min_prices, color='#ff8c00', marker='x',
                        s=60, zorder=7, linewidths=1.5, label='Min local')

        # Anotar cambios de patron (solo cuando cambia, texto pequeño)
        if not signals_df.empty and 'pattern' in signals_df.columns:
            prev_pat   = None
            ann_count  = 0
            for ann_dt, ann_row in signals_df.iterrows():
                pat = ann_row.get('pattern', '')
                if pat != prev_pat and pat not in ('NO_PATTERN',) and ann_count < 8:
                    px = df.loc[ann_dt, 'close'] if ann_dt in df.index else None
                    if px is not None:
                        short = _PAT_SHORT.get(pat, pat[:7])
                        ax1.annotate(
                            short,
                            xy=(ann_dt, px),
                            xytext=(0, 18),
                            textcoords='offset points',
                            color='#8b949e',
                            fontsize=5.5,
                            rotation=55,
                            ha='left',
                        )
                        ann_count += 1
                prev_pat = pat

        # Neckline horizontal si el ultimo patron es DB
        if not signals_df.empty and 'pattern' in signals_df.columns:
            last_pat = signals_df['pattern'].iloc[-1]
            if last_pat in ('DOUBLE_BOTTOM_FORMING', 'DOUBLE_BOTTOM_CONFIRMED'):
                # Recalcular neckline del ultimo patron
                from strategies.reversal import _detect_double_bottom as _rdb
                vol_last = df['vol_r'].iloc[-1] if 'vol_r' in df.columns else None
                s200_last = df['sma200'].iloc[-1] if 'sma200' in df.columns else None
                try:
                    import math
                    vol_l  = None if (vol_last  is None or math.isnan(float(vol_last)))  else float(vol_last)
                    s200_l = None if (s200_last is None or math.isnan(float(s200_last))) else float(s200_last)
                except Exception:
                    vol_l, s200_l = None, None
                _, db_det = _rdb(df['close'].tolist(), vol_l, s200_l)
                if db_det.get('neckline'):
                    nk = db_det['neckline']
                    ax1.axhline(nk, color='#f0a500', ls=':', lw=1.2, alpha=0.7, zorder=3)
                    ax1.text(df.index[-1], nk, f' NL ${nk:.0f}',
                             color='#f0a500', fontsize=7, va='bottom')

    # ── Panel 2: RSI ──────────────────────────────────────────────────────────
    ax2.plot(df.index, df['rsi'], color=_COLORS['rsi'], linewidth=1.1, label='RSI(14)')
    ax2.axhline(70, color=_COLORS['ob'], linestyle='--', linewidth=0.8, alpha=0.6)
    ax2.axhline(30, color=_COLORS['os'], linestyle='--', linewidth=0.8, alpha=0.6)
    ax2.fill_between(df.index, 30, df['rsi'].clip(upper=30),
                     alpha=0.15, color=_COLORS['os'])
    ax2.fill_between(df.index, 70, df['rsi'].clip(lower=70),
                     alpha=0.15, color=_COLORS['ob'])
    ax2.set_ylim(0, 100)
    ax2.set_yticks([30, 50, 70])
    ax2.set_ylabel('RSI(14)', color=_TEXT_COLOR, fontsize=9)
    ax2.text(df.index[-1], 72, 'OB', color=_COLORS['ob'],
             fontsize=7, va='bottom', ha='right')
    ax2.text(df.index[-1], 28, 'OS', color=_COLORS['os'],
             fontsize=7, va='top', ha='right')

    # ── Eje X ─────────────────────────────────────────────────────────────────
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=0, ha='center',
             color=_TEXT_COLOR, fontsize=8)
    plt.setp(ax1.xaxis.get_majorticklabels(), visible=False)

    # Estadísticas de señales en el título
    if show_signals and not signals_df.empty:
        buy_n   = (signals_df['decision'] == 'BUY_CANDIDATE').sum()
        watch_n = (signals_df['decision'] == 'WATCHLIST').sum()
        avoid_n = (signals_df['decision'] == 'AVOID').sum()
        stats_text = (
            f"BUY: {buy_n}d  |  WATCHLIST: {watch_n}d  |  AVOID: {avoid_n}d"
        )
        fig.text(0.5, 0.005, stats_text, ha='center', va='bottom',
                 color='#8b949e', fontsize=8)

    plt.tight_layout(rect=[0, 0.02, 1, 1])

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor=_DARK_BG)
        print(f"Guardado en: {save_path}")
    else:
        plt.show()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Grafico de debug (Trend+Pullback o Reversal)')
    parser.add_argument('--symbol',     required=True,        help='Ticker (ej. GOOGL)')
    parser.add_argument('--start',      default='2025-01-01', help='Fecha inicio YYYY-MM-DD')
    parser.add_argument('--end',        default=None,         help='Fecha fin YYYY-MM-DD (default: hoy)')
    parser.add_argument('--mode',       default='trend',      help='trend (default), reversal, support o divergence')
    parser.add_argument('--no-signals', action='store_true',  help='Solo precio y MAs, sin señales')
    parser.add_argument('--save',       default=None,         help='Ruta para guardar PNG')
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end) if args.end else date.today()

    plot_asset(
        symbol=args.symbol.upper(),
        start=start,
        end=end,
        show_signals=not args.no_signals,
        save_path=args.save,
        mode=args.mode.lower(),
    )


if __name__ == '__main__':
    main()
