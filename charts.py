"""
charts.py — Gráficos Plotly para trading-assist
"""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# ── Paleta dark terminal ──────────────────────────────────────────────────────
C = {
    'bg':      '#0a0e1a',
    'panel':   '#111827',
    'panel2':  '#0f1623',
    'green':   '#10b981',
    'red':     '#ef4444',
    'blue':    '#3b82f6',
    'orange':  '#f59e0b',
    'purple':  '#8b5cf6',
    'gray':    '#4b5563',
    'text':    '#f1f5f9',
    'text2':   '#94a3b8',
    'grid':    'rgba(255,255,255,0.04)',
    'spike':   'rgba(255,255,255,0.2)',
}

_FONT = dict(family="'JetBrains Mono', 'Fira Code', monospace", size=11, color=C['text2'])


def _base(height=480) -> dict:
    return dict(
        paper_bgcolor=C['bg'],
        plot_bgcolor=C['panel'],
        font=_FONT,
        height=height,
        margin=dict(l=60, r=16, t=32, b=36),
        xaxis=dict(
            showgrid=True, gridcolor=C['grid'], gridwidth=1,
            zeroline=False, showline=True, linecolor=C['gray'],
            tickfont=dict(size=10, color=C['text2']),
            showspikes=True, spikecolor=C['spike'], spikethickness=1, spikedash='dot',
        ),
        yaxis=dict(
            showgrid=True, gridcolor=C['grid'], gridwidth=1,
            zeroline=False, showline=True, linecolor=C['gray'],
            tickfont=dict(size=10, color=C['text2']),
            side='right',
        ),
        legend=dict(
            bgcolor='rgba(0,0,0,0)', font=dict(size=10, color=C['text2']),
            orientation='h', yanchor='bottom', y=1.01, xanchor='left', x=0,
        ),
        hovermode='x unified',
        hoverlabel=dict(
            bgcolor=C['panel'], font_size=11, font_family='monospace',
            bordercolor=C['gray'],
        ),
    )


def _apply_date_ticks(fig: go.Figure, df: pd.DataFrame, tf: str,
                      hide_labels_row: int | None = None) -> None:
    """
    Aplica ticks de fecha al eje X usando update_xaxes (funciona correctamente
    con make_subplots). Se llama DESPUÉS de update_layout.

    hide_labels_row: si se indica, oculta los tick labels de esa fila (1-indexed).
      price_chart  → hide_labels_row=2 (ocultar en panel volumen)
      momentum_chart→ hide_labels_row=1 (ocultar en panel superior)
    """
    tick0 = df['fecha'].iloc[0] if not df.empty else '2020-01-01'

    if tf == '3M':
        cfg = dict(
            type='date',
            tickmode='linear',
            tick0=tick0,
            dtick=7 * 24 * 60 * 60 * 1000,  # 7 días en ms → ~1 tick por semana
            tickformat='%d %b',              # "12 Mar"
            tickangle=0,
            showticklabels=True,
        )
    else:  # 1A
        cfg = dict(
            type='date',
            tickmode='linear',
            tick0=tick0,
            dtick='M1',                      # 1 mes exacto
            tickformat='%b %Y',              # "Mar 2025"
            tickangle=0,
            showticklabels=True,
        )

    fig.update_xaxes(**cfg)   # aplica a TODOS los ejes X de la figura

    if hide_labels_row is not None:
        fig.update_xaxes(showticklabels=False, row=hide_labels_row, col=1)


# ── Helpers de análisis dinámico ──────────────────────────────────────────────

def _count_touches(df: pd.DataFrame, level: float, tol: float = 0.005) -> int:
    """Velas donde high >= level*(1-tol) AND low <= level*(1+tol)."""
    return int(((df['high'] >= level * (1 - tol)) & (df['low'] <= level * (1 + tol))).sum())


def _score_to_fuerza(score: float) -> str:
    if score >= 5.0:  return 'muy alta'
    if score >= 3.5:  return 'alta'
    if score >= 2.0:  return 'media'
    return 'baja'


def get_dynamic_sr(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """
    Niveles dinámicos de S/R: MAs actuales + swing lows/highs recientes.

    Lógica:
      1. SMA200 / SMA50 / EMA20: si está por debajo del precio → soporte, si no → resistencia.
         Puntaje base: SMA200=3.5, SMA50=2.5, EMA20=1.5
      2. Swing lows (low[i] < low[i-1] y low[i] < low[i+1]) en los últimos 80 bars.
         Puntaje = 1 + recencia(0-1.5) + toques(0-1.5)
      3. Swing highs: análogo.
      4. Agrupación en zonas si niveles están dentro del 1% entre sí.
         La confluencia suma +0.8 por nivel adicional en la zona.

    Returns (sup_dynamic, res_dynamic) — lista de dicts:
      {'label': str, 'value': float, 'fuerza': str,
       'is_zone': bool, 'vmin': float, 'vmax': float}
    """
    if df.empty or len(df) < 10:
        return [], []

    df = df.copy()
    for col in ('high', 'low', 'close', 'sma200', 'sma50', 'ema20'):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    cur  = float(df['close'].iloc[-1])
    last = df.iloc[-1]
    raw_sup: list[dict] = []
    raw_res: list[dict] = []

    # 1. MAs como S/R dinámico ─────────────────────────────────────────────────
    for col, name, base_score in (('sma200','SMA200',3.5), ('sma50','SMA50',2.5), ('ema20','EMA20',1.5)):
        val = pd.to_numeric(last.get(col, None), errors='coerce')
        if pd.notna(val):
            item = {'label': name, 'value': float(val), 'score': base_score}
            (raw_sup if float(val) < cur else raw_res).append(item)

    # 2. Swing lows y highs (últimos 80 bars) ──────────────────────────────────
    lookback = min(len(df), 80)
    rec      = df.iloc[-lookback:].reset_index(drop=True)
    nr       = len(rec)

    for i in range(1, nr - 1):
        lo_p, lo_i, lo_n = rec['low'].iat[i-1], rec['low'].iat[i], rec['low'].iat[i+1]
        hi_p, hi_i, hi_n = rec['high'].iat[i-1], rec['high'].iat[i], rec['high'].iat[i+1]

        recency = i / nr   # 0 = más antiguo, 1 = más reciente → bonus 0..1.5

        if pd.notna(lo_i) and pd.notna(lo_p) and pd.notna(lo_n):
            if lo_i < lo_p and lo_i < lo_n and lo_i < cur:
                score = 1.0 + recency * 1.5 + min(_count_touches(df, lo_i) * 0.25, 1.5)
                raw_sup.append({'label': 'Swing low', 'value': float(lo_i), 'score': score})

        if pd.notna(hi_i) and pd.notna(hi_p) and pd.notna(hi_n):
            if hi_i > hi_p and hi_i > hi_n and hi_i > cur:
                score = 1.0 + recency * 1.5 + min(_count_touches(df, hi_i) * 0.25, 1.5)
                raw_res.append({'label': 'Swing high', 'value': float(hi_i), 'score': score})

    # 3. Agrupar y asignar fuerza ──────────────────────────────────────────────
    def _cluster(raw: list[dict], top_n: int = 4) -> list[dict]:
        if not raw:
            return []
        raw_s = sorted(raw, key=lambda x: x['value'])
        clusters: list[list[dict]] = []
        cur_cl = [raw_s[0]]
        for item in raw_s[1:]:
            if abs(item['value'] - cur_cl[0]['value']) / max(cur_cl[0]['value'], 1e-9) <= 0.01:
                cur_cl.append(item)
            else:
                clusters.append(cur_cl)
                cur_cl = [item]
        clusters.append(cur_cl)

        result = []
        for cl in clusters:
            combined = sum(c['score'] for c in cl) + (len(cl) - 1) * 0.8
            labels   = list(dict.fromkeys(c['label'] for c in cl))
            vals     = [c['value'] for c in cl]
            is_zone  = len(cl) > 1
            result.append({
                'label':   ' + '.join(labels[:2]) if is_zone else labels[0],
                'value':   (min(vals) + max(vals)) / 2,
                'vmin':    min(vals),
                'vmax':    max(vals),
                'fuerza':  _score_to_fuerza(combined),
                'is_zone': is_zone,
            })

        result.sort(key=lambda x: abs(x['value'] - cur))
        return result[:top_n]

    sup_dyn = sorted(_cluster(raw_sup), key=lambda x: x['value'], reverse=True)
    res_dyn = sorted(_cluster(raw_res), key=lambda x: x['value'])
    return sup_dyn, res_dyn


# ── S/R estático ───────────────────────────────────────────────────────────────

def get_support_resistance(df: pd.DataFrame, window: int = 15, n: int = 4) -> tuple[list, list]:
    """
    Detecta soportes y resistencias: mínimos/máximos locales agrupados.
    Retorna (supports, resistances) — listas de float ordenadas.
    Público: llamable desde app.py para mostrar valores como texto.
    """
    closes = df['close'].dropna().tolist()
    if len(closes) < window * 2 + 1:
        return [], []

    supports, resistances = [], []
    for i in range(window, len(closes) - window):
        sl = closes[i - window: i + window + 1]
        if closes[i] == min(sl):
            supports.append(closes[i])
        if closes[i] == max(sl):
            resistances.append(closes[i])

    def cluster(lvls):
        if not lvls:
            return []
        lvls = sorted(set(lvls))
        out  = [lvls[0]]
        for lv in lvls[1:]:
            if abs(lv - out[-1]) / max(out[-1], 1e-9) > 0.018:
                out.append(lv)
        return out

    cur = closes[-1]
    sup = sorted([s for s in cluster(supports)    if s < cur], reverse=True)[:n]
    res = sorted([r for r in cluster(resistances) if r > cur])[:n]
    return sup, res


def price_chart(df: pd.DataFrame, simbolo: str = '', tf: str = '3M',
                dyn_sup: list | None = None,
                dyn_res: list | None = None) -> go.Figure:
    """
    Candlestick + EMA20 + SMA50 + SMA200 + S/R estático + S/R dinámico + Volumen.
    dyn_sup / dyn_res: output de get_dynamic_sr() — se dibuja sin tocar el S/R estático.
    """
    sup, res = get_support_resistance(df) if len(df) > 40 else ([], [])

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.78, 0.22],
        vertical_spacing=0.02,
    )

    x0, x1 = df['fecha'].iloc[0], df['fecha'].iloc[-1]

    # ── S/R estático (puntos existentes — sin cambios) ────────────────────────
    for s in sup:
        fig.add_shape(type='line', x0=x0, x1=x1,
                      y0=s, y1=s, line=dict(color=C['green'], width=2, dash='dot'),
                      row=1, col=1)
    for r in res:
        fig.add_shape(type='line', x0=x0, x1=x1,
                      y0=r, y1=r, line=dict(color=C['red'], width=2, dash='dot'),
                      row=1, col=1)

    # ── S/R dinámico (líneas dash semitransparentes, zonas sombreadas) ────────
    _MA_LABELS = {'SMA200', 'SMA50', 'EMA20'}  # MAs ya aparecen como líneas de precio
    _DYN_S = 'rgba(16,185,129,0.6)'             # verde semitransparente
    _DYN_R = 'rgba(239,68,68,0.6)'              # rojo semitransparente

    for item in (dyn_sup or []):
        if item['label'] in _MA_LABELS:
            continue                             # ya visible como MA line
        lw = 1.2 if item['fuerza'] in ('alta', 'muy alta') else 0.7
        if item['is_zone']:
            fig.add_shape(type='rect', x0=x0, x1=x1,
                          y0=item['vmin'], y1=item['vmax'],
                          fillcolor='rgba(16,185,129,0.06)',
                          line=dict(color=_DYN_S, width=0.5),
                          row=1, col=1)
        else:
            fig.add_shape(type='line', x0=x0, x1=x1,
                          y0=item['value'], y1=item['value'],
                          line=dict(color=_DYN_S, width=lw, dash='dash'),
                          row=1, col=1)

    for item in (dyn_res or []):
        if item['label'] in _MA_LABELS:
            continue
        lw = 1.2 if item['fuerza'] in ('alta', 'muy alta') else 0.7
        if item['is_zone']:
            fig.add_shape(type='rect', x0=x0, x1=x1,
                          y0=item['vmin'], y1=item['vmax'],
                          fillcolor='rgba(239,68,68,0.06)',
                          line=dict(color=_DYN_R, width=0.5),
                          row=1, col=1)
        else:
            fig.add_shape(type='line', x0=x0, x1=x1,
                          y0=item['value'], y1=item['value'],
                          line=dict(color=_DYN_R, width=lw, dash='dash'),
                          row=1, col=1)

    # ── Candlestick ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df['fecha'],
        open=df['open'], high=df['high'],
        low=df['low'],  close=df['close'],
        name='', showlegend=False,
        increasing=dict(line=dict(color=C['green'], width=1),
                        fillcolor=C['green']),
        decreasing=dict(line=dict(color=C['red'],   width=1),
                        fillcolor=C['red']),
    ), row=1, col=1)

    # ── Moving averages ───────────────────────────────────────────────────────
    ma_cfg = [
        ('ema20',  C['purple'], 'EMA 20', 1.2),
        ('sma50',  C['blue'],   'SMA 50', 1.2),
        ('sma200', C['orange'], 'SMA 200', 1.4),
    ]
    for col, color, name, width in ma_cfg:
        series = pd.to_numeric(df.get(col, pd.Series()), errors='coerce')
        if series.notna().sum() >= 2:
            fig.add_trace(go.Scatter(
                x=df['fecha'], y=series, name=name,
                line=dict(color=color, width=width),
                opacity=0.85, hovertemplate=f'{name}: %{{y:.2f}}<extra></extra>',
            ), row=1, col=1)

    # ── Volumen ───────────────────────────────────────────────────────────────
    vol = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
    bar_colors = [C['green'] if float(c) >= float(o) else C['red']
                  for c, o in zip(df['close'], df['open'])]
    fig.add_trace(go.Bar(
        x=df['fecha'], y=vol, name='Vol',
        marker=dict(color=bar_colors, opacity=0.45),
        showlegend=False,
        hovertemplate='Vol: %{y:,.0f}<extra></extra>',
    ), row=2, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    layout = _base(height=520)
    layout['title'] = dict(
        text=f'<span style="font-size:14px;font-weight:700;color:{C["text"]}">{simbolo}</span>',
        x=0.01, xanchor='left',
    )
    layout['xaxis_rangeslider_visible'] = False
    layout['yaxis2'] = dict(
        showgrid=False, zeroline=False, showticklabels=False,
        side='right', showline=False,
    )
    layout['plot_bgcolor'] = C['panel2']

    fig.update_layout(**layout)

    # Aplicar ticks de fecha DESPUÉS de update_layout (garantía con subplots)
    # hide row 2 (volumen) para no duplicar las fechas
    _apply_date_ticks(fig, df, tf, hide_labels_row=2)

    return fig


def rsi_chart(df: pd.DataFrame, tf: str = '3M') -> go.Figure:
    rsi = pd.to_numeric(df['rsi14'], errors='coerce')

    fig = go.Figure()
    fig.add_hrect(y0=70, y1=100, fillcolor='rgba(239,68,68,0.06)',   line_width=0)
    fig.add_hrect(y0=0,  y1=30,  fillcolor='rgba(16,185,129,0.06)', line_width=0)

    for y, color, dash in [(70, C['red'], 'dash'), (30, C['green'], 'dash'), (50, C['gray'], 'dot')]:
        fig.add_hline(y=y, line_color=color, line_dash=dash,
                      line_width=0.8, opacity=0.6)

    fig.add_trace(go.Scatter(
        x=df['fecha'], y=rsi,
        name='RSI 14',
        line=dict(color=C['blue'], width=1.5),
        fill='tozeroy',
        fillcolor='rgba(59,130,246,0.06)',
        hovertemplate='RSI: %{y:.1f}<extra></extra>',
    ))

    layout = _base(height=180)
    layout['yaxis']['range'] = [0, 100]
    layout['yaxis']['side']  = 'right'
    layout['margin'] = dict(l=10, r=60, t=20, b=30)
    layout['showlegend'] = False
    fig.update_layout(**layout)
    _apply_date_ticks(fig, df, tf)
    return fig


def momentum_chart(df: pd.DataFrame, tf: str = '3M') -> go.Figure:
    mom = pd.to_numeric(df['mom_12_1'], errors='coerce') * 100
    rs  = pd.to_numeric(df['rs_sector'], errors='coerce')

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.5],
        vertical_spacing=0.06,
        subplot_titles=[
            f'<span style="color:{C["text2"]};font-size:10px">MOMENTUM 12-1 (%)</span>',
            f'<span style="color:{C["text2"]};font-size:10px">RS SECTOR</span>',
        ],
    )

    fig.add_hline(y=0, line_color=C['gray'], line_dash='solid',
                  line_width=0.8, opacity=0.5, row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=mom, name='Mom 12-1',
        line=dict(color=C['green'], width=1.4),
        fill='tozeroy',
        fillcolor='rgba(16,185,129,0.07)',
        hovertemplate='Mom 12-1: %{y:.1f}%<extra></extra>',
    ), row=1, col=1)

    fig.add_hline(y=0, line_color=C['gray'], line_dash='solid',
                  line_width=0.8, opacity=0.5, row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df['fecha'], y=rs, name='RS Sector',
        line=dict(color=C['orange'], width=1.4),
        fill='tozeroy',
        fillcolor='rgba(245,158,11,0.07)',
        hovertemplate='RS: %{y:.3f}<extra></extra>',
    ), row=2, col=1)

    layout = _base(height=300)
    layout['margin']     = dict(l=10, r=60, t=28, b=30)
    layout['showlegend'] = False
    layout['yaxis2'] = dict(
        showgrid=True, gridcolor=C['grid'], zeroline=False,
        side='right', tickfont=dict(size=10, color=C['text2']),
    )
    fig.update_layout(**layout)
    # hide row 1 (momentum), mostrar fechas solo en row 2 (RS sector, fila inferior)
    _apply_date_ticks(fig, df, tf, hide_labels_row=1)
    return fig
