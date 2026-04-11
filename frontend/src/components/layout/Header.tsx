import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, X, LogOut, KeyRound, Menu } from 'lucide-react'
import { api, changePassword, type Asset } from '@/lib/api'
import { fmtPrice, fmtPct, pctClass } from '@/lib/utils'
import { useAuth } from '@/lib/auth'
import { useGapFilter, GAP_OPTIONS, type GapThreshold } from '@/lib/gapFilter'

interface HeaderProps {
  onOpenSidebar?: () => void
}

export default function Header({ onOpenSidebar }: HeaderProps = {}) {
  const { username, logout } = useAuth()
  const [query,   setQuery]   = useState('')
  const [results, setResults] = useState<Asset[]>([])
  const [open,    setOpen]    = useState(false)
  const [loading, setLoading] = useState(false)
  const [showPwModal, setShowPwModal] = useState(false)
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
    if (query.trim().length < 1) { setResults([]); setOpen(false); return }
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
    <header className="h-14 border-b border-border bg-surface flex items-center px-3 md:px-6 gap-2 md:gap-4 shrink-0">
      {/* Hamburger — solo móvil */}
      <button
        onClick={onOpenSidebar}
        className="md:hidden p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-text-primary transition-colors"
        aria-label="Abrir menú"
      >
        <Menu size={18} />
      </button>

      {/* Search */}
      <div ref={ref} className="relative flex-1 md:flex-none md:w-72 max-w-xs">
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

      {/* Spacer — sólo en desktop */}
      <div className="hidden md:block flex-1" />

      {/* Filtro Gap global */}
      <GapFilterControl />

      {/* Fecha — sólo en desktop */}
      <span className="hidden lg:inline text-xs text-text-muted">
        {new Date().toLocaleDateString('es-AR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
      </span>

      {/* User menu */}
      <div className="flex items-center gap-1.5 md:gap-2 md:ml-4 md:pl-4 md:border-l md:border-border">
        <span className="hidden sm:inline text-xs text-text-secondary font-medium">{username}</span>
        <button
          onClick={() => setShowPwModal(true)}
          className="p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-text-primary transition-colors"
          title="Cambiar contraseña"
        >
          <KeyRound size={14} />
        </button>
        <button
          onClick={logout}
          className="p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-red-400 transition-colors"
          title="Cerrar sesión"
        >
          <LogOut size={14} />
        </button>
      </div>

      {/* Change password modal */}
      {showPwModal && <ChangePasswordModal onClose={() => setShowPwModal(false)} />}
    </header>
  )
}

function GapFilterControl() {
  const { threshold, setThreshold } = useGapFilter()
  return (
    <div
      className="hidden md:flex items-center gap-1 text-2xs"
      title="Filtro de gap de apertura: las señales BUY con |gap| ≥ threshold se marcan como 'esperando confirmación'"
    >
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
          >
            {opt === 0 ? 'Off' : `${opt}%`}
          </button>
        ))}
      </div>
    </div>
  )
}

function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (newPw !== confirm) { setError('Las contraseñas no coinciden'); return }
    if (newPw.length < 6) { setError('Mínimo 6 caracteres'); return }
    setLoading(true)
    try {
      await changePassword(current, newPw)
      setSuccess(true)
      setTimeout(onClose, 1500)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60" onClick={onClose}>
      <form
        onClick={e => e.stopPropagation()}
        onSubmit={submit}
        className="card p-6 w-full max-w-sm space-y-4"
      >
        <h2 className="text-sm font-semibold text-text-primary">Cambiar contraseña</h2>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}
        {success && (
          <div className="bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2 text-xs text-green-400">
            Contraseña actualizada
          </div>
        )}

        <div>
          <label className="block text-xs text-text-secondary mb-1">Contraseña actual</label>
          <input type="password" className="input h-9 w-full" value={current}
                 onChange={e => setCurrent(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="block text-xs text-text-secondary mb-1">Nueva contraseña</label>
          <input type="password" className="input h-9 w-full" value={newPw}
                 onChange={e => setNewPw(e.target.value)} />
        </div>
        <div>
          <label className="block text-xs text-text-secondary mb-1">Confirmar nueva contraseña</label>
          <input type="password" className="input h-9 w-full" value={confirm}
                 onChange={e => setConfirm(e.target.value)} />
        </div>

        <div className="flex gap-2 pt-2">
          <button type="submit" disabled={loading}
                  className="flex-1 h-9 rounded-lg bg-accent hover:bg-accent/90 text-white text-xs font-medium
                             disabled:opacity-50">
            {loading ? 'Guardando...' : 'Guardar'}
          </button>
          <button type="button" onClick={onClose}
                  className="flex-1 h-9 rounded-lg bg-elevated hover:bg-elevated/80 text-text-secondary text-xs">
            Cancelar
          </button>
        </div>
      </form>
    </div>
  )
}
