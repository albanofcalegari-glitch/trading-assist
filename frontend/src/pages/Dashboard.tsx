import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, Filter, AlertTriangle, TrendingDown, TrendingUp, Activity } from 'lucide-react'
import { api, type Mover, type Asset, type MarketContext } from '@/lib/api'
import MoverBlock from '@/components/dashboard/MoverBlock'
import AssetTable from '@/components/dashboard/AssetTable'

const MARKETS = [
  { value: '',     label: 'Todos' },
  { value: 'USA',  label: 'USA' },
  { value: 'BYMA', label: 'BYMA' },
]

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
  const [ctx,      setCtx]      = useState<MarketContext | null>(null)

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
    api.marketContext().then(setCtx).catch(() => {})
  }, [loadMovers])

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
      {/* Page title */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-text-primary">Dashboard</h1>
          <p className="text-xs text-text-muted mt-0.5">Resumen del mercado</p>
        </div>
        <button
          className="btn-ghost text-xs gap-1.5"
          onClick={() => { loadMovers(); loadAssets(market, search, page) }}
        >
          <RefreshCw size={13} />
          Actualizar
        </button>
      </div>

      {/* Market Context */}
      {ctx && <MarketBar ctx={ctx} />}

      {/* Movers 2×2 */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <MoverBlock title="Top alza — USA"  items={movers.usaUp}   isUp loading={mLoading} />
        <MoverBlock title="Top baja — USA"  items={movers.usaDown} isUp={false} loading={mLoading} />
        <MoverBlock title="Top alza — BYMA" items={movers.bymaUp}  isUp loading={mLoading} />
        <MoverBlock title="Top baja — BYMA" items={movers.bymaDown} isUp={false} loading={mLoading} />
      </div>

      {/* Filtros + tabla */}
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="flex-1 max-w-xs relative">
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

function MarketBar({ ctx }: { ctx: MarketContext }) {
  const vix      = ctx.vix_level ?? 0
  const redFlag  = vix > 30
  const vixPct   = ctx.vix_percentile_1y != null ? Math.round(ctx.vix_percentile_1y * 100) : null
  const regime   = ctx.market_regime ?? 0

  return (
    <div className={`flex flex-wrap items-center gap-3 px-4 py-3 rounded-lg border text-xs ${
      redFlag
        ? 'bg-down/10 border-down/40'
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

      <div className="ml-auto text-text-muted">{ctx.fecha}</div>
    </div>
  )
}
