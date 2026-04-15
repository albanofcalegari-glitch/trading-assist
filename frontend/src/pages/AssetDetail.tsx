import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, TrendingUp, TrendingDown, Activity, BarChart2, Tv2, AlertTriangle } from 'lucide-react'
import { api, type AssetDetail as IAsset, type Candle, type Indicator, type CompanyInfo, type TrendPullbackSignal, type ChannelData, type ChannelItem, type HistoricalLowSignal, type HistoricalHighSignal, type DynamicSupports } from '@/lib/api'
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
  const [chartMode, setChartMode] = useState<'local' | 'tv'>('local')
  const [companyInfo,    setCompanyInfo]    = useState<CompanyInfo | null>(null)
  const [companyLoading, setCompanyLoading] = useState(true)
  const [tpSignal,       setTpSignal]       = useState<TrendPullbackSignal | null>(null)
  const [channelData,    setChannelData]    = useState<ChannelData | null>(null)
  const [showChannels,   setShowChannels]   = useState(true)
  const [hlSignal,       setHlSignal]       = useState<HistoricalLowSignal | null>(null)
  const [hhSignal,       setHhSignal]       = useState<HistoricalHighSignal | null>(null)
  const [dynSupports,    setDynSupports]    = useState<DynamicSupports | null>(null)
  const [showDynSupports,setShowDynSupports]= useState(true)
  const [showUtBot,      setShowUtBot]      = useState(false)

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

    // Fetch dynamic supports (long/mid/short trendlines ascendentes en log-space)
    api.dynamicSupports(accionId)
      .then(setDynSupports)
      .catch(() => setDynSupports(null))
  }, [accionId])

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
      // line_points viene en fechas semanales; interpolo en log-space a cada fecha diaria
      // dentro del rango [primera, última] fecha del tier.
      const pts = tier.line_points
      const tsValues = pts.map(p => Date.parse(p.fecha))
      const logValues = pts.map(p => Math.log(p.value))
      const firstTs = tsValues[0]
      const lastTs  = tsValues[tsValues.length - 1]
      const values = candleDates.map(d => {
        const t = Date.parse(d)
        if (t < firstTs || t > lastTs) return null
        // búsqueda binaria del intervalo [i, i+1] que contiene t
        let lo = 0, hi = tsValues.length - 1
        while (hi - lo > 1) {
          const mid = (lo + hi) >> 1
          if (tsValues[mid] <= t) lo = mid
          else hi = mid
        }
        const t0 = tsValues[lo], t1 = tsValues[hi]
        if (t1 === t0) return Math.exp(logValues[lo])
        const frac = (t - t0) / (t1 - t0)
        return Math.exp(logValues[lo] + frac * (logValues[hi] - logValues[lo]))
      })
      indicatorLines.push({
        dates:  candleDates,
        values,
        color,
        label:  `Soporte ${label}`,
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
            chartMode === 'tv'
              ? 'bg-accent text-white border-accent'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setChartMode('tv')}
        >
          <Tv2 size={12} /> TradingView Live
        </button>
        <span className="mx-1 border-l border-border h-5" />
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
      </div>

      {/* Chart */}
      <div className="card p-1 overflow-hidden">
        {chartMode === 'tv' && asset ? (
          <TradingViewChart
            symbol={tvSymbol(asset)}
            interval={tf}
            theme="dark"
            height={520}
          />
        ) : candles.length > 0 ? (
          <PriceChart
            candles={candles}
            freq={tf}
            indicators={indicatorLines}
            markers={utBotMarkers}
            zones={dynZones}
            height={480}
            viewStartDate={dynSupports?.long?.anchor1?.fecha}
          />
        ) : (
          <div className="h-80 flex items-center justify-center">
            <p className="text-sm text-text-muted">Sin datos de precio</p>
          </div>
        )}
      </div>

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

