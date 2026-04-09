import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null || isNaN(n)) return '—'
  return n.toFixed(decimals)
}

export function fmtPrice(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  if (n >= 1000) return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n.toFixed(2)
}

export function fmtPct(n: number | null | undefined): string {
  if (n == null || isNaN(n)) return '—'
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

export function fmtVol(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000)     return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

export function pctClass(n: number | null | undefined): string {
  if (n == null || n === 0) return 'price-flat'
  return n > 0 ? 'price-up' : 'price-down'
}

/** Calcula WMA(n) para el array de precios de cierre */
export function calcWMA(closes: number[], n: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  for (let i = n - 1; i < closes.length; i++) {
    let sum = 0, wsum = 0
    for (let j = 0; j < n; j++) {
      const w = j + 1
      sum  += closes[i - (n - 1 - j)] * w
      wsum += w
    }
    result[i] = sum / wsum
  }
  return result
}

/** Calcula SMA(n) */
export function calcSMA(closes: number[], n: number): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  for (let i = n - 1; i < closes.length; i++) {
    let sum = 0
    for (let j = 0; j < n; j++) sum += closes[i - j]
    result[i] = sum / n
  }
  return result
}

/** Resample OHLCV a semanal/mensual */
export type Candle = {
  fecha: string
  open: number; high: number; low: number; close: number; volume: number
}

export function resampleOHLCV(candles: Candle[], freq: 'W' | 'M'): Candle[] {
  if (!candles.length) return []
  const out: Candle[] = []
  let bucket: Candle[] = []

  const key = (d: string) => {
    // Parsear como LOCAL time — new Date("YYYY-MM-DD") da UTC midnight,
    // que en zonas horarias negativas (ej. UTC-3 Argentina) desplaza
    // getDay() al día anterior, rompiendo los límites de semana ISO.
    const [yr, mo, dy] = d.split('-').map(Number)
    const dt = new Date(yr, mo - 1, dy)
    if (freq === 'M') return `${yr}-${mo}`
    // Semana ISO: semanas comienzan en lunes
    const tmp = new Date(yr, mo - 1, dy)
    tmp.setDate(tmp.getDate() + 4 - (tmp.getDay() || 7))
    const y = tmp.getFullYear()
    const w = Math.ceil(((tmp.getTime() - new Date(y, 0, 1).getTime()) / 86400000 + 1) / 7)
    return `${y}-${w}`
  }

  let currentKey = key(candles[0].fecha)

  for (const c of candles) {
    const k = key(c.fecha)
    if (k !== currentKey) {
      if (bucket.length) {
        const highs = bucket.map(b => b.high).filter(v => v != null) as number[]
        const lows  = bucket.map(b => b.low).filter(v => v != null) as number[]
        out.push({
          fecha:  bucket[bucket.length - 1].fecha,
          open:   bucket[0].open,
          high:   highs.length ? Math.max(...highs) : bucket[bucket.length - 1].close,
          low:    lows.length  ? Math.min(...lows)  : bucket[bucket.length - 1].close,
          close:  bucket[bucket.length - 1].close,
          volume: bucket.reduce((s, b) => s + b.volume, 0),
        })
      }
      bucket     = [c]
      currentKey = k
    } else {
      bucket.push(c)
    }
  }
  if (bucket.length) {
    const highs = bucket.map(b => b.high).filter(v => v != null) as number[]
    const lows  = bucket.map(b => b.low).filter(v => v != null) as number[]
    out.push({
      fecha:  bucket[bucket.length - 1].fecha,
      open:   bucket[0].open,
      high:   highs.length ? Math.max(...highs) : bucket[bucket.length - 1].close,
      low:    lows.length  ? Math.min(...lows)  : bucket[bucket.length - 1].close,
      close:  bucket[bucket.length - 1].close,
      volume: bucket.reduce((s, b) => s + b.volume, 0),
    })
  }
  return out
}

/** ADX — Average Directional Index (período 14 por defecto)
 *  Retorna { adx, plusDI, minusDI } arrays alineados con candles.
 */
export function calcADX(
  candles: Candle[],
  period = 14,
): { adx: (number | null)[]; plusDI: (number | null)[]; minusDI: (number | null)[] } {
  const len = candles.length
  const adx:     (number | null)[] = new Array(len).fill(null)
  const plusDI:  (number | null)[] = new Array(len).fill(null)
  const minusDI: (number | null)[] = new Array(len).fill(null)
  if (len < period * 2 + 1) return { adx, plusDI, minusDI }

  // True Range, +DM, -DM raw
  const tr:  number[] = [0]
  const pdm: number[] = [0]
  const ndm: number[] = [0]

  for (let i = 1; i < len; i++) {
    const h  = Number(candles[i].high)
    const l  = Number(candles[i].low)
    const pc = Number(candles[i - 1].close)
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)))

    const upMove   = h - Number(candles[i - 1].high)
    const downMove = Number(candles[i - 1].low) - l
    pdm.push(upMove > downMove && upMove > 0 ? upMove : 0)
    ndm.push(downMove > upMove && downMove > 0 ? downMove : 0)
  }

  // Wilder smoothing para ATR, +DM14, -DM14
  let atr14 = 0, pdm14 = 0, ndm14 = 0
  for (let i = 1; i <= period; i++) {
    atr14 += tr[i]; pdm14 += pdm[i]; ndm14 += ndm[i]
  }

  const smooth = (prev: number, cur: number) => prev - prev / period + cur

  // Primer valor de DI en index = period
  let pdi = atr14 > 0 ? (pdm14 / atr14) * 100 : 0
  let ndi = atr14 > 0 ? (ndm14 / atr14) * 100 : 0
  plusDI[period]  = pdi
  minusDI[period] = ndi

  const dxArr: number[] = []
  const sumPdiNdi = pdi + ndi
  dxArr.push(sumPdiNdi > 0 ? (Math.abs(pdi - ndi) / sumPdiNdi) * 100 : 0)

  for (let i = period + 1; i < len; i++) {
    atr14 = smooth(atr14, tr[i])
    pdm14 = smooth(pdm14, pdm[i])
    ndm14 = smooth(ndm14, ndm[i])

    pdi = atr14 > 0 ? (pdm14 / atr14) * 100 : 0
    ndi = atr14 > 0 ? (ndm14 / atr14) * 100 : 0
    plusDI[i]  = pdi
    minusDI[i] = ndi

    const s = pdi + ndi
    dxArr.push(s > 0 ? (Math.abs(pdi - ndi) / s) * 100 : 0)
  }

  // ADX = Wilder smooth de DX (necesita otro período de warm-up)
  if (dxArr.length < period) return { adx, plusDI, minusDI }

  let adxVal = 0
  for (let i = 0; i < period; i++) adxVal += dxArr[i]
  adxVal /= period
  adx[period * 2] = adxVal

  for (let i = period; i < dxArr.length; i++) {
    adxVal = (adxVal * (period - 1) + dxArr[i]) / period
    adx[period + i] = adxVal
  }

  return { adx, plusDI, minusDI }
}

/** RSI de Wilder (período 14 por defecto) */
export function calcRSI(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length < period + 1) return result

  let avgGain = 0, avgLoss = 0
  for (let i = 1; i <= period; i++) {
    const diff = closes[i] - closes[i - 1]
    if (diff > 0) avgGain += diff
    else          avgLoss -= diff
  }
  avgGain /= period
  avgLoss /= period

  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)

  for (let i = period + 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1]
    const gain = diff > 0 ? diff : 0
    const loss = diff < 0 ? -diff : 0
    avgGain = (avgGain * (period - 1) + gain) / period
    avgLoss = (avgLoss * (period - 1) + loss) / period
    result[i] = avgLoss === 0 ? 100 : avgGain === 0 ? 0 : 100 - 100 / (1 + avgGain / avgLoss)
  }
  return result
}
