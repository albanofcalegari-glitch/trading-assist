// UT Bot trailing stop (QuantNomad / Yo_adriiiiaan variant) — port del módulo
// Python `strategies/ut_bot.py` para correr en el frontend sobre las velas
// resampleadas (D/W/M) y asegurar que los markers aterricen exactamente sobre
// los bars visibles en el chart.

import type { Candle } from '@/lib/utils'

export interface UtBotPoint {
  fecha: string
  value: number
  state: 'UP' | 'DOWN'
}

export interface UtBotSignal {
  fecha: string
  kind:  'BUY' | 'SELL'
  price: number
}

export interface UtBotResult {
  points:  UtBotPoint[]
  signals: UtBotSignal[]
}

function wilderATR(high: number[], low: number[], close: number[], period: number): (number | null)[] {
  const n = close.length
  const atr: (number | null)[] = new Array(n).fill(null)
  if (n < period + 1) return atr

  const tr: number[] = [high[0] - low[0]]
  for (let i = 1; i < n; i++) {
    tr.push(Math.max(
      high[i] - low[i],
      Math.abs(high[i] - close[i - 1]),
      Math.abs(low[i]  - close[i - 1]),
    ))
  }

  let seed = 0
  for (let i = 0; i < period; i++) seed += tr[i]
  seed /= period
  atr[period - 1] = seed

  for (let i = period; i < n; i++) {
    const prev = atr[i - 1] ?? seed
    atr[i] = (prev * (period - 1) + tr[i]) / period
  }
  return atr
}

export function computeUtBot(
  candles:     Candle[],
  sensitivity: number = 2.0,
  atrPeriod:   number = 10,
): UtBotResult {
  if (candles.length < atrPeriod + 2) return { points: [], signals: [] }

  const high  = candles.map(c => Number(c.high))
  const low   = candles.map(c => Number(c.low))
  const close = candles.map(c => Number(c.close))
  const atr   = wilderATR(high, low, close, atrPeriod)

  const n = candles.length
  const trailing: (number | null)[] = new Array(n).fill(null)
  const state:    ('UP' | 'DOWN' | null)[] = new Array(n).fill(null)

  const start = atrPeriod - 1
  const a0    = atr[start] ?? 0
  const nloss0 = sensitivity * a0
  trailing[start] = close[start] - nloss0
  state[start]    = close[start] > (trailing[start] as number) ? 'UP' : 'DOWN'

  for (let i = start + 1; i < n; i++) {
    const a  = atr[i] ?? 0
    const nl = sensitivity * a
    const prev = trailing[i - 1] as number

    let t: number
    if (close[i] > prev && close[i - 1] > prev) {
      t = Math.max(prev, close[i] - nl)
    } else if (close[i] < prev && close[i - 1] < prev) {
      t = Math.min(prev, close[i] + nl)
    } else if (close[i] > prev) {
      t = close[i] - nl
    } else {
      t = close[i] + nl
    }
    trailing[i] = t
    state[i]    = close[i] > t ? 'UP' : 'DOWN'
  }

  const points: UtBotPoint[] = []
  for (let i = start; i < n; i++) {
    points.push({
      fecha: candles[i].fecha,
      value: Math.round((trailing[i] as number) * 10000) / 10000,
      state: state[i] as 'UP' | 'DOWN',
    })
  }

  const signals: UtBotSignal[] = []
  for (let i = start + 1; i < n; i++) {
    if (state[i - 1] === 'DOWN' && state[i] === 'UP') {
      signals.push({ fecha: candles[i].fecha, kind: 'BUY',  price: Math.round(close[i] * 10000) / 10000 })
    } else if (state[i - 1] === 'UP' && state[i] === 'DOWN') {
      signals.push({ fecha: candles[i].fecha, kind: 'SELL', price: Math.round(close[i] * 10000) / 10000 })
    }
  }

  return { points, signals }
}
