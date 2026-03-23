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
    'tf':                 '3M',    # timeframe activo en detalle: '3M'|'1A'
}
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


def _render_chart_legend() -> None:
    """Fila compacta que identifica cada tipo de línea del gráfico de precio."""
    items = [
        # (símbolo SVG-like, color, etiqueta)
        ('dotted', '#10b981',              'Soporte estático'),
        ('dotted', '#ef4444',              'Resistencia estática'),
        ('dashed', 'rgba(16,185,129,0.8)', 'Soporte dinámico'),
        ('dashed', 'rgba(239,68,68,0.8)',  'Resistencia dinámica'),
        ('solid',  '#8b5cf6',              'EMA 20'),
        ('solid',  '#3b82f6',              'SMA 50'),
        ('solid',  '#f59e0b',              'SMA 200'),
    ]

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
               sup, res, status, fig,
               dyn_sup=None, dyn_res=None) -> bytes:
    """Genera un PDF con ticker, fecha, gráfico, S/R y estado del activo."""
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

    status_data = [
        [_p('Indicador', bold=True), _p('Valor', bold=True)],
        [_p('Tendencia'),            _p(tend,    tend_col, True)],
        [_p('Sobre SMA 200'),        _p(sma_txt, sma_col,  True)],
        [_p('RSI 14'),               _p(rsi_txt, rsi_col,  True)],
        [_p('Momentum 12-1'),        _p(mom_txt, mom_col,  True)],
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

    # ── Gráfico ───────────────────────────────────────────────────────────────
    story.append(Paragraph('Gráfico de precio', s_head2))
    try:
        img_bytes = fig.to_image(format='png', width=900, height=480, scale=1.5)
        story.append(RLImage(io.BytesIO(img_bytes),
                             width=W - 4*cm, height=(W - 4*cm) * 480/900))
    except Exception as e:
        story.append(Paragraph(f'(Gráfico no disponible: {e})', s_norm))

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
    st.markdown('<br>', unsafe_allow_html=True)

    # ── Selector de temporalidad + botón PDF — fila fija sobre el gráfico ────
    tf_labels = list(TF_OPTIONS.keys())   # ['3M', '1A']
    cur_tf    = st.session_state['tf']
    if cur_tf not in tf_labels:
        cur_tf = '3M'
        st.session_state['tf'] = cur_tf

    row_tf, row_pdf = st.columns([3, 1])
    with row_tf:
        selected_tf = st.segmented_control(
            'Timeframe',
            tf_labels,
            default=cur_tf,
            label_visibility='collapsed',
            key='tf_ctrl',
        )
        if selected_tf is not None and selected_tf != st.session_state['tf']:
            st.session_state['tf'] = selected_tf
            st.rerun()

    cur_tf = st.session_state['tf']

    # Cortar el DataFrame al timeframe seleccionado por fecha calendario
    import pandas as _pd
    _last  = _pd.Timestamp(prices_df['fecha'].iloc[-1])
    _cut   = (_last - _pd.Timedelta(days=TF_OPTIONS[cur_tf])).strftime('%Y-%m-%d')
    prices_slice = prices_df[prices_df['fecha'] >= _cut].reset_index(drop=True)

    # Indicators: mismo rango temporal
    if not indic_df.empty and not prices_slice.empty:
        cutoff      = prices_slice['fecha'].iloc[0]
        indic_slice = indic_df[indic_df['fecha'] >= cutoff].reset_index(drop=True)
    else:
        indic_slice = indic_df

    # S/R estático + dinámico (ambos sobre datos completos — más señal)
    sup, res         = ch.get_support_resistance(prices_df) if not prices_df.empty else ([], [])
    dyn_sup, dyn_res = ch.get_dynamic_sr(prices_df)         if not prices_df.empty else ([], [])

    # Figura con ambas capas de S/R
    price_fig = (ch.price_chart(prices_slice, simbolo, cur_tf, dyn_sup, dyn_res)
                 if not prices_slice.empty else None)

    with row_pdf:
        if price_fig is not None:
            pdf_bytes = _build_pdf(simbolo, mercado, cur_tf, prices_df, prices_slice,
                                   sup, res, status, price_fig, dyn_sup, dyn_res)
            st.download_button(
                label='⬇ PDF',
                data=pdf_bytes,
                file_name=f'{simbolo}_{cur_tf}.pdf',
                mime='application/pdf',
                use_container_width=True,
            )

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
            _render_chart_legend()
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
