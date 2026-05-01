import { useEffect, useRef } from 'react'
import {
  createChart, ColorType, LineStyle,
  type IChartApi,
} from 'lightweight-charts'
import type { Candle } from '@/lib/utils'
import type { ElliottWavePoint, ElliottFibLevel } from '@/lib/api'

const COLORS = {
  bg:      '#131722',
  border:  '#2a2e39',
  grid:    '#1e222d',
  text:    '#b2b5be',
  up:      '#26a69a',
  down:    '#ef5350',
  volUp:   'rgba(38,166,154,0.45)',
  volDown: 'rgba(239,83,80,0.45)',
  zigzag:  '#60a5fa',
  fibRetrace: '#fbbf24',
  fibTarget:  '#22c55e',
}

const WAVE_COLORS: Record<string, string> = {
  '0': '#9ca3af',
  '1': '#22c55e',
  '2': '#ef4444',
  '3': '#22c55e',
  '4': '#ef4444',
  '5': '#22c55e',
  'A': '#f97316',
  'B': '#f97316',
  'C': '#f97316',
}

interface Props {
  candles:       Candle[]
  waves:         ElliottWavePoint[]
  fibLevels:     ElliottFibLevel[]
  fibTargets:    ElliottFibLevel[]
  zigzagPivots:  { fecha: string; price: number; type: 'high' | 'low' }[]
  height?:       number
}

export default function ElliottChart({
  candles, waves, fibLevels, fibTargets, zigzagPivots, height = 500,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el || candles.length === 0) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const chart = createChart(el, {
      width:  el.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor: COLORS.text,
        fontFamily: "'DM Sans', sans-serif",
        fontSize:   11,
      },
      grid: {
        vertLines: { color: 'rgba(42,46,57,0.15)' },
        horzLines: { color: 'rgba(42,46,57,0.15)' },
      },
      crosshair: {
        horzLine: { color: '#758696', labelBackgroundColor: '#2a2e39' },
        vertLine: { color: '#758696', labelBackgroundColor: '#2a2e39' },
      } as any,
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: false,
        tickMarkFormatter: (time: any) => {
          const date = new Date(time)
          return date.toLocaleDateString('es', { day: 'numeric', month: 'short' })
        },
      },
    })

    chartRef.current = chart

    // Hide TradingView logo
    const hideLogo = () => {
      el.querySelectorAll('a').forEach(a => {
        if (a.href?.includes('tradingview')) (a as HTMLElement).style.display = 'none'
      })
    }
    hideLogo()
    setTimeout(hideLogo, 200)

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor:          COLORS.up,
      downColor:        COLORS.down,
      borderUpColor:    COLORS.up,
      borderDownColor:  COLORS.down,
      wickUpColor:      COLORS.up,
      wickDownColor:    COLORS.down,
      priceLineVisible: true,
      lastValueVisible: true,
    })

    candleSeries.setData(candles.map(c => ({
      time:  c.fecha as any,
      open:  Number(c.open),
      high:  Number(c.high),
      low:   Number(c.low),
      close: Number(c.close),
      color:       Number(c.close) >= Number(c.open) ? COLORS.up : COLORS.down,
      wickColor:   Number(c.close) >= Number(c.open) ? COLORS.up : COLORS.down,
      borderColor: Number(c.close) >= Number(c.open) ? COLORS.up : COLORS.down,
    })))

    // Volume
    const volSeries = chart.addHistogramSeries({
      priceFormat:      { type: 'volume' },
      priceScaleId:     'vol',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0.0 },
    })
    volSeries.setData(candles.map(c => ({
      time:  c.fecha as any,
      value: Number(c.volume),
      color: Number(c.close) >= Number(c.open) ? COLORS.volUp : COLORS.volDown,
    })))

    // Zigzag line
    if (zigzagPivots.length >= 2) {
      const zigzagSeries = chart.addLineSeries({
        color:                  COLORS.zigzag,
        lineWidth:              2,
        lineStyle:              LineStyle.Solid,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
      })
      const candleDates = new Set(candles.map(c => c.fecha))
      const zigzagData = zigzagPivots
        .filter(p => candleDates.has(p.fecha))
        .map(p => ({
          time:  p.fecha as any,
          value: p.price,
        }))
      if (zigzagData.length >= 2) {
        zigzagSeries.setData(zigzagData)
      }
    }

    // Wave markers
    if (waves.length > 0) {
      const candleDates = new Set(candles.map(c => c.fecha))
      const markers = waves
        .filter(w => candleDates.has(w.fecha))
        .map(w => {
          const isImpulseUp = ['1', '3', '5'].includes(w.label)
          const isCorrection = ['A', 'B', 'C'].includes(w.label)
          const position = isImpulseUp || w.label === 'B'
            ? 'aboveBar' as const
            : 'belowBar' as const

          return {
            time:     w.fecha as any,
            position,
            color:    WAVE_COLORS[w.label] || '#9ca3af',
            shape:    'circle' as const,
            text:     w.label === '0' ? '' : w.label,
            size:     w.label === '0' ? 0 : 1,
          }
        })
        .filter(m => m.size > 0)
        .sort((a, b) => (a.time < b.time ? -1 : 1))

      if (markers.length > 0) {
        candleSeries.setMarkers(markers)
      }
    }

    // Fibonacci levels (retracement)
    for (const fib of fibLevels) {
      candleSeries.createPriceLine({
        price:           fib.price,
        color:           COLORS.fibRetrace,
        lineWidth:       1,
        lineStyle:       LineStyle.Dashed,
        axisLabelVisible: true,
        title:           fib.label,
      })
    }

    // Fibonacci targets
    for (const fib of fibTargets) {
      candleSeries.createPriceLine({
        price:           fib.price,
        color:           COLORS.fibTarget,
        lineWidth:       1,
        lineStyle:       LineStyle.Dotted,
        axisLabelVisible: true,
        title:           fib.label,
      })
    }

    chart.timeScale().fitContent()

    // Resize observer
    const ro = new ResizeObserver(entries => {
      const { width: w } = entries[0].contentRect
      chart.applyOptions({ width: w })
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [candles, waves, fibLevels, fibTargets, zigzagPivots, height])

  return <div ref={containerRef} className="w-full rounded-lg overflow-hidden" />
}
