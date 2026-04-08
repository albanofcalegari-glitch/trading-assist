import { useEffect, useRef } from 'react'
import {
  createChart, ColorType, LineStyle, PriceScaleMode,
  type IChartApi, type CandlestickSeriesOptions,
} from 'lightweight-charts'
import { calcWMA, calcSMA, resampleOHLCV, type Candle } from '@/lib/utils'

interface IndicatorLine {
  dates:  string[]
  values: (number | null)[]
  color:  string
  label:  string
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  candles:    Candle[]
  freq:       'D' | 'W' | 'M'
  indicators: IndicatorLine[]
  height?:    number
}

// Colores exactos TradingView dark theme
const COLORS = {
  bg:      '#131722',
  border:  '#2a2e39',
  grid:    '#1e222d',
  text:    '#b2b5be',
  up:      '#26a69a',
  down:    '#ef5350',
  volUp:   'rgba(38,166,154,0.45)',
  volDown: 'rgba(239,83,80,0.45)',
  xhair:   '#758696',
}

// ── Componente ────────────────────────────────────────────────────────────────

export default function PriceChart({
  candles, freq, indicators,
  height = 550,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current || !candles.length) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const el = containerRef.current

    // Resample según temporalidad desde datos diarios (ohlcv_extended D = 20 años).
    // D: sin resample. W: agrega diario→semanal. M: agrega diario→mensual.
    const data = freq === 'D' ? candles
               : freq === 'W' ? resampleOHLCV(candles, 'W')
               :                resampleOHLCV(candles, 'M')

    // ── Chart — opciones idénticas al look TradingView dark ───────────────────
    const chart = createChart(el, {
      width:  el.clientWidth,
      height,
      watermark: { visible: false },
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor:  COLORS.text,
        fontFamily: "'Trebuchet MS', Arial, sans-serif",
        fontSize:   12,
        // Oculta el logo de TradingView en versiones recientes de lightweight-charts.
        // Si la versión instalada no lo soporta, el fallback DOM-hide más abajo lo cubre.
        attributionLogo: false,
      } as any,
      grid: {
        vertLines: { color: 'rgba(42,46,57,0.15)' },
        horzLines: { color: 'rgba(42,46,57,0.15)' },
      },
      crosshair: {
        mode: 0,
        vertLine: {
          color:                COLORS.xhair,
          width:                1,
          style:                LineStyle.Solid,
          labelBackgroundColor: COLORS.border,
        },
        horzLine: {
          color:                COLORS.xhair,
          width:                1,
          style:                LineStyle.Solid,
          labelBackgroundColor: COLORS.border,
        },
      },
      // Scroll horizontal con rueda + drag con click; zoom con rueda y pinch
      handleScroll: {
        mouseWheel:           true,
        pressedMouseMove:     true,
        horzTouchDrag:        true,
        vertTouchDrag:        true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel:           true,
        pinch:                true,
      },
      rightPriceScale: {
        autoScale:    true,
        borderVisible: false,
        textColor:    COLORS.text,
        mode:         PriceScaleMode.Normal,
        scaleMargins: { top: 0.02, bottom: 0.02 },
      },
      timeScale: {
        borderColor:           COLORS.border,
        timeVisible:           false,
        secondsVisible:        false,
        rightBarStaysOnScroll: true,
        rightOffset:           12,
        barSpacing:            7,
        fixLeftEdge:           true,
        tickMarkFormatter: (t: any, tickMarkType: number) => {
          const str = typeof t === 'string' ? t : new Date(t * 1000).toISOString().slice(0, 10)
          const [y, m, d] = str.split('-').map(Number)
          const date = new Date(y, m - 1, d)
          // tickMarkType: 0=Year 1=Month 2=DayOfMonth 3=Time
          if (tickMarkType === 0) return String(date.getFullYear())
          if (freq === 'M') return date.toLocaleDateString('es', { month: 'short', year: '2-digit' })
          if (freq === 'W') return date.toLocaleDateString('es', { month: 'short' })
          if (tickMarkType === 1) return date.toLocaleDateString('es', { month: 'short' })
          return date.toLocaleDateString('es', { day: 'numeric', month: 'short' })
        },
      },
    })

    chartRef.current = chart

    // Fallback: en versiones viejas de lightweight-charts attributionLogo no existe
    // y el logo se inyecta como <a href="tradingview...">. Lo ocultamos por DOM.
    const hideLogo = () => {
      el.querySelectorAll('a').forEach(a => {
        if (a.href.includes('tradingview')) (a as HTMLElement).style.display = 'none'
      })
    }
    hideLogo()
    setTimeout(hideLogo, 200)

    // ── Velas — colores exactos TradingView ───────────────────────────────────
    const candleSeries = chart.addCandlestickSeries({
      upColor:          COLORS.up,
      downColor:        COLORS.down,
      borderUpColor:    COLORS.up,
      borderDownColor:  COLORS.down,
      wickUpColor:      COLORS.up,
      wickDownColor:    COLORS.down,
      priceLineVisible: true,
      lastValueVisible: true,
    } as Partial<CandlestickSeriesOptions>)

    const ohlcData = data.map(c => {
      const open  = Number(c.open)
      const close = Number(c.close)
      const isUp  = close >= open
      return {
        time:        c.fecha as any,
        open,
        high:        Number(c.high),
        low:         Number(c.low),
        close,
        color:       isUp ? COLORS.up : COLORS.down,
        wickColor:   isUp ? COLORS.up : COLORS.down,
        borderColor: isUp ? COLORS.up : COLORS.down,
      }
    })

    candleSeries.setData(ohlcData)

    // ── Volumen — histograma en la zona inferior (18%) ─────────────────────────
    const volSeries = chart.addHistogramSeries({
      priceFormat:      { type: 'volume' },
      priceScaleId:     'vol',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0.0 },
    })
    volSeries.setData(data.map(c => ({
      time:  c.fecha as any,
      value: Number(c.volume),
      color: Number(c.close) >= Number(c.open) ? COLORS.volUp : COLORS.volDown,
    })))

    // Helper: line series excluida del autoscale (solo las velas mandan en el eje Y)
    const addOverlay = (opts: Parameters<typeof chart.addLineSeries>[0]) =>
      chart.addLineSeries({
        ...opts,
        autoscaleInfoProvider: () => ({ priceRange: null }),
      } as any)

    // ── Indicadores (WMA, SMA, etc.) ──────────────────────────────────────────
    for (const ind of indicators) {
      const series = addOverlay({
        color:                  ind.color,
        lineWidth:              1,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
      })
      const lineData = ind.dates
        .map((d, i) => ({ time: d as any, value: ind.values[i] }))
        .filter(p => p.value != null) as { time: any; value: number }[]
      series.setData(lineData)
    }

    // ── Vista por defecto según timeframe ─────────────────────────────────────
    //   D → 365   (~1.5 años de diario)
    //   W → 250   (~5 años de semanal)
    //   M → 120   (~10 años de mensual)
    const DEFAULT_BARS = freq === 'W' ? 250 : freq === 'M' ? 120 : 365
    if (data.length > DEFAULT_BARS) {
      chart.timeScale().setVisibleLogicalRange({
        from: data.length - DEFAULT_BARS - 0.5,
        to:   data.length - 1 + 15,
      })
    } else {
      chart.timeScale().fitContent()
    }

    // ── Doble click: reset a la vista por defecto ─────────────────────────────
    const onDblClick = () => {
      if (data.length > DEFAULT_BARS) {
        chart.timeScale().setVisibleLogicalRange({
          from: data.length - DEFAULT_BARS - 0.5,
          to:   data.length - 1 + 15,
        })
      } else {
        chart.timeScale().fitContent()
      }
    }
    el.addEventListener('dblclick', onDblClick)

    // ── Region zoom (Ctrl+drag, estilo TradingView) ──────────────────────────
    // Drag horizontal con Ctrl presionado define un rango temporal a hacer zoom.
    // Se dibuja un overlay translúcido sobre el chart durante el drag.
    el.style.position = 'relative'
    const zoomBox = document.createElement('div')
    Object.assign(zoomBox.style, {
      position:        'absolute',
      top:             '0',
      bottom:          '0',
      left:            '0',
      width:           '0',
      pointerEvents:   'none',
      background:      'rgba(91,108,246,0.15)',
      borderLeft:      '1px solid rgba(91,108,246,0.7)',
      borderRight:     '1px solid rgba(91,108,246,0.7)',
      display:         'none',
      zIndex:          '5',
    })
    el.appendChild(zoomBox)

    let dragStartX:        number | null = null
    let dragStartLogical:  number | null = null

    const onMouseDown = (ev: MouseEvent) => {
      if (!ev.ctrlKey && !ev.metaKey) return
      const rect = el.getBoundingClientRect()
      const x    = ev.clientX - rect.left
      const logical = chart.timeScale().coordinateToLogical(x)
      if (logical == null) return
      dragStartX       = x
      dragStartLogical = logical
      zoomBox.style.left    = `${x}px`
      zoomBox.style.width   = '0px'
      zoomBox.style.display = 'block'
      ev.preventDefault()
      ev.stopPropagation()
    }

    const onMouseMove = (ev: MouseEvent) => {
      if (dragStartX == null) return
      const rect = el.getBoundingClientRect()
      const x    = ev.clientX - rect.left
      const left  = Math.min(dragStartX, x)
      const width = Math.abs(x - dragStartX)
      zoomBox.style.left  = `${left}px`
      zoomBox.style.width = `${width}px`
    }

    const onMouseUp = (ev: MouseEvent) => {
      if (dragStartX == null || dragStartLogical == null) {
        zoomBox.style.display = 'none'
        return
      }
      const rect = el.getBoundingClientRect()
      const x    = ev.clientX - rect.left
      const endLogical = chart.timeScale().coordinateToLogical(x)
      zoomBox.style.display = 'none'

      if (endLogical != null && Math.abs(x - dragStartX) > 5) {
        const from = Math.min(dragStartLogical, endLogical)
        const to   = Math.max(dragStartLogical, endLogical)
        if (to - from >= 1) {
          chart.timeScale().setVisibleLogicalRange({ from, to })
        }
      }
      dragStartX       = null
      dragStartLogical = null
    }

    el.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup',   onMouseUp)

    // ── Responsive ────────────────────────────────────────────────────────────
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) chart.applyOptions({ width: entry.contentRect.width })
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      el.removeEventListener('dblclick', onDblClick)
      el.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup',   onMouseUp)
      if (zoomBox.parentNode) zoomBox.parentNode.removeChild(zoomBox)
      chart.remove()
      chartRef.current = null
    }
  }, [candles, freq, indicators, height])

  return (
    <div
      ref={containerRef}
      style={{ height }}
      className="w-full rounded-md overflow-hidden"
      title="Scroll: pan horizontal · Rueda: zoom · Ctrl+arrastrar: zoom a región · Doble click: reset"
    />
  )
}

// ── buildIndicatorLines ───────────────────────────────────────────────────────

export function buildIndicatorLines(
  candles: Candle[],
  strategy: string | string[],
): IndicatorLine[] {
  if (!candles.length) return []

  const strategies = Array.isArray(strategy) ? strategy : [strategy]
  const dates  = candles.map(c => c.fecha)
  const closes = candles.map(c => Number(c.close))
  const linesMap = new Map<string, IndicatorLine>()

  const add = (line: IndicatorLine) => {
    if (!linesMap.has(line.label)) linesMap.set(line.label, line)
  }

  for (const s of strategies) {
    if (s === 'WMA6 / WMA30 — Swing' || s === 'BUY_EARLY_SWING — Anticipado') {
      add({ label: 'WMA 6',  dates, values: calcWMA(closes, 6),  color: '#4f79e8' })
      add({ label: 'WMA 30', dates, values: calcWMA(closes, 30), color: '#f59e0b' })
    }

    if (s === 'WMA21 / SMA30 — Tendencia media' || s === 'BUY_CONFIRMATION') {
      add({ label: 'WMA 21', dates, values: calcWMA(closes, 21), color: '#4f79e8' })
      add({ label: 'SMA 30', dates, values: calcSMA(closes, 30), color: '#a78bfa' })
    }

    if (s === 'BUY_CONFIRMATION' || s === 'BUY_EARLY_SWING — Anticipado') {
      add({ label: 'SMA 50',  dates, values: calcSMA(closes, 50),  color: '#22c55e' })
      add({ label: 'SMA 200', dates, values: calcSMA(closes, 200), color: '#ef4444' })
    }
  }

  return Array.from(linesMap.values())
}
