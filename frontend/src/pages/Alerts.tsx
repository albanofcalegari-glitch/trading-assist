import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bell, RefreshCw, Sunrise, DoorOpen, Sun, Moon, Trophy, Activity, ChevronRight,
  TrendingDown, TrendingUp, Star,
} from 'lucide-react'
import { api, markNotificationRead, type Notification } from '@/lib/api'

const KIND_FILTERS = [
  { value: '',           label: 'Todas',     icon: Bell },
  { value: 'pre_market', label: 'Premarket', icon: Sunrise },
  { value: 'opening',    label: 'Apertura',  icon: DoorOpen },
  { value: 'midday',     label: 'Mediodía',  icon: Sun },
  { value: 'close',      label: 'Cierre',    icon: Moon },
  { value: 'weekly_rank',     label: 'Semanal',  icon: Trophy },
  { value: 'historical_lows', label: 'Mínimos',  icon: TrendingDown },
  { value: 'historical_highs', label: 'Máximos', icon: TrendingUp },
  { value: 'watchlist',       label: 'Watchlist', icon: Star },
  { value: 'universe_scan',  label: 'Universo',  icon: Activity },
]

const KIND_META: Record<string, { color: string; icon: any; label: string }> = {
  pre_market:        { color: '#f59e0b', icon: Sunrise,      label: 'Premarket' },
  opening:           { color: '#06b6d4', icon: DoorOpen,     label: 'Apertura' },
  midday:            { color: '#facc15', icon: Sun,          label: 'Mediodía' },
  close:             { color: '#8b5cf6', icon: Moon,         label: 'Cierre' },
  weekly_rank:       { color: '#22c55e', icon: Trophy,       label: 'Semanal' },
  historical_lows:   { color: '#ef4444', icon: TrendingDown, label: 'Mínimos' },
  historical_highs:  { color: '#22c55e', icon: TrendingUp,   label: 'Máximos' },
  watchlist:         { color: '#eab308', icon: Star,         label: 'Watchlist' },
  watchlist_summary: { color: '#eab308', icon: Star,         label: 'Watchlist' },
  universe_scan:         { color: '#06b6d4', icon: Activity,    label: 'Universo' },
  universe_scan_summary: { color: '#06b6d4', icon: Activity,    label: 'Universo' },
}

export default function Alerts() {
  const [items,   setItems]   = useState<Notification[]>([])
  const [kind,    setKind]    = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.notifications(kind, 50)
      setItems(res.items)
    } finally {
      setLoading(false)
    }
  }, [kind])

  useEffect(() => { load() }, [load])

  const handleClick = async (n: Notification) => {
    if (!n.read_at) {
      try { await markNotificationRead(n.id) } catch {}
      setItems(list => list.map(x => x.id === n.id
        ? { ...x, read_at: new Date().toISOString() }
        : x))
    }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-text-primary">Notificaciones</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Feed de batches del mercado
          </p>
        </div>
        <button
          className="btn-ghost text-xs gap-1.5"
          onClick={() => load()}
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Actualizar
        </button>
      </div>

      {/* Filtros */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {KIND_FILTERS.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            onClick={() => setKind(value)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors ${
              kind === value
                ? 'bg-accent text-white border-accent'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>

      {/* Lista */}
      {loading && items.length === 0 ? (
        <div className="card p-6 text-center text-xs text-text-muted">Cargando...</div>
      ) : items.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="space-y-2">
          {items.map(n => (
            <NotificationRow key={n.id} notif={n} onClick={() => handleClick(n)} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Subcomponentes ─────────────────────────────────────────────────────────────

function NotificationRow({ notif, onClick }: { notif: Notification; onClick: () => void }) {
  const navigate = useNavigate()
  const meta = KIND_META[notif.kind] || { color: '#94a3b8', icon: Activity, label: notif.kind }
  const Icon = meta.icon
  const isUnread = !notif.read_at

  // Si la notificación tiene un asset asociado en el payload, la flecha
  // derecha lleva a la página de detalle del activo.
  // Soportamos varias claves posibles según el batch que la generó.
  const targetAccionId: number | null = (() => {
    if (typeof notif.accion_id === 'number') return notif.accion_id
    const d = notif.data
    if (!d) return null
    if (typeof d.accion_id === 'number') return d.accion_id
    if (typeof d.symbol_id === 'number') return d.symbol_id
    if (Array.isArray(d.top_up) && d.top_up.length === 1 && d.top_up[0]?.accion_id) {
      return d.top_up[0].accion_id
    }
    return null
  })()

  return (
    <button
      onClick={onClick}
      className={`w-full card p-3 md:p-4 flex items-start gap-3 text-left transition-colors
                  hover:border-accent/40 ${isUnread ? 'border-l-2 border-l-accent' : ''}`}
    >
      <div
        className="w-9 h-9 rounded-md flex items-center justify-center shrink-0"
        style={{ backgroundColor: `${meta.color}18`, color: meta.color }}
      >
        <Icon size={16} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-2xs uppercase tracking-wide font-medium"
            style={{ color: meta.color }}
          >
            {meta.label}
          </span>
          {notif.signal_direction && (
            <span
              className={`text-2xs px-1.5 py-0.5 rounded font-semibold tracking-wide ${
                notif.signal_direction === 'BUY'
                  ? 'bg-up/15 text-up border border-up/30'
                  : 'bg-down/15 text-down border border-down/30'
              }`}
            >
              {notif.signal_direction}
            </span>
          )}
          {notif.accion_simbolo && (
            <span className="text-2xs font-mono text-text-secondary">
              {notif.accion_simbolo}
            </span>
          )}
          <span className="text-2xs text-text-muted">·</span>
          <span className="text-2xs text-text-muted">{fmtRelative(notif.created_at)}</span>
          {isUnread && (
            <span className="text-2xs px-1.5 py-0.5 rounded bg-accent/20 text-accent font-medium">
              nueva
            </span>
          )}
        </div>
        <p className={`text-sm mt-1 ${isUnread ? 'text-text-primary font-medium' : 'text-text-secondary'}`}>
          {notif.title}
        </p>
        <p className="text-xs text-text-muted mt-0.5 line-clamp-2">{notif.body}</p>

        {/* Top movers chips: closing/premarket/opening usan pct, weekly_rank usa score, historical_lows usa dist */}
        {notif.data?.top_up?.length ? (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {notif.data.top_up.slice(0, 10).map((m: any) => (
              <MoverChip
                key={`u-${m.symbol}`}
                symbol={m.symbol}
                pct={m.pct}
                accionId={m.accion_id}
                up={notif.kind !== 'historical_lows'}
                mode={notif.kind === 'weekly_rank' ? 'score' : notif.kind === 'historical_lows' ? 'dist' : notif.kind === 'historical_highs' ? 'dist_high' : 'pct'}
              />
            ))}
            {notif.data.top_down?.slice(0, 5).map((m: any) => (
              <MoverChip
                key={`d-${m.symbol}`}
                symbol={m.symbol}
                pct={m.pct}
                accionId={m.accion_id}
                up={notif.kind === 'historical_highs'}
                mode={notif.kind === 'weekly_rank' ? 'score' : notif.kind === 'historical_lows' ? 'dist' : notif.kind === 'historical_highs' ? 'dist_high' : 'pct'}
              />
            ))}
          </div>
        ) : null}
      </div>

      {targetAccionId ? (
        <span
          role="button"
          tabIndex={0}
          onClick={e => { e.stopPropagation(); navigate(`/asset/${targetAccionId}`) }}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              e.stopPropagation()
              navigate(`/asset/${targetAccionId}`)
            }
          }}
          className="shrink-0 mt-0.5 p-1 rounded-md text-text-muted hover:text-accent hover:bg-elevated cursor-pointer transition-colors"
          title="Ir al activo"
          aria-label="Ir al activo"
        >
          <ChevronRight size={16} />
        </span>
      ) : (
        <ChevronRight size={14} className="text-text-muted shrink-0 mt-1 opacity-40" />
      )}
    </button>
  )
}

function MoverChip({ symbol, pct, accionId, up, mode = 'pct' }: {
  symbol: string; pct: number; accionId?: number; up: boolean
  mode?: 'pct' | 'score' | 'dist' | 'dist_high'
}) {
  const navigate = useNavigate()
  const cls = up
    ? 'bg-up/10 text-up border-up/20'
    : 'bg-down/10 text-down border-down/20'
  const label = mode === 'score'
    ? pct.toFixed(0)
    : mode === 'dist'
    ? `${pct.toFixed(1)}% del min`
    : mode === 'dist_high'
    ? `${pct.toFixed(1)}% del max`
    : `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`
  return (
    <span
      onClick={e => {
        e.stopPropagation()
        if (accionId) navigate(`/asset/${accionId}`)
      }}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-2xs font-mono ${cls}
                  ${accionId ? 'cursor-pointer hover:opacity-80' : ''}`}
    >
      {symbol} {label}
    </span>
  )
}

function EmptyState() {
  return (
    <div className="card flex flex-col items-center justify-center py-16 gap-3">
      <div className="w-10 h-10 rounded-xl bg-elevated flex items-center justify-center">
        <Bell size={18} className="text-text-muted" />
      </div>
      <p className="text-sm text-text-secondary">Todavía no hay notificaciones</p>
      <p className="text-xs text-text-muted text-center max-w-xs">
        Los batches del mercado generan notificaciones automáticas. Probá:{' '}
        <code className="text-accent">python -m batches.run_batch closing</code>
      </p>
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtRelative(iso: string): string {
  const ts = new Date(iso).getTime()
  const diff = (Date.now() - ts) / 1000
  if (diff < 60)        return 'recién'
  if (diff < 3600)      return `${Math.floor(diff / 60)}m`
  if (diff < 86400)     return `${Math.floor(diff / 3600)}h`
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d`
  return new Date(iso).toLocaleDateString('es-AR', { day: 'numeric', month: 'short' })
}
