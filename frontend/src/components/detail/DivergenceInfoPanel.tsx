/**
 * DivergenceInfoPanel — Tabla con las divergencias detectadas.
 * Muestra: tipo, fuerza, RSI en p1/p2, diferencia, precios de los pivotes.
 */

import type { Divergence } from '@/lib/divergence'

interface Props {
  divergences: Divergence[]
  currentRsi:  number | null
}

const STRENGTH_LABEL: Record<string, string> = {
  weak:   'Débil',
  medium: 'Media',
  strong: 'Fuerte',
}

const STRENGTH_COLOR: Record<string, string> = {
  weak:   'text-yellow-400',
  medium: 'text-orange-400',
  strong: 'text-red-400',
}

export default function DivergenceInfoPanel({ divergences, currentRsi }: Props) {
  return (
    <div className="card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-text-secondary uppercase tracking-wide">
          Divergencias RSI
        </p>
        {currentRsi != null && (
          <span className="font-mono text-sm text-text-primary">
            RSI <span className={currentRsi >= 70 ? 'text-down' : currentRsi <= 30 ? 'text-up' : 'text-text-primary'}>
              {currentRsi.toFixed(1)}
            </span>
          </span>
        )}
      </div>

      {divergences.length === 0 ? (
        <p className="text-xs text-text-muted">Sin divergencias detectadas en las últimas 120 barras</p>
      ) : (
        <div className="space-y-2">
          {divergences.map((div, i) => {
            const isBullish = div.type === 'BULLISH_DIVERGENCE'
            return (
              <div
                key={i}
                className={`rounded-md px-3 py-2 border ${
                  isBullish
                    ? 'bg-up/5 border-up/20 text-up'
                    : 'bg-down/5 border-down/20 text-down'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold">
                    {isBullish ? '🟢 Alcista' : '🔴 Bajista'}
                  </span>
                  <span className={`text-xs font-medium ${STRENGTH_COLOR[div.strength]}`}>
                    {STRENGTH_LABEL[div.strength]}
                  </span>
                </div>
                <div className="mt-1 grid grid-cols-2 gap-x-4 text-2xs text-text-muted">
                  <span>Precio  {isBullish ? '↓' : '↑'}  ${div.p1.price.toFixed(2)} → ${div.p2.price.toFixed(2)}</span>
                  <span>RSI     {isBullish ? '↑' : '↓'}  {div.p1.rsi.toFixed(1)} → {div.p2.rsi.toFixed(1)}</span>
                  <span className="text-text-muted">{div.p1.fecha.slice(0, 10)}</span>
                  <span className={`font-mono font-semibold ${isBullish ? 'text-up' : 'text-down'}`}>
                    ΔRSI {isBullish ? '+' : '-'}{div.rsiDiff.toFixed(1)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
