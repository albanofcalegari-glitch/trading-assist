"""
generate_sr_pdf.py — Genera PDF con soportes y resistencias dinámicas (V2)
para una lista de tickers.

Uso:
    python scripts/generate_sr_pdf.py AAPL TSLA MELI ...
    python scripts/generate_sr_pdf.py  # usa lista default
"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from strategies.dynamic_supports import get_dynamic_supports
from strategies.dynamic_resistances import get_dynamic_resistances


DEFAULT_TICKERS = ['AAPL', 'MELI', 'OKLO', 'TSLA', 'AMD', 'MCD', 'V', 'SPY', 'UBER']

COLOR_GREEN  = HexColor('#16a34a')
COLOR_RED    = HexColor('#dc2626')
COLOR_ORANGE = HexColor('#ea580c')
COLOR_CYAN   = HexColor('#0891b2')
COLOR_GRAY   = HexColor('#64748b')
COLOR_BG_ALT = HexColor('#f1f5f9')
COLOR_BG_HDR = HexColor('#1e293b')
COLOR_WHITE  = HexColor('#ffffff')
COLOR_BLACK  = HexColor('#0f172a')


def _fmt(v, decimals=2):
    if v is None:
        return '—'
    return f'${v:,.{decimals}f}'


def _pct(v):
    if v is None:
        return '—'
    sign = '+' if v >= 0 else ''
    return f'{sign}{v:.2f}%'


def _status_color(status):
    if status == 'ACTIVE':
        return COLOR_GREEN
    if status == 'TESTING':
        return COLOR_ORANGE
    if status == 'BROKEN':
        return COLOR_RED
    return COLOR_GRAY


def _build_tier_row(tier_name, tier_data, role):
    """Arma una fila [tier, kind, valor, distancia, status, slope_anual]."""
    if tier_data is None:
        return [tier_name.upper(), '—', '—', '—', '—', '—']
    kind = tier_data.get('kind', 'descending' if role == 'R' else 'ascending')
    kind_label = {
        'ascending': 'Diagonal ↗',
        'descending': 'Diagonal ↘',
        'horizontal': 'Horizontal →',
    }.get(kind, kind)
    return [
        tier_name.upper(),
        kind_label,
        _fmt(tier_data.get('current_value')),
        _pct(tier_data.get('distance_pct')),
        tier_data.get('status', '—'),
        _pct(tier_data.get('slope_annual_pct')),
    ]


def generate_pdf(tickers: list[str], output_path: str, fecha: date | None = None):
    fecha = fecha or date.today()
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle', parent=styles['Title'],
        fontSize=18, textColor=COLOR_BLACK, spaceAfter=2*mm,
    )
    subtitle_style = ParagraphStyle(
        'Subtitle', parent=styles['Normal'],
        fontSize=10, textColor=COLOR_GRAY, spaceAfter=6*mm,
    )
    ticker_style = ParagraphStyle(
        'Ticker', parent=styles['Heading2'],
        fontSize=14, textColor=COLOR_BLACK, spaceBefore=4*mm, spaceAfter=2*mm,
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Heading3'],
        fontSize=10, spaceAfter=1*mm,
    )
    note_style = ParagraphStyle(
        'Note', parent=styles['Normal'],
        fontSize=7, textColor=COLOR_GRAY, spaceBefore=1*mm,
    )

    story = []
    story.append(Paragraph('Soportes y Resistencias V2', title_style))
    story.append(Paragraph(
        f'Generado el {fecha.strftime("%d/%m/%Y")} — Trading Assist',
        subtitle_style,
    ))

    col_widths = [22*mm, 28*mm, 30*mm, 22*mm, 22*mm, 26*mm]
    headers = ['Tier', 'Tipo', 'Valor', 'Dist %', 'Status', 'Slope/Año']

    header_style_cell = ParagraphStyle(
        'HeaderCell', parent=styles['Normal'],
        fontSize=8, textColor=COLOR_WHITE, leading=10,
    )
    cell_style_normal = ParagraphStyle(
        'CellNormal', parent=styles['Normal'],
        fontSize=8, textColor=COLOR_BLACK, leading=10,
    )

    for sym in tickers:
        elements = []
        elements.append(Paragraph(f'{sym}', ticker_style))

        # Soportes
        try:
            sup = get_dynamic_supports(sym, fecha)
            price = sup.get('price')
            tf = sup.get('timeframe_used', '?')
        except Exception:
            sup = None
            price = None
            tf = '?'

        elements.append(Paragraph(
            f'<font color="#16a34a"><b>SOPORTES</b></font>'
            f'  <font color="#64748b" size="7">(tf={tf}, precio={_fmt(price)})</font>',
            section_style,
        ))

        sup_rows = [headers]
        for tier_name in ('Long', 'Mid', 'Short'):
            tier = sup.get(tier_name.lower()) if sup else None
            sup_rows.append(_build_tier_row(tier_name, tier, 'S'))

        t = Table(sup_rows, colWidths=col_widths)
        t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_BG_HDR),
            ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_WHITE),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.4, COLOR_GRAY),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [COLOR_WHITE, COLOR_BG_ALT]),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]
        # Color status cells
        for row_idx in range(1, len(sup_rows)):
            status = sup_rows[row_idx][4]
            t_style.append(('TEXTCOLOR', (4, row_idx), (4, row_idx), _status_color(status)))
            t_style.append(('FONTNAME', (4, row_idx), (4, row_idx), 'Helvetica-Bold'))

        t.setStyle(TableStyle(t_style))
        elements.append(t)
        elements.append(Spacer(1, 3*mm))

        # Resistencias
        try:
            res = get_dynamic_resistances(sym, fecha)
            price_r = res.get('price')
            tf_r = res.get('timeframe_used', '?')
        except Exception:
            res = None
            price_r = None
            tf_r = '?'

        elements.append(Paragraph(
            f'<font color="#dc2626"><b>RESISTENCIAS</b></font>'
            f'  <font color="#64748b" size="7">(tf={tf_r}, precio={_fmt(price_r)})</font>',
            section_style,
        ))

        res_rows = [headers]
        for tier_name in ('Long', 'Mid', 'Short'):
            tier = res.get(tier_name.lower()) if res else None
            res_rows.append(_build_tier_row(tier_name, tier, 'R'))

        t2 = Table(res_rows, colWidths=col_widths)
        t2_style = list(t_style)  # reuse base style
        t2_style[0] = ('BACKGROUND', (0, 0), (-1, 0), HexColor('#7f1d1d'))
        for row_idx in range(1, len(res_rows)):
            status = res_rows[row_idx][4]
            t2_style.append(('TEXTCOLOR', (4, row_idx), (4, row_idx), _status_color(status)))
            t2_style.append(('FONTNAME', (4, row_idx), (4, row_idx), 'Helvetica-Bold'))

        t2.setStyle(TableStyle(t2_style))
        elements.append(t2)

        # Nota si hay breakout
        if res:
            for tier_name in ('short', 'mid', 'long'):
                tier = res.get(tier_name)
                if tier and isinstance(tier, dict):
                    dist = tier.get('distance_pct', -99)
                    if 0 < dist <= 5:
                        sl = round(tier['current_value'] * 0.95, 2)
                        tp = round(tier['current_value'] * 1.10, 2)
                        elements.append(Paragraph(
                            f'<font color="#dc2626"><b>BREAKOUT {tier_name.upper()}</b></font> '
                            f'Precio rompio resistencia (+{dist:.1f}%). '
                            f'SL: {_fmt(sl)} (-5%) | TP: {_fmt(tp)} (+10%)',
                            note_style,
                        ))
                        break

        elements.append(Spacer(1, 6*mm))
        story.append(KeepTogether(elements))

    # Footer
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        '<font color="#94a3b8" size="7">'
        'Disclaimer: Este reporte es informativo y no constituye asesoramiento financiero. '
        'Los niveles de soporte y resistencia son estimaciones basadas en datos historicos. '
        'Operar en mercados financieros implica riesgo de perdida.</font>',
        styles['Normal'],
    ))

    doc.build(story)
    return output_path


if __name__ == '__main__':
    tickers = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_TICKERS
    out = os.path.join(os.path.dirname(__file__), '..', f'SR_Report_{date.today().isoformat()}.pdf')
    out = os.path.abspath(out)
    generate_pdf(tickers, out)
    print(f'PDF generado: {out}')
