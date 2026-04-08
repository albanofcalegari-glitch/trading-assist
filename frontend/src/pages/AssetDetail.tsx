import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, TrendingUp, Activity, BarChart2, Tv2, AlertTriangle } from 'lucide-react'
import { api, type AssetDetail as IAsset, type Candle, type Indicator, type CompanyInfo, type TrendPullbackSignal } from '@/lib/api'
import { fmtPrice, fmtPct, pctClass, fmt, calcRSI, calcADX } from '@/lib/utils'
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
  const [strategyA, setStrategyA] = useState('(Ninguna)')
  const [strategyB, setStrategyB] = useState('(Ninguna)')
  const [tf,        setTf]        = useState<'D' | 'W' | 'M'>('W')
  const [chartMode, setChartMode] = useState<'local' | 'tv'>('local')
  const [companyInfo,    setCompanyInfo]    = useState<CompanyInfo | null>(null)
  const [companyLoading, setCompanyLoading] = useState(true)
  const [tpSignal,       setTpSignal]       = useState<TrendPullbackSignal | null>(null)

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
  }, [accionId])

  const rsiValues   = candles.length ? calcRSI(candles.map(c => Number(c.close))) : []
  const divergences = candles.length
    ? detectDivergences(candles, rsiValues)
    : [] as Divergence[]
  const currentRsiCalc = rsiValues.length ? (rsiValues[rsiValues.length - 1] ?? null) : null
  const adxData = candles.length ? calcADX(candles) : { adx: [], plusDI: [], minusDI: [] }

  const activeStrategies = [strategyA, strategyB].filter(s => s !== '(Ninguna)')
  const indicatorLines = buildIndicatorLines(candles, activeStrategies)
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
            height={480}
          />
        ) : (
          <div className="h-80 flex items-center justify-center">
            <p className="text-sm text-text-muted">Sin datos de precio</p>
          </div>
        )}
      </div>

      {/* ADX panel — siempre visible bajo el chart */}
      {candles.length > 0 && (
        <ADXPanel
          candles={candles}
          adx={adxData.adx}
          plusDI={adxData.plusDI}
          minusDI={adxData.minusDI}
          height={160}
        />
      )}

      {/* RSI Divergence panels — visibles si la estrategia está activa en cualquiera de los dos combos */}
      {rsiDivergenceActive && candles.length > 0 && (
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

