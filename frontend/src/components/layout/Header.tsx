import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, X } from 'lucide-react'
import { api, type Asset } from '@/lib/api'
import { fmtPrice, fmtPct, pctClass } from '@/lib/utils'

export default function Header() {
  const [query,   setQuery]   = useState('')
  const [results, setResults] = useState<Asset[]>([])
  const [open,    setOpen]    = useState(false)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const timer    = useRef<ReturnType<typeof setTimeout>>()
  const ref      = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [])

  useEffect(() => {
    clearTimeout(timer.current)
    if (query.length < 2) { setResults([]); setOpen(false); return }
    setLoading(true)
    timer.current = setTimeout(async () => {
      try {
        const { items } = await api.assets('', query, 0, 8)
        setResults(items)
        setOpen(true)
      } finally {
        setLoading(false)
      }
    }, 300)
  }, [query])

  const go = (id: number) => {
    setQuery(''); setOpen(false)
    navigate(`/asset/${id}`)
  }

  return (
    <header className="h-14 border-b border-border bg-surface flex items-center px-6 gap-4 shrink-0">
      {/* Search */}
      <div ref={ref} className="relative w-72">
        <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <input
          className="input pl-8 pr-8 h-8 text-xs"
          placeholder="Buscar símbolo o empresa..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
        />
        {query && (
          <button
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
            onClick={() => { setQuery(''); setOpen(false) }}
          >
            <X size={12} />
          </button>
        )}

        {/* Dropdown */}
        {open && results.length > 0 && (
          <div className="absolute top-full mt-1 w-full z-50 card-elevated overflow-hidden shadow-xl rounded-lg border border-border">
            {results.map(a => (
              <button
                key={a.accion_id}
                className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-elevated/70
                           border-b border-border-subtle last:border-0 text-left transition-colors"
                onClick={() => go(a.accion_id)}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-medium text-sm text-text-primary">
                      {a.simbolo}
                    </span>
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
          <div className="absolute top-full mt-1 w-full z-50 card-elevated px-3 py-2 text-xs text-text-muted">
            Buscando...
          </div>
        )}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Fecha */}
      <span className="text-xs text-text-muted">
        {new Date().toLocaleDateString('es-AR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
      </span>
    </header>
  )
}
