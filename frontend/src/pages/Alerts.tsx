import { Bell } from 'lucide-react'

export default function Alerts() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-base font-semibold text-text-primary">Alertas</h1>
        <p className="text-xs text-text-muted mt-0.5">Notificaciones y señales configuradas</p>
      </div>

      <div className="card flex flex-col items-center justify-center py-16 gap-3">
        <div className="w-10 h-10 rounded-xl bg-elevated flex items-center justify-center">
          <Bell size={18} className="text-text-muted" />
        </div>
        <p className="text-sm text-text-secondary">Próximamente</p>
        <p className="text-xs text-text-muted text-center max-w-xs">
          Configuración de alertas por precio, cruce de medias y señales de estrategia.
        </p>
      </div>
    </div>
  )
}
