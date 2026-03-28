"""
app.py — Dashboard trading-assist
Uso: streamlit run app.py
"""
import streamlit as st
import math
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import queries    as q
import charts     as ch
import components as cmp

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title='Trading Assist',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='collapsed',
)
st.markdown(cmp.GLOBAL_CSS, unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────

_DEFAULTS = {
    'page':               'home',
    'selected_accion_id': None,
    'selected_simbolo':   None,
    'tbl_page':           0,
    'tbl_market':         None,
    'tbl_market_label':   'Todos',
    'tbl_search':         '',
    # Controles del gráfico de detalle
    'chart_strategy':     '(Seleccionar)',
    'chart_tf_label':     'Diario',
}

# ── Definición de estrategias y sus indicadores asociados ─────────────────

_STRAT_OPTIONS = [
    '(Seleccionar)',
    'WMA21 / SMA30 — Tendencia media',
    'BUY_CONFIRMATION',
    'WMA6 / WMA30 — Swing',
    'BUY_EARLY_SWING — Anticipado',
]

# Flags de indicadores por estrategia
_STRAT_FLAGS: dict[str, dict] = {
    '(Seleccionar)': dict(
        sma50=False, sma200=False, ema20=False,
        dyn_sr=False, static_sr=False,
        wma=False, wma6=False, wma30=False,
        buy_conf=False, swing=False, early_swing=False,
    ),
    'WMA21 / SMA30 — Tendencia media': dict(
        sma50=False, sma200=False, ema20=False,
        dyn_sr=True,  static_sr=False,
        wma=True,  wma6=False, wma30=False,
        buy_conf=False, swing=False, early_swing=False,
    ),
    'BUY_CONFIRMATION': dict(
        sma50=True,  sma200=False, ema20=False,
        dyn_sr=True,  static_sr=True,
        wma=True,  wma6=False, wma30=False,
        buy_conf=True,  swing=False, early_swing=False,
    ),
    'WMA6 / WMA30 — Swing': dict(
        sma50=False, sma200=False, ema20=False,
        dyn_sr=False, static_sr=False,
        wma=False, wma6=True,  wma30=True,
        buy_conf=False, swing=True,  early_swing=False,
    ),
    'BUY_EARLY_SWING — Anticipado': dict(
        sma50=True,  sma200=True,  ema20=False,
        dyn_sr=True,  static_sr=True,
        wma=False, wma6=True,  wma30=True,
        buy_conf=False, swing=False, early_swing=True,
    ),
}

_TF_CHART = {'Diario': 'D', 'Semanal': 'W', 'Mensual': 'M'}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

PAGE_SIZE = 50

# ── Cache ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def cached_movers(segment, direction, n=5):
    return q.get_top_movers(segment, direction, n)

@st.cache_data(ttl=120)
def cached_table(market, search, page):
    # market=None  → "Todos": dedup USA > BYMA en SQL
    # market='USA' → solo mercados americanos
    # market='BYMA'→ solo BYMA/CEDEAR
    return q.get_asset_table(market, search or None, page, PAGE_SIZE)

@st.cache_data(ttl=120)
def cached_markets():
    return q.get_available_markets()

@st.cache_data(ttl=300)
def cached_prices(accion_id):
    # Siempre fetcheamos 400 días; el slicing al timeframe se hace en la UI
    return q.get_asset_prices(accion_id, 400)

@st.cache_data(ttl=300)
def cached_indicators(accion_id):
    return q.get_asset_indicators(accion_id, 365)

@st.cache_data(ttl=300)
def cached_info(accion_id):
    return q.get_accion_info(accion_id)


# ── HOME ──────────────────────────────────────────────────────────────────────

def page_home():

    # ── Nav bar ───────────────────────────────────────────────────────────────
    nav_l, nav_r = st.columns([5, 1])
    with nav_l:
        st.markdown(
            '<h2 style="margin:0;font-size:1.3rem;color:#f1f5f9;font-weight:700;'
            'letter-spacing:-0.01em">📊 Trading Assist</h2>',
            unsafe_allow_html=True,
        )
    with nav_r:
        st.markdown('<div class="refresh-btn">', unsafe_allow_html=True)
        if st.button('⟳ Refresh', use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<hr>', unsafe_allow_html=True)

    # ── 4 bloques top movers ──────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4, gap='medium')
    with c1:
        cmp.render_mover_block('Top 5 Alza — USA',  cached_movers('USA',  'up'),   is_up=True)
    with c2:
        cmp.render_mover_block('Top 5 Baja — USA',  cached_movers('USA',  'down'), is_up=False)
    with c3:
        cmp.render_mover_block('Top 5 Alza — BYMA', cached_movers('BYMA', 'up'),   is_up=True)
    with c4:
        cmp.render_mover_block('Top 5 Baja — BYMA', cached_movers('BYMA', 'down'), is_up=False)

    st.markdown('<br>', unsafe_allow_html=True)

    # ── Filtros ───────────────────────────────────────────────────────────────
    markets = cached_markets()
    search, market_filter, market_label = cmp.render_filter_bar(markets)

    # Detectar cambios y resetear página
    if search != st.session_state['tbl_search']:
        st.session_state['tbl_search']       = search
        st.session_state['tbl_page']         = 0
        st.rerun()
    if market_filter != st.session_state['tbl_market']:
        st.session_state['tbl_market']       = market_filter
        st.session_state['tbl_market_label'] = market_label
        st.session_state['tbl_page']         = 0
        st.rerun()

    # ── Tabla ─────────────────────────────────────────────────────────────────
    rows, total = cached_table(
        st.session_state['tbl_market'],
        st.session_state['tbl_search'],
        st.session_state['tbl_page'],
    )

    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    cur_page    = st.session_state['tbl_page']

    st.markdown(
        f'<div style="color:#334155;font-size:0.72rem;margin-bottom:6px">'
        f'{total:,} activos&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'Página {cur_page + 1} de {total_pages}&nbsp;&nbsp;·&nbsp;&nbsp;'
        f'Ordenado por mayor movimiento</div>',
        unsafe_allow_html=True,
    )

    cmp.render_asset_table(rows)

    # ── Paginación ────────────────────────────────────────────────────────────
    if total_pages > 1:
        pg = st.columns([1, 1, 6, 1, 1])
        with pg[0]:
            st.markdown('<div class="pg-btn">', unsafe_allow_html=True)
            if st.button('«', key='pg_first') and cur_page > 0:
                st.session_state['tbl_page'] = 0; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        with pg[1]:
            st.markdown('<div class="pg-btn">', unsafe_allow_html=True)
            if st.button('‹', key='pg_prev') and cur_page > 0:
                st.session_state['tbl_page'] = cur_page - 1; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        with pg[3]:
            st.markdown('<div class="pg-btn">', unsafe_allow_html=True)
            if st.button('›', key='pg_next') and cur_page < total_pages - 1:
                st.session_state['tbl_page'] = cur_page + 1; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        with pg[4]:
            st.markdown('<div class="pg-btn">', unsafe_allow_html=True)
            if st.button('»', key='pg_last') and cur_page < total_pages - 1:
                st.session_state['tbl_page'] = total_pages - 1; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)


# ── DETAIL helpers ────────────────────────────────────────────────────────────

# Días calendario por timeframe
TF_OPTIONS = {'3M': 90, '1A': 365}

def _asset_status(prices_df, indic_df) -> dict:
    """Calcula estado del activo: tendencia, SMA200, RSI, momentum."""
    status = {'sobre_sma200': None, 'tendencia': 'N/D',
              'rsi': None, 'mom': None, 'rs': None}
    if prices_df.empty:
        return status

    last   = prices_df.iloc[-1]
    close  = cmp._f(last.get('close'))
    sma200 = cmp._f(last.get('sma200'))
    sma50  = cmp._f(last.get('sma50'))

    if close and sma200:
        status['sobre_sma200'] = close > sma200
        if sma50:
            if close > sma200 and sma50 > sma200:
                status['tendencia'] = 'Alcista'
            elif close < sma200 and sma50 < sma200:
                status['tendencia'] = 'Bajista'
            else:
                status['tendencia'] = 'Lateral'

    if not indic_df.empty:
        if indic_df['rsi14'].notna().any():
            status['rsi'] = float(indic_df['rsi14'].dropna().iloc[-1])
        last_i = indic_df.dropna(subset=['mom_12_1'], how='all')
        if not last_i.empty:
            status['mom'] = cmp._f(last_i['mom_12_1'].iloc[-1])
        last_rs = indic_df.dropna(subset=['rs_sector'], how='all')
        if not last_rs.empty:
            status['rs'] = cmp._f(last_rs['rs_sector'].iloc[-1])

    return status


def _render_status_block(status: dict) -> None:
    """Bloque de estado del activo (sobre SMA200, tendencia, RSI, momentum)."""
    tend = status['tendencia']
    tend_color = {'Alcista': '#10b981', 'Bajista': '#ef4444',
                  'Lateral': '#f59e0b'}.get(tend, '#64748b')

    sma_val  = status['sobre_sma200']
    sma_txt  = 'Sí' if sma_val is True else ('No' if sma_val is False else 'N/D')
    sma_col  = '#10b981' if sma_val else ('#ef4444' if sma_val is False else '#64748b')

    rsi      = status['rsi']
    rsi_txt  = f'{rsi:.1f}' if rsi is not None else 'N/D'
    rsi_col  = '#10b981' if (rsi and rsi < 30) else ('#ef4444' if (rsi and rsi > 70) else '#94a3b8')

    mom      = status['mom']
    mom_txt  = f'{mom*100:+.1f}%' if mom is not None else 'N/D'
    mom_col  = '#10b981' if (mom and mom > 0) else ('#ef4444' if (mom and mom < 0) else '#94a3b8')

    rs       = status['rs']
    rs_txt   = f'{rs:.3f}' if rs is not None else 'N/D'
    rs_col   = '#10b981' if (rs and rs > 0) else ('#ef4444' if (rs and rs < 0) else '#94a3b8')

    cols = st.columns(5)
    items = [
        ('Sobre SMA 200', sma_txt, sma_col),
        ('Tendencia',     tend,    tend_color),
        ('RSI 14',        rsi_txt, rsi_col),
        ('Momentum 12-1', mom_txt, mom_col),
        ('RS Sector',     rs_txt,  rs_col),
    ]
    for col, (label, val, color) in zip(cols, items):
        col.markdown(
            f'<div style="background:#111827;border:1px solid #1e293b;border-radius:8px;'
            f'padding:10px 14px;text-align:center">'
            f'<div style="color:#475569;font-size:0.68rem;text-transform:uppercase;'
            f'letter-spacing:0.07em;margin-bottom:4px">{label}</div>'
            f'<div style="color:{color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{val}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_wma_signal_block(wma_data: dict) -> None:
    """Panel compacto con estado y último cruce WMA21/SMA30."""
    estado = wma_data.get('estado', 'N/D')
    uc     = wma_data.get('ultimo_cruce')

    est_color = {'Alcista': '#10b981', 'Bajista': '#ef4444'}.get(estado, '#64748b')

    if uc:
        uc_color = {'Alcista': '#10b981', 'Bajista': '#ef4444'}.get(uc['tipo'], '#94a3b8')
        uc_tipo  = uc['tipo']
        uc_fecha = uc['fecha']
    else:
        uc_color = '#64748b'
        uc_tipo  = '—'
        uc_fecha = ''

    c1, c2 = st.columns(2)

    def _card(label, val_html):
        return (
            f'<div style="background:#111827;border:1px solid #1e293b;border-radius:8px;'
            f'padding:10px 14px">'
            f'<div style="color:#475569;font-size:0.68rem;text-transform:uppercase;'
            f'letter-spacing:0.07em;margin-bottom:4px">{label}</div>'
            f'{val_html}'
            f'</div>'
        )

    with c1:
        st.markdown(_card(
            'Señal WMA21 / SMA30',
            f'<div style="color:{est_color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{estado}</div>',
        ), unsafe_allow_html=True)

    with c2:
        fecha_span = (f'&nbsp;<span style="color:#64748b;font-size:0.8rem;'
                      f'font-weight:400">{uc_fecha}</span>') if uc_fecha else ''
        st.markdown(_card(
            'Último cruce WMA/SMA',
            f'<div style="color:{uc_color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{uc_tipo}{fecha_span}</div>',
        ), unsafe_allow_html=True)


def _render_buy_confirmation_block(conf_data: dict) -> None:
    """Panel compacto para la señal BUY_CONFIRMATION."""
    activo = conf_data.get('activo', False)
    fuerza = conf_data.get('fuerza')
    motivo = conf_data.get('motivo', [])
    fecha  = conf_data.get('fecha')
    cerca  = conf_data.get('cerca_soporte', False)

    est_label = 'ACTIVO'  if activo else 'inactivo'
    est_color = '#10b981' if activo else '#475569'
    fuerza_color = {'FUERTE': '#fbbf24', 'MEDIA': '#fb923c'}.get(fuerza or '', '#64748b')
    fuerza_label = fuerza or '—'
    motivo_txt   = ' · '.join(motivo) if motivo else '—'
    fecha_span   = (f' <span style="color:#64748b;font-size:0.75rem">{fecha}</span>'
                    if fecha else '')

    def _card(label, val_html):
        return (
            f'<div style="background:#111827;border:1px solid #1e293b;border-radius:8px;'
            f'padding:10px 14px">'
            f'<div style="color:#475569;font-size:0.68rem;text-transform:uppercase;'
            f'letter-spacing:0.07em;margin-bottom:4px">{label}</div>'
            f'{val_html}'
            f'</div>'
        )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_card(
            'BUY_CONFIRMATION',
            f'<div style="color:{est_color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{est_label}{fecha_span}</div>'
            f'<div style="color:#64748b;font-size:0.72rem;margin-top:3px">{motivo_txt}</div>',
        ), unsafe_allow_html=True)
    with c2:
        st.markdown(_card(
            'Fuerza',
            f'<div style="color:{fuerza_color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{fuerza_label}</div>'
            f'<div style="color:#64748b;font-size:0.72rem;margin-top:3px">'
            f'Cerca soporte: {"sí 📍" if cerca else "no"}</div>',
        ), unsafe_allow_html=True)


def _render_swing_block(swing_data: dict, early_swing_data: dict | None = None) -> None:
    """Semaforo de corto plazo (WMA6/WMA30): estado + ultimo cruce + estrategias anticipadas."""
    estado = swing_data.get('estado', 'N/D')
    uc     = swing_data.get('ultimo_cruce')

    _map = {
        'Compra':  ('#10b981', '●', 'COMPRA'),
        'Venta':   ('#ef4444', '●', 'VENTA'),
        'Neutral': ('#f59e0b', '●', 'NEUTRAL'),
    }
    color, dot, label = _map.get(estado, ('#64748b', '○', estado or 'N/D'))

    if uc:
        uc_color = '#10b981' if uc['tipo'] == 'BUY_SWING' else '#ef4444'
        uc_tipo  = 'Compra' if uc['tipo'] == 'BUY_SWING' else 'Venta'
        uc_fecha = uc['fecha']
    else:
        uc_color, uc_tipo, uc_fecha = '#64748b', '—', ''

    def _card(lbl, val_html):
        return (
            f'<div style="background:#0f1623;border:1px solid #1e293b;border-radius:8px;'
            f'padding:10px 14px">'
            f'<div style="color:#475569;font-size:0.65rem;text-transform:uppercase;'
            f'letter-spacing:0.07em;margin-bottom:4px">{lbl}</div>'
            f'{val_html}</div>'
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(_card(
            'Corto plazo (WMA6/WMA30)',
            f'<div style="display:flex;align-items:center;gap:8px">'
            f'<span style="color:{color};font-size:1.3rem;line-height:1">{dot}</span>'
            f'<span style="color:{color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{label}</span></div>',
        ), unsafe_allow_html=True)
    with c2:
        st.markdown(_card(
            'Estado WMA6 / WMA30',
            f'<div style="color:{color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{estado}</div>',
        ), unsafe_allow_html=True)
    with c3:
        fecha_span = (f'&nbsp;<span style="color:#64748b;font-size:0.78rem">'
                      f'{uc_fecha}</span>') if uc_fecha else ''
        st.markdown(_card(
            'Último cruce WMA6/WMA30',
            f'<div style="color:{uc_color};font-size:1rem;font-weight:700;'
            f'font-family:monospace">{uc_tipo}{fecha_span}</div>',
        ), unsafe_allow_html=True)

    # ── Bloque de estrategias anticipadas ────────────────────────────────────
    if early_swing_data:
        st.markdown(
            '<div style="color:#475569;font-size:0.65rem;font-weight:700;'
            'text-transform:uppercase;letter-spacing:0.08em;margin:10px 0 6px">'
            'Estrategias anticipadas (BUY_EARLY_SWING / SELL_SWING_CROSS)</div>',
            unsafe_allow_html=True,
        )

        es_estado   = early_swing_data.get('estado', 'NEUTRAL')
        es_senal    = early_swing_data.get('senal_activa')
        es_fuerza   = early_swing_data.get('fuerza')
        es_vol      = early_swing_data.get('volumen_comprador', False)
        es_res      = early_swing_data.get('resistencia_cercana', False)
        es_tend     = early_swing_data.get('tendencia_alcista', False)
        es_fecha    = early_swing_data.get('fecha_senal')

        _sem_map = {
            'COMPRA_FUERTE': ('#10b981', '●', 'COMPRA FUERTE'),
            'COMPRA':        ('#22c55e', '○', 'COMPRA'),
            'VENTA':         ('#ef4444', '●', 'VENTA'),
            'NEUTRAL':       ('#f59e0b', '●', 'NEUTRAL'),
        }
        sem_c, sem_dot, sem_lbl = _sem_map.get(es_estado, ('#64748b', '○', 'NEUTRAL'))

        e1, e2, e3, e4 = st.columns(4)

        with e1:
            fecha_es = (f'<div style="color:#64748b;font-size:0.72rem;margin-top:2px">'
                        f'{es_fecha}</div>') if es_fecha else ''
            st.markdown(_card(
                'Semáforo anticipado',
                f'<div style="display:flex;align-items:center;gap:7px">'
                f'<span style="color:{sem_c};font-size:1.2rem;line-height:1">{sem_dot}</span>'
                f'<span style="color:{sem_c};font-size:0.95rem;font-weight:700;'
                f'font-family:monospace">{sem_lbl}</span></div>'
                f'{fecha_es}',
            ), unsafe_allow_html=True)

        with e2:
            s_color = ('#22c55e' if es_senal and 'BUY' in es_senal
                       else ('#ef4444' if es_senal == 'SELL_SWING_CROSS' else '#64748b'))
            f_color = {'FUERTE': '#fbbf24', 'MEDIA': '#fb923c'}.get(es_fuerza or '', '#64748b')
            st.markdown(_card(
                'Señal activa',
                f'<div style="color:{s_color};font-size:0.82rem;font-weight:700;'
                f'font-family:monospace;word-break:break-all">{es_senal or "—"}</div>'
                f'<div style="color:{f_color};font-size:0.78rem;margin-top:2px">'
                f'Fuerza: {es_fuerza or "—"}</div>',
            ), unsafe_allow_html=True)

        with e3:
            vc = '#10b981' if es_vol else '#64748b'
            rc = '#ef4444' if es_res else '#10b981'
            st.markdown(_card(
                'Condiciones',
                f'<div style="font-size:0.82rem;line-height:1.6">'
                f'<span style="color:#94a3b8">Vol. comprador: </span>'
                f'<span style="color:{vc};font-weight:700">{"sí" if es_vol else "no"}</span>'
                f'<br>'
                f'<span style="color:#94a3b8">Res. cercana: </span>'
                f'<span style="color:{rc};font-weight:700">{"sí" if es_res else "no"}</span>'
                f'</div>',
            ), unsafe_allow_html=True)

        with e4:
            tc = '#10b981' if es_tend else '#ef4444'
            st.markdown(_card(
                'Tendencia fondo',
                f'<div style="color:{tc};font-size:0.95rem;font-weight:700;'
                f'font-family:monospace">{"alcista" if es_tend else "no alcista"}</div>'
                f'<div style="color:#64748b;font-size:0.70rem;margin-top:2px">'
                f'precio &gt; SMA200 o SMA50 &gt; SMA200</div>',
            ), unsafe_allow_html=True)


def _render_chart_legend(
    show_wma: bool = False,
    show_wma6: bool = False,
    show_wma30: bool = False,
    show_sma50: bool = False,
    show_sma200: bool = False,
    show_ema20: bool = False,
    show_buy_conf: bool = False,
    show_dyn_sr: bool = False,
    show_static_sr: bool = False,
) -> None:
    """Fila compacta que identifica las líneas activas del gráfico."""
    sr_items = []
    if show_static_sr:
        sr_items += [
            ('dotted', '#10b981', 'Soporte estático'),
            ('dotted', '#ef4444', 'Resistencia estática'),
        ]
    if show_dyn_sr:
        sr_items += [
            ('dashed', 'rgba(16,185,129,0.8)', 'Soporte dinámico'),
            ('dashed', 'rgba(239,68,68,0.8)',  'Resistencia dinámica'),
        ]

    ma_items = []
    if show_wma:
        ma_items += [
            ('solid', '#06b6d4', 'WMA 21'),
            ('solid', '#a3e635', 'SMA 30'),
            ('tri-up',   '#10b981', 'Cruce alcista'),
            ('tri-down', '#ef4444', 'Cruce bajista'),
        ]
    if show_ema20:
        ma_items.append(('solid', '#8b5cf6', 'EMA 20'))
    if show_sma50:
        ma_items.append(('solid', '#3b82f6', 'SMA 50'))
    if show_sma200:
        ma_items.append(('solid', '#f59e0b', 'SMA 200'))
    if show_buy_conf:
        ma_items += [
            ('star', '#fbbf24', 'BUY_CONF fuerte'),
            ('star', '#fb923c', 'BUY_CONF media'),
        ]

    swing_items = []
    if show_wma6:
        swing_items.append(('thin', '#f97316', 'WMA 6'))
    if show_wma30:
        swing_items.append(('thin', '#60a5fa', 'WMA 30'))
    if show_wma6 and show_wma30:
        swing_items += [
            ('tri-up',      '#10b981', 'BUY_SWING'),
            ('tri-down',    '#ef4444', 'SELL_SWING'),
            ('circle-open', '#22c55e', 'BUY_EARLY_SWING'),
            ('circle',      '#4ade80', 'BUY_EARLY_STRONG'),
            ('x-marker',    '#ef4444', 'SELL_SWING_CROSS'),
        ]

    items = sr_items + ma_items + swing_items
    if not items:
        return   # gráfico limpio — sin leyenda

    # Renderiza cada ítem como una pequeña línea SVG + label
    # stroke-linecap="round" + dasharray="0,N" → puntos circulares (= Plotly dash='dot')
    # stroke-dasharray="7,4"                   → rayas    (= Plotly dash='dash')
    def _item_html(style, color, label):
        if style == 'dotted':
            line = (f'<svg width="30" height="10" style="vertical-align:middle">'
                    f'<line x1="2" y1="5" x2="28" y2="5" stroke="{color}" '
                    f'stroke-width="2.5" stroke-linecap="round" '
                    f'stroke-dasharray="0,6"/></svg>')
        elif style == 'dashed':
            line = (f'<svg width="30" height="10" style="vertical-align:middle">'
                    f'<line x1="0" y1="5" x2="30" y2="5" stroke="{color}" '
                    f'stroke-width="1.5" stroke-dasharray="7,4"/></svg>')
        elif style == 'tri-up':
            line = (f'<svg width="14" height="14" style="vertical-align:middle">'
                    f'<polygon points="7,1 13,13 1,13" fill="{color}"/></svg>')
        elif style == 'tri-down':
            line = (f'<svg width="14" height="14" style="vertical-align:middle">'
                    f'<polygon points="7,13 13,1 1,1" fill="{color}"/></svg>')
        elif style == 'star':
            line = (f'<span style="color:{color};font-size:13px;'
                    f'vertical-align:middle">★</span>')
        elif style == 'thin':
            line = (f'<svg width="30" height="10" style="vertical-align:middle">'
                    f'<line x1="0" y1="5" x2="30" y2="5" stroke="{color}" '
                    f'stroke-width="1.2" opacity="0.65"/></svg>')
        elif style == 'circle-open':
            line = (f'<svg width="14" height="14" style="vertical-align:middle">'
                    f'<circle cx="7" cy="7" r="5" fill="none" stroke="{color}" '
                    f'stroke-width="2"/></svg>')
        elif style == 'circle':
            line = (f'<svg width="14" height="14" style="vertical-align:middle">'
                    f'<circle cx="7" cy="7" r="5" fill="{color}"/></svg>')
        elif style == 'x-marker':
            line = (f'<svg width="14" height="14" style="vertical-align:middle">'
                    f'<line x1="2" y1="2" x2="12" y2="12" stroke="{color}" '
                    f'stroke-width="2.5" stroke-linecap="round"/>'
                    f'<line x1="12" y1="2" x2="2" y2="12" stroke="{color}" '
                    f'stroke-width="2.5" stroke-linecap="round"/></svg>')
        else:  # solid
            line = (f'<svg width="30" height="10" style="vertical-align:middle">'
                    f'<line x1="0" y1="5" x2="30" y2="5" stroke="{color}" '
                    f'stroke-width="2"/></svg>')
        return (f'{line}&nbsp;'
                f'<span style="color:#64748b;font-size:0.72rem">{label}</span>')

    html = (
        '<div style="display:flex;flex-wrap:wrap;gap:14px;'
        'padding:6px 0 10px;align-items:center">'
        + ''.join(_item_html(s, c, l) for s, c, l in items)
        + '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


_FUERZA_COLOR = {
    'muy alta': '#10b981',
    'alta':     '#34d399',
    'media':    '#f59e0b',
    'baja':     '#64748b',
}


def _find_sr_overlaps(static_vals: list, dyn_items: list, tol: float = 0.012) -> list[str]:
    """
    Detecta solapamientos entre niveles estáticos y dinámicos.
    Retorna lista de strings descriptivos para mostrar al usuario.
    tol=1.2%: mismo umbral que la agrupación interna de get_dynamic_sr.
    """
    msgs = []
    for sv in static_vals:
        for d in dyn_items:
            if abs(sv - d['value']) / max(abs(sv), 1e-9) <= tol:
                msgs.append(
                    f'${sv:,.2f} (estático) ≈ {d["label"]} ${d["value"]:,.2f} (dinámico)'
                )
    return msgs


def _render_sr_values(sup: list, res: list,
                      dyn_sup: list | None = None,
                      dyn_res: list | None = None) -> None:
    """Soportes y resistencias — estáticos + dinámicos, en dos columnas."""

    # ── Aviso de solapamiento ──────────────────────────────────────────────────
    overlaps_sup = _find_sr_overlaps(sup, dyn_sup or [])
    overlaps_res = _find_sr_overlaps(res, dyn_res or [])
    all_overlaps  = overlaps_sup + overlaps_res
    if all_overlaps:
        lines = ''.join(f'<li style="margin:2px 0">{o}</li>' for o in all_overlaps)
        st.markdown(
            f'<div style="background:#1c1a0a;border:1px solid #854d0e;border-radius:7px;'
            f'padding:8px 12px;margin-bottom:10px">'
            f'<span style="color:#fbbf24;font-size:0.72rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.07em">⚠ Niveles superpuestos</span>'
            f'<ul style="color:#fcd34d;font-family:monospace;font-size:0.78rem;'
            f'margin:4px 0 0 0;padding-left:16px">{lines}</ul>'
            f'<span style="color:#78716c;font-size:0.68rem">'
            f'Estos niveles coinciden en el gráfico — pueden verse como una sola línea.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    def _section_header(label: str, color: str) -> None:
        st.markdown(
            f'<span style="color:{color};font-size:0.68rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.09em">{label}</span>',
            unsafe_allow_html=True,
        )

    def _static_row(value: float) -> None:
        st.markdown(
            f'<span style="color:#cbd5e1;font-family:monospace;font-size:0.88rem">'
            f'${value:,.2f}</span>',
            unsafe_allow_html=True,
        )

    def _dyn_row(item: dict) -> None:
        fc   = _FUERZA_COLOR.get(item['fuerza'], '#64748b')
        val  = item['value']
        lbl  = item['label']
        if item['is_zone']:
            rng = f' ({item["vmin"]:,.0f}–{item["vmax"]:,.0f})'
        else:
            rng = ''
        st.markdown(
            f'<span style="color:#94a3b8;font-size:0.78rem">{lbl}: </span>'
            f'<span style="color:#e2e8f0;font-family:monospace;font-size:0.88rem">'
            f'${val:,.2f}{rng}</span> '
            f'<span style="color:{fc};font-size:0.72rem;font-weight:600">'
            f'({item["fuerza"]})</span>',
            unsafe_allow_html=True,
        )

    s_col, r_col = st.columns(2)

    with s_col:
        # Estáticos
        _section_header('Soportes estáticos', '#10b981')
        if sup:
            for s in sup: _static_row(s)
        else:
            st.markdown('<span style="color:#475569;font-size:0.8rem">N/D</span>',
                        unsafe_allow_html=True)
        # Dinámicos
        if dyn_sup:
            st.markdown('<br>', unsafe_allow_html=True)
            _section_header('Soportes dinámicos', '#34d399')
            for item in dyn_sup:
                _dyn_row(item)

    with r_col:
        # Estáticos
        _section_header('Resistencias estáticas', '#ef4444')
        if res:
            for r in res: _static_row(r)
        else:
            st.markdown('<span style="color:#475569;font-size:0.8rem">N/D</span>',
                        unsafe_allow_html=True)
        # Dinámicos
        if dyn_res:
            st.markdown('<br>', unsafe_allow_html=True)
            _section_header('Resistencias dinámicas', '#f87171')
            for item in dyn_res:
                _dyn_row(item)


# ── PDF export ────────────────────────────────────────────────────────────────

def _build_pdf(simbolo, mercado, tf, prices_df_full, prices_slice,
               sup, res, status,
               dyn_sup=None, dyn_res=None, wma_data=None) -> bytes:
    """Genera un PDF con ticker, fecha, dos gráficos (clásico + WMA), S/R y estado del activo."""
    import io
    from datetime import datetime
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, Image as RLImage)

    W, H = A4
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=2*cm, rightMargin=2*cm,
                              topMargin=2*cm,  bottomMargin=2*cm)

    # Paleta
    C_BG   = HexColor('#0a0e1a')
    C_CARD = HexColor('#111827')
    C_BLUE = HexColor('#3b82f6')
    C_TEXT = HexColor('#f1f5f9')
    C_MUTED= HexColor('#64748b')
    C_GRN  = HexColor('#10b981')
    C_RED  = HexColor('#ef4444')
    C_AMB  = HexColor('#f59e0b')

    # Estilos
    s_title = ParagraphStyle('title', fontName='Helvetica-Bold',
                              fontSize=20, textColor=C_TEXT, spaceAfter=4)
    s_sub   = ParagraphStyle('sub',   fontName='Helvetica',
                              fontSize=10, textColor=C_MUTED, spaceAfter=12)
    s_head2 = ParagraphStyle('h2',    fontName='Helvetica-Bold',
                              fontSize=12, textColor=C_BLUE, spaceBefore=14, spaceAfter=6)
    s_norm  = ParagraphStyle('norm',  fontName='Helvetica',
                              fontSize=9,  textColor=C_TEXT)

    story = []

    # ── Cabecera ──────────────────────────────────────────────────────────────
    fecha_gen  = datetime.now().strftime('%Y-%m-%d %H:%M')
    fecha_dato = prices_slice['fecha'].iloc[-1] if not prices_slice.empty else '—'
    story.append(Paragraph(simbolo, s_title))
    story.append(Paragraph(
        f'{mercado} &nbsp;·&nbsp; Temporalidad: {tf} &nbsp;·&nbsp; '
        f'Datos al {fecha_dato} &nbsp;·&nbsp; Generado {fecha_gen}', s_sub))

    # ── Estado del activo ─────────────────────────────────────────────────────
    story.append(Paragraph('Estado del activo', s_head2))

    tend      = status.get('tendencia', 'N/D')
    tend_col  = C_GRN if tend == 'Alcista' else (C_RED if tend == 'Bajista' else C_AMB)
    sma_val   = status.get('sobre_sma200')
    sma_txt   = 'Sí' if sma_val is True else ('No' if sma_val is False else 'N/D')
    sma_col   = C_GRN if sma_val is True else (C_RED if sma_val is False else C_MUTED)
    rsi       = status.get('rsi')
    rsi_txt   = f"{rsi:.1f}" if rsi is not None else 'N/D'
    rsi_col   = C_GRN if (rsi and rsi < 30) else (C_RED if (rsi and rsi > 70) else C_TEXT)
    mom       = status.get('mom')
    mom_txt   = f"{mom*100:+.1f}%" if mom is not None else 'N/D'
    mom_col   = C_GRN if (mom and mom > 0) else (C_RED if (mom and mom < 0) else C_TEXT)

    def _p(txt, color=C_TEXT, bold=False):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        return Paragraph(f'<font name="{fn}" color="{color.hexval()}">{txt}</font>',
                         ParagraphStyle('c', fontSize=9))

    # WMA21/SMA30
    wma_sig = (wma_data or {}).get('estado', 'N/D')
    wma_uc  = (wma_data or {}).get('ultimo_cruce')
    wma_col = C_GRN if wma_sig == 'Alcista' else (C_RED if wma_sig == 'Bajista' else C_MUTED)
    uc_txt  = f'{wma_uc["tipo"]}  {wma_uc["fecha"]}' if wma_uc else 'N/D'
    uc_col  = C_GRN if (wma_uc and wma_uc['tipo'] == 'Alcista') else (C_RED if wma_uc else C_MUTED)

    # BUY_CONFIRMATION para PDF
    import charts as _ch_pdf
    _bc_pdf  = _ch_pdf.get_buy_confirmation(prices_slice,
                                            list(sup or []),
                                            list(dyn_sup or []))
    bc_act   = _bc_pdf.get('activo', False)
    bc_fuerza= _bc_pdf.get('fuerza') or '—'
    bc_motivo= ' · '.join(_bc_pdf.get('motivo', [])) or '—'
    bc_act_txt = f'ACTIVO  {_bc_pdf["fecha"]}' if bc_act and _bc_pdf.get('fecha') else ('inactivo' if not bc_act else 'ACTIVO')
    bc_act_col = C_GRN if bc_act else C_MUTED
    bc_f_col   = HexColor('#fbbf24') if bc_fuerza == 'FUERTE' else (HexColor('#fb923c') if bc_fuerza == 'MEDIA' else C_MUTED)

    status_data = [
        [_p('Indicador', bold=True), _p('Valor', bold=True)],
        [_p('Tendencia'),            _p(tend,    tend_col, True)],
        [_p('Sobre SMA 200'),        _p(sma_txt, sma_col,  True)],
        [_p('RSI 14'),               _p(rsi_txt, rsi_col,  True)],
        [_p('Momentum 12-1'),        _p(mom_txt, mom_col,  True)],
        [_p('Señal WMA21/SMA30'),    _p(wma_sig, wma_col,  True)],
        [_p('Último cruce WMA/SMA'), _p(uc_txt,  uc_col,   True)],
        [_p('BUY_CONFIRMATION'),     _p(bc_act_txt, bc_act_col, True)],
        [_p('Fuerza BUY_CONF'),      _p(bc_fuerza,  bc_f_col,   True)],
        [_p('Motivo BUY_CONF'),      _p(bc_motivo,  C_TEXT)],
    ]
    tbl = Table(status_data, colWidths=[7*cm, 7*cm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), C_CARD),
        ('BACKGROUND', (0, 1), (-1, -1), C_CARD),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [C_CARD, HexColor('#0f1623')]),
        ('GRID',        (0, 0), (-1, -1), 0.3, HexColor('#1e293b')),
        ('TOPPADDING',  (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',(0,0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(tbl)

    # ── Gráfico 1: clásico (EMA20 / SMA50 / SMA200) + BUY_CONF markers ───────
    story.append(Paragraph('Gráfico de precio — EMA20 / SMA50 / SMA200', s_head2))
    try:
        fig1 = _ch_pdf.price_chart(prices_slice, simbolo, tf,
                                   dyn_sup or [], dyn_res or [],
                                   wma_data=None, buy_conf_data=_bc_pdf)
        img1 = fig1.to_image(format='png', width=900, height=480, scale=1.5)
        story.append(RLImage(io.BytesIO(img1),
                             width=W - 4*cm, height=(W - 4*cm) * 480/900))
    except Exception as e:
        story.append(Paragraph(f'(Gráfico clásico no disponible: {e})', s_norm))

    # ── Gráfico 2: WMA21 / SMA30 + BUY_CONF markers ──────────────────────────
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph('Gráfico de precio — WMA21 / SMA30', s_head2))
    try:
        _wma_pdf = _ch_pdf.get_wma_sma_signal(prices_slice) if not prices_slice.empty else None
        fig2 = _ch_pdf.price_chart(prices_slice, simbolo, tf,
                                   dyn_sup or [], dyn_res or [],
                                   wma_data=_wma_pdf, buy_conf_data=_bc_pdf)
        img2 = fig2.to_image(format='png', width=900, height=480, scale=1.5)
        story.append(RLImage(io.BytesIO(img2),
                             width=W - 4*cm, height=(W - 4*cm) * 480/900))
    except Exception as e:
        story.append(Paragraph(f'(Gráfico WMA no disponible: {e})', s_norm))

    # ── Gráfico 3: Corto plazo (WMA6 / WMA30) ────────────────────────────────
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph('Gráfico de corto plazo — WMA6 / WMA30', s_head2))
    try:
        _swing_pdf = _ch_pdf.get_swing_signal(prices_slice) if not prices_slice.empty else None
        fig3 = _ch_pdf.price_chart(prices_slice, simbolo, tf,
                                   dyn_sup or [], dyn_res or [],
                                   wma_data=None, buy_conf_data=_bc_pdf,
                                   swing_data=_swing_pdf)
        img3 = fig3.to_image(format='png', width=900, height=480, scale=1.5)
        story.append(RLImage(io.BytesIO(img3),
                             width=W - 4*cm, height=(W - 4*cm) * 480/900))
    except Exception as e:
        story.append(Paragraph(f'(Gráfico corto plazo no disponible: {e})', s_norm))

    # ── Soportes y Resistencias ───────────────────────────────────────────────
    if sup or res:
        story.append(Paragraph('Soportes y Resistencias', s_head2))
        sr_data = [[_p('Soportes', bold=True), _p('Resistencias', bold=True)]]
        max_rows = max(len(sup), len(res))
        for i in range(max_rows):
            sv = _p(f'${sup[i]:,.2f}', C_GRN) if i < len(sup) else _p('—', C_MUTED)
            rv = _p(f'${res[i]:,.2f}', C_RED) if i < len(res) else _p('—', C_MUTED)
            sr_data.append([sv, rv])
        sr_tbl = Table(sr_data, colWidths=[7*cm, 7*cm])
        sr_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), C_CARD),
            ('BACKGROUND', (0, 1), (-1, -1), C_CARD),
            ('GRID',       (0, 0), (-1, -1), 0.3, HexColor('#1e293b')),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING',(0,0),(-1,-1),  5),
            ('LEFTPADDING',(0, 0), (-1, -1), 8),
        ]))
        story.append(sr_tbl)

    # ── Aviso de solapamiento ─────────────────────────────────────────────────
    all_overlaps = (
        _find_sr_overlaps(sup, dyn_sup or []) +
        _find_sr_overlaps(res, dyn_res or [])
    )
    if all_overlaps:
        C_WARN_BG  = HexColor('#1c1a0a')
        C_WARN_BRD = HexColor('#854d0e')
        C_WARN_TXT = HexColor('#fbbf24')
        C_WARN_LI  = HexColor('#fcd34d')
        s_warn_hdr = ParagraphStyle('wh', fontName='Helvetica-Bold',
                                    fontSize=9, textColor=C_WARN_TXT)
        s_warn_li  = ParagraphStyle('wl', fontName='Helvetica',
                                    fontSize=8, textColor=C_WARN_LI,
                                    leftIndent=10, spaceAfter=1)
        s_warn_sub = ParagraphStyle('ws', fontName='Helvetica',
                                    fontSize=7, textColor=C_MUTED)

        warn_story = (
            [Paragraph('⚠  Niveles superpuestos', s_warn_hdr)]
            + [Paragraph(f'• {o}', s_warn_li) for o in all_overlaps]
            + [Paragraph('Estos niveles coinciden en el gráfico — pueden verse como una sola línea.', s_warn_sub)]
        )
        warn_tbl = Table([[warn_story]], colWidths=[W - 4*cm])
        warn_tbl.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, -1), C_WARN_BG),
            ('BOX',           (0, 0), (-1, -1), 0.6, C_WARN_BRD),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ]))
        story.append(Spacer(1, 0.3*cm))
        story.append(warn_tbl)

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# ── DETAIL ────────────────────────────────────────────────────────────────────

def page_detail():
    accion_id = st.session_state.get('selected_accion_id')
    simbolo   = st.session_state.get('selected_simbolo', '—')

    st.markdown('<div class="back-btn">', unsafe_allow_html=True)
    if st.button('← Inicio', key='back'):
        st.session_state['page'] = 'home'
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    if not accion_id:
        st.session_state['page'] = 'home'
        st.rerun()

    info      = cached_info(accion_id)
    prices_df = cached_prices(accion_id)   # 400 días completos
    indic_df  = cached_indicators(accion_id)

    nombre  = (info.get('nombre')  or '') if info else ''
    mercado = (info.get('mercado') or '') if info else ''

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="margin:8px 0 6px">'
        f'<span style="font-size:1.6rem;font-weight:700;color:#f1f5f9;'
        f'font-family:monospace;letter-spacing:0.04em">{simbolo}</span>'
        f'<span style="font-size:0.85rem;color:#475569;margin-left:12px">{nombre[:60]}</span>'
        f'<span style="font-size:0.72rem;color:#60a5fa;background:#1e3a5f;'
        f'padding:2px 8px;border-radius:4px;margin-left:8px;font-family:monospace">'
        f'{mercado}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Métricas rápidas ──────────────────────────────────────────────────────
    if not prices_df.empty:
        last   = prices_df.iloc[-1]
        prev   = prices_df.iloc[-2] if len(prices_df) > 1 else last
        close  = cmp._f(last.get('close'))
        prev_c = cmp._f(prev.get('close'))
        pct    = ((close / prev_c) - 1) * 100 if close and prev_c and prev_c > 0 else None

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric('Precio',  cmp.fmt_price(close))
        m2.metric('% Día',   cmp.fmt_pct(pct))
        m3.metric('EMA 20',  cmp.fmt_price(cmp._f(last.get('ema20'))))
        m4.metric('SMA 50',  cmp.fmt_price(cmp._f(last.get('sma50'))))
        m5.metric('SMA 200', cmp.fmt_price(cmp._f(last.get('sma200'))))

    st.markdown('<hr>', unsafe_allow_html=True)

    # ── Bloque de estado ──────────────────────────────────────────────────────
    status = _asset_status(prices_df, indic_df)
    _render_status_block(status)

    # Señal WMA21/SMA30 (calculada sobre datos completos para ver último cruce real)
    wma_data_full = ch.get_wma_sma_signal(prices_df) if not prices_df.empty else {}
    st.markdown('<br>', unsafe_allow_html=True)
    _render_wma_signal_block(wma_data_full)
    st.markdown('<br>', unsafe_allow_html=True)

    # BUY_CONFIRMATION (capa adicional — calculada sobre datos completos)
    if not prices_df.empty:
        _sup_bc, _  = ch.get_support_resistance(prices_df)
        _dyn_bc, _2 = ch.get_dynamic_sr(prices_df)
        buy_conf_full = ch.get_buy_confirmation(prices_df, _sup_bc, _dyn_bc)
    else:
        buy_conf_full = {}
    _render_buy_confirmation_block(buy_conf_full)
    st.markdown('<br>', unsafe_allow_html=True)

    # Corto plazo: WMA6/WMA30 (calculado sobre datos completos para el panel)
    swing_data_full = ch.get_swing_signal(prices_df) if not prices_df.empty else {}
    if not prices_df.empty:
        _sup_es, _res_es = ch.get_support_resistance(prices_df)
        _, _dyn_res_es   = ch.get_dynamic_sr(prices_df)
        early_swing_full = ch.get_early_swing_signal(prices_df, _dyn_res_es, _res_es)
    else:
        early_swing_full = {}
    _render_swing_block(swing_data_full, early_swing_full)
    st.markdown('<br>', unsafe_allow_html=True)

    # ── Controles encima del gráfico: Estrategia + Temporalidad + PDF ────────
    import pandas as _pd

    col_strat, col_tf, col_pdf = st.columns([3, 1.5, 1])

    with col_strat:
        chart_strategy = st.selectbox(
            'Estrategia',
            _STRAT_OPTIONS,
            key='chart_strategy',
        )

    with col_tf:
        chart_tf_label = st.selectbox(
            'Temporalidad',
            list(_TF_CHART.keys()),
            key='chart_tf_label',
        )

    candle_freq = _TF_CHART.get(chart_tf_label, 'D')
    cur_tf      = '1A'   # para ticks diarios

    # Flags derivados de la estrategia seleccionada
    _flags        = _STRAT_FLAGS.get(chart_strategy, _STRAT_FLAGS['(Seleccionar)'])
    ind_sma50     = _flags['sma50']
    ind_sma200    = _flags['sma200']
    ind_ema20     = _flags['ema20']
    ind_volume    = True   # siempre
    ind_dyn_sr    = _flags['dyn_sr']
    ind_static_sr = _flags['static_sr']
    ind_wma6      = _flags['wma6']
    ind_wma30     = _flags['wma30']
    show_wma      = _flags['wma']        and (candle_freq == 'D')
    show_swing    = (_flags['wma6'] or _flags['wma30'] or _flags['swing']) and (candle_freq == 'D')
    _do_buy_conf  = _flags['buy_conf']   and (candle_freq == 'D')
    _do_early_sw  = _flags['early_swing'] and (candle_freq == 'D')

    # ── Datos fuente ──────────────────────────────────────────────────────────
    if candle_freq == 'D':
        _last = _pd.Timestamp(prices_df['fecha'].iloc[-1])
        _cut  = (_last - _pd.Timedelta(days=TF_OPTIONS[cur_tf])).strftime('%Y-%m-%d')
        prices_slice = prices_df[prices_df['fecha'] >= _cut].reset_index(drop=True)
    else:
        prices_slice = prices_df

    if not indic_df.empty and not prices_slice.empty and candle_freq == 'D':
        cutoff      = prices_slice['fecha'].iloc[0]
        indic_slice = indic_df[indic_df['fecha'] >= cutoff].reset_index(drop=True)
    else:
        indic_slice = indic_df

    # S/R siempre sobre datos diarios completos
    sup, res         = ch.get_support_resistance(prices_df) if not prices_df.empty else ([], [])
    dyn_sup, dyn_res = ch.get_dynamic_sr(prices_df)         if not prices_df.empty else ([], [])

    chart_df = ch.resample_ohlcv(prices_slice, candle_freq)

    # Señales (solo en modo diario — marcadores necesitan fechas diarias)
    wma_data_slice = (ch.get_wma_sma_signal(prices_slice)
                      if show_wma and not prices_slice.empty else None)

    buy_conf_slice = (ch.get_buy_confirmation(prices_slice, sup, dyn_sup)
                      if _do_buy_conf and not prices_slice.empty else {})

    swing_slice = (ch.get_swing_signal(prices_slice)
                   if show_swing and not prices_slice.empty else None)

    early_swing_slice = (ch.get_early_swing_signal(prices_slice, dyn_res, res)
                         if _do_early_sw and not prices_slice.empty else None)

    _dyn_sup_chart = dyn_sup if ind_dyn_sr else []
    _dyn_res_chart = dyn_res if ind_dyn_sr else []

    price_fig = (ch.price_chart(
        chart_df, simbolo, cur_tf,
        _dyn_sup_chart, _dyn_res_chart,
        wma_data=wma_data_slice,
        buy_conf_data=buy_conf_slice,
        swing_data=swing_slice,
        early_swing_data=early_swing_slice,
        show_sma50=ind_sma50,
        show_sma200=ind_sma200,
        show_ema20=ind_ema20,
        show_volume=ind_volume,
        show_static_sr=ind_static_sr,
        show_wma6=ind_wma6,
        show_wma30=ind_wma30,
        candle_freq=candle_freq,
    ) if not chart_df.empty else None)

    # PDF en la tercera columna (disponible tras calcular price_fig)
    with col_pdf:
        if price_fig is not None:
            try:
                pdf_bytes = _build_pdf(simbolo, mercado, cur_tf, prices_df, prices_slice,
                                       sup, res, status, dyn_sup, dyn_res,
                                       wma_data=wma_data_full)
                st.download_button(
                    label='⬇ PDF',
                    data=pdf_bytes,
                    file_name=f'{simbolo}_{cur_tf}.pdf',
                    mime='application/pdf',
                    use_container_width=True,
                )
            except Exception:
                st.button('⬇ PDF', disabled=True, use_container_width=True)

    # ── Tabs de gráficos ──────────────────────────────────────────────────────
    tab_price, tab_rsi, tab_mom = st.tabs(['📈 Precio', '📉 RSI', '🚀 Momentum'])

    with tab_price:
        if prices_slice.empty:
            st.info('Sin datos de precio.')
        else:
            st.plotly_chart(
                price_fig,
                use_container_width=True,
                config={'displayModeBar': False},
            )
            _render_chart_legend(
                show_wma=show_wma,
                show_wma6=ind_wma6,
                show_wma30=ind_wma30,
                show_sma50=ind_sma50,
                show_sma200=ind_sma200,
                show_ema20=ind_ema20,
                show_buy_conf=_do_buy_conf,
                show_dyn_sr=ind_dyn_sr,
                show_static_sr=ind_static_sr,
            )
            st.markdown('<hr>', unsafe_allow_html=True)
            _render_sr_values(sup, res, dyn_sup, dyn_res)

    with tab_rsi:
        if indic_slice.empty or indic_slice['rsi14'].isna().all():
            st.info('Sin datos de RSI.')
        else:
            st.plotly_chart(
                ch.rsi_chart(indic_slice, cur_tf),
                use_container_width=True,
                config={'displayModeBar': False},
            )
            rsi_val = status.get('rsi')
            if rsi_val is not None:
                if rsi_val < 30:
                    estado, color = 'SOBREVENDIDO', '#10b981'
                elif rsi_val > 70:
                    estado, color = 'SOBRECOMPRADO', '#ef4444'
                else:
                    estado, color = 'NEUTRAL', '#94a3b8'
                st.markdown(
                    f'RSI actual: <span style="color:{color};font-weight:700;'
                    f'font-family:monospace">{rsi_val:.1f}</span>'
                    f' — <span style="color:{color}">{estado}</span>',
                    unsafe_allow_html=True,
                )

    with tab_mom:
        no_mom = indic_slice.empty or \
                 (indic_slice['mom_12_1'].isna().all() and
                  indic_slice['rs_sector'].isna().all())
        if no_mom:
            st.info('Sin datos de momentum / RS sector.')
        else:
            st.plotly_chart(
                ch.momentum_chart(indic_slice, cur_tf),
                use_container_width=True,
                config={'displayModeBar': False},
            )
            i1, i2, i3 = st.columns(3)
            mom = status.get('mom')
            rs  = status.get('rs')
            i1.metric('Mom 12-1',  f'{mom*100:+.1f}%' if mom is not None else '—')
            i2.metric('RS Sector', f'{rs:.3f}'         if rs  is not None else '—')


# ── Router ────────────────────────────────────────────────────────────────────

def main():
    page = st.session_state.get('page', 'home')
    if page == 'home':
        page_home()
    elif page == 'detail':
        page_detail()
    else:
        st.session_state['page'] = 'home'
        st.rerun()


if __name__ == '__main__':
    main()
