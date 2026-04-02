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

export type TrendlineStatus =
  | 'ACTIVE_SUPPORT'
  | 'TESTING_SUPPORT'
  | 'BROKEN_SUPPORT'
  | 'NO_VALID_ACTIVE_SUPPORT'
  | 'ACTIVE_RESISTANCE'
  | 'TESTING_RESISTANCE'
  | 'BROKEN_RESISTANCE'
  | 'NO_VALID_ACTIVE_RESISTANCE'

interface TrendlineResult {
  line:   { fecha: string; value: number }[]
  pivots: { fecha: string; value: number }[]
  meta?:  {
    status:         TrendlineStatus
    slopeLog?:      number
    projectedToday?: number
    distancePct?:   number
    signedDistPct?: number
  }
}

export interface LongtermSupportLayer {
  line_points:     { fecha: string; value: number }[]
  status:          string   // 'ACTIVE' | 'TESTING' | 'BROKEN' | 'NO_SUPPORT'
  timeframe_used?: string
}

export interface HorizontalZoneData {
  zone_low:        number
  zone_high:       number
  center:          number
  total_touches:   number
  recent_touches:  number
  score:           number
  type:            'support' | 'resistance'
  rank:            'primary' | 'secondary' | 'tertiary'
}

function addMonths(dateStr: string, n: number): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  const dt = new Date(y, m - 1 + n, Math.min(d, 28))
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
}

// ── Soporte / Resistencia dinámica ───────────────────────────────────────────
//
// Recta matemática en escala logarítmica definida por 2 pivotes estructurales.
// Evaluación exhaustiva de todos los pares. Selección por score compuesto.
//
// Score = gap(25%) + growth(25%) + exact_touches(20%) + near_touches(15%) + proximity(15%)

function findBestTrendline(
  candles: Candle[],
  type: 'support' | 'resistance',
  tfLabel: string,
): TrendlineResult {
  const noValid: TrendlineStatus = type === 'support' ? 'NO_VALID_ACTIVE_SUPPORT' : 'NO_VALID_ACTIVE_RESISTANCE'
  const finalLabel = type === 'support' ? 'FINAL SUPPORT' : 'FINAL RESISTANCE'

  const n = candles.length
  if (n < 10) return { line: [], pivots: [], meta: { status: noValid } }

  interface Pivot { idx: number; fecha: string; value: number; significance: number }

  // ── 1. Pivot estructurales WIN=2 ──────────────────────────────────────────
  // low[i] < low[i-1], low[i-2], low[i+1], low[i+2]  (obligatorio)
  const WIN = 2
  const raw: { idx: number; fecha: string; value: number }[] = []
  for (let i = WIN; i < n - WIN; i++) {
    if (type === 'support') {
      const v = Number(candles[i].low)
      if (v <= 0) continue
      const left  = candles.slice(i - WIN, i).every(c => Number(c.low) >= v)
      const right = candles.slice(i + 1, i + WIN + 1).every(c => Number(c.low) >= v)
      if (left && right) raw.push({ idx: i, fecha: candles[i].fecha, value: v })
    } else {
      const v = Number(candles[i].high)
      if (v <= 0) continue
      const left  = candles.slice(i - WIN, i).every(c => Number(c.high) <= v)
      const right = candles.slice(i + 1, i + WIN + 1).every(c => Number(c.high) <= v)
      if (left && right) raw.push({ idx: i, fecha: candles[i].fecha, value: v })
    }
  }

  // ── 2. Filtro de significancia ≥5% en 6 barras ───────────────────────────
  const MIN_MOVE   = 0.05
  const LOOK_AHEAD = 6
  const field      = type === 'support' ? 'low' : 'high'
  const pivots: Pivot[] = []

  console.groupCollapsed(`[${type.toUpperCase()}] pivots — ${raw.length} raw detected`)
  for (const p of raw) {
    const slice = candles.slice(p.idx + 1, Math.min(p.idx + LOOK_AHEAD + 1, n))
    if (slice.length < 2) {
      console.log(`[pivot] ${p.fecha}  ${field}=${p.value}  valid=false  reason=near_edge`)
      continue
    }
    const sig = type === 'support'
      ? Math.max(...slice.map(c => Number(c.high))) / p.value - 1
      : 1 - Math.min(...slice.map(c => Number(c.low))) / p.value
    const valid = sig >= MIN_MOVE
    console.log(
      `[pivot] ${p.fecha}  ${field}=${p.value}  valid=${valid}  significance=${(sig * 100).toFixed(1)}%` +
      (!valid ? '  ← DISCARDED' : '')
    )
    if (valid) pivots.push({ ...p, significance: sig })
  }
  console.groupEnd()

  if (pivots.length < 2) {
    console.log(`[${finalLabel}]\n  timeframe=${tfLabel}\n  status=${noValid}\n  reason=insufficient_pivots`)
    return { line: [], pivots: [], meta: { status: noValid } }
  }

  // ── 3. Evaluar TODOS los pares (p1, p2) ──────────────────────────────────
  const VIOL_TOL       = 0.012   // 1.2% tolerancia zona de definición
  const BREAK_TOL      = 0.050   // 5%   soporte roto
  const EXACT_TOL      = 0.010   // 1%   toque exacto
  const NEAR_TOL       = 0.030   // 3%   toque cercano
  const MIN_GAP        = 40      // MÍNIMO 40 barras entre p1 y p2 (semanal ≈ 10 meses)
  const MIN_AFTER      = Math.max(3, Math.floor(n * 0.05))
  const MIN_LOG_GROWTH = 0.08    // 8% crecimiento mínimo p1→p2
  const MAX_DIST_PRICE = 0.20    // rechazar si línea está >20% del precio actual
  const PEN_DIST_PRICE = 0.12    // penalizar si >12%

  const currentPrice = Number(candles[n - 1].close)
  const tNow         = n - 1

  interface Candidate {
    p1: Pivot; p2: Pivot
    logSlope: number; logInter: number
    growth: number; gap: number
    exactTouches: number; nearTouches: number
    projectedNow: number; distancePct: number
    score: number
  }
  const candidates: Candidate[] = []

  console.groupCollapsed(`[${type.toUpperCase()}] pair evaluation`)
  for (let b = 1; b < pivots.length; b++) {
    const p2 = pivots[b]
    if (n - 1 - p2.idx < MIN_AFTER) continue

    for (let a = 0; a < b; a++) {
      const p1  = pivots[a]
      const gap = p2.idx - p1.idx
      if (gap < MIN_GAP) continue
      if (type === 'support' && p2.value <= p1.value) continue

      // ── Log-space slope ───────────────────────────────────────────────────
      // m = (log(p2) - log(p1)) / (t2 - t1)
      // b = log(p1) - m * t1
      const logSlope       = (Math.log(p2.value) - Math.log(p1.value)) / gap
      const logInter       = Math.log(p1.value) - logSlope * p1.idx
      const totalLogGrowth = Math.abs(logSlope) * gap
      const growth         = Math.exp(logSlope * gap) - 1

      const lbl = `p1=${p1.fecha} $${p1.value}  p2=${p2.fecha} $${p2.value}  growth=${(growth * 100).toFixed(1)}%  time_gap=${gap}bars`

      // A. Crecimiento mínimo
      if (type === 'support' && totalLogGrowth < MIN_LOG_GROWTH) {
        console.log(`[line candidate] ${lbl}\n  status=REJECTED  reason=slope_too_flat`)
        continue
      }

      // B. Continuidad zona de definición (pivotes entre p1 y p2)
      let defBreaker = ''
      for (const p of pivots) {
        if (p.idx <= p1.idx || p.idx >= p2.idx) continue
        const lv = Math.exp(logSlope * p.idx + logInter)
        if (type === 'support'    && p.value < lv * (1 - VIOL_TOL)) { defBreaker = `${p.fecha} $${p.value}`; break }
        if (type === 'resistance' && p.value > lv * (1 + VIOL_TOL)) { defBreaker = `${p.fecha} $${p.value}`; break }
      }
      if (defBreaker) {
        console.log(`[line candidate] ${lbl}\n  status=REJECTED  reason=def_zone_violated_by=${defBreaker}`)
        continue
      }

      // C. Vigente: no roto post-p2 + contar toques exactos/cercanos
      let breaker      = ''
      let exactTouches = 0
      let nearTouches  = 0
      for (const p of pivots) {
        if (p.idx <= p2.idx) continue
        const lv   = Math.exp(logSlope * p.idx + logInter)
        const dist = Math.abs(p.value - lv) / lv
        if (type === 'support') {
          if (p.value < lv * (1 - BREAK_TOL))  { breaker = `${p.fecha} $${p.value}`; break }
          if (dist <= EXACT_TOL)                  exactTouches++
          else if (dist <= NEAR_TOL && p.value >= lv) nearTouches++
        } else {
          if (p.value > lv * (1 + BREAK_TOL))  { breaker = `${p.fecha} $${p.value}`; break }
          if (dist <= EXACT_TOL)                  exactTouches++
          else if (dist <= NEAR_TOL && p.value <= lv) nearTouches++
        }
      }
      if (breaker) {
        console.log(`[line candidate] ${lbl}\n  status=BROKEN  reason=broken_at=${breaker}`)
        continue
      }

      // D. Proximidad al precio actual
      // projected_today = exp(m * t_now + b)
      const projectedNow = Math.exp(logSlope * tNow + logInter)
      const distancePct  = Math.abs(currentPrice - projectedNow) / currentPrice

      if (distancePct > MAX_DIST_PRICE) {
        console.log(`[line candidate] ${lbl}\n  projected_today=$${projectedNow.toFixed(2)}  distance=${(distancePct * 100).toFixed(1)}%\n  status=REJECTED  reason=too_far_from_price (>${(MAX_DIST_PRICE * 100).toFixed(0)}%)`)
        continue
      }

      // E. Score compuesto
      // gap(40%) + growth(25%) + exact_touches(15%) + near_touches(10%) + proximity(10%)
      const gapScore       = Math.min(gap, 100) / 100   // normalizado hasta 100 barras
      const growthScore    = Math.min(totalLogGrowth, 0.50) / 0.50
      const exactScore     = Math.min(exactTouches, 5) / 5
      const nearScore      = Math.min(nearTouches, 5) / 5
      const proximityScore = distancePct <= PEN_DIST_PRICE
        ? 1.0
        : Math.max(0, 1 - (distancePct - PEN_DIST_PRICE) / (MAX_DIST_PRICE - PEN_DIST_PRICE))
      const score = gapScore * 0.40 + growthScore * 0.25 + exactScore * 0.15 + nearScore * 0.10 + proximityScore * 0.10

      console.log(
        `[line candidate] ${lbl}\n` +
        `  bars_between=${gap}  exact_touches=${exactTouches}  near_touches=${nearTouches}\n` +
        `  projected_today=$${projectedNow.toFixed(2)}  distance=${(distancePct * 100).toFixed(1)}%\n` +
        `  score=${score.toFixed(3)}  status=ACTIVE_${type.toUpperCase()}`
      )

      candidates.push({
        p1, p2, logSlope, logInter, growth, gap,
        exactTouches, nearTouches, projectedNow, distancePct, score,
      })
    }
  }
  console.groupEnd()

  if (candidates.length === 0) {
    console.log(`[${finalLabel}]\n  timeframe=${tfLabel}\n  status=${noValid}\n  reason=no_valid_candidates`)
    return { line: [], pivots: [], meta: { status: noValid } }
  }

  // ── 4. Ordenar por score y mostrar ranking ────────────────────────────────
  candidates.sort((x, y) => y.score - x.score)

  console.groupCollapsed(`[${type.toUpperCase()}] candidate ranking (${candidates.length} valid)`)
  candidates.forEach((c, i) => {
    const tag = i === 0 ? `★ BEST_ACTIVE_${type.toUpperCase()}` : `  #${i + 1}`
    console.log(
      `${tag}\n` +
      `  p1=${c.p1.fecha} $${c.p1.value}  p2=${c.p2.fecha} $${c.p2.value}\n` +
      `  bars_between=${c.gap}  growth=${(c.growth * 100).toFixed(1)}%\n` +
      `  exact_touches=${c.exactTouches}  near_touches=${c.nearTouches}\n` +
      `  projected_today=$${c.projectedNow.toFixed(2)}  distance_to_price=${(c.distancePct * 100).toFixed(1)}%\n` +
      `  status=ACTIVE_${type.toUpperCase()}  score=${c.score.toFixed(3)}`
    )
  })
  console.groupEnd()

  const best = candidates[0]

  // ── 5. Continuidad de higher lows (soporte) ───────────────────────────────
  if (type === 'support') {
    const seq = pivots.filter(p => p.idx >= best.p1.idx)
    if (seq.length >= 3) {
      let rising = 0
      for (let i = 1; i < seq.length; i++) {
        if (seq[i].value > seq[i - 1].value) rising++
      }
      const ratio = rising / (seq.length - 1)
      if (ratio < 0.5) {
        console.log(`[${finalLabel}]\n  timeframe=${tfLabel}\n  status=${noValid}\n  reason=higher_lows_continuity=${(ratio * 100).toFixed(0)}%<50%`)
        return { line: [], pivots: [], meta: { status: noValid } }
      }
    }
  }

  // ── 6. Clasificación de estado ────────────────────────────────────────────
  // distance_pct = (current_price - projected_today) / projected_today
  // > +5%  → ACTIVE   (precio sobre la línea, soporte vigente)
  // ±5%    → TESTING  (precio tocando la línea)
  // < -5%  → BROKEN   (precio bajo la línea, soporte roto)
  const { p1, p2, logSlope, logInter, growth, gap, exactTouches, nearTouches, projectedNow, distancePct, score } = best

  const signedDistPct = type === 'support'
    ? (currentPrice - projectedNow) / projectedNow          // + arriba, - abajo
    : (projectedNow - currentPrice) / projectedNow          // + debajo, - encima

  const trendStatus: TrendlineStatus = (() => {
    if (type === 'support') {
      if (signedDistPct >  0.05) return 'ACTIVE_SUPPORT'
      if (signedDistPct >= -0.05) return 'TESTING_SUPPORT'
      return 'BROKEN_SUPPORT'
    } else {
      if (signedDistPct >  0.05) return 'ACTIVE_RESISTANCE'
      if (signedDistPct >= -0.05) return 'TESTING_RESISTANCE'
      return 'BROKEN_RESISTANCE'
    }
  })()

  // ── 7. [FINAL SUPPORT / RESISTANCE] ──────────────────────────────────────
  const brokenMeta = { slopeLog: logSlope, projectedToday: projectedNow, distancePct, signedDistPct, status: trendStatus }

  console.log(
    `[${finalLabel}]\n` +
    `  timeframe=${tfLabel}\n` +
    `  status=${trendStatus}\n` +
    `  p1=${p1.fecha} $${p1.value}\n` +
    `  p2=${p2.fecha} $${p2.value}\n` +
    `  signed_dist_pct=${(signedDistPct * 100).toFixed(1)}%\n` +
    `  projected_today=$${projectedNow.toFixed(2)}\n` +
    `  score=${score.toFixed(3)}`
  )

  // BROKEN: no dibujar línea — devuelve meta para que la UI muestre el estado
  if (trendStatus === 'BROKEN_SUPPORT' || trendStatus === 'BROKEN_RESISTANCE') {
    return { line: [], pivots: [], meta: brokenMeta }
  }

  // ── 7. Render: price(t) = exp(m·t + b) ───────────────────────────────────
  // En escala logarítmica esta función es una recta perfecta.
  const line: { fecha: string; value: number }[] = []
  for (let i = p1.idx; i < n + 20; i++) {
    const value = Math.exp(logSlope * i + logInter)
    if (!isFinite(value) || value <= 0) continue
    const fecha = i < n
      ? candles[i].fecha
      : addMonths(candles[n - 1].fecha, i - n + 1)
    line.push({ fecha, value: Math.round(value * 100) / 100 })
  }

  return {
    line,
    pivots: [p1, p2].map(p => ({ fecha: p.fecha, value: p.value })),
    meta:   { slopeLog: logSlope, projectedToday: projectedNow, distancePct, signedDistPct, status: trendStatus },
  }
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  candles:              Candle[]
  freq:                 'D' | 'W' | 'M'
  indicators:           IndicatorLine[]
  showTrendline?:       boolean
  showResistanceTrend?: boolean
  debugSegmentOnly?:    boolean
  height?:              number
  onTrendlineResult?:   (support: TrendlineStatus | null, resistance: TrendlineStatus | null) => void
  // Capas de soporte/resistencia estructural desde ohlcv_extended (motor longterm_support.py)
  longtermLayer?:           LongtermSupportLayer | null
  longtermResistanceLayer?: LongtermSupportLayer | null
  midtermLayer?:            LongtermSupportLayer | null
  shorttermLayer?:          LongtermSupportLayer | null
  // Capas activas (ultimos 7 anos)
  activeLayer?:             LongtermSupportLayer | null
  activeResistanceLayer?:   LongtermSupportLayer | null
  // Zonas horizontales de soporte/resistencia
  horizontalZones?:         HorizontalZoneData[] | null
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
  showTrendline = true, showResistanceTrend = true,
  debugSegmentOnly = false,
  height = 550,
  onTrendlineResult,
  longtermLayer           = null,
  longtermResistanceLayer = null,
  midtermLayer            = null,
  shorttermLayer          = null,
  activeLayer             = null,
  activeResistanceLayer   = null,
  horizontalZones         = null,
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
      },
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
        mouseWheel:      true,
        pressedMouseMove: true,
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

    // Ocultar logo de TradingView (lightweight-charts lo inyecta como <a>)
    const hideLogo = () => {
      el.querySelectorAll('a').forEach(a => {
        if (a.href.includes('tradingview')) (a as HTMLElement).style.display = 'none'
      })
    }
    hideLogo()
    setTimeout(hideLogo, 200)   // fallback por si lo inyecta de forma asíncrona

    // ── Velas — colores exactos TradingView ───────────────────────────────────
    // Color definido SOLO por close >= open (regla estándar japonesa).
    // Se fuerza color/wickColor/borderColor por barra para no depender de
    // la lógica interna de la versión de lightweight-charts instalada.
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

    // ── Volumen — histograma en la zona inferior (20%) ─────────────────────────
    const volSeries = chart.addHistogramSeries({
      priceFormat:      { type: 'volume' },
      priceScaleId:     'vol',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    // El volumen ocupa solo el 18% inferior del chart (top: 0.82)
    chart.priceScale('vol').applyOptions({
      scaleMargins: { top: 0.82, bottom: 0.0 },
    })
    volSeries.setData(data.map(c => ({
      time:  c.fecha as any,
      value: Number(c.volume),
      color: Number(c.close) >= Number(c.open) ? COLORS.volUp : COLORS.volDown,
    })))

    // Helper: crea line series EXCLUIDA del autoscale (solo las velas lo controlan)
    // Retornar { priceRange: null } le dice a LW charts "no contribuyo al rango Y"
    // (≠ retornar null, que significa "usá el default" y SÍ afecta el eje Y)
    // Se pasa en las creation options para que aplique desde el primer render.
    const addOverlay = (opts: Parameters<typeof chart.addLineSeries>[0]) =>
      chart.addLineSeries({
        ...opts,
        autoscaleInfoProvider: () => ({ priceRange: null }),
      } as any)

    // ── Soporte / Resistencia dinámica ───────────────────────────────────────
    type Marker = { time: any; position: 'belowBar' | 'aboveBar'; color: string; shape: 'circle'; text: string; size: number }
    const allMarkers: Marker[] = []

    // Calcular ambas trendlines primero para poder notificar el estado al padre
    const tfLabel = freq === 'W' ? 'Semanal' : freq === 'M' ? 'Mensual' : 'Diario'
    const tl = showTrendline       ? findBestTrendline(data, 'support',    tfLabel) : null
    const tr = showResistanceTrend ? findBestTrendline(data, 'resistance', tfLabel) : null
    onTrendlineResult?.(tl?.meta?.status ?? null, tr?.meta?.status ?? null)

    if (showTrendline && tl) {
      // Sin recorte: usar todo el histórico disponible.
      // El gap mínimo (40 barras) y la proximidad al precio actual
      // garantizan relevancia estructural sin necesidad de filtrar por fecha.

      if (tl.line.length >= 2 && tl.pivots.length === 2) {
        const [pv1, pv2] = tl.pivots

        // debugSegmentOnly: solo segmento p1→p2 sin extensión
        const lineData = debugSegmentOnly
          ? tl.line.filter(p => p.fecha >= pv1.fecha && p.fecha <= pv2.fecha)
          : tl.line

        // Dump en consola de los puntos renderizados
        if (lineData.length > 0) {
          const m = tl.meta
          console.log(
            `[RENDER SUPPORT]\n` +
            `  p1=${pv1.fecha} $${pv1.value}\n` +
            `  p2=${pv2.fecha} $${pv2.value}\n` +
            (m ? `  status=${m.status}\n` +
                 (m.slopeLog      != null ? `  slope_log=${m.slopeLog.toFixed(6)}\n` : '') +
                 (m.projectedToday != null ? `  projected_today=$${m.projectedToday.toFixed(2)}\n` : '') +
                 (m.signedDistPct  != null ? `  signed_dist_pct=${(m.signedDistPct * 100).toFixed(1)}%\n` : '') : '') +
            `  first_rendered=${lineData[0].fecha} $${lineData[0].value}\n` +
            `  last_rendered=${lineData[lineData.length - 1].fecha} $${lineData[lineData.length - 1].value}\n` +
            `  points=${lineData.length}  mode=${debugSegmentOnly ? 'SEGMENT_ONLY' : 'EXTENDED'}`
          )
        }

        // Color según estado — capa secundaria (demoted): fino y transparente
        const supportColor = tl.meta?.status === 'TESTING_SUPPORT'
          ? 'rgba(74,222,128,0.45)' : 'rgba(38,166,154,0.40)'
        const tlSeries = addOverlay({
          color:                  supportColor,
          lineWidth:              1,
          lineStyle:              LineStyle.Dashed,
          priceLineVisible:       false,
          lastValueVisible:       false,
          crosshairMarkerVisible: false,
        })
        tlSeries.setData(lineData.map(p => ({ time: p.fecha as any, value: p.value })))

        // Marcadores P1/P2 solo en modo debug
        if (debugSegmentOnly) {
          allMarkers.push({ time: pv1.fecha as any, position: 'belowBar', color: '#00e676', shape: 'circle', text: 'P1', size: 1 })
          allMarkers.push({ time: pv2.fecha as any, position: 'belowBar', color: '#00e676', shape: 'circle', text: 'P2', size: 1 })
        }
      }
    }

    // ── Resistencia dinámica ──────────────────────────────────────────────────
    if (showResistanceTrend && tr) {

      if (tr.line.length >= 2 && tr.pivots.length === 2) {
        const [pv1, pv2] = tr.pivots

        const lineData = debugSegmentOnly
          ? tr.line.filter(p => p.fecha >= pv1.fecha && p.fecha <= pv2.fecha)
          : tr.line

        if (lineData.length > 0) {
          const m = tr.meta
          console.log(
            `[RENDER RESISTANCE]\n` +
            `  p1=${pv1.fecha} $${pv1.value}\n` +
            `  p2=${pv2.fecha} $${pv2.value}\n` +
            (m ? `  status=${m.status}\n` +
                 (m.projectedToday != null ? `  projected_today=$${m.projectedToday.toFixed(2)}\n` : '') +
                 (m.signedDistPct  != null ? `  signed_dist_pct=${(m.signedDistPct * 100).toFixed(1)}%\n` : '') : '') +
            `  first=$${lineData[0].value} (${lineData[0].fecha})` +
            `  last=$${lineData[lineData.length - 1].value} (${lineData[lineData.length - 1].fecha})` +
            `  points=${lineData.length}  mode=${debugSegmentOnly ? 'SEGMENT_ONLY' : 'EXTENDED'}`
          )
        }

        // Color según estado — capa secundaria (demoted): fino y transparente
        const resistanceColor = tr.meta?.status === 'TESTING_RESISTANCE'
          ? 'rgba(250,204,21,0.45)' : 'rgba(249,115,22,0.40)'
        const trSeries = addOverlay({
          color:                  resistanceColor,
          lineWidth:              1,
          lineStyle:              LineStyle.Dashed,
          priceLineVisible:       false,
          lastValueVisible:       false,
          crosshairMarkerVisible: false,
        })
        trSeries.setData(lineData.map(p => ({ time: p.fecha as any, value: p.value })))

        // Marcadores P1/P2 solo en modo debug
        if (debugSegmentOnly) {
          allMarkers.push({ time: pv1.fecha as any, position: 'aboveBar', color: '#fb923c', shape: 'circle', text: 'P1', size: 1 })
          allMarkers.push({ time: pv2.fecha as any, position: 'aboveBar', color: '#fb923c', shape: 'circle', text: 'P2', size: 1 })
        }
      }
    }

    // Markers ordenados por fecha
    allMarkers.sort((a, b) => String(a.time) < String(b.time) ? -1 : 1)
    if (allMarkers.length > 0) candleSeries.setMarkers(allMarkers)

    // ── Capas de soporte estructural (motor longterm_support.py) ─────────────
    //
    // Estilos por horizonte:
    //   long_term  → 3px sólido   — el más importante, color según estado
    //   mid_term   → 2px dashed   — intermedio
    //   short_term → 1px dashed   — fino
    //
    // Colores por estado:
    //   ACTIVE  → color sobrio del horizonte
    //   TESTING → amarillo (#f59e0b) en todos
    //   BROKEN  → long_term: gris tenue punteado; mid/short: no renderizar
    //
    // Sólo se renderizan puntos que están dentro del rango visible del chart
    // (desde el primer candle disponible en adelante) para evitar scroll.

    const firstCandleDate = data.length ? data[0].fecha : null

    function renderStructuralLayer(
      layer:     LongtermSupportLayer | null | undefined,
      activeColor: string,
      width:     1 | 2 | 3,
      style:     0 | 1 | 2 | 3,   // LineStyle enum values
    ) {
      if (!layer || !layer.line_points.length) return
      if (layer.status === 'NO_SUPPORT') return

      // BROKEN: mid_term y short_term no se renderizan
      // BROKEN: long_term se renderiza tenue y punteada
      let color: string
      let lineStyle: 0 | 1 | 2 | 3
      let lineWidth: 1 | 2 | 3

      if (layer.status === 'BROKEN') {
        if (width < 3) return   // mid_term y short_term rotos: no renderizar
        color     = 'rgba(239,83,80,0.38)'   // rojo tenue — directriz rota, contexto histórico
        lineStyle = 2   // Dashed
        lineWidth = 1
      } else if (layer.status === 'TESTING') {
        color     = '#f59e0b'
        lineStyle = style
        lineWidth = width
      } else {
        color     = activeColor
        lineStyle = style
        lineWidth = width
      }

      // Filtrar puntos desde el primer candle disponible
      const pts = firstCandleDate
        ? layer.line_points.filter(p => p.fecha >= firstCandleDate)
        : layer.line_points

      if (pts.length < 2) return

      const series = addOverlay({
        color,
        lineWidth,
        lineStyle,
        priceLineVisible:       false,
        lastValueVisible:       false,
        crosshairMarkerVisible: false,
      })
      series.setData(pts.map(p => ({ time: p.fecha as any, value: p.value })))
    }

    // Capas diagonales — demoted a secundarias (1px, transparentes)
    renderStructuralLayer(longtermLayer,           'rgba(91,108,246,0.35)',  1, 2)
    renderStructuralLayer(longtermResistanceLayer, 'rgba(249,115,22,0.35)', 1, 2)
    renderStructuralLayer(midtermLayer,            'rgba(96,165,250,0.30)',  1, 2)
    renderStructuralLayer(shorttermLayer,          'rgba(34,211,238,0.25)',  1, 2)
    renderStructuralLayer(activeLayer,             'rgba(132,204,22,0.35)', 1, 2)
    renderStructuralLayer(activeResistanceLayer,   'rgba(234,179,8,0.35)',  1, 2)

    // ── Zonas horizontales de soporte/resistencia ─────────────────────────────
    //
    // Cada zona se renderiza como DOS líneas horizontales (zone_high y zone_low)
    // que delimitan la banda.  Colores:
    //   Soporte     → teal (#26a69a)   — primary 2px, secondary 1px
    //   Resistencia → coral (#ef5350)  — primary 2px, secondary 1px

    if (horizontalZones && horizontalZones.length > 0 && data.length >= 2) {
      const zoneFirst = data[Math.max(0, data.length - (freq === 'W' ? 520 : freq === 'M' ? 240 : 365))].fecha
      const zoneLast  = data[data.length - 1].fecha

      for (const hz of horizontalZones) {
        if (hz.rank === 'tertiary') continue   // skip noise — solo primary + secondary

        const isSup   = hz.type === 'support'
        const baseClr = isSup ? '38,166,154' : '239,83,80'

        // Visual hierarchy por rank
        const isPrimary = hz.rank === 'primary'
        const alpha     = isPrimary ? 0.6 : 0.3
        const width: 1 | 2 = isPrimary ? 2 : 1
        const style     = isPrimary ? LineStyle.Solid : LineStyle.Dashed

        // zone_high line
        const hi = addOverlay({
          color: `rgba(${baseClr},${alpha})`,
          lineWidth: width, lineStyle: style,
          priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        hi.setData([
          { time: zoneFirst as any, value: hz.zone_high },
          { time: zoneLast  as any, value: hz.zone_high },
        ])

        // zone_low line
        const lo = addOverlay({
          color: `rgba(${baseClr},${alpha})`,
          lineWidth: width, lineStyle: style,
          priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        lo.setData([
          { time: zoneFirst as any, value: hz.zone_low },
          { time: zoneLast  as any, value: hz.zone_low },
        ])

        // Y-axis label solo para primary
        if (isPrimary) {
          candleSeries.createPriceLine({
            price:            hz.center,
            color:            `rgba(${baseClr},0.55)`,
            lineWidth:        1,
            lineStyle:        LineStyle.Dotted,
            axisLabelVisible: true,
            title:            isSup ? `S ${hz.total_touches}t` : `R ${hz.total_touches}t`,
          })
        }
      }
    }

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

    // ── Responsive ────────────────────────────────────────────────────────────
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) chart.applyOptions({ width: entry.contentRect.width })
    })
    ro.observe(el)
    // Bars visibles por defecto según timeframe:
    //   D → 365  (~1.5 años de diario)
    //   W → 250  (~5 años de semanal — rango amplio como TradingView)
    //   M → 120  (~10 años de mensual)
    const DEFAULT_BARS = freq === 'W' ? 250 : freq === 'M' ? 120 : 365
    if (data.length > DEFAULT_BARS) {
      chart.timeScale().setVisibleLogicalRange({
        from: data.length - DEFAULT_BARS - 0.5,
        to:   data.length - 1 + 15,
      })
    } else {
      chart.timeScale().fitContent()
    }

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [candles, freq, indicators, showTrendline, showResistanceTrend, debugSegmentOnly, height, onTrendlineResult, longtermLayer, longtermResistanceLayer, midtermLayer, shorttermLayer, activeLayer, activeResistanceLayer, horizontalZones])

  return (
    <div
      ref={containerRef}
      style={{ height }}
      className="w-full rounded-md overflow-hidden"
    />
  )
}

// ── buildIndicatorLines ───────────────────────────────────────────────────────

export function buildIndicatorLines(candles: Candle[], strategy: string): IndicatorLine[] {
  if (!candles.length) return []

  const dates  = candles.map(c => c.fecha)
  const closes = candles.map(c => Number(c.close))
  const lines: IndicatorLine[] = []

  if (strategy === 'WMA6 / WMA30 — Swing' || strategy === 'BUY_EARLY_SWING — Anticipado') {
    lines.push({ label: 'WMA 6',  dates, values: calcWMA(closes, 6),  color: '#4f79e8' })
    lines.push({ label: 'WMA 30', dates, values: calcWMA(closes, 30), color: '#f59e0b' })
  }

  if (strategy === 'WMA21 / SMA30 — Tendencia media' || strategy === 'BUY_CONFIRMATION') {
    lines.push({ label: 'WMA 21', dates, values: calcWMA(closes, 21), color: '#4f79e8' })
    lines.push({ label: 'SMA 30', dates, values: calcSMA(closes, 30), color: '#a78bfa' })
  }

  if (strategy === 'BUY_CONFIRMATION' || strategy === 'BUY_EARLY_SWING — Anticipado') {
    lines.push({ label: 'SMA 50',  dates, values: calcSMA(closes, 50),  color: '#22c55e' })
    lines.push({ label: 'SMA 200', dates, values: calcSMA(closes, 200), color: '#ef4444' })
  }

  return lines
}
