import { Moon, Sun, Palette, User } from 'lucide-react'
import { useTheme } from '@/lib/theme'
import { useAuth } from '@/lib/auth'

export default function Settings() {
  const { theme, setTheme } = useTheme()
  const { username, investorProfile } = useAuth()

  return (
    <div className="space-y-5 max-w-2xl">
      {/* Header */}
      <div>
        <h1 className="text-base font-semibold text-text-primary">Configuración</h1>
        <p className="text-xs text-text-muted mt-0.5">Preferencias de la aplicación</p>
      </div>

      {/* Apariencia */}
      <section className="card p-4 md:p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Palette size={14} className="text-accent" />
          <h2 className="text-sm font-semibold text-text-primary">Apariencia</h2>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-text-secondary">Tema</p>
            <p className="text-2xs text-text-muted mt-0.5">
              Se guarda en este navegador.
            </p>
          </div>

          <div className="flex items-center gap-1 border border-border rounded-md p-0.5">
            <ThemeOption
              active={theme === 'dark'}
              onClick={() => setTheme('dark')}
              icon={<Moon size={13} />}
              label="Oscuro"
            />
            <ThemeOption
              active={theme === 'light'}
              onClick={() => setTheme('light')}
              icon={<Sun size={13} />}
              label="Claro"
            />
          </div>
        </div>
      </section>

      {/* Cuenta — info read-only por ahora */}
      <section className="card p-4 md:p-5 space-y-3">
        <div className="flex items-center gap-2">
          <User size={14} className="text-accent" />
          <h2 className="text-sm font-semibold text-text-primary">Cuenta</h2>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
          <div>
            <p className="text-text-muted text-2xs uppercase tracking-wider">Usuario</p>
            <p className="text-text-primary mt-0.5">{username || '—'}</p>
          </div>
          <div>
            <p className="text-text-muted text-2xs uppercase tracking-wider">Perfil de inversor</p>
            <p className="text-text-primary mt-0.5 capitalize">{investorProfile || '—'}</p>
          </div>
        </div>
      </section>
    </div>
  )
}

function ThemeOption({
  active, onClick, icon, label,
}: {
  active: boolean; onClick: () => void; icon: React.ReactNode; label: string
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded transition-colors cursor-pointer ${
        active
          ? 'bg-accent text-white'
          : 'text-text-secondary hover:text-text-primary hover:bg-elevated'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}
