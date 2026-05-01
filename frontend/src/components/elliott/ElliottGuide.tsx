import { useState } from 'react'
import { ChevronDown, ChevronUp, HelpCircle } from 'lucide-react'

export default function ElliottGuide() {
  const [open, setOpen] = useState(false)

  return (
    <div className="card border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-hover transition-colors"
      >
        <HelpCircle size={14} className="text-blue-400 shrink-0" />
        <span className="text-xs font-medium text-text-secondary">Guía rápida — Ondas de Elliott</span>
        {open ? <ChevronUp size={14} className="ml-auto text-text-muted" /> : <ChevronDown size={14} className="ml-auto text-text-muted" />}
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 text-2xs text-text-muted space-y-3 border-t border-border">
          <div>
            <p className="font-medium text-text-secondary mb-1">Ondas impulsivas (1-2-3-4-5)</p>
            <ul className="list-disc list-inside space-y-0.5">
              <li><span className="text-emerald-400">Onda 1</span> — Inicio del movimiento, volumen moderado</li>
              <li><span className="text-red-400">Onda 2</span> — Retroceso (no supera inicio de onda 1). Típico: 50-61.8% Fib</li>
              <li><span className="text-emerald-400">Onda 3</span> — La más fuerte y extendida, nunca la más corta. Target: 161.8% de onda 1</li>
              <li><span className="text-red-400">Onda 4</span> — Corrección moderada, no se solapa con onda 1</li>
              <li><span className="text-emerald-400">Onda 5</span> — Movimiento final, posible divergencia de momentum</li>
            </ul>
          </div>
          <div>
            <p className="font-medium text-text-secondary mb-1">Ondas correctivas (A-B-C)</p>
            <ul className="list-disc list-inside space-y-0.5">
              <li><span className="text-orange-400">Onda A</span> — Primer tramo de corrección</li>
              <li><span className="text-yellow-400">Onda B</span> — Rebote parcial (trampa alcista/bajista)</li>
              <li><span className="text-orange-400">Onda C</span> — Tramo final correctivo, suele igualar longitud de A</li>
            </ul>
          </div>
          <div>
            <p className="font-medium text-text-secondary mb-1">Señales del scanner</p>
            <ul className="list-disc list-inside space-y-0.5">
              <li><span className="text-emerald-400">BUY</span> — Final de onda 2 o 4 (inicio de impulso)</li>
              <li><span className="text-red-400">SELL</span> — Final de onda 5 o B (inicio de corrección)</li>
              <li><span className="text-gray-400">HOLD</span> — Mitad de movimiento, sin punto de entrada claro</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
