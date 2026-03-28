import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Zap, TrendingUp, RefreshCw, AlertCircle, Clock, ChevronRight } from 'lucide-react'
import { api, type WmaCrossItem } from '@/lib/api'
import { fmtPrice, fmtVol } from '@/lib/utils'
import Semaphore from '@/components/shared/Semaphore'

const MARKETS = [
  { value: 'USA',  label: 'USA' },
  { value: 'BYMA', label: 'BYMA' },
  { value: 'ALL',  label: 'Todos' },
]

export default function Screener() {
  const navigate = useNavigate()
  const [setup,      setSetup]      = useState<WmaCrossItem[]>([])
  const [cross,      setCross]      = useState<WmaCrossItem[]>([])
  const [fecha,      setFecha]      = useState('')
  const [market,     setMarket]     = useState('USA')
  const [trend,      setTrend]      = useState(false)
  const [loading,    setLoading]    = useState(false)
  const [computing,  setComputing]  = useState(false)
  const [error,      setError]      = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval>>()

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    setError('')
    try {
      const res = await api.wmaCross(market, 10, trend)

      if ((res as any).status === 'computing') {
        setComputing(true)
        setLoading(false)
        // Polling cada 15s hasta que esté listo
        if (!pollRef.current) {
          pollRef.current = setInterval(() => load(true), 15_000)
        }
        return
      }

      // Datos listos
      clearInterval(pollRef.current); pollRef.current = undefined
      setComputing(false)
      setSetup(res.setup)
      setCross(res.cross)
      setFecha(res.fecha)
    } catch (e) {
      setError('Error al cargar. ¿El API está corriendo en :8000?')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    clearInterval(pollRef.current); pollRef.current = undefined
    setComputing(false); setSetup([]); setCross([])
    load()
    return () => clearInterval(pollRef.current)
  }, [market, trend])   // eslint-disable-line

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-text-primary">Screener WMA6 / WMA30</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Cruces y setups de corto plazo{fecha && ` · ${fecha}`}
          </p>
        </div>
        <button className="btn-ghost text-xs gap-1.5" onClick={load}>
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Actualizar
        </button>
      </div>

      {/* Filtros */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-0 border border-border rounded-md overflow-hidden">
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

        <label className="flex items-center gap-2 cursor-pointer select-none">
          <div
            className={`w-8 h-4 rounded-full transition-colors ${trend ? 'bg-accent' : 'bg-border'}`}
            onClick={() => setTrend(v => !v)}
          >
            <div className={`w-3 h-3 rounded-full bg-white m-0.5 transition-transform shadow ${
              trend ? 'translate-x-4' : ''}`}
            />
          </div>
          <span className="text-xs text-text-secondary">Solo tendencia alcista</span>
        </label>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-down/10 border border-down/20 text-down text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {computing && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-warn/10 border border-warn/20 text-warn text-sm">
          <Clock size={14} className="shrink-0 animate-pulse" />
          <span>
            Escaneando el universo de stocks (~5 min). La página se actualizará automáticamente.
          </span>
          <RefreshCw size={13} className="ml-auto animate-spin shrink-0" />
        </div>
      )}

      {/* Dos columnas */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {/* Setup */}
        <SignalSection
          icon={<Zap size={14} className="text-warn" />}
          title="Por cruzar (Setup)"
          subtitle="WMA6 se acerca a WMA30"
          items={setup}
          tipo="SETUP_SWING"
          loading={loading}
          onSelect={id => navigate(`/asset/${id}`)}
        />

        {/* Cruce confirmado */}
        <SignalSection
          icon={<TrendingUp size={14} className="text-up" />}
          title="Cruce confirmado (Hoy)"
          subtitle="WMA6 cruzó WMA30 al alza"
          items={cross}
          tipo="CROSS_SWING_BUY"
          loading={loading}
          onSelect={id => navigate(`/asset/${id}`)}
        />
      </div>
    </div>
  )
}

// ── Sección de señales ─────────────────────────────────────────────────────────

function SignalSection({ icon, title, subtitle, items, tipo, loading, onSelect }: {
  icon:      React.ReactNode
  title:     string
  subtitle:  string
  items:     WmaCrossItem[]
  tipo:      string
  loading:   boolean
  onSelect:  (id: number) => void
}) {
  const isSetup = tipo === 'SETUP_SWING'

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3.5 border-b border-border flex items-center gap-2">
        {icon}
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          <p className="text-2xs text-text-muted">{subtitle}</p>
        </div>
        <span className="ml-auto badge badge-neutral">{items.length}</span>
      </div>

      {/* Items */}
      {loading ? (
        <div className="p-4 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 rounded bg-elevated animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-text-muted">Sin oportunidades</p>
        </div>
      ) : (
        <div className="divide-y divide-border-subtle">
          {items.map(item => (
            <button
              key={item.simbolo}
              className="w-full flex items-center gap-3 px-4 py-3 cursor-pointer
                         hover:bg-elevated transition-colors text-left group"
              onClick={() => onSelect(item.accion_id)}
            >
              {/* Symbol */}
              <div className="w-20 shrink-0">
                <span className="font-mono font-semibold text-sm text-text-primary
                                 group-hover:text-accent transition-colors">
                  {item.simbolo}
                </span>
                <p className="text-2xs text-text-muted">{item.mercado}</p>
              </div>

              {/* Name */}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-text-secondary truncate">{item.nombre}</p>
                <p className="text-2xs text-text-muted mt-0.5">
                  WMA6 {item.wma6.toFixed(2)} · WMA30 {item.wma30.toFixed(2)}
                </p>
              </div>

              {/* GAP + trend */}
              <div className="text-right shrink-0 space-y-1">
                <span className={`badge ${isSetup ? 'badge-warn' : 'badge-up'}`}>
                  {isSetup ? `gap ${item.gap_pct.toFixed(2)}%` : 'cruce hoy'}
                </span>
                <div className="flex justify-end">
                  <Semaphore
                    color={item.trend_up ? 'up' : 'neutral'}
                    label={item.trend_up ? 'Tend SI' : 'Tend NO'}
                    size="sm"
                  />
                </div>
              </div>

              {/* Precio + vol */}
              <div className="text-right shrink-0 w-20">
                <p className="font-mono text-xs text-text-primary">{fmtPrice(item.precio)}</p>
                <p className="text-2xs text-text-muted">{fmtVol(item.vol)}</p>
              </div>

              <ChevronRight size={14} className="text-text-muted opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
