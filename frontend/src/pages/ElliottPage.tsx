import { useState, useEffect, useCallback } from 'react'
import { Search, RefreshCw, ChevronDown, ChevronUp, Activity,
         CheckCircle2, XCircle, ArrowUpCircle, ArrowDownCircle, MinusCircle,
         AlertTriangle, TrendingUp as TrendingUpIcon, TrendingDown,
         HelpCircle } from 'lucide-react'
import { api, type ElliottResult, type ElliottScanItem,
         type TrendPullbackSignal, type ChannelBreakdown,
         type HistoricalLowSignal, type HistoricalHighSignal } from '@/lib/api'
import type { Candle } from '@/lib/utils'
import ElliottChart from '@/components/elliott/ElliottChart'
import ElliottGuide from '@/components/elliott/ElliottGuide'
import { cn } from '@/lib/utils'

interface OtherSignals {
  trendPullback: TrendPullbackSignal | null
  channelBreakdown: ChannelBreakdown | null
  historicalLow: HistoricalLowSignal | null
  historicalHigh: HistoricalHighSignal | null
}

const SIGNAL_STYLES: Record<string, { bg: string; text: string; icon: typeof ArrowUpCircle }> = {
  BUY:  { bg: 'bg-emerald-500/15 border-emerald-500/30', text: 'text-emerald-400', icon: ArrowUpCircle },
  SELL: { bg: 'bg-red-500/15 border-red-500/30',         text: 'text-red-400',     icon: ArrowDownCircle },
  HOLD: { bg: 'bg-gray-500/15 border-gray-500/30',       text: 'text-gray-400',    icon: MinusCircle },
}

export default function ElliottPage() {
  const [scanItems, setScanItems] = useState<ElliottScanItem[]>([])
  const [loading, setLoading] = useState(false)
  const [scanDate, setScanDate] = useState('')
  const [market, setMarket] = useState('USA')

  // Detail state
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ElliottResult | null>(null)
  const [candles, setCandles] = useState<Candle[]>([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [otherSignals, setOtherSignals] = useState<OtherSignals>({
    trendPullback: null, channelBreakdown: null, historicalLow: null, historicalHigh: null,
  })

  // Search
  const [search, setSearch] = useState('')
  const [searchResults, setSearchResults] = useState<{ id: number; simbolo: string; nombre: string }[]>([])
  const [searchOpen, setSearchOpen] = useState(false)

  const loadScan = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.elliottScan(market)
      setScanItems(res.items)
      setScanDate(res.fecha)
    } catch { /* ignore */ }
    setLoading(false)
  }, [market])

  useEffect(() => { loadScan() }, [loadScan])

  const loadDetail = useCallback(async (accionId: number) => {
    setSelectedId(accionId)
    setDetailLoading(true)
    setOtherSignals({ trendPullback: null, channelBreakdown: null, historicalLow: null, historicalHigh: null })
    try {
      const [ell, ohlcv] = await Promise.all([
        api.elliott(accionId),
        api.ohlcvExtended(accionId, 'D'),
      ])
      setDetail(ell)
      setCandles(ohlcv.candles)

      // Load other signals in background (non-blocking)
      Promise.allSettled([
        api.trendPullbackSignal(accionId),
        api.channelBreakdown(accionId),
        api.historicalLowSignal(accionId),
        api.historicalHighSignal(accionId),
      ]).then(([tp, cb, hl, hh]) => {
        setOtherSignals({
          trendPullback:    tp.status === 'fulfilled' ? tp.value : null,
          channelBreakdown: cb.status === 'fulfilled' ? cb.value : null,
          historicalLow:    hl.status === 'fulfilled' ? hl.value : null,
          historicalHigh:   hh.status === 'fulfilled' ? hh.value : null,
        })
      })
    } catch { /* ignore */ }
    setDetailLoading(false)
  }, [])

  // Search assets — abort stale requests to avoid race conditions
  useEffect(() => {
    if (search.length < 1) { setSearchResults([]); setSearchOpen(false); return }
    const abort = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const res = await api.assets(market, search, 0, 10)
        if (abort.signal.aborted) return
        const items = res.items.map((a: any) => ({ id: a.accion_id, simbolo: a.simbolo, nombre: a.nombre }))
        setSearchResults(items)
        setSearchOpen(items.length > 0)
      } catch { /* ignore */ }
    }, 250)
    return () => { clearTimeout(timer); abort.abort() }
  }, [search, market])

  const signalCounts = {
    BUY: scanItems.filter(i => i.signal === 'BUY').length,
    SELL: scanItems.filter(i => i.signal === 'SELL').length,
  }

  return (
    <div className="space-y-6 p-4 md:p-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-blue-500/15 flex items-center justify-center">
            <Activity size={18} className="text-blue-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-text-primary">Elliott Wave</h1>
            <p className="text-xs text-text-muted">{scanDate && `Análisis ${scanDate}`}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:ml-auto">
          <select
            value={market}
            onChange={e => setMarket(e.target.value)}
            className="input text-xs h-8 w-24"
          >
            <option value="USA">USA</option>
            <option value="BYMA">BYMA</option>
          </select>
          <button onClick={loadScan} disabled={loading} className="btn btn-primary h-8 text-xs px-3 gap-1.5">
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Escanear
          </button>
        </div>
      </div>

      {/* Guide */}
      <ElliottGuide />

      {/* Search bar */}
      <div className="relative">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            onFocus={() => searchResults.length > 0 && setSearchOpen(true)}
            onBlur={() => setTimeout(() => setSearchOpen(false), 200)}
            onKeyDown={e => {
              if (e.key === 'Enter' && searchResults.length > 0) {
                loadDetail(searchResults[0].id)
                setSearchOpen(false)
                setSearch('')
              }
              if (e.key === 'Escape') { setSearchOpen(false) }
            }}
            placeholder="Escribí un símbolo (ej: AAPL, MSFT, TSLA) y seleccioná..."
            className="input w-full pl-9 h-9 text-sm uppercase"
          />
        </div>
        {searchOpen && searchResults.length > 0 && (
          <div className="absolute z-20 mt-1 w-full bg-surface border border-border rounded-lg shadow-xl max-h-60 overflow-y-auto">
            {searchResults.map(a => (
              <button
                key={a.id}
                onClick={() => { loadDetail(a.id); setSearchOpen(false); setSearch('') }}
                className="w-full px-4 py-2.5 text-left hover:bg-elevated flex items-center gap-3 text-sm transition-colors"
              >
                <span className="font-mono font-medium text-accent">{a.simbolo}</span>
                <span className="text-text-muted truncate">{a.nombre}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Summary badges */}
      <div className="flex gap-3">
        <div className="card px-4 py-2 flex items-center gap-2">
          <ArrowUpCircle size={14} className="text-emerald-400" />
          <span className="text-xs text-text-muted">BUY:</span>
          <span className="text-sm font-semibold text-emerald-400">{signalCounts.BUY}</span>
        </div>
        <div className="card px-4 py-2 flex items-center gap-2">
          <ArrowDownCircle size={14} className="text-red-400" />
          <span className="text-xs text-text-muted">SELL:</span>
          <span className="text-sm font-semibold text-red-400">{signalCounts.SELL}</span>
        </div>
        <div className="card px-4 py-2 flex items-center gap-2">
          <Activity size={14} className="text-text-muted" />
          <span className="text-xs text-text-muted">Total:</span>
          <span className="text-sm font-semibold text-text-primary">{scanItems.length}</span>
        </div>
      </div>

      {/* Scan conclusions */}
      {scanItems.length > 0 && <ScanConclusions items={scanItems} />}

      {/* Detail panel (when asset selected) */}
      {selectedId && (
        <div className="card p-0 overflow-hidden">
          {detailLoading ? (
            <div className="flex items-center justify-center h-[400px] text-text-muted text-sm">
              Analizando ondas...
            </div>
          ) : detail ? (
            <>
              {/* Signal header */}
              <div className="p-4 border-b border-border flex flex-col sm:flex-row sm:items-center gap-3">
                <div className="flex items-center gap-3">
                  <h2 className="text-base font-semibold text-text-primary">{detail.symbol}</h2>
                  {detail.price && (
                    <span className="text-sm text-text-muted">${detail.price.toFixed(2)}</span>
                  )}
                  <SignalBadge signal={detail.signal} />
                  <DirectionBadge direction={detail.direction} />
                </div>
                <p className="text-sm text-text-muted sm:ml-auto">{detail.current_wave}</p>
              </div>

              {/* Chart */}
              <ElliottChart
                candles={candles}
                waves={detail.wave_count}
                fibLevels={detail.fib_levels}
                fibTargets={detail.fib_targets}
                zigzagPivots={detail.zigzag_pivots}
                height={480}
              />

              {/* Info panel */}
              <div className="p-4 border-t border-border grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* Signal reason */}
                <div className="space-y-2">
                  <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">Señal</h3>
                  <p className="text-sm text-text-primary">{detail.signal_reason}</p>
                  <ConfidenceBar value={detail.confidence} />
                </div>

                {/* Rules */}
                <div className="space-y-2">
                  <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">Reglas de Elliott</h3>
                  {detail.rules_detail && Object.entries(detail.rules_detail).map(([key, ok]) => (
                    <div key={key} className="flex items-center gap-2 text-xs">
                      {ok
                        ? <CheckCircle2 size={13} className="text-emerald-400" />
                        : <XCircle size={13} className="text-red-400" />
                      }
                      <span className="text-text-secondary">{ruleLabel(key)}</span>
                    </div>
                  ))}
                </div>

                {/* Fib targets & levels */}
                <div className="space-y-2">
                  <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">
                    Fibonacci
                  </h3>
                  {detail.fib_targets.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-2xs text-emerald-400 font-medium">Targets</p>
                      {detail.fib_targets.map((f, i) => (
                        <div key={i} className="flex justify-between text-xs">
                          <span className="text-text-muted">{f.label}</span>
                          <span className="text-emerald-400 font-mono">${f.price.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {detail.fib_levels.length > 0 && (
                    <div className="space-y-1 mt-2">
                      <p className="text-2xs text-amber-400 font-medium">Retrocesos</p>
                      {detail.fib_levels.map((f, i) => (
                        <div key={i} className="flex justify-between text-xs">
                          <span className="text-text-muted">{f.label}</span>
                          <span className="text-amber-400 font-mono">${f.price.toFixed(2)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {detail.fib_targets.length === 0 && detail.fib_levels.length === 0 && (
                    <p className="text-xs text-text-muted">Sin niveles Fibonacci calculados</p>
                  )}
                </div>
              </div>

              {/* Other signals panel */}
              <OtherSignalsPanel signals={otherSignals} />

              {/* Wave count table */}
              {detail.wave_count.length > 0 && (
                <div className="p-4 border-t border-border">
                  <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2">
                    Conteo de ondas
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {detail.wave_count.map((w, i) => (
                      <div
                        key={i}
                        className={cn(
                          'px-3 py-1.5 rounded-lg text-xs font-mono border',
                          ['1', '3', '5'].includes(w.label)
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                            : ['A', 'B', 'C'].includes(w.label)
                            ? 'border-orange-500/30 bg-orange-500/10 text-orange-400'
                            : w.label === '0'
                            ? 'border-gray-500/30 bg-gray-500/10 text-gray-400'
                            : 'border-red-500/30 bg-red-500/10 text-red-400'
                        )}
                      >
                        <span className="font-bold">{w.label === '0' ? 'Inicio' : w.label}</span>
                        <span className="ml-2 text-text-muted">${w.price.toFixed(2)}</span>
                        <span className="ml-2 text-text-muted">{w.fecha}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* Scan results table */}
      {scanItems.length > 0 && (
        <div className="card p-0 overflow-hidden">
          <div className="p-4 border-b border-border">
            <h2 className="text-sm font-semibold text-text-primary">
              Señales activas ({scanItems.length})
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-text-muted border-b border-border">
                  <th className="text-left px-4 py-2.5">Símbolo</th>
                  <th className="text-left px-4 py-2.5">Nombre</th>
                  <th className="text-center px-4 py-2.5">Señal</th>
                  <th className="text-left px-4 py-2.5">Onda actual</th>
                  <th className="text-center px-4 py-2.5">Dirección</th>
                  <th className="text-right px-4 py-2.5">Precio</th>
                  <th className="text-right px-4 py-2.5">Confianza</th>
                </tr>
              </thead>
              <tbody>
                {scanItems.map(item => (
                  <tr
                    key={item.accion_id}
                    onClick={() => loadDetail(item.accion_id)}
                    className={cn(
                      'border-b border-border/50 hover:bg-elevated/50 cursor-pointer transition-colors',
                      selectedId === item.accion_id && 'bg-elevated'
                    )}
                  >
                    <td className="px-4 py-2.5 font-mono font-medium text-accent">{item.simbolo}</td>
                    <td className="px-4 py-2.5 text-text-secondary truncate max-w-[200px]">{item.nombre}</td>
                    <td className="px-4 py-2.5 text-center">
                      <SignalBadge signal={item.signal} />
                    </td>
                    <td className="px-4 py-2.5 text-text-secondary text-xs">{item.current_wave}</td>
                    <td className="px-4 py-2.5 text-center">
                      <DirectionBadge direction={item.direction} />
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-text-primary">
                      ${item.price.toFixed(2)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <ConfidenceBar value={item.confidence} compact />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && scanItems.length === 0 && (
        <div className="card p-8 text-center text-text-muted text-sm">
          No se encontraron señales Elliott activas. Presioná "Escanear" para analizar.
        </div>
      )}

      {loading && scanItems.length === 0 && (
        <div className="card p-8 text-center text-text-muted text-sm">
          <RefreshCw size={20} className="animate-spin mx-auto mb-2" />
          Escaneando universo — esto puede tardar unos minutos...
        </div>
      )}
    </div>
  )
}

function SignalBadge({ signal }: { signal: string }) {
  const style = SIGNAL_STYLES[signal] || SIGNAL_STYLES.HOLD
  const Icon = style.icon
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border', style.bg, style.text)}>
      <Icon size={12} />
      {signal}
    </span>
  )
}

function DirectionBadge({ direction }: { direction: string }) {
  const isBull = direction === 'ALCISTA'
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs',
      isBull ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
    )}>
      {isBull ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      {direction}
    </span>
  )
}

function ConfidenceBar({ value, compact }: { value: number; compact?: boolean }) {
  const pct = Math.min(100, Math.max(0, value))
  const color = pct >= 60 ? 'bg-emerald-500' : pct >= 30 ? 'bg-amber-500' : 'bg-red-500'
  if (compact) {
    return (
      <div className="flex items-center gap-1.5">
        <div className="w-12 h-1.5 bg-elevated rounded-full overflow-hidden">
          <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
        </div>
        <span className="text-2xs text-text-muted font-mono">{pct.toFixed(0)}%</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-elevated rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-text-muted font-mono w-10 text-right">{pct.toFixed(1)}%</span>
    </div>
  )
}

function ScanConclusions({ items }: { items: ElliottScanItem[] }) {
  const buys  = items.filter(i => i.signal === 'BUY')
  const sells = items.filter(i => i.signal === 'SELL')

  // Group by wave label to understand market phase
  const waveGroups: Record<string, ElliottScanItem[]> = {}
  for (const item of items) {
    const lbl = item.current_wave_label || '?'
    if (!waveGroups[lbl]) waveGroups[lbl] = []
    waveGroups[lbl].push(item)
  }

  const conclusions: { text: string; type: 'buy' | 'sell' | 'info' | 'warn' }[] = []

  // Ratio buy/sell
  const total = items.length
  const buyPct = total > 0 ? (buys.length / total * 100) : 0
  const sellPct = total > 0 ? (sells.length / total * 100) : 0

  if (buyPct > 65) {
    conclusions.push({
      text: `Sesgo alcista fuerte: ${buyPct.toFixed(0)}% de las señales son BUY (${buys.length} de ${total}). El mercado muestra múltiples activos completando correcciones o iniciando impulsos.`,
      type: 'buy',
    })
  } else if (sellPct > 65) {
    conclusions.push({
      text: `Sesgo bajista fuerte: ${sellPct.toFixed(0)}% de las señales son SELL (${sells.length} de ${total}). Muchos activos terminando impulsos o entrando en fase correctiva.`,
      type: 'sell',
    })
  } else if (total > 0) {
    conclusions.push({
      text: `Mercado mixto: ${buys.length} señales BUY vs ${sells.length} SELL de ${total} activos con patrón detectado. No hay una tendencia dominante clara según Elliott.`,
      type: 'info',
    })
  }

  // Wave C completions (new cycle starters)
  const waveC = (waveGroups['C'] || []).filter(i => i.signal === 'BUY')
  if (waveC.length > 0) {
    const names = waveC.slice(0, 5).map(i => i.simbolo).join(', ')
    const extra = waveC.length > 5 ? ` y ${waveC.length - 5} más` : ''
    conclusions.push({
      text: `${waveC.length} activo(s) completaron corrección A-B-C — posible inicio de nuevo ciclo alcista: ${names}${extra}`,
      type: 'buy',
    })
  }

  // Wave 2 completions (wave 3 about to start - strongest)
  const wave2 = (waveGroups['2'] || []).filter(i => i.signal === 'BUY')
  if (wave2.length > 0) {
    const names = wave2.slice(0, 5).map(i => i.simbolo).join(', ')
    const extra = wave2.length > 5 ? ` y ${wave2.length - 5} más` : ''
    conclusions.push({
      text: `${wave2.length} activo(s) terminando onda 2 — onda 3 (la más fuerte) por comenzar: ${names}${extra}`,
      type: 'buy',
    })
  }

  // Wave 4 completions (wave 5 about to start)
  const wave4 = (waveGroups['4'] || []).filter(i => i.signal === 'BUY')
  if (wave4.length > 0) {
    const names = wave4.slice(0, 5).map(i => i.simbolo).join(', ')
    conclusions.push({
      text: `${wave4.length} activo(s) terminando onda 4 — último impulso (onda 5) inminente: ${names}`,
      type: 'buy',
    })
  }

  // Wave 5 completions (exhaustion - sell)
  const wave5sell = (waveGroups['5'] || []).filter(i => i.signal === 'SELL')
  if (wave5sell.length > 0) {
    const names = wave5sell.slice(0, 5).map(i => i.simbolo).join(', ')
    conclusions.push({
      text: `${wave5sell.length} activo(s) completaron impulso de 5 ondas — agotamiento, corrección esperada: ${names}`,
      type: 'warn',
    })
  }

  // Wave B completions (wave C about to drop)
  const waveB = (waveGroups['B'] || []).filter(i => i.signal === 'SELL')
  if (waveB.length > 0) {
    const names = waveB.slice(0, 5).map(i => i.simbolo).join(', ')
    conclusions.push({
      text: `${waveB.length} activo(s) terminaron rebote B — onda C bajista por venir (no comprar): ${names}`,
      type: 'sell',
    })
  }

  // High confidence highlights
  const highConf = items.filter(i => i.confidence >= 50).sort((a, b) => b.confidence - a.confidence)
  if (highConf.length > 0) {
    const top = highConf.slice(0, 3).map(i => `${i.simbolo} (${i.confidence.toFixed(0)}%)`).join(', ')
    conclusions.push({
      text: `Mayor confianza Fibonacci: ${top}. Estos conteos tienen mejor alineación con los ratios clásicos de Elliott.`,
      type: 'info',
    })
  }

  if (conclusions.length === 0) return null

  const colorMap = {
    buy:  'border-emerald-500/20 bg-emerald-500/5',
    sell: 'border-red-500/20 bg-red-500/5',
    info: 'border-blue-500/20 bg-blue-500/5',
    warn: 'border-amber-500/20 bg-amber-500/5',
  }
  const textColorMap = {
    buy:  'text-emerald-300',
    sell: 'text-red-300',
    info: 'text-blue-300',
    warn: 'text-amber-300',
  }
  const iconMap = {
    buy:  ArrowUpCircle,
    sell: ArrowDownCircle,
    info: Activity,
    warn: AlertTriangle,
  }

  return (
    <div className="card p-4 space-y-3">
      <h2 className="text-sm font-semibold text-text-primary flex items-center gap-2">
        <Activity size={15} className="text-blue-400" />
        Conclusiones del escaneo
      </h2>
      <div className="space-y-2">
        {conclusions.map((c, i) => {
          const Icon = iconMap[c.type]
          return (
            <div key={i} className={cn(
              'flex items-start gap-3 px-4 py-3 rounded-lg border',
              colorMap[c.type],
            )}>
              <Icon size={15} className={cn('mt-0.5 shrink-0', textColorMap[c.type])} />
              <p className="text-sm text-text-secondary leading-relaxed">{c.text}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function OtherSignalsPanel({ signals }: { signals: OtherSignals }) {
  const messages: { text: string; type: 'buy' | 'sell' | 'info' | 'warn' }[] = []

  const { trendPullback, channelBreakdown, historicalLow, historicalHigh } = signals

  if (trendPullback) {
    if (trendPullback.decision === 'BUY_CANDIDATE') {
      messages.push({ text: `Trend Pullback: ${trendPullback.reading}`, type: 'buy' })
    } else if (trendPullback.decision === 'WATCHLIST') {
      messages.push({ text: `Trend Pullback (watchlist): ${trendPullback.reading}`, type: 'info' })
    } else if (trendPullback.decision === 'AVOID') {
      messages.push({ text: `Trend Pullback: ${trendPullback.reading}`, type: 'sell' })
    }
  }

  if (channelBreakdown?.has_breakdown && channelBreakdown.best_scenario) {
    const sc = channelBreakdown.best_scenario
    const typeMap: Record<string, 'buy' | 'sell' | 'info'> = { BUY: 'buy', SELL: 'sell', WAIT: 'info', SKIP: 'info' }
    messages.push({
      text: `Channel Breakdown: ${sc.description}${sc.entry ? ` — Entrada $${sc.entry.toFixed(2)}` : ''}`,
      type: typeMap[sc.signal] || 'info',
    })
  }

  if (historicalLow && historicalLow.setup_state !== 'NO_SIGNAL') {
    const isActionable = historicalLow.decision === 'BUY_CANDIDATE'
    messages.push({
      text: `Mínimo histórico: ${historicalLow.reading}`,
      type: isActionable ? 'buy' : 'warn',
    })
  }

  if (historicalHigh && historicalHigh.setup_state !== 'NO_SIGNAL') {
    messages.push({
      text: `Máximo histórico: ${(historicalHigh as any).reading || historicalHigh.setup_state}`,
      type: 'info',
    })
  }

  if (messages.length === 0) return null

  const colorMap = {
    buy:  'border-emerald-500/30 bg-emerald-500/5 text-emerald-400',
    sell: 'border-red-500/30 bg-red-500/5 text-red-400',
    info: 'border-blue-500/30 bg-blue-500/5 text-blue-400',
    warn: 'border-amber-500/30 bg-amber-500/5 text-amber-400',
  }

  const iconMap = {
    buy:  TrendingUpIcon,
    sell: TrendingDown,
    info: Activity,
    warn: AlertTriangle,
  }

  return (
    <div className="p-4 border-t border-border space-y-2">
      <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2">
        Señales complementarias
      </h3>
      {messages.map((m, i) => {
        const Icon = iconMap[m.type]
        return (
          <div key={i} className={cn('flex items-start gap-2 px-3 py-2 rounded-lg border text-xs', colorMap[m.type])}>
            <Icon size={13} className="mt-0.5 shrink-0" />
            <span>{m.text}</span>
          </div>
        )
      })}
    </div>
  )
}

function ruleLabel(key: string): string {
  switch (key) {
    case 'rule1_wave2_retrace': return 'Onda 2 no retrocede > 100% de Onda 1'
    case 'rule2_wave3_not_shortest': return 'Onda 3 no es la más corta'
    case 'rule3_wave4_no_overlap': return 'Onda 4 no se superpone con Onda 1'
    default: return key
  }
}
