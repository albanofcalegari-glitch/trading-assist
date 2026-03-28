"""
export_buy_confirmation_pdf.py
─────────────────────────────────────────────────────────────────────────────
Escanea activos, detecta BUY_CONFIRMATION y genera un PDF con:
  - Portada con resumen
  - 2 activos por pagina: mini-header + grafico WMA21/SMA30 con markers

Uso:
    python export_buy_confirmation_pdf.py
    python export_buy_confirmation_pdf.py --market USA
    python export_buy_confirmation_pdf.py --only-fuerte
    python export_buy_confirmation_pdf.py --limit 40
    python export_buy_confirmation_pdf.py --output reporte.pdf
    python export_buy_confirmation_pdf.py --days 120
"""
import sys, os, argparse, time, io
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

import pymysql
import pandas as pd

import charts as ch

# ── Config BD ────────────────────────────────────────────────────────────────
BOLSA_CFG = dict(
    host='localhost', user='root', password='123456', db='bolsa',
    charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
    ssl={'ssl_disabled': False},
)
USA_MARKETS = ('NASDAQ', 'NYSE', 'NYSE_AMERICAN', 'NYSE_ARCA', 'CBOE_BZX')


def _conn():
    return pymysql.connect(**BOLSA_CFG)


# ── Fetch masivo (igual que scan_buy_confirmation) ────────────────────────────

def fetch_bulk(days: int, market: str | None) -> pd.DataFrame:
    if market == 'USA':
        ph       = ','.join(['%s'] * len(USA_MARKETS))
        m_clause = f"AND m.descripcion IN ({ph})"
        m_params = list(USA_MARKETS)
    elif market:
        m_clause = "AND m.descripcion = %s"
        m_params = [market]
    else:
        m_clause = ""
        m_params = []

    active_subq = """
        SELECT DISTINCT accion_id FROM valorhistoricoaccion
        WHERE fecha >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) AND precio_cierre > 0.5
    """
    sql = f"""
        SELECT v.accion_id, a.simbolo, a.nombre, m.descripcion AS mercado,
               v.fecha, v.precio_apertura AS open, v.precio_max AS high,
               v.precio_min AS low, v.precio_cierre AS close,
               v.volumen AS volume, it.rsi14
        FROM valorhistoricoaccion v
        JOIN accion  a ON a.id = v.accion_id
        JOIN mercado m ON m.id = a.mercado_id
        LEFT JOIN indicadortecnico it
               ON it.accion_id = v.accion_id AND it.fecha = v.fecha
        WHERE v.accion_id IN ({active_subq})
          AND v.fecha >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
          AND v.precio_cierre > 0.5
          {m_clause}
        ORDER BY v.accion_id, v.fecha
    """
    print(f"  Descargando datos ({days} dias)...", end=' ', flush=True)
    t0 = time.time()
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [days] + m_params)
            rows = cur.fetchall()
    print(f"{len(rows):,} filas en {time.time()-t0:.1f}s")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for col in ['open', 'high', 'low', 'close', 'volume', 'rsi14']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['fecha'] = df['fecha'].astype(str)
    return df


# ── Procesar activo → devuelve (result_dict, prepared_grp) ───────────────────

def process_asset(grp: pd.DataFrame):
    """
    Retorna (dict_resultado, grp_con_mas, sup, dyn_sup, conf) o (None, ...).
    Guardamos grp y S/R para generar el grafico despues sin recalcular.
    """
    grp = grp.reset_index(drop=True)
    if len(grp) < 30:
        return None, None, None, None, None

    grp['ema20']  = grp['close'].ewm(span=20, adjust=False).mean()
    grp['sma50']  = grp['close'].rolling(50).mean()
    grp['sma200'] = grp['close'].rolling(200, min_periods=80).mean()

    sup,     _res = ch.get_support_resistance(grp)
    dyn_sup, _dr  = ch.get_dynamic_sr(grp)
    _,       res  = ch.get_support_resistance(grp)
    _,       dyn_res = ch.get_dynamic_sr(grp)

    conf = ch.get_buy_confirmation(grp, sup, dyn_sup)
    if not conf['signals']:
        return None, None, None, None, None

    meta = grp.iloc[0]
    last = grp.iloc[-1]

    result = {
        'simbolo':       str(meta['simbolo']),
        'nombre':        (str(meta.get('nombre') or ''))[:45],
        'mercado':       str(meta['mercado']),
        'precio':        float(last['close']),
        'activo':        conf['activo'],
        'fuerza':        conf['fuerza'],
        'motivo':        ' | '.join(conf['motivo']),
        'fecha_signal':  conf['fecha'],
        'cerca_soporte': conf['cerca_soporte'],
        'n_signals':     len(conf['signals']),
        'rsi':           float(last['rsi14']) if pd.notna(last.get('rsi14')) else None,
        'sup':           sup,
        'res':           res,
        'dyn_sup':       dyn_sup,
        'dyn_res':       dyn_res,
    }
    return result, grp, conf, dyn_sup, dyn_res


# ── Generar imagen del grafico para un activo ─────────────────────────────────

def make_chart_png(grp: pd.DataFrame, result: dict, conf: dict,
                   dyn_sup: list, dyn_res: list,
                   img_w: int = 860, img_h: int = 380) -> bytes | None:
    """
    Genera PNG del grafico con WMA21/SMA30 activos + BUY_CONF markers.
    Usa los ultimos 90 dias del grp para que el grafico sea legible.
    """
    try:
        # Slice: ultimos 90 dias
        if len(grp) > 90:
            df_plot = grp.tail(90).reset_index(drop=True)
        else:
            df_plot = grp.copy()

        wma_data  = ch.get_wma_sma_signal(df_plot)
        conf_plot = ch.get_buy_confirmation(
            df_plot, result['sup'], result['dyn_sup']
        )

        fig = ch.price_chart(
            df_plot,
            simbolo=result['simbolo'],
            tf='3M',
            dyn_sup=dyn_sup,
            dyn_res=dyn_res,
            wma_data=wma_data,
            buy_conf_data=conf_plot,
        )
        return fig.to_image(format='png', width=img_w, height=img_h, scale=1.5)
    except Exception as e:
        print(f"\n    [!] Error grafico {result['simbolo']}: {e}")
        return None


# ── Construir PDF ─────────────────────────────────────────────────────────────

def build_pdf(results_with_data: list, market_label: str, days: int) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, Image as RLImage,
                                    PageBreak, HRFlowable)

    W, H = A4
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=1.5*cm, rightMargin=1.5*cm,
                              topMargin=1.5*cm,  bottomMargin=1.5*cm)

    # Paleta
    C_BG    = HexColor('#0a0e1a')
    C_CARD  = HexColor('#111827')
    C_BLUE  = HexColor('#3b82f6')
    C_TEXT  = HexColor('#f1f5f9')
    C_MUTED = HexColor('#64748b')
    C_GRN   = HexColor('#10b981')
    C_RED   = HexColor('#ef4444')
    C_AMB   = HexColor('#f59e0b')
    C_GOLD  = HexColor('#fbbf24')
    C_ORG   = HexColor('#fb923c')

    def _p(txt, color=C_TEXT, bold=False, size=9):
        fn = 'Helvetica-Bold' if bold else 'Helvetica'
        return Paragraph(
            f'<font name="{fn}" color="{color.hexval()}">{txt}</font>',
            ParagraphStyle('_', fontSize=size, leading=size + 3)
        )

    s_title = ParagraphStyle('title', fontName='Helvetica-Bold',
                              fontSize=22, textColor=C_TEXT, spaceAfter=6)
    s_sub   = ParagraphStyle('sub',   fontName='Helvetica',
                              fontSize=10, textColor=C_MUTED, spaceAfter=10)
    s_h2    = ParagraphStyle('h2',    fontName='Helvetica-Bold',
                              fontSize=11, textColor=C_BLUE,
                              spaceBefore=8, spaceAfter=4)
    s_norm  = ParagraphStyle('norm',  fontName='Helvetica',
                              fontSize=8,  textColor=C_TEXT)

    story = []

    # ── Portada ───────────────────────────────────────────────────────────────
    fecha_gen = datetime.now().strftime('%Y-%m-%d %H:%M')
    n_fuerte  = sum(1 for r, *_ in results_with_data if r['fuerza'] == 'FUERTE')
    n_media   = sum(1 for r, *_ in results_with_data if r['fuerza'] == 'MEDIA')

    story.append(Spacer(1, 2*cm))
    story.append(Paragraph('BUY_CONFIRMATION', s_title))
    story.append(Paragraph(
        f'Senales activas &nbsp;·&nbsp; Mercado: {market_label} &nbsp;·&nbsp; '
        f'Historia: {days} dias &nbsp;·&nbsp; Generado: {fecha_gen}', s_sub))

    # Tabla resumen portada
    summary_data = [
        [_p('Metrica', bold=True),     _p('Valor', bold=True)],
        [_p('Total senales'),           _p(str(len(results_with_data)), C_TEXT, True)],
        [_p('FUERTE  (cerca soporte)'), _p(str(n_fuerte), C_GOLD, True)],
        [_p('MEDIA'),                   _p(str(n_media),  C_ORG,  True)],
        [_p('Condicion RSI > 50'),
         _p(str(sum(1 for r,*_ in results_with_data if 'RSI > 50' in r['motivo'])),
            C_TEXT, True)],
        [_p('Condicion RSI recuperacion'),
         _p(str(sum(1 for r,*_ in results_with_data if 'RSI recuperacion' in r['motivo'] or 'recuperaci' in r['motivo'])),
            C_TEXT, True)],
    ]
    tbl = Table(summary_data, colWidths=[8*cm, 6*cm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  C_CARD),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [C_CARD, HexColor('#0f1623')]),
        ('GRID',          (0,0), (-1,-1), 0.3, HexColor('#1e293b')),
        ('TOPPADDING',    (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.8*cm))

    # Tabla indice: simbolo | mercado | fuerza | fecha | motivo
    story.append(Paragraph('Indice de senales', s_h2))
    idx_data = [[_p('Simbolo', bold=True), _p('Mercado', bold=True),
                 _p('Fuerza',  bold=True), _p('Fecha',   bold=True),
                 _p('Motivo',  bold=True)]]
    for r, *_ in results_with_data:
        f_col = C_GOLD if r['fuerza'] == 'FUERTE' else C_ORG
        soporte_mark = ' [S]' if r['cerca_soporte'] else ''
        idx_data.append([
            _p(r['simbolo'], C_TEXT, True, 8),
            _p(r['mercado'], C_MUTED, size=8),
            _p((r['fuerza'] or '-') + soporte_mark, f_col, True, 8),
            _p(r['fecha_signal'] or '-', C_TEXT, size=8),
            _p(r['motivo'], C_MUTED, size=7),
        ])
    idx_tbl = Table(idx_data, colWidths=[2.2*cm, 3*cm, 2.2*cm, 2.4*cm, 7.2*cm])
    idx_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0),  C_CARD),
        ('ROWBACKGROUNDS',(0,1), (-1,-1), [C_CARD, HexColor('#0f1623')]),
        ('GRID',          (0,0), (-1,-1), 0.3, HexColor('#1e293b')),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 6),
        ('FONTSIZE',      (0,0), (-1,-1), 7),
    ]))
    story.append(idx_tbl)
    story.append(PageBreak())

    # ── Una pagina por activo ─────────────────────────────────────────────────
    chart_w = W - 3*cm
    chart_h = chart_w * 380 / 860   # mantener aspecto

    for i, (r, grp, conf, dyn_sup, dyn_res) in enumerate(results_with_data):
        f_col       = C_GOLD if r['fuerza'] == 'FUERTE' else C_ORG
        activo_col  = C_GRN  if r['activo'] else C_MUTED
        soporte_tag = '  [SOPORTE]' if r['cerca_soporte'] else ''
        rsi_val     = f"{r['rsi']:.1f}" if r['rsi'] is not None else 'N/D'
        rsi_col     = C_GRN if (r['rsi'] and r['rsi'] < 30) else (C_RED if (r['rsi'] and r['rsi'] > 70) else C_TEXT)

        # Mini-header del activo
        hdr_data = [[
            _p(r['simbolo'], C_TEXT,  True, 14),
            _p(r['nombre'],  C_MUTED, size=9),
            _p(r['mercado'], C_BLUE,  size=9),
            _p(f"Precio: ${r['precio']:,.2f}", C_TEXT, size=9),
        ]]
        hdr_tbl = Table(hdr_data, colWidths=[2.5*cm, 7*cm, 3*cm, 4.5*cm])
        hdr_tbl.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,-1), HexColor('#0d1424')),
            ('TOPPADDING',   (0,0), (-1,-1), 6),
            ('BOTTOMPADDING',(0,0), (-1,-1), 6),
            ('LEFTPADDING',  (0,0), (-1,-1), 8),
            ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
            ('BOX',          (0,0), (-1,-1), 0.5, HexColor('#1e293b')),
        ]))
        story.append(hdr_tbl)

        # Fila de estado: BUY_CONFIRMATION | fuerza | fecha | motivo | RSI
        st_data = [[
            _p('BUY_CONF', C_MUTED, size=7),
            _p('ACTIVO' if r['activo'] else 'inactivo', activo_col, True, 9),
            _p('Fuerza', C_MUTED, size=7),
            _p((r['fuerza'] or '-') + soporte_tag, f_col, True, 9),
            _p('Fecha senal', C_MUTED, size=7),
            _p(r['fecha_signal'] or '-', C_TEXT, size=9),
            _p('RSI 14', C_MUTED, size=7),
            _p(rsi_val, rsi_col, True, 9),
            _p('Motivo', C_MUTED, size=7),
            _p(r['motivo'], C_TEXT, size=8),
        ]]
        st_tbl = Table(st_data,
                       colWidths=[1.5*cm, 1.5*cm, 1.3*cm, 2.5*cm,
                                  2*cm, 2.2*cm, 1.3*cm, 1.3*cm,
                                  1.4*cm, 3*cm])
        st_tbl.setStyle(TableStyle([
            ('BACKGROUND',   (0,0), (-1,-1), C_CARD),
            ('TOPPADDING',   (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',(0,0), (-1,-1), 5),
            ('LEFTPADDING',  (0,0), (-1,-1), 5),
            ('VALIGN',       (0,0), (-1,-1), 'MIDDLE'),
            ('BOX',          (0,0), (-1,-1), 0.3, HexColor('#1e293b')),
        ]))
        story.append(st_tbl)
        story.append(Spacer(1, 0.2*cm))

        # Grafico
        png = make_chart_png(grp, r, conf, dyn_sup, dyn_res)
        if png:
            story.append(RLImage(io.BytesIO(png), width=chart_w, height=chart_h))
        else:
            story.append(Paragraph('(Grafico no disponible)', s_norm))

        # Soportes/Resistencias si hay
        sup_list = r.get('sup', [])
        res_list = r.get('res', [])
        if sup_list or res_list:
            sr_items = []
            for sv in sup_list[:3]:
                sr_items.append(_p(f'Sop: ${sv:,.2f}', C_GRN, size=7))
            for rv in res_list[:3]:
                sr_items.append(_p(f'Res: ${rv:,.2f}', C_RED, size=7))
            sr_row = [sr_items + [_p('', size=7)] * max(0, 6 - len(sr_items))]
            sr_tbl = Table(sr_row, colWidths=[(chart_w / 6)] * 6)
            sr_tbl.setStyle(TableStyle([
                ('BACKGROUND',   (0,0), (-1,-1), HexColor('#0d1424')),
                ('TOPPADDING',   (0,0), (-1,-1), 3),
                ('BOTTOMPADDING',(0,0), (-1,-1), 3),
                ('LEFTPADDING',  (0,0), (-1,-1), 6),
                ('BOX',          (0,0), (-1,-1), 0.3, HexColor('#1e293b')),
            ]))
            story.append(sr_tbl)

        # Separador (excepto ultima pagina)
        if i < len(results_with_data) - 1:
            story.append(PageBreak())

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Genera PDF con graficos BUY_CONFIRMATION')
    parser.add_argument('--market',      default=None,
                        help='BYMA | USA | NASDAQ | NYSE | ... (default: todos)')
    parser.add_argument('--cedear',      action='store_true',
                        help='Alias para --market BYMA')
    parser.add_argument('--days',        type=int, default=90,
                        help='Dias de historia para el scan (default: 90)')
    parser.add_argument('--only-fuerte', action='store_true',
                        help='Incluir solo senales FUERTE en el PDF')
    parser.add_argument('--limit',       type=int, default=0,
                        help='Maximo de activos en el PDF (0 = sin limite)')
    parser.add_argument('--output',      default='',
                        help='Nombre del archivo PDF de salida')
    args = parser.parse_args()

    if args.cedear:
        args.market = 'BYMA'

    market_label = args.market or 'Todos'
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    out_path = args.output or f'buy_confirmation_{market_label}_{ts}.pdf'

    print()
    print('=' * 70)
    print('  EXPORT BUY_CONFIRMATION PDF')
    print(f'  Mercado: {market_label}  |  Historia: {args.days} dias')
    print('=' * 70)

    # 1. Bulk fetch
    df_all = fetch_bulk(args.days, args.market)
    if df_all.empty:
        print("Sin datos.")
        return

    n_activos = df_all['accion_id'].nunique()
    print(f"  Activos a procesar: {n_activos:,}")

    # 2. Scan + guardar datos para grafico
    t0 = time.time()
    results_with_data = []

    for i, (aid, grp) in enumerate(df_all.groupby('accion_id', sort=False), 1):
        if i % 200 == 0 or i == n_activos:
            print(f"\r  Escaneando {i:>5}/{n_activos}  "
                  f"candidatos: {len(results_with_data)}", end='', flush=True)
        result, grp_prep, conf, dyn_sup, dyn_res = process_asset(grp)
        if result is None:
            continue
        if not result['activo']:
            continue
        if args.only_fuerte and result['fuerza'] != 'FUERTE':
            continue
        results_with_data.append((result, grp_prep, conf, dyn_sup, dyn_res))

    print(f"\r  Escaneando {n_activos}/{n_activos}  "
          f"candidatos: {len(results_with_data)}  — {time.time()-t0:.1f}s")

    if not results_with_data:
        print("  No se encontraron senales activas.")
        return

    # 3. Ordenar: FUERTE primero, luego fecha desc
    def _date_neg(s):
        try:
            y, m, d = map(int, (s or '0000-01-01').split('-'))
            return -(y * 10000 + m * 100 + d)
        except Exception:
            return 0

    _fuerza_ord = {'FUERTE': 0, 'MEDIA': 1}
    results_with_data.sort(key=lambda x: (
        _fuerza_ord.get(x[0]['fuerza'] or '', 2),
        _date_neg(x[0]['fecha_signal']),
    ))

    # 4. Aplicar limite
    if args.limit > 0:
        results_with_data = results_with_data[:args.limit]
        print(f"  Limitado a {args.limit} activos.")

    # 5. Generar imagenes + PDF
    n = len(results_with_data)
    print(f"\n  Generando {n} graficos y PDF...")
    t1 = time.time()

    pdf_bytes = build_pdf(results_with_data, market_label, args.days)

    # 6. Guardar
    with open(out_path, 'wb') as f:
        f.write(pdf_bytes)

    size_kb = len(pdf_bytes) / 1024
    print(f"  PDF generado: {out_path}  ({size_kb:,.0f} KB)  — {time.time()-t1:.1f}s")
    print()


if __name__ == '__main__':
    main()
