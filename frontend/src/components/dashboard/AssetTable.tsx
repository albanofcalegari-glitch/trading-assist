import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { fmtPrice, fmtPct, fmtVol, pctClass } from '@/lib/utils'
import type { Asset } from '@/lib/api'

interface Props {
  items:   Asset[]
  total:   number
  page:    number
  pages:   number
  onPage:  (p: number) => void
  loading?: boolean
}

// `hideOnMobile` oculta la columna en pantallas chicas usando `hidden md:table-cell`
const COLS = [
  { key: 'simbolo',    label: 'Símbolo',  cls: 'w-20 md:w-28',                    hideOnMobile: false },
  { key: 'nombre',     label: 'Empresa',  cls: 'min-w-0 hidden md:table-cell',    hideOnMobile: true  },
  { key: 'mercado',    label: 'Mercado',  cls: 'w-20 md:w-28 text-center hidden sm:table-cell', hideOnMobile: true },
  { key: 'precio',     label: 'Precio',   cls: 'w-20 md:w-24 text-right',         hideOnMobile: false },
  { key: 'pct_cambio', label: 'Cambio',   cls: 'w-20 md:w-24 text-right',         hideOnMobile: false },
  { key: 'volumen',    label: 'Volumen',  cls: 'w-24 text-right hidden lg:table-cell', hideOnMobile: true },
]

export default function AssetTable({ items, total, page, pages, onPage, loading }: Props) {
  const navigate = useNavigate()

  return (
    <div className="card overflow-hidden">
      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              {COLS.map(c => (
                <th key={c.key} className={`px-4 py-2.5 text-left table-header ${c.cls}`}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 10 }).map((_, i) => (
                <tr key={i} className="border-b border-border-subtle">
                  {COLS.map(c => (
                    <td key={c.key} className="px-4 py-3">
                      <div className="h-4 rounded bg-elevated animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-10 text-center text-sm text-text-muted">
                  Sin resultados
                </td>
              </tr>
            ) : (
              items.map(a => (
                <tr
                  key={a.accion_id}
                  className="table-row cursor-pointer group"
                  onClick={() => navigate(`/asset/${a.accion_id}`)}
                >
                  {/* Símbolo + (en móvil) nombre debajo */}
                  <td className="px-2 md:px-4 py-2.5">
                    <span className="font-mono font-semibold text-sm text-text-primary
                                     group-hover:text-accent transition-colors">
                      {a.simbolo}
                    </span>
                    <p className="md:hidden text-2xs text-text-muted truncate">{a.nombre}</p>
                  </td>
                  {/* Empresa — desktop */}
                  <td className="px-4 py-2.5 max-w-0 hidden md:table-cell">
                    <p className="text-sm text-text-secondary truncate">{a.nombre}</p>
                  </td>
                  {/* Mercado — sm+ */}
                  <td className="px-4 py-2.5 text-center hidden sm:table-cell">
                    <span className="badge badge-neutral">{a.mercado}</span>
                  </td>
                  {/* Precio */}
                  <td className="px-2 md:px-4 py-2.5 text-right">
                    <span className="font-mono text-sm text-text-primary">{fmtPrice(a.precio)}</span>
                  </td>
                  {/* Cambio */}
                  <td className="px-2 md:px-4 py-2.5 text-right">
                    <span className={`font-mono text-sm font-medium ${pctClass(a.pct_cambio)}`}>
                      {fmtPct(a.pct_cambio)}
                    </span>
                  </td>
                  {/* Volumen — lg+ */}
                  <td className="px-4 py-2.5 text-right hidden lg:table-cell">
                    <span className="font-mono text-xs text-text-secondary">
                      {fmtVol(a.volumen)}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Paginación */}
      {pages > 1 && (
        <div className="flex items-center justify-between px-4 py-2.5 border-t border-border">
          <span className="text-xs text-text-muted">
            {total.toLocaleString()} activos · pág. {page + 1} / {pages}
          </span>
          <div className="flex items-center gap-0.5">
            <button
              className="btn-ghost h-7 w-7 p-0 flex items-center justify-center"
              disabled={page === 0}
              onClick={() => onPage(0)}
            >
              <ChevronsLeft size={14} />
            </button>
            <button
              className="btn-ghost h-7 w-7 p-0 flex items-center justify-center"
              disabled={page === 0}
              onClick={() => onPage(page - 1)}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              className="btn-ghost h-7 w-7 p-0 flex items-center justify-center"
              disabled={page >= pages - 1}
              onClick={() => onPage(page + 1)}
            >
              <ChevronRight size={14} />
            </button>
            <button
              className="btn-ghost h-7 w-7 p-0 flex items-center justify-center"
              disabled={page >= pages - 1}
              onClick={() => onPage(pages - 1)}
            >
              <ChevronsRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
