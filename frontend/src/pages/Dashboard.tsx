import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw, Filter, AlertTriangle, TrendingDown, TrendingUp, Activity, Search, X } from 'lucide-react'
import { api, type Mover, type Asset, type MarketContext } from '@/lib/api'
import { fmtPrice, fmtPct, pctClass } from '@/lib/utils'
import { useGapFilter, GAP_OPTIONS, type GapThreshold } from '@/lib/gapFilter'
import MoverBlock from '@/components/dashboard/MoverBlock'
import AssetTable from '@/components/dashboard/AssetTable'

const MARKETS = [
  { value: '',     label: 'Todos' },
  { value: 'USA',  label: 'USA' },
  { value: 'BYMA', label: 'BYMA' },
]

function QuickSearch() {
  const navigate = useNavigate()
  const [query, setQuery]     = useState('')
  const [results, setResults] = useState<Asset[]>([])
  const [open, setOpen]       = useState(false)
  const [loading, setLoading] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const ref   = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

  useEffect(() => {
    clearTimeout(timer.current)
    if (query.trim().length < 1) { setResults([]); setOpen(false); return }
    setLoading(true)
    timer.current = setTimeout(async () => {
      try {
        const { items } = await api.assets('', query, 0, 8)
        setResults(items)
        setOpen(true)
      } finally { setLoading(false) }
    }, 300)
  }, [query])

  const go = (id: number) => { setQuery(''); setOpen(false); navigate(`/asset/${id}`) }

  return (
    <div ref={ref} className="relative w-72">
      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
      <input
        className="input pl-9 pr-8 h-10 text-sm"
        placeholder="Buscar activo..."
        value={query}
        onChange={e => setQuery(e.target.value)}
        onFocus={() => results.length && setOpen(true)}
      />
      {query && (
        <button
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
          onClick={() => { setQuery(''); setOpen(false) }}
        ><X size={12} /></button>
      )}
      {open && results.length > 0 && (
        <div className="absolute top-full mt-1 w-full z-50 card-elevated overflow-hidden shadow-xl rounded-lg border border-border">
          {results.map(a => (
            <button
              key={a.accion_id}
              className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-elevated/70 border-b border-border-subtle last:border-0 text-left transition-colors"
              onClick={() => go(a.accion_id)}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-medium text-sm text-text-primary">{a.simbolo}</span>
                  <span className="text-2xs text-text-muted">{a.mercado}</span>
                </div>
                <p className="text-2xs text-text-secondary truncate mt-0.5">{a.nombre}</p>
              </div>
              <div className="text-right shrink-0">
                <p className="font-mono text-xs text-text-primary">{fmtPrice(a.precio)}</p>
                <p className={`text-2xs ${pctClass(a.pct_cambio)}`}>{fmtPct(a.pct_cambio)}</p>
              </div>
            </button>
          ))}
        </div>
      )}
      {open && loading && (
        <div className="absolute top-full mt-1 w-full z-50 card-elevated px-3 py-2 text-xs text-text-muted">Buscando...</div>
      )}
    </div>
  )
}

function GapFilterControl() {
  const { threshold, setThreshold } = useGapFilter()
  return (
    <div className="flex items-center gap-1 text-2xs" title="Filtro de gap de apertura">
      <span className="text-text-muted uppercase tracking-wider">Gap</span>
      <div className="flex items-center border border-border rounded-md overflow-hidden">
        {GAP_OPTIONS.map(opt => (
          <button
            key={opt}
            onClick={() => setThreshold(opt as GapThreshold)}
            className={`px-2 py-1 transition-colors ${
              threshold === opt
                ? 'bg-accent text-white'
                : 'text-text-secondary hover:text-text-primary hover:bg-elevated'
            }`}
          >{opt === 0 ? 'Off' : `${opt}%`}</button>
        ))}
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [movers, setMovers] = useState<{
    usaUp: Mover[]; usaDown: Mover[]
    bymaUp: Mover[]; bymaDown: Mover[]
  }>({ usaUp: [], usaDown: [], bymaUp: [], bymaDown: [] })

  const [items,   setItems]   = useState<Asset[]>([])
  const [total,   setTotal]   = useState(0)
  const [pages,   setPages]   = useState(1)
  const [page,    setPage]    = useState(0)
  const [market,  setMarket]  = useState('')
  const [search,  setSearch]  = useState('')
  const [draft,   setDraft]   = useState('')
  const [loading, setLoading] = useState(false)
  const [mLoading, setMLoading] = useState(false)
  const [ctx,         setCtx]         = useState<MarketContext | null>(null)
  const [ctxLoading,  setCtxLoading]  = useState(false)
  const [ctxUpdated,  setCtxUpdated]  = useState<Date | null>(null)

  // Movers
  const loadMovers = useCallback(async () => {
    setMLoading(true)
    try {
      const [uU, uD, bU, bD] = await Promise.all([
        api.movers('USA',  'up'),
        api.movers('USA',  'down'),
        api.movers('BYMA', 'up'),
        api.movers('BYMA', 'down'),
      ])
      setMovers({ usaUp: uU.items, usaDown: uD.items, bymaUp: bU.items, bymaDown: bD.items })
    } finally {
      setMLoading(false)
    }
  }, [])

  // Market context — fetch + auto-refresh cada 3 min
  const loadCtx = useCallback(async () => {
    setCtxLoading(true)
    try {
      const c = await api.marketContext()
      setCtx(c)
      // Preferir updated_at del server (epoch unix s); si no viene, fallback a now()
      setCtxUpdated(c.updated_at ? new Date(c.updated_at * 1000) : new Date())
    } catch {} finally {
      setCtxLoading(false)
    }
  }, [])

  // Tabla de activos
  const loadAssets = useCallback(async (mkt: string, q: string, pg: number) => {
    setLoading(true)
    try {
      const res = await api.assets(mkt, q, pg)
      setItems(res.items)
      setTotal(res.total)
      setPages(res.pages)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadMovers()
  }, [loadMovers])

  // Indicadores: fetch inmediato + auto-refresh cada 3 min
  // (también re-fetchea cuando la pestaña vuelve a estar visible)
  useEffect(() => {
    loadCtx()
    const id = setInterval(loadCtx, 3 * 60 * 1000)
    const onVisible = () => {
      if (document.visibilityState === 'visible') loadCtx()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [loadCtx])

  useEffect(() => {
    setPage(0)
    loadAssets(market, search, 0)
  }, [market, search, loadAssets])

  useEffect(() => {
    loadAssets(market, search, page)
  }, [page])                                    // eslint-disable-line

  // Búsqueda con debounce
  useEffect(() => {
    const t = setTimeout(() => setSearch(draft), 350)
    return () => clearTimeout(t)
  }, [draft])

  return (
    <div className="space-y-5">
      {/* Title row: Dashboard + search + controls */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-5">
          <h1 className="text-xl font-heading font-bold text-text-primary whitespace-nowrap">Dashboard</h1>
          <QuickSearch />
        </div>
        <div className="flex items-center gap-3">
          <GapFilterControl />
          <button
            className="btn-ghost text-xs gap-1.5"
            onClick={() => { loadCtx(); loadMovers(); loadAssets(market, search, page) }}
          >
            <RefreshCw size={13} className={ctxLoading || mLoading ? 'animate-spin' : ''} />
            Actualizar
          </button>
        </div>
      </div>

      {/* Resumen de mercado */}
      <div>
        <p className="text-xs text-text-muted mb-3">Resumen del mercado</p>
        {ctx && <MarketBar ctx={ctx} updatedAt={ctxUpdated} loading={ctxLoading} />}
      </div>

      {/* Movers — 1 col móvil, 2 cols sm, 4 cols xl */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3 md:gap-4">
        <MoverBlock title="Top alza — USA"  items={movers.usaUp}   isUp loading={mLoading} />
        <MoverBlock title="Top baja — USA"  items={movers.usaDown} isUp={false} loading={mLoading} />
        <MoverBlock title="Top alza — BYMA" items={movers.bymaUp}  isUp loading={mLoading} />
        <MoverBlock title="Top baja — BYMA" items={movers.bymaDown} isUp={false} loading={mLoading} />
      </div>

      {/* Filtros + tabla */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[160px] max-w-xs relative">
            <Filter size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              className="input pl-8 h-8 text-xs"
              placeholder="Filtrar por símbolo o nombre..."
              value={draft}
              onChange={e => setDraft(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-1 border border-border rounded-md overflow-hidden">
            {MARKETS.map(m => (
              <button
                key={m.value}
                className={`px-3 py-1.5 text-xs transition-colors ${
                  market === m.value
                    ? 'bg-accent text-white'
                    : 'text-text-secondary hover:text-text-primary hover:bg-elevated'
                }`}
                onClick={() => setMarket(m.value)}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <AssetTable
          items={items}
          total={total}
          page={page}
          pages={pages}
          onPage={setPage}
          loading={loading}
        />
      </div>
    </div>
  )
}

// ── Market Context Bar ──────────────────────────────────────────────────────────

const REGIME_LABEL: Record<number, string> = { 0: 'Lateral', 1: 'Alcista', 2: 'Bajista' }
const REGIME_COLOR: Record<number, string> = {
  0: 'text-yellow-400',
  1: 'text-up',
  2: 'text-down',
}

function MarketBar({ ctx, updatedAt, loading }: {
  ctx: MarketContext; updatedAt: Date | null; loading: boolean
}) {
  const vix      = ctx.vix_level ?? 0
  const redFlag  = vix > 30
  const vixPct   = ctx.vix_percentile_1y != null ? Math.round(ctx.vix_percentile_1y * 100) : null
  const regime   = ctx.market_regime ?? 0

  // Frescura: > 5 min sin update O fallback de DB → stale
  const ageMs   = updatedAt ? Date.now() - updatedAt.getTime() : null
  const ageMin  = ageMs != null ? Math.floor(ageMs / 60_000) : null
  const isStale = ctx.source === 'db_fallback' || ageMs == null || ageMs > 5 * 60 * 1000
  const ageLbl  = ageMin == null
    ? '—'
    : ageMin < 1 ? 'recién'
    : ageMin < 60 ? `hace ${ageMin} min`
    : `hace ${Math.floor(ageMin / 60)}h`

  return (
    <div className={`flex flex-wrap items-center gap-3 px-4 py-3 rounded-lg border text-xs ${
      redFlag
        ? 'bg-down/10 border-down/40'
        : isStale
        ? 'bg-surface border-yellow-500/40'
        : 'bg-surface border-border'
    }`}>

      {/* VIX */}
      <div className={`flex items-center gap-2 font-mono ${redFlag ? 'text-down' : 'text-yellow-400'}`}>
        {redFlag
          ? <AlertTriangle size={14} className="shrink-0" />
          : <Activity size={14} className="shrink-0" />
        }
        <span className="font-semibold text-sm">{vix.toFixed(1)}</span>
        <span className="text-text-muted font-sans">VIX</span>
        {redFlag
          ? <span className="font-semibold text-down">🚩 Red Flag</span>
          : <span className="text-text-muted">Normal</span>
        }
        {vixPct != null && (
          <span className="text-text-muted">· pct {vixPct}%</span>
        )}
      </div>

      <div className="w-px h-4 bg-border" />

      {/* Régimen */}
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted">Régimen:</span>
        <span className={`font-medium ${REGIME_COLOR[regime] ?? 'text-text-secondary'}`}>
          {REGIME_LABEL[regime] ?? '—'}
        </span>
      </div>

      <div className="w-px h-4 bg-border" />

      {/* SPY */}
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted">SPY 5d:</span>
        <span className={`font-mono font-medium ${(ctx.spy_return_5d ?? 0) >= 0 ? 'text-up' : 'text-down'}`}>
          {ctx.spy_return_5d != null ? `${ctx.spy_return_5d >= 0 ? '+' : ''}${ctx.spy_return_5d.toFixed(2)}%` : '—'}
        </span>
        {ctx.spy_return_5d != null && (
          ctx.spy_return_5d >= 0
            ? <TrendingUp size={12} className="text-up" />
            : <TrendingDown size={12} className="text-down" />
        )}
      </div>

      <div className="w-px h-4 bg-border" />

      {/* Yield */}
      <div className="flex items-center gap-1.5">
        <span className="text-text-muted">T10Y:</span>
        <span className="font-mono text-text-secondary">
          {ctx.yield_10y != null ? `${ctx.yield_10y.toFixed(2)}%` : '—'}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {loading && <RefreshCw size={11} className="animate-spin text-text-muted" />}
        {isStale && (
          <span
            className="flex items-center gap-1 text-2xs px-1.5 py-0.5 rounded
                       bg-yellow-500/15 text-yellow-400 border border-yellow-500/30 font-medium"
            title={ctx.source === 'db_fallback'
              ? 'Yahoo Finance no respondió — mostrando último valor de DB'
              : `Datos atrasados (${ageMin ?? '?'} min sin actualizar)`}
          >
            <AlertTriangle size={10} /> stale
          </span>
        )}
        <span
          className="text-text-muted"
          title={updatedAt ? updatedAt.toLocaleString('es-AR') : ''}
        >
          {ageLbl}
        </span>
      </div>
    </div>
  )
}
