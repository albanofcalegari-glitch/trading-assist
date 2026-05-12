import { useState } from 'react'
import { LogOut, KeyRound, Menu } from 'lucide-react'
import { changePassword } from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface HeaderProps {
  onOpenSidebar?: () => void
}

export default function Header({ onOpenSidebar }: HeaderProps = {}) {
  const { username, logout } = useAuth()
  const [showPwModal, setShowPwModal] = useState(false)

  return (
    <header className="h-14 border-b border-border bg-surface flex items-center px-3 md:px-6 gap-2 md:gap-4 shrink-0">
      {/* Hamburger — solo movil */}
      <button
        onClick={onOpenSidebar}
        className="md:hidden p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-text-primary transition-colors"
        aria-label="Abrir menu"
      >
        <Menu size={18} />
      </button>

      <div className="flex-1" />

      {/* Fecha */}
      <span className="hidden lg:inline text-xs text-text-muted">
        {new Date().toLocaleDateString('es-AR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })}
      </span>

      {/* User menu */}
      <div className="flex items-center gap-1.5 md:gap-2 md:ml-4 md:pl-4 md:border-l md:border-border">
        <span className="hidden sm:inline text-xs text-text-secondary font-medium">{username}</span>
        <button
          onClick={() => setShowPwModal(true)}
          className="p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-text-primary transition-colors"
          title="Cambiar contrasena"
        >
          <KeyRound size={14} />
        </button>
        <button
          onClick={logout}
          className="p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-red-400 transition-colors"
          title="Cerrar sesion"
        >
          <LogOut size={14} />
        </button>
      </div>

      {showPwModal && <ChangePasswordModal onClose={() => setShowPwModal(false)} />}
    </header>
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
