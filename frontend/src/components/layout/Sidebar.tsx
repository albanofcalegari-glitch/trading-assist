import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, ScanLine, Bell, Briefcase, Settings, TrendingUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/screener',  icon: ScanLine,         label: 'Screener' },
  { to: '/alerts',    icon: Bell,             label: 'Alertas' },
]

const NAV_BOTTOM = [
  { to: '/settings', icon: Settings, label: 'Configuración' },
]

export default function Sidebar() {
  return (
    <aside className="w-[220px] shrink-0 flex flex-col border-r border-border bg-surface h-full">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-4 h-14 border-b border-border">
        <div className="w-7 h-7 rounded-md bg-accent/20 flex items-center justify-center">
          <TrendingUp size={14} className="text-accent" />
        </div>
        <span className="font-semibold text-sm text-text-primary tracking-tight">
          Trading Assist
        </span>
      </div>

      {/* Nav principal */}
      <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
        <p className="px-3 py-2 text-2xs text-text-muted font-medium uppercase tracking-wider">
          Navegación
        </p>
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn('nav-item', isActive && 'nav-item-active')
            }
          >
            <Icon size={15} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Nav inferior */}
      <div className="px-2 pb-3 border-t border-border pt-3 space-y-0.5">
        {NAV_BOTTOM.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn('nav-item', isActive && 'nav-item-active')
            }
          >
            <Icon size={15} />
            <span>{label}</span>
          </NavLink>
        ))}
      </div>
    </aside>
  )
}
