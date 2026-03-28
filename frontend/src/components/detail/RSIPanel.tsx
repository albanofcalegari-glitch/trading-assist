/**
 * RSIPanel — Panel de RSI con visualización de divergencias.
 *
 * Muestra:
 *   - Línea RSI (púrpura)
 *   - Niveles 70 / 50 / 30
 *   - Líneas cortas en RSI conectando los pivotes de cada divergencia
 *   - Marcador en p2 con etiqueta DIV↑ / DIV↓
 */

import { useEffect, useRef } from 'react'
import {
  createChart, ColorType, CrosshairMode, LineStyle,
  type IChartApi,
} from 'lightweight-charts'
import type { Candle } from '@/lib/utils'
import type { Divergence } from '@/lib/divergence'

interface Props {
  candles:     Candle[]
  rsiValues:   (number | null)[]
  divergences: Divergence[]
  height?:     number
}

const BG     = '#0b0d11'
const BORDER = '#1e2535'
const TEXT   = '#7c8ca1'

export default function RSIPanel({ candles, rsiValues, divergences, height = 180 }: Props) {
  const ref      = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!ref.current || !candles.length) return
    if (chartRef.current) { chartRef.current.remove(); chartRef.current = null }

    const el    = ref.current
    const chart = createChart(el, {
      width:     el.clientWidth,
      height,
      watermark: { visible: false },
      layout: {
        background: { type: ColorType.Solid, color: BG },
        textColor:  TEXT,
        fontFamily: 'JetBrains Mono, monospace',
        fontSize:   10,
      },
      grid: {
        vertLines: { color: BORDER, style: 0 },
        horzLines: { color: BORDER, style: 0 },
      },
      crosshair: {
        mode:     CrosshairMode.Normal,
        vertLine: { color: '#334155', labelBackgroundColor: BORDER },
        horzLine: { color: '#334155', labelBackgroundColor: BORDER },
      },
      rightPriceScale: {
        borderColor:  BORDER,
        textColor:    TEXT,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor:    BORDER,
        timeVisible:    true,
        secondsVisible: false,
        tickMarkFormatter: (t: any) => {
          const str = typeof t === 'string' ? t : new Date(t * 1000).toISOString().slice(0, 10)
          const [y, m, d] = str.split('-').map(Number)
          return new Date(y, m - 1, d).toLocaleDateString('es', { day: 'numeric', month: 'short' })
        },
      },
    })
    chartRef.current = chart

    // ── Línea RSI ────────────────────────────────────────────────────────────
    const rsiSeries = chart.addLineSeries({
      color:            '#a78bfa',
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    })

    const rsiData = candles
      .map((c, i) => ({ time: c.fecha as any, value: rsiValues[i] }))
      .filter(p => p.value != null) as { time: any; value: number }[]
    rsiSeries.setData(rsiData)

    // Niveles horizontales
    const levels: [number, string, string][] = [
      [70, 'rgba(239,68,68,0.7)',   'OB'],
      [50, 'rgba(100,116,139,0.5)', '—'],
      [30, 'rgba(34,197,94,0.7)',   'OS'],
    ]
    for (const [price, color, title] of levels) {
      rsiSeries.createPriceLine({ price, color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title })
    }

    // ── Líneas de divergencia sobre RSI ──────────────────────────────────────
    type Marker = { time: any; position: 'belowBar' | 'aboveBar'; color: string; shape: 'arrowUp' | 'arrowDown'; text: string; size: number }
    const markers: Marker[] = []

    for (const div of divergences) {
      const isBullish = div.type === 'BULLISH_DIVERGENCE'
      const color     = isBullish ? 'rgba(34,197,94,0.9)' : 'rgba(239,68,68,0.9)'

      // Línea corta conectando p1 y p2 en el RSI
      const seg = chart.addLineSeries({
        color,
        lineWidth:              2,
        lineStyle:              LineStyle.Solid,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
      })
      seg.setData([
        { time: div.p1.fecha as any, value: div.p1.rsi },
        { time: div.p2.fecha as any, value: div.p2.rsi },
      ])

      // Marcador en p2
      markers.push({
        time:     div.p2.fecha as any,
        position: isBullish ? 'belowBar' : 'aboveBar',
        color,
        shape:    isBullish ? 'arrowUp' : 'arrowDown',
        text:     isBullish ? 'DIV↑' : 'DIV↓',
        size:     1,
      })
    }

    if (markers.length) {
      rsiSeries.setMarkers(markers.sort((a, b) => String(a.time) < String(b.time) ? -1 : 1))
    }

    // ── Responsive ───────────────────────────────────────────────────────────
    const ro = new ResizeObserver(entries => {
      for (const e of entries) chart.applyOptions({ width: e.contentRect.width })
    })
    ro.observe(el)
    chart.timeScale().fitContent()

    return () => { ro.disconnect(); chart.remove(); chartRef.current = null }
  }, [candles, rsiValues, divergences, height])

  return (
    <div className="card p-1 overflow-hidden">
      <p className="text-2xs text-text-muted px-2 pt-1 pb-0.5 font-mono">RSI 14</p>
      <div ref={ref} style={{ height }} className="w-full" />
    </div>
  )
}
