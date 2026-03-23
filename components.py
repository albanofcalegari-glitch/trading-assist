"""
components.py — Componentes UI para trading-assist dashboard
"""
import streamlit as st
from decimal import Decimal

# ── Helpers ───────────────────────────────────────────────────────────────────

def _f(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt_price(v) -> str:
    f = _f(v)
    if f is None:
        return '—'
    return f'${f:,.2f}' if f >= 1 else f'${f:.4f}'


def fmt_pct(v, sign=True) -> str:
    f = _f(v)
    if f is None:
        return '—'
    return f'{f:+.2f}%' if sign else f'{f:.2f}%'


def pct_color(v) -> str:
    f = _f(v)
    if f is None:
        return '#4b5563'
    return '#10b981' if f >= 0 else '#ef4444'


# ── CSS global ────────────────────────────────────────────────────────────────

GLOBAL_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  html, body,
  [data-testid="stAppViewContainer"],
  [data-testid="stHeader"],
  [data-testid="stToolbar"]        { background: #0a0e1a !important; }

  section[data-testid="stSidebar"] { background: #0f1623 !important; }

  /* Header fijo de Streamlit: altura ~3.75rem — el block-container debe arrancar debajo */
  [data-testid="stHeader"] {
    height: 3.75rem !important;
    overflow: visible !important;
  }

  .block-container {
    padding: 4.5rem 2rem 2rem !important;
    max-width: 1400px !important;
    overflow: visible !important;
  }

  /* Texto base */
  body, p, span, div { font-family: 'Inter', sans-serif !important; }

  /* Métricas */
  [data-testid="stMetricLabel"]  { font-size: 0.72rem !important; color: #64748b !important; text-transform: uppercase; letter-spacing: 0.05em; }
  [data-testid="stMetricValue"]  { font-size: 1.05rem !important; font-weight: 600 !important; color: #f1f5f9 !important; }

  /* Inputs */
  [data-testid="stTextInput"] input {
    background: #111827 !important;
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
    color: #f1f5f9 !important;
    font-size: 0.9rem !important;
    padding: 10px 14px !important;
  }
  [data-testid="stTextInput"] input:focus {
    border-color: #3b82f6 !important;
    box-shadow: 0 0 0 2px rgba(59,130,246,0.15) !important;
  }

  /* Selectbox */
  [data-testid="stSelectbox"] > div > div {
    background: #111827 !important;
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
    color: #f1f5f9 !important;
  }

  /* Botones de tabla (ticker) */
  .ticker-btn > button {
    background: transparent !important;
    border: none !important;
    color: #60a5fa !important;
    font-weight: 600 !important;
    font-size: 0.88rem !important;
    font-family: 'JetBrains Mono', monospace !important;
    padding: 0 !important;
    cursor: pointer !important;
    letter-spacing: 0.03em;
  }
  .ticker-btn > button:hover { color: #93c5fd !important; }

  /* Botón volver */
  .back-btn > button {
    background: #111827 !important;
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
    color: #94a3b8 !important;
    font-size: 0.82rem !important;
    padding: 6px 14px !important;
  }
  .back-btn > button:hover {
    border-color: #3b82f6 !important;
    color: #f1f5f9 !important;
  }

  /* Refresh */
  .refresh-btn > button {
    background: #111827 !important;
    border: 1px solid #1e293b !important;
    border-radius: 8px !important;
    color: #64748b !important;
    font-size: 0.82rem !important;
    padding: 8px 16px !important;
  }
  .refresh-btn > button:hover { border-color: #3b82f6 !important; color: #f1f5f9 !important; }

  /* Paginación */
  .pg-btn > button {
    background: #111827 !important;
    border: 1px solid #1e293b !important;
    border-radius: 6px !important;
    color: #64748b !important;
    font-size: 0.85rem !important;
    min-width: 36px !important;
    padding: 4px 10px !important;
  }
  .pg-btn > button:hover { border-color: #3b82f6 !important; color: #f1f5f9 !important; }

  /* Tabs */
  [data-testid="stTabs"] button {
    font-size: 0.82rem !important;
    color: #64748b !important;
    font-weight: 500 !important;
  }
  [data-testid="stTabs"] button[aria-selected="true"] {
    color: #f1f5f9 !important;
    border-bottom-color: #3b82f6 !important;
  }

  /* Dividers */
  hr { border: none; border-top: 1px solid #1e293b !important; margin: 12px 0 !important; }

  /* Plotly chart background passthrough */
  [data-testid="stPlotlyChart"] { background: transparent !important; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: #0a0e1a; }
  ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 2px; }

  /* ── Menú hamburguesa: solo selector de tema (System / Light / Dark) ──────
     Oculta: Rerun, Auto rerun, Clear cache, Print, Record screen, footer.
     Los ítems de acción tienen un shortcut de teclado (abbr/kbd) o son
     un toggle/checkbox (Auto rerun) — los ocultamos por esas características.
  ─────────────────────────────────────────────────────────────────────────── */

  /* Ítems con shortcut de teclado: Rerun (R), Clear cache (C) */
  [data-testid="stMainMenuPopover"] li:has(abbr),
  [data-testid="stMainMenuPopover"] li:has(kbd),
  [data-testid="stMainMenuRerun"],
  [data-testid="stMainMenuClearCache"] { display: none !important; }

  /* Auto rerun (toggle interno) */
  [data-testid="stMainMenuPopover"] li:has(input[type="checkbox"]) { display: none !important; }

  /* Print y Record screen */
  [data-testid="stMainMenuPrint"],
  [data-testid="stMainMenuRecordScreen"] { display: none !important; }

  /* Footer "Made with Streamlit v..." */
  [data-testid="stMainMenuPopover"] a[href] { display: none !important; }

  /* Separadores hr huérfanos */
  [data-testid="stMainMenuPopover"] hr { display: none !important; }
</style>
"""


# ── Bloques top movers ────────────────────────────────────────────────────────

def render_mover_block(title: str, rows: list[dict], is_up: bool = True) -> None:
    accent = '#10b981' if is_up else '#ef4444'
    icon   = '▲' if is_up else '▼'

    with st.container(border=True):
        # Header
        st.markdown(
            f'<div style="padding:2px 0 8px">'
            f'<span style="color:{accent};font-size:0.72rem;margin-right:6px">{icon}</span>'
            f'<span style="color:#64748b;font-size:0.72rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.08em">{title}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if not rows:
            st.markdown('<span style="color:#475569;font-size:0.8rem">Sin datos</span>',
                        unsafe_allow_html=True)
            return

        for r in rows:
            pct    = _f(r.get('pct_cambio'))
            color  = '#10b981' if (pct or 0) >= 0 else '#ef4444'
            nombre = (r.get('nombre') or '')[:32]
            sym    = r.get('simbolo', '')

            left, right = st.columns([3, 2])
            with left:
                st.markdown(
                    f'<div style="line-height:1.3;padding:2px 0">'
                    f'<span style="color:#f1f5f9;font-weight:700;font-family:monospace;'
                    f'font-size:0.9rem">{sym}</span><br>'
                    f'<span style="color:#475569;font-size:0.7rem">{nombre}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with right:
                st.markdown(
                    f'<div style="text-align:right;line-height:1.3;padding:2px 0">'
                    f'<span style="color:#cbd5e1;font-family:monospace;font-size:0.85rem">'
                    f'{fmt_price(r.get("precio"))}</span><br>'
                    f'<span style="color:{color};font-weight:700;font-family:monospace;'
                    f'font-size:0.85rem">{fmt_pct(pct)}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            st.markdown('<hr>', unsafe_allow_html=True)


# ── Buscador + selector de mercado ───────────────────────────────────────────

def render_filter_bar(markets: list[str]) -> tuple[str, str | None]:
    """
    Retorna (search_text, selected_market_or_None).
    Usa session_state para búsqueda y mercado.
    """
    st.markdown("""
    <div style="
        background:#111827; border:1px solid #1e293b;
        border-radius:10px; padding:14px 16px; margin-bottom:12px;
        display:flex; align-items:center; gap:12px;
    ">
      <span style="color:#3b82f6;font-size:1.1rem">⌕</span>
      <span style="color:#475569;font-size:0.8rem">Buscar activo</span>
    </div>
    """, unsafe_allow_html=True)

    col_search, col_market = st.columns([3, 1])

    with col_search:
        search = st.text_input(
            'search',
            value=st.session_state.get('tbl_search', ''),
            placeholder='⌕  Buscar por ticker o nombre…',
            label_visibility='collapsed',
            key='search_input',
        )

    with col_market:
        options   = ['Todos', 'USA', 'BYMA'] + [m for m in markets
                    if m not in ('BYMA', 'NASDAQ', 'NYSE', 'NYSE_AMERICAN',
                                 'NYSE_ARCA', 'CBOE_BZX')]
        cur_sel   = st.session_state.get('tbl_market_label', 'Todos')
        idx       = options.index(cur_sel) if cur_sel in options else 0
        sel       = st.selectbox('Mercado', options, index=idx,
                                 label_visibility='collapsed', key='market_select')

    # Mapear selección a filtro SQL
    # 'Todos' → None (deduplicación automática USA > BYMA en queries.py)
    # 'USA'   → 'USA' (filtra a mercados americanos solamente)
    # 'BYMA'  → 'BYMA' (muestra CEDEARs/locales explícitamente)
    market_filter = None if sel == 'Todos' else sel

    return search.strip(), market_filter, sel


# ── Tabla de activos ──────────────────────────────────────────────────────────

def render_asset_table(rows: list[dict]) -> None:
    if not rows:
        st.markdown(
            '<div style="color:#475569;font-size:0.85rem;padding:20px 0;text-align:center">'
            'Sin resultados para los filtros aplicados.</div>',
            unsafe_allow_html=True,
        )
        return

    # Header
    hcols = st.columns([1.1, 3.2, 1.4, 1.3, 1])
    labels = ['TICKER', 'NOMBRE', 'MERCADO', 'PRECIO', '% DÍA']
    for c, lbl in zip(hcols, labels):
        c.markdown(
            f'<span style="color:#334155;font-size:0.68rem;font-weight:700;'
            f'text-transform:uppercase;letter-spacing:0.1em">{lbl}</span>',
            unsafe_allow_html=True,
        )

    st.markdown('<hr>', unsafe_allow_html=True)

    for i, r in enumerate(rows):
        pct   = _f(r.get('pct_cambio'))
        color = '#10b981' if (pct or 0) >= 0 else '#ef4444'
        bg    = 'rgba(255,255,255,0.012)' if i % 2 == 0 else 'transparent'

        cols = st.columns([1.1, 3.2, 1.4, 1.3, 1])

        with cols[0]:
            st.markdown('<div class="ticker-btn">', unsafe_allow_html=True)
            if st.button(r['simbolo'], key=f"t_{r['accion_id']}_{i}",
                         use_container_width=False):
                st.session_state['selected_accion_id'] = r['accion_id']
                st.session_state['selected_simbolo']   = r['simbolo']
                st.session_state['page'] = 'detail'
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        cols[1].markdown(
            f'<span style="font-size:0.82rem;color:#94a3b8">{(r.get("nombre") or "")[:48]}</span>',
            unsafe_allow_html=True)
        cols[2].markdown(
            f'<span style="font-size:0.78rem;color:#475569;font-family:monospace">'
            f'{r.get("mercado","")}</span>',
            unsafe_allow_html=True)
        cols[3].markdown(
            f'<span style="font-size:0.88rem;color:#e2e8f0;font-family:monospace">'
            f'{fmt_price(r.get("precio"))}</span>',
            unsafe_allow_html=True)
        cols[4].markdown(
            f'<span style="font-size:0.88rem;color:{color};font-weight:600;font-family:monospace">'
            f'{fmt_pct(pct)}</span>',
            unsafe_allow_html=True)
