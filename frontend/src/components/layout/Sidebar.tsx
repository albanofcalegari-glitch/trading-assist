import { useEffect, useMemo, useState } from 'react'
import { NavLink, Link } from 'react-router-dom'
import {
  LayoutDashboard, ScanLine, Bell, Settings, TrendingUp, X,
  ChevronsLeft, ChevronsRight, Star, BookOpen, Activity,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'

const BASE_NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/screener',  icon: ScanLine,         label: 'Screener' },
  { to: '/alerts',    icon: Bell,             label: 'Alertas' },
  { to: '/watchlist', icon: Star,             label: 'Watchlist' },
  { to: '/elliott',   icon: Activity,         label: 'Elliott Wave' },
]

const MOVIMIENTOS_ITEM = {
  to: '/movimientos', icon: BookOpen, label: 'Movimientos',
}

const NAV_BOTTOM = [
  { to: '/settings', icon: Settings, label: 'Configuración' },
]

const COLLAPSE_KEY = 'trading.sidebarCollapsed'

interface Props {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: Props) {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  })
  const { username } = useAuth()

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  const NAV = useMemo(() => (
    username === 'albano' ? [...BASE_NAV, MOVIMIENTOS_ITEM] : BASE_NAV
  ), [username])

  return (
    <>
      {/* Backdrop móvil */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={onClose}
          aria-hidden
        />
      )}

      <aside
        className={cn(
          'fixed md:static z-40 shrink-0 flex flex-col border-r border-border bg-surface h-full',
          'transition-[width,transform] duration-200 ease-out',
          collapsed ? 'md:w-[64px]' : 'md:w-[220px]',
          'w-[220px]',
          open ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
        )}
      >
        {/* Header con logo + collapse */}
        <div className={cn(
          'flex items-center h-14 border-b border-border gap-1',
          collapsed ? 'md:px-2 px-4' : 'px-3',
        )}>
          <Link
            to="/dashboard"
            onClick={onClose}
            className="flex items-center gap-2.5 flex-1 min-w-0 cursor-pointer
                       hover:opacity-90 transition-opacity"
            aria-label="Ir al dashboard"
            title="Trading Assist"
          >
            <div className="w-7 h-7 rounded-md bg-accent/20 flex items-center justify-center shrink-0">
              <TrendingUp size={14} className="text-accent" />
            </div>
            {!collapsed && (
              <span className="font-semibold text-sm text-text-primary tracking-tight truncate">
                Trading Assist
              </span>
            )}
          </Link>

          {/* Collapse — solo desktop, visible siempre */}
          <button
            type="button"
            onClick={() => setCollapsed(c => !c)}
            className={cn(
              'hidden md:flex items-center justify-center w-7 h-7 rounded-md shrink-0',
              'text-text-muted hover:text-text-primary hover:bg-elevated transition-colors cursor-pointer',
            )}
            title={collapsed ? 'Expandir' : 'Contraer'}
            aria-label={collapsed ? 'Expandir sidebar' : 'Contraer sidebar'}
          >
            {collapsed ? <ChevronsRight size={15} /> : <ChevronsLeft size={15} />}
          </button>

          {/* Cerrar — solo móvil */}
          <button
            onClick={onClose}
            className="md:hidden p-1 rounded-md hover:bg-elevated text-text-muted cursor-pointer"
            aria-label="Cerrar menú"
          >
            <X size={16} />
          </button>
        </div>

        {/* Nav principal */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {!collapsed && (
            <p className="px-3 py-2 text-2xs text-text-muted font-medium uppercase tracking-wider">
              Navegación
            </p>
          )}
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'nav-item',
                  isActive && 'nav-item-active',
                  collapsed && 'md:justify-center md:px-0',
                )
              }
            >
              <Icon size={15} />
              {!collapsed && <span className="md:inline">{label}</span>}
              {collapsed && <span className="md:hidden">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Nav inferior */}
        <div className="px-2 pb-3 border-t border-border pt-3 space-y-0.5">
          {NAV_BOTTOM.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'nav-item',
                  isActive && 'nav-item-active',
                  collapsed && 'md:justify-center md:px-0',
                )
              }
            >
              <Icon size={15} />
              {!collapsed && <span className="md:inline">{label}</span>}
              {collapsed && <span className="md:hidden">{label}</span>}
            </NavLink>
          ))}
        </div>
      </aside>
    </>
  )
}
