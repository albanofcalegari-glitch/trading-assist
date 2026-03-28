/**
 * divergence.ts — Detección de divergencias RSI/Precio
 *
 * Bullish divergence:  precio hace mínimo más bajo + RSI hace mínimo más alto → posible rebote
 * Bearish divergence:  precio hace máximo más alto + RSI hace máximo más bajo → posible caída
 *
 * Filtros de calidad:
 *   Bullish: RSI en p2 < 50 (zona de sobreventa/neutral)
 *   Bearish: RSI en p2 > 50 (zona de sobrecompra/neutral)
 *
 * Solo se retornan las 3 divergencias más recientes para no sobrecargar la UI.
 */

import type { Candle } from './utils'

export interface DivergencePivot {
  idx:   number   // índice en el array original de candles
  fecha: string
  price: number   // low para bullish, high para bearish
  rsi:   number
}

export interface Divergence {
  type:     'BULLISH_DIVERGENCE' | 'BEARISH_DIVERGENCE'
  p1:       DivergencePivot   // pivote anterior
  p2:       DivergencePivot   // pivote más reciente
  strength: 'weak' | 'medium' | 'strong'
  rsiDiff:  number            // diferencia absoluta de RSI entre pivotes
}

function getStrength(rsiDiff: number): 'weak' | 'medium' | 'strong' {
  if (rsiDiff >= 15) return 'strong'
  if (rsiDiff >= 7)  return 'medium'
  return 'weak'
}

export function detectDivergences(
  candles:   Candle[],
  rsiValues: (number | null)[],
  win      = 3,     // ventana para pivot detection
  lookback = 120,   // barras hacia atrás donde buscar
): Divergence[] {
  const n     = candles.length
  const start = Math.max(win, n - lookback)

  // ── Pivot lows (para bullish) ─────────────────────────────────────────────
  const pivLows: DivergencePivot[] = []
  for (let i = start; i < n - win; i++) {
    const r = rsiValues[i]
    if (r == null) continue
    const low = Number(candles[i].low)
    if (low <= 0) continue
    const leftOk  = candles.slice(i - win, i).every(c => Number(c.low) >= low)
    const rightOk = candles.slice(i + 1, i + win + 1).every(c => Number(c.low) >= low)
    if (leftOk && rightOk) pivLows.push({ idx: i, fecha: candles[i].fecha, price: low, rsi: r })
  }

  // ── Pivot highs (para bearish) ────────────────────────────────────────────
  const pivHighs: DivergencePivot[] = []
  for (let i = start; i < n - win; i++) {
    const r = rsiValues[i]
    if (r == null) continue
    const high = Number(candles[i].high)
    if (high <= 0) continue
    const leftOk  = candles.slice(i - win, i).every(c => Number(c.high) <= high)
    const rightOk = candles.slice(i + 1, i + win + 1).every(c => Number(c.high) <= high)
    if (leftOk && rightOk) pivHighs.push({ idx: i, fecha: candles[i].fecha, price: high, rsi: r })
  }

  const divs: Divergence[] = []

  // ── Bullish: precio lower low + RSI higher low ────────────────────────────
  for (let i = 1; i < pivLows.length; i++) {
    const p1 = pivLows[i - 1]
    const p2 = pivLows[i]
    if (p2.idx - p1.idx < 5) continue      // demasiado juntos
    if (p2.price >= p1.price) continue     // precio NO hace lower low
    if (p2.rsi   <= p1.rsi)  continue     // RSI NO hace higher low
    if (p2.rsi   >= 50)      continue     // filtro: RSI < 50

    const diff = p2.rsi - p1.rsi
    divs.push({ type: 'BULLISH_DIVERGENCE', p1, p2, strength: getStrength(diff), rsiDiff: diff })
  }

  // ── Bearish: precio higher high + RSI lower high ─────────────────────────
  for (let i = 1; i < pivHighs.length; i++) {
    const p1 = pivHighs[i - 1]
    const p2 = pivHighs[i]
    if (p2.idx - p1.idx < 5) continue      // demasiado juntos
    if (p2.price <= p1.price) continue     // precio NO hace higher high
    if (p2.rsi   >= p1.rsi)  continue     // RSI NO hace lower high
    if (p2.rsi   <= 50)      continue     // filtro: RSI > 50

    const diff = p1.rsi - p2.rsi
    divs.push({ type: 'BEARISH_DIVERGENCE', p1, p2, strength: getStrength(diff), rsiDiff: diff })
  }

  // Las 3 más recientes primero
  return divs.sort((a, b) => b.p2.idx - a.p2.idx).slice(0, 3)
}
