import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, TrendingUp, TrendingDown, Activity, BarChart2, Tv2, AlertTriangle, Trash2, Pencil, X, Check, ChevronDown } from 'lucide-react'
import { api, backfillAsset, addPriceLevel, updatePriceLevel, deletePriceLevel, addTrendline, updateTrendline, deleteTrendline, type AssetDetail as IAsset, type Candle, type Indicator, type CompanyInfo, type TrendPullbackSignal, type ChannelData, type ChannelItem, type HistoricalLowSignal, type HistoricalHighSignal, type DynamicSupports, type DynamicSupportTier, type DynamicResistances, type DynamicResistanceTier, type PriceLevel, type PriceLevelKind, type Trendline, type TrendlineKind, type ChannelBreakdown, type SRV2Result } from '@/lib/api'
import { computeV2RenderObjects, type V2RenderObject, type V2RenderZone, type V2RenderDiagonal } from '@/lib/srV2Render'
import { useAuth } from '@/lib/auth'
import { fmtPrice, fmtPct, pctClass, fmt, calcRSI, calcADX, resampleOHLCV } from '@/lib/utils'
import { computeUtBot } from '@/lib/utBot'
import PriceChart, { buildIndicatorLines } from '@/components/detail/PriceChart'
import { SemaphoreBadge } from '@/components/shared/Semaphore'
import { detectDivergences, type Divergence } from '@/lib/divergence'
import RSIPanel from '@/components/detail/RSIPanel'
import DivergenceInfoPanel from '@/components/detail/DivergenceInfoPanel'
import TradingViewChart from '@/components/shared/TradingViewChart'
import ADXPanel from '@/components/detail/ADXPanel'
import CompanyInfoPanel from '@/components/detail/CompanyInfoPanel'
import FundamentalsPanel from '@/components/detail/FundamentalsPanel'
import { useGapFilter, applyGapFilter } from '@/lib/gapFilter'

const STRATEGIES = [
  '(Ninguna)',
  'WMA6 / WMA30 — Swing',
  'BUY_EARLY_SWING — Anticipado',
  'WMA21 / SMA30 — Tendencia media',
  'BUY_CONFIRMATION',
  'RSI Divergence — Señal',
]

const TIMEFRAMES = [
  { label: 'D', value: 'D' as const },
  { label: 'S', value: 'W' as const },
  { label: 'M', value: 'M' as const },
]

export default function AssetDetail() {
  const { id }    = useParams()
  const navigate  = useNavigate()
  const accionId  = Number(id)

  const [asset,     setAsset]     = useState<IAsset | null>(null)
  const [candles,   setCandles]   = useState<Candle[]>([])
  const [indicators, setIndicators] = useState<Indicator[]>([])
  const [loading,   setLoading]   = useState(true)
  const [strategyA, setStrategyA] = useState('(Ninguna)')
  const [strategyB, setStrategyB] = useState('(Ninguna)')
  const [tf,        setTf]        = useState<'D' | 'W' | 'M'>('W')
  const [chartMode, setChartMode] = useState<'local' | 'tv' | 'v2'>('local')
  const [companyInfo,    setCompanyInfo]    = useState<CompanyInfo | null>(null)
  const [companyLoading, setCompanyLoading] = useState(true)
  const [tpSignal,       setTpSignal]       = useState<TrendPullbackSignal | null>(null)
  const [channelData,    setChannelData]    = useState<ChannelData | null>(null)
  const [showChannels,   setShowChannels]   = useState(true)
  const [hlSignal,       setHlSignal]       = useState<HistoricalLowSignal | null>(null)
  const [hhSignal,       setHhSignal]       = useState<HistoricalHighSignal | null>(null)
  const [dynSupports,    setDynSupports]    = useState<DynamicSupports | null>(null)
  const [showDynSupports,setShowDynSupports]= useState(true)
  const [dynSupTiers, setDynSupTiers] = useState({ long: true, mid: true, short: true })
  const [dynSupDropdown, setDynSupDropdown] = useState(false)
  const [dynResistances,    setDynResistances]    = useState<DynamicResistances | null>(null)
  const [showDynResistances,setShowDynResistances]= useState(true)
  const [dynResTf,          setDynResTf]          = useState<'W' | 'D'>('W')
  const [v2DynSup,          setV2DynSup]          = useState<DynamicSupports | null>(null)
  const [v2DynRes,          setV2DynRes]          = useState<DynamicResistances | null>(null)
  const [chBreakdown,    setChBreakdown]    = useState<ChannelBreakdown | null>(null)
  const [showUtBot,      setShowUtBot]      = useState(false)
  const [backfilling,    setBackfilling]    = useState(false)
  // Niveles dibujados por el usuario (soporte/resistencia/target/nota) — per-user
  const [priceLevels,    setPriceLevels]    = useState<PriceLevel[]>([])
  // Popover posicionado en click-derecho sobre el chart. `price` viene del Y->price del chart.
  const [ctxMenu, setCtxMenu] = useState<{ price: number; x: number; y: number } | null>(null)
  // Trendlines (polyline N>=2) dibujadas por el usuario — per-user
  const [trendlines,     setTrendlines]     = useState<Trendline[]>([])
  // Modo dibujo: cada clic acumula un punto. "Trazar" guarda la trendline
  // con todos los puntos acumulados (se requiere N>=2).
  const [drawMode,       setDrawMode]       = useState(false)
  const [drawKind,       setDrawKind]       = useState<TrendlineKind>('support')
  const [drawPoints,     setDrawPoints]     = useState<{ time: string; price: number }[]>([])
  const [lineInfoTab,    setLineInfoTab]    = useState<string | null>(null)
  const [srV2,           setSrV2]           = useState<SRV2Result | null>(null)
  const [srV2Loading,    setSrV2Loading]    = useState(false)
  const [v2InfoTab,      setV2InfoTab]      = useState<string | null>(null)
  const { username } = useAuth()
  const isAdmin = username === 'albano'

  const handleBackfill = async () => {
    if (backfilling) return
    setBackfilling(true)
    try {
      const r = await backfillAsset(accionId)
      alert(`Backfill OK para ${r.symbol}. Recargando…`)
      window.location.reload()
    } catch (e) {
      alert(`Error backfill: ${(e as Error).message}`)
    } finally {
      setBackfilling(false)
    }
  }

  useEffect(() => {
    if (!accionId) return
    setLoading(true)
    Promise.allSettled([
      api.asset(accionId),
      api.ohlcvExtended(accionId, 'D'),   // histórico completo diario — fuente única
      api.indicators(accionId, 365),
    ]).then(([a, od, ind]) => {
      if (a.status === 'fulfilled')   setAsset(a.value)
      if (od.status === 'fulfilled')  setCandles(od.value.candles)
      if (ind.status === 'fulfilled') setIndicators(ind.value.indicators)
    }).finally(() => setLoading(false))

    // Fetch company info (fundamentals — Yahoo quoteSummary)
    setCompanyLoading(true)
    setCompanyInfo(null)
    api.companyInfo(accionId)
      .then(data => setCompanyInfo(data))
      .catch(() => setCompanyInfo(null))
      .finally(() => setCompanyLoading(false))

    // Fetch última señal trend_pullback (puede ser null si no hay)
    api.trendPullbackSignal(accionId)
      .then(setTpSignal)
      .catch(() => setTpSignal(null))

    // Fetch channel detection
    api.channel(accionId)
      .then(setChannelData)
      .catch(() => setChannelData(null))

    // Fetch historical low signal
    api.historicalLowSignal(accionId)
      .then(setHlSignal)
      .catch(() => setHlSignal(null))

    // Fetch historical high signal
    api.historicalHighSignal(accionId)
      .then(setHhSignal)
      .catch(() => setHhSignal(null))

    // Fetch channel breakdown analysis (3 escenarios post-ruptura de canal)
    api.channelBreakdown(accionId)
      .then(setChBreakdown)
      .catch(() => setChBreakdown(null))

    // Fetch dynamic supports (long/mid/short trendlines ascendentes en log-space)
    api.dynamicSupports(accionId)
      .then(setDynSupports)
      .catch(() => setDynSupports(null))

    // Resistencias dinámicas se fetchean en un effect separado para poder
    // reaccionar al toggle W/D sin volver a traer todo.

    // Fetch niveles de precio dibujados por el usuario (per-user, filtrados en backend)
    api.priceLevels(accionId)
      .then(r => setPriceLevels(r.items ?? []))
      .catch(() => setPriceLevels([]))

    // Fetch trendlines dibujadas por el usuario (per-user, filtradas en backend)
    api.trendlines(accionId)
      .then(r => setTrendlines(r.items ?? []))
      .catch(() => setTrendlines([]))
  }, [accionId])

  // Resistencias dinámicas: re-fetch al cambiar asset o timeframe (W/D)
  useEffect(() => {
    if (!accionId) return
    api.dynamicResistances(accionId, dynResTf)
      .then(setDynResistances)
      .catch(() => setDynResistances(null))
  }, [accionId, dynResTf])

  // SR V2: lazy-fetch al entrar al tab V2
  useEffect(() => {
    if (chartMode !== 'v2' || !accionId) return
    if (srV2 && srV2.symbol) return
    setSrV2Loading(true)
    api.srV2(accionId)
      .then(setSrV2)
      .catch(() => setSrV2(null))
      .finally(() => setSrV2Loading(false))
  }, [chartMode, accionId])

  // V2: soportes y resistencias en timeframe D (diario) para rectas precisas
  useEffect(() => {
    if (chartMode !== 'v2' || !accionId) return
    api.dynamicSupports(accionId, 'D')
      .then(setV2DynSup)
      .catch(() => setV2DynSup(null))
    api.dynamicResistances(accionId, 'D')
      .then(setV2DynRes)
      .catch(() => setV2DynRes(null))
  }, [chartMode, accionId])

  // Helpers CRUD para niveles del usuario — refetch simple post-mutación
  const reloadLevels = () => {
    api.priceLevels(accionId)
      .then(r => setPriceLevels(r.items ?? []))
      .catch(() => { /* keep previous */ })
  }
  const handleAddLevel = async (kind: PriceLevelKind, price: number) => {
    try {
      await addPriceLevel({ accion_id: accionId, price, kind })
      reloadLevels()
    } catch (e) {
      alert(`No pude crear el nivel: ${(e as Error).message}`)
    } finally {
      setCtxMenu(null)
    }
  }
  const handleDeleteLevel = async (id: number) => {
    try {
      await deletePriceLevel(id)
      setPriceLevels(prev => prev.filter(l => l.id !== id))
    } catch (e) {
      alert(`No pude borrar el nivel: ${(e as Error).message}`)
    }
  }
  const handlePatchLevel = async (id: number, patch: { price?: number; kind?: PriceLevelKind; label?: string | null }) => {
    try {
      const updated = await updatePriceLevel(id, patch)
      setPriceLevels(prev => prev.map(l => l.id === id ? updated : l))
    } catch (e) {
      alert(`No pude actualizar el nivel: ${(e as Error).message}`)
    }
  }

  // Handlers para trendlines (polyline N>=2)
  const handleDrawPoint = ({ time, price }: { time: string; price: number }) => {
    // Dedup por fecha: si el usuario clickea 2 veces sobre la misma vela,
    // sobreescribimos el precio del punto previo (una sola trendline por bar).
    setDrawPoints(prev => {
      const without = prev.filter(p => p.time !== time)
      return [...without, { time, price }].sort((a, b) => a.time < b.time ? -1 : 1)
    })
  }
  const handleUndoPoint = () => {
    setDrawPoints(prev => prev.slice(0, -1))
  }
  const handleCancelDraw = () => {
    setDrawPoints([])
  }
  const handleCommitTrendline = async () => {
    if (drawPoints.length < 2) {
      alert('Necesitás al menos 2 puntos')
      return
    }
    try {
      const created = await addTrendline({
        accion_id: accionId,
        points:    drawPoints.map(p => ({ t: p.time, p: p.price })),
        kind:      drawKind,
      })
      setTrendlines(prev => [created, ...prev])
      setDrawPoints([])
    } catch (e) {
      alert(`No pude crear la trendline: ${(e as Error).message}`)
    }
  }
  const handleDeleteTrendline = async (id: number) => {
    try {
      await deleteTrendline(id)
      setTrendlines(prev => prev.filter(t => t.id !== id))
    } catch (e) {
      alert(`No pude borrar la trendline: ${(e as Error).message}`)
    }
  }
  const handlePatchTrendline = async (id: number, patch: { kind?: TrendlineKind; label?: string | null }) => {
    try {
      const updated = await updateTrendline(id, patch)
      setTrendlines(prev => prev.map(t => t.id === id ? updated : t))
    } catch (e) {
      alert(`No pude actualizar la trendline: ${(e as Error).message}`)
    }
  }

  // Cancelar modo dibujo si cambia el activo
  useEffect(() => {
    setDrawMode(false)
    setDrawPoints([])
  }, [accionId])

  // Esc: si hay puntos en progreso los cancela; si no, sale del modo.
  // Enter: si hay N>=2 puntos, traza.
  useEffect(() => {
    if (!drawMode) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (drawPoints.length) setDrawPoints([])
        else setDrawMode(false)
      } else if (e.key === 'Enter' && drawPoints.length >= 2) {
        handleCommitTrendline()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawMode, drawPoints])

  // Velas al timeframe del chart — todos los paneles (ADX/RSI/UT Bot/divergences)
  // usan esta serie para que coincida con las velas visibles.
  const chartCandles: Candle[] = candles.length
    ? (tf === 'D' ? candles
       : tf === 'W' ? resampleOHLCV(candles, 'W')
       :              resampleOHLCV(candles, 'M'))
    : []

  const rsiValues   = chartCandles.length ? calcRSI(chartCandles.map(c => Number(c.close))) : []
  const divergences = chartCandles.length
    ? detectDivergences(chartCandles, rsiValues)
    : [] as Divergence[]
  const currentRsiCalc = rsiValues.length ? (rsiValues[rsiValues.length - 1] ?? null) : null
  const adxData = chartCandles.length ? calcADX(chartCandles) : { adx: [], plusDI: [], minusDI: [] }

  const activeStrategies = [strategyA, strategyB].filter(s => s !== '(Ninguna)')
  const indicatorLines = buildIndicatorLines(candles, activeStrategies)

  // Build channel overlay lines — multiple horizons with different colors
  // Log-scale chart → exp() lines appear as straight lines (same as PDF/TradingView)
  const channelColors: Record<string, { line: string; mid: string }> = {
    long:   { line: '#00e5ff', mid: 'rgba(0,229,255,0.25)' },
    medium: { line: '#FFD700', mid: 'rgba(255,215,0,0.2)' },
    short:  { line: '#00ff88', mid: 'rgba(0,255,136,0.2)' },
  }
  const channelItems: ChannelItem[] = showChannels ? (channelData?.channels ?? []) : []
  for (const ch of channelItems) {
    if (!ch.channel_type || !candles.length) continue
    const originMs = new Date(ch.line_origin).getTime()
    const slope = ch.line_slope
    const icLow = ch.line_ic_lower
    const icUp = ch.line_ic_upper
    const colors = channelColors[ch.horizon] ?? channelColors.long
    const dates: string[] = []
    const upperVals: (number | null)[] = []
    const lowerVals: (number | null)[] = []
    const midVals: (number | null)[] = []
    for (const c of candles) {
      const ms = new Date(c.fecha).getTime()
      dates.push(c.fecha)
      if (ms < originMs) {
        upperVals.push(null)
        lowerVals.push(null)
        midVals.push(null)
        continue
      }
      const days = (ms - originMs) / 86400000
      const u = Math.exp(slope * days + icUp)
      const l = Math.exp(slope * days + icLow)
      upperVals.push(u)
      lowerVals.push(l)
      midVals.push(Math.sqrt(u * l))
    }
    const label = ch.horizon === 'long' ? 'LP' : ch.horizon === 'medium' ? 'MP' : 'CP'
    indicatorLines.push(
      { dates, values: upperVals, color: colors.line, label: `Canal ${label} Upper` },
      { dates, values: lowerVals, color: colors.line, label: `Canal ${label} Lower` },
      { dates, values: midVals,   color: colors.mid,  label: `Canal ${label} Mid` },
    )
  }
  // Build dynamic support overlay lines (long/mid/short trendlines)
  //   verde    = largo plazo estructural
  //   amarillo = mediano plazo (pullbacks recientes)
  //   cyan     = corto plazo (ultimo rally / lateralizacion)
  // Tiers con kind='horizontal' se renderizan como ZONA (priceZones) en vez
  // de como linea; los ascendentes siguen como IndicatorLine interpolada.
  const dynZones: import('@/components/detail/PriceChart').PriceZone[] = []
  if (dynSupports && showDynSupports && candles.length) {
    const tiers: [keyof DynamicSupports, string, string][] = [
      ['long',  '#00e676', 'LP'],
      ['mid',   '#ffd54f', 'MP'],
      ['short', '#4fc3f7', 'CP'],
    ]
    const candleDates = candles.map(c => c.fecha)
    for (const [key, color, label] of tiers) {
      if (!dynSupTiers[key as 'long' | 'mid' | 'short']) continue
      const tier = dynSupports[key]
      if (!tier || typeof tier === 'string' || typeof tier === 'number') continue
      if (!('line_points' in tier)) continue
      // Horizontal (lateralizacion): zona con piso + tope
      if (tier.kind === 'horizontal' && typeof tier.zone_top === 'number') {
        dynZones.push({
          floor: tier.current_value,
          top:   tier.zone_top,
          color,
          label: `Zona ${label}`,
        })
        continue
      }
      if (!tier.line_points.length) continue
      const pts = tier.line_points
      const firstPt = pts[0]
      const lastPt  = pts[pts.length - 1]
      const firstTs = Date.parse(firstPt.fecha)
      const lastTs  = Date.parse(lastPt.fecha)
      const logFirst = Math.log(firstPt.value)
      const logLast  = Math.log(lastPt.value)
      const values = candleDates.map(d => {
        const t = Date.parse(d)
        if (t < firstTs || t > lastTs) return null
        if (lastTs === firstTs) return firstPt.value
        const frac = (t - firstTs) / (lastTs - firstTs)
        return Math.exp(logFirst + frac * (logLast - logFirst))
      })
      indicatorLines.push({
        dates:  candleDates,
        values,
        color,
        label:  `Soporte ${label}`,
      })
    }
  }
  // Build dynamic resistance overlay lines (long/mid/short trendlines descendentes)
  //   rojo     = largo plazo estructural (bear market vigente)
  //   naranja  = mediano plazo (rally bajista reciente)
  //   magenta  = corto plazo (ultima caida / lateralizacion bajo un techo)
  // Horizontal => zona (zone_floor + zone_ceiling) en vez de linea diagonal.
  if (dynResistances && showDynResistances && candles.length) {
    const tiers: [keyof DynamicResistances, string, string][] = [
      ['long',  '#ef4444', 'LP'],
      ['mid',   '#fb923c', 'MP'],
      ['short', '#ef4444', 'CP'],
    ]
    const candleDates = candles.map(c => c.fecha)
    for (const [key, color, label] of tiers) {
      const tier = dynResistances[key]
      if (!tier || typeof tier === 'string' || typeof tier === 'number') continue
      if (!('line_points' in tier)) continue
      // Horizontal: zona con piso + techo (techo = la resistencia)
      if (tier.kind === 'horizontal' && typeof tier.zone_floor === 'number' && typeof tier.zone_ceiling === 'number') {
        dynZones.push({
          floor: tier.zone_floor,
          top:   tier.zone_ceiling,
          color,
          label: `Zona R ${label}`,
        })
        continue
      }
      if (!tier.line_points.length) continue
      const pts = tier.line_points
      const firstPt = pts[0]
      const lastPt  = pts[pts.length - 1]
      const firstTs = Date.parse(firstPt.fecha)
      const lastTs  = Date.parse(lastPt.fecha)
      const logFirst = Math.log(firstPt.value)
      const logLast  = Math.log(lastPt.value)
      const values = candleDates.map(d => {
        const t = Date.parse(d)
        if (t < firstTs || t > lastTs) return null
        if (lastTs === firstTs) return firstPt.value
        const frac = (t - firstTs) / (lastTs - firstTs)
        return Math.exp(logFirst + frac * (logLast - logFirst))
      })
      indicatorLines.push({
        dates:  candleDates,
        values,
        color,
        label:  `Resistencia ${label}`,
      })
    }
  }
  // Build UT Bot trailing stop overlay + markers (se computa local, sobre las
  // velas del timeframe visible — así D/S/M rinden su propia versión consistente
  // con las velas del chart y los markers caen exactos sobre los bars).
  //
  // 2 IndicatorLines: UP verde `#26a69a` / DOWN rojo `#ef5350`. En cada flip, el
  // valor se agrega a AMBAS series para que se toquen visualmente sin huecos.
  const utBot = showUtBot && chartCandles.length
    ? computeUtBot(chartCandles, 2.0, 10)
    : { points: [], signals: [] }
  if (showUtBot && utBot.points.length) {
    const pts = utBot.points
    const dates = pts.map(p => p.fecha)
    const upVals:   (number | null)[] = []
    const downVals: (number | null)[] = []
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i]
      const prev = i > 0 ? pts[i - 1] : null
      const flip = prev && prev.state !== p.state
      if (p.state === 'UP') {
        upVals.push(p.value)
        downVals.push(flip ? p.value : null)
      } else {
        downVals.push(p.value)
        upVals.push(flip ? p.value : null)
      }
    }
    indicatorLines.push(
      { dates, values: upVals,   color: '#26a69a', label: 'UT Bot UP' },
      { dates, values: downVals, color: '#ef5350', label: 'UT Bot DOWN' },
    )
  }
  const utBotMarkers = showUtBot ? utBot.signals : []

  // Touch-point dot layers: una capa por tier, cada una con su color
  const dotLayers: import('@/components/detail/PriceChart').DotMarker[][] = []
  if (dynSupports && showDynSupports) {
    const dotColors: Record<string, string> = { long: '#ff00ff', mid: '#ff8800', short: '#00ffff' }
    for (const key of ['long', 'mid', 'short'] as const) {
      if (!dynSupTiers[key]) continue
      const tier = dynSupports[key]
      if (!tier || typeof tier !== 'object' || !('touch_points' in tier)) continue
      if (tier.kind === 'horizontal') continue
      const tp = (tier as any).touch_points as { fecha: string; value: number }[] | undefined
      if (!tp || !tp.length) continue
      dotLayers.push(tp.map(pt => ({ fecha: pt.fecha, value: pt.value, color: dotColors[key] })))
    }
  }
  // Build historical low overlay lines (horizontal lines at 52w low / all-time low)
  if (hlSignal && hlSignal.setup_state !== 'NO_SIGNAL' && candles.length) {
    const dates = candles.map(c => c.fecha)
    // 52-week low line
    if (hlSignal.low_52w) {
      indicatorLines.push({
        dates,
        values: dates.map(() => hlSignal.low_52w),
        color: '#ef4444',
        label: `Min 52w $${hlSignal.low_52w.toFixed(2)}`,
      })
    }
    // All-time low line (only if different from 52w low)
    if (hlSignal.low_all && Math.abs(hlSignal.low_all - hlSignal.low_52w) > 0.01) {
      indicatorLines.push({
        dates,
        values: dates.map(() => hlSignal.low_all),
        color: '#f97316',
        label: `Min hist $${hlSignal.low_all.toFixed(2)}`,
      })
    }
  }
  // Build historical high overlay lines (horizontal lines at 52w high / all-time high)
  if (hhSignal && hhSignal.setup_state !== 'NO_SIGNAL' && candles.length) {
    const dates = candles.map(c => c.fecha)
    // 52-week high line
    if (hhSignal.high_52w) {
      indicatorLines.push({
        dates,
        values: dates.map(() => hhSignal.high_52w),
        color: '#22c55e',
        label: `Max 52w $${hhSignal.high_52w.toFixed(2)}`,
      })
    }
    // All-time high line (only if different from 52w high)
    if (hhSignal.high_all && Math.abs(hhSignal.high_all - hhSignal.high_52w) > 0.01) {
      indicatorLines.push({
        dates,
        values: dates.map(() => hhSignal.high_all),
        color: '#16a34a',
        label: `Max hist $${hhSignal.high_all.toFixed(2)}`,
      })
    }
  }

  // Channel Breakdown: dibujar zonas de soporte post-ruptura como bandas
  if (chBreakdown && chBreakdown.has_breakdown && chBreakdown.zones.length && candles.length) {
    for (const z of chBreakdown.zones) {
      dynZones.push({
        floor: z.zone_low,
        top:   z.zone_high,
        color: '#4fc3f7',
        label: `Zona BD $${z.floor.toFixed(0)}`,
      })
    }
  }

  // ── V2 render pipeline ─────────────────────────────────────────────────────
  const v2Rendered = useMemo(() => {
    if (!srV2 || !candles.length) return [] as V2RenderObject[]
    const prices = candles.map(c => Number(c.high))
    const lows = candles.map(c => Number(c.low))
    const recentHigh = Math.max(...prices.slice(-52))
    const recentLow = Math.min(...lows.slice(-52))
    return computeV2RenderObjects(srV2, recentHigh, recentLow)
  }, [srV2, candles])

  const v2Overlays = useMemo(() => {
    const indicators: { dates: string[]; values: (number | null)[]; color: string; label: string }[] = []
    const zones: { floor: number; top: number; color: string; label: string; borderColor?: string; floorWidth?: number; topWidth?: number; floorStyle?: 'solid' | 'dashed' | 'dotted'; topStyle?: 'solid' | 'dashed' | 'dotted'; labelVisible?: boolean }[] = []

    if (!v2Rendered.length || !candles.length) return { indicators, zones }

    const candleDates = candles.map(c => c.fecha)

    for (const obj of v2Rendered) {
      if (obj.kind === 'horizontal') {
        const hz = obj as V2RenderZone
        zones.push({
          floor:        hz.zone_min,
          top:          hz.zone_max,
          color:        hz.fill_color,
          label:        hz.label,
          borderColor:  hz.border_color,
          floorWidth:   hz.border_width,
          topWidth:     hz.border_width,
          floorStyle:   hz.border_style,
          topStyle:     hz.border_style,
          labelVisible: hz.label_visible,
        })
      } else {
        const dl = obj as V2RenderDiagonal

        const buildInterp = (pts: { fecha: string; value: number }[]) => {
          if (!pts.length) return candleDates.map(() => null as number | null)
          const t0 = Date.parse(pts[0].fecha)
          const tN = Date.parse(pts[pts.length - 1].fecha)
          let idx0 = -1, idxN = -1, bd0 = Infinity, bdN = Infinity
          for (let i = 0; i < candleDates.length; i++) {
            const ct = Date.parse(candleDates[i])
            const d0 = Math.abs(ct - t0); if (d0 < bd0) { bd0 = d0; idx0 = i }
            const dN = Math.abs(ct - tN); if (dN < bdN) { bdN = dN; idxN = i }
          }
          if (idx0 < 0 || idxN < 0 || idxN <= idx0) return candleDates.map(() => null as number | null)
          const log0 = Math.log(pts[0].value)
          const logN = Math.log(pts[pts.length - 1].value)
          const logSlope = (logN - log0) / (idxN - idx0)
          return candleDates.map((_, i) => {
            if (i < idx0 || i > idxN) return null
            return Math.exp(log0 + logSlope * (i - idx0))
          })
        }

        indicators.push({
          dates:  candleDates,
          values: buildInterp(dl.line_points),
          color:  dl.line_color,
          label:  dl.label,
        })
        if (dl.visual_tier !== 'tertiary') {
          indicators.push({
            dates:  candleDates,
            values: buildInterp(dl.zone_upper_points),
            color:  dl.zone_color,
            label:  `${dl.label} upper`,
          })
          indicators.push({
            dates:  candleDates,
            values: buildInterp(dl.zone_lower_points),
            color:  dl.zone_color,
            label:  `${dl.label} lower`,
          })
        }
      }
    }

    return { indicators, zones }
  }, [v2Rendered, candles])

  // ── V2: soportes/resistencias dinámicos con recta log-space por bar-index ──
  // Helper: busca el indice de vela mas cercano a una fecha
  const findBarIdx = (dates: string[], fecha: string) => {
    const t = Date.parse(fecha)
    let best = 0, bestD = Infinity
    for (let i = 0; i < dates.length; i++) {
      const d = Math.abs(Date.parse(dates[i]) - t)
      if (d < bestD) { bestD = d; best = i }
    }
    return best
  }

  const v2DynZones: import('@/components/detail/PriceChart').PriceZone[] = []
  const v2DynLines: { dates: string[]; values: (number | null)[]; color: string; label: string }[] = []
  const v2DotLayers: import('@/components/detail/PriceChart').DotMarker[][] = []

  const v2SupData = v2DynSup || dynSupports
  const v2ResData = v2DynRes || dynResistances

  if (v2SupData && showDynSupports && candles.length) {
    const cd = candles.map(c => c.fecha)
    const tiers: [keyof DynamicSupports, string, string][] = [
      ['long',  '#00e676', 'LP'],
      ['mid',   '#ffd54f', 'MP'],
      ['short', '#4fc3f7', 'CP'],
    ]
    for (const [key, color, label] of tiers) {
      if (!dynSupTiers[key as 'long' | 'mid' | 'short']) continue
      const tier = v2SupData[key]
      if (!tier || typeof tier === 'string' || typeof tier === 'number') continue
      if (!('line_points' in tier)) continue
      if (tier.kind === 'horizontal' && typeof tier.zone_top === 'number') {
        v2DynZones.push({ floor: tier.current_value, top: tier.zone_top, color, label: `Zona ${label}` })
        continue
      }
      const a1v = tier.anchor1.value
      const a2v = tier.anchor2.value
      const a1idx = findBarIdx(cd, tier.anchor1.fecha)
      const a2idx = findBarIdx(cd, tier.anchor2.fecha)
      if (a2idx <= a1idx) continue
      const lg1 = Math.log(a1v)
      const lgS = (Math.log(a2v) - lg1) / (a2idx - a1idx)
      v2DynLines.push({
        dates: cd,
        values: cd.map((_, i) => i < a1idx ? null : Math.exp(lg1 + lgS * (i - a1idx))),
        color,
        label: `Soporte ${label}`,
      })
    }
  }

  if (v2ResData && showDynResistances && candles.length) {
    const cd = candles.map(c => c.fecha)
    const tiers: [keyof DynamicResistances, string, string][] = [
      ['long',  '#ef4444', 'LP'],
      ['mid',   '#fb923c', 'MP'],
      ['short', '#ef4444', 'CP'],
    ]
    for (const [key, color, label] of tiers) {
      const tier = v2ResData[key]
      if (!tier || typeof tier === 'string' || typeof tier === 'number') continue
      if (!('line_points' in tier)) continue
      if (tier.kind === 'horizontal' && typeof tier.zone_floor === 'number' && typeof tier.zone_ceiling === 'number') {
        v2DynZones.push({ floor: tier.zone_floor, top: tier.zone_ceiling, color, label: `Zona R ${label}` })
        continue
      }
      const a1v = tier.anchor1.value
      const a2v = tier.anchor2.value
      const a1idx = findBarIdx(cd, tier.anchor1.fecha)
      const a2idx = findBarIdx(cd, tier.anchor2.fecha)
      if (a2idx <= a1idx) continue
      const lg1 = Math.log(a1v)
      const lgS = (Math.log(a2v) - lg1) / (a2idx - a1idx)
      v2DynLines.push({
        dates: cd,
        values: cd.map((_, i) => i < a1idx ? null : Math.exp(lg1 + lgS * (i - a1idx))),
        color,
        label: `Resistencia ${label}`,
      })
    }
  }

  const rsiDivergenceActive = activeStrategies.includes('RSI Divergence — Señal')

  // Último indicador disponible
  const lastInd = indicators.length ? indicators[indicators.length - 1] : null

  // Semáforo: dist_sma200_pct
  const distSma = lastInd?.dist_sma200_pct
  const trendColor = distSma == null ? 'neutral'
    : distSma >= 5  ? 'up'
    : distSma >= 0  ? 'warn'
    : distSma >= -5 ? 'warn'
    : 'down'
  const trendLabel = distSma == null ? 'Sin datos'
    : distSma >= 5  ? 'Tendencia alcista'
    : distSma >= 0  ? 'Cerca de SMA200'
    : 'Bajo SMA200'

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-sm text-text-muted">Cargando...</p>
    </div>
  )

  if (!asset) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-sm text-text-muted">Activo no encontrado</p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Back */}
      <button
        className="btn-ghost text-xs gap-1"
        onClick={() => navigate(-1)}
      >
        <ArrowLeft size={13} /> Volver
      </button>

      {/* Asset header */}
      <div className="card p-4 md:p-5">
        <div className="flex flex-wrap items-start gap-3 md:gap-6">
          {/* Symbol + name */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5">
              <span className="font-mono text-2xl font-bold text-text-primary tracking-tight">
                {asset.simbolo}
              </span>
              <span className="badge badge-neutral">{asset.mercado}</span>
            </div>
            <p className="text-sm text-text-secondary mt-0.5 truncate">{asset.nombre}</p>
          </div>

          {/* Price */}
          <div className="text-right">
            <p className="font-mono text-2xl font-semibold text-text-primary">
              {fmtPrice(asset.precio)}
            </p>
            <p className={`font-mono text-base font-medium mt-0.5 ${pctClass(asset.pct_cambio)}`}>
              {fmtPct(asset.pct_cambio)}
            </p>
          </div>

          {/* Semáforo de tendencia */}
          <div className="flex flex-col gap-1.5 pt-0.5">
            <SemaphoreBadge color={trendColor} label={trendLabel} />
          </div>
        </div>

        {/* Indicadores clave */}
        {lastInd && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4 mt-5 pt-4 border-t border-border">
            <Kpi icon={<Activity size={12} />} label="RSI 14"
              value={fmt(lastInd.rsi14, 1)} />
            <Kpi icon={<TrendingUp size={12} />} label="Mom 5d"
              value={fmtPct(lastInd.momentum_5d)}
              cls={pctClass(lastInd.momentum_5d)} />
            <Kpi icon={<BarChart2 size={12} />} label="Vol ratio 20d"
              value={fmt(lastInd.volume_ratio_20d) + 'x'} />
            <Kpi icon={<Activity size={12} />} label="ATR 14"
              value={fmt(lastInd.atr14_rel, 2) + '%'} />
          </div>
        )}
      </div>

      {/* Información fundamental de la empresa */}
      <CompanyInfoPanel data={companyInfo} loading={companyLoading} />

      {/* Información financiera fundamental (yfinance) */}
      <FundamentalsPanel accionId={accionId} />

      {/* Estado señal Trend+Pullback (con filtro gap del usuario) */}
      {tpSignal && <TrendPullbackBadgeRow signal={tpSignal} />}

      {/* Estado señal de mínimos históricos */}
      {hlSignal && hlSignal.setup_state !== 'NO_SIGNAL' && (
        <HistoricalLowBadgeRow signal={hlSignal} />
      )}

      {/* Estado señal de máximos históricos */}
      {hhSignal && hhSignal.setup_state !== 'NO_SIGNAL' && (
        <HistoricalHighBadgeRow signal={hhSignal} />
      )}

      {/* Channel Breakdown — 3 escenarios post-ruptura */}
      {chBreakdown && chBreakdown.has_breakdown && chBreakdown.best_scenario && (
        <ChannelBreakdownBadgeRow data={chBreakdown} />
      )}

      {/* Controles del gráfico */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Estrategias — combinables de a dos */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Estrategia A</span>
          <select
            value={strategyA}
            onChange={e => setStrategyA(e.target.value)}
            className="bg-surface border border-border rounded-md px-2.5 py-1.5 text-xs
                       text-text-primary hover:border-accent focus:outline-none focus:border-accent
                       transition-colors"
          >
            {STRATEGIES.map(s => (
              <option key={s} value={s}>
                {s === '(Ninguna)' ? 'Ninguna' : s}
              </option>
            ))}
          </select>

          <span className="text-xs text-text-muted">+ B</span>
          <select
            value={strategyB}
            onChange={e => setStrategyB(e.target.value)}
            className="bg-surface border border-border rounded-md px-2.5 py-1.5 text-xs
                       text-text-primary hover:border-accent focus:outline-none focus:border-accent
                       transition-colors"
          >
            {STRATEGIES.map(s => (
              <option key={s} value={s}>
                {s === '(Ninguna)' ? 'Ninguna' : s}
              </option>
            ))}
          </select>
        </div>

        {/* Temporalidad */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Temporalidad</span>
          <div className="flex items-center gap-0 border border-border rounded-md overflow-hidden">
            {TIMEFRAMES.map(t => (
              <button
                key={t.value}
                className={`px-3 py-1.5 text-xs transition-colors ${
                  tf === t.value
                    ? 'bg-accent text-white'
                    : 'text-text-secondary hover:text-text-primary hover:bg-elevated'
                }`}
                onClick={() => setTf(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Leyenda de líneas activas (las que dibujan los combos seleccionados) */}
        {indicatorLines.length > 0 && (
          <div className="flex items-center gap-3 ml-2">
            {indicatorLines.map(l => (
              <div key={l.label} className="flex items-center gap-1.5">
                <span className="w-4 h-0.5 block rounded" style={{ backgroundColor: l.color }} />
                <span className="text-2xs text-text-secondary">{l.label}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Selector de fuente del gráfico
          - Gráfico local: chart propio con soportes, resistencias, canales y señales (overlays)
          - TradingView Live: widget embebido externo, solo visualización, sin overlays propios */}
      <div className="flex items-center gap-1.5">
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            chartMode === 'local'
              ? 'bg-accent text-white border-accent'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setChartMode('local')}
        >
          <BarChart2 size={12} /> Gráfico local
        </button>
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            chartMode === 'v2'
              ? 'bg-accent text-white border-accent'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setChartMode('v2')}
        >
          <BarChart2 size={12} /> Gráfico local V2
        </button>
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            chartMode === 'tv'
              ? 'bg-accent text-white border-accent'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setChartMode('tv')}
        >
          <Tv2 size={12} /> TradingView Live
        </button>
        <span className="mx-1 border-l border-border h-5" />
        <div className="relative">
          <button
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
              showDynSupports
                ? 'bg-[#00e676]/20 text-[#00e676] border-[#00e676]/40'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
            onClick={() => setShowDynSupports(v => !v)}
            title="Soportes dinámicos (long/mid/short)"
          >
            <TrendingUp size={12} /> Soportes
            <ChevronDown
              size={10}
              className="ml-0.5 cursor-pointer"
              onClick={e => { e.stopPropagation(); setDynSupDropdown(v => !v) }}
            />
          </button>
          {dynSupDropdown && showDynSupports && (<>
            <div className="fixed inset-0 z-40" onClick={() => setDynSupDropdown(false)} />
            <div className="absolute top-full left-0 mt-1 bg-bg-primary border border-border rounded-md shadow-lg z-50 min-w-[120px]">
              {([['long', 'LP', '#00e676'], ['mid', 'MP', '#ffd54f'], ['short', 'CP', '#4fc3f7']] as const).map(([k, label, color]) => (
                <label key={k} className="flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer hover:bg-bg-secondary">
                  <input
                    type="checkbox"
                    checked={dynSupTiers[k]}
                    onChange={() => setDynSupTiers(prev => ({ ...prev, [k]: !prev[k] }))}
                    className="accent-current"
                    style={{ accentColor: color }}
                  />
                  <span style={{ color }}>{label}</span>
                </label>
              ))}
            </div>
          </>)}
        </div>
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            showChannels
              ? 'bg-[#00e5ff]/20 text-[#00e5ff] border-[#00e5ff]/40'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setShowChannels(v => !v)}
        >
          <TrendingUp size={12} /> Canales
        </button>
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            showUtBot
              ? 'bg-[#26a69a]/20 text-[#26a69a] border-[#26a69a]/40'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setShowUtBot(v => !v)}
          title="UT Bot trailing stop (sensitivity 2, ATR 10)"
        >
          <Activity size={12} /> UT Bot
        </button>
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            showDynResistances
              ? 'bg-[#ef4444]/20 text-[#ef4444] border-[#ef4444]/40'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setShowDynResistances(v => !v)}
          title="Resistencias dinámicas (long/mid/short)"
        >
          <TrendingDown size={12} /> Resistencias
        </button>
        {showDynResistances && (
          <div className="flex items-center rounded-md border border-border overflow-hidden -ml-1">
            {(['W', 'D'] as const).map(tf => (
              <button
                key={tf}
                className={`px-2 py-1.5 text-xs transition-colors ${
                  dynResTf === tf
                    ? 'bg-[#ef4444]/15 text-[#ef4444]'
                    : 'text-text-muted hover:text-text-secondary'
                }`}
                onClick={() => setDynResTf(tf)}
                title={`Recalcular resistencias en ${tf === 'W' ? 'semanal' : 'diario'}`}
              >
                {tf}
              </button>
            ))}
          </div>
        )}
        <span className="mx-1 border-l border-border h-5" />
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
            drawMode
              ? 'bg-accent-blue/20 text-accent-blue border-accent-blue/40'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => {
            setDrawMode(v => !v)
            setDrawPoints([])
          }}
          title="Dibujar trendline: clic en 2+ puntos y después 'Trazar'"
        >
          <Pencil size={12} /> Dibujar
        </button>
        {drawMode && (
          <div className="flex items-center gap-1">
            {(['support', 'resistance', 'target', 'note'] as TrendlineKind[]).map(k => {
              const meta = { support: { c: '#22c55e', i: '🟢' }, resistance: { c: '#ef4444', i: '🔴' }, target: { c: '#eab308', i: '🟡' }, note: { c: '#94a3b8', i: '⚪' } }[k]
              const active = drawKind === k
              return (
                <button
                  key={k}
                  className={`w-6 h-6 rounded border text-xs flex items-center justify-center ${
                    active ? 'border-white' : 'border-border opacity-60 hover:opacity-100'
                  }`}
                  style={{ backgroundColor: active ? `${meta.c}33` : undefined }}
                  onClick={() => setDrawKind(k)}
                  title={k}
                >
                  {meta.i}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {drawMode && (
        <div className="rounded-md border border-accent-blue/30 bg-accent-blue/5 px-3 py-2 text-xs text-text-secondary flex items-center gap-2 flex-wrap">
          <span>
            {drawPoints.length === 0
              ? 'Modo dibujo activo — hacé clic sobre el gráfico para marcar puntos.'
              : <>
                  <b>{drawPoints.length}</b> punto{drawPoints.length === 1 ? '' : 's'} marcado{drawPoints.length === 1 ? '' : 's'}
                  {drawPoints.length >= 2 && <> — pulsá <b>Trazar</b> (o Enter) para guardar.</>}
                  {drawPoints.length < 2  && <> — necesitás al menos 2 puntos.</>}
                </>
            }
          </span>
          <span className="ml-auto flex items-center gap-1.5">
            <button
              onClick={handleCommitTrendline}
              disabled={drawPoints.length < 2}
              className="px-2.5 py-1 rounded border border-accent-blue/40 bg-accent-blue/20 text-accent-blue text-2xs disabled:opacity-40 disabled:cursor-not-allowed"
              title="Guardar la trendline con los puntos marcados (Enter)"
            >
              Trazar
            </button>
            <button
              onClick={handleUndoPoint}
              disabled={drawPoints.length === 0}
              className="px-2.5 py-1 rounded border border-border text-text-secondary text-2xs disabled:opacity-40 disabled:cursor-not-allowed"
              title="Deshacer el último punto"
            >
              ↶ Deshacer
            </button>
            <button
              onClick={handleCancelDraw}
              disabled={drawPoints.length === 0}
              className="px-2.5 py-1 rounded border border-border text-text-muted text-2xs disabled:opacity-40 disabled:cursor-not-allowed"
              title="Cancelar trazo en progreso (Esc)"
            >
              Cancelar
            </button>
          </span>
        </div>
      )}

      {/* Chart */}
      <div className="card p-1 overflow-hidden relative">
        {chartMode === 'tv' && asset ? (
          <TradingViewChart
            symbol={tvSymbol(asset)}
            interval={tf}
            theme="dark"
            height={520}
          />
        ) : chartMode === 'v2' ? (
          srV2Loading ? (
            <div className="h-80 flex items-center justify-center">
              <p className="text-sm text-text-muted">Calculando S/R V2…</p>
            </div>
          ) : candles.length > 0 ? (
            <PriceChart
              candles={candles}
              freq={tf}
              indicators={v2DynLines}
              zones={[...v2Overlays.zones, ...v2DynZones]}
              dotLayers={v2DotLayers}
              height={480}
              viewStartDate={(() => {
                const minDate = new Date()
                minDate.setFullYear(minDate.getFullYear() - 3)
                return minDate.toISOString().slice(0, 10)
              })()}
            />
          ) : (
            <div className="h-80 flex items-center justify-center">
              <p className="text-sm text-text-muted">Sin datos de precio</p>
            </div>
          )
        ) : candles.length > 0 ? (
          <PriceChart
            candles={candles}
            freq={tf}
            indicators={indicatorLines}
            markers={utBotMarkers}
            dotLayers={dotLayers}
            zones={dynZones}
            userLevels={priceLevels.map(l => ({
              id:    l.id,
              price: l.price,
              kind:  l.kind,
              label: l.label,
            }))}
            userTrendlines={trendlines.map(t => ({
              id:     t.id,
              points: t.points,
              kind:   t.kind,
              label:  t.label,
            }))}
            drawMode={drawMode}
            onDrawPoint={handleDrawPoint}
            drawPreview={drawPoints}
            drawPreviewColor={
              ({ support: '#22c55e', resistance: '#ef4444', target: '#eab308', note: '#94a3b8' } as const)[drawKind]
            }
            onContextMenu={drawMode ? undefined : ({ price, clientX, clientY }) =>
              setCtxMenu({ price, x: clientX, y: clientY })
            }
            height={480}
            viewStartDate={(() => {
              // Auto-zoom desde anchor1 del tier LP, pero minimo 3 anios de historia
              // — si el LP detectado es corto (ej. NVDA con micro-linea reciente),
              // igual se muestra el contexto multi-anio para no "agrandar" el chart.
              const anchor = dynSupports?.long?.anchor1?.fecha
              const minDate = new Date()
              minDate.setFullYear(minDate.getFullYear() - 3)
              const minStr = minDate.toISOString().slice(0, 10)
              if (!anchor) return minStr
              return anchor < minStr ? anchor : minStr
            })()}
          />
        ) : (
          <div className="h-80 flex flex-col items-center justify-center gap-3">
            <p className="text-sm text-text-muted">Sin datos de precio</p>
            {isAdmin && (
              <button
                onClick={handleBackfill}
                disabled={backfilling}
                className="px-4 py-2 rounded bg-accent-blue/20 border border-accent-blue/50 text-accent-blue hover:bg-accent-blue/30 disabled:opacity-50 text-sm"
              >
                {backfilling ? 'Descargando histórico…' : 'Cargar datos (admin)'}
              </button>
            )}
          </div>
        )}
        {/* Line info overlay — tabs por soporte/resistencia */}
        {chartMode === 'local' && candles.length > 0 && (() => {
          const tabs: { id: string; label: string; color: string; tier: DynamicSupportTier | DynamicResistanceTier; type: 'S' | 'R' }[] = []
          if (dynSupports && showDynSupports) {
            const sTiers: [keyof DynamicSupports, string, string][] = [
              ['long', 'S LP', '#00e676'], ['mid', 'S MP', '#ffd54f'], ['short', 'S CP', '#4fc3f7'],
            ]
            for (const [k, lbl, col] of sTiers) {
              if (!dynSupTiers[k as 'long' | 'mid' | 'short']) continue
              const t = dynSupports[k]
              if (t && typeof t === 'object' && 'line_points' in t) tabs.push({ id: `s-${k}`, label: lbl, color: col, tier: t as DynamicSupportTier, type: 'S' })
            }
          }
          if (dynResistances && showDynResistances) {
            const rTiers: [keyof DynamicResistances, string, string][] = [
              ['long', 'R LP', '#ef4444'], ['mid', 'R MP', '#fb923c'], ['short', 'R CP', '#ef4444'],
            ]
            for (const [k, lbl, col] of rTiers) {
              const t = dynResistances[k]
              if (t && typeof t === 'object' && 'line_points' in t) tabs.push({ id: `r-${k}`, label: lbl, color: col, tier: t as DynamicResistanceTier, type: 'R' })
            }
          }
          if (!tabs.length) return null
          const activeTab = lineInfoTab && tabs.find(t => t.id === lineInfoTab) ? lineInfoTab : null
          const selected = activeTab ? tabs.find(t => t.id === activeTab) : null
          const statusColors: Record<string, string> = { ACTIVE: '#22c55e', TESTING: '#eab308', BROKEN: '#ef4444' }
          return (
            <div className="absolute top-2 left-2 z-10 pointer-events-auto" style={{ maxWidth: 280 }}>
              <div className="flex gap-0.5 flex-wrap">
                {tabs.map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => setLineInfoTab(activeTab === tab.id ? null : tab.id)}
                    className="px-1.5 py-0.5 text-2xs font-medium rounded-t transition-colors"
                    style={{
                      background: activeTab === tab.id ? 'rgba(30,34,45,0.95)' : 'rgba(30,34,45,0.6)',
                      color: tab.color,
                      borderBottom: activeTab === tab.id ? `2px solid ${tab.color}` : '2px solid transparent',
                    }}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              {selected && (
                <div
                  className="rounded-b rounded-tr text-2xs leading-relaxed"
                  style={{ background: 'rgba(30,34,45,0.95)', padding: '6px 8px', borderTop: `1px solid ${selected.color}33` }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="font-semibold" style={{ color: selected.color }}>
                      {selected.type === 'S' ? 'Soporte' : 'Resistencia'} {selected.label.split(' ')[1]}
                    </span>
                    <span
                      className="px-1 py-px rounded font-bold"
                      style={{ fontSize: '0.55rem', background: `${statusColors[selected.tier.status]}22`, color: statusColors[selected.tier.status] }}
                    >
                      {selected.tier.status}
                    </span>
                    <span className="text-text-muted ml-auto">{selected.tier.kind ?? (selected.type === 'S' ? 'ascending' : 'descending')}</span>
                  </div>
                  <table className="w-full" style={{ borderSpacing: 0 }}>
                    <tbody className="text-text-secondary">
                      <tr><td className="text-text-muted pr-2">Anchor 1</td><td>{selected.tier.anchor1.fecha}</td><td className="text-right">${fmtPrice(selected.tier.anchor1.value)}</td></tr>
                      <tr><td className="text-text-muted pr-2">Anchor 2</td><td>{selected.tier.anchor2.fecha}</td><td className="text-right">${fmtPrice(selected.tier.anchor2.value)}</td></tr>
                      <tr><td className="text-text-muted pr-2">Proyección</td><td colSpan={2} className="text-right">${fmtPrice(selected.tier.current_value)}</td></tr>
                      <tr>
                        <td className="text-text-muted pr-2">Distancia</td>
                        <td colSpan={2} className="text-right" style={{ color: selected.tier.distance_pct > 0 ? '#22c55e' : '#ef4444' }}>
                          {selected.tier.distance_pct > 0 ? '+' : ''}{selected.tier.distance_pct.toFixed(1)}%
                        </td>
                      </tr>
                      <tr><td className="text-text-muted pr-2">Slope anual</td><td colSpan={2} className="text-right">{selected.tier.slope_annual_pct > 0 ? '+' : ''}{selected.tier.slope_annual_pct.toFixed(1)}%</td></tr>
                      <tr><td className="text-text-muted pr-2">Toques</td><td colSpan={2} className="text-right">{selected.tier.touches}{(selected.tier as any).fallback ? ' ⚠' : ''}</td></tr>
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        })()}
        {/* V2 info overlay — tabs por cada render object */}
        {chartMode === 'v2' && v2Rendered.length > 0 && (() => {
          const tabs = v2Rendered.map(obj => ({
            id: obj.id,
            label: obj.label,
            color: obj.kind === 'horizontal' ? (obj as V2RenderZone).border_color : (obj as V2RenderDiagonal).line_color,
            obj,
          }))
          const activeTab = v2InfoTab && tabs.find(t => t.id === v2InfoTab) ? v2InfoTab : null
          const selected = activeTab ? tabs.find(t => t.id === activeTab) : null
          const tierBadge: Record<string, string> = { primary: 'PRIMARY', secondary: 'SECONDARY', tertiary: 'ACCEL', ghosted: 'GHOST' }
          return (
            <div className="absolute top-2 left-2 z-10 pointer-events-auto" style={{ maxWidth: 320 }}>
              <div className="flex gap-0.5 flex-wrap">
                {tabs.map(tab => (
                  <button
                    key={tab.id}
                    onClick={() => setV2InfoTab(activeTab === tab.id ? null : tab.id)}
                    className="px-1.5 py-0.5 text-2xs font-medium rounded-t transition-colors"
                    style={{
                      background: activeTab === tab.id ? 'rgba(30,34,45,0.95)' : 'rgba(30,34,45,0.6)',
                      color: tab.color,
                      borderBottom: activeTab === tab.id ? `2px solid ${tab.color}` : '2px solid transparent',
                    }}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              {selected && (() => {
                const obj = selected.obj
                const tt = obj.tooltip
                const sc = obj.kind === 'horizontal' ? (obj as V2RenderZone).label_color : (obj as V2RenderDiagonal).label_color
                return (
                  <div className="rounded-b rounded-tr text-2xs leading-relaxed" style={{ background: 'rgba(30,34,45,0.95)', padding: '6px 8px', borderTop: `1px solid ${selected.color}33` }}>
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="font-semibold" style={{ color: selected.color }}>
                        {obj.role === 'support' ? 'Soporte' : 'Resistencia'}
                      </span>
                      <span className="px-1 py-px rounded font-bold" style={{ fontSize: '0.55rem', background: `${sc}22`, color: sc }}>{tt.state}</span>
                      <span className="text-text-muted" style={{ fontSize: '0.55rem' }}>{tierBadge[obj.visual_tier]}</span>
                      <span className="text-text-muted ml-auto">score {tt.score}</span>
                    </div>
                    <table className="w-full" style={{ borderSpacing: 0 }}>
                      <tbody className="text-text-secondary">
                        {obj.kind === 'horizontal' && (
                          <tr><td className="text-text-muted pr-2">Zona</td><td colSpan={2} className="text-right">${(obj as V2RenderZone).zone_min.toFixed(2)} – ${(obj as V2RenderZone).zone_max.toFixed(2)}</td></tr>
                        )}
                        <tr><td className="text-text-muted pr-2">Toques</td><td colSpan={2} className="text-right">{tt.touches}</td></tr>
                        {obj.kind === 'horizontal' && (
                          <tr><td className="text-text-muted pr-2">Rebote prom</td><td colSpan={2} className="text-right">{(tt as V2RenderZone['tooltip']).bounce_pct}%</td></tr>
                        )}
                        {obj.kind === 'diagonal' && (
                          <>
                            <tr>
                              <td className="text-text-muted pr-2">Distancia</td>
                              <td colSpan={2} className="text-right" style={{ color: (tt as any).distance_pct > 0 ? '#22c55e' : '#ef4444' }}>
                                {(tt as any).distance_pct > 0 ? '+' : ''}{(tt as any).distance_pct.toFixed(1)}%
                              </td>
                            </tr>
                            <tr><td className="text-text-muted pr-2">Slope anual</td><td colSpan={2} className="text-right">{(tt as any).slope_annual_pct.toFixed(1)}%/año</td></tr>
                            <tr><td className="text-text-muted pr-2">Violaciones</td><td colSpan={2} className="text-right">{(tt as any).violations}</td></tr>
                          </>
                        )}
                      </tbody>
                    </table>
                    <p className="text-text-muted mt-1" style={{ fontSize: '0.55rem' }}>{tt.explanation}</p>
                  </div>
                )
              })()}
            </div>
          )
        })()}
        {isAdmin && candles.length > 0 && (
          <div className="mt-2 flex justify-end">
            <button
              onClick={handleBackfill}
              disabled={backfilling}
              className="px-2 py-1 rounded text-xs bg-bg-secondary/50 border border-border-subtle text-text-muted hover:text-text-primary disabled:opacity-50"
              title="Re-descargar histórico desde Yahoo (admin)"
            >
              {backfilling ? '…' : '↻ refrescar histórico'}
            </button>
          </div>
        )}
      </div>

      {/* Popover para crear nivel (click-derecho sobre el chart) */}
      {ctxMenu && (
        <AddLevelPopover
          price={ctxMenu.price}
          x={ctxMenu.x}
          y={ctxMenu.y}
          onPick={handleAddLevel}
          onClose={() => setCtxMenu(null)}
        />
      )}

      {/* Panel "Mis niveles" — lista editable de niveles del usuario para este activo */}
      {candles.length > 0 && (
        <MyLevelsPanel
          levels={priceLevels}
          onPatch={handlePatchLevel}
          onDelete={handleDeleteLevel}
        />
      )}

      {/* Panel "Mis trendlines" — lista de líneas de 2 puntos dibujadas por el usuario */}
      {candles.length > 0 && (
        <MyTrendlinesPanel
          lines={trendlines}
          onPatch={handlePatchTrendline}
          onDelete={handleDeleteTrendline}
        />
      )}

      {/* ADX panel — siempre visible bajo el chart */}
      {chartCandles.length > 0 && (
        <ADXPanel
          candles={chartCandles}
          adx={adxData.adx}
          plusDI={adxData.plusDI}
          minusDI={adxData.minusDI}
          height={160}
        />
      )}

      {/* RSI Divergence panels — visibles si la estrategia está activa en cualquiera de los dos combos */}
      {rsiDivergenceActive && chartCandles.length > 0 && (
        <>
          <RSIPanel
            candles={chartCandles}
            rsiValues={rsiValues}
            divergences={divergences}
            height={180}
          />
          <DivergenceInfoPanel
            divergences={divergences}
            currentRsi={currentRsiCalc}
          />
        </>
      )}
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/**
 * Convierte el mercado interno de la BD al prefijo de exchange de TradingView.
 * TradingView acepta "NYSE:BABA", "NASDAQ:GOOGL", "NASDAQ:MELI", etc.
 */
function tvSymbol(asset: IAsset): string {
  const sym = asset.simbolo.toUpperCase()
  const mkt = (asset.mercado ?? '').toUpperCase()
  // Mapeo de mercados conocidos
  const exchangeMap: Record<string, string> = {
    NYSE:   'NYSE',
    NASDAQ: 'NASDAQ',
    AMEX:   'AMEX',
    BCBA:   'BCBA',
    BYMA:   'BCBA',
    OTC:    'OTC',
  }
  const exchange = exchangeMap[mkt] ?? ''
  return exchange ? `${exchange}:${sym}` : sym
}

// ── TrendPullbackBadgeRow ──────────────────────────────────────────────────────
//
// Card compacto que muestra el estado de la última señal trend_pullback.
// Aplica el filtro GAP global del usuario: si la decisión es BUY_CANDIDATE
// y |gap_pct| supera el threshold, transforma a AWAITING_CONFIRMATION
// (sin tocar el backend).

const DECISION_LABEL: Record<string, { label: string; cls: string }> = {
  BUY_CANDIDATE:        { label: 'Compra candidata',     cls: 'text-up bg-up/10 border-up/30' },
  WATCHLIST:            { label: 'Vigilar',              cls: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30' },
  AWAITING_CONFIRMATION:{ label: 'Esperando confirmación', cls: 'text-orange-400 bg-orange-500/10 border-orange-500/30' },
  AVOID:                { label: 'Evitar',               cls: 'text-down bg-down/10 border-down/30' },
  NO_ACTION:            { label: 'Sin acción',           cls: 'text-text-muted bg-surface border-border' },
}

function TrendPullbackBadgeRow({ signal }: { signal: TrendPullbackSignal }) {
  const { threshold } = useGapFilter()
  const { decision: effDecision, gapBlocked } = applyGapFilter(
    signal.decision, signal.gap_pct, threshold,
  )
  const meta = DECISION_LABEL[effDecision] ?? DECISION_LABEL.NO_ACTION

  return (
    <div className="card p-3 md:p-4 flex flex-wrap items-center gap-3 text-xs">
      <span className="text-text-muted uppercase tracking-wider">Trend+Pullback</span>
      <span className={`font-medium px-2 py-0.5 rounded border ${meta.cls}`}>{meta.label}</span>

      {gapBlocked && signal.gap_pct != null && (
        <span
          className="flex items-center gap-1 text-2xs px-1.5 py-0.5 rounded
                     bg-orange-500/10 text-orange-400 border border-orange-500/30"
          title={`Gap de apertura ${signal.gap_pct.toFixed(2)}% supera el filtro (${threshold}%)`}
        >
          <AlertTriangle size={10} /> gap {signal.gap_pct >= 0 ? '+' : ''}{signal.gap_pct.toFixed(2)}%
        </span>
      )}

      <span className="text-text-muted">
        Trend <span className="font-mono text-text-primary">{signal.trend_score}</span>
      </span>
      <span className="text-text-muted">
        Pullback <span className="font-mono text-text-primary">{signal.pullback_score}</span>
      </span>
      <span className="text-text-muted hidden md:inline">{signal.reading}</span>
      <span className="ml-auto text-text-muted text-2xs">{signal.fecha}</span>
    </div>
  )
}

// ── HistoricalLowBadgeRow ─────────────────────────────────────────────────────

const HL_STATE_LABEL: Record<string, { label: string; cls: string }> = {
  NEW_52W_LOW:  { label: 'Nuevo mínimo 52w',    cls: 'text-down bg-down/10 border-down/30' },
  AT_52W_LOW:   { label: 'En mínimo 52w',       cls: 'text-down bg-down/10 border-down/30' },
  NEAR_52W_LOW: { label: 'Cerca de mínimo 52w', cls: 'text-orange-400 bg-orange-500/10 border-orange-500/30' },
}

function HistoricalLowBadgeRow({ signal }: { signal: HistoricalLowSignal }) {
  const meta = HL_STATE_LABEL[signal.setup_state] ?? HL_STATE_LABEL.NEAR_52W_LOW

  return (
    <div className="card p-3 md:p-4 flex flex-wrap items-center gap-3 text-xs">
      <TrendingDown size={14} className="text-down" />
      <span className="text-text-muted uppercase tracking-wider">Mínimos</span>
      <span className={`font-medium px-2 py-0.5 rounded border ${meta.cls}`}>{meta.label}</span>

      {signal.is_all_time_low && (
        <span className="px-2 py-0.5 rounded border text-down bg-down/10 border-down/30 font-medium animate-pulse">
          ALL-TIME LOW
        </span>
      )}

      <span className="text-text-muted">
        Min 52w <span className="font-mono text-text-primary">${signal.low_52w.toFixed(2)}</span>
      </span>
      <span className="text-text-muted">
        Dist <span className="font-mono text-text-primary">{signal.distance_52w_pct?.toFixed(1)}%</span>
      </span>
      <span className="text-text-muted hidden md:inline">{signal.reading}</span>
      <span className="ml-auto text-text-muted text-2xs">{signal.fecha}</span>
    </div>
  )
}

// ── HistoricalHighBadgeRow ────────────────────────────────────────────────────

const HH_STATE_LABEL: Record<string, { label: string; cls: string }> = {
  NEW_52W_HIGH:  { label: 'Nuevo máximo 52w',    cls: 'text-up bg-up/10 border-up/30' },
  AT_52W_HIGH:   { label: 'En máximo 52w',       cls: 'text-up bg-up/10 border-up/30' },
  NEAR_52W_HIGH: { label: 'Cerca de máximo 52w', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
}

function HistoricalHighBadgeRow({ signal }: { signal: HistoricalHighSignal }) {
  const meta = HH_STATE_LABEL[signal.setup_state] ?? HH_STATE_LABEL.NEAR_52W_HIGH

  return (
    <div className="card p-3 md:p-4 flex flex-wrap items-center gap-3 text-xs">
      <TrendingUp size={14} className="text-up" />
      <span className="text-text-muted uppercase tracking-wider">Máximos</span>
      <span className={`font-medium px-2 py-0.5 rounded border ${meta.cls}`}>{meta.label}</span>

      {signal.is_all_time_high && (
        <span className="px-2 py-0.5 rounded border text-up bg-up/10 border-up/30 font-medium animate-pulse">
          ALL-TIME HIGH
        </span>
      )}

      <span className="text-text-muted">
        Max 52w <span className="font-mono text-text-primary">${signal.high_52w.toFixed(2)}</span>
      </span>
      <span className="text-text-muted">
        Dist <span className="font-mono text-text-primary">{signal.distance_52w_pct?.toFixed(1)}%</span>
      </span>
      <span className="text-text-muted hidden md:inline">{signal.reading}</span>
      <span className="ml-auto text-text-muted text-2xs">{signal.fecha}</span>
    </div>
  )
}

// ── KPI mini ───────────────────────────────────────────────────────────────────

function Kpi({ icon, label, value, cls }: {
  icon: React.ReactNode; label: string; value: string; cls?: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1 text-text-muted">
        {icon}
        <span className="text-2xs">{label}</span>
      </div>
      <span className={`font-mono text-sm font-medium text-text-primary ${cls ?? ''}`}>
        {value}
      </span>
    </div>
  )
}

// ── AddLevelPopover ───────────────────────────────────────────────────────────
//
// Popover de 4 presets posicionado en (x,y) absolutos respecto al viewport.
// `price` ya viene calculado desde el coordinateToPrice del chart. Se cierra
// al elegir una opción, al clickear fuera o al presionar Escape.

const LEVEL_PRESETS: { kind: PriceLevelKind; label: string; color: string; icon: string }[] = [
  { kind: 'support',    label: 'Soporte',     color: '#22c55e', icon: '🟢' },
  { kind: 'resistance', label: 'Resistencia', color: '#ef4444', icon: '🔴' },
  { kind: 'target',     label: 'Target',      color: '#eab308', icon: '🟡' },
  { kind: 'note',       label: 'Nota',        color: '#94a3b8', icon: '⚪' },
]

function AddLevelPopover({ price, x, y, onPick, onClose }: {
  price:   number
  x:       number
  y:       number
  onPick:  (kind: PriceLevelKind, price: number) => void
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onDocClick = (e: MouseEvent) => {
      const el = document.getElementById('add-level-popover')
      if (el && !el.contains(e.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey)
    // defer para no capturar el mismo click-derecho que abrió el popover
    const t = window.setTimeout(() => document.addEventListener('mousedown', onDocClick), 0)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDocClick)
      window.clearTimeout(t)
    }
  }, [onClose])

  // Clamp al viewport para no quedar fuera de pantalla
  const WIDTH = 200
  const HEIGHT = 180
  const left = Math.min(x, window.innerWidth  - WIDTH  - 8)
  const top  = Math.min(y, window.innerHeight - HEIGHT - 8)

  return (
    <div
      id="add-level-popover"
      className="fixed z-50 bg-surface border border-border rounded-md shadow-lg p-2 text-xs"
      style={{ left, top, width: WIDTH }}
    >
      <div className="flex items-center justify-between px-1 pb-1.5 mb-1 border-b border-border">
        <span className="text-text-muted">
          Nivel en <span className="font-mono text-text-primary">${price.toFixed(2)}</span>
        </span>
        <button className="text-text-muted hover:text-text-primary" onClick={onClose} title="Cerrar">
          <X size={12} />
        </button>
      </div>
      <div className="flex flex-col gap-0.5">
        {LEVEL_PRESETS.map(p => (
          <button
            key={p.kind}
            onClick={() => onPick(p.kind, price)}
            className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-elevated text-left"
          >
            <span>{p.icon}</span>
            <span className="text-text-primary">{p.label}</span>
            <span
              className="ml-auto w-3 h-0.5 rounded"
              style={{ backgroundColor: p.color }}
            />
          </button>
        ))}
      </div>
    </div>
  )
}

// ── MyLevelsPanel ─────────────────────────────────────────────────────────────
//
// Lista editable de los niveles del usuario para el activo actual. Cada fila
// tiene label (editable inline), precio, kind (dropdown) y borrar. Si no hay
// niveles, muestra un hint explicando cómo crearlos con click-derecho.

const KIND_META: Record<PriceLevelKind, { label: string; color: string; icon: string }> = {
  support:    { label: 'Soporte',     color: '#22c55e', icon: '🟢' },
  resistance: { label: 'Resistencia', color: '#ef4444', icon: '🔴' },
  target:     { label: 'Target',      color: '#eab308', icon: '🟡' },
  note:       { label: 'Nota',        color: '#94a3b8', icon: '⚪' },
}

function MyLevelsPanel({ levels, onPatch, onDelete }: {
  levels:   PriceLevel[]
  onPatch:  (id: number, patch: { price?: number; kind?: PriceLevelKind; label?: string | null }) => void
  onDelete: (id: number) => void
}) {
  return (
    <div className="card p-3 md:p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs uppercase tracking-wider text-text-muted font-medium">
          Mis niveles
        </h3>
        <span className="text-2xs text-text-muted">
          click derecho sobre el chart para agregar
        </span>
      </div>
      {levels.length === 0 ? (
        <p className="text-xs text-text-muted py-2">
          Todavía no marcaste niveles en este activo. Apuntá al precio en el gráfico y hacé click-derecho.
        </p>
      ) : (
        <div className="divide-y divide-border">
          {levels.map(lvl => (
            <LevelRow
              key={lvl.id}
              level={lvl}
              onPatch={patch => onPatch(lvl.id, patch)}
              onDelete={() => onDelete(lvl.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function LevelRow({ level, onPatch, onDelete }: {
  level:    PriceLevel
  onPatch:  (patch: { price?: number; kind?: PriceLevelKind; label?: string | null }) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [labelDraft, setLabelDraft] = useState(level.label ?? '')
  const [priceDraft, setPriceDraft] = useState(String(level.price))
  const meta = KIND_META[level.kind]

  const commit = () => {
    const patch: { price?: number; label?: string | null } = {}
    const newPrice = Number(priceDraft)
    if (Number.isFinite(newPrice) && newPrice > 0 && newPrice !== Number(level.price)) {
      patch.price = newPrice
    }
    const newLabel = labelDraft.trim()
    const oldLabel = (level.label ?? '').trim()
    if (newLabel !== oldLabel) patch.label = newLabel || null
    if (Object.keys(patch).length) onPatch(patch)
    setEditing(false)
  }
  const cancel = () => {
    setLabelDraft(level.label ?? '')
    setPriceDraft(String(level.price))
    setEditing(false)
  }

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs">
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: meta.color }}
        title={meta.label}
      />
      <select
        value={level.kind}
        onChange={e => onPatch({ kind: e.target.value as PriceLevelKind })}
        className="bg-surface border border-border rounded px-1.5 py-0.5 text-2xs text-text-primary"
      >
        {(Object.keys(KIND_META) as PriceLevelKind[]).map(k => (
          <option key={k} value={k}>{KIND_META[k].icon} {KIND_META[k].label}</option>
        ))}
      </select>
      {editing ? (
        <>
          <input
            type="number"
            step="0.01"
            value={priceDraft}
            onChange={e => setPriceDraft(e.target.value)}
            className="w-24 bg-surface border border-border rounded px-1.5 py-0.5 text-2xs font-mono text-text-primary"
          />
          <input
            type="text"
            value={labelDraft}
            onChange={e => setLabelDraft(e.target.value)}
            placeholder="etiqueta (opcional)"
            maxLength={120}
            className="flex-1 min-w-0 bg-surface border border-border rounded px-1.5 py-0.5 text-2xs text-text-primary"
          />
          <button onClick={commit} className="text-up hover:text-up/80" title="Guardar">
            <Check size={13} />
          </button>
          <button onClick={cancel} className="text-text-muted hover:text-text-primary" title="Cancelar">
            <X size={13} />
          </button>
        </>
      ) : (
        <>
          <span className="font-mono text-text-primary w-24">${Number(level.price).toFixed(2)}</span>
          <span className="flex-1 min-w-0 truncate text-text-secondary">
            {level.label || <span className="text-text-muted italic">sin etiqueta</span>}
          </span>
          <button onClick={() => setEditing(true)} className="text-text-muted hover:text-text-primary" title="Editar">
            <Pencil size={12} />
          </button>
          <button onClick={onDelete} className="text-down/80 hover:text-down" title="Borrar">
            <Trash2 size={12} />
          </button>
        </>
      )}
    </div>
  )
}

// ── MyTrendlinesPanel ─────────────────────────────────────────────────────────
//
// Lista de trendlines (2 puntos) del usuario para el activo actual. Se puede
// editar kind (color) y label; los puntos son inmutables — para ajustarlos,
// borrar y redibujar.

function MyTrendlinesPanel({ lines, onPatch, onDelete }: {
  lines:    Trendline[]
  onPatch:  (id: number, patch: { kind?: TrendlineKind; label?: string | null }) => void
  onDelete: (id: number) => void
}) {
  return (
    <div className="card p-3 md:p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs uppercase tracking-wider text-text-muted font-medium">
          Mis trendlines
        </h3>
        <span className="text-2xs text-text-muted">
          activá "Dibujar" y marcá 2 puntos sobre el chart
        </span>
      </div>
      {lines.length === 0 ? (
        <p className="text-xs text-text-muted py-2">
          Todavía no dibujaste trendlines en este activo.
        </p>
      ) : (
        <div className="divide-y divide-border">
          {lines.map(ln => (
            <TrendlineRow
              key={ln.id}
              line={ln}
              onPatch={patch => onPatch(ln.id, patch)}
              onDelete={() => onDelete(ln.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function TrendlineRow({ line, onPatch, onDelete }: {
  line:     Trendline
  onPatch:  (patch: { kind?: TrendlineKind; label?: string | null }) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [labelDraft, setLabelDraft] = useState(line.label ?? '')
  const meta = KIND_META[line.kind]

  const commit = () => {
    const newLabel = labelDraft.trim()
    const oldLabel = (line.label ?? '').trim()
    if (newLabel !== oldLabel) onPatch({ label: newLabel || null })
    setEditing(false)
  }
  const cancel = () => {
    setLabelDraft(line.label ?? '')
    setEditing(false)
  }

  const first = line.points[0]
  const last  = line.points[line.points.length - 1]
  const nPts  = line.points.length
  const slope = first && last && first.t !== last.t
    ? (last.p - first.p) / Math.max(1, (new Date(last.t).getTime() - new Date(first.t).getTime()) / 86400000)
    : 0
  const direction = Math.abs(slope) < 1e-9 ? '→' : (slope > 0 ? '↗' : '↘')

  return (
    <div className="flex items-center gap-2 py-1.5 text-xs">
      <span
        className="w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: meta.color }}
        title={meta.label}
      />
      <select
        value={line.kind}
        onChange={e => onPatch({ kind: e.target.value as TrendlineKind })}
        className="bg-surface border border-border rounded px-1.5 py-0.5 text-2xs text-text-primary"
      >
        {(Object.keys(KIND_META) as TrendlineKind[]).map(k => (
          <option key={k} value={k}>{KIND_META[k].icon} {KIND_META[k].label}</option>
        ))}
      </select>
      <span className="font-mono text-text-secondary text-2xs whitespace-nowrap">
        {first.t} ${Number(first.p).toFixed(2)} {direction} {last.t} ${Number(last.p).toFixed(2)}
        {nPts > 2 && <span className="text-text-muted"> · {nPts} pts</span>}
      </span>
      {editing ? (
        <>
          <input
            type="text"
            value={labelDraft}
            onChange={e => setLabelDraft(e.target.value)}
            placeholder="etiqueta (opcional)"
            maxLength={120}
            className="flex-1 min-w-0 bg-surface border border-border rounded px-1.5 py-0.5 text-2xs text-text-primary"
          />
          <button onClick={commit} className="text-up hover:text-up/80" title="Guardar">
            <Check size={13} />
          </button>
          <button onClick={cancel} className="text-text-muted hover:text-text-primary" title="Cancelar">
            <X size={13} />
          </button>
        </>
      ) : (
        <>
          <span className="flex-1 min-w-0 truncate text-text-secondary">
            {line.label || <span className="text-text-muted italic">sin etiqueta</span>}
          </span>
          <button onClick={() => setEditing(true)} className="text-text-muted hover:text-text-primary" title="Editar">
            <Pencil size={12} />
          </button>
          <button onClick={onDelete} className="text-down/80 hover:text-down" title="Borrar">
            <Trash2 size={12} />
          </button>
        </>
      )}
    </div>
  )
}


// ── ChannelBreakdownBadgeRow ─────────────────────────────────────────────────

const CBD_SIGNAL_LABEL: Record<string, { label: string; cls: string }> = {
  BUY:  { label: 'Compra',  cls: 'text-up bg-up/10 border-up/30' },
  SELL: { label: 'Vender',  cls: 'text-down bg-down/10 border-down/30' },
  WAIT: { label: 'Esperar', cls: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30' },
  SKIP: { label: 'Skip',    cls: 'text-text-muted bg-surface border-border' },
}

const CBD_SCENARIO_LABEL: Record<string, string> = {
  BOUNCE_RETEST: 'Esc.1 — Rebote + Retest',
  NEW_FLOOR:     'Esc.2 — Piso Nuevo',
  BREAKDOWN:     'Esc.3 — Breakdown',
  ABOVE_ZONE:    'Sobre zona',
  BELOW_ZONE:    'Bajo zona',
}

function ChannelBreakdownBadgeRow({ data }: { data: ChannelBreakdown }) {
  const sc = data.best_scenario!
  const sigMeta = CBD_SIGNAL_LABEL[sc.signal] ?? CBD_SIGNAL_LABEL.WAIT
  const scenarioLabel = CBD_SCENARIO_LABEL[sc.scenario] ?? sc.scenario

  return (
    <div className="card p-3 md:p-4 flex flex-wrap items-center gap-3 text-xs">
      <Activity size={14} className="text-accent" />
      <span className="text-text-muted uppercase tracking-wider">Channel Breakdown</span>
      <span className={`font-medium px-2 py-0.5 rounded border ${sigMeta.cls}`}>{sigMeta.label}</span>
      <span className="text-text-muted">{scenarioLabel}</span>

      {sc.entry != null && (
        <span className="text-text-muted">
          Entrada <span className="font-mono text-text-primary">${sc.entry.toFixed(2)}</span>
        </span>
      )}
      {sc.sl != null && (
        <span className="text-text-muted">
          SL <span className="font-mono text-down">${sc.sl.toFixed(2)}</span>
          {sc.sl_pct != null && <span className="text-down"> ({sc.sl_pct.toFixed(1)}%)</span>}
        </span>
      )}

      <span className="text-text-muted hidden md:inline">{sc.description}</span>
      <span className="ml-auto text-text-muted text-2xs">{data.fecha}</span>
    </div>
  )
}
