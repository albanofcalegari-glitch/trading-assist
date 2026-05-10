import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw, TrendingUp, TrendingDown, Search } from 'lucide-react'
import { api, type TrendSma200Item } from '@/lib/api'
import { fmtPrice } from '@/lib/utils'

type Filter = 'ALL' | 'ALCISTA' | 'BAJISTA'

export default function Tendencias() {
  const navigate = useNavigate()
  const [items, setItems]     = useState<TrendSma200Item[]>([])
  const [fecha, setFecha]     = useState('')
  const [totals, setTotals]   = useState({ alcistas: 0, bajistas: 0 })
  const [loading, setLoading] = useState(false)
  const [filter, setFilter]   = useState<Filter>('ALL')
  const [search, setSearch]   = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.trendsSma200Weekly()
      setItems(res.items)
      setFecha(res.fecha)
      setTotals({ alcistas: res.alcistas, bajistas: res.bajistas })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = items.filter(i => {
    if (filter !== 'ALL' && i.trend !== filter) return false
    if (search) {
      const q = search.toLowerCase()
      return i.simbolo.toLowerCase().includes(q) || i.nombre.toLowerCase().includes(q)
    }
    return true
  })

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-text-primary">Activos / Tendencias</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Tendencia de largo plazo basada en SMA200 semanal{fecha && ` · ${fecha}`}
          </p>
        </div>
        <button className="btn-ghost text-xs gap-1.5" onClick={() => load()}>
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Actualizar
        </button>
      </div>

      {/* Stats + Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-0 border border-border rounded-md overflow-hidden">
          {([
            ['ALL', 'Todos'],
            ['ALCISTA', `Alcistas (${totals.alcistas})`],
            ['BAJISTA', `Bajistas (${totals.bajistas})`],
          ] as [Filter, string][]).map(([val, label]) => (
            <button
              key={val}
              onClick={() => setFilter(val)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                filter === val
                  ? 'bg-accent text-white'
                  : 'bg-surface text-text-muted hover:text-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="relative flex-1 min-w-[160px] max-w-xs">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            placeholder="Buscar activo..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="input pl-8 py-1.5 text-xs w-full"
          />
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-text-muted">
                <th className="text-left px-3 py-2.5 font-medium w-24">Ticker</th>
                <th className="text-left px-3 py-2.5 font-medium hidden md:table-cell">Empresa</th>
                <th className="text-right px-3 py-2.5 font-medium w-24">Precio</th>
                <th className="text-right px-3 py-2.5 font-medium w-24 hidden sm:table-cell">SMA200</th>
                <th className="text-right px-3 py-2.5 font-medium w-24">Dist %</th>
                <th className="text-center px-3 py-2.5 font-medium w-28">Tendencia</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0
                ? Array.from({ length: 12 }).map((_, i) => (
                    <tr key={i} className="border-b border-border/50">
                      {Array.from({ length: 6 }).map((_, j) => (
                        <td key={j} className="px-3 py-2.5">
                          <div className="h-3.5 bg-elevated rounded animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : filtered.map(item => (
                    <tr
                      key={item.simbolo}
                      onClick={() => item.accion_id && navigate(`/asset/${item.accion_id}`)}
                      className="border-b border-border/50 hover:bg-elevated/50 transition-colors cursor-pointer"
                    >
                      <td className="px-3 py-2.5 font-semibold text-text-primary">
                        {item.simbolo}
                      </td>
                      <td className="px-3 py-2.5 text-text-muted truncate max-w-[200px] hidden md:table-cell">
                        {item.nombre}
                      </td>
                      <td className="px-3 py-2.5 text-right text-text-primary font-mono">
                        {fmtPrice(item.price)}
                      </td>
                      <td className="px-3 py-2.5 text-right text-text-muted font-mono hidden sm:table-cell">
                        {fmtPrice(item.sma200)}
                      </td>
                      <td className={`px-3 py-2.5 text-right font-mono font-medium ${
                        item.distance_pct >= 0 ? 'text-up' : 'text-down'
                      }`}>
                        {item.distance_pct >= 0 ? '+' : ''}{item.distance_pct.toFixed(1)}%
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold ${
                          item.trend === 'ALCISTA'
                            ? 'bg-up/15 text-up'
                            : 'bg-down/15 text-down'
                        }`}>
                          {item.trend === 'ALCISTA'
                            ? <TrendingUp size={11} />
                            : <TrendingDown size={11} />}
                          {item.trend}
                        </span>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>

        {!loading && filtered.length === 0 && (
          <div className="text-center py-8 text-text-muted text-xs">
            Sin resultados{search && ` para "${search}"`}
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="px-3 py-2.5 text-2xs text-text-muted border-t border-border">
            {filtered.length} activos
            {filter !== 'ALL' && ` (${filter.toLowerCase()})`}
            {search && ` con "${search}"`}
          </div>
        )}
      </div>
    </div>
  )
}
