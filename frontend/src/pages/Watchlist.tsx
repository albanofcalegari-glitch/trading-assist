import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Plus, Pencil, Trash2, RefreshCw, Star, Search, X, Loader2,
  TrendingUp, TrendingDown, ArrowLeft,
} from 'lucide-react'
import {
  api, addWatchlist, updateWatchlist, deleteWatchlist,
  type WatchlistItem, type Asset,
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

function pctClass(v: number | null | undefined): string {
  if (v == null) return 'price-flat'
  if (v > 0) return 'price-up'
  if (v < 0) return 'price-down'
  return 'price-flat'
}

// ── Página principal ──────────────────────────────────────────────────────────

export default function Watchlist() {
  const [items,   setItems]   = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [editItem, setEditItem] = useState<WatchlistItem | null>(null)
  const [deleteItem, setDeleteItem] = useState<WatchlistItem | null>(null)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.watchlist()
      setItems(res.items)
    } catch (e: any) {
      setError(e.message || 'Error al cargar la watchlist')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleDelete = async (item: WatchlistItem) => {
    try {
      await deleteWatchlist(item.id)
      setItems(xs => xs.filter(x => x.id !== item.id))
      setDeleteItem(null)
    } catch (e: any) {
      setError(e.message || 'Error al eliminar')
      setDeleteItem(null)
    }
  }

  const totals = useMemo(() => {
    let invertido = 0
    let valor = 0
    let anyPos = false
    for (const it of items) {
      if (it.qty != null && it.avg_buy_price != null) {
        invertido += it.qty * it.avg_buy_price
        anyPos = true
      }
      if (it.valor_corriente != null) {
        valor += it.valor_corriente
      }
    }
    if (!anyPos) return null
    const gan = valor - invertido
    const ganPct = invertido > 0 ? (valor / invertido - 1) * 100 : null
    return { invertido, valor, gan, ganPct }
  }, [items])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-base font-semibold text-text-primary flex items-center gap-2">
            <Star size={16} className="text-accent" />
            Watchlist
          </h1>
          <p className="text-xs text-text-muted mt-0.5">
            Activos a seguir · {items.length} {items.length === 1 ? 'activo' : 'activos'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-ghost text-xs gap-1.5" onClick={() => load()}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            Actualizar
          </button>
          <button className="btn-primary text-xs gap-1.5" onClick={() => setAddOpen(true)}>
            <Plus size={14} />
            Agregar activo
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
                <th className="table-header text-left  px-3 py-2.5">Especie</th>
                <th className="table-header text-right px-3 py-2.5">Disp.</th>
                <th className="table-header text-right px-3 py-2.5">Var día</th>
                <th className="table-header text-right px-3 py-2.5">Último precio</th>
                <th className="table-header text-right px-3 py-2.5">Precio compra</th>
                <th className="table-header text-right px-3 py-2.5">SL</th>
                <th className="table-header text-right px-3 py-2.5">TP</th>
                <th className="table-header text-right px-3 py-2.5">G/P %</th>
                <th className="table-header text-right px-3 py-2.5">Valor corriente</th>
                <th className="table-header text-right px-3 py-2.5 w-24">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {loading && items.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-center py-10 text-text-muted text-xs">
                    <Loader2 size={16} className="inline animate-spin mr-2" />
                    Cargando watchlist…
                  </td>
                </tr>
              )}
              {!loading && items.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-center py-10 text-text-muted text-xs">
                    Tu watchlist está vacía. Agregá tu primer activo con el botón de arriba.
                  </td>
                </tr>
              )}
              {items.map(it => (
                <tr
                  key={it.id}
                  className="table-row cursor-pointer"
                  onClick={() => navigate(`/asset/${it.accion_id}`)}
                >
                  {/* Especie */}
                  <td className="px-3 py-2">
                    <div className="flex flex-col min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-semibold text-text-primary">{it.simbolo}</span>
                        <span className="text-2xs text-text-muted">{it.mercado}</span>
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

                  {/* Disp. */}
                  <td className="px-3 py-2 text-right num text-text-secondary">
                    {it.qty != null ? fmtNum(it.qty, it.qty % 1 === 0 ? 0 : 4) : '—'}
                  </td>

                  {/* Var día */}
                  <td className={cn('px-3 py-2 text-right num', pctClass(it.pct_cambio_dia))}>
                    <div className="flex items-center justify-end gap-1">
                      {it.pct_cambio_dia != null && (
                        it.pct_cambio_dia > 0 ? <TrendingUp size={11} /> :
                        it.pct_cambio_dia < 0 ? <TrendingDown size={11} /> : null
                      )}
                      {fmtPct(it.pct_cambio_dia)}
                    </div>
                  </td>

                  {/* Último precio */}
                  <td className="px-3 py-2 text-right num text-text-primary">
                    {it.precio != null ? `$${fmtNum(it.precio)}` : '—'}
                  </td>

                  {/* Precio compra */}
                  <td className="px-3 py-2 text-right num text-text-secondary">
                    {it.avg_buy_price != null ? `$${fmtNum(it.avg_buy_price)}` : '—'}
                  </td>

                  {/* SL */}
                  <td className={cn('px-3 py-2 text-right num', it.stop_loss != null && it.precio != null && it.precio <= it.stop_loss ? 'text-red-400 font-semibold' : 'text-text-muted')}>
                    {it.stop_loss != null ? `$${fmtNum(it.stop_loss)}` : '—'}
                  </td>

                  {/* TP */}
                  <td className={cn('px-3 py-2 text-right num', it.take_profit != null && it.precio != null && it.precio >= it.take_profit ? 'text-green-400 font-semibold' : 'text-text-muted')}>
                    {it.take_profit != null ? `$${fmtNum(it.take_profit)}` : '—'}
                  </td>

                  {/* G/P % */}
                  <td className={cn('px-3 py-2 text-right num', pctClass(it.ganancia_pct))}>
                    {fmtPct(it.ganancia_pct)}
                  </td>

                  {/* Valor corriente */}
                  <td className="px-3 py-2 text-right num text-text-primary">
                    {it.valor_corriente != null ? `$${fmtNum(it.valor_corriente)}` : '—'}
                  </td>

                  {/* Acciones */}
                  <td className="px-3 py-2 text-right" onClick={(e) => e.stopPropagation()}>
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
                        onClick={() => setDeleteItem(it)}
                        title="Quitar"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>

            {/* Totales */}
            {totals && (
              <tfoot>
                <tr className="border-t-2 border-border bg-elevated/30">
                  <td className="px-3 py-2.5 text-xs font-semibold text-text-primary" colSpan={4}>
                    Totales · invertido ${fmtNum(totals.invertido)}
                  </td>
                  <td className="px-3 py-2.5" colSpan={3}></td>
                  <td className={cn('px-3 py-2.5 text-right num font-semibold', pctClass(totals.ganPct))}>
                    {fmtPct(totals.ganPct)}
                  </td>
                  <td className={cn('px-3 py-2.5 text-right num font-semibold', pctClass(totals.gan))}>
                    ${fmtNum(totals.valor)}
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {/* Modales */}
      {addOpen && (
        <AddWatchlistModal
          existingAccionIds={new Set(items.map(i => i.accion_id))}
          onClose={() => setAddOpen(false)}
          onAdded={() => { setAddOpen(false); load() }}
        />
      )}
      {editItem && (
        <EditWatchlistModal
          item={editItem}
          onClose={() => setEditItem(null)}
          onSaved={() => { setEditItem(null); load() }}
        />
      )}
      {deleteItem && (
        <ConfirmDeleteModal
          item={deleteItem}
          onClose={() => setDeleteItem(null)}
          onConfirm={() => handleDelete(deleteItem)}
        />
      )}
    </div>
  )
}

// ── Modal: agregar activo ─────────────────────────────────────────────────────

function AddWatchlistModal({
  existingAccionIds,
  onClose,
  onAdded,
}: {
  existingAccionIds: Set<number>
  onClose: () => void
  onAdded: () => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Asset[]>([])
  const [searching, setSearching] = useState(false)
  const [selected, setSelected] = useState<Asset | null>(null)
  const [qty, setQty] = useState('')
  const [avg, setAvg] = useState('')
  const [sl,  setSl]  = useState('')
  const [tp,  setTp]  = useState('')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const debounceRef = useRef<number | null>(null)

  // Debounced search
  useEffect(() => {
    if (selected) return
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
  }, [query, selected])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      await addWatchlist({
        accion_id:     selected.accion_id,
        qty:           qty ? parseFloat(qty) : null,
        avg_buy_price: avg ? parseFloat(avg) : null,
        stop_loss:     sl  ? parseFloat(sl)  : null,
        take_profit:   tp  ? parseFloat(tp)  : null,
        note:          note.trim() || null,
      })
      onAdded()
    } catch (e: any) {
      setError(e.message || 'Error al agregar')
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
        className="card-elevated w-full max-w-md p-5 space-y-4 rounded-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            {selected && (
              <button
                onClick={() => { setSelected(null); setQuery(''); setError('') }}
                className="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary cursor-pointer"
                title="Volver al buscador"
                aria-label="Volver al buscador"
              >
                <ArrowLeft size={14} />
              </button>
            )}
            <h2 className="text-sm font-semibold text-text-primary">Agregar a la watchlist</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>

        {/* Buscador / Seleccionado */}
        {!selected ? (
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
                {results.map(r => {
                  const dup = existingAccionIds.has(r.accion_id)
                  return (
                    <button
                      key={r.accion_id}
                      disabled={dup}
                      className={cn(
                        'w-full px-3 py-2 flex items-center justify-between text-left transition-colors',
                        dup ? 'opacity-40 cursor-not-allowed' : 'hover:bg-elevated cursor-pointer',
                      )}
                      onClick={() => !dup && setSelected(r)}
                    >
                      <div className="flex flex-col min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold text-sm text-text-primary">{r.simbolo}</span>
                          <span className="text-2xs text-text-muted">{r.mercado}</span>
                          {dup && <span className="text-2xs text-accent">· ya en lista</span>}
                        </div>
                        <span className="text-xs text-text-muted truncate max-w-[300px]">{r.nombre}</span>
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="num text-xs text-text-primary">
                          {r.precio != null ? `$${fmtNum(r.precio)}` : '—'}
                        </div>
                        <div className={cn('num text-2xs', pctClass(r.pct_cambio))}>
                          {fmtPct(r.pct_cambio)}
                        </div>
                      </div>
                    </button>
                  )
                })}
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
            {/* Asset seleccionado */}
            <div className="card-elevated border border-accent/30 p-3 flex items-center justify-between">
              <div className="flex flex-col min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-semibold text-sm text-text-primary">{selected.simbolo}</span>
                  <span className="text-2xs text-text-muted">{selected.mercado}</span>
                </div>
                <span className="text-xs text-text-muted truncate max-w-[300px]">{selected.nombre}</span>
              </div>
              <button
                className="text-xs text-text-muted hover:text-text-primary cursor-pointer"
                onClick={() => { setSelected(null); setQuery('') }}
              >
                Cambiar
              </button>
            </div>

            {/* Opcionales: qty + avg + note */}
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
                  Cantidad (opcional)
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="input"
                  placeholder="0"
                  value={qty}
                  onChange={(e) => setQty(e.target.value)}
                />
              </div>
              <div>
                <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
                  Precio compra (opcional)
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="input"
                  placeholder="0.00"
                  value={avg}
                  onChange={(e) => setAvg(e.target.value)}
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
                  Stop Loss (opcional)
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="input"
                  placeholder="0.00"
                  value={sl}
                  onChange={(e) => setSl(e.target.value)}
                />
              </div>
              <div>
                <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
                  Take Profit (opcional)
                </label>
                <input
                  type="number"
                  step="any"
                  min="0"
                  className="input"
                  placeholder="0.00"
                  value={tp}
                  onChange={(e) => setTp(e.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
                Nota (opcional)
              </label>
              <input
                type="text"
                maxLength={500}
                className="input"
                placeholder="Ej: esperar pullback a SMA50"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-3 py-2 rounded-md">
                {error}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button className="btn-ghost text-xs" onClick={onClose}>Cancelar</button>
              <button
                className="btn-primary text-xs"
                onClick={handleSave}
                disabled={saving}
              >
                {saving && <Loader2 size={13} className="animate-spin" />}
                Agregar
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Modal: editar activo ──────────────────────────────────────────────────────

function EditWatchlistModal({
  item,
  onClose,
  onSaved,
}: {
  item: WatchlistItem
  onClose: () => void
  onSaved: () => void
}) {
  const [qty,  setQty]  = useState(item.qty != null ? String(item.qty) : '')
  const [avg,  setAvg]  = useState(item.avg_buy_price != null ? String(item.avg_buy_price) : '')
  const [sl,   setSl]   = useState(item.stop_loss != null ? String(item.stop_loss) : '')
  const [tp,   setTp]   = useState(item.take_profit != null ? String(item.take_profit) : '')
  const [note, setNote] = useState(item.note || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      await updateWatchlist(item.id, {
        qty:           qty  === '' ? null : parseFloat(qty),
        avg_buy_price: avg  === '' ? null : parseFloat(avg),
        stop_loss:     sl   === '' ? null : parseFloat(sl),
        take_profit:   tp   === '' ? null : parseFloat(tp),
        note:          note.trim() || null,
      })
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
        className="card-elevated w-full max-w-md p-5 space-y-4 rounded-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">
            Editar {item.simbolo}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>

        <div className="text-xs text-text-muted -mt-1">{item.nombre}</div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
              Cantidad
            </label>
            <input
              type="number"
              step="any"
              min="0"
              className="input"
              placeholder="0"
              value={qty}
              onChange={(e) => setQty(e.target.value)}
            />
          </div>
          <div>
            <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
              Precio compra
            </label>
            <input
              type="number"
              step="any"
              min="0"
              className="input"
              placeholder="0.00"
              value={avg}
              onChange={(e) => setAvg(e.target.value)}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
              Stop Loss
            </label>
            <input
              type="number"
              step="any"
              min="0"
              className="input"
              placeholder="0.00"
              value={sl}
              onChange={(e) => setSl(e.target.value)}
            />
          </div>
          <div>
            <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
              Take Profit
            </label>
            <input
              type="number"
              step="any"
              min="0"
              className="input"
              placeholder="0.00"
              value={tp}
              onChange={(e) => setTp(e.target.value)}
            />
          </div>
        </div>
        <div>
          <label className="text-2xs text-text-muted uppercase tracking-wide block mb-1">
            Nota
          </label>
          <input
            type="text"
            maxLength={500}
            className="input"
            placeholder="Ej: esperar pullback a SMA50"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-400 text-xs px-3 py-2 rounded-md">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button className="btn-ghost text-xs" onClick={onClose}>Cancelar</button>
          <button
            className="btn-primary text-xs"
            onClick={handleSave}
            disabled={saving}
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            Guardar
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Modal: confirmar eliminación ─────────────────────────────────────────────

function ConfirmDeleteModal({
  item,
  onClose,
  onConfirm,
}: {
  item: WatchlistItem
  onClose: () => void
  onConfirm: () => void
}) {
  const [deleting, setDeleting] = useState(false)

  const handle = async () => {
    setDeleting(true)
    await onConfirm()
  }

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 p-4"
      onClick={onClose}
    >
      <div
        className="card-elevated w-full max-w-sm p-5 space-y-4 rounded-xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">Quitar de la watchlist</h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface text-text-muted hover:text-text-primary cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>

        <p className="text-xs text-text-muted">
          ¿Quitar <span className="font-semibold text-text-primary">{item.simbolo}</span> de tu watchlist?
          Se eliminarán también los niveles de SL/TP configurados.
        </p>

        <div className="flex items-center justify-end gap-2 pt-2">
          <button className="btn-ghost text-xs" onClick={onClose}>Cancelar</button>
          <button
            className="text-xs px-3 py-1.5 rounded-lg font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors cursor-pointer"
            onClick={handle}
            disabled={deleting}
          >
            {deleting && <Loader2 size={13} className="animate-spin inline mr-1" />}
            Eliminar
          </button>
        </div>
      </div>
    </div>
  )
}
