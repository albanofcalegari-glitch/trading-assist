import { useState, useEffect, useCallback, useMemo } from 'react'
import { RefreshCw, TrendingUp, TrendingDown, ChevronDown, ChevronUp } from 'lucide-react'
import {
  api,
  type BondAnalysis,
  type BondSpread,
  type BondHistoryRow,
  type BondCurvePoint,
  type SpreadPair,
} from '@/lib/api'
import { fmtPrice } from '@/lib/utils'

type LawFilter = 'ALL' | 'ARG' | 'NY'
type Tab = 'dashboard' | 'curve' | 'spreads'

function SignalBadge({ signal }: { signal: string | null }) {
  if (!signal || signal === 'NEUTRAL')
    return <span className="text-text-muted text-2xs">NEUTRAL</span>

  const isBuy = signal === 'BUY'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-semibold ${
      isBuy ? 'bg-up/15 text-up' : 'bg-down/15 text-down'
    }`}>
      {isBuy ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
      {isBuy ? 'COMPRAR' : 'VENDER'}
    </span>
  )
}

function BondDetailRow({ bond }: { bond: BondAnalysis }) {
  const [open, setOpen] = useState(false)
  const [history, setHistory] = useState<BondHistoryRow[]>([])
  const [loading, setLoading] = useState(false)

  const toggle = async () => {
    if (!open && history.length === 0) {
      setLoading(true)
      try {
        const res = await api.bondsHistory(bond.symbol, 30)
        setHistory(res.history)
      } finally {
        setLoading(false)
      }
    }
    setOpen(o => !o)
  }

  return (
    <>
      <tr
        onClick={toggle}
        className="border-b border-border/50 hover:bg-elevated/50 transition-colors cursor-pointer"
      >
        <td className="px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            {open ? <ChevronUp size={12} className="text-text-muted" /> : <ChevronDown size={12} className="text-text-muted" />}
            <span className="font-semibold text-text-primary">{bond.symbol}</span>
          </div>
        </td>
        <td className="px-3 py-2.5 text-center">
          <span className={`text-2xs px-1.5 py-0.5 rounded font-medium ${
            bond.law === 'ARG' ? 'bg-blue-500/15 text-blue-400' : 'bg-amber-500/15 text-amber-400'
          }`}>
            {bond.law}
          </span>
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-text-primary hidden sm:table-cell">
          {bond.maturity?.slice(0, 4)}
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-text-primary">
          {fmtPrice(bond.price_clean)}
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-accent font-medium">
          {bond.tir?.toFixed(2)}%
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-text-muted hidden md:table-cell">
          {bond.paridad?.toFixed(1)}%
        </td>
        <td className="px-3 py-2.5 text-right font-mono text-text-muted hidden md:table-cell">
          {bond.duration_mod?.toFixed(2)}
        </td>
        <td className={`px-3 py-2.5 text-right font-mono font-medium hidden sm:table-cell ${
          bond.z_score == null ? 'text-text-muted'
            : bond.z_score > 1.5 ? 'text-up'
            : bond.z_score < -1.5 ? 'text-down'
            : 'text-text-muted'
        }`}>
          {bond.z_score != null ? (bond.z_score >= 0 ? '+' : '') + bond.z_score.toFixed(2) : 'N/A'}
        </td>
        <td className="px-3 py-2.5 text-center">
          <SignalBadge signal={bond.signal} />
        </td>
      </tr>

      {open && (
        <tr className="border-b border-border/50">
          <td colSpan={9} className="px-4 py-3 bg-elevated/30">
            {loading ? (
              <div className="text-xs text-text-muted animate-pulse">Cargando historial...</div>
            ) : history.length === 0 ? (
              <div className="text-xs text-text-muted">Sin historial disponible</div>
            ) : (
              <div className="space-y-2">
                <p className="text-2xs text-text-muted font-medium uppercase tracking-wider">
                  Historial reciente (30 dias)
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-2xs">
                    <thead>
                      <tr className="text-text-muted">
                        <th className="text-left px-2 py-1 font-medium">Fecha</th>
                        <th className="text-right px-2 py-1 font-medium">Precio USD</th>
                        <th className="text-right px-2 py-1 font-medium">TIR %</th>
                        <th className="text-right px-2 py-1 font-medium">Paridad %</th>
                        <th className="text-right px-2 py-1 font-medium">Z-score</th>
                        <th className="text-center px-2 py-1 font-medium">Signal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.slice(0, 15).map(h => (
                        <tr key={h.fecha} className="border-t border-border/30">
                          <td className="px-2 py-1 text-text-muted">{h.fecha}</td>
                          <td className="px-2 py-1 text-right font-mono text-text-primary">{h.price_usd != null ? fmtPrice(h.price_usd) : '—'}</td>
                          <td className="px-2 py-1 text-right font-mono text-accent">{h.tir != null ? h.tir.toFixed(2) + '%' : '—'}</td>
                          <td className="px-2 py-1 text-right font-mono text-text-muted">{h.paridad != null ? h.paridad.toFixed(1) + '%' : '—'}</td>
                          <td className={`px-2 py-1 text-right font-mono ${
                            h.z_score == null ? 'text-text-muted'
                              : h.z_score > 1.5 ? 'text-up'
                              : h.z_score < -1.5 ? 'text-down'
                              : 'text-text-muted'
                          }`}>
                            {h.z_score != null ? (h.z_score >= 0 ? '+' : '') + h.z_score.toFixed(2) : '—'}
                          </td>
                          <td className="px-2 py-1 text-center">
                            <SignalBadge signal={h.signal} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

function DashboardTab({ bonds, spreads, fecha }: {
  bonds: BondAnalysis[]
  spreads: BondSpread[]
  fecha: string
}) {
  const [lawFilter, setLawFilter] = useState<LawFilter>('ALL')

  const filtered = useMemo(() =>
    bonds.filter(b => lawFilter === 'ALL' || b.law === lawFilter),
    [bonds, lawFilter],
  )

  const sorted = useMemo(() =>
    [...filtered].sort((a, b) => {
      const matA = a.maturity || ''
      const matB = b.maturity || ''
      return matA.localeCompare(matB)
    }),
    [filtered],
  )

  const signals = useMemo(() => bonds.filter(b => b.signal === 'BUY' || b.signal === 'SELL'), [bonds])

  return (
    <div className="space-y-5">
      {signals.length > 0 && (
        <div className="card p-4 space-y-2 border-l-4 border-accent">
          <p className="text-xs font-semibold text-text-primary">Senales activas</p>
          {signals.map(s => (
            <div key={s.symbol} className="flex items-center gap-3 text-xs">
              <SignalBadge signal={s.signal} />
              <span className="font-semibold text-text-primary">{s.symbol}</span>
              <span className="text-text-muted">[{s.law}]</span>
              <span className="text-accent font-mono">TIR {s.tir?.toFixed(2)}%</span>
              {s.z_score != null && (
                <span className="text-text-muted font-mono">Z={s.z_score >= 0 ? '+' : ''}{s.z_score.toFixed(2)}</span>
              )}
              {s.avg_tir != null && (
                <span className="text-text-muted">prom {s.avg_tir.toFixed(2)}%</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <div className="flex items-center gap-0 border border-border rounded-md overflow-hidden">
          {([['ALL', 'Todos'], ['ARG', 'Ley ARG'], ['NY', 'Ley NY']] as [LawFilter, string][]).map(([val, label]) => (
            <button
              key={val}
              onClick={() => setLawFilter(val)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                lawFilter === val
                  ? 'bg-accent text-white'
                  : 'bg-surface text-text-muted hover:text-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="text-2xs text-text-muted">{fecha}</span>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-text-muted">
                <th className="text-left px-3 py-2.5 font-medium w-24">Bono</th>
                <th className="text-center px-3 py-2.5 font-medium w-16">Ley</th>
                <th className="text-right px-3 py-2.5 font-medium w-16 hidden sm:table-cell">Vto</th>
                <th className="text-right px-3 py-2.5 font-medium w-20">Precio</th>
                <th className="text-right px-3 py-2.5 font-medium w-20">TIR %</th>
                <th className="text-right px-3 py-2.5 font-medium w-20 hidden md:table-cell">Paridad</th>
                <th className="text-right px-3 py-2.5 font-medium w-16 hidden md:table-cell">DM</th>
                <th className="text-right px-3 py-2.5 font-medium w-20 hidden sm:table-cell">Z-score</th>
                <th className="text-center px-3 py-2.5 font-medium w-28">Senal</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(bond => (
                <BondDetailRow key={bond.symbol} bond={bond} />
              ))}
            </tbody>
          </table>
        </div>

        {sorted.length === 0 && (
          <div className="text-center py-8 text-text-muted text-xs">Sin datos de bonos</div>
        )}
      </div>

      {spreads.length > 0 && (
        <div className="card overflow-hidden">
          <div className="px-3 py-2.5 border-b border-border">
            <p className="text-xs font-semibold text-text-primary">Spreads Ley ARG vs NY</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th className="text-left px-3 py-2.5 font-medium">Par</th>
                  <th className="text-right px-3 py-2.5 font-medium">Spread (bps)</th>
                  <th className="text-right px-3 py-2.5 font-medium hidden sm:table-cell">Prom (bps)</th>
                  <th className="text-right px-3 py-2.5 font-medium hidden sm:table-cell">Z-score</th>
                  <th className="text-center px-3 py-2.5 font-medium">Senal</th>
                </tr>
              </thead>
              <tbody>
                {spreads.map(sp => (
                  <tr key={`${sp.al}-${sp.gd}`} className="border-b border-border/50 hover:bg-elevated/50 transition-colors">
                    <td className="px-3 py-2.5 font-semibold text-text-primary">
                      {sp.al} / {sp.gd}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-accent">
                      {sp.spread_bps?.toFixed(0)}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-text-muted hidden sm:table-cell">
                      {sp.avg_spread != null ? sp.avg_spread.toFixed(0) : '—'}
                    </td>
                    <td className={`px-3 py-2.5 text-right font-mono hidden sm:table-cell ${
                      sp.spread_z == null ? 'text-text-muted'
                        : Math.abs(sp.spread_z) > 1.5 ? 'text-accent' : 'text-text-muted'
                    }`}>
                      {sp.spread_z != null ? (sp.spread_z >= 0 ? '+' : '') + sp.spread_z.toFixed(2) : '—'}
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      {sp.spread_signal === 'AL_CHEAP' ? (
                        <span className="text-2xs font-semibold text-up">AL barato</span>
                      ) : sp.spread_signal === 'GD_CHEAP' ? (
                        <span className="text-2xs font-semibold text-amber-400">GD barato</span>
                      ) : (
                        <span className="text-2xs text-text-muted">NEUTRAL</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function CurveTab({ curve, fecha }: { curve: BondCurvePoint[]; fecha: string }) {
  const argBonds = curve.filter(c => c.law === 'ARG')
  const nyBonds = curve.filter(c => c.law === 'NY')

  const maxTir = Math.max(...curve.map(c => c.tir), 0)
  const minTir = Math.min(...curve.map(c => c.tir), 0)
  const range = maxTir - minTir || 1

  const years = curve.map(c => {
    const d = new Date(c.maturity)
    return d.getFullYear() + (d.getMonth() / 12)
  })
  const minYear = Math.min(...years)
  const maxYear = Math.max(...years)
  const yearRange = maxYear - minYear || 1

  const getX = (maturity: string) => {
    const d = new Date(maturity)
    const y = d.getFullYear() + (d.getMonth() / 12)
    return 60 + ((y - minYear) / yearRange) * 680
  }

  const getY = (tir: number) => {
    return 280 - ((tir - minTir) / range) * 240
  }

  const argPath = argBonds.length >= 2
    ? argBonds.map((b, i) => `${i === 0 ? 'M' : 'L'}${getX(b.maturity)},${getY(b.tir)}`).join(' ')
    : null

  const nyPath = nyBonds.length >= 2
    ? nyBonds.map((b, i) => `${i === 0 ? 'M' : 'L'}${getX(b.maturity)},${getY(b.tir)}`).join(' ')
    : null

  const ticks = Array.from({ length: 5 }, (_, i) => minTir + (range * i) / 4)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-text-primary">
          Curva de rendimiento — TIR vs Vencimiento
        </p>
        <span className="text-2xs text-text-muted">{fecha}</span>
      </div>

      <div className="card p-4">
        <svg viewBox="0 0 800 320" className="w-full h-auto" style={{ minHeight: 220 }}>
          {ticks.map(t => (
            <g key={t}>
              <line x1="60" x2="740" y1={getY(t)} y2={getY(t)} stroke="currentColor" strokeOpacity={0.1} />
              <text x="52" y={getY(t) + 4} textAnchor="end" fill="currentColor" opacity={0.4} fontSize={10}>
                {t.toFixed(1)}%
              </text>
            </g>
          ))}

          {argPath && <path d={argPath} fill="none" stroke="#3b82f6" strokeWidth={2} />}
          {nyPath && <path d={nyPath} fill="none" stroke="#f59e0b" strokeWidth={2} />}

          {curve.map(b => (
            <g key={b.symbol}>
              <circle
                cx={getX(b.maturity)}
                cy={getY(b.tir)}
                r={5}
                fill={b.law === 'ARG' ? '#3b82f6' : '#f59e0b'}
                stroke="currentColor"
                strokeOpacity={0.2}
                strokeWidth={1}
              />
              <text
                x={getX(b.maturity)}
                y={getY(b.tir) - 10}
                textAnchor="middle"
                fill="currentColor"
                opacity={0.7}
                fontSize={9}
              >
                {b.symbol}
              </text>
            </g>
          ))}

          <circle cx={620} cy={10} r={5} fill="#3b82f6" />
          <text x={630} y={14} fill="currentColor" opacity={0.6} fontSize={10}>Ley ARG</text>
          <circle cx={700} cy={10} r={5} fill="#f59e0b" />
          <text x={710} y={14} fill="currentColor" opacity={0.6} fontSize={10}>Ley NY</text>
        </svg>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-text-muted">
                <th className="text-left px-3 py-2.5 font-medium">Bono</th>
                <th className="text-center px-3 py-2.5 font-medium">Ley</th>
                <th className="text-right px-3 py-2.5 font-medium">Vto</th>
                <th className="text-right px-3 py-2.5 font-medium">TIR %</th>
                <th className="text-right px-3 py-2.5 font-medium">Paridad %</th>
                <th className="text-right px-3 py-2.5 font-medium">DM</th>
              </tr>
            </thead>
            <tbody>
              {curve.map(b => (
                <tr key={b.symbol} className="border-b border-border/50 hover:bg-elevated/50 transition-colors">
                  <td className="px-3 py-2.5 font-semibold text-text-primary">{b.symbol}</td>
                  <td className="px-3 py-2.5 text-center">
                    <span className={`text-2xs px-1.5 py-0.5 rounded font-medium ${
                      b.law === 'ARG' ? 'bg-blue-500/15 text-blue-400' : 'bg-amber-500/15 text-amber-400'
                    }`}>{b.law}</span>
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-muted">{b.maturity?.slice(0, 4)}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-accent font-medium">{b.tir?.toFixed(2)}%</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-muted">{b.paridad != null ? b.paridad.toFixed(1) + '%' : '—'}</td>
                  <td className="px-3 py-2.5 text-right font-mono text-text-muted">{b.duration_mod != null ? b.duration_mod.toFixed(2) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function SpreadsTab({ pairs }: { pairs: SpreadPair[] }) {
  const [selected, setSelected] = useState(0)
  const pair = pairs[selected]

  if (!pairs.length) {
    return <div className="text-center py-8 text-text-muted text-xs">Sin historial de spreads</div>
  }

  const history = pair?.history || []
  const reversed = [...history].reverse()

  const maxSpread = Math.max(...reversed.map(h => h.spread_bps), 0)
  const minSpread = Math.min(...reversed.map(h => h.spread_bps), 0)
  const range = maxSpread - minSpread || 1

  const chartW = 700
  const chartH = 200
  const padL = 60
  const padR = 20
  const padT = 20
  const padB = 30

  const getX = (i: number) => padL + (i / Math.max(reversed.length - 1, 1)) * (chartW - padL - padR)
  const getY = (v: number) => padT + ((maxSpread - v) / range) * (chartH - padT - padB)

  const path = reversed.length >= 2
    ? reversed.map((h, i) => `${i === 0 ? 'M' : 'L'}${getX(i)},${getY(h.spread_bps)}`).join(' ')
    : null

  const avgSpread = reversed.length > 0
    ? reversed.reduce((s, h) => s + h.spread_bps, 0) / reversed.length
    : 0

  const ticks = Array.from({ length: 5 }, (_, i) => minSpread + (range * i) / 4)

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <p className="text-xs font-semibold text-text-primary">Spreads AL vs GD (bps)</p>
        <div className="flex gap-0 border border-border rounded-md overflow-hidden">
          {pairs.map((p, i) => (
            <button
              key={i}
              onClick={() => setSelected(i)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                selected === i
                  ? 'bg-accent text-white'
                  : 'bg-surface text-text-muted hover:text-text-primary'
              }`}
            >
              {p.al}/{p.gd}
            </button>
          ))}
        </div>
      </div>

      <div className="card p-4">
        <svg viewBox={`0 0 ${chartW} ${chartH}`} className="w-full h-auto" style={{ minHeight: 180 }}>
          {ticks.map(t => (
            <g key={t}>
              <line x1={padL} x2={chartW - padR} y1={getY(t)} y2={getY(t)} stroke="currentColor" strokeOpacity={0.1} />
              <text x={padL - 6} y={getY(t) + 4} textAnchor="end" fill="currentColor" opacity={0.4} fontSize={9}>
                {t.toFixed(0)}
              </text>
            </g>
          ))}

          <line
            x1={padL} x2={chartW - padR}
            y1={getY(avgSpread)} y2={getY(avgSpread)}
            stroke="#f59e0b" strokeWidth={1} strokeDasharray="4,3" opacity={0.6}
          />
          <text x={chartW - padR + 4} y={getY(avgSpread) + 3} fill="#f59e0b" fontSize={8} opacity={0.8}>
            prom {avgSpread.toFixed(0)}
          </text>

          {path && <path d={path} fill="none" stroke="#3b82f6" strokeWidth={1.5} />}

          {reversed.length > 0 && (
            <>
              <text x={padL} y={chartH - 4} fill="currentColor" opacity={0.3} fontSize={8}>
                {reversed[0].fecha}
              </text>
              <text x={chartW - padR} y={chartH - 4} textAnchor="end" fill="currentColor" opacity={0.3} fontSize={8}>
                {reversed[reversed.length - 1].fecha}
              </text>
            </>
          )}
        </svg>
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto max-h-[300px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-border text-text-muted">
                <th className="text-left px-3 py-2.5 font-medium">Fecha</th>
                <th className="text-right px-3 py-2.5 font-medium">TIR {pair.al}</th>
                <th className="text-right px-3 py-2.5 font-medium">TIR {pair.gd}</th>
                <th className="text-right px-3 py-2.5 font-medium">Spread (bps)</th>
              </tr>
            </thead>
            <tbody>
              {history.map(h => (
                <tr key={h.fecha} className="border-b border-border/50 hover:bg-elevated/50 transition-colors">
                  <td className="px-3 py-2 text-text-muted">{h.fecha}</td>
                  <td className="px-3 py-2 text-right font-mono text-text-primary">{h.al_tir.toFixed(2)}%</td>
                  <td className="px-3 py-2 text-right font-mono text-text-primary">{h.gd_tir.toFixed(2)}%</td>
                  <td className="px-3 py-2 text-right font-mono text-accent font-medium">{h.spread_bps.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function Bonos() {
  const [tab, setTab] = useState<Tab>('dashboard')
  const [loading, setLoading] = useState(false)

  const [bonds, setBonds] = useState<BondAnalysis[]>([])
  const [spreads, setSpreads] = useState<BondSpread[]>([])
  const [fecha, setFecha] = useState('')

  const [curve, setCurve] = useState<BondCurvePoint[]>([])
  const [curveFecha, setCurveFecha] = useState('')

  const [pairs, setPairs] = useState<SpreadPair[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      if (tab === 'dashboard') {
        const res = await api.bondsDashboard()
        setBonds(res.bonds)
        setSpreads(res.spreads)
        setFecha(res.fecha)
      } else if (tab === 'curve') {
        const res = await api.bondsCurve()
        setCurve(res.curve)
        setCurveFecha(res.fecha)
      } else if (tab === 'spreads') {
        const res = await api.bondsSpreads()
        setPairs(res.pairs)
      }
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-text-primary">Bonos Argentinos</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Bonos soberanos USD — precios BYMA, TIR, Z-score y senales
          </p>
        </div>
        <button className="btn-ghost text-xs gap-1.5" onClick={() => load()}>
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          Actualizar
        </button>
      </div>

      <div className="flex items-center gap-0 border border-border rounded-md overflow-hidden w-fit">
        {([
          ['dashboard', 'Dashboard'],
          ['curve', 'Curva TIR'],
          ['spreads', 'Spreads'],
        ] as [Tab, string][]).map(([val, label]) => (
          <button
            key={val}
            onClick={() => setTab(val)}
            className={`px-4 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
              tab === val
                ? 'bg-accent text-white'
                : 'bg-surface text-text-muted hover:text-text-primary'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {loading && bonds.length === 0 && curve.length === 0 && pairs.length === 0 ? (
        <div className="card p-8 text-center">
          <RefreshCw size={20} className="animate-spin mx-auto text-text-muted mb-2" />
          <p className="text-xs text-text-muted">Cargando datos de BYMA...</p>
        </div>
      ) : (
        <>
          {tab === 'dashboard' && <DashboardTab bonds={bonds} spreads={spreads} fecha={fecha} />}
          {tab === 'curve' && <CurveTab curve={curve} fecha={curveFecha} />}
          {tab === 'spreads' && <SpreadsTab pairs={pairs} />}
        </>
      )}
    </div>
  )
}
