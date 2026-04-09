import { useState } from 'react'
import {
  Building2, Globe, MapPin, Users as UsersIcon,
  Activity, TrendingUp, DollarSign, ChevronDown, ChevronUp,
} from 'lucide-react'
import type { CompanyInfo } from '@/lib/api'

interface Props {
  data: CompanyInfo | null
  loading: boolean
}

export default function CompanyInfoPanel({ data, loading }: Props) {
  const [expanded, setExpanded] = useState(false)

  if (loading) {
    return (
      <div className="card p-4">
        <p className="text-xs text-text-muted">Cargando info de la empresa...</p>
      </div>
    )
  }

  if (!data || data.status !== 'OK') {
    return (
      <div className="card p-4">
        <p className="text-xs text-text-muted">Sin información fundamental disponible</p>
      </div>
    )
  }

  const profile   = data.profile   || {}
  const health    = data.health    || {}
  const growth    = data.growth    || {}
  const valuation = data.valuation || {}
  const analyst   = data.analyst   || {}

  const healthColor =
    health.score == null      ? 'text-text-muted'
    : health.score >= 70      ? 'text-up'
    : health.score >= 45      ? 'text-warn'
    :                           'text-down'

  const healthBg =
    health.score == null      ? 'bg-surface border-border'
    : health.score >= 70      ? 'bg-up/10 border-up/30'
    : health.score >= 45      ? 'bg-warn/10 border-warn/30'
    :                           'bg-down/10 border-down/30'

  const lastBalance = data.income_statements?.[0]
  const prevBalance = data.income_statements?.[1]
  const revenueDelta =
    lastBalance && prevBalance && prevBalance.total_revenue && lastBalance.total_revenue
      ? (lastBalance.total_revenue / prevBalance.total_revenue - 1) * 100
      : null
  const niDelta =
    lastBalance && prevBalance && prevBalance.net_income && lastBalance.net_income
      ? (lastBalance.net_income / prevBalance.net_income - 1) * 100
      : null

  return (
    <div className="card p-4 space-y-4">
      {/* Header empresa + score */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Building2 size={14} className="text-text-muted shrink-0" />
            <p className="text-sm font-semibold text-text-primary truncate">
              {profile.long_name || data.symbol}
            </p>
          </div>
          <div className="flex items-center gap-3 mt-1 flex-wrap">
            {profile.sector && (
              <span className="text-2xs text-text-secondary">{profile.sector}</span>
            )}
            {profile.industry && (
              <span className="text-2xs text-text-muted">· {profile.industry}</span>
            )}
            {profile.country && (
              <span className="text-2xs text-text-muted flex items-center gap-1">
                <MapPin size={10} /> {profile.country}
              </span>
            )}
            {profile.employees != null && (
              <span className="text-2xs text-text-muted flex items-center gap-1">
                <UsersIcon size={10} /> {fmtCompact(profile.employees)} empleados
              </span>
            )}
            {profile.website && (
              <a
                href={profile.website}
                target="_blank"
                rel="noreferrer noopener"
                className="text-2xs text-accent hover:underline flex items-center gap-1"
              >
                <Globe size={10} /> sitio
              </a>
            )}
          </div>
        </div>

        {/* Health score */}
        {health.score != null && (
          <div className={`text-right px-3 py-1.5 rounded-md border ${healthBg} shrink-0`}>
            <p className="text-2xs text-text-muted uppercase tracking-wide">Salud</p>
            <p className={`font-mono text-lg font-semibold leading-none mt-0.5 ${healthColor}`}>
              {health.score}
            </p>
            <p className={`text-2xs ${healthColor} capitalize`}>{health.label}</p>
          </div>
        )}
      </div>

      {/* Métricas principales: salud, crecimiento, valuación */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-3 border-t border-border">
        <Section title="Salud financiera" icon={<Activity size={11} />}>
          <Metric label="Margen neto" value={fmtPct(health.profit_margin)} />
          <Metric label="ROE"          value={fmtPct(health.roe)} />
          <Metric label="Deuda/Equity" value={fmtRatio(health.debt_to_equity, true)} />
          <Metric label="Liquidez"     value={fmtRatio(health.current_ratio)} />
        </Section>

        <Section title="Crecimiento" icon={<TrendingUp size={11} />}>
          <Metric label="Revenue YoY"  value={fmtPct(growth.revenue_growth)}  highlight />
          <Metric label="Earnings YoY" value={fmtPct(growth.earnings_growth)} highlight />
        </Section>

        <Section title="Valuación" icon={<DollarSign size={11} />}>
          <Metric label="P/E"         value={fmtRatio(valuation.trailing_pe)} />
          <Metric label="P/E fwd"     value={fmtRatio(valuation.forward_pe)} />
          <Metric label="PEG"         value={fmtRatio(valuation.peg_ratio)} />
          <Metric label="P/B"         value={fmtRatio(valuation.price_to_book)} />
        </Section>

        <Section title="Analistas">
          <Metric label="Recomendación"
                  value={analyst.recommendation ? analyst.recommendation.toUpperCase() : '—'}
                  highlight />
          <Metric label="Target medio" value={fmtMoney(analyst.target_mean_price)} />
          <Metric label="N° analistas" value={analyst.number_of_analysts != null
            ? String(analyst.number_of_analysts) : '—'} />
          <Metric label="Market cap"   value={fmtCompact(valuation.market_cap)} />
        </Section>
      </div>

      {/* Último balance */}
      {lastBalance && (
        <div className="pt-3 border-t border-border">
          <div className="flex items-center justify-between mb-2">
            <p className="text-2xs uppercase tracking-wide text-text-muted">
              Último balance {lastBalance.end_date ? `· ${lastBalance.end_date}` : ''}
            </p>
            <button
              onClick={() => setExpanded(v => !v)}
              className="text-2xs text-accent hover:underline flex items-center gap-1"
            >
              {expanded ? <>Menos <ChevronUp size={11} /></> : <>Más detalle <ChevronDown size={11} /></>}
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <BalanceMetric label="Revenue"     value={fmtCompact(lastBalance.total_revenue)} delta={revenueDelta} />
            <BalanceMetric label="Beneficio bruto" value={fmtCompact(lastBalance.gross_profit)} />
            <BalanceMetric label="Op. income"  value={fmtCompact(lastBalance.operating_income)} />
            <BalanceMetric label="Net income"  value={fmtCompact(lastBalance.net_income)} delta={niDelta} />
          </div>

          {expanded && (
            <>
              {data.earnings_yearly && data.earnings_yearly.length > 0 && (
                <div className="mt-4">
                  <p className="text-2xs uppercase tracking-wide text-text-muted mb-2">
                    Histórico anual
                  </p>
                  <div className="overflow-x-auto">
                    <table className="w-full text-2xs font-mono">
                      <thead>
                        <tr className="text-text-muted border-b border-border-subtle">
                          <th className="text-left py-1">Año</th>
                          <th className="text-right py-1">Revenue</th>
                          <th className="text-right py-1">Earnings</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.earnings_yearly.slice().reverse().map((y, i) => (
                          <tr key={i} className="border-b border-border-subtle/50 last:border-0">
                            <td className="py-1 text-text-secondary">{y.year ?? '—'}</td>
                            <td className="py-1 text-right text-text-primary">{fmtCompact(y.revenue)}</td>
                            <td className="py-1 text-right text-text-primary">{fmtCompact(y.earnings)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {profile.description && (
                <div className="mt-4">
                  <p className="text-2xs uppercase tracking-wide text-text-muted mb-2">
                    Sobre la empresa
                  </p>
                  <p className="text-2xs text-text-secondary leading-relaxed line-clamp-6">
                    {profile.description}
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── Subcomponentes ─────────────────────────────────────────────────────────────

function Section({ title, icon, children }: {
  title: string; icon?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-2xs uppercase tracking-wide text-text-muted flex items-center gap-1">
        {icon}{title}
      </p>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Metric({ label, value, highlight }: {
  label: string; value: string; highlight?: boolean
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-2xs text-text-muted">{label}</span>
      <span className={`font-mono text-xs ${highlight ? 'text-text-primary font-medium' : 'text-text-secondary'}`}>
        {value}
      </span>
    </div>
  )
}

function BalanceMetric({ label, value, delta }: {
  label: string; value: string; delta?: number | null
}) {
  return (
    <div>
      <p className="text-2xs text-text-muted">{label}</p>
      <p className="font-mono text-sm font-medium text-text-primary">{value}</p>
      {delta != null && (
        <p className={`text-2xs ${delta >= 0 ? 'text-up' : 'text-down'}`}>
          {delta >= 0 ? '+' : ''}{delta.toFixed(1)}% YoY
        </p>
      )}
    </div>
  )
}

// ── Formatters ─────────────────────────────────────────────────────────────────

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function fmtRatio(v: number | null | undefined, normalizePct = false): string {
  if (v == null) return '—'
  const x = normalizePct && v > 5 ? v / 100 : v
  return x.toFixed(2)
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return '—'
  return `$${v.toFixed(2)}`
}

function fmtCompact(v: number | null | undefined): string {
  if (v == null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (abs >= 1e9)  return `$${(v / 1e9).toFixed(2)}B`
  if (abs >= 1e6)  return `$${(v / 1e6).toFixed(2)}M`
  if (abs >= 1e3)  return `$${(v / 1e3).toFixed(1)}K`
  return `$${v.toFixed(0)}`
}
