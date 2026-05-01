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
  kind:  'BUY' | 'SELL' | 'PIVOT_LOW' | 'PIVOT_HIGH'
  price: number
}

export interface DotMarker {
  fecha: string
  value: number
  color: string
}

// Zona de soporte/resistencia: banda horizontal entre `floor` y `top`, dibujada
// con 2 priceLines (nativas de lightweight-charts).  Se usa para mostrar
// lateralizaciones detectadas por dynamic_supports (short tier horizontal).
export interface PriceZone {
  floor: number
  top:   number
  color: string
  label: string
  // V2 visual tier extensions
  borderColor?:  string
  floorWidth?:   number
  topWidth?:     number
  floorStyle?:   'solid' | 'dashed' | 'dotted'
  topStyle?:     'solid' | 'dashed' | 'dotted'
  labelVisible?: boolean
}

// Nivel horizontal dibujado por el usuario. Se renderiza como priceLine nativa.
export interface UserPriceLevel {
  id:    number
  price: number
  kind:  'support' | 'resistance' | 'target' | 'note'
  label: string | null
}

// Paleta por kind. Match con los presets del popover en AssetDetail.
const USER_LEVEL_COLORS: Record<UserPriceLevel['kind'], string> = {
  support:    '#22c55e',
  resistance: '#ef4444',
  target:     '#eab308',
  note:       '#94a3b8',
}

// Trendline (polyline de N puntos, N>=2) dibujada por el usuario.
// Se renderiza como LineSeries con N puntos consecutivos.
export interface UserTrendline {
  id:     number
  points: { t: string; p: number }[]   // ordenados por t ascendente
  kind:   UserPriceLevel['kind']
  label:  string | null
}

// Punto en coordenadas del chart para el preview en vivo durante el dibujo.
export interface DrawPreviewPoint {
  time:  string   // 'YYYY-MM-DD'
  price: number
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  candles:       Candle[]
  freq:          'D' | 'W' | 'M'
  indicators:    IndicatorLine[]
  markers?:      ChartMarker[]
  dotLayers?:    DotMarker[][]
  zones?:        PriceZone[]
  userLevels?:   UserPriceLevel[]
  userTrendlines?: UserTrendline[]
  // Modo dibujo: cuando está activo, cada clic izquierdo sobre el chart
  // dispara onDrawPoint con (time, price). AssetDetail acumula puntos y
  // crea la trendline cuando el usuario pulsa "Trazar".
  drawMode?:     boolean
  onDrawPoint?:  (args: { time: string; price: number }) => void
  // Puntos en progreso (N>=0). Se renderiza un LineSeries preview separado
  // para mostrar el polyline que se está dibujando.
  drawPreview?:  DrawPreviewPoint[]
  // Color del preview (coincide con kind elegido en AssetDetail).
  drawPreviewColor?: string
  // Callback cuando el usuario hace click-derecho sobre el chart.
  // Recibe el precio del clic (convertido desde Y) y las coords absolutas del
  // mouse para posicionar el popover. Si no se pasa, el click-derecho nativo
  // del browser queda habilitado.
  onContextMenu?: (args: { price: number; clientX: number; clientY: number }) => void
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
  dotLayers,
  zones,
  userLevels,
  userTrendlines,
  drawMode,
  onDrawPoint,
  drawPreview,
  drawPreviewColor,
  onContextMenu,
  height = 550,
  viewStartDate,
}: Props) {
  const containerRef  = useRef<HTMLDivElement>(null)
  const chartRef      = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const overlayRef    = useRef<ISeriesApi<'Line'>[]>([])
  const trendlinePoolRef = useRef<ISeriesApi<'Line'>[]>([])
  const drawPreviewSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const dotSeriesPoolRef = useRef<ISeriesApi<'Line'>[]>([])
  const chartDatesRef = useRef<Set<string>>(new Set())
  const chartDataRef  = useRef<Candle[]>([])
  const priceLinesRef = useRef<IPriceLine[]>([])
  const userLinesRef  = useRef<IPriceLine[]>([])
  const viewStartRef  = useRef<string | undefined>(viewStartDate)
  const onContextMenuRef = useRef(onContextMenu)
  const drawModeRef    = useRef<boolean>(!!drawMode)
  const onDrawPointRef = useRef(onDrawPoint)
  useLayoutEffect(() => { onContextMenuRef.current = onContextMenu }, [onContextMenu])
  useLayoutEffect(() => { drawModeRef.current    = !!drawMode }, [drawMode])
  useLayoutEffect(() => { onDrawPointRef.current = onDrawPoint }, [onDrawPoint])
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
    chartDataRef.current  = data

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

    // ── Trendline pool: pre-creado para que crear/borrar no altere layout ────
    const TRENDLINE_POOL_SIZE = 20
    const tlPool: ISeriesApi<'Line'>[] = []
    for (let i = 0; i < TRENDLINE_POOL_SIZE; i++) {
      tlPool.push(chart.addLineSeries({
        color:                  '#3b82f6',
        lineWidth:              2,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
        visible:                false,
        autoscaleInfoProvider:  () => ({ priceRange: null }),
      } as any))
    }
    trendlinePoolRef.current = tlPool

    // ── Preview series: polyline que se está dibujando en drawMode ───────────
    // Usa líneas discontinuas + markers visibles para diferenciar del trazo final.
    drawPreviewSeriesRef.current = chart.addLineSeries({
      color:                  '#3b82f6',
      lineWidth:              2,
      lineStyle:              LineStyle.Dashed,
      priceLineVisible:       false,
      lastValueVisible:       false,
      crosshairMarkerVisible: false,
      pointMarkersVisible:    true,
      pointMarkersRadius:     4,
      visible:                false,
      autoscaleInfoProvider:  () => ({ priceRange: null }),
    } as any)

    // ── Dot markers pool: hasta 3 series para puntos de contacto por tier ─────
    const DOT_POOL_SIZE = 6
    const dotPool: ISeriesApi<'Line'>[] = []
    for (let i = 0; i < DOT_POOL_SIZE; i++) {
      dotPool.push(chart.addLineSeries({
        color:                  '#ff00ff',
        lineVisible:            false,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
        pointMarkersVisible:    true,
        pointMarkersRadius:     5,
        visible:                false,
        autoscaleInfoProvider:  () => ({ priceRange: null }),
      } as any))
    }
    dotSeriesPoolRef.current = dotPool

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

    // ── Context menu (click-derecho): crear nivel a la altura clickeada ──────
    const onContextMenuEvt = (ev: MouseEvent) => {
      const cb = onContextMenuRef.current
      if (!cb) return
      const cs = candleSeriesRef.current
      if (!cs) return
      const rect = el.getBoundingClientRect()
      const y = ev.clientY - rect.top
      const price = cs.coordinateToPrice(y)
      if (price == null) return
      ev.preventDefault()
      cb({ price: Number(price), clientX: ev.clientX, clientY: ev.clientY })
    }
    el.addEventListener('contextmenu', onContextMenuEvt)

    // ── Click izquierdo en modo dibujo: captura (time, price) ────────────────
    // Se usa subscribeClick de lightweight-charts (integra con su time scale).
    // Sólo dispara cuando drawMode está activo. El propio drag del chart no
    // genera 'click' así que la funcionalidad de pan queda intacta.
    const onChartClick = (param: any) => {
      if (!drawModeRef.current) return
      const cb = onDrawPointRef.current
      if (!cb) return
      if (!param || !param.point || param.time == null) return
      const cs = candleSeriesRef.current
      if (!cs) return
      const price = cs.coordinateToPrice(param.point.y)
      if (price == null) return
      // param.time puede ser string ('YYYY-MM-DD') o BusinessDay
      let timeStr: string | null = null
      if (typeof param.time === 'string') {
        timeStr = param.time
      } else if (param.time && typeof param.time === 'object' && 'year' in param.time) {
        const bd = param.time as { year: number; month: number; day: number }
        timeStr = `${bd.year}-${String(bd.month).padStart(2, '0')}-${String(bd.day).padStart(2, '0')}`
      }
      if (!timeStr) return
      cb({ time: timeStr, price: Number(price) })
    }
    chart.subscribeClick(onChartClick)

    // ── Responsive ────────────────────────────────────────────────────────────
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) chart.applyOptions({ width: entry.contentRect.width })
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      el.removeEventListener('dblclick', onDblClick)
      el.removeEventListener('mousedown', onMouseDown)
      el.removeEventListener('contextmenu', onContextMenuEvt)
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup',   onMouseUp)
      try { chart.unsubscribeClick(onChartClick) } catch {}
      if (zoomBox.parentNode) zoomBox.parentNode.removeChild(zoomBox)
      chart.remove()
      chartRef.current = null
      candleSeriesRef.current = null
      overlayRef.current = []
      trendlinePoolRef.current = []
      drawPreviewSeriesRef.current = null
      userLinesRef.current = []
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
    const seen = new Set<string>()
    const out = markers
      .map(m => {
        const time = snap(m.fecha)
        if (!time) return null
        const key = `${time}_${m.kind}`
        if (seen.has(key)) return null
        seen.add(key)
        if (m.kind === 'PIVOT_LOW') {
          return {
            time: time as any,
            position: 'belowBar' as const,
            color: '#00e676',
            shape: 'circle' as const,
            text: m.price.toFixed(2),
            size: 0.5,
          }
        }
        if (m.kind === 'PIVOT_HIGH') {
          return {
            time: time as any,
            position: 'aboveBar' as const,
            color: '#ff1744',
            shape: 'circle' as const,
            text: m.price.toFixed(2),
            size: 0.5,
          }
        }
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
    out.sort((a, b) => (a.time < b.time ? -1 : 1))
    cs.setMarkers(out)
  }, [markers, candles, freq])

  // ── Effect dot layers: puntos de contacto en precio exacto, uno por tier ──
  useEffect(() => {
    const pool = dotSeriesPoolRef.current
    if (!pool.length) return
    const validDates = chartDatesRef.current
    const sortedDates = Array.from(validDates).sort()
    const snap = (fecha: string): string | null => {
      if (validDates.has(fecha)) return fecha
      for (const d of sortedDates) if (d >= fecha) return d
      return null
    }
    for (let i = 0; i < pool.length; i++) {
      const layer = dotLayers && dotLayers[i]
      if (!layer || !layer.length) {
        pool[i].applyOptions({ visible: false } as any)
        pool[i].setData([])
        continue
      }
      const seen = new Map<string, number>()
      for (const dm of layer) {
        const snapped = snap(dm.fecha)
        if (!snapped) continue
        if (!seen.has(snapped)) seen.set(snapped, dm.value)
      }
      const mapped = Array.from(seen.entries())
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .map(([time, value]) => ({ time: time as any, value }))
      if (!mapped.length) {
        pool[i].applyOptions({ visible: false } as any)
        pool[i].setData([])
        continue
      }
      pool[i].applyOptions({ visible: true, color: layer[0].color } as any)
      pool[i].setData(mapped)
    }
  }, [dotLayers, candles, freq])

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
    const styleMap = { solid: LineStyle.Solid, dashed: LineStyle.Dashed, dotted: LineStyle.Dotted }
    for (const z of zones) {
      const bc = z.borderColor ?? z.color
      const floorW = z.floorWidth ?? 2
      const topW = z.topWidth ?? 1
      const floorS = z.floorStyle ? (styleMap[z.floorStyle] ?? LineStyle.Solid) : LineStyle.Solid
      const topS = z.topStyle ? (styleMap[z.topStyle] ?? LineStyle.Dotted) : LineStyle.Dotted
      const showLabel = z.labelVisible !== false
      priceLinesRef.current.push(cs.createPriceLine({
        price:            z.floor,
        color:            bc,
        lineWidth:        floorW,
        lineStyle:        floorS,
        axisLabelVisible: showLabel,
        title:            showLabel ? z.label : '',
      } as any))
      priceLinesRef.current.push(cs.createPriceLine({
        price:            z.top,
        color:            bc,
        lineWidth:        topW,
        lineStyle:        topS,
        axisLabelVisible: false,
        title:            '',
      } as any))
    }
  }, [zones, candles, freq])

  // ── Effect userLevels: priceLines horizontales del usuario (color por kind) ─
  // Se recrean en cada cambio de userLevels/candles/freq. Independientes de
  // las zones automáticas del sistema.
  useEffect(() => {
    const cs = candleSeriesRef.current
    if (!cs) return
    for (const pl of userLinesRef.current) {
      try { cs.removePriceLine(pl) } catch {}
    }
    userLinesRef.current = []
    if (!userLevels || !userLevels.length) return
    for (const lvl of userLevels) {
      const color = USER_LEVEL_COLORS[lvl.kind] || '#94a3b8'
      const title = lvl.label && lvl.label.trim()
        ? lvl.label.trim()
        : ({ support: 'Soporte', resistance: 'Resistencia', target: 'Target', note: 'Nota' }[lvl.kind])
      userLinesRef.current.push(cs.createPriceLine({
        price:            lvl.price,
        color,
        lineWidth:        2,
        lineStyle:        lvl.kind === 'note' ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
        title,
      } as any))
    }
  }, [userLevels, candles, freq])

  // ── Effect userTrendlines: polyline de N>=2 puntos usando el pool ───────
  // Snap de cada punto a la fecha de vela más cercana >= (mismo esquema que
  // markers). Puntos con la misma fecha post-snap se colapsan (se queda el
  // último), garantizando que lightweight-charts acepte la serie ordenada.
  useEffect(() => {
    const pool = trendlinePoolRef.current
    if (!pool.length) return
    const validDates = chartDatesRef.current
    const sortedDates = Array.from(validDates).sort()
    const snap = (fecha: string): string | null => {
      if (validDates.has(fecha)) return fecha
      for (const d of sortedDates) if (d >= fecha) return d
      return null
    }
    for (let i = 0; i < pool.length; i++) {
      const tl = userTrendlines && userTrendlines[i]
      if (!tl || !tl.points || tl.points.length < 2) {
        pool[i].applyOptions({ visible: false } as any)
        pool[i].setData([])
        continue
      }
      const mapped: { time: any; value: number }[] = []
      const seen = new Map<string, number>()
      for (const pt of tl.points) {
        const snapped = snap(pt.t)
        if (!snapped) continue
        seen.set(snapped, pt.p)
      }
      const keys = Array.from(seen.keys()).sort()
      for (const k of keys) mapped.push({ time: k as any, value: seen.get(k)! })
      if (mapped.length < 2) {
        pool[i].applyOptions({ visible: false } as any)
        pool[i].setData([])
        continue
      }
      const color = USER_LEVEL_COLORS[tl.kind] || '#3b82f6'
      pool[i].applyOptions({ color, visible: true } as any)
      pool[i].setData(mapped)
    }
  }, [userTrendlines, candles, freq])

  // ── Effect drawPreview: polyline en vivo mientras el usuario está dibujando
  useEffect(() => {
    const s = drawPreviewSeriesRef.current
    if (!s) return
    if (!drawMode || !drawPreview || drawPreview.length === 0) {
      s.applyOptions({ visible: false } as any)
      s.setData([])
      return
    }
    const validDates = chartDatesRef.current
    const sortedDates = Array.from(validDates).sort()
    const snap = (fecha: string): string | null => {
      if (validDates.has(fecha)) return fecha
      for (const d of sortedDates) if (d >= fecha) return d
      return null
    }
    const seen = new Map<string, number>()
    for (const pt of drawPreview) {
      const snapped = snap(pt.time)
      if (!snapped) continue
      seen.set(snapped, pt.price)
    }
    const keys = Array.from(seen.keys()).sort()
    const mapped = keys.map(k => ({ time: k as any, value: seen.get(k)! }))
    const color = drawPreviewColor || '#3b82f6'
    if (mapped.length === 0) {
      s.applyOptions({ visible: false } as any)
      s.setData([])
      return
    }
    // Con 1 solo punto, LineSeries igual acepta: se ve como un marker
    s.applyOptions({ color, visible: true } as any)
    s.setData(mapped)
  }, [drawMode, drawPreview, drawPreviewColor, candles, freq])

  // ── Effect 2: Update overlay data/visibility (never add/remove series) ────
  useEffect(() => {
    const pool = overlayRef.current
    if (!pool.length) return

    // Use dates in the chart's candle series + any future dates (projection)
    const validDates = chartDatesRef.current
    const lastChartDate = chartDataRef.current.length
      ? chartDataRef.current[chartDataRef.current.length - 1].fecha
      : ''

    for (let i = 0; i < pool.length; i++) {
      if (i < indicators.length) {
        const ind = indicators[i]
        const lineData = ind.dates
          .map((d, j) => ({ time: d as any, value: ind.values[j] }))
          .filter(p => p.value != null && (validDates.has(p.time as string) || p.time > lastChartDate)) as { time: any; value: number }[]
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
      style={{ height, cursor: drawMode ? 'crosshair' : undefined }}
      className="w-full rounded-md overflow-hidden"
      title={drawMode
        ? 'Modo dibujo activo — clic en 2 puntos para crear una trendline'
        : 'Scroll: pan horizontal · Rueda: zoom · Ctrl+arrastrar: zoom a región · Doble click: reset'}
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
