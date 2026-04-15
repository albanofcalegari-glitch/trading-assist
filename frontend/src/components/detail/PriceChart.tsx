import { useEffect, useRef, useLayoutEffect } from 'react'
import {
  createChart, ColorType, LineStyle, PriceScaleMode,
  type IChartApi, type ISeriesApi, type CandlestickSeriesOptions,
  type IPriceLine,
} from 'lightweight-charts'
import { calcWMA, calcSMA, resampleOHLCV, type Candle } from '@/lib/utils'

interface IndicatorLine {
  dates:  string[]
  values: (number | null)[]
  color:  string
  label:  string
}

export interface ChartMarker {
  fecha: string
  kind:  'BUY' | 'SELL'
  price: number
}

// Zona de soporte/resistencia: banda horizontal entre `floor` y `top`, dibujada
// con 2 priceLines (nativas de lightweight-charts).  Se usa para mostrar
// lateralizaciones detectadas por dynamic_supports (short tier horizontal).
export interface PriceZone {
  floor: number
  top:   number
  color: string
  label: string
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  candles:       Candle[]
  freq:          'D' | 'W' | 'M'
  indicators:    IndicatorLine[]
  markers?:      ChartMarker[]
  zones?:        PriceZone[]
  height?:       number
  // Fecha (YYYY-MM-DD) desde la que mostrar el chart por default.
  // Si está definida y existe en los datos, reemplaza el DEFAULT_BARS.
  viewStartDate?: string
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
  markers,
  zones,
  height = 550,
  viewStartDate,
}: Props) {
  const containerRef  = useRef<HTMLDivElement>(null)
  const chartRef      = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const overlayRef    = useRef<ISeriesApi<'Line'>[]>([])
  const chartDatesRef = useRef<Set<string>>(new Set())
  const priceLinesRef = useRef<IPriceLine[]>([])
  const viewStartRef  = useRef<string | undefined>(viewStartDate)
  // Sincroniza el ref con el prop (para que onDblClick y el reset usen el valor vigente)
  useLayoutEffect(() => { viewStartRef.current = viewStartDate }, [viewStartDate])

  // ── Effect 1: Chart lifecycle (candles, freq, height) ─────────────────────
  useEffect(() => {
    if (!containerRef.current || !candles.length) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }
    overlayRef.current = []

    const el = containerRef.current

    const data = freq === 'D' ? candles
               : freq === 'W' ? resampleOHLCV(candles, 'W')
               :                resampleOHLCV(candles, 'M')

    // Store chart dates so Effect 2 can filter overlays to matching dates only
    chartDatesRef.current = new Set(data.map(c => c.fecha))

    const chart = createChart(el, {
      width:  el.clientWidth,
      height,
      watermark: { visible: false },
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor:  COLORS.text,
        fontFamily: "'Trebuchet MS', Arial, sans-serif",
        fontSize:   12,
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
        mode:         PriceScaleMode.Logarithmic,
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
          if (tickMarkType === 0) return String(date.getFullYear())
          if (freq === 'M') return date.toLocaleDateString('es', { month: 'short', year: '2-digit' })
          if (freq === 'W') return date.toLocaleDateString('es', { month: 'short' })
          if (tickMarkType === 1) return date.toLocaleDateString('es', { month: 'short' })
          return date.toLocaleDateString('es', { day: 'numeric', month: 'short' })
        },
      },
    })

    chartRef.current = chart

    // Fallback: hide TradingView logo
    const hideLogo = () => {
      el.querySelectorAll('a').forEach(a => {
        if (a.href.includes('tradingview')) (a as HTMLElement).style.display = 'none'
      })
    }
    hideLogo()
    setTimeout(hideLogo, 200)

    // ── Velas ─────────────────────────────────────────────────────────────────
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
    candleSeriesRef.current = candleSeries

    // ── Volumen ───────────────────────────────────────────────────────────────
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

    // ── Overlay pool: series pre-creadas, nunca se agregan ni eliminan ────────
    // Esto garantiza que toggle de canales/indicadores no altere el layout.
    const POOL_SIZE = 28
    const pool: ISeriesApi<'Line'>[] = []
    for (let i = 0; i < POOL_SIZE; i++) {
      pool.push(chart.addLineSeries({
        color:                  '#ffffff',
        lineWidth:              1,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
        visible:                false,
        autoscaleInfoProvider:  () => ({ priceRange: null }),
      } as any))
    }
    overlayRef.current = pool

    // ── Vista por defecto según timeframe ─────────────────────────────────────
    // Si hay viewStartDate y existe en `data`, se usa como borde izquierdo (mismo
    // comportamiento que el PDF: mostrar desde anchor1 del soporte largo plazo).
    const DEFAULT_BARS = freq === 'W' ? 250 : freq === 'M' ? 120 : 365
    const computeRange = (): { from: number; to: number } | null => {
      const vsd = viewStartRef.current
      if (vsd) {
        const idx = data.findIndex(c => c.fecha >= vsd)
        if (idx >= 0) return { from: idx - 0.5, to: data.length - 1 + 15 }
      }
      if (data.length > DEFAULT_BARS) {
        return { from: data.length - DEFAULT_BARS - 0.5, to: data.length - 1 + 15 }
      }
      return null
    }
    const applyDefaultView = () => {
      const r = computeRange()
      if (r) chart.timeScale().setVisibleLogicalRange(r)
      else chart.timeScale().fitContent()
    }
    applyDefaultView()

    // ── Doble click: reset a la vista por defecto ─────────────────────────────
    const onDblClick = () => applyDefaultView()
    el.addEventListener('dblclick', onDblClick)

    // ── Region zoom (Ctrl+drag) ──────────────────────────────────────────────
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
      candleSeriesRef.current = null
      overlayRef.current = []
    }
  }, [candles, freq, height])

  // ── Effect 1b: pan del chart cuando llega tarde viewStartDate (dynSupports) ─
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !viewStartDate || !candles.length) return
    const data = freq === 'D' ? candles
               : freq === 'W' ? resampleOHLCV(candles, 'W')
               :                resampleOHLCV(candles, 'M')
    const idx = data.findIndex(c => c.fecha >= viewStartDate)
    if (idx < 0) return
    chart.timeScale().setVisibleLogicalRange({
      from: idx - 0.5,
      to:   data.length - 1 + 15,
    })
  }, [viewStartDate, freq, candles])

  // ── Effect markers: BUY/SELL labels estilo TradingView ────────────────────
  // Se filtran a fechas que existen en las velas actuales (tras resample) para
  // que lightweight-charts no las rechace. Si una señal cae dentro de un bucket
  // W/M, se snapea al próximo bar cuya fecha sea ≥ la señal.
  useEffect(() => {
    const cs = candleSeriesRef.current
    if (!cs) return
    if (!markers || !markers.length) {
      cs.setMarkers([])
      return
    }
    const validDates = chartDatesRef.current
    const sortedDates = Array.from(validDates).sort()
    const snap = (fecha: string): string | null => {
      if (validDates.has(fecha)) return fecha
      // busca la primera fecha de vela >= fecha de la señal
      for (const d of sortedDates) if (d >= fecha) return d
      return null
    }
    const out = markers
      .map(m => {
        const time = snap(m.fecha)
        if (!time) return null
        return {
          time: time as any,
          position: (m.kind === 'BUY' ? 'belowBar' : 'aboveBar') as 'belowBar' | 'aboveBar',
          color:    m.kind === 'BUY' ? '#26a69a' : '#ef5350',
          shape:    (m.kind === 'BUY' ? 'arrowUp' : 'arrowDown') as 'arrowUp' | 'arrowDown',
          text:     m.kind,
          size:     1,
        }
      })
      .filter(Boolean) as any[]
    // lightweight-charts pide markers ordenados por tiempo
    out.sort((a, b) => (a.time < b.time ? -1 : 1))
    cs.setMarkers(out)
  }, [markers, candles, freq])

  // ── Effect zones: banda horizontal (piso + tope) via priceLines nativas ──
  // Se limpian y recrean en cada cambio de zones/candles/freq.  priceLines
  // son horizontales infinitas sobre el eje X y tienen label en el eje Y.
  useEffect(() => {
    const cs = candleSeriesRef.current
    if (!cs) return
    for (const pl of priceLinesRef.current) {
      try { cs.removePriceLine(pl) } catch {}
    }
    priceLinesRef.current = []
    if (!zones || !zones.length) return
    for (const z of zones) {
      priceLinesRef.current.push(cs.createPriceLine({
        price:            z.floor,
        color:            z.color,
        lineWidth:        2,
        lineStyle:        LineStyle.Solid,
        axisLabelVisible: true,
        title:            `${z.label} piso`,
      } as any))
      priceLinesRef.current.push(cs.createPriceLine({
        price:            z.top,
        color:            z.color,
        lineWidth:        1,
        lineStyle:        LineStyle.Dotted,
        axisLabelVisible: true,
        title:            `${z.label} tope`,
      } as any))
    }
  }, [zones, candles, freq])

  // ── Effect 2: Update overlay data/visibility (never add/remove series) ────
  useEffect(() => {
    const pool = overlayRef.current
    if (!pool.length) return

    // Only use dates that exist in the chart's candle series (weekly/monthly)
    // to avoid expanding the time scale with daily data points
    const validDates = chartDatesRef.current

    for (let i = 0; i < pool.length; i++) {
      if (i < indicators.length) {
        const ind = indicators[i]
        const lineData = ind.dates
          .map((d, j) => ({ time: d as any, value: ind.values[j] }))
          .filter(p => p.value != null && validDates.has(p.time as string)) as { time: any; value: number }[]
        pool[i].applyOptions({ color: ind.color, visible: true } as any)
        pool[i].setData(lineData)
      } else {
        pool[i].applyOptions({ visible: false } as any)
        pool[i].setData([])
      }
    }
  }, [indicators])

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
