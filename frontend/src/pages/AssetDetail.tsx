import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, TrendingUp, Activity, BarChart2, Tv2 } from 'lucide-react'
import { api, type AssetDetail as IAsset, type Candle, type Indicator, type LongtermSupport, type HorizontalZonesResponse, type TieredSRResponse } from '@/lib/api'
import { fmtPrice, fmtPct, fmtVol, pctClass, fmt, calcRSI, calcADX } from '@/lib/utils'
import PriceChart, { buildIndicatorLines, type TrendlineStatus, type LongtermSupportLayer, type HorizontalZoneData } from '@/components/detail/PriceChart'
import { SemaphoreBadge } from '@/components/shared/Semaphore'
import { detectDivergences, type Divergence } from '@/lib/divergence'
import RSIPanel from '@/components/detail/RSIPanel'
import DivergenceInfoPanel from '@/components/detail/DivergenceInfoPanel'
import TradingViewChart from '@/components/shared/TradingViewChart'
import ADXPanel from '@/components/detail/ADXPanel'

const STRATEGIES = [
  '(Ninguna)',
  'WMA6 / WMA30 — Swing',
  'BUY_EARLY_SWING — Anticipado',
  'WMA21 / SMA30 — Tendencia media',
  'BUY_CONFIRMATION',
  'RSI Divergence — Señal',
]

const TIMEFRAMES = [
  { label: 'Diario',   value: 'D' as const },
  { label: 'Semanal',  value: 'W' as const },
  { label: 'Mensual',  value: 'M' as const },
]

export default function AssetDetail() {
  const { id }    = useParams()
  const navigate  = useNavigate()
  const accionId  = Number(id)

  const [asset,     setAsset]     = useState<IAsset | null>(null)
  const [candles,   setCandles]   = useState<Candle[]>([])
  const [indicators, setIndicators] = useState<Indicator[]>([])
  const [loading,   setLoading]   = useState(true)
  const [strategy,       setStrategy]       = useState('(Ninguna)')
  const [tf,             setTf]             = useState<'D' | 'W' | 'M'>('W')
  const [showTrendline,       setShowTrendline]       = useState(false)
  const [showResistanceTrend, setShowResistanceTrend] = useState(false)
  const [trendlineStatus, setTrendlineStatus] = useState<{
    support: TrendlineStatus | null
    resistance: TrendlineStatus | null
  }>({ support: null, resistance: null })
  const [chartMode,           setChartMode]           = useState<'local' | 'tv'>('local')
  const [longtermSupport,  setLongtermSupport]  = useState<LongtermSupport | null>(null)
  const [midtermSupport,   setMidtermSupport]   = useState<LongtermSupport | null>(null)
  const [shorttermSupport, setShorttermSupport] = useState<LongtermSupport | null>(null)
  const [showLongterm,     setShowLongterm]     = useState(false)
  const [showMidterm,      setShowMidterm]      = useState(false)
  const [showShortterm,    setShowShortterm]    = useState(false)
  const [showActiveLayers, setShowActiveLayers] = useState(false)
  const [hzonesData,       setHzonesData]       = useState<HorizontalZonesResponse | null>(null)
  const [showHzones,       setShowHzones]       = useState(true)
  const [tieredSR,         setTieredSR]         = useState<TieredSRResponse | null>(null)
  const [showTieredSR,     setShowTieredSR]     = useState(false)
  const [showADX,          setShowADX]          = useState(false)
  useEffect(() => {
    if (!accionId) return
    setLoading(true)
    Promise.allSettled([
      api.asset(accionId),
      api.ohlcvExtended(accionId, 'D'),   // histórico completo diario (20 años) — fuente única
      api.indicators(accionId, 365),
    ]).then(([a, od, ind]) => {
      if (a.status === 'fulfilled')   setAsset(a.value)
      if (od.status === 'fulfilled')  setCandles(od.value.candles)
      if (ind.status === 'fulfilled') setIndicators(ind.value.indicators)
    }).finally(() => setLoading(false))

    // Fetch soportes estructurales en paralelo (no bloquean el render del chart)
    Promise.allSettled([
      api.longtermSupport(accionId, 'long_term'),
      api.longtermSupport(accionId, 'mid_term'),
      api.longtermSupport(accionId, 'short_term'),
    ]).then(([lt, mt, st]) => {
      setLongtermSupport(lt.status === 'fulfilled' ? lt.value : null)
      setMidtermSupport(mt.status === 'fulfilled' ? mt.value : null)
      setShorttermSupport(st.status === 'fulfilled' ? st.value : null)
    })

    // Fetch zonas horizontales + tiered SR
    api.horizontalZones(accionId)
      .then(data => setHzonesData(data))
      .catch(() => setHzonesData(null))
    api.tieredSR(accionId)
      .then(data => setTieredSR(data))
      .catch(() => setTieredSR(null))
  }, [accionId])

  const rsiValues   = candles.length ? calcRSI(candles.map(c => Number(c.close))) : []
  const divergences = candles.length
    ? detectDivergences(candles, rsiValues)
    : [] as Divergence[]
  const currentRsiCalc = rsiValues.length ? (rsiValues[rsiValues.length - 1] ?? null) : null
  const adxData = candles.length ? calcADX(candles) : { adx: [], plusDI: [], minusDI: [] }

  const indicatorLines = buildIndicatorLines(candles, strategy)

  function toLayer(s: LongtermSupport | null): LongtermSupportLayer | null {
    if (!s) return null
    return { line_points: s.line_points, status: s.status, timeframe_used: s.timeframe_used }
  }
  function toResistanceLayer(s: LongtermSupport | null): LongtermSupportLayer | null {
    if (!s || !s.resistance_line_points?.length) return null
    return {
      line_points:    s.resistance_line_points,
      status:         s.resistance_status ?? 'NO_SUPPORT',
      timeframe_used: s.timeframe_used,
    }
  }
  function toActiveLayer(s: LongtermSupport | null): LongtermSupportLayer | null {
    if (!s || !s.active_line_points?.length) return null
    return {
      line_points:    s.active_line_points,
      status:         s.active_status ?? 'NO_SUPPORT',
      timeframe_used: s.timeframe_used,
    }
  }
  function toActiveResistanceLayer(s: LongtermSupport | null): LongtermSupportLayer | null {
    if (!s || !s.active_resistance_line_points?.length) return null
    return {
      line_points:    s.active_resistance_line_points,
      status:         s.active_resistance_status ?? 'NO_SUPPORT',
      timeframe_used: s.timeframe_used,
    }
  }
  const longtermLayer           = showLongterm  ? toLayer(longtermSupport)  : null
  const longtermResistanceLayer = showLongterm  ? toResistanceLayer(longtermSupport) : null
  const midtermLayer            = showMidterm   ? toLayer(midtermSupport)   : null
  const shorttermLayer          = showShortterm ? toLayer(shorttermSupport) : null
  const activeLayer             = showActiveLayers ? toActiveLayer(longtermSupport) : null
  const activeResistanceLayer   = showActiveLayers ? toActiveResistanceLayer(longtermSupport) : null

  // Zonas horizontales: unir soporte + resistencia en un solo array para el chart
  const horizontalZones: HorizontalZoneData[] | null = showHzones && hzonesData?.status === 'OK'
    ? [
        ...hzonesData.support_zones.map(z => ({
          zone_low: z.zone_low, zone_high: z.zone_high, center: z.center,
          total_touches: z.total_touches, recent_touches: z.recent_touches,
          score: z.score, type: 'support' as const, rank: z.rank,
        })),
        ...hzonesData.resistance_zones.map(z => ({
          zone_low: z.zone_low, zone_high: z.zone_high, center: z.center,
          total_touches: z.total_touches, recent_touches: z.recent_touches,
          score: z.score, type: 'resistance' as const, rank: z.rank,
        })),
      ]
    : null


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
      <div className="card p-5">
        <div className="flex flex-wrap items-start gap-6">
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
          <div className="grid grid-cols-4 gap-4 mt-5 pt-4 border-t border-border">
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

      {/* Filtros Compra Swing */}
      {candles.length > 0 && (
        <SwingFilterPanel candles={candles} rsi={lastInd?.rsi14 ?? null} />
      )}

      {/* Controles del gráfico */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Estrategia */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-muted">Estrategia</span>
          <div className="flex items-center gap-0 border border-border rounded-md overflow-hidden">
            {STRATEGIES.map(s => (
              <button
                key={s}
                className={`px-3 py-1.5 text-xs transition-colors whitespace-nowrap ${
                  strategy === s
                    ? 'bg-accent text-white'
                    : 'text-text-secondary hover:text-text-primary hover:bg-elevated'
                }`}
                onClick={() => setStrategy(s)}
              >
                {s === '(Ninguna)' ? 'Ninguna' : s}
              </button>
            ))}
          </div>
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

        {/* Trendlines dinámicas */}
        <div className="flex items-center gap-2">
          {/* Toggle soporte */}
          <button
            className={`px-3 py-1.5 text-xs rounded-md border transition-colors flex items-center gap-1.5 ${
              showTrendline
                ? 'border-[#26a69a]/40 text-[#26a69a] bg-[#26a69a]/10'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
            onClick={() => setShowTrendline(v => !v)}
          >
            <span className="w-3 h-0.5 block rounded bg-current" style={{ transform: 'rotate(-20deg)' }} />
            Soporte din.
          </button>
          {/* Badge estado soporte */}
          {showTrendline && trendlineStatus.support && (
            <TrendlineBadge status={trendlineStatus.support} />
          )}

          {/* Toggle resistencia */}
          <button
            className={`px-3 py-1.5 text-xs rounded-md border transition-colors flex items-center gap-1.5 ${
              showResistanceTrend
                ? 'border-orange-500/40 text-orange-400 bg-orange-500/10'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
            onClick={() => setShowResistanceTrend(v => !v)}
          >
            <span className="w-3 h-0.5 block rounded bg-current" style={{ transform: 'rotate(20deg)' }} />
            Resistencia din.
          </button>
          {/* Badge estado resistencia */}
          {showResistanceTrend && trendlineStatus.resistance && (
            <TrendlineBadge status={trendlineStatus.resistance} />
          )}
        </div>

        {/* Soportes estructurales (motor long-term) */}
        <div className="flex items-center gap-2">
          <StructuralToggle
            label="L"
            title="Soporte largo plazo"
            active={showLongterm}
            activeColor="#5b6cf6"
            support={longtermSupport}
            onToggle={() => setShowLongterm(v => !v)}
          />
          <StructuralToggle
            label="M"
            title="Soporte medio plazo"
            active={showMidterm}
            activeColor="#60a5fa"
            support={midtermSupport}
            onToggle={() => setShowMidterm(v => !v)}
          />
          <StructuralToggle
            label="C"
            title="Soporte corto plazo"
            active={showShortterm}
            activeColor="#22d3ee"
            support={shorttermSupport}
            onToggle={() => setShowShortterm(v => !v)}
          />
          {/* Toggle capas activas (soporte operativo + resistencia operativa) */}
          <button
            title="Soporte/Resistencia operativa activa (ultimos 7 anos)"
            className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors font-mono font-semibold ${
              showActiveLayers
                ? 'border-transparent text-white'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
            style={showActiveLayers ? { backgroundColor: '#84cc16', borderColor: '#84cc16' } : {}}
            onClick={() => setShowActiveLayers(v => !v)}
          >
            A
          </button>
          {showActiveLayers && (
            <span className="text-2xs text-text-muted font-mono">activo</span>
          )}

          {/* Toggle zonas horizontales */}
          <button
            title="Zonas horizontales de soporte/resistencia"
            className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors font-mono font-semibold ${
              showHzones
                ? 'border-transparent text-white'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
            style={showHzones ? { backgroundColor: '#26a69a', borderColor: '#26a69a' } : {}}
            onClick={() => setShowHzones(v => !v)}
          >
            Z
          </button>
          {showHzones && hzonesData?.status === 'OK' && (
            <span className="text-2xs text-text-muted font-mono">
              {hzonesData.support_zones.length}S/{hzonesData.resistance_zones.length}R
            </span>
          )}

          {/* Toggle tiered S/R */}
          <button
            title="S/R behavioral: historical / accelerated / tactical"
            className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors font-mono font-semibold ${
              showTieredSR
                ? 'border-transparent text-white'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
            style={showTieredSR ? { backgroundColor: '#e879f9', borderColor: '#e879f9' } : {}}
            onClick={() => setShowTieredSR(v => !v)}
          >
            T
          </button>
          {showTieredSR && tieredSR && (
            <span className="text-2xs text-text-muted font-mono">tiered</span>
          )}
        </div>

        {/* ADX toggle */}
        <button
          title="ADX — Fuerza de tendencia"
          className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors font-mono font-semibold ${
            showADX
              ? 'border-transparent text-black bg-[#facc15]'
              : 'border-border text-text-muted hover:text-text-secondary'
          }`}
          onClick={() => setShowADX(v => !v)}
        >
          ADX
        </button>

        {/* Leyenda de líneas activas */}
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
            showTrendline={showTrendline}
            showResistanceTrend={showResistanceTrend}
            debugSegmentOnly={false}
            height={480}
            onTrendlineResult={(sup, res) => setTrendlineStatus({ support: sup, resistance: res })}
            longtermLayer={longtermLayer}
            longtermResistanceLayer={longtermResistanceLayer}
            midtermLayer={midtermLayer}
            shorttermLayer={shorttermLayer}
            activeLayer={activeLayer}
            activeResistanceLayer={activeResistanceLayer}
            horizontalZones={horizontalZones}
            tieredSR={showTieredSR ? tieredSR : null}
          />
        ) : (
          <div className="h-80 flex items-center justify-center">
            <p className="text-sm text-text-muted">Sin datos de precio</p>
          </div>
        )}
      </div>

      {/* ADX panel */}
      {showADX && candles.length > 0 && (
        <ADXPanel
          candles={candles}
          adx={adxData.adx}
          plusDI={adxData.plusDI}
          minusDI={adxData.minusDI}
          height={180}
        />
      )}

      {/* RSI Divergence panels — solo visibles cuando la estrategia está activa */}
      {strategy === 'RSI Divergence — Señal' && candles.length > 0 && (
        <>
          <RSIPanel
            candles={candles}
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

// ── TrendlineBadge ─────────────────────────────────────────────────────────────

const TRENDLINE_BADGE: Record<TrendlineStatus, { label: string; cls: string }> = {
  ACTIVE_SUPPORT:           { label: 'Activo',          cls: 'text-[#26a69a] bg-[#26a69a]/10 border-[#26a69a]/30' },
  TESTING_SUPPORT:          { label: 'En test',         cls: 'text-green-400 bg-green-400/10 border-green-400/30' },
  BROKEN_SUPPORT:           { label: 'Roto',            cls: 'text-red-400 bg-red-400/10 border-red-400/30' },
  NO_VALID_ACTIVE_SUPPORT:  { label: 'Sin estructura',  cls: 'text-text-muted bg-surface border-border' },
  ACTIVE_RESISTANCE:        { label: 'Activa',          cls: 'text-orange-400 bg-orange-400/10 border-orange-400/30' },
  TESTING_RESISTANCE:       { label: 'En test',         cls: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/30' },
  BROKEN_RESISTANCE:        { label: 'Rota',            cls: 'text-red-400 bg-red-400/10 border-red-400/30' },
  NO_VALID_ACTIVE_RESISTANCE:{ label: 'Sin estructura', cls: 'text-text-muted bg-surface border-border' },
}

function TrendlineBadge({ status }: { status: TrendlineStatus }) {
  const { label, cls } = TRENDLINE_BADGE[status]
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${cls}`}>
      {label}
    </span>
  )
}

// ── StructuralToggle ───────────────────────────────────────────────────────────

const STRUCTURAL_STATUS: Record<string, { label: string; cls: string }> = {
  ACTIVE:     { label: 'Activo',   cls: 'text-up bg-up/10 border-up/30' },
  TESTING:    { label: 'Test',     cls: 'text-warn bg-warn/10 border-warn/30' },
  BROKEN:     { label: 'Roto',     cls: 'text-down bg-down/10 border-down/30' },
  NO_SUPPORT: { label: 'Sin estr', cls: 'text-text-muted bg-surface border-border' },
}

function StructuralToggle({
  label, title, active, activeColor, support, onToggle,
}: {
  label:       string
  title:       string
  active:      boolean
  activeColor: string
  support:     LongtermSupport | null
  onToggle:    () => void
}) {
  const st = support ? (STRUCTURAL_STATUS[support.status] ?? STRUCTURAL_STATUS.NO_SUPPORT) : null
  const tf = support?.timeframe_used ?? null

  return (
    <div className="flex items-center gap-1">
      <button
        title={title}
        className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors font-mono font-semibold ${
          active
            ? 'border-transparent text-white'
            : 'border-border text-text-muted hover:text-text-secondary'
        }`}
        style={active ? { backgroundColor: activeColor, borderColor: activeColor } : {}}
        onClick={onToggle}
      >
        {label}
      </button>
      {/* tf badge */}
      {tf && (
        <span className="text-2xs text-text-muted font-mono">{tf}</span>
      )}
      {/* status badge — solo cuando el toggle está activo */}
      {active && st && support?.status !== 'NO_SUPPORT' && (
        <span className={`text-2xs font-medium px-1.5 py-0.5 rounded border ${st.cls}`}>
          {st.label}
        </span>
      )}
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

// ── Panel Filtros Compra Swing ──────────────────────────────────────────────────

function SwingFilterPanel({ candles, rsi }: { candles: Candle[]; rsi: number | null }) {
  const currentPrice = candles.length ? Number(candles[candles.length - 1].close) : 0

  const nearestResistance = (() => {
    if (!candles.length) return null
    const window = 5
    const pivots: number[] = []
    for (let i = window; i < candles.length - window; i++) {
      const h = Number(candles[i].high)
      if (h <= currentPrice) continue
      const leftOk  = candles.slice(i - window, i).every(c => Number(c.high) <= h)
      const rightOk = candles.slice(i + 1, i + window + 1).every(c => Number(c.high) <= h)
      if (leftOk && rightOk) pivots.push(h)
    }
    const above = pivots.filter(p => p > currentPrice)
    return above.length ? Math.min(...above) : null
  })()

  const upsidePct = nearestResistance
    ? ((nearestResistance - currentPrice) / currentPrice * 100)
    : null

  const rsiOk    = rsi != null && rsi < 50
  const upsideOk = upsidePct != null && upsidePct >= 15

  return (
    <div className="card p-4">
      <p className="text-xs font-semibold text-text-secondary mb-3 uppercase tracking-wide">Filtros Compra Swing</p>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-muted">RSI 14</span>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium text-text-primary">
              {rsi != null ? rsi.toFixed(1) : '—'}
            </span>
            <span className={`text-xs font-medium ${rsiOk ? 'text-up' : 'text-down'}`}>
              {rsiOk ? '✓ < 50' : '✗ ≥ 50'}
            </span>
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-muted">Recorrido a resistencia</span>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium text-text-primary">
              {upsidePct != null ? `${upsidePct.toFixed(1)}%` : '—'}
            </span>
            <span className={`text-xs font-medium ${upsideOk ? 'text-up' : 'text-down'}`}>
              {upsideOk ? '✓ ≥ 15%' : '✗ < 15%'}
            </span>
          </div>
        </div>
        {nearestResistance && (
          <p className="text-2xs text-text-muted mt-1">
            Resistencia más cercana: ${nearestResistance.toFixed(2)}
          </p>
        )}
        <div className={`mt-3 py-1.5 px-3 rounded text-xs font-medium text-center ${
          rsiOk && upsideOk
            ? 'bg-up/10 text-up border border-up/30'
            : 'bg-surface text-text-muted border border-border'
        }`}>
          {rsiOk && upsideOk ? '✓ Señal habilitada' : '✗ Señal no habilitada'}
        </div>
      </div>
    </div>
  )
}
