import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Plus, Pencil, Trash2, RefreshCw, BookOpen, Search, X, Loader2,
  ArrowLeft,
} from 'lucide-react'
import {
  api, addTrade, updateTrade, deleteTrade,
  type Trade, type Asset, type TradeInput,
} from '@/lib/api'
import { cn } from '@/lib/utils'

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null || !isFinite(v)) return '—'
  return v.toLocaleString('es-AR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

function pnlClass(v: number | null | undefined): string {
  if (v == null) return 'text-text-muted'
  if (v > 0) return 'price-up'
  if (v < 0) return 'price-down'
  return 'text-text-muted'
}

function todayISO(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ── Página principal ──────────────────────────────────────────────────────────

export default function Movimientos() {
  const [items,   setItems]   = useState<Trade[]>([])
  const [loading, setLoading] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [editItem, setEditItem] = useState<Trade | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.trades()
      setItems(res.items)
    } catch (e: any) {
      setError(e.message || 'Error al cargar los movimientos')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (item: Trade) => {
    if (!confirm(`¿Eliminar movimiento de ${item.simbolo}?`)) return
    try {
      await deleteTrade(item.id)
      setItems(xs => xs.filter(x => x.id !== item.id))
    } catch (e: any) {
      alert(e.message || 'Error al eliminar')
    }
  }

  const totals = useMemo(() => {
    let invertido = 0
    let fees = 0
    let neto = 0
    let cerradas = 0
    for (const it of items) {
      invertido += it.qty * it.buy_price
      fees      += it.fee || 0
      if (it.net_pnl != null) {
        neto += it.net_pnl
        cerradas += 1
      }
    }
    if (items.length === 0) return null
    return { invertido, fees, neto, cerradas, abiertas: items.length - cerradas }
  }, [items])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-base font-semibold text-text-primary flex items-center gap-2">
            <BookOpen size={16} className="text-accent" />
            Log de movimientos
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            Compras/ventas registradas · {items.length} {items.length === 1 ? 'movimiento' : 'movimientos'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost text-xs gap-1.5" onClick={() => load()}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Actualizar
          </button>
          <button className="btn-primary text-xs gap-1.5" onClick={() => setAddOpen(true)}>
            <Plus size={14} />
            Nuevo movimiento
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-3 py-2 rounded-md">
          {error}
        </div>
      )}

      {/* Tabla */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="table-header text-left  px-3 py-2.5">Activo</th>
                <th className="table-header text-right px-3 py-2.5">Cant.</th>
                <th className="table-header text-right px-3 py-2.5">Compra</th>
                <th className="table-header text-right px-3 py-2.5">Fecha compra</th>
                <th className="table-header text-right px-3 py-2.5">Venta</th>
                <th className="table-header text-right px-3 py-2.5">Fecha venta</th>
                <th className="table-header text-right px-3 py-2.5">Comisión</th>
                <th className="table-header text-right px-3 py-2.5">G/P</th>
                <th className="table-header text-right px-3 py-2.5">Neto</th>
                <th className="table-header text-right px-3 py-2.5 w-24">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-center py-10 text-text-muted text-xs">
                    <Loader2 size={16} className="inline animate-spin mr-2" />
                    Cargando movimientos…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-center py-10 text-text-muted text-xs">
                    Sin movimientos. Agregá tu primer registro con el botón de arriba.
                  </td>
                </tr>
              )}
              {items.map(it => (
                <tr key={it.id} className="table-row">
                  <td className="px-3 py-2">
                    <div className="flex flex-col min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-text-primary">{it.simbolo}</span>
                        <span className="text-2xs text-text-muted">{it.mercado}</span>
                        {it.sell_price == null && (
                          <span className="text-2xs text-accent">· abierto</span>
                        )}
                      </div>
                      <span className="text-xs text-text-muted truncate max-w-[240px]">
                        {it.nombre}
                      </span>
                      {it.note && (
                        <span className="text-2xs text-text-muted italic mt-0.5 truncate max-w-[240px]">
                          {it.note}
                        </span>
                      )}
                    </div>
                  </td>

                  <td className="px-3 py-2 text-right num text-text-secondary">
                    {fmtNum(it.qty, it.qty % 1 === 0 ? 0 : 4)}
                  </td>

                  <td className="px-3 py-2 text-right num text-text-primary">
                    ${fmtNum(it.buy_price)}
                  </td>
                  <td className="px-3 py-2 text-right num text-text-muted text-xs">
                    {it.buy_date}
                  </td>

                  <td className="px-3 py-2 text-right num text-text-primary">
                    {it.sell_price != null ? `$${fmtNum(it.sell_price)}` : '—'}
                  </td>
                  <td className="px-3 py-2 text-right num text-text-muted text-xs">
                    {it.sell_date || '—'}
                  </td>

                  <td className="px-3 py-2 text-right num text-text-secondary">
                    {it.fee ? `$${fmtNum(it.fee)}` : '—'}
                  </td>

                  {/* G/P bruta con % */}
                  <td className={cn('px-3 py-2 text-right num', pnlClass(it.gross_pnl))}>
                    {it.gross_pnl != null ? (
                      <div className="flex flex-col items-end leading-tight">
                        <span>${fmtNum(it.gross_pnl)}</span>
                        <span className="text-2xs">{fmtPct(it.pct)}</span>
                      </div>
                    ) : '—'}
                  </td>

                  {/* Neto */}
                  <td className={cn('px-3 py-2 text-right num font-semibold', pnlClass(it.net_pnl))}>
                    {it.net_pnl != null ? `$${fmtNum(it.net_pnl)}` : '—'}
                  </td>

                  <td className="px-3 py-2 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        className="p-1.5 rounded hover:bg-elevated text-text-muted hover:text-text-primary transition-colors cursor-pointer"
                        onClick={() => setEditItem(it)}
                        title="Editar"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        className="p-1.5 rounded hover:bg-red-500/10 text-text-muted hover:text-red-400 transition-colors cursor-pointer"
                        onClick={() => handleDelete(it)}
                        title="Eliminar"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>

            {totals && (
              <tfoot>
                <tr className="border-t-2 border-border bg-elevated/30">
                  <td className="px-3 py-2.5 text-xs font-semibold text-text-primary" colSpan={6}>
                    Totales · invertido ${fmtNum(totals.invertido)} · {totals.cerradas} cerrada{totals.cerradas === 1 ? '' : 's'} / {totals.abiertas} abierta{totals.abiertas === 1 ? '' : 's'}
                  </td>
                  <td className="px-3 py-2.5 text-right num text-text-secondary">
                    ${fmtNum(totals.fees)}
                  </td>
                  <td></td>
                  <td className={cn('px-3 py-2.5 text-right num font-semibold', pnlClass(totals.neto))}>
                    ${fmtNum(totals.neto)}
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {addOpen && (
        <TradeModal
          onClose={() => setAddOpen(false)}
          onSaved={() => { setAddOpen(false); load() }}
        />
      )}
      {editItem && (
        <TradeModal
          item={editItem}
          onClose={() => setEditItem(null)}
          onSaved={() => { setEditItem(null); load() }}
        />
      )}
    </div>
  )
}

// ── Modal unificado alta/edición ──────────────────────────────────────────────

function TradeModal({
  item,
  onClose,
  onSaved,
}: {
  item?: Trade
  onClose: () => void
  onSaved: () => void
}) {
  const isEdit = !!item

  // Selección de activo (solo en alta)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Asset[]>([])
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<{ accion_id: number; simbolo: string; nombre: string; mercado: string } | null>(
    item ? { accion_id: item.accion_id, simbolo: item.simbolo, nombre: item.nombre, mercado: item.mercado } : null,
  )
  const debounceRef = useRef<number | null>(null)

  // Campos del trade
  const [qty,        setQty]        = useState(item ? String(item.qty) : '')
  const [buyPrice,   setBuyPrice]   = useState(item ? String(item.buy_price) : '')
  const [buyDate,    setBuyDate]    = useState(item?.buy_date || todayISO())
  const [sellPrice,  setSellPrice]  = useState(item?.sell_price != null ? String(item.sell_price) : '')
  const [sellDate,   setSellDate]   = useState(item?.sell_date || '')
  const [fee,        setFee]        = useState(item ? String(item.fee) : '')
  const [note,       setNote]       = useState(item?.note || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // Buscador (solo alta)
  useEffect(() => {
    if (isEdit || selected) return
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    const q = query.trim()
    if (q.length < 1) {
      setResults([])
      return
    }
    debounceRef.current = window.setTimeout(async () => {
      setSearching(true)
      try {
        const res = await api.assets('', q, 0, 10)
        setResults(res.items)
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 200)
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
  }, [query, selected, isEdit])

  // Derivados para preview
  const preview = useMemo(() => {
    const q = parseFloat(qty)
    const bp = parseFloat(buyPrice)
    const sp = sellPrice ? parseFloat(sellPrice) : null
    const f  = fee ? parseFloat(fee) : 0
    if (!isFinite(q) || !isFinite(bp)) return null
    const invertido = q * bp
    if (sp == null || !isFinite(sp)) {
      return { invertido, gross: null, net: null, pct: null }
    }
    const gross = (sp - bp) * q
    const net = gross - f
    const pct = bp > 0 ? (sp / bp - 1) * 100 : null
    return { invertido, gross, net, pct }
  }, [qty, buyPrice, sellPrice, fee])

  const handleSave = async () => {
    if (!selected) {
      setError('Seleccioná un activo')
      return
    }
    const q = parseFloat(qty)
    const bp = parseFloat(buyPrice)
    if (!isFinite(q) || q <= 0)   { setError('Cantidad inválida'); return }
    if (!isFinite(bp) || bp <= 0) { setError('Precio de compra inválido'); return }
    if (!buyDate) { setError('Fecha de compra requerida'); return }

    const sp = sellPrice ? parseFloat(sellPrice) : null
    const sd = sellDate || null
    if ((sp != null) !== (sd != null)) {
      setError('Precio y fecha de venta deben completarse juntos')
      return
    }
    if (sp != null && !isFinite(sp)) { setError('Precio de venta inválido'); return }

    const f = fee ? parseFloat(fee) : 0
    if (!isFinite(f) || f < 0) { setError('Comisión inválida'); return }

    setSaving(true)
    setError('')
    try {
      if (isEdit && item) {
        await updateTrade(item.id, {
          qty: q,
          buy_price: bp,
          buy_date: buyDate,
          sell_price: sp,
          sell_date: sd,
          fee: f,
          note: note.trim() || null,
        })
      } else {
        const input: TradeInput = {
          accion_id: selected.accion_id,
          qty: q,
          buy_price: bp,
          buy_date: buyDate,
          sell_price: sp,
          sell_date: sd,
          fee: f,
          note: note.trim() || null,
        }
        await addTrade(input)
      }
      onSaved()
    } catch (e: any) {
      setError(e.message || 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="card-elevated w-full max-w-lg p-5 space-y-4 rounded-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {!isEdit && selected && (
              <button
                onClick={() => { setSelected(null); setQuery(''); setError('') }}
                className="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary cursor-pointer"
                title="Volver al buscador"
                aria-label="Volver al buscador"
              >
                <ArrowLeft size={14} />
              </button>
            )}
            <h2 className="text-sm font-semibold text-text-primary">
              {isEdit ? `Editar movimiento · ${item!.simbolo}` : 'Nuevo movimiento'}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>

        {/* Buscador (solo alta sin activo seleccionado) */}
        {!isEdit && !selected ? (
          <div className="relative">
            <div className="relative">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none" />
              <input
                autoFocus
                className="input pl-8"
                placeholder="Buscar ticker o nombre (ej: AAPL, Apple)"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              {searching && (
                <Loader2 size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted animate-spin" />
              )}
            </div>

            {results.length > 0 && (
              <div className="mt-2 card max-h-72 overflow-y-auto divide-y divide-border-subtle">
                {results.map(r => (
                  <button
                    key={r.accion_id}
                    className="w-full px-3 py-2 flex items-center justify-between text-left transition-colors hover:bg-elevated cursor-pointer"
                    onClick={() => setSelected({
                      accion_id: r.accion_id,
                      simbolo: r.simbolo,
                      nombre: r.nombre,
                      mercado: r.mercado,
                    })}
                  >
                    <div className="flex flex-col min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-sm text-text-primary">{r.simbolo}</span>
                        <span className="text-2xs text-text-muted">{r.mercado}</span>
                      </div>
                      <span className="text-xs text-text-muted truncate max-w-[300px]">{r.nombre}</span>
                    </div>
                    <div className="text-right shrink-0 ml-2">
                      <div className="num text-xs text-text-primary">
                        {r.precio != null ? `$${fmtNum(r.precio)}` : '—'}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            {!searching && query.trim().length >= 1 && results.length === 0 && (
              <p className="mt-2 text-xs text-text-muted text-center py-4">
                Sin resultados para "{query.trim()}"
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {/* Asset */}
            <div className="card-elevated border border-accent/30 p-3 flex items-center justify-between">
              <div className="flex flex-col min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold text-sm text-text-primary">{selected!.simbolo}</span>
                  <span className="text-2xs text-text-muted">{selected!.mercado}</span>
                </div>
                <span className="text-xs text-text-muted truncate max-w-[340px]">{selected!.nombre}</span>
              </div>
              {!isEdit && (
                <button
                  className="text-xs text-text-muted hover:text-text-primary cursor-pointer"
                  onClick={() => { setSelected(null); setQuery('') }}
                >
                  Cambiar
                </button>
              )}
            </div>

            {/* Cantidad + Comisión */}
            <div className="grid grid-cols-2 gap-2">
              <Field label="Cantidad">
                <input type="number" step="any" min="0" className="input" placeholder="0"
                  value={qty} onChange={(e) => setQty(e.target.value)} />
              </Field>
              <Field label="Comisión (total)">
                <input type="number" step="any" min="0" className="input" placeholder="0.00"
                  value={fee} onChange={(e) => setFee(e.target.value)} />
              </Field>
            </div>

            {/* Compra */}
            <div className="grid grid-cols-2 gap-2">
              <Field label="Precio de compra">
                <input type="number" step="any" min="0" className="input" placeholder="0.00"
                  value={buyPrice} onChange={(e) => setBuyPrice(e.target.value)} />
              </Field>
              <Field label="Fecha de compra">
                <input type="date" className="input"
                  value={buyDate} onChange={(e) => setBuyDate(e.target.value)} />
              </Field>
            </div>

            {/* Venta (opcional) */}
            <div className="grid grid-cols-2 gap-2">
              <Field label="Precio de venta (opcional)">
                <input type="number" step="any" min="0" className="input" placeholder="dejar vacío si abierto"
                  value={sellPrice} onChange={(e) => setSellPrice(e.target.value)} />
              </Field>
              <Field label="Fecha de venta">
                <input type="date" className="input"
                  value={sellDate} onChange={(e) => setSellDate(e.target.value)} />
              </Field>
            </div>

            {/* Nota */}
            <Field label="Nota (opcional)">
              <input type="text" maxLength={500} className="input" placeholder="Ej: swing BUY_CANDIDATE"
                value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>

            {/* Preview */}
            {preview && (
              <div className="bg-elevated/40 border border-border-subtle rounded-md px-3 py-2 text-xs grid grid-cols-4 gap-2">
                <Metric label="Invertido" value={`$${fmtNum(preview.invertido)}`} />
                <Metric label="G/P bruta" value={preview.gross != null ? `$${fmtNum(preview.gross)}` : '—'}
                  color={pnlClass(preview.gross)} />
                <Metric label="%" value={fmtPct(preview.pct)} color={pnlClass(preview.pct)} />
                <Metric label="Neto" value={preview.net != null ? `$${fmtNum(preview.net)}` : '—'}
                  color={pnlClass(preview.net)} />
              </div>
            )}

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-3 py-2 rounded-md">
                {error}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button className="btn-ghost text-xs" onClick={onClose}>Cancelar</button>
              <button className="btn-primary text-xs" onClick={handleSave} disabled={saving}>
                {saving && <Loader2 size={13} className="animate-spin" />}
                {isEdit ? 'Guardar' : 'Crear'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
        {label}
      </label>
      {children}
    </div>
  )
}

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-2xs text-text-muted uppercase tracking-wide">{label}</span>
      <span className={cn('num font-semibold text-sm', color || 'text-text-primary')}>{value}</span>
    </div>
  )
}
