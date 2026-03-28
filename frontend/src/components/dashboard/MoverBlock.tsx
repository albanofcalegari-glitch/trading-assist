import { TrendingUp, TrendingDown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { fmtPrice, fmtPct } from '@/lib/utils'
import type { Mover } from '@/lib/api'

interface Props {
  title:  string
  items:  Mover[]
  isUp:   boolean
  loading?: boolean
}

export default function MoverBlock({ title, items, isUp, loading }: Props) {
  const navigate = useNavigate()
  const Icon = isUp ? TrendingUp : TrendingDown

  return (
    <div className="card p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Icon size={14} className={isUp ? 'text-up' : 'text-down'} />
        <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          {title}
        </h3>
      </div>

      {/* Items */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-8 rounded bg-elevated animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="text-xs text-text-muted py-2">Sin datos</p>
      ) : (
        <div className="space-y-0">
          {items.map((m, i) => (
            <button
              key={m.simbolo}
              className="w-full flex items-center gap-2 py-2 px-1.5 rounded-md
                         hover:bg-elevated/60 transition-colors text-left group"
              onClick={() => navigate(`/asset/${m.accion_id}`)}
            >
              {/* Rank */}
              <span className="text-2xs text-text-muted w-4 shrink-0 font-mono">{i + 1}</span>

              {/* Symbol + name */}
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-1.5">
                  <span className="font-mono font-medium text-sm text-text-primary
                                   group-hover:text-accent transition-colors">
                    {m.simbolo}
                  </span>
                  <span className="text-2xs text-text-muted truncate">{m.mercado}</span>
                </div>
                <p className="text-2xs text-text-muted truncate">{m.nombre?.slice(0, 28)}</p>
              </div>

              {/* Price + change */}
              <div className="text-right shrink-0">
                <p className="font-mono text-xs text-text-primary">{fmtPrice(m.precio)}</p>
                <p className={`font-mono text-xs font-medium ${isUp ? 'text-up' : 'text-down'}`}>
                  {fmtPct(m.pct_cambio)}
                </p>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
