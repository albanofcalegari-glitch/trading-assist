/**
 * FundamentalsPanel — métricas financieras puras (separadas de CompanyInfoPanel
 * que es perfil + scoring de salud).
 *
 * Datos: yfinance via /api/assets/<id>/fundamentals (cache 6h server-side).
 *
 * Layout: grid compacto en 4 grupos:
 *   1. Tamaño y resultados (revenue/net income/market cap)
 *   2. Márgenes (gross/operating/profit)
 *   3. Balance (cash/debt/D-E)
 *   4. Valuación + dividendos + próximos earnings
 */

import { useEffect, useState } from 'react'
import { DollarSign, Percent, Scale, BarChart3, CalendarClock, ChevronDown, ChevronRight } from 'lucide-react'
import { api, type Fundamentals } from '@/lib/api'

const COLLAPSE_KEY = 'ta:fundamentals:collapsed'

interface Props {
  accionId: number
}

export default function FundamentalsPanel({ accionId }: Props) {
  const [data, setData]           = useState<Fundamentals | null>(null)
  const [loading, setLoading]     = useState(true)
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) !== '0' } catch { return true }
  })

  useEffect(() => {
    if (!accionId) return
    setLoading(true)
    setData(null)
    api.fundamentals(accionId)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [accionId])

  const toggle = () => {
    setCollapsed(v => {
      const next = !v
      try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0') } catch {}
      return next
    })
  }

  // Header compartido — siempre clickeable, muestra chevron según estado
  const Header = ({ rightSlot }: { rightSlot?: React.ReactNode }) => (
    <button
      type="button"
      onClick={toggle}
      className="w-full flex items-center gap-2 text-left hover:bg-elevated/40 rounded-sm px-1 -mx-1 py-0.5 transition-colors"
    >
      {collapsed ? <ChevronRight size={14} className="text-text-muted" />
                 : <ChevronDown  size={14} className="text-text-muted" />}
      <BarChart3 size={14} className="text-accent" />
      <h3 className="text-sm font-semibold text-text-primary">Fundamentals</h3>
      {rightSlot && <span className="ml-auto">{rightSlot}</span>}
    </button>
  )

  if (loading) {
    return (
      <div className="card p-3">
        <Header />
        {!collapsed && <p className="text-xs text-text-muted mt-2">Cargando fundamentals...</p>}
      </div>
    )
  }

  if (!data) {
    return (
      <div className="card p-3">
        <Header />
        {!collapsed && <p className="text-xs text-text-muted mt-2">Sin datos fundamentales disponibles</p>}
      </div>
    )
  }

  const cur = data.currency || 'USD'

  if (collapsed) {
    return (
      <div className="card p-3">
        <Header rightSlot={<span className="text-2xs text-text-muted">{cur}</span>} />
      </div>
    )
  }

  return (
    <div className="card p-4 md:p-5">
      <div className="mb-3">
        <Header rightSlot={<span className="text-2xs text-text-muted">{cur}</span>} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {/* Tamaño & resultados */}
        <Group icon={<DollarSign size={11} />} title="Tamaño y resultados">
          <Row label="Market cap"   value={fmtMoney(data.market_cap, cur)} />
          <Row label="Revenue TTM"  value={fmtMoney(data.revenue_ttm, cur)} />
          <Row label="Net income"   value={fmtMoney(data.net_income_ttm, cur)} />
        </Group>

        {/* Márgenes */}
        <Group icon={<Percent size={11} />} title="Márgenes">
          <Row label="Bruto"        value={fmtPct(data.gross_margin)} cls={pctClass(data.gross_margin)} />
          <Row label="Operativo"    value={fmtPct(data.operating_margin)} cls={pctClass(data.operating_margin)} />
          <Row label="Neto"         value={fmtPct(data.profit_margin)} cls={pctClass(data.profit_margin)} />
        </Group>

        {/* Balance */}
        <Group icon={<Scale size={11} />} title="Balance">
          <Row label="Cash"         value={fmtMoney(data.total_cash, cur)} />
          <Row label="Debt"         value={fmtMoney(data.total_debt, cur)} />
          <Row label="D/E"          value={fmtNum(data.debt_to_equity, 2)} cls={data.debt_to_equity != null && data.debt_to_equity > 2 ? 'text-down' : ''} />
        </Group>

        {/* Valuación */}
        <Group icon={<BarChart3 size={11} />} title="Valuación">
          <Row label="PE trailing"  value={fmtNum(data.trailing_pe, 1)} />
          <Row label="PE forward"   value={fmtNum(data.forward_pe, 1)} />
          <Row label="P/B"          value={fmtNum(data.price_to_book, 2)} />
        </Group>
      </div>

      {/* Crecimiento, dividendos, fechas */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t border-border">
        <Group icon={<Percent size={11} />} title="Crecimiento YoY">
          <Row label="Revenue"      value={fmtPct(data.revenue_growth_yoy)}  cls={pctClass(data.revenue_growth_yoy)} />
          <Row label="Earnings"     value={fmtPct(data.earnings_growth_yoy)} cls={pctClass(data.earnings_growth_yoy)} />
          <Row label="EV/EBITDA"    value={fmtNum(data.ev_to_ebitda, 1)} />
        </Group>

        <Group icon={<DollarSign size={11} />} title="Dividendos">
          <Row label="Yield"        value={fmtPct(data.dividend_yield)} />
          <Row label="Tasa anual"   value={fmtMoney(data.dividend_rate, cur)} />
        </Group>

        <Group icon={<CalendarClock size={11} />} title="Próximos earnings">
          <Row label="Próximo"      value={data.next_earnings_date || '—'} />
          <Row label="Último FY"    value={data.last_earnings_date || '—'} />
        </Group>

        <div className="text-2xs text-text-muted self-end">
          {data.updated_at && (
            <p>Actualizado {timeAgo(data.updated_at)}</p>
          )}
        </div>
      </div>
    </div>
  )
}

function Group({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-2xs text-text-muted uppercase tracking-wider mb-2">
        {icon} {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ label, value, cls = '' }: { label: string; value: string; cls?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-2xs text-text-secondary">{label}</span>
      <span className={`text-xs font-mono text-text-primary ${cls}`}>{value}</span>
    </div>
  )
}

// ── helpers ──────────────────────────────────────────────────────────────────

function fmtMoney(v: number | null, currency = 'USD'): string {
  if (v == null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e12) return `${(v / 1e12).toFixed(2)}T`
  if (abs >= 1e9)  return `${(v / 1e9).toFixed(2)}B`
  if (abs >= 1e6)  return `${(v / 1e6).toFixed(2)}M`
  if (abs >= 1e3)  return `${(v / 1e3).toFixed(2)}K`
  return `${v.toFixed(2)} ${currency === 'USD' ? '' : currency}`.trim()
}

function fmtPct(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function fmtNum(v: number | null, decimals = 2): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function pctClass(v: number | null | undefined): string {
  if (v == null) return ''
  return v >= 0 ? 'text-up' : 'text-down'
}

function timeAgo(epochSec: number): string {
  const diffMs = Date.now() - epochSec * 1000
  const min  = Math.floor(diffMs / 60000)
  if (min < 1) return 'recién'
  if (min < 60) return `hace ${min} min`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `hace ${hr}h`
  return `hace ${Math.floor(hr / 24)}d`
}
