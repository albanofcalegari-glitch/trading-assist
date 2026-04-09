"""
capture_comparison_pdf.py
─────────────────────────
Genera un PDF comparativo:  Gráfico Local  vs  TradingView Live
para cada ticker, en vista semanal, sin soportes ni resistencias.

Usa Playwright para capturar screenshots del frontend (localhost:3000).
"""

import asyncio
import io
import os
import sys
from datetime import datetime

from playwright.async_api import async_playwright
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = 'http://localhost:3000'

# Ticker → accion_id (solo mercados USA, no CEDEARs)
TICKERS = {
    'NVDA':  7827,
    'NU':    7783,
    'GOOGL': 4747,
    'META':  6958,
    'MSFT':  7256,
    'AAPL':  25,
    'YPF':   12243,
}

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')
PDF_NAME = f'comparacion_charts_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf'


# ── Capture ───────────────────────────────────────────────────────────────────

async def capture_charts():
    """Captura screenshots de ambos modos de chart para cada ticker."""
    screenshots = {}  # ticker → { 'local': bytes, 'tv': bytes }

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=[
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--js-flags=--max-old-space-size=2048',
        ])

        for ticker, asset_id in TICKERS.items():
            # Contexto nuevo por ticker para liberar memoria entre capturas
            context = await browser.new_context(
                viewport={'width': 1400, 'height': 900},
                device_scale_factor=1.5,
            )
            page = await context.new_page()

            try:
                print(f'  [{ticker}] Navegando...')
                url = f'{BASE_URL}/asset/{asset_id}'
                await page.goto(url, wait_until='domcontentloaded')

                # Esperar a que cargue el chart (puede tardar por backfill)
                canvas_found = False
                for attempt in range(12):
                    try:
                        await page.wait_for_selector('canvas', timeout=5000)
                        canvas_found = True
                        break
                    except Exception:
                        backfill_text = await page.locator('text=Cargando').count()
                        if backfill_text > 0:
                            print(f'  [{ticker}] backfilling... ({(attempt+1)*5}s)')
                        else:
                            error_text = await page.locator('text=Error').count()
                            no_data = await page.locator('text=Sin datos').count()
                            if error_text or no_data:
                                break
                            print(f'  [{ticker}] esperando render... ({(attempt+1)*5}s)')
                        await page.wait_for_timeout(5000)

                if not canvas_found:
                    print(f'  [{ticker}] SKIP - no se pudo cargar el chart')
                    await context.close()
                    continue

                # ── 1. Gráfico Local + Semanal + Ninguna ──────────────────
                await page.locator('button', has_text='Gráfico local').click()
                await page.wait_for_timeout(300)
                await page.locator('button', has_text='Semanal').click()
                await page.wait_for_timeout(2500)
                await page.locator('button', has_text='Ninguna').click()
                await page.wait_for_timeout(1000)

                # ── 2. Capturar Gráfico local ─────────────────────────────
                chart_container = page.locator('.card.p-1.overflow-hidden').first
                local_png = await chart_container.screenshot(type='png')
                print(f'  [{ticker}] OK local ({len(local_png)//1024} KB)')

                # ── 3. Cambiar a TradingView Live ─────────────────────────
                await page.locator('button', has_text='TradingView Live').click()
                await page.wait_for_timeout(8000)

                tv_png = await chart_container.screenshot(type='png')
                print(f'  [{ticker}] OK TV ({len(tv_png)//1024} KB)')

                screenshots[ticker] = {'local': local_png, 'tv': tv_png}

            except Exception as e:
                print(f'  [{ticker}] ERROR: {e}')
            finally:
                await context.close()

        await browser.close()

    return screenshots


# ── PDF ───────────────────────────────────────────────────────────────────────

def build_pdf(screenshots: dict, output_path: str):
    """Construye el PDF comparativo con ReportLab."""

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=1.2 * cm,
        bottomMargin=1 * cm,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
    )

    # Estilos
    title_style = ParagraphStyle(
        'ChartTitle',
        fontName='Helvetica-Bold',
        fontSize=22,
        textColor=HexColor('#e2e8f0'),
        spaceAfter=6,
        alignment=1,  # center
    )
    subtitle_style = ParagraphStyle(
        'ChartSubtitle',
        fontName='Helvetica',
        fontSize=10,
        textColor=HexColor('#7c8ca1'),
        spaceAfter=4,
        alignment=1,
    )
    label_style = ParagraphStyle(
        'ChartLabel',
        fontName='Helvetica-Bold',
        fontSize=11,
        textColor=HexColor('#b2b5be'),
        spaceBefore=6,
        spaceAfter=3,
    )
    footer_style = ParagraphStyle(
        'Footer',
        fontName='Helvetica',
        fontSize=7,
        textColor=HexColor('#3f4f63'),
        alignment=2,  # right
    )

    page_w = A4[0] - 3 * cm  # ancho disponible
    chart_w = page_w
    chart_h = 10.5 * cm  # altura por chart

    story = []
    tickers_list = list(TICKERS.keys())

    for i, ticker in enumerate(tickers_list):
        data = screenshots[ticker]

        # Título: ticker
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(ticker, title_style))
        story.append(Paragraph('Semanal — Sin soportes ni resistencias', subtitle_style))
        story.append(Spacer(1, 0.3 * cm))

        # Gráfico local
        story.append(Paragraph('Gráfico Local (Claude)', label_style))
        img_local = RLImage(io.BytesIO(data['local']), width=chart_w, height=chart_h)
        img_local.hAlign = 'CENTER'
        story.append(img_local)

        story.append(Spacer(1, 0.4 * cm))

        # Gráfico TradingView
        story.append(Paragraph('TradingView Live', label_style))
        img_tv = RLImage(io.BytesIO(data['tv']), width=chart_w, height=chart_h)
        img_tv.hAlign = 'CENTER'
        story.append(img_tv)

        # Footer
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(
            f'Trading Assist — {datetime.now().strftime("%d/%m/%Y %H:%M")}',
            footer_style,
        ))

        # Page break si no es el último
        if i < len(tickers_list) - 1:
            story.append(PageBreak())

    # Fondo oscuro en todas las páginas
    def draw_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(HexColor('#0b0d11'))
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_bg, onLaterPages=draw_bg)

    # Guardar
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(buf.getvalue())

    print(f'\nOK PDF guardado en: {output_path}')
    return output_path


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    print('Capturando charts...\n')
    screenshots = await capture_charts()

    output_path = os.path.join(OUT_DIR, PDF_NAME)
    build_pdf(screenshots, output_path)


if __name__ == '__main__':
    asyncio.run(main())
