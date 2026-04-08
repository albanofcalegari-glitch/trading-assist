/**
 * gapFilter — selector global de filtro GAP para señales de compra.
 *
 * El threshold se persiste en localStorage. Cuando una señal viene con
 * decision = 'BUY_CANDIDATE' y |gap_pct| >= threshold, el cliente la
 * transforma a 'AWAITING_CONFIRMATION' visualmente.
 *
 * El backend NO filtra hard: siempre guarda gap_pct, y el cliente decide.
 * Esto permite cambiar el threshold sin reprocesar batches.
 */
import { createContext, useContext, useEffect, useState, useCallback } from 'react'
import type { ReactNode } from 'react'

const KEY = 'trading.gapThreshold'

// 0 = filtro desactivado
export type GapThreshold = 0 | 2 | 2.5 | 3
export const GAP_OPTIONS: GapThreshold[] = [0, 2, 2.5, 3]

interface Ctx {
  threshold: GapThreshold
  setThreshold: (t: GapThreshold) => void
}

const GapCtx = createContext<Ctx>({ threshold: 0, setThreshold: () => {} })

export function GapFilterProvider({ children }: { children: ReactNode }) {
  const [threshold, setThresholdState] = useState<GapThreshold>(() => {
    const raw = localStorage.getItem(KEY)
    const n = raw ? Number(raw) : 0
    return (GAP_OPTIONS as number[]).includes(n) ? (n as GapThreshold) : 0
  })

  const setThreshold = useCallback((t: GapThreshold) => {
    setThresholdState(t)
    localStorage.setItem(KEY, String(t))
  }, [])

  // Sincronizar entre tabs
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== KEY || !e.newValue) return
      const n = Number(e.newValue)
      if ((GAP_OPTIONS as number[]).includes(n)) setThresholdState(n as GapThreshold)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  return <GapCtx.Provider value={{ threshold, setThreshold }}>{children}</GapCtx.Provider>
}

export const useGapFilter = () => useContext(GapCtx)

/**
 * Aplica el filtro a una señal: si threshold > 0 y |gap_pct| >= threshold y
 * la decisión actual es BUY_CANDIDATE, devuelve 'AWAITING_CONFIRMATION'.
 * Si no, devuelve la decisión original.
 */
export function applyGapFilter(
  decision: string | null | undefined,
  gapPct: number | null | undefined,
  threshold: GapThreshold,
): { decision: string; gapBlocked: boolean } {
  if (
    threshold > 0 &&
    decision === 'BUY_CANDIDATE' &&
    gapPct != null &&
    Math.abs(gapPct) >= threshold
  ) {
    return { decision: 'AWAITING_CONFIRMATION', gapBlocked: true }
  }
  return { decision: decision || 'NO_ACTION', gapBlocked: false }
}
